"""Stable page ids + the id->path index (HELIX.md §6.2, §8.6).

Identity is the ``id`` (a uuid4), never the path. Every Forge-state
pointer, decision-log ``atlas_ref``/``evidence`` entry, Snapshot
``atlas_pages`` key, and ``[[wikilink]]`` resolves through this index.
Promotion moves files and rewrites link *text*, but the underlying id is
unchanged, so moving a page can never break a reference.

Two identifier forms both resolve here:

* the canonical **uuid** (frontmatter ``id``) — the real identity;
* a stable human **handle** ``<prefix>:<slug>`` (e.g. ``concept:odf``,
  ``proj:bowel-length``, ``src:2024-zhang``) used in the decision log
  and Snapshots. The handle is an alias onto the uuid and survives moves.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterator, Optional

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# page type -> handle prefix. The decision log uses these exact prefixes
# (HELIX.md §7.1 evidence/atlas_ref examples: "src:", "proj:", "concept:").
TYPE_TO_PREFIX: Dict[str, str] = {
    "concept": "concept",
    "entity": "entity",
    "method": "method",
    "source": "src",
    "project": "proj",
    "scratch": "scratch",
}
PREFIX_TO_TYPE: Dict[str, str] = {v: k for k, v in TYPE_TO_PREFIX.items()}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def new_page_id() -> str:
    """A fresh stable page id (uuid4)."""
    return str(uuid.uuid4())


def is_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value))


def slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "untitled"


def make_handle(page_type: str, slug_or_title: str) -> str:
    """Build a ``<prefix>:<slug>`` handle for a page type + title/slug."""
    prefix = TYPE_TO_PREFIX.get(page_type)
    if prefix is None:
        raise ValueError(f"unknown page type: {page_type!r}")
    return f"{prefix}:{slugify(slug_or_title)}"


def split_ref(ref: str) -> tuple[str, Optional[str]]:
    """Split an optional ``#fragment`` (e.g. ``proj:x#hypothesis``).

    Returns ``(base_ref, fragment_or_None)``. Fragments are sub-anchors
    inside a page (used by ``wiki_pages_touched``); resolution is by the
    base ref only.
    """
    base, _, fragment = ref.partition("#")
    return base, (fragment or None)


@dataclass
class PageEntry:
    """One row of the index: the current location + metadata for an id.

    ``summary`` lives here on purpose: it is the tier-1 retrieval
    payload (HELIX.md §6.2/§8.2 — "the summary field is what the cheap
    retrieval tier loads"), so anchor ranking never has to open files.
    """

    id: str
    path: str          # relative to the atlas root
    version: int
    type: str
    status: str
    title: str
    handle: str
    summary: str = ""


class UnknownReference(KeyError):
    """Raised when a ref (uuid or handle) is not in the index."""


class IdIndex:
    """Persistent uuid -> location map, with handle aliases.

    Stored as JSON at ``<atlas>/.helix/index.json``. The Atlas write
    layer is the only writer; readers resolve refs through it so a
    rename/promotion is invisible to every pointer.
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._pages: Dict[str, PageEntry] = {}
        self._handles: Dict[str, str] = {}  # handle -> uuid
        if self._path.exists():
            self._load()

    # ---- persistence -------------------------------------------------

    def _load(self) -> None:
        raw = json.loads(self._path.read_text())
        self._pages = {
            pid: PageEntry(**entry) for pid, entry in raw.get("pages", {}).items()
        }
        self._handles = dict(raw.get("handles", {}))

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pages": {pid: asdict(e) for pid, e in self._pages.items()},
            "handles": self._handles,
        }
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(self._path)  # atomic on POSIX

    # ---- mutation (write layer only) ---------------------------------

    def register(self, entry: PageEntry) -> None:
        if entry.handle in self._handles and self._handles[entry.handle] != entry.id:
            raise ValueError(
                f"handle {entry.handle!r} already maps to a different page"
            )
        self._pages[entry.id] = entry
        self._handles[entry.handle] = entry.id

    def set_path(self, page_id: str, new_path: str) -> None:
        """Relocate a page (promotion). The id and handle are unchanged."""
        self._pages[page_id].path = new_path

    def bump_version(self, page_id: str) -> int:
        entry = self._pages[page_id]
        entry.version += 1
        return entry.version

    def update_meta(
        self,
        page_id: str,
        *,
        status: Optional[str] = None,
        title: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> None:
        entry = self._pages[page_id]
        if status is not None:
            entry.status = status
        if title is not None:
            entry.title = title
        if summary is not None:
            entry.summary = summary

    # ---- resolution (readers) ----------------------------------------

    def _id_for(self, ref: str) -> str:
        base, _ = split_ref(ref)
        if is_uuid(base):
            if base not in self._pages:
                raise UnknownReference(ref)
            return base
        if base not in self._handles:
            raise UnknownReference(ref)
        return self._handles[base]

    def resolve(self, ref: str) -> PageEntry:
        """Resolve a uuid or ``prefix:slug`` (with optional ``#frag``)."""
        return self._pages[self._id_for(ref)]

    def path_for(self, ref: str) -> str:
        return self.resolve(ref).path

    def version_for(self, ref: str) -> int:
        return self.resolve(ref).version

    def has(self, ref: str) -> bool:
        try:
            self._id_for(ref)
            return True
        except UnknownReference:
            return False

    def resolve_link(self, text: str) -> Optional[PageEntry]:
        """Resolve a ``[[wikilink]]`` target to a page (or None).

        Tries id/handle first (the canonical agent-written form, §8.6),
        then falls back to a path match (``folder/slug`` with or without
        ``.md``) and finally a case-insensitive title match — so the
        human/Obsidian-friendly forms still resolve into the graph.
        """
        base, _ = split_ref(text)
        base = base.strip()
        try:
            return self._pages[self._id_for(base)]
        except UnknownReference:
            pass
        cand = base if base.endswith(".md") else base + ".md"
        for entry in self._pages.values():
            if entry.path == cand or entry.path == base:
                return entry
        low = base.lower()
        for entry in self._pages.values():
            if entry.title.lower() == low:
                return entry
        return None

    def __iter__(self) -> Iterator[PageEntry]:
        return iter(self._pages.values())

    def __len__(self) -> int:
        return len(self._pages)
