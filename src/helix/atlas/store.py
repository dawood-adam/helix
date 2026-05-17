"""Atlas filesystem layout + low-level page IO (HELIX.md §6.1).

The store knows *where* a page lives given its type/status (the canonical
folder layout) and how to read/write a page file. It performs **no**
concurrency control or versioning — that is the WriteQueue's job
(§6.4.1). Agents never call the store directly; they go through the
queue. Readers use :meth:`AtlasStore.read_page`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from helix.ids import IdIndex, PageEntry
from helix.pages import Page

# type -> canonical folder once a page is no longer scratch (§6.1).
_TYPE_FOLDER = {
    "concept": "concepts",
    "method": "methods",
    "entity": "entities",
    "source": "sources",
}


def folder_for(page: Page) -> str:
    """The canonical folder (relative to atlas root) for a page.

    Path is a function of (status, type). Promotion changes status and
    therefore the folder; the id is unchanged so references survive.

    A ``project`` page is the exception: it ALWAYS lives at
    ``projects/<slug>/`` regardless of tier/status. Its decision log,
    Snapshots and metadata are keyed to that directory and must not
    move when the lifecycle rung changes (§6.1) — only its frontmatter
    status changes. (This check must precede the scratch/archived
    checks: a notes-tier project is scratch-*status* but must not land
    in scratch/.)
    """
    if page.type == "project":
        return f"projects/{_slug_of(page)}"
    if page.status == "archived":
        return "archive"
    if page.status == "scratch" or page.type == "scratch":
        return "scratch"
    return _TYPE_FOLDER.get(page.type, "scratch")


def _slug_of(page: Page) -> str:
    # handle is "<prefix>:<slug>"; the slug is stable across moves.
    from helix.ids import make_handle

    return make_handle(page.type, page.title).split(":", 1)[1]


def default_path_for(page: Page) -> str:
    """Relative path a page should occupy given its current status/type."""
    if page.type == "project":
        # A project's primary page is its overview.
        return f"{folder_for(page)}/overview.md"
    return f"{folder_for(page)}/{_slug_of(page)}.md"


@dataclass(frozen=True)
class AtlasLayout:
    """Resolved paths for Helix-internal machine state under an atlas root."""

    root: Path

    @property
    def helix_dir(self) -> Path:
        return self.root / ".helix"

    @property
    def index_path(self) -> Path:
        return self.helix_dir / "index.json"

    @property
    def wal_path(self) -> Path:
        return self.helix_dir / "wal.jsonl"

    def project_dir(self, project: str) -> Path:
        return self.root / "projects" / project

    def decision_log_json(self, project: str) -> Path:
        return self.project_dir(project) / ".decision-log.json"

    def decision_log_narrative(self, project: str) -> Path:
        return self.project_dir(project) / "decision-log-narrative.md"

    def snapshots_dir(self, project: str) -> Path:
        return self.project_dir(project) / ".snapshots"

    def refs_path(self, project: str) -> Path:
        return self.snapshots_dir(project) / "refs.json"


class AtlasStore:
    """Low-level page IO over the canonical folder layout."""

    def __init__(self, root: Path):
        self.layout = AtlasLayout(Path(root))
        self.root = self.layout.root
        self.root.mkdir(parents=True, exist_ok=True)
        self.layout.helix_dir.mkdir(parents=True, exist_ok=True)
        self.index = IdIndex(self.layout.index_path)

    # ---- reads -------------------------------------------------------

    def abspath(self, rel: str) -> Path:
        return self.root / rel

    def read_page(self, ref: str) -> Tuple[Page, int]:
        """Resolve a ref (uuid or handle) and return ``(page, version)``.

        The version is authoritative from the index; an agent passes it
        back as ``base_version`` so the WriteQueue can detect a conflict.
        """
        entry: PageEntry = self.index.resolve(ref)
        page = Page.from_markdown(self.abspath(entry.path).read_text())
        return page, entry.version

    def read_raw(self, rel: str) -> str:
        return self.abspath(rel).read_text()

    # ---- low-level writes (WriteQueue only) --------------------------

    def _write_file(self, rel: str, text: str) -> None:
        dest = self.abspath(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(text)
        tmp.replace(dest)  # atomic on POSIX

    def _move_file(self, old_rel: str, new_rel: str) -> None:
        if old_rel == new_rel:
            return
        src = self.abspath(old_rel)
        dest = self.abspath(new_rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dest)
