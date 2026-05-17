"""The unified queue — the one mental model (HELIX.md §9.1, §9.0).

Everything that needs the user lands in one prioritised queue with
**three buckets in fixed order**: *Needs you now* (blocking) →
*Working* (in flight) → *FYI* (no action). One badge = the count of
*Needs you now*. ``helix`` with no args *is* this queue.

Providers feed items in. Step 5 ships the queue *infrastructure*; the
content providers for gates (step 9), Maintainer suggestions (step 11)
and the Watcher (step 13) plug into the same interface as they land —
so this deliberately renders the Appendix A.2 first-run screen until
they do, rather than faking items.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

NEEDS_YOU = "NEEDS YOU NOW"
WORKING = "WORKING"
FYI = "FYI"
BUCKET_ORDER = (NEEDS_YOU, WORKING, FYI)


@dataclass
class QueueItem:
    bucket: str
    title: str
    detail: str = ""
    aside: str = ""                       # age ("2h ago") or eta ("~20m")
    command: Optional[str] = None         # exact invocation (§9.0)


# A provider takes the app and returns items. Kept as a plain callable
# so later build steps register without importing this module's guts.
QueueProvider = Callable[["object"], List[QueueItem]]


def explore_fyi_provider(app) -> List[QueueItem]:
    """Surfaces finished explores as FYI (§9.1/§10) — informational,
    never a gate (§9.10). 'Make it a project' = init --from-think."""
    items: List[QueueItem] = []
    for r in app.explore_store.unconsumed():
        n, m = r.get("paper_count", 0), len(r.get("gaps") or [])
        items.append(QueueItem(
            bucket=FYI,
            title="Explore done",
            detail=f'"{r["query"]}" — {n} papers, {m} gaps',
            aside="done",
            command="helix init <name> --from-think",
        ))
    return items


def workflow_gate_provider(app) -> List[QueueItem]:
    """Interrupted workflow gates → NEEDS-YOU items (§9.1). This is what
    finally makes the blocking bucket real. Read-only: skipped entirely
    until a workflow has been started (no side effects on the queue)."""
    if not (app.home / "forge.sqlite").exists():
        return []
    items: List[QueueItem] = []
    engine = app.workflow()
    for p in app.projects.list():
        try:
            st = engine.pending(p.name)
        except Exception:  # noqa: BLE001 — a broken thread never breaks the queue
            continue
        if st.get("status") == "interrupted":
            gate = st["gate"]
            items.append(QueueItem(
                bucket=NEEDS_YOU,
                title=p.name,
                detail=gate.get("title", "decision needed"),
                command=f"helix {p.name}",
            ))
    return items


def loom_fyi_provider(app) -> List[QueueItem]:
    """§7.7.7: a branch abandoned without salvage is a cost the prose
    log hides — Loom surfaces it; the queue carries it as FYI (§9.5)."""
    items: List[QueueItem] = []
    for p in app.projects.list():
        snaps = app.snapshots(p.name)
        for b in snaps.branches():
            if b != "main" and snaps.is_parked(b) and \
                    not snaps.is_salvaged(b):
                items.append(QueueItem(
                    bucket=FYI, title=f"{p.name}/{b}",
                    detail="branch abandoned without salvage",
                    command=f"helix salvage {p.name} {b}"))
    return items


def maintainer_fyi_provider(app) -> List[QueueItem]:
    """Promotion-as-suggestion (§9.4): the Maintainer detects the
    moments; the queue carries them as one-tap FYI with the exact
    command (discovery replaces memorisation, §9.0)."""
    from helix.maintainer import Maintainer

    items: List[QueueItem] = []
    for s in Maintainer(app).suggestions():
        items.append(QueueItem(bucket=FYI, title=s.title,
                                detail="", command=s.command))
    return items


def cosign_provider(app) -> List[QueueItem]:
    """High-stakes decisions awaiting PI co-sign → NEEDS YOU NOW
    (§13 attestation trail; only for opt-in regulated/private)."""
    from helix.cosign import CoSign

    cs = CoSign(app)
    items: List[QueueItem] = []
    for p in app.projects.list():
        pend = cs.pending(p.name)
        if pend:
            items.append(QueueItem(
                bucket=NEEDS_YOU, title=p.name,
                detail=f"{len(pend)} decision(s) await PI co-sign (§13)",
                command=f"helix {p.name} --cosign --as <pi>"))
    return items


def watcher_fyi_provider(app) -> List[QueueItem]:
    """Watcher findings → batched FYI (§9.1/§5.1). Aggregated per
    project/topic (not per-paper) — the §9.5 triage keeps it ping-free."""
    from helix.watcher import Watcher

    groups: dict = {}
    for p in Watcher(app).open_proposals():
        key = p.get("project") or p.get("query") or "atlas"
        g = groups.setdefault(key, {"n": 0, "deferred": 0})
        g["n"] += 1
        g["deferred"] += 1 if p.get("deferred") else 0
    items: List[QueueItem] = []
    for key, g in groups.items():
        d = (f"  ·  {g['deferred']} deferred (project in-flight)"
             if g["deferred"] else "")
        items.append(QueueItem(
            bucket=FYI,
            title=f"Watcher: {g['n']} new paper(s) may overlap {key}{d}",
            command="helix watcher"))
    return items


class Queue:
    def __init__(self, app):
        self.app = app
        self._providers: List[QueueProvider] = []

    def register(self, provider: QueueProvider) -> None:
        self._providers.append(provider)

    def collect(self, project: Optional[str] = None) -> dict:
        """All queue items by bucket. ``project`` filters to items that
        concern that project — an item is in-scope if the project name
        appears in its title or its suggested command (§9.7
        ``helix status [<name>]`` = the queue, filtered)."""
        items = {b: [] for b in BUCKET_ORDER}
        for provider in self._providers:
            for it in provider(self.app):
                if project and not (
                        project in it.title
                        or (it.command and project in it.command)):
                    continue
                items[it.bucket].append(it)
        return items

    def badge(self, project: Optional[str] = None) -> int:
        return len(self.collect(project)[NEEDS_YOU])

    # ---- rendering --------------------------------------------------

    def render(self, project: Optional[str] = None) -> str:
        items = self.collect(project)
        lines: List[str] = []
        any_items = False
        for bucket in BUCKET_ORDER:
            bucket_items = items[bucket]
            if not bucket_items:
                continue
            any_items = True
            lines.append(f"{bucket} ({len(bucket_items)})")
            marker = "▸" if bucket == NEEDS_YOU else "·"
            for it in bucket_items:
                head = f"  {marker} {it.title}"
                if it.detail:
                    head += f" — {it.detail}"
                if it.aside:
                    # Always keep a visible gap before the aside, even
                    # when the line overflows the pad width (avoids
                    # "...gapsdone").
                    pad = max(58 - len(head), 2)
                    head = f"{head}{' ' * pad}{it.aside}"
                lines.append(head)
                if it.command:
                    lines.append(f"      → {it.command}")
        if not any_items:
            if project:
                lines.append(f"Nothing needs you on '{project}'.")
                return "\n".join(lines) + "\n"
            lines.append("Nothing needs you yet.")
            projects = self.app.projects.list()
            if not projects:
                lines += [
                    '  ▸ Start exploring:   helix think "<your question>"',
                    '                       helix explore '
                    '"<a literature question>"',
                ]
            else:
                lines.append("  Your projects:")
                for p in projects:
                    lines.append(
                        f"    · {p.name}  [{p.rung}]"
                        f"   ·   helix peek {p.name}"
                    )
        return "\n".join(lines) + "\n"
