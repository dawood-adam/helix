"""The Maintainer + promotion-as-suggestion (HELIX.md §5.1, §9.4, §13).

At freeze the Maintainer runs the full-corpus Atlas lint (§6.4), writes
the repro manifest (§4.3), freezes the project (tier → published, via
the ProjectStore so it's a logged + Snapshotted rung change), git-tags
the Atlas repo, and auto-drafts the **within-project value** wedge
(§13): Methods, Limitations, reviewer Rebuttals and a BibTeX file —
all *deterministic roll-ups of the canonical decision log*, not LLM
ghostwriting (the LLM polish is the upgrade; this is honest about
being a structured draft). Loom + Prism are emitted as the publication
supplement (§7.7.6).

Promotion-as-suggestion (§9.4): the Maintainer detects the moments and
proposes one-tap FYI items in plain language — the user answers yes/no,
never memorises ``promote --to canonical``.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from helix import vc
from helix.atlas.lint import Linter


class AttestationIncomplete(RuntimeError):
    """Freeze blocked: high-stakes decisions await PI co-sign (§13)."""


@dataclass
class FreezeReport:
    project: str
    lint_findings: int
    drafts: List[str]
    repro_ok: bool
    git_tag: Optional[str]
    supplement: str


@dataclass
class Suggestion:
    kind: str           # "promote" | "freeze"
    title: str
    command: str
    detail: str


class Maintainer:
    def __init__(self, app):
        self.app = app

    # ---- freeze (§5.1, §13) -----------------------------------------

    def freeze(self, project: str) -> FreezeReport:
        # §13: publication is always high-stakes — the attestation
        # trail must be complete before we freeze. Enforced here, the
        # one genuinely high-stakes moment, not as a second interrupt.
        from helix.cosign import CoSign

        # Only enforced for opt-in high-stakes projects (regulated /
        # privacy=strict) — never paternalistic on the solo user (§9.3).
        pend = CoSign(self.app).pending(project)
        if pend:
            raise AttestationIncomplete(
                f"cannot freeze {project}: {len(pend)} high-stakes "
                f"decision(s) await PI co-sign — `helix {project} "
                f"--cosign --as <pi>` (§13 attestation trail).")
        layout = self.app.store.layout
        pdir = layout.project_dir(project)
        pdir.mkdir(parents=True, exist_ok=True)
        log = self.app.decision_log(project)
        entries = log.entries()

        # 1. Full-corpus Atlas lint (§6.4 — Maintainer's freeze sweep).
        findings = Linter(self.app.store).lint_all(project=project)

        # 2. Repro manifest (§4.3) — readable doc from the head Snapshot.
        head = self.app.snapshots(project).head()
        repro_ok = False
        if head:
            man = vc.repro(self.app, project, head)
            repro_ok = bool(man.get("reproducible"))
            (pdir / "repro.md").write_text(_repro_md(project, man))

        # 3. Within-project value drafts (§13) — decision-log roll-ups.
        drafts = self._draft_artifacts(project, entries, pdir)

        # 4. Freeze the project (logged + Snapshotted rung change) and
        #    emit the Loom/Prism publication supplement (§7.7.6).
        self.app.projects.freeze(project, "published")
        supplement = self._emit_supplement(project)

        # 5. git-tag the Atlas repo (best-effort; honest if no git).
        tag = self._git_tag(project)

        log.append(stage="lifecycle", action="maintainer_freeze",
                   rationale=(f"Maintainer froze {project}: lint "
                              f"{len(findings)} finding(s), repro "
                              f"{'ok' if repro_ok else 'incomplete'}, "
                              f"drafts {', '.join(drafts)}."),
                   auto_or_human="auto")
        return FreezeReport(project, len(findings), drafts, repro_ok,
                            tag, str(supplement))

    # ---- the §13 within-project artifacts ---------------------------

    def _draft_artifacts(self, project: str, entries: List[Dict[str, Any]],
                          pdir: Path) -> List[str]:
        made: List[str] = []
        banner = ("<!-- auto-drafted from .decision-log.json — a "
                  "deterministic roll-up, not a written-up paper. The "
                  "LLM polish is the opt-in upgrade. -->\n\n")

        picks = [e for e in entries if e["action"].startswith("pick:")]
        approvals = [e for e in entries
                     if e["action"] in ("approve", "ship")]
        methods = [f"# Methods — {project} (draft)\n", banner]
        for e in picks + approvals:
            r = (e.get("rationale") or "").strip()
            if r:
                ev = ", ".join(e.get("evidence", [])) or "—"
                methods.append(f"- **{e['action']}** ({e['stage']}): {r}  "
                               f"_(evidence: {ev})_")
        (pdir / "methods.md").write_text("\n".join(methods) + "\n")
        made.append("methods.md")

        # Limitations = parked/salvaged lines + blocking critiques.
        snaps = self.app.snapshots(project)
        parked = [b for b in snaps.branches() if snaps.is_parked(b)]
        lims = [f"# Limitations — {project} (draft)\n", banner]
        for b in parked:
            tag = "salvaged" if snaps.is_salvaged(b) else "parked"
            lims.append(f"- Research line **{b}** ({tag}) was not pursued "
                        f"to completion.")
        for e in entries:
            if e["action"] == "salvage":
                lims.append(f"- {e.get('rationale', '')}")
        if len(lims) == 2:
            lims.append("- No parked lines or salvage events recorded.")
        (pdir / "limitations.md").write_text("\n".join(lims) + "\n")
        made.append("limitations.md")

        # Reviewer rebuttals (§13): every rejected option already has its
        # reason + evidence in the log — "why didn't you try X?" answered.
        reb = [f"# Reviewer rebuttals — {project} (draft)\n", banner]
        for e in entries:
            for rj in e.get("rejected", []):
                reb.append(
                    f"**Q: Why didn't you use "
                    f"{rj.get('label', rj.get('id', '?'))}?**  \n"
                    f"A: {rj.get('reason', 'rejected at '+e['stage'])} "
                    f"(decision {e['id']}).\n")
        for b in parked:
            reb.append(f"**Q: Why didn't you pursue the '{b}' line?**  \n"
                       f"A: it was parked/salvaged — see Limitations and "
                       f"`helix resume {b}` (the bet is retained, §7.4).\n")
        if len(reb) == 2:
            reb.append("_No rejected alternatives recorded yet._\n")
        (pdir / "rebuttals.md").write_text("\n".join(reb) + "\n")
        made.append("rebuttals.md")

        # BibTeX from ingested source pages (honest: from what we have).
        bib = []
        for entry in self.app.store.index:
            if entry.type != "source":
                continue
            key = entry.handle.split(":", 1)[1].replace("-", "_")[:40]
            yr = entry.handle.split(":")[1][:4]
            bib.append(f"@misc{{{key},\n  title={{{entry.title}}},\n"
                       f"  year={{{yr if yr.isdigit() else 'n.d.'}}},\n"
                       f"  note={{ingested via helix explore}}\n}}")
        if bib:
            (pdir / "references.bib").write_text("\n\n".join(bib) + "\n")
            made.append("references.bib")
        return made

    def _emit_supplement(self, project: str) -> Path:
        from helix.loom import Loom
        from helix.prism import Prism

        sup = self.app.store.layout.project_dir(project) / "supplement"
        sup.mkdir(parents=True, exist_ok=True)
        (sup / "loom.svg").write_text(Loom(self.app, project).render_svg())
        (sup / "loom.txt").write_text(
            Loom(self.app, project).render_tty(color=False))
        (sup / "prism.svg").write_text(Prism(self.app, project).render_svg())
        (sup / "prism.txt").write_text(
            Prism(self.app, project).render_tty())
        return sup

    def _git_tag(self, project: str) -> Optional[str]:
        import subprocess

        root = self.app.store.root
        if not (root / ".git").exists():
            return None
        tag = f"helix/{project}/frozen-{_dt.date.today().isoformat()}"
        try:
            subprocess.run(["git", "-C", str(root), "tag", "-f", tag],
                           check=True, capture_output=True)
            return tag
        except (OSError, subprocess.SubprocessError):
            return None

    # ---- promotion-as-suggestion (§9.4) -----------------------------

    def suggestions(self) -> List[Suggestion]:
        """Detect the moments; propose one-tap FYI items in plain
        language. Detectors are deterministic (no LLM)."""
        out: List[Suggestion] = []

        # (a) a concept used as evidence across >=2 distinct projects but
        #     not yet canonical → "save as reusable knowledge".
        cross: Dict[str, set] = {}
        for proj in self.app.projects.list():
            for e in self.app.decision_log(proj.name).entries():
                for ev in e.get("evidence", []):
                    if str(ev).startswith("concept:"):
                        cross.setdefault(ev, set()).add(proj.name)
        for handle, projs in cross.items():
            if len(projs) < 2:
                continue
            try:
                entry = self.app.store.index.resolve(handle)
            except KeyError:
                continue
            if entry.status == "canonical":
                continue
            # §9.9 no auto-promotion: a concept any private project
            # touched must be manually abstracted first — never
            # *suggested* for one-tap promotion.
            from helix.privacy import Privacy

            if Privacy(self.app).concept_is_private(handle):
                continue
            out.append(Suggestion(
                "promote",
                f"'{entry.title}' has shown up in {len(projs)} "
                f"projects — save it as reusable knowledge?",
                f"helix promote {handle}",
                "promotion-as-suggestion (§9.4)"))

        # (b) workflow shipped but project not yet published → freeze.
        for proj in self.app.projects.list():
            if proj.tier == "published":
                continue
            acts = [e["action"]
                    for e in self.app.decision_log(proj.name).entries()]
            if "ship" in acts and "maintainer_freeze" not in acts:
                out.append(Suggestion(
                    "freeze",
                    f"{proj.name} looks publication-ready — freeze it "
                    f"and write the repro manifest?",
                    f"helix freeze {proj.name}",
                    "promotion-as-suggestion (§9.4)"))
        return out


def _repro_md(project: str, man: Dict[str, Any]) -> str:
    lines = [f"# Reproduction manifest — {project}",
             "",
             f"*generated at freeze — `helix repro` reproduces any "
             f"Snapshot, not just this one (§7.5).*", ""]
    for k in ("snapshot", "decision_head", "code_sha", "integrity_ok",
              "env_lock"):
        lines.append(f"- **{k}**: {man.get(k)}")
    lines.append(f"- **model_routing**: {man.get('model_routing')}")
    lines.append("")
    lines.append(man.get("materialisation_note", ""))
    return "\n".join(lines) + "\n"
