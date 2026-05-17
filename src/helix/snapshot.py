"""Snapshot — the composite commit for the whole project (HELIX.md §7.3-7.4).

The decision log alone is an event log, not version control: you can
replay what happened but not *check out the project as it was at
decision 4*. A **Snapshot** is a small content-addressed object that
atomically binds the entire project state **by reference**: the
decision head, the code git sha, Atlas page versions (by id), data
hashes, the env lock and the resolved model routing (§11.2).

Logging and Snapshotting are decoupled (§7.3): *every* decision is
logged (cheap, replayable), but a Snapshot is minted only at a
**meaningful point** — every HITL gate decision, every branch/park/
resume, every freeze. A contiguous run of pure auto-routed steps
**coalesces into the next meaningful Snapshot**. This module provides
the mint/branch/resolve primitives; *when* to mint (the coalescing
policy) is enforced by the workflow caller — ``checkout`` of a
coalesced auto-routed decision resolves to its enclosing Snapshot, a
well-defined point (:meth:`SnapshotStore.enclosing`).
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from helix.atlas.store import AtlasLayout


def project_atlas_binding(index, project: str,
                          scout_ref: Optional[str],
                          decision_entries) -> Dict[str, str]:
    """§7.3: the Atlas page versions (by id) a Snapshot binds — the
    project overview, the Scout summary, and every decision evidence
    page, at their *current* versions. Shared by the workflow gate
    mints AND the ProjectStore lifecycle mints so **every** Snapshot is
    complete (§7.5), not just the workflow ones (HIGH-2)."""
    from helix.ids import make_handle

    refs = {make_handle("project", project)}
    if scout_ref:
        refs.add(scout_ref)
    for e in decision_entries:
        refs.update(str(r) for r in e.get("evidence", []))
    out: Dict[str, str] = {}
    for ref in refs:
        try:
            entry = index.resolve(ref)
        except KeyError:
            continue                       # unresolvable → not bound
        out[entry.handle] = f"v{entry.version}"
    return out


def _decision_number(decision_id: Optional[str]) -> int:
    """``proj#decision-7`` -> 7. ``None``/malformed -> 0 (project start)."""
    if not decision_id or "-" not in decision_id:
        return 0
    tail = decision_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


@dataclass
class Snapshot:
    """A composite commit. ``id`` is ``snap:<project>@<seq>``; integrity
    is checkable via :attr:`content_hash` (used by ``helix doctor``)."""

    id: str
    seq: int
    branch: str
    parent: Optional[str]
    decision_head: Optional[str]
    code_sha: Optional[str] = None
    atlas_pages: Dict[str, str] = field(default_factory=dict)
    data_hashes: Dict[str, str] = field(default_factory=dict)
    env_lock: Optional[str] = None
    model_routing: Dict[str, str] = field(default_factory=dict)
    reason: str = ""
    content_hash: str = ""

    def _binding(self) -> Dict[str, Any]:
        return {
            "decision_head": self.decision_head,
            "code_sha": self.code_sha,
            "atlas_pages": self.atlas_pages,
            "data_hashes": self.data_hashes,
            "env_lock": self.env_lock,
            "model_routing": self.model_routing,
            "branch": self.branch,
            "parent": self.parent,
        }

    def compute_hash(self) -> str:
        blob = json.dumps(self._binding(), sort_keys=True)
        return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()

    def verify(self) -> bool:
        return self.content_hash == self.compute_hash()

    def binding_diff(self, other: "Snapshot") -> Dict[str, Any]:
        """Semantic delta between two Snapshots — cheap because the
        Snapshot binds by reference (the §7.5 ``helix diff`` payload)."""
        delta: Dict[str, Any] = {}
        a, b = self._binding(), other._binding()
        for key in ("decision_head", "code_sha", "env_lock", "branch"):
            if a[key] != b[key]:
                delta[key] = {"from": a[key], "to": b[key]}
        for key in ("atlas_pages", "data_hashes", "model_routing"):
            changed = {
                k: {"from": a[key].get(k), "to": b[key].get(k)}
                for k in set(a[key]) | set(b[key])
                if a[key].get(k) != b[key].get(k)
            }
            if changed:
                delta[key] = changed
        return delta


class SnapshotStore:
    """Per-project Snapshot DAG + branch refs (parked lines are resumable)."""

    DEFAULT_BRANCH = "main"

    def __init__(
        self,
        project: str,
        layout: AtlasLayout,
        *,
        lock: Optional["threading.RLock"] = None,
    ):
        self.project = project
        self.layout = layout
        self._dir = layout.snapshots_dir(project)
        self._refs_path = layout.refs_path(project)
        self._dir.mkdir(parents=True, exist_ok=True)
        # The Snapshot DAG is the keystone (§7.3, §13). Mutations must
        # serialize on the SAME process-global lock as page and
        # decision-log writes so the §7 'strongest consistency' holds.
        # Production wiring passes ``write_queue.lock``; the per-instance
        # default keeps standalone use correct for a single instance.
        self._lock = lock or threading.RLock()
        self._refs = self._load_refs()

    def _sync(self) -> None:
        """Re-read refs from disk under the lock so a stale in-memory
        instance can't overwrite another writer's mint (finding #4)."""
        self._refs = self._load_refs()

    # ---- refs --------------------------------------------------------

    def _load_refs(self) -> Dict[str, Any]:
        refs = {
            "active_branch": self.DEFAULT_BRANCH,
            "branches": {},          # branch -> head snapshot id
            "parked": [],
            "salvaged": [],          # branches whose learning was salvaged
            "names": {},             # tag/release name -> snapshot id
            "counter": 0,
        }
        if self._refs_path.exists():
            refs.update(json.loads(self._refs_path.read_text()))
            refs.setdefault("salvaged", [])   # back-compat for old refs
            refs.setdefault("names", {})
        return refs

    def _save_refs(self) -> None:
        tmp = self._refs_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._refs, indent=2, sort_keys=True))
        tmp.replace(self._refs_path)

    @property
    def active_branch(self) -> str:
        return self._refs["active_branch"]

    def head(self, branch: Optional[str] = None) -> Optional[str]:
        return self._refs["branches"].get(branch or self.active_branch)

    def branches(self) -> Dict[str, str]:
        return dict(self._refs["branches"])

    def is_parked(self, branch: str) -> bool:
        return branch in self._refs["parked"]

    # ---- snapshot IO -------------------------------------------------

    def _path(self, seq: int):
        return self._dir / f"{seq}.json"

    def get(self, snapshot_id: str) -> Snapshot:
        seq = int(snapshot_id.split("@")[-1])
        return Snapshot(**json.loads(self._path(seq).read_text()))

    def all(self) -> List[Snapshot]:
        snaps = [
            Snapshot(**json.loads(p.read_text()))
            for p in self._dir.glob("*.json")
            if p.name != "refs.json"
        ]
        return sorted(snaps, key=lambda s: s.seq)

    # ---- minting (the keystone primitive) ----------------------------

    _AUTO = "__auto__"

    def mint(
        self,
        *,
        decision_head: Optional[str],
        branch: Optional[str] = None,
        parent: Optional[str] = _AUTO,
        set_active: bool = True,
        code_sha: Optional[str] = None,
        atlas_pages: Optional[Dict[str, str]] = None,
        data_hashes: Optional[Dict[str, str]] = None,
        env_lock: Optional[str] = None,
        model_routing: Optional[Dict[str, str]] = None,
        reason: str = "",
    ) -> Snapshot:
        """Mint a Snapshot at a meaningful point. Cheap: references only.

        ``reason`` records *why* this point was meaningful (gate / branch
        / park / resume / freeze) — auto-routed steps must not call this;
        they coalesce into the next meaningful Snapshot (§7.3).
        ``parent`` defaults to the branch's current head; ``set_active``
        lets a fork mint without switching the working branch.
        """
        with self._lock:
            self._sync()  # never compute seq from a stale counter
            branch = branch or self.active_branch
            seq = self._refs["counter"] + 1
            snap = Snapshot(
                id=f"snap:{self.project}@{seq}",
                seq=seq,
                branch=branch,
                parent=self._refs["branches"].get(branch)
                if parent == self._AUTO
                else parent,
                decision_head=decision_head,
                code_sha=code_sha,
                atlas_pages=dict(atlas_pages or {}),
                data_hashes=dict(data_hashes or {}),
                env_lock=env_lock,
                model_routing=dict(model_routing or {}),
                reason=reason,
            )
            snap.content_hash = snap.compute_hash()
            self._path(seq).write_text(json.dumps(asdict(snap), indent=2))
            self._refs["counter"] = seq
            self._refs["branches"][branch] = snap.id
            if set_active:
                self._refs["active_branch"] = branch
            self._save_refs()
            return snap

    # ---- branches (first-class research lines, §7.4) -----------------

    def fork(self, new_branch: str, *, decision_head: Optional[str], **kw) -> Snapshot:
        """Fork the current line into a named parallel research line.

        The branch op itself mints a Snapshot (§7.3). Active branch is
        unchanged — ``resume(new_branch)`` switches to work on it.
        """
        with self._lock:
            self._sync()
            if new_branch in self._refs["branches"]:
                raise ValueError(f"branch already exists: {new_branch!r}")
            source = self.active_branch
            source_head = self._refs["branches"].get(source)
            return self.mint(
                decision_head=decision_head,
                branch=new_branch,
                parent=source_head,
                set_active=False,
                reason=f"fork from {source}",
                **kw,
            )

    def park(self, branch: Optional[str] = None, *, decision_head: Optional[str] = None,
             reason: str = "parked") -> Snapshot:
        """Pause a line; its Snapshot is retained and resumable (§7.4).

        Parking never changes the active branch (review finding #2):
        you park a line to step away from it, then explicitly
        ``resume`` another line to switch.
        """
        with self._lock:
            self._sync()
            branch = branch or self.active_branch
            if branch not in self._refs["branches"]:
                raise ValueError(f"unknown branch: {branch!r}")
            snap = self.mint(decision_head=decision_head, branch=branch,
                              set_active=False, reason=reason)
            if branch not in self._refs["parked"]:
                self._refs["parked"].append(branch)
            self._save_refs()
            return snap

    def resume(self, branch: str, *, decision_head: Optional[str] = None) -> Snapshot:
        """Bring a parked line back and make it the active branch (§7.4)."""
        with self._lock:
            self._sync()
            if branch not in self._refs["branches"]:
                raise ValueError(f"unknown branch: {branch!r}")
            snap = self.mint(
                decision_head=decision_head, branch=branch, reason="resume"
            )
            if branch in self._refs["parked"]:
                self._refs["parked"].remove(branch)
            self._save_refs()
            return snap

    def salvage(self, branch: str, *, decision_head: Optional[str] = None
                ) -> Snapshot:
        """Park a dead line but keep its Snapshot resumable, and mark it
        salvaged so Loom shows it distinctly (§6.4, §7.7)."""
        with self._lock:
            self._sync()
            if branch not in self._refs["branches"]:
                raise ValueError(f"unknown branch: {branch!r}")
            snap = self.mint(decision_head=decision_head, branch=branch,
                              set_active=False, reason="salvage")
            if branch not in self._refs["parked"]:
                self._refs["parked"].append(branch)
            if branch not in self._refs["salvaged"]:
                self._refs["salvaged"].append(branch)
            self._save_refs()
            return snap

    def is_salvaged(self, branch: str) -> bool:
        return branch in self._refs.get("salvaged", [])

    def name(self, name: str, snapshot_id: str) -> None:
        """Tag/release: any Snapshot is nameable and returnable (§7.5)."""
        with self._lock:
            self._sync()
            self._refs["names"][name] = snapshot_id
            self._save_refs()

    def resolve_name(self, name: str) -> Optional[str]:
        return self._refs.get("names", {}).get(name)

    def names(self) -> Dict[str, str]:
        return dict(self._refs.get("names", {}))

    # ---- checkout / resolution (§7.3 coalescing) ---------------------

    def enclosing(self, decision_id: str) -> Optional[Snapshot]:
        """The Snapshot a decision id checks out to.

        A coalesced auto-routed decision has no Snapshot of its own;
        ``helix checkout`` resolves it to its **enclosing** Snapshot —
        the earliest meaningful Snapshot at or after that decision.
        """
        want = _decision_number(decision_id)
        candidates = [
            s for s in self.all() if _decision_number(s.decision_head) >= want
        ]
        return min(candidates, key=lambda s: s.seq) if candidates else None
