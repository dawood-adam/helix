"""The ``helix`` CLI (HELIX.md §9.0, §9.1, §9.7, §9.10, §11.1).

The friction floor is the queue + seven verbs (§9.0). Everything else
is a power-user accelerator. This module is thin glue over the wired
core (steps 1-4) via the :class:`~helix.app.Helix` facade.

Honesty (matching §12's correction): where a downstream layer is not
yet built — the Explore agent (step 6), the workflow gates (step 9),
the Watcher (step 13) — the command says so plainly instead of faking
a result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from helix.app import Helix
from helix.project import LADDER, LadderError
from helix.queue import (Queue, cosign_provider, explore_fyi_provider,
                         loom_fyi_provider, maintainer_fyi_provider,
                         watcher_fyi_provider, workflow_gate_provider)
from helix.routing import RoutingError


def _app(ctx) -> Helix:
    return ctx.obj


def _build_queue(app: Helix) -> Queue:
    q = Queue(app)
    q.register(workflow_gate_provider)      # NEEDS YOU NOW (real, step 9)
    q.register(cosign_provider)             # PI co-sign attestation (§13)
    q.register(explore_fyi_provider)
    q.register(loom_fyi_provider)           # abandoned-without-salvage
    q.register(maintainer_fyi_provider)     # promotion-as-suggestion (§9.4)
    q.register(watcher_fyi_provider)        # passive enrichment (§5.1)
    return q


def _render_queue(app: Helix, *, opened: bool = True,
                  project: Optional[str] = None) -> None:
    if not app.is_set_up:
        click.echo("Helix isn't set up yet. Run:  helix setup")
        return
    from helix.catchup import CatchUp
    from helix.notify import triage

    q = _build_queue(app)
    cu = CatchUp(app)
    # §9.6: opening the queue after >24h idle leads with a per-project
    # catch-me-up digest (same renderer as §7 — free, can't drift).
    # When filtered to one project, scope the digest to it too.
    if opened and cu.is_idle_reentry():
        names = ([project] if project else cu.all_active())
        digests = [d for d in (cu.project_digest(p) for p in names) if d]
        if digests:
            click.echo("Catch me up (you've been away):")
            for d in digests:
                click.echo(f"  • {d}")
            click.echo("")
    # §9.5: one badge; blocking pushes vs one batched digest.
    tr = triage(q.collect(project),
                quiet_hours_enabled=str(app.config_get("quiet_hours")
                                        or "on") != "off")
    click.echo(tr.summary())
    click.echo("")
    click.echo(q.render(project), nl=False)
    if opened and not project:
        cu.mark_opened()    # advancing the cursor is what 'open' means


class HelixGroup(click.Group):
    """``helix <project>`` dispatches to ``act`` when the first token
    is not a known command (§9.0: ``helix <project>``)."""

    def resolve_command(self, ctx, args):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            if args and not args[0].startswith("-"):
                act = super().get_command(ctx, "act")
                return "act", act, args
            raise


@click.group(cls=HelixGroup, invoke_without_command=True)
@click.option("--home", type=click.Path(), default=None,
              help="Helix home (default $HELIX_HOME or ~/.helix).")
@click.pass_context
def cli(ctx: click.Context, home: Optional[str]) -> None:
    """Helix — Git for research projects, with a second brain underneath."""
    ctx.obj = Helix(home=Path(home) if home else None)
    if ctx.invoked_subcommand is None:
        _render_queue(ctx.obj)


# ---- setup (§11.1 / Appendix A.2) ----------------------------------


_STARTER_ATLAS_MD = """# ATLAS.md — the Atlas schema contract

This file tells agents how to maintain Atlas. It co-evolves with use.

- **Folder layout**: concepts/ entities/ methods/ sources/ raw/
  scratch/ projects/ archive/ (HELIX.md §6.1).
- **Identity is the frontmatter `id` (a uuid), never the path** (§6.2).
- All agent writes go through the single ordered write queue (§6.4.1).
- Status tiers: scratch · active · canonical · published · archived.
- Decision log JSON is canonical; the narrative is generated (§7.2).
"""


@cli.command()
@click.option("--model", "model_ref", default=None,
              help='The one decision: a "provider:model" (e.g. '
                   '"anthropic:claude-sonnet-4.6" or "local:qwen2.5:32b").')
@click.option("--force", is_flag=True, help="Re-run even if already set up.")
@click.pass_context
def setup(ctx: click.Context, model_ref: Optional[str], force: bool) -> None:
    """Zero-integration bootstrap — asks exactly one thing (§A.2)."""
    app = _app(ctx)
    if app.is_set_up and not force:
        click.echo(f"Already set up ({app.models_path}). "
                   f"Use --force to re-run.")
        return
    if not model_ref:
        click.echo("How should Helix run models?")
        click.echo("  1) paste an API key   2) use a local model")
        model_ref = click.prompt(
            'Enter a "provider:model"', default="anthropic:claude-sonnet-4.6"
        )
    from helix.routing import ModelRef, default_config_toml

    try:
        ModelRef.parse(model_ref)  # fail-closed: change nothing if invalid
    except ValueError as e:
        raise click.ClickException(f"{e} — nothing was changed.")
    app.home.mkdir(parents=True, exist_ok=True)
    app.models_path.write_text(default_config_toml(model_ref))
    app.atlas_root.mkdir(parents=True, exist_ok=True)
    atlas_md = app.atlas_root / "ATLAS.md"
    if not atlas_md.exists():
        atlas_md.write_text(_STARTER_ATLAS_MD)
    _git_init(app.atlas_root)
    click.echo(f"Ready. Atlas: {app.atlas_root}")
    click.echo(f"       Models: {model_ref}  (change: helix model use ...)")
    from helix.upgrades import status_lines
    click.echo("Available upgrades (opt-in, off the critical path) — "
               "`helix upgrades`:")
    for ln in status_lines():
        click.echo(ln)
    click.echo('Next:  helix think "<your question>"')


def _git_init(root: Path) -> None:
    import subprocess

    if (root / ".git").exists():
        return
    try:
        subprocess.run(["git", "init", "-q", str(root)], check=True,
                        capture_output=True)
        gi = root / ".gitignore"
        if not gi.exists():
            gi.write_text(".helix/*.tmp\n*.tmp\n")
    except (OSError, subprocess.CalledProcessError):
        click.echo("(note: git not available — Atlas is not version-"
                   "tracked yet; install git and run `git init`.)")


# ---- Think -> Forge (§9.10) ----------------------------------------


@cli.command()
@click.argument("topic", required=False)
@click.pass_context
def think(ctx: click.Context, topic: Optional[str]) -> None:
    """Open, ticket-free exploration — no queue items, no gates (§9.10)."""
    app = _app(ctx)
    if not topic:
        click.echo("Think is your ticket-free space. Give it a topic:")
        click.echo('  helix think "synthetic CT for bowel length"')
        return
    from helix.atlas.writequeue import Intent

    try:
        r = app.wq.submit(Intent(op="create", payload={
            "type": "scratch", "title": topic, "status": "scratch",
            "body": f"# {topic}\n\nThinking space — no commitments yet."}))
        handle = r.handle
    except ValueError:
        from helix.ids import make_handle

        handle = make_handle("scratch", topic)
        click.echo("(already in Think — reusing that page)")
    click.echo(f'Noted in Think (ticket-free): "{topic}"')
    click.echo(f"  scratch page: {handle}")
    click.echo("Nothing is blocked on you; this created no queue item.")
    click.echo(f'Commit it when ready:  helix init <name> --from-think')


@cli.command()
@click.argument("query")
@click.option("--scope", default=None, help="Extra scope terms.")
@click.option("--limit", default=12, show_default=True,
              help="Max papers to ingest.")
@click.option("--model", "model_override", default=None,
              help="One-shot model override for this run (§11.2).")
@click.pass_context
def explore(ctx, query, scope, limit, model_override):
    """One-shot literature scan — writes to Notes, no gates (§9.10)."""
    app = _app(ctx)
    from helix.explore import ExploreError

    try:
        result = app.explorer().run(
            query, scope=scope, limit=limit,
            model_override=model_override,
        )
    except ExploreError as e:
        # Fail closed (§11.2 / no fake success): say what went wrong,
        # fabricate nothing.
        raise click.ClickException(str(e))
    click.echo(f'Explore done: "{query}"  ·  model: {result.model}')
    click.echo(f"  {result.paper_count} papers → Notes (scratch)"
               + (f", {result.skipped} already known" if result.skipped
                  else ""))
    if result.gaps:
        click.echo(f"  gaps: {', '.join(result.gaps)}")
    click.echo("Ticket-free: no gate, no notification. It's in the queue "
               "as FYI.")
    click.echo(f"Commit it:  helix init <name> --from-think")


@cli.command()
@click.argument("name")
@click.option("--from-think", is_flag=True, help="Seed from Think context.")
@click.option("--tier", type=click.Choice(["notes", "project"]),
              default="notes", help="Starting rung (default: notes).")
@click.option("--at", "at_path", default=None,
              help="Intended location (§9.10), recorded as project "
                   "metadata; tree relocation is not yet implemented.")
@click.option("--private", is_flag=True, help="Strict privacy (§9.9).")
@click.option("--pi", "pi", default="",
              help="Require this PI to co-sign high-stakes decisions "
                   "(§13 attestation; opt-in).")
@click.pass_context
def init(ctx, name, from_think, tier, at_path, private, pi):
    """Commit an idea to a project (a Snapshot is created here, §9.10)."""
    app = _app(ctx)
    from helix.project import RUNG_TO_TIER

    seed = []
    consumed = []
    if from_think:
        # Carry Think context across (§9.10): both `think` notes
        # (type=scratch) and `explore` source pages (type=source) live
        # at scratch status — seed from all of them.
        seed = [e.handle for e in app.store.index if e.status == "scratch"]
        consumed = app.explore_store.consume_all()
    try:
        p = app.projects.create(
            name, tier=RUNG_TO_TIER[tier],
            privacy=private, at_path=at_path, pi=pi,
            origin="think" if from_think else "direct",
            seed_refs=seed,
        )
    except LadderError as e:
        raise click.ClickException(str(e))
    click.echo(f"Committed '{name}' at rung '{p.rung}'"
               + (f" (seeded from Think: {len(seed)} pages"
                  + (f", {len(consumed)} explore result(s)"
                     if consumed else "") + ")" if seed else "")
               + (" · privacy: strict" if private else ""))
    click.echo(f"  history starts here — Snapshot "
               f"{app.snapshots(name).head()}")
    click.echo(f"Next:  helix {name}    (or: helix peek {name})")


# ---- act on a project / why / peek / undo (§9.0) -------------------


@cli.command()
@click.argument("name")
@click.option("--question", default="", help="Research question to start.")
@click.pass_context
def run(ctx: click.Context, name: str, question: str) -> None:
    """Start (or advance) this project's workflow (§5.2)."""
    app = _app(ctx)
    if not app.projects.exists(name):
        raise click.ClickException(f"no such project: {name!r}")
    eng = app.workflow()
    st = eng.pending(name)
    if st["status"] == "interrupted":
        click.echo(f"{name} is blocked on a gate — resolve it: "
                   f"helix {name}")
        return
    if st["status"] == "running":
        click.echo(f"{name}: workflow already in progress.")
        return
    res = eng.start(name, research_question=question)
    _print_status(name, res)


@cli.command()
@click.argument("name")
@click.option("--approve", is_flag=True, help="Take the recommended option.")
@click.option("--option", "option", default=None,
              help="Resolve with a specific option id (e.g. pick:approach-2).")
@click.option("--why", "why", default="",
              help="Your reasoning (logged into the decision rationale).")
@click.option("--cosign", is_flag=True,
              help="PI countersignature for high-stakes decisions (§13).")
@click.option("--as", "pi", default="",
              help="The PI identity for --cosign.")
@click.pass_context
def act(ctx: click.Context, name, approve, option, why, cosign, pi):
    """Act on this project's pending item (§9.0: ``helix <project>``)."""
    app = _app(ctx)
    if not app.projects.exists(name):
        raise click.ClickException(
            f"no such project: {name!r}. Start one: "
            f'helix init {name}  (or  helix think "...")')
    if cosign:
        from helix.cosign import CoSign
        if not pi:
            raise click.ClickException("--cosign requires --as <pi>")
        signed = CoSign(app).sign(name, pi)
        if not signed:
            click.echo(f"{name}: nothing awaits co-sign.")
        else:
            click.echo(f"PI '{pi}' co-signed {len(signed)} decision(s): "
                       f"{', '.join(signed)} (§13 attestation, logged + "
                       f"Snapshotted).")
        return
    eng = app.workflow()
    st = eng.pending(name)
    if st["status"] == "done":
        click.echo(f"{name}: nothing is blocked on you. "
                   f"(helix run {name} to start · helix peek {name})")
        return
    if st["status"] == "running":
        click.echo(f"{name}: workflow is running — try again shortly.")
        return
    gate = st["gate"]
    chosen = option or (gate.get("recommended") if approve else None)
    if chosen is None:
        _render_gate(name, gate)
        return
    # §9.3: on published / privacy-strict the attestation trail IS the
    # deliverable — teach-back is required there.
    if gate.get("teach_back_required") and not why:
        raise click.ClickException(
            "this gate requires teach-back — add --why \"<your reasoning>\" "
            "(it is logged into the decision's rationale).")
    res = eng.resume(name, chosen, why)
    click.echo(f"Recorded '{chosen}'. Soft-commit: ~"
               f"{gate.get('soft_commit_seconds', 20)}s — `helix undo "
               f"{name}` reverts (logged).")
    _print_status(name, res)


def _print_status(name: str, res: dict) -> None:
    if res["status"] == "interrupted":
        click.echo(f"\n{name}: next decision —")
        _render_gate(name, res["gate"])
    elif res["status"] == "done":
        click.echo(f"{name}: workflow complete.")
    else:
        click.echo(f"{name}: running ({', '.join(res.get('next', []))}).")


def _render_gate(name: str, gate: dict) -> None:
    click.echo(f"{gate.get('title', 'Decision')}  ({name})")
    conf = gate.get("confidence")
    if conf is not None:
        click.echo(f"  confidence: {conf:.2f}  ·  unsure: "
                   f"{gate.get('unsure_about', '')}")
    for b in gate.get("why", []):
        click.echo(f"  • {b}")
    if gate.get("pause_reasons"):
        click.echo(f"  paused because: {'; '.join(gate['pause_reasons'])}")
    if gate.get("compare"):
        click.echo("  branches (side-by-side, §7.4):")
        for c in gate["compare"]:
            mark = " (parked)" if c.get("parked") else ""
            click.echo(f"    · {c['branch']}{mark} → {c['head']}")
    click.echo("  options:")
    for o in gate.get("options", []):
        star = " ◀ recommended" if o.get("recommended") else ""
        click.echo(f"    [{o['id']}] {o['label']}{star}")
    rec = gate.get("recommended", "")
    tb = ("  --why required (teach-back: this tier's attestation trail)"
          if gate.get("teach_back_required") else
          "  --why optional (pick-not-type; logged if given)")
    click.echo(f"Resolve:  helix {name} --approve"
               f"   |   helix {name} --option <id>")
    click.echo(f"          (recommended: {rec}){tb}")


@cli.command()
@click.argument("target")
@click.pass_context
def why(ctx: click.Context, target: str) -> None:
    """The reasoning behind where a project is (§9.0, the §14 artifact)."""
    app = _app(ctx)
    project = target.split("#")[0]
    if not app.projects.exists(project):
        raise click.ClickException(f"no such project: {project!r}")
    log = app.decision_log(project)
    entries = log.entries()
    if not entries:
        click.echo(f"{project}: no decisions logged yet.")
        return
    try:
        entry = (log.get(target) if "#" in target else entries[-1])
    except KeyError:
        raise click.ClickException(f"no such decision: {target!r}")
    click.echo(log.render_entry(entry))
    click.echo("Why (one-tap summary):")
    for b in log.why_bullets(entry):
        click.echo(f"  • {b}")


@cli.command()
@click.argument("name", required=False)
@click.pass_context
def peek(ctx: click.Context, name: Optional[str]) -> None:
    """READ-ONLY status + catch-me-up; no action, no tickets (§9.7)."""
    app = _app(ctx)
    from helix.catchup import CatchUp
    cu = CatchUp(app)                       # read-only: never marks opened
    if name is None:
        projs = app.projects.list()
        if not projs:
            click.echo("No projects yet.")
            return
        for p in projs:
            click.echo(f"  {p.name:<20} [{p.rung}]  "
                       f"{app.snapshots(p.name).head() or '—'}")
            d = cu.project_digest(p.name)   # catch-me-up, read-only (§9.6)
            if d:
                click.echo(f"     ↳ {d}")
        return
    if not app.projects.exists(name):
        raise click.ClickException(f"no such project: {name!r}")
    cd = cu.project_digest(name)
    if cd:
        click.echo(f"catch-me-up: {cd}")
    p = app.projects.get(name)
    snaps = app.snapshots(name)
    log = app.decision_log(name)
    click.echo(f"{name}  ·  rung: {p.rung}  ·  privacy: {p.privacy_mode}")
    if p.privacy_mode == "strict":
        from helix.privacy import Privacy
        _, degraded = Privacy(app).degraded(name)
        shown = ", ".join(degraded) or "(configure a [privacy] model)"
        click.echo(f"  privacy=strict — degraded roles (§9.9, visible): "
                   f"{shown}")
    click.echo(f"  branch: {snaps.active_branch}   head: "
               f"{snaps.head() or '—'}")
    last = log.entries()[-1] if log.entries() else None
    if last:
        click.echo(f"  last decision: {last['action']} "
                   f"— {last.get('rationale','')}")
    parked = [b for b in snaps.branches() if snaps.is_parked(b)]
    if parked:
        click.echo(f"  parked lines: {', '.join(parked)} "
                   f"(resumable: helix resume <branch>)")


@cli.command()
@click.argument("name")
@click.pass_context
def undo(ctx: click.Context, name: str) -> None:
    """Rewind the last step; the reversal is itself logged (§9.3)."""
    app = _app(ctx)
    if not app.projects.exists(name):
        raise click.ClickException(f"no such project: {name!r}")
    snaps = app.snapshots(name)
    head_id = snaps.head()
    head = snaps.get(head_id) if head_id else None
    if head is None or head.parent is None:
        click.echo(f"{name}: nothing to undo (at the project's start).")
        return
    log = app.decision_log(name)
    log.append(stage="undo", action="undo",
               rationale=f"Reverted {head.id} → {head.parent}.",
               auto_or_human="human")
    snaps.mint(decision_head=log.head(), parent=head.id,
               reason=f"undo: reverted to {head.parent}")
    click.echo(f"{name}: reverted to {head.parent} (logged + Snapshotted).")
    click.echo(f"  Inspect/verify the prior point: helix checkout {name} "
               f"{head.parent}. Restoring historical Atlas page *bodies* "
               f"is the §7.6 boundary (bindings resolve + verify; bodies "
               f"are not re-materialised).")


# ---- lifecycle ladder (§9.4) ---------------------------------------


def _ladder_move(app, name, fn, *a):
    if not app.projects.exists(name):
        raise click.ClickException(f"no such project: {name!r}")
    try:
        return fn(name, *a)
    except LadderError as e:
        raise click.ClickException(str(e))


@cli.command()
@click.argument("name")
@click.option("--to", type=click.Choice(LADDER), default=None)
@click.pass_context
def promote(ctx, name, to):
    """Move one rung up the lifecycle ladder (§9.4)."""
    app = _app(ctx)
    p = _ladder_move(app, name, app.projects.promote, to)
    click.echo(f"{name} → '{p.rung}' (logged + Snapshotted; reversible: "
               f"helix demote {name}).")


@cli.command()
@click.argument("name")
@click.option("--to", type=click.Choice(LADDER + ["archived"]), default=None)
@click.pass_context
def demote(ctx, name, to):
    """Move one rung down the lifecycle ladder (§9.4)."""
    app = _app(ctx)
    p = _ladder_move(app, name, app.projects.demote, to)
    click.echo(f"{name} → '{p.rung}' (logged + Snapshotted).")


@cli.command()
@click.argument("name")
@click.option("--status", type=click.Choice(["published", "paused"]),
              default="published")
@click.pass_context
def freeze(ctx, name, status):
    """Freeze a project: publication-ready (Maintainer) or paused (§9.7)."""
    app = _app(ctx)
    _need(app, name)
    if status == "paused":
        p = _ladder_move(app, name, app.projects.freeze, "paused")
        click.echo(f"{name} paused (active line parked).")
        return
    from helix.maintainer import AttestationIncomplete, Maintainer
    try:
        rep = Maintainer(app).freeze(name)      # the real §5.1 Maintainer
    except AttestationIncomplete as e:
        raise click.ClickException(str(e))      # clean, actionable (§13)
    click.echo(f"{name} frozen → published.")
    click.echo(f"  Atlas lint: {rep.lint_findings} finding(s) · "
               f"repro: {'ok' if rep.repro_ok else 'incomplete'}")
    click.echo(f"  drafts (from the decision log): "
               f"{', '.join(rep.drafts)}")
    click.echo(f"  supplement (Loom + Prism): {rep.supplement}")
    if rep.git_tag:
        click.echo(f"  git tag: {rep.git_tag}")


@cli.command()
@click.argument("name")
@click.pass_context
def archive(ctx, name):
    """Archive a project (= demote past the bottom rung) (§9.7)."""
    app = _app(ctx)
    _ladder_move(app, name, app.projects.archive)
    click.echo(f"{name} archived (logged + Snapshotted; reversible: "
               f"helix promote {name}).")


@cli.command()
@click.argument("name", required=False)
@click.pass_context
def status(ctx: click.Context, name: Optional[str]) -> None:
    """= the queue, filtered (§9.7). With NAME, only that project's
    items (and a project-scoped catch-me-up); the global idle cursor
    is not advanced by a scoped check."""
    app = _app(ctx)
    if name and not app.projects.exists(name):
        raise click.ClickException(f"no such project: {name!r}")
    _render_queue(app, project=name)


# ---- config + model (§9.7, §11.2) ----------------------------------


@cli.group()
def config() -> None:
    """Show or set Helix configuration (§9.7)."""


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    app = _app(ctx)
    cfg = app.config
    click.echo(f"home:       {app.home}")
    click.echo(f"atlas_root: {app.atlas_root}")
    for k, v in sorted(cfg.items()):
        click.echo(f"{k}: {v}")


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    _app(ctx).config_set(key, value)
    click.echo(f"set {key} = {value}")


@cli.group()
def model() -> None:
    """Model & provider routing (§11.2)."""


@model.command("list")
@click.option("--project", default=None)
@click.option("--privacy-strict", is_flag=True)
@click.pass_context
def model_list(ctx, project, privacy_strict):
    """Show the resolved model for every role (which layer won)."""
    app = _app(ctx)
    try:
        rows = app.router.table(project=project,
                                privacy_strict=privacy_strict)
    except RoutingError as e:
        raise click.ClickException(str(e))
    for r in rows:
        deg = (f"  (was {r.degraded_from}, privacy)" if r.degraded else "")
        click.echo(f"  {r.role:<16}{str(r.ref):<30}[{r.source}]{deg}")


@model.command("use")
@click.argument("ref")
@click.pass_context
def model_use(ctx: click.Context, ref: str) -> None:
    """Set the GLOBAL default model for every role (§11.2)."""
    app = _app(ctx)
    try:
        app.router.set_global(ref)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"global default → {ref}")


@model.command("set")
@click.argument("role")
@click.argument("ref")
@click.option("--project", default=None)
@click.pass_context
def model_set(ctx, role, ref, project):
    """Set a per-role (optionally per-project) model (§11.2)."""
    app = _app(ctx)
    try:
        if project:
            app.router.set_project_role(project, role, ref)
        else:
            app.router.set_role(role, ref)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{role}{f' @{project}' if project else ''} → {ref}")


@cli.group()
def atlas() -> None:
    """Knowledge base: GraphRAG search + continuous lint (§8, §6.4)."""


@atlas.command("search")
@click.argument("query")
@click.option("--scope", default=None, help="Restrict to a project.")
@click.option("--budget", default=10_000, show_default=True,
              help="Token budget for the scan (§8.3).")
@click.option("--notes", is_flag=True,
              help="Also search Notes (scratch) — hidden by default "
                   "(§6.3 'explicitly asked').")
@click.option("--show", default=3, show_default=True,
              help="Print the top-N page bodies/summaries.")
@click.pass_context
def atlas_search(ctx, query, scope, budget, notes, show):
    """Ranked context within a token budget (§8.4 Atlas.retrieve)."""
    app = _app(ctx)
    status = None
    if notes:
        status = ["scratch", "active", "canonical", "published"]
    ctx_ = app.retriever.retrieve(query, project_scope=scope,
                                  max_tokens=budget, status_filter=status)
    if not ctx_.items:
        # Be accurate: distinguish 'nothing exists' from 'everything
        # that matches is out of default scope' (§6.3 hides scratch).
        total = len(list(app.store.index))
        if total == 0:
            click.echo("No Atlas pages yet — `helix explore` to seed.")
        elif not notes:
            click.echo(f"No matches in active/canonical/published "
                       f"({total} pages indexed). Notes (scratch) are "
                       f"hidden by default — add --notes to include them.")
        else:
            click.echo(f"No matches across {total} indexed pages.")
        return
    click.echo(ctx_.render())
    for it in ctx_.items[:show]:
        click.echo(f"\n--- {it.handle}  (tier {it.tier}) ---")
        click.echo(it.text[:600] + ("…" if len(it.text) > 600 else ""))


@atlas.command("lint")
@click.option("--project", default=None, help="Limit to one project.")
@click.pass_context
def atlas_lint(ctx, project):
    """Full-corpus lint sweep (§6.4). Continuous lint runs on every
    write too; this is the on-demand Maintainer-style sweep."""
    app = _app(ctx)
    findings = app.linter.lint_all(project=project)
    if not findings:
        click.echo("Atlas lint: clean.")
        return
    by_kind: dict = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    click.echo(f"Atlas lint: {len(findings)} finding(s)")
    for kind in sorted(by_kind):
        click.echo(f"  {kind} ({len(by_kind[kind])}):")
        for f in by_kind[kind][:20]:
            click.echo(f"    - {f.handle}: {f.detail}")
    click.echo("(contradiction lint needs the LLM critic — not faked here.)")


# ---- version control over Snapshots (§7.5) -------------------------


def _need(app, name):
    if not app.projects.exists(name):
        raise click.ClickException(f"no such project: {name!r}")


@cli.command()
@click.argument("name")
@click.pass_context
def history(ctx, name):
    """The decision DAG — the project's commit graph (§7.5)."""
    app = _app(ctx); _need(app, name)
    from helix import vc
    rows = vc.history(app, name)
    if not rows:
        click.echo(f"{name}: no decisions yet.")
        return
    for r in rows:
        click.echo(f"  {r['decision']:<24} {r['action']:<22}"
                   f"{r['snapshot'] or '—':<22}[{r['auto_or_human']}]")


@cli.command()
@click.argument("name")
@click.argument("a")
@click.argument("b")
@click.pass_context
def diff(ctx, name, a, b):
    """Semantic diff between two points (§7.5) — not a text diff."""
    app = _app(ctx); _need(app, name)
    from helix import vc
    try:
        click.echo(vc.diff(app, name, a, b).render())
    except KeyError as e:
        raise click.ClickException(str(e))


@cli.command()
@click.argument("name")
@click.argument("ref")
@click.pass_context
def checkout(ctx, name, ref):
    """Resolve + integrity-verify a Snapshot (§7.5)."""
    app = _app(ctx); _need(app, name)
    from helix import vc
    try:
        man = vc.checkout(app, name, ref)
    except KeyError as e:
        raise click.ClickException(str(e))
    for k, v in man.items():
        click.echo(f"  {k}: {v}")


@cli.command()
@click.argument("name")
@click.argument("ref")
@click.pass_context
def repro(ctx, name, ref):
    """Reproduction manifest for any point (§7.5)."""
    app = _app(ctx); _need(app, name)
    from helix import vc
    try:
        man = vc.repro(app, name, ref)
    except KeyError as e:
        raise click.ClickException(str(e))
    click.echo(f"reproducible: {man['reproducible']}  "
               f"(integrity {man['integrity_ok']})")
    click.echo(f"  models: {man['model_routing']}")
    click.echo(f"  {man['note']}")


@cli.command()
@click.argument("name")
@click.pass_context
def bisect(ctx, name):
    """Find which decision first introduced a metric regression (§7.5)."""
    app = _app(ctx); _need(app, name)
    from helix import vc
    r = vc.bisect(app, name)
    if r["found"]:
        click.echo(f"first bad: {r['decision']} ({r['snapshot']})\n"
                   f"  {r['reason']}")
    else:
        click.echo(r["reason"])


@cli.command()
@click.argument("name")
@click.option("--to", "dest", default=None,
              help="Bundle output dir (default: ./<name>-fork).")
@click.pass_context
def fork(ctx, name, dest):
    """Export a self-contained importable bundle + Loom/Prism (§7.5)."""
    app = _app(ctx); _need(app, name)
    from helix import vc
    out = vc.fork_bundle(app, name, Path(dest or f"./{name}-fork"))
    click.echo(f"forked → {out}  (decision history + Snapshots + Atlas "
               f"subgraph + Loom + Prism)")


@cli.command()
@click.argument("name")
@click.option("--export", "export", default=None,
              help="Write the grayscale SVG to this path.")
@click.pass_context
def loom(ctx, name, export):
    """The project map (§7.7) — Map mode, TTY/SVG (Layers/Compare: v1.5)."""
    app = _app(ctx); _need(app, name)
    from helix.loom import Loom
    lm = Loom(app, name)
    if export:
        Path(export).write_text(lm.render_svg())
        click.echo(f"Loom SVG (grayscale) → {export}")
    else:
        click.echo(lm.render_tty(), nl=False)


@cli.command()
@click.argument("name")
@click.option("--export", "export", default=None,
              help="Write the SVG (legend included) to this path.")
@click.pass_context
def prism(ctx, name, export):
    """The project anatomy (§7.8) — Strategy → Data → Code."""
    app = _app(ctx); _need(app, name)
    from helix.prism import Prism
    pr = Prism(app, name)
    if export:
        Path(export).write_text(pr.render_svg())
        click.echo(f"Prism SVG → {export}")
    else:
        click.echo(pr.render_tty(), nl=False)


@cli.command()
@click.argument("name")
@click.argument("branch")
@click.option("--reason", default="dead end", help="Why the line died.")
@click.pass_context
def salvage(ctx, name, branch, reason):
    """Keep the learning, park the dead end (§6.4)."""
    app = _app(ctx); _need(app, name)
    from helix.salvage import Salvager
    try:
        r = Salvager(app).salvage(name, branch, reason=reason)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"salvaged '{branch}': {r.claims} durable claim(s) → "
               f"{r.canonical_handle} (canonical, provenance-tagged); "
               f"branch parked + resumable.")


@cli.command()
@click.argument("name", required=False)
@click.pass_context
def doctor(ctx, name):
    """One cross-layer diagnostic, plain language (§9.11)."""
    app = _app(ctx)
    if name:
        _need(app, name)
    from helix.doctor import Doctor
    checks = Doctor(app).run(name)
    bad = [c for c in checks if not c.ok]
    click.echo(f"helix doctor — {'ISSUES' if bad else 'all clear'} "
               f"({len(checks)} checks)")
    for c in checks:
        click.echo(c.render())


@cli.group()
def watcher() -> None:
    """Async passive enrichment — off by default (§5.1, §11.1)."""


@watcher.command("status")
@click.pass_context
def watcher_status(ctx):
    from helix.watcher import Watcher
    st = Watcher(_app(ctx)).status()
    click.echo(f"enabled: {st['enabled']}  schedule: {st['schedule']}")
    click.echo(f"watching: {st['watch'] or '(active projects only)'}")
    click.echo(f"seen papers: {st['seen']}  open proposals: "
               f"{st['open_proposals']}")


@watcher.command("schedule")
@click.argument("cron", required=False)
@click.pass_context
def watcher_schedule(ctx, cron):
    """Enable the Watcher + record cadence; prints the crontab line."""
    from helix.watcher import Watcher
    w = Watcher(_app(ctx))
    w.enable(cron)
    click.echo("Watcher enabled. Add this to your crontab "
               "(Helix does not daemonize itself):")
    click.echo(f"  {w.crontab_line()}")


@watcher.command("off")
@click.pass_context
def watcher_off(ctx):
    from helix.watcher import Watcher
    Watcher(_app(ctx)).disable()
    click.echo("Watcher disabled.")


@watcher.command("watch")
@click.argument("query")
@click.pass_context
def watcher_watch(ctx, query):
    from helix.watcher import Watcher
    Watcher(_app(ctx)).watch(query)
    click.echo(f"watching: {query!r}")


@watcher.command("run")
@click.pass_context
def watcher_run(ctx):
    """One pass (cron-wrap this). Scratch-only; proposals are FYI."""
    from helix.watcher import Watcher
    rep = Watcher(_app(ctx)).run()
    if not rep.ran:
        click.echo(rep.note)
        return
    click.echo(f"Watcher pass: {rep.ingested} new source(s) → scratch, "
               f"{rep.proposals} proposal(s) "
               f"({rep.deferred} deferred), {rep.skipped_seen} already "
               f"seen.")
    click.echo(f"  {rep.note}")


@watcher.command("apply")
@click.argument("proposal_id")
@click.pass_context
def watcher_apply(ctx, proposal_id):
    from helix.watcher import Watcher
    try:
        click.echo(Watcher(_app(ctx)).apply(proposal_id))
    except KeyError:
        raise click.ClickException(f"no such proposal: {proposal_id!r}")


@cli.command()
@click.option("--port", default=8765, show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.pass_context
def serve(ctx: click.Context, port: int, host: str) -> None:
    """Mobile/QR-paired gate view (§11, opt-in, zero-dep)."""
    app = _app(ctx)
    from helix.web import serve as _serve

    httpd, url, token = _serve(app, host=host, port=port)
    click.echo(f"Helix web view paired — open on your phone:\n  {url}")
    click.echo(f"  token: {token}")
    try:
        import qrcode  # opt-in 'qr-image' upgrade
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii()
    except ImportError:
        click.echo("  (scannable QR image: `pip install qrcode` — the "
                   "qr-image upgrade; URL/token above work without it)")
    click.echo("Token auth is advisory (loopback dev tool), not a "
               "security boundary. Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


@cli.command()
@click.pass_context
def upgrades(ctx: click.Context) -> None:
    """List opt-in upgrades + status (§11.1). None on the critical path."""
    from helix.upgrades import status_lines
    click.echo("Opt-in upgrades (the default needs none of these):")
    for ln in status_lines():
        click.echo(ln)
    click.echo("Selecting an unconfigured upgrade fails closed with "
               "instructions — Helix never fabricates results.")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
