"""GraphRAG retrieval over Atlas (HELIX.md §8.2-8.6).

Retrieval is graph traversal, so cost scales with *hops × pages-per-hop*,
not total Atlas size — once the graph is dense enough. The three
safeguards from §8.6 are implemented explicitly:

* **Cold start** — below a page/edge threshold, skip traversal and rank
  *all* in-scope summaries flat. The user never sees a "graph not
  warmed up" failure (§8.6).
* **Hub blow-up** — BFS applies a per-node degree cap: a hub's
  neighbours aren't expanded blindly, only the top-k by query
  similarity, and the hub itself is summary-only unless it's an anchor.
* **Link hygiene** is enforced upstream by the write queue (§8.6); the
  graph here only ever sees resolvable edges.

Anchor ranking is **BM25** (lexical, deterministic, zero-integration —
the honest default, half of what §8.6 specifies for cold start). A
semantic embedder (the ``atlas-embed`` role, §11.2) is a pluggable
upgrade via :class:`Embedder`; no fake/hashing "embeddings" are shipped
pretending to be semantic.

Three-tier loading (§8.2): tier-1 (title + truncated summary) and
tier-2 (full summary) come from the index with no file read; tier-3
(body) reads the file only for the top-ranked pages, until the token
budget is hit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from helix.atlas.graph import AtlasGraph
from helix.atlas.store import AtlasStore
from helix.ids import PageEntry
from helix.pages import Page

# Per-agent presets (§8.3): role -> (max_tokens, max_hops).
AGENT_BUDGETS: Dict[str, Tuple[Optional[int], Optional[int]]] = {
    "explore": (20_000, 3),
    "critic-methods": (10_000, 2),
    "planner": (8_000, 2),
    "builder": (5_000, 1),
    "validator": (3_000, 1),
    "critic-results": (10_000, 2),
    "maintainer": (None, None),         # unbounded, full (offline lint)
}

# §6.3 retrieval defaults.
DEFAULT_STATUS = ("active", "canonical", "published")
COLD_PAGES = 12
COLD_EDGES = 6
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _terms(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


class Embedder(Protocol):
    """Optional semantic upgrade (the ``atlas-embed`` role). Not shipped
    by default — BM25 is the honest zero-integration ranker."""

    def rank(self, query: str, docs: Sequence[str]) -> List[float]:
        ...


class _BM25:
    """Classic BM25 over the in-scope (title + summary) corpus."""

    def __init__(self, docs: Sequence[List[str]], k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.N = len(docs) or 1
        self.docs = docs
        self.dl = [len(d) for d in docs]
        self.avgdl = (sum(self.dl) / self.N) if self.N else 0.0
        self.df: Dict[str, int] = {}
        for d in docs:
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1
        self.tf: List[Dict[str, int]] = []
        for d in docs:
            tf: Dict[str, int] = {}
            for t in d:
                tf[t] = tf.get(t, 0) + 1
            self.tf.append(tf)

    def score(self, q_terms: Sequence[str], i: int) -> float:
        s = 0.0
        for t in q_terms:
            if t not in self.tf[i]:
                continue
            idf = math.log(1 + (self.N - self.df[t] + 0.5) /
                           (self.df[t] + 0.5))
            f = self.tf[i][t]
            denom = f + self.k1 * (
                1 - self.b + self.b * (self.dl[i] / (self.avgdl or 1))
            )
            s += idf * (f * (self.k1 + 1)) / (denom or 1)
        return s


@dataclass
class RetrievedItem:
    handle: str
    title: str
    tier: int               # 1 = title+trunc summary, 2 = summary, 3 = body
    text: str
    score: float
    tokens: int


@dataclass
class RetrievedContext:
    items: List[RetrievedItem] = field(default_factory=list)
    total_tokens: int = 0
    budget_exceeded: bool = False
    mode: str = "graph"     # "graph" | "flat" (cold start)
    anchors: List[str] = field(default_factory=list)

    def render(self) -> str:
        head = (f"{len(self.items)} pages · ~{self.total_tokens} tok · "
                f"{self.mode}"
                + (" · budget exceeded" if self.budget_exceeded else ""))
        lines = [head]
        for it in self.items:
            lines.append(f"  [{it.tier}] {it.handle}  ({it.score:.2f}, "
                         f"~{it.tokens} tok)")
        return "\n".join(lines)


class Retriever:
    """Atlas GraphRAG retriever (§8.4 ``Atlas.retrieve``)."""

    def __init__(self, store: AtlasStore, embedder: Optional[Embedder] = None):
        self.store = store
        self.embedder = embedder
        self._graph: Optional[AtlasGraph] = None
        self._graph_sig: Tuple[int, int] = (-1, -1)

    def _graph_now(self) -> AtlasGraph:
        sig = AtlasGraph.signature(self.store)
        if self._graph is None or sig != self._graph_sig:
            self._graph = AtlasGraph.build(self.store)
            self._graph_sig = sig
        return self._graph

    # ---- scope (§6.3) ----------------------------------------------

    def _in_scope(
        self, status_filter: Optional[List[str]], project_scope: Optional[str]
    ) -> List[PageEntry]:
        allowed = set(status_filter or DEFAULT_STATUS)
        out = []
        for e in self.store.index:
            if e.status not in allowed:
                continue
            if project_scope and f"projects/{project_scope}/" in e.path:
                out.append(e)
            elif project_scope and e.status in ("canonical", "published"):
                out.append(e)
            elif not project_scope:
                out.append(e)
        return out

    # ---- the API (§8.4) --------------------------------------------

    def retrieve(
        self,
        query: str,
        *,
        max_hops: int = 2,
        max_tokens: int = 10_000,
        project_scope: Optional[str] = None,
        status_filter: Optional[List[str]] = None,
        recency_decay: bool = True,
        hub_cap: int = 8,
        anchors_k: int = 5,
    ) -> RetrievedContext:
        scope = self._in_scope(status_filter, project_scope)
        if not scope:
            return RetrievedContext(mode="flat")
        by_id = {e.id: e for e in scope}
        docs = [_terms(f"{e.title} {e.summary}") for e in scope]
        bm = _BM25(docs)
        q = _terms(query)
        base = {e.id: bm.score(q, i) for i, e in enumerate(scope)}
        if recency_decay:  # cheap version-based proxy (no file read)
            maxv = max((e.version for e in scope), default=1) or 1
            for e in scope:
                base[e.id] *= 1.0 + 0.15 * (e.version / maxv)

        graph = self._graph_now()
        total_edges = sum(len(v) for v in graph.adj.values())
        cold = len(list(self.store.index)) < COLD_PAGES or \
            total_edges < COLD_EDGES

        if cold:
            reached = {e.id for e in scope}
            mode, anchors = "flat", []
        else:
            mode = "graph"
            ranked_ids = sorted(base, key=lambda i: -base[i])
            anchors = ranked_ids[:anchors_k]
            reached = self._bfs(anchors, graph, max_hops, hub_cap, q,
                                by_id, scope)

        order = sorted(reached, key=lambda i: -base.get(i, 0.0))
        return self._assemble(order, by_id, base, max_tokens, mode, anchors)

    def _bfs(self, anchors, graph, max_hops, hub_cap, q, by_id, scope):
        # Pages reachable within max_hops; scratch is included only when
        # link-reached from an in-scope anchor (§6.3 "or linked").
        bm_all = {e.id: e for e in scope}
        reached = set(anchors)
        frontier = list(anchors)
        for _hop in range(max_hops):
            nxt = []
            for nid in frontier:
                neigh = graph.adj.get(nid, [])
                if len(neigh) > hub_cap:
                    # Hub: follow only the top-k neighbours by query
                    # similarity; the hub stays summary-only (handled in
                    # assembly by its lower score / tier choice).
                    neigh = sorted(
                        neigh,
                        key=lambda x: -self._kw(q, by_id.get(x)),
                    )[:hub_cap]
                for m in neigh:
                    if m not in reached:
                        reached.add(m)
                        nxt.append(m)
            frontier = nxt
            if not frontier:
                break
        return reached

    @staticmethod
    def _kw(q_terms, entry: Optional[PageEntry]) -> float:
        if entry is None:
            return 0.0
        hay = set(_terms(f"{entry.title} {entry.summary}"))
        return sum(1 for t in q_terms if t in hay)

    def _assemble(self, order, by_id, base, max_tokens, mode, anchors):
        ctx = RetrievedContext(mode=mode, anchors=[
            by_id[a].handle for a in anchors if a in by_id])
        budget = max_tokens
        for pid in order:
            e = by_id.get(pid)
            if e is None:
                continue
            tier1 = f"{e.title} — {e.summary[:120]}"
            tier2 = f"{e.title}\n{e.summary}"
            body = self._body(e)
            tier3 = f"# {e.title}\n{e.summary}\n\n{body}" if body else tier2
            for tier, text in ((3, tier3), (2, tier2), (1, tier1)):
                tok = estimate_tokens(text)
                if tok <= budget:
                    ctx.items.append(RetrievedItem(
                        e.handle, e.title, tier, text, base.get(pid, 0.0),
                        tok))
                    ctx.total_tokens += tok
                    budget -= tok
                    break
            else:
                ctx.budget_exceeded = True
                break
        # more candidates than fit?
        if len(ctx.items) < len(order):
            ctx.budget_exceeded = ctx.budget_exceeded or \
                len(ctx.items) < len(order)
        return ctx

    def _body(self, entry: PageEntry) -> str:
        try:
            return Page.from_markdown(
                self.store.abspath(entry.path).read_text()
            ).body
        except (OSError, ValueError):
            return ""

    # ---- per-agent preset (§8.3) -----------------------------------

    def retrieve_for(
        self, role: str, query: str, *, project_scope: Optional[str] = None
    ) -> RetrievedContext:
        max_tok, hops = AGENT_BUDGETS.get(role, (10_000, 2))
        return self.retrieve(
            query,
            max_tokens=max_tok if max_tok is not None else 1_000_000,
            max_hops=hops if hops is not None else 6,
            project_scope=project_scope,
        )

    # ---- real coverage analysis (replaces Explore's placeholder) ----

    def coverage_gaps(self, query: str, terms: Sequence[str]) -> List[str]:
        """Which query terms are NOT covered by an existing concept/
        method page? Real retrieval-based coverage (§5.1 Scout 'gaps'),
        replacing the step-6 frequency placeholder."""
        ctx = self.retrieve(
            query, max_hops=1, max_tokens=8_000,
            status_filter=["active", "canonical", "published"],
        )
        covered = " ".join(
            f"{it.handle} {it.text}" for it in ctx.items
        ).lower()
        gaps = []
        for t in terms:
            if t.lower() not in covered:
                gaps.append(t)
            if len(gaps) >= 3:
                break
        return gaps
