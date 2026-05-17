"""Explore — the front door / Scout body (HELIX.md §5.1, §9.10, §11.1).

``helix explore "<q>"`` is a one-shot literature scan. Per §11.1 the
**default** body is a zero-integration *built-in lightweight search*
(no API key, no LLM pipeline); FutureHouse / Open Deep Research is the
opt-in upgrade that plugs into the same :class:`SearchBackend` seam.

Faithful to §9.10 / §10: results are written to ``scratch/`` through
the single ordered write queue (§6.4.1), create no gates or
notifications, and surface only as a queue **FYI** ("Explore done — N
papers, M gaps") the user may turn into a project.

Honesty (no fake success): the real backend does a real search
(arXiv, stdlib only). Network failure raises :class:`ExploreError` and
the CLI says so plainly — it never fabricates papers. Tests inject a
deterministic :class:`FakeBackend`.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from helix.atlas.writequeue import Intent

_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z][a-z0-9+-]{3,}")
_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "using", "based",
    "into", "via", "are", "was", "were", "can", "but", "not", "all", "any",
    "data", "model", "models", "method", "methods", "approach", "results",
    "study", "paper", "propose", "proposed", "show", "present", "novel",
}


class ExploreError(RuntimeError):
    """Fail-closed: search could not run. Never returns fake results."""


@dataclass
class Paper:
    source_id: str          # e.g. arXiv id / DOI
    title: str
    authors: List[str]
    abstract: str
    url: str
    published: str
    source: str = "arxiv"

    def slug_title(self) -> str:
        yr = self.published[:4]
        first = (self.authors[0].split()[-1] if self.authors else "anon")
        return f"{yr} {first} {self.title}"

    def summary(self, limit: int = 300) -> str:
        text = _WS.sub(" ", self.abstract).strip()
        if len(text) <= limit:
            return text
        cut = text[:limit]
        dot = cut.rfind(". ")
        return (cut[: dot + 1] if dot > 80 else cut.rstrip() + "…")


class SearchBackend(Protocol):
    def search(
        self, query: str, *, limit: int, scope: Optional[str] = None
    ) -> List[Paper]:
        ...


class ArxivBackend:
    """Built-in default: arXiv public API (no key, stdlib only, §11.1)."""

    ENDPOINT = "http://export.arxiv.org/api/query"

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def search(self, query, *, limit, scope=None) -> List[Paper]:
        q = query if not scope else f"{query} {scope}"
        params = urllib.parse.urlencode({
            "search_query": f"all:{q}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
        })
        req = urllib.request.Request(
            f"{self.ENDPOINT}?{params}",
            headers={"User-Agent": "helix-explore/0.0 (research co-pilot)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ExploreError(
                f"could not reach arXiv ({e}). Explore needs network — "
                f"or enable the FutureHouse/ODR upgrade. No results were "
                f"fabricated."
            ) from e
        return self._parse(raw)

    @staticmethod
    def _parse(raw: bytes) -> List[Paper]:
        def local(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise ExploreError(f"arXiv returned unparseable data: {e}") from e
        papers: List[Paper] = []
        for entry in root:
            if local(entry.tag) != "entry":
                continue
            title = abstract = url = published = ""
            authors: List[str] = []
            for child in entry:
                tag = local(child.tag)
                txt = (child.text or "").strip()
                if tag == "title":
                    title = _WS.sub(" ", txt)
                elif tag == "summary":
                    abstract = txt
                elif tag == "id":
                    url = txt
                elif tag == "published":
                    published = txt
                elif tag == "author":
                    for sub in child:
                        if local(sub.tag) == "name" and sub.text:
                            authors.append(sub.text.strip())
            if title:
                papers.append(Paper(
                    source_id=url.rsplit("/", 1)[-1] or url,
                    title=title, authors=authors, abstract=abstract,
                    url=url, published=published or "", source="arxiv",
                ))
        return papers


class FakeBackend:
    """Deterministic, offline — for tests and the ``fake`` env hook.

    Not a feature: it exists so CLI tests don't hit the network and so
    behaviour is reproducible. ``fail=True`` simulates a network
    outage to exercise the fail-closed path.
    """

    def __init__(self, papers: Optional[List[Paper]] = None,
                 fail: bool = False):
        self._papers = papers
        self._fail = fail

    def search(self, query, *, limit, scope=None) -> List[Paper]:
        if self._fail:
            raise ExploreError("simulated network outage (FakeBackend).")
        if self._papers is not None:
            return self._papers[:limit]
        return [
            Paper(
                source_id=f"fake.{i}",
                title=f"{query.title()} — study {i}",
                authors=[f"Author {i}"],
                abstract=(f"We investigate {query}. A centerline tracing "
                          f"and sim-to-real imaging method is proposed. "
                          f"Finding number {i} about {query}."),
                url=f"https://example.org/fake/{i}",
                published="2026-01-01",
            )
            for i in range(1, min(limit, 12) + 1)
        ]


@dataclass
class ExploreResult:
    query: str
    scope: Optional[str]
    model: str
    source_handles: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    skipped: int = 0           # de-duplicated (already in Atlas)

    @property
    def paper_count(self) -> int:
        return len(self.source_handles)

    @property
    def gap_count(self) -> int:
        return len(self.gaps)


class Explorer:
    """Runs the built-in scan and writes source pages via the queue."""

    def __init__(self, app, backend: Optional[SearchBackend] = None):
        self.app = app
        self.backend = backend or ArxivBackend()

    def run(
        self,
        query: str,
        *,
        scope: Optional[str] = None,
        limit: int = 12,
        model_override: Optional[str] = None,
    ) -> ExploreResult:
        # Resolve the explore model for transparency/repro and to honor
        # a one-shot `--model` override (§11.2). The built-in body is
        # extractive (zero-integration); the resolved model is what the
        # FutureHouse/LLM upgrade would use.
        try:
            res = self.app.router.resolve(
                "explore", step_override=model_override
            )
            model = str(res.ref)
        except Exception:  # noqa: BLE001 — routing optional pre-setup
            model = model_override or "unset"

        papers = self.backend.search(query, limit=limit, scope=scope)
        handles: List[str] = []
        skipped = 0
        for p in papers:
            body = self._page_body(p, query)
            try:
                r = self.app.wq.submit(Intent(op="create", payload={
                    "type": "source",
                    "title": p.slug_title(),
                    "status": "scratch",          # §9.10: scratch only
                    "summary": p.summary(),
                    "tags": ["explore", p.source],
                    "body": body,
                }))
                handles.append(r.handle)
            except ValueError:
                skipped += 1  # already ingested (handle collision, fix #1)
        gaps = self._gaps(query, papers)
        result = ExploreResult(
            query=query, scope=scope, model=model,
            source_handles=handles, gaps=gaps, skipped=skipped,
        )
        self.app.explore_store.record(result)
        return result

    @staticmethod
    def _page_body(p: Paper, query: str) -> str:
        auth = ", ".join(p.authors) if p.authors else "—"
        return (
            f"# {p.title}\n\n"
            f"*{auth}* · {p.published[:10]} · {p.source} · "
            f"[{p.source_id}]({p.url})\n\n"
            f"_Ingested by `helix explore \"{query}\"` (scratch tier; "
            f"promote to make it durable)._\n\n"
            f"## Abstract\n\n{_WS.sub(' ', p.abstract).strip()}\n"
        )

    def _gaps(self, query: str, papers: List[Paper]) -> List[str]:
        """Salient query/abstract terms not covered by existing Atlas
        knowledge. Coverage is now decided by the **real GraphRAG
        retriever** (build step 7): a term is a gap iff retrieval over
        active/canonical/published Atlas for the query surfaces nothing
        containing it (replaces the step-6 string-match placeholder)."""
        text = (query + " " + " ".join(
            p.title + " " + p.abstract for p in papers
        )).lower()
        freq: dict = {}
        for w in _WORD.findall(text):
            if w not in _STOP:
                freq[w] = freq.get(w, 0) + 1
        # Prefer query terms, then the most frequent topical terms.
        ql = query.lower()
        ranked = sorted(
            freq, key=lambda w: (-(w in ql), -freq[w])
        )[:12]
        try:
            return self.app.retriever.coverage_gaps(query, ranked)
        except Exception:  # noqa: BLE001 — never fail a scan on gap calc
            return ranked[:3]


class ExploreStore:
    """Persists explore results so the queue can surface them as FYI
    (§9.1/§10) — informational, never a gate or ticket (§9.10)."""

    def __init__(self, layout):
        self._dir = layout.helix_dir / "explore"

    def record(self, result: "ExploreResult") -> str:
        self._dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now(_dt.timezone.utc)
        rid = ts.strftime("%Y%m%dT%H%M%S%f")
        payload = {
            "id": rid,
            "ts": ts.isoformat().replace("+00:00", "Z"),
            "query": result.query,
            "scope": result.scope,
            "model": result.model,
            "source_handles": result.source_handles,
            "gaps": result.gaps,
            "skipped": result.skipped,
            "paper_count": result.paper_count,
            "consumed": False,
        }
        tmp = self._dir / f".{rid}.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._dir / f"{rid}.json")
        return rid

    def _all(self) -> List[dict]:
        if not self._dir.exists():
            return []
        out = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return out

    def unconsumed(self) -> List[dict]:
        return [r for r in self._all() if not r.get("consumed")]

    def consume_all(self) -> List[dict]:
        consumed = []
        for r in self._all():
            if r.get("consumed"):
                continue
            r["consumed"] = True
            path = self._dir / f"{r['id']}.json"
            tmp = self._dir / f".{r['id']}.consume.tmp"
            tmp.write_text(json.dumps(r, indent=2))
            tmp.replace(path)
            consumed.append(r)
        return consumed


class FutureHouseBackend:
    """Opt-in Explore upgrade (§11.1). Fails closed with instructions
    when the FutureHouse/ODR integration isn't configured — never fakes
    papers (the honest contract for an un-sandboxable integration)."""

    def search(self, query, *, limit, scope=None):
        from helix.upgrades import by_id

        by_id("explore-futurehouse").require()      # raises if unconfigured
        raise ExploreError(                          # configured but client
            "FutureHouse key present, but the FutureHouse/ODR client is "
            "the opt-in integration and is not bundled — wire your client "
            "in helix.explore.FutureHouseBackend.")


def make_backend(name: str) -> SearchBackend:
    """Backend selection seam. ``arxiv`` (default, real) · ``fake``
    (offline/tests) · ``futurehouse`` (opt-in upgrade, §11.1)."""
    if name == "fake":
        return FakeBackend()
    if name == "fake-fail":
        return FakeBackend(fail=True)
    if name in ("futurehouse", "opendeepresearch"):
        return FutureHouseBackend()
    return ArxivBackend()
