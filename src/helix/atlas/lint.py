"""Continuous Atlas lint (HELIX.md §6.4).

Lint runs **continuously**, not only at freeze. Every write triggers an
incremental lint of the touched page; ``helix lint`` / the Maintainer's
freeze lint is the full-corpus sweep.

Deterministic checks only — and honestly so:

* **broken_link**  — a ``[[target]]`` that doesn't resolve (local).
* **duplicate_link** — the same target linked twice on one page (local).
* **stale_claim**  — an inline ``^src:<id>`` provenance marker (§6.2)
  whose source no longer resolves (local).
* **orphan** — no inbound and no outbound edges (corpus-level; full
  sweep only — it's not a cheap per-write property).

**Contradiction** lint is listed in §6.4 but is *not* implemented here:
a real contradiction check needs the LLM critic. It is deliberately
left out rather than faked with a keyword heuristic that would give a
false sense of safety.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from helix.atlas.graph import AtlasGraph, extract_links
from helix.atlas.store import AtlasStore
from helix.pages import Page

_PROVENANCE = re.compile(r"\^(src|dec):([A-Za-z0-9:#._-]+)")

LOCAL_KINDS = ("broken_link", "duplicate_link", "stale_claim")


@dataclass(frozen=True)
class Finding:
    page_id: str
    handle: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.handle}: {self.detail}"


class Linter:
    def __init__(self, store: AtlasStore):
        self.store = store

    # ---- per-page (incremental, cheap, local) -----------------------

    def lint_page(self, ref: str) -> List[Finding]:
        entry = self.store.index.resolve(ref)
        try:
            page = Page.from_markdown(
                self.store.abspath(entry.path).read_text()
            )
        except (OSError, ValueError):
            return []
        out: List[Finding] = []
        seen = {}
        for raw in extract_links(page.body):
            seen[raw] = seen.get(raw, 0) + 1
            if self.store.index.resolve_link(raw) is None:
                out.append(Finding(entry.id, entry.handle, "broken_link",
                                    f"unresolved [[{raw}]]"))
        for raw, n in seen.items():
            if n > 1:
                out.append(Finding(entry.id, entry.handle, "duplicate_link",
                                    f"[[{raw}]] linked {n}×"))
        for kind, pid in _PROVENANCE.findall(page.body):
            # `^src:<slug>` means the ref `src:<slug>` (the prefix is
            # part of the handle, §6.2). `^dec:` points into the
            # decision log, not the page index, so it isn't validated
            # here (honest scoping, not faked).
            if kind == "src" and not self.store.index.has(f"src:{pid}"):
                out.append(Finding(
                    entry.id, entry.handle, "stale_claim",
                    f"^src:{pid} provenance no longer resolves"))
        return out

    # ---- full corpus sweep (helix lint / Maintainer freeze) ---------

    def lint_all(self, project: Optional[str] = None) -> List[Finding]:
        graph = AtlasGraph.build(self.store)
        out: List[Finding] = []
        for entry in self.store.index:
            if project and f"projects/{project}/" not in entry.path \
                    and entry.status not in ("canonical", "published"):
                continue
            out.extend(self.lint_page(entry.handle))
            if graph.is_orphan(entry.id):
                out.append(Finding(entry.id, entry.handle, "orphan",
                                   "no inbound or outbound links"))
        return out
