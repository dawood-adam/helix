"""The Atlas write model — one ordered writer (HELIX.md §6.4.1, §7.2).

Atlas is written by the project workflow, the async Watcher, the
Maintainer *and* the human in Obsidian. Concurrent prose edits can't be
auto-merged, so there are no free-for-all writes:

* **All writes go through one append-then-apply queue.** A writer
  submits an :class:`Intent`; a single serial applier validates
  ``base_version``, applies the op, bumps the page version, and persists
  the index. One writer at a time, globally (a process-wide lock).
* **Optimistic concurrency on ``base_version``.** If the page changed
  since the writer read it, the op is rejected with :class:`Conflict`
  and the writer re-reads and retries (:meth:`WriteQueue.submit_with_retry`).
* **Human (Obsidian) edits are first-class** — ingested as queue ops so
  a manual edit and an agent edit to the same page serialize instead of
  clobbering. A human save to a ``generated: true`` file is the one
  special case: not ingested, not clobbered, but returned as a
  :class:`FoldSuggestion` to be folded back into the source (§7.2).

Durability: the **full intent** (op, ref, base_version *and payload*,
matching the §6.4.1 ``{page_id, op, payload, base_version}`` record)
plus its outcome are appended to a write-ahead log
(``.helix/wal.jsonl``) before the index is persisted, so every
attempted write is recorded for audit/replay. NOTE: automated
crash-recovery *replay* from the WAL is not yet implemented — the WAL
is currently an audit/forensic record, not a self-healing journal.

Scope of the writer lock: this is a **process-global** lock
(:attr:`WriteQueue.lock`). Decision-log and Snapshot writes serialize
on the *same* lock, so the single-ordered-writer / strongest-consistency
guarantee (§6.4.1, §7) holds across all canonical state in-process.
Cross-process serialization (CLI vs. the Watcher cron vs. the Obsidian
filesystem watcher) requires a filesystem lock and is a known gap to
close before the Watcher ships (build step 13).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Optional

from helix.ids import PageEntry, UnknownReference, make_handle, new_page_id
from helix.atlas.store import AtlasStore, default_path_for
from helix.atlas.graph import normalise_links
from helix.atlas.proclock import ProcessLock
from helix.pages import Page, is_generated_markdown


@dataclass
class Intent:
    """A requested write. ``base_version`` is the version the writer saw."""

    op: str  # create | upsert | update | set_status | ingest_human_edit
    payload: Dict[str, Any] = field(default_factory=dict)
    ref: Optional[str] = None
    base_version: Optional[int] = None


# ---- results --------------------------------------------------------


@dataclass
class Applied:
    page_id: str
    handle: str
    version: int
    path: str
    op: str
    ok: bool = True


@dataclass
class Conflict:
    """Optimistic-concurrency rejection: re-read and retry (§6.4.1)."""

    ref: str
    expected_version: int
    actual_version: int
    ok: bool = False


@dataclass
class FoldSuggestion:
    """A human edited a ``generated: true`` file.

    Not ingested (it would vanish on the next regenerate) and not
    clobbered. The delta is routed back as a one-tap fold into the
    canonical source (§7.2). Resolving the fold is the owning
    component's job (e.g. DecisionLog writes prose into a JSON
    ``rationale``); the queue only refuses to lose or eat the edit.
    """

    path: str
    page_id: Optional[str]
    human_text: str
    ok: bool = False


@dataclass
class LinkError:
    """Write-time link hygiene rejection (§8.6): a non-generated page
    linked to a page that does not exist. Broken links never enter the
    graph in the first place. Deterministic — not worth retrying."""

    ref: str
    unresolved: list
    ok: bool = False


WriteResult = Applied | Conflict | FoldSuggestion | LinkError


class WriteQueue:
    """Process-global single ordered writer over an :class:`AtlasStore`."""

    def __init__(self, store: AtlasStore):
        self.store = store
        # Optional post-apply hook (set by the app facade) for the §6.4
        # continuous incremental lint. Never allowed to break a write.
        self.on_applied = None
        # Process-GLOBAL write lock (review finding #7): re-entrant
        # in-process + an advisory file lock so concurrent `helix`
        # processes (cron Watcher ∥ interactive CLI) serialise too.
        self._lock = ProcessLock(store.layout.helix_dir / "write.lock")
        self._wal = store.layout.wal_path
        self._wal.parent.mkdir(parents=True, exist_ok=True)
        self._seq = self._last_seq()

    @property
    def lock(self) -> ProcessLock:
        """The process-global Atlas write lock.

        DecisionLog and SnapshotStore serialize their canonical-state
        writes on this same lock so the §7 'strongest consistency'
        contract holds for *all* durable artifacts, not just pages, and
        — via the file lock in :class:`ProcessLock` — across concurrent
        ``helix`` processes too, not only threads. Re-entrant, so a
        decision append that regenerates the narrative (or a
        ProjectStore compound op that nests a mint) does not
        self-deadlock.
        """
        return self._lock

    # ---- write-ahead log --------------------------------------------

    def _last_seq(self) -> int:
        if not self._wal.exists():
            return 0
        last = 0
        for line in self._wal.read_text().splitlines():
            if line.strip():
                last = max(last, json.loads(line).get("seq", 0))
        return last

    def _wal_append(self, record: Dict[str, Any]) -> None:
        with self._wal.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    # ---- public API --------------------------------------------------

    def submit(self, intent: Intent) -> WriteResult:
        """Apply one intent under the global write lock."""
        with self._lock:
            self._seq += 1
            seq = self._seq
            # Record the FULL intent (§6.4.1: {page_id, op, payload,
            # base_version}) so the WAL is genuinely replayable, not a
            # lossy trace.
            self._wal_append(
                {
                    "seq": seq,
                    "ts": time.time(),
                    "op": intent.op,
                    "ref": intent.ref,
                    "base_version": intent.base_version,
                    "payload": intent.payload,
                    "status": "pending",
                }
            )
            try:
                result = self._apply(intent)
            except Exception as exc:  # noqa: BLE001 — record then re-raise
                self._wal_append({"seq": seq, "status": "error", "error": repr(exc)})
                raise
            status = "applied" if result.ok else "rejected"
            outcome: Dict[str, Any] = {"seq": seq, "status": status}
            if isinstance(result, Applied):
                outcome.update(page_id=result.page_id, version=result.version,
                               path=result.path)
            self._wal_append(outcome)
            if result.ok:
                self.store.index.save()
                if self.on_applied is not None and isinstance(result, Applied):
                    try:
                        self.on_applied(result)
                    except Exception:  # noqa: BLE001 — lint can't break writes
                        pass
            return result

    def submit_with_retry(
        self,
        build_intent: Callable[[], Intent],
        *,
        max_attempts: int = 5,
    ) -> WriteResult:
        """Re-read + retry on :class:`Conflict` (the §6.4.1 retry loop).

        ``build_intent`` must re-read the page each call so a fresh
        ``base_version`` is used; otherwise it would conflict forever.
        """
        result: WriteResult = Conflict("?", -1, -1)
        for _ in range(max_attempts):
            result = self.submit(build_intent())
            # Conflict is the only retryable outcome; FoldSuggestion and
            # LinkError are deterministic and terminal.
            if result.ok or isinstance(result, (FoldSuggestion, LinkError)):
                return result
        return result

    # ---- apply (single serial applier) ------------------------------

    def _apply(self, intent: Intent) -> WriteResult:
        if intent.op == "create":
            return self._apply_create(intent, generated=False)
        if intent.op == "upsert":
            return self._apply_upsert(intent)
        if intent.op == "update":
            return self._apply_update(intent)
        if intent.op == "set_status":
            return self._apply_set_status(intent)
        if intent.op == "ingest_human_edit":
            return self._apply_human_edit(intent)
        raise ValueError(f"unknown op: {intent.op!r}")

    def _hygiene(self, page: Page, ref: str):
        """§8.6 link hygiene. Generated projections are exempt (their
        links come from the §7.2 renderer, which already falls back
        safely) — enforcing here would break the decision-log invariant.
        For authored pages: normalise resolvable links to canonical
        handles; reject if any link target does not exist.

        Returns ``LinkError`` to reject, else mutates ``page.body`` to
        the normalised form and returns ``None``.
        """
        if page.generated:
            return None
        new_body, unresolved = normalise_links(self.store, page.body)
        if unresolved:
            return LinkError(ref=ref, unresolved=unresolved)
        page.body = new_body
        return None

    def _apply_create(self, intent: Intent, *, generated: bool) -> WriteResult:
        p = intent.payload
        page = Page(
            id=new_page_id(),
            title=p["title"],
            type=p["type"],
            status=p.get("status", "scratch"),
            body=p.get("body", ""),
            summary=p.get("summary", ""),
            tags=list(p.get("tags", [])),
            referenced_by=list(p.get("referenced_by", [])),
            generated=generated,
            private=bool(p.get("private", False)),   # §9.9 banner
            extra=dict(p.get("extra", {})),
        )
        handle = p.get("handle") or make_handle(page.type, page.title)
        rel = p.get("path") or default_path_for(page)
        # Check uniqueness BEFORE any filesystem write — otherwise a
        # colliding create would clobber the existing page's bytes on
        # disk and only then raise (data loss; review finding #1).
        if self.store.index.has(handle):
            raise ValueError(
                f"handle {handle!r} already maps to a different page"
            )
        link_err = self._hygiene(page, handle)
        if link_err is not None:
            return link_err  # reject before any filesystem mutation
        self.store._write_file(rel, page.to_markdown())
        self.store.index.register(
            PageEntry(
                id=page.id,
                path=rel,
                version=1,
                type=page.type,
                status=page.status,
                title=page.title,
                handle=handle,
                summary=page.summary,
            )
        )
        return Applied(page.id, handle, 1, rel, intent.op)

    def _apply_upsert(self, intent: Intent) -> Applied:
        """Create-or-replace by handle. Used for generated files (§7.2)."""
        p = intent.payload
        handle = p.get("handle") or make_handle(p["type"], p["title"])
        if not self.store.index.has(handle):
            return self._apply_create(intent, generated=True)
        entry = self.store.index.resolve(handle)
        page = Page(
            id=entry.id,
            title=p.get("title", entry.title),
            type=entry.type,
            status=entry.status,
            body=p.get("body", ""),
            summary=p.get("summary", ""),
            tags=list(p.get("tags", [])),
            generated=True,
            extra=dict(p.get("extra", {})),
        )
        self.store._write_file(entry.path, page.to_markdown())
        version = self.store.index.bump_version(entry.id)
        self.store.index.update_meta(
            entry.id, title=page.title, summary=page.summary
        )
        return Applied(entry.id, handle, version, entry.path, intent.op)

    def _resolve_or_conflict(
        self, intent: Intent
    ) -> tuple[Optional[PageEntry], Optional[Conflict]]:
        try:
            entry = self.store.index.resolve(intent.ref)  # type: ignore[arg-type]
        except UnknownReference:
            raise
        if intent.base_version is None or intent.base_version != entry.version:
            return None, Conflict(
                intent.ref or "?",
                expected_version=intent.base_version
                if intent.base_version is not None
                else -1,
                actual_version=entry.version,
            )
        return entry, None

    def _apply_update(self, intent: Intent) -> WriteResult:
        entry, conflict = self._resolve_or_conflict(intent)
        if conflict:
            return conflict
        assert entry is not None
        page = Page.from_markdown(self.store.abspath(entry.path).read_text())
        p = intent.payload
        if "body" in p:
            page.body = p["body"]
        if "summary" in p:
            page.summary = p["summary"]
        if "tags" in p:
            page.tags = list(p["tags"])
        if "title" in p:
            page.title = p["title"]
        if "referenced_by" in p:
            page.referenced_by = list(p["referenced_by"])
        link_err = self._hygiene(page, entry.handle)
        if link_err is not None:
            return link_err
        import datetime as _dt

        page.updated = _dt.date.today().isoformat()
        self.store._write_file(entry.path, page.to_markdown())
        version = self.store.index.bump_version(entry.id)
        self.store.index.update_meta(
            entry.id, title=page.title, summary=page.summary
        )
        return Applied(entry.id, entry.handle, version, entry.path, intent.op)

    def _apply_set_status(self, intent: Intent) -> WriteResult:
        """Promote/demote/archive. id + handle stay stable (§6.2).

        The path may change (a new tier folder); the index is updated so
        every uuid/handle reference keeps resolving — no pointer breaks.
        """
        entry, conflict = self._resolve_or_conflict(intent)
        if conflict:
            return conflict
        assert entry is not None
        new_status = intent.payload["status"]
        page = Page.from_markdown(self.store.abspath(entry.path).read_text())
        page.status = new_status
        import datetime as _dt

        page.updated = _dt.date.today().isoformat()
        new_rel = default_path_for(page)
        self.store._write_file(entry.path, page.to_markdown())
        if new_rel != entry.path:
            self.store._move_file(entry.path, new_rel)
            self.store.index.set_path(entry.id, new_rel)
        version = self.store.index.bump_version(entry.id)
        self.store.index.update_meta(
            entry.id, status=new_status, summary=page.summary
        )
        return Applied(entry.id, entry.handle, version, new_rel, intent.op)

    def _apply_human_edit(self, intent: Intent) -> WriteResult:
        """Filesystem-watcher path: a human saved a file in Obsidian.

        Pass ``base_version`` = the version the watcher last observed
        for the page to get clobber-safe optimistic concurrency. Without
        it the edit is taken as last-writer (serialized, never racy, but
        it can overwrite an interleaved agent write — the watcher is
        responsible for tracking the observed version).
        """
        rel = intent.payload["rel_path"]
        text = intent.payload["text"]
        if is_generated_markdown(text):
            # Never ingest (vanishes on regenerate), never clobber.
            pid = None
            try:
                pid = Page.from_markdown(text).id
            except ValueError:
                pass
            return FoldSuggestion(path=rel, page_id=pid, human_text=text)
        page = Page.from_markdown(text)
        if not self.store.index.has(page.id):
            # Human created a brand-new file in the vault.
            h = make_handle(page.type, page.title)
            link_err = self._hygiene(page, h)
            if link_err is not None:
                return link_err
            self.store._write_file(rel, page.to_markdown())
            self.store.index.register(
                PageEntry(
                    id=page.id,
                    path=rel,
                    version=1,
                    type=page.type,
                    status=page.status,
                    title=page.title,
                    handle=h,
                    summary=page.summary,
                )
            )
            return Applied(page.id, h, 1, rel, intent.op)
        entry = self.store.index.resolve(page.id)
        # §6.4.1: a human edit and an agent edit to the same page must
        # serialize instead of clobbering. If the watcher observed the
        # page at a known version, reject when it moved underneath the
        # human (review finding #5) so the delta can be re-surfaced
        # rather than silently overwriting the agent's write.
        base = intent.base_version
        if base is not None and base != entry.version:
            return Conflict(page.id, expected_version=base,
                            actual_version=entry.version)
        link_err = self._hygiene(page, entry.handle)
        if link_err is not None:
            return link_err
        self.store._write_file(entry.path, page.to_markdown())
        version = self.store.index.bump_version(entry.id)
        self.store.index.update_meta(
            entry.id, status=page.status, title=page.title,
            summary=page.summary,
        )
        return Applied(entry.id, entry.handle, version, entry.path, intent.op)
