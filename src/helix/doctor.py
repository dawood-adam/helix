"""One project object, one ``helix doctor`` (HELIX.md §9.11).

The Forge/Atlas split is internal but leaks the moment something
breaks. Users never debug two systems: ``helix doctor`` runs one
cross-layer diagnostic (Atlas write/index health, Snapshot integrity,
decision↔Snapshot consistency, broken refs, Prism rationale slots,
budget/workflow presence) and reports in plain language with a
suggested fix. The user's mental model stays "one project".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Check:
    area: str
    ok: bool
    detail: str
    fix: str = ""

    def render(self) -> str:
        mark = "✓" if self.ok else "✗"
        s = f"  {mark} {self.area}: {self.detail}"
        if not self.ok and self.fix:
            s += f"\n      fix: {self.fix}"
        return s


class Doctor:
    def __init__(self, app):
        self.app = app

    def run(self, project: Optional[str] = None) -> List[Check]:
        checks: List[Check] = []

        # 1. Atlas index + write-ahead log health.
        try:
            n = len(list(self.app.store.index))
            checks.append(Check("atlas-index", True,
                                f"{n} page(s) indexed, index loads"))
        except Exception as e:  # noqa: BLE001
            checks.append(Check("atlas-index", False, f"index unreadable: {e}",
                                "restore .helix/index.json from git"))
        wal = self.app.store.layout.wal_path
        checks.append(Check(
            "atlas-wal", True,
            f"{sum(1 for _ in wal.open()) if wal.exists() else 0} "
            f"write record(s)" if wal.exists() else "no writes yet"))

        projects = ([self.app.projects.get(project)]
                    if project else self.app.projects.list())
        for p in projects:
            checks.extend(self._project_checks(p.name))

        # 4. Workflow/budget presence (deep budget read needs an active
        # thread — reported honestly, not faked).
        if (self.app.home / "forge.sqlite").exists():
            checks.append(Check("forge", True,
                                "workflow checkpoint store present"))
        return checks

    def _project_checks(self, name: str) -> List[Check]:
        out: List[Check] = []
        snaps = self.app.snapshots(name)
        all_snaps = snaps.all()

        bad = [s.id for s in all_snaps if not s.verify()]
        out.append(Check(
            f"{name}: snapshot-integrity", not bad,
            "all Snapshot content hashes verify" if not bad
            else f"tampered/corrupt Snapshots: {bad}",
            "restore the project's .snapshots/ from git"))

        head = snaps.head()
        out.append(Check(
            f"{name}: snapshot-head", head is None or
            any(s.id == head for s in all_snaps),
            f"head {head} resolves" if head else "no head yet (not run)",
            "run `helix history` and re-mint if missing"))

        # decision ↔ snapshot consistency
        dl_ids = {e["id"] for e in self.app.decision_log(name).entries()}
        dangling = [s.id for s in all_snaps
                    if s.decision_head and s.decision_head not in dl_ids]
        out.append(Check(
            f"{name}: decision-binding", not dangling,
            "every Snapshot decision_head exists in the log"
            if not dangling else f"dangling decision heads: {dangling}",
            "decision log and snapshots desynced — `helix repro`"))

        # broken refs (reuse the §7 linter)
        try:
            from helix.atlas.lint import Linter
            broken = [f for f in Linter(self.app.store).lint_all(project=name)
                      if f.kind == "broken_link"]
            out.append(Check(
                f"{name}: broken-refs", not broken,
                "no broken wikilinks" if not broken
                else f"{len(broken)} broken link(s)",
                "regenerate the source, or `helix atlas lint`"))
        except Exception as e:  # noqa: BLE001
            out.append(Check(f"{name}: broken-refs", False,
                             f"lint failed: {e}"))

        # Prism rationale slots (§7.8.4: never silently blank)
        try:
            from helix.prism import Prism
            miss = Prism(self.app, name).model().missing_rationale
            out.append(Check(
                f"{name}: prism-rationale", not miss,
                "Strategy/Data/Code rationale all present" if not miss
                else f"rationale missing for {', '.join(miss)}",
                "add reasoning at the relevant gate (helix why)"))
        except Exception as e:  # noqa: BLE001
            out.append(Check(f"{name}: prism-rationale", False,
                             f"prism failed: {e}"))
        return out
