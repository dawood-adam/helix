import pytest

from helix.atlas.writequeue import Intent
from helix.explore import (
    ArxivBackend,
    ExploreError,
    Explorer,
    FakeBackend,
    Paper,
)

# A representative arXiv Atom payload (namespaced default xmlns +
# arxiv/opensearch extensions, nested authors, padded summary). This
# verifies the parser offline — the sandbox has no network, so the live
# path is only checked for fail-closed behaviour, not parsing.
_ARXIV_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults
    xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">2
  </opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2401.01234v1</id>
    <published>2024-01-01T00:00:00Z</published>
    <title>Centerline Tracing of the
      Small Intestine</title>
    <summary>  We propose a tracing method.  </summary>
    <author><name>Jane Zhang</name></author>
    <author><name>Bob Lee</name></author>
    <category term="eess.IV" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.05678v2</id>
    <published>2024-02-15T00:00:00Z</published>
    <title>Sim-to-Real Imaging</title>
    <summary>Second abstract.</summary>
    <author><name>Carol Diaz</name></author>
  </entry>
</feed>"""


def test_arxiv_atom_parser():
    papers = ArxivBackend._parse(_ARXIV_ATOM)
    assert len(papers) == 2                       # opensearch row skipped
    a, b = papers
    assert a.source_id == "2401.01234v1"
    assert a.title == "Centerline Tracing of the Small Intestine"
    assert a.authors == ["Jane Zhang", "Bob Lee"]
    assert a.abstract.strip() == "We propose a tracing method."
    assert a.published.startswith("2024-01-01")
    assert b.authors == ["Carol Diaz"]


def test_arxiv_parser_rejects_garbage():
    with pytest.raises(ExploreError):
        ArxivBackend._parse(b"<not-xml")


def test_paper_slug_and_summary():
    p = Paper(source_id="x", title="ODF Direction Prediction",
              authors=["Jane Zhang"], abstract="A. " * 400,
              url="u", published="2024-05-01")
    assert p.slug_title().startswith("2024 Zhang")
    assert len(p.summary(120)) <= 121


def test_run_writes_source_pages_via_queue(helix_app):
    r = Explorer(helix_app, backend=FakeBackend()).run("bowel length", limit=5)
    assert r.paper_count == 5
    assert all(h.startswith("src:") for h in r.source_handles)
    # Written to scratch tier through the single ordered queue (§9.10).
    page, _ = helix_app.store.read_page(r.source_handles[0])
    assert page.type == "source" and page.status == "scratch"
    assert "explore" in page.tags
    assert r.gaps                                  # heuristic produced gaps
    assert helix_app.explore_store.unconsumed()    # result persisted


def test_rerun_dedupes_against_existing_pages(helix_app):
    ex = Explorer(helix_app, backend=FakeBackend())
    ex.run("bowel length", limit=4)
    second = ex.run("bowel length", limit=4)
    assert second.paper_count == 0 and second.skipped == 4  # all known


def test_gap_heuristic_excludes_covered_concepts(helix_app):
    helix_app.wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Bowel Length",
        "status": "canonical", "body": "covered"}))
    r = Explorer(helix_app, backend=FakeBackend()).run("bowel length scan")
    assert "bowel" not in r.gaps        # covered by concept:bowel-length
    assert r.gaps                        # but still surfaces other gaps


def test_fail_closed_fabricates_nothing(helix_app):
    ex = Explorer(helix_app, backend=FakeBackend(fail=True))
    with pytest.raises(ExploreError):
        ex.run("anything")
    # No source pages, no recorded result — honest failure.
    assert len(list(helix_app.store.index)) == 0
    assert helix_app.explore_store.unconsumed() == []


def test_explore_store_record_and_consume(helix_app):
    Explorer(helix_app, backend=FakeBackend()).run("q1", limit=2)
    Explorer(helix_app, backend=FakeBackend()).run("q2", limit=2)
    assert len(helix_app.explore_store.unconsumed()) == 2
    consumed = helix_app.explore_store.consume_all()
    assert len(consumed) == 2
    assert helix_app.explore_store.unconsumed() == []


def test_model_override_is_recorded(helix_app, tmp_path):
    # Router resolves from an (empty) config -> fallback path; an
    # explicit override must still be recorded for transparency (§11.2).
    r = Explorer(helix_app, backend=FakeBackend()).run(
        "q", limit=1, model_override="openai:gpt-5")
    assert r.model == "openai:gpt-5"
