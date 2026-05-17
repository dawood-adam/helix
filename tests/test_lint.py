from helix.atlas.lint import Linter
from helix.atlas.writequeue import Intent
from helix.decisionlog import DecisionLog


def mk(wq, title, body="content", typ="concept", status="canonical"):
    return wq.submit(Intent(op="create", payload={
        "type": typ, "title": title, "status": status, "body": body}))


def test_broken_link_flagged_on_generated_page(store, wq):
    # Authored pages can't carry broken links (hygiene rejects them);
    # the realistic broken-link source is the generated narrative.
    log = DecisionLog("bl", store.layout, wq)
    log.append(stage="methods", action="pick:ODF", rationale="r",
               evidence=["src:never-ingested"])
    findings = Linter(store).lint_page("proj:bl-decision-log")
    assert any(f.kind == "broken_link" for f in findings)


def test_duplicate_link(store, wq):
    mk(wq, "Alpha")
    mk(wq, "Beta", body="[[concept:alpha]] [[concept:alpha]]")
    kinds = [f.kind for f in Linter(store).lint_page("concept:beta")]
    assert kinds.count("duplicate_link") == 1


def test_stale_claim_provenance(store, wq):
    mk(wq, "Gamma", body="A claim. ^src:2099-ghost-paper")
    findings = Linter(store).lint_page("concept:gamma")
    assert any(f.kind == "stale_claim" for f in findings)
    mk(wq, "Real Source", typ="source")
    mk(wq, "Delta", body="Backed claim. ^src:real-source")
    assert not any(f.kind == "stale_claim"
                   for f in Linter(store).lint_page("concept:delta"))


def test_orphan_is_corpus_level_only(store, wq):
    mk(wq, "Lonely")                       # no links in or out
    page_findings = Linter(store).lint_page("concept:lonely")
    assert not any(f.kind == "orphan" for f in page_findings)  # not local
    all_findings = Linter(store).lint_all()
    assert any(f.kind == "orphan" and f.handle == "concept:lonely"
               for f in all_findings)


def test_lint_all_clean_when_connected(store, wq):
    # A↔B cycle. Hard-reject (§8.6) forbids forward refs, so a cycle is
    # built two-phase: B (linkless) → A→B → then update B→A. This is
    # the supported way to author cyclic links; assert it really built.
    mk(wq, "B", body="leaf for now")
    mk(wq, "A", body="links to [[concept:b]]")
    upd = wq.submit(Intent(op="update", ref="concept:b", base_version=1,
                           payload={"body": "links to [[concept:a]]"}))
    assert upd.ok
    assert store.index.has("concept:a") and store.index.has("concept:b")
    findings = Linter(store).lint_all()
    assert findings == [], [str(f) for f in findings]


def test_continuous_lint_runs_on_write(helix_app):
    helix_app.wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Solo", "status": "canonical",
        "body": "claim ^src:missing-x"}))
    # The facade wired on_applied -> incremental lint of the touched page.
    assert any(f.kind == "stale_claim" for f in helix_app.last_lint)
