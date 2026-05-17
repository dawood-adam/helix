"""The Atlas link graph (HELIX.md §8.1).

Atlas is a graph natively: pages = nodes, ``[[wikilinks]]`` = edges.
This module extracts and resolves those edges so the retriever can
traverse by hops (§8.2-8.6) and the linter can find broken/duplicate/
orphan links (§6.4).

Adjacency is cached by a cheap signature (page count + version sum) so
repeated retrievals don't re-read every body; it rebuilds only when a
write actually changed something.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from helix.atlas.store import AtlasStore

# [[target]] / [[target#frag]] / [[target|alias]] (Obsidian forms).
_WIKILINK = re.compile(r"\[\[([^\[\]]+?)\]\]")


def extract_links(body: str) -> List[str]:
    """Raw link targets in document order (duplicates preserved so the
    linter can flag them). Alias/fragment are stripped to the target."""
    out: List[str] = []
    for m in _WIKILINK.finditer(body or ""):
        target = m.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            out.append(target)
    return out


@dataclass
class AtlasGraph:
    # node id -> resolved out-neighbour ids (deduped, order-preserved)
    adj: Dict[str, List[str]] = field(default_factory=dict)
    # node id -> in-neighbour ids
    radj: Dict[str, List[str]] = field(default_factory=dict)
    # node id -> raw link targets that did NOT resolve (broken links)
    unresolved: Dict[str, List[str]] = field(default_factory=dict)
    # node id -> raw targets seen more than once (duplicate links)
    duplicates: Dict[str, List[str]] = field(default_factory=dict)
    _sig: Tuple[int, int] = (0, 0)

    @staticmethod
    def signature(store: AtlasStore) -> Tuple[int, int]:
        entries = list(store.index)
        return (len(entries), sum(e.version for e in entries))

    @classmethod
    def build(cls, store: AtlasStore) -> "AtlasGraph":
        g = cls(_sig=cls.signature(store))
        for e in store.index:
            g.adj.setdefault(e.id, [])
            seen: Dict[str, int] = {}
            for raw in extract_links(
                _safe_body(store, e.path)
            ):
                seen[raw] = seen.get(raw, 0) + 1
                target = store.index.resolve_link(raw)
                if target is None:
                    g.unresolved.setdefault(e.id, []).append(raw)
                    continue
                if target.id not in g.adj[e.id] and target.id != e.id:
                    g.adj[e.id].append(target.id)
                    g.radj.setdefault(target.id, []).append(e.id)
            dups = [r for r, n in seen.items() if n > 1]
            if dups:
                g.duplicates[e.id] = dups
        return g

    def out_degree(self, node_id: str) -> int:
        return len(self.adj.get(node_id, ()))

    def is_orphan(self, node_id: str) -> bool:
        """No inbound and no outbound edges (§6.4 orphan)."""
        return not self.adj.get(node_id) and not self.radj.get(node_id)


def _safe_body(store: AtlasStore, rel_path: str) -> str:
    try:
        from helix.pages import Page

        return Page.from_markdown(store.abspath(rel_path).read_text()).body
    except (OSError, ValueError):
        return ""


def canonical_link(store: AtlasStore, raw: str) -> Optional[str]:
    """Normalise a link target to its canonical handle (§8.6 'normalises
    titles'); None if it doesn't resolve."""
    entry = store.index.resolve_link(raw)
    return entry.handle if entry else None


def normalise_links(store: AtlasStore, body: str) -> Tuple[str, List[str]]:
    """Rewrite every resolvable ``[[target]]`` to its canonical handle
    (preserving ``#frag``/``|alias``) and collect targets that do not
    resolve. Returns ``(new_body, unresolved_targets)`` (§8.6)."""
    unresolved: List[str] = []

    def repl(m: "re.Match[str]") -> str:
        inner = m.group(1)
        target, sep, tail = _split_inner(inner)
        entry = store.index.resolve_link(target)
        if entry is None:
            unresolved.append(target)
            return m.group(0)
        return f"[[{entry.handle}{sep}{tail}]]" if sep else f"[[{entry.handle}]]"

    return _WIKILINK.sub(repl, body or ""), unresolved


def _split_inner(inner: str) -> Tuple[str, str, str]:
    """``target#frag`` / ``target|alias`` -> (target, sep, tail)."""
    for sep in ("#", "|"):
        if sep in inner:
            target, tail = inner.split(sep, 1)
            return target.strip(), sep, tail
    return inner.strip(), "", ""
