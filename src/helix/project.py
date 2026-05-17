"""Projects + the lifecycle ladder (HELIX.md §9.4, §9.8, §9.10, §4.1).

One ordered ladder, moved one rung at a time::

    think  →  notes  →  project  →  published
                ↑__________↓                  →  archived
              demote      promote      (freeze)

User-facing rung names map to the internal §4.1 ``project_tier``:
``notes``↔``scratch``, ``project``↔``active``, ``published`` and
``archived`` unchanged. "think" is pre-project (the Think surface,
§9.10 — no project object yet).

Every rung change is a decision-log event **and** mints a Snapshot
(§9.4), so promote/demote/freeze/archive are themselves reversible and
attributable. ``init`` creates the project and its first Snapshot —
the project's history starts at the moment of commitment (§9.10).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from helix.atlas.writequeue import Intent

if TYPE_CHECKING:
    from helix.app import Helix

# user-facing rung  ->  internal project_tier (§9.8)
RUNG_TO_TIER = {
    "notes": "scratch",
    "project": "active",
    "published": "published",
    "archived": "archived",
}
TIER_TO_RUNG = {v: k for k, v in RUNG_TO_TIER.items()}
# Promotable order; ``archived`` is aside (reached by demoting past the
# bottom rung, or `helix archive` from anywhere — §9.7).
LADDER = ["notes", "project", "published"]


class LadderError(RuntimeError):
    """An impossible rung move (already at top/bottom, bad target)."""


def rung_of(tier: str) -> str:
    return TIER_TO_RUNG[tier]


@dataclass
class Project:
    name: str
    tier: str = "scratch"                 # internal project_tier (§4.1)
    privacy_mode: str = "normal"          # normal | strict (§9.9)
    at_path: Optional[str] = None         # where it lives (§9.10 --at)
    origin: str = "direct"                # direct | think | explore
    pi: str = ""                          # opt-in PI co-sign (§13, §9.3)
    created: str = field(
        default_factory=lambda: _dt.date.today().isoformat()
    )
    seed_refs: List[str] = field(default_factory=list)

    @property
    def rung(self) -> str:
        return rung_of(self.tier)


class ProjectStore:
    """Per-project metadata + the ladder operations."""

    META = ".helix-project.json"

    def __init__(self, app: "Helix"):
        self.app = app
        self.layout = app.store.layout

    # ---- persistence ------------------------------------------------

    def _meta_path(self, name: str):
        return self.layout.project_dir(name) / self.META

    def exists(self, name: str) -> bool:
        return self._meta_path(name).exists()

    def get(self, name: str) -> Project:
        if not self.exists(name):
            raise KeyError(f"no such project: {name!r}")
        return Project(**json.loads(self._meta_path(name).read_text()))

    def list(self) -> List[Project]:
        root = self.layout.root / "projects"
        if not root.exists():
            return []
        out = []
        for d in sorted(root.iterdir()):
            if (d / self.META).exists():
                out.append(Project(**json.loads((d / self.META).read_text())))
        return out

    def _save(self, p: Project) -> None:
        path = self._meta_path(p.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique temp name: never share a temp path across threads/
        # processes (a fixed ".tmp" raced under concurrent tier changes —
        # the second replace() found the temp already consumed).
        tmp = path.with_suffix(
            f".{os.getpid()}.{threading.get_ident()}.json.tmp"
        )
        tmp.write_text(json.dumps(asdict(p), indent=2, sort_keys=True))
        tmp.replace(path)  # atomic on POSIX

    # ---- the project's Atlas overview page --------------------------

    def _overview_handle(self, name: str) -> str:
        from helix.ids import make_handle

        return make_handle("project", name)

    def _ensure_overview(self, p: Project) -> None:
        handle = self._overview_handle(p.name)
        body = f"# {p.name}\n\nProject overview. Tier: {p.rung}."
        if p.seed_refs:
            body += "\n\nSeeded from Think:\n" + "\n".join(
                f"- [[{r}]]" for r in p.seed_refs
            )
        if self.app.store.index.has(handle):
            page, ver = self.app.store.read_page(handle)
            self.app.wq.submit(
                Intent(op="set_status", ref=handle, base_version=ver,
                       payload={"status": p.tier})
            )
        else:
            self.app.wq.submit(
                Intent(op="create", payload={
                    "type": "project", "title": p.name,
                    "status": p.tier, "body": body})
            )

    # ---- create (Think -> Forge hand-off, §9.10) --------------------

    def create(
        self,
        name: str,
        *,
        tier: str = "scratch",
        privacy: bool = False,
        at_path: Optional[str] = None,
        origin: str = "direct",
        pi: str = "",
        seed_refs: Optional[List[str]] = None,
    ) -> Project:
        # The whole commit is one atomic, serialized unit on the global
        # write lock (RLock; nested submits re-enter safely): meta +
        # overview page + init decision + first Snapshot land together
        # or not at all — no half-created project under concurrency.
        with self.app.wq.lock:
            if self.exists(name):
                raise LadderError(f"project already exists: {name!r}")
            p = Project(
                name=name,
                tier=tier,
                privacy_mode="strict" if privacy else "normal",
                at_path=at_path,
                origin=origin,
                pi=pi,
                seed_refs=list(seed_refs or []),
            )
            self._save(p)
            self._ensure_overview(p)
            log = self.app.decision_log(name)
            log.append(
                stage="lifecycle",
                action="init",
                rationale=(
                    f"Project committed at rung '{p.rung}'"
                    + (f", seeded from Think ({len(p.seed_refs)} refs)"
                       if p.seed_refs else "")
                    + (". Privacy: strict." if privacy else ".")
                ),
                evidence=list(p.seed_refs or []),
                auto_or_human="human",
            )
            self.app.snapshots(name).mint(
                decision_head=log.head(), reason="init",
                atlas_pages=self._atlas_binding(name, log),
                data_hashes=self._data_binding(name),
            )
            return p

    # ---- ladder moves ----------------------------------------------

    def _change_tier(
        self, name: str, new_tier: str, *, action: str, rationale: str
    ) -> Project:
        with self.app.wq.lock:
            p = self.get(name)
            old_rung = p.rung
            p.tier = new_tier
            self._save(p)
            self._ensure_overview(p)
            log = self.app.decision_log(name)
            log.append(
                stage="lifecycle",
                action=action,
                rationale=f"{rationale} ({old_rung} → {p.rung}).",
                auto_or_human="human",
            )
            self.app.snapshots(name).mint(
                decision_head=log.head(), reason=action,
                atlas_pages=self._atlas_binding(name, log),
                data_hashes=self._data_binding(name),
            )
            return p

    def _atlas_binding(self, name: str, log) -> dict:
        """§7.3/§7.5: even a lifecycle Snapshot binds the project's
        Atlas page versions, so a project-spanning diff/checkout is
        never hollow (HIGH-2 — completes it past the workflow mints)."""
        from helix.snapshot import project_atlas_binding

        return project_atlas_binding(
            self.app.store.index, name, None, log.entries())

    def _data_binding(self, name: str) -> dict:
        """Lifecycle Snapshots also bind data hashes (§7.6) so the
        final freeze Snapshot's repro is complete, not hollow."""
        from helix.cas import project_data_hashes

        return project_data_hashes(self.app, name)

    def promote(self, name: str, to: Optional[str] = None) -> Project:
        p = self.get(name)
        cur = p.rung
        if cur not in LADDER:
            raise LadderError(f"{name!r} is {cur}; cannot promote")
        i = LADDER.index(cur)
        target = to or (LADDER[i + 1] if i + 1 < len(LADDER) else None)
        if target is None:
            raise LadderError(f"{name!r} is already at the top ('published')")
        if target not in LADDER or LADDER.index(target) <= i:
            raise LadderError(
                f"promote target must be a higher rung than {cur!r}"
            )
        return self._change_tier(
            name, RUNG_TO_TIER[target], action="promote",
            rationale="Promoted up the lifecycle ladder",
        )

    def demote(self, name: str, to: Optional[str] = None) -> Project:
        p = self.get(name)
        cur = p.rung
        if cur == "archived":
            raise LadderError(f"{name!r} is archived")
        if cur not in LADDER:
            raise LadderError(f"cannot demote from {cur!r}")
        i = LADDER.index(cur)
        if to is not None:
            if to == "archived":
                return self.archive(name)
            if to not in LADDER or LADDER.index(to) >= i:
                raise LadderError(
                    f"demote target must be a lower rung than {cur!r}"
                )
            return self._change_tier(
                name, RUNG_TO_TIER[to], action="demote",
                rationale="Demoted down the lifecycle ladder",
            )
        if i == 0:  # demote past the bottom rung == archive (§9.7)
            return self.archive(name)
        return self._change_tier(
            name, RUNG_TO_TIER[LADDER[i - 1]], action="demote",
            rationale="Demoted down the lifecycle ladder",
        )

    def freeze(self, name: str, status: str = "published") -> Project:
        if status == "paused":
            with self.app.wq.lock:
                snaps = self.app.snapshots(name)
                log = self.app.decision_log(name)
                log.append(stage="lifecycle", action="freeze:paused",
                           rationale="Project paused; active line parked.",
                           auto_or_human="human")
                snaps.park(decision_head=log.head(), reason="freeze:paused")
                return self.get(name)
        return self._change_tier(
            name, "published", action="freeze",
            rationale="Frozen for publication",
        )

    def archive(self, name: str) -> Project:
        return self._change_tier(
            name, "archived", action="archive",
            rationale="Archived (abandoned or superseded)",
        )
