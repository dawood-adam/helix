from helix.atlas.graph import AtlasGraph, extract_links
from helix.atlas.retriever import Retriever, estimate_tokens
from helix.atlas.writequeue import Intent
from helix.ids import IdIndex, PageEntry


# ---- graph + link resolution --------------------------------------


def test_extract_links_forms():
    body = "[[a]] [[b|alias]] [[c#frag]] text [[a]]"
    assert extract_links(body) == ["a", "b", "c", "a"]


def test_resolve_link_by_handle_path_title(tmp_path):
    idx = IdIndex(tmp_path / "i.json")
    idx.register(PageEntry("u1", "concepts/odf.md", 1, "concept",
                           "canonical", "ODF Pred", "concept:odf", "s"))
    assert idx.resolve_link("concept:odf").id == "u1"
    assert idx.resolve_link("concepts/odf.md").id == "u1"
    assert idx.resolve_link("concepts/odf").id == "u1"
    assert idx.resolve_link("odf pred").id == "u1"          # title, ci
    assert idx.resolve_link("nope") is None


def test_graph_adjacency_and_orphan(store, wq):
    # §8.6 contract: links are written by id to pages that already
    # exist — so the target (B) must be created before A links it.
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "B", "status": "canonical",
        "body": "leaf"}))
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "A", "status": "canonical",
        "body": "[[concept:b]]"}))
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Island", "status": "canonical",
        "body": "alone"}))
    g = AtlasGraph.build(store)
    a = store.index.resolve("concept:a").id
    b = store.index.resolve("concept:b").id
    assert g.adj[a] == [b]
    assert g.radj[b] == [a]
    assert g.is_orphan(store.index.resolve("concept:island").id)
    assert not g.is_orphan(a)


# ---- retriever ----------------------------------------------------


def _seed(wq, n, status="canonical", link=False):
    for i in range(n):
        body = f"page {i} about bowel length odf imaging"
        if link and i > 0:
            body += " [[concept:c0]]"
        wq.submit(Intent(op="create", payload={
            "type": "concept", "title": f"C{i}", "status": status,
            "body": body, "summary": f"summary {i} bowel odf"}))


def test_cold_start_flat_mode(store, wq):
    _seed(wq, 4)
    ctx = Retriever(store).retrieve("bowel odf")
    assert ctx.mode == "flat"               # below the cold threshold
    assert ctx.items and ctx.items[0].score >= ctx.items[-1].score


def test_graph_mode_when_warm(store, wq):
    _seed(wq, 14, link=True)                # >=12 pages, many edges
    r = Retriever(store)
    ctx = r.retrieve("bowel odf", max_hops=2)
    assert ctx.mode == "graph"
    assert ctx.anchors                       # anchors were chosen
    assert ctx.items


def test_scope_excludes_scratch_and_archived_by_default(store, wq):
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Visible", "status": "canonical",
        "body": "bowel", "summary": "bowel"}))
    wq.submit(Intent(op="create", payload={
        "type": "scratch", "title": "Hidden", "status": "scratch",
        "body": "bowel", "summary": "bowel"}))
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Old", "status": "archived",
        "body": "bowel", "summary": "bowel"}))
    handles = {it.handle for it in Retriever(store).retrieve("bowel").items}
    assert "concept:visible" in handles
    assert "scratch:hidden" not in handles          # §6.3 scratch hidden
    assert "concept:old" not in handles             # §6.3 archived excluded
    # explicitly asking includes scratch
    h2 = {it.handle for it in Retriever(store).retrieve(
        "bowel", status_filter=["scratch"]).items}
    assert "scratch:hidden" in h2


def test_token_budget_and_tier_downgrade(store, wq):
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Big", "status": "canonical",
        "summary": "short summary about bowel",
        "body": "bowel " * 2000}))
    tight = Retriever(store).retrieve("bowel", max_tokens=40)
    assert tight.budget_exceeded or tight.items[0].tier < 3
    assert tight.total_tokens <= 40 or not tight.items


def test_hub_cap_bounds_pages_per_hop(store, wq):
    # one hub linking to 10 leaves
    links = " ".join(f"[[concept:leaf{i}]]" for i in range(10))
    for i in range(10):
        wq.submit(Intent(op="create", payload={
            "type": "concept", "title": f"Leaf{i}", "status": "canonical",
            "body": "bowel leaf", "summary": "bowel"}))
    for i in range(3):                      # padding to leave cold start
        wq.submit(Intent(op="create", payload={
            "type": "concept", "title": f"Pad{i}", "status": "canonical",
            "body": "bowel pad", "summary": "bowel"}))
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Hub", "status": "canonical",
        "body": "bowel hub " + links, "summary": "bowel hub"}))
    ctx = Retriever(store).retrieve("bowel hub", max_hops=1, hub_cap=3,
                                    anchors_k=1, max_tokens=100_000)
    leaves = [it for it in ctx.items if it.handle.startswith("concept:leaf")]
    assert len(leaves) <= 3                  # hub cap bounded the expansion


def test_retrieve_for_uses_agent_preset(store, wq):
    _seed(wq, 3)
    ctx = Retriever(store).retrieve_for("builder", "bowel")
    assert ctx.total_tokens <= 5_000         # §8.3 Builder budget


def test_coverage_gaps_uses_real_retrieval(store, wq):
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Bowel Length", "status": "canonical",
        "body": "bowel length is covered", "summary": "bowel length"}))
    gaps = Retriever(store).coverage_gaps(
        "bowel length", ["bowel", "length", "zzztopic"])
    assert "zzztopic" in gaps
    assert "bowel" not in gaps               # covered by the concept page


def test_estimate_tokens_monotonic():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("a" * 400) > estimate_tokens("a" * 4)
