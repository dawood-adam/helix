"""Write-time link hygiene (§8.6) + the generated-page exemption."""

from helix.atlas.writequeue import Applied, Intent, LinkError
from helix.decisionlog import DecisionLog


def _concept(wq, title, body="x"):
    return wq.submit(Intent(op="create", payload={
        "type": "concept", "title": title, "status": "canonical",
        "body": body}))


def test_resolvable_link_is_normalised_to_handle(wq, store):
    _concept(wq, "ODF Direction Prediction")
    r = wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Crossings", "status": "canonical",
        "body": "See [[ODF Direction Prediction]] and "
                "[[concepts/odf-direction-prediction]]."}))
    assert isinstance(r, Applied)
    body = store.read_page("concept:crossings")[0].body
    # Title- and path-form links rewritten to the canonical handle.
    assert body.count("[[concept:odf-direction-prediction]]") == 2
    assert "[[ODF Direction Prediction]]" not in body


def test_unresolvable_link_rejects_without_writing(wq, store):
    r = wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Dangling", "status": "canonical",
        "body": "Refs [[concept:does-not-exist]]."}))
    assert isinstance(r, LinkError) and not r.ok
    assert "concept:does-not-exist" in r.unresolved
    assert not store.index.has("concept:dangling")          # nothing written
    assert not store.abspath("concepts/dangling.md").exists()


def test_link_error_is_terminal_under_retry(wq):
    def build():
        return Intent(op="create", payload={
            "type": "concept", "title": "Bad", "status": "canonical",
            "body": "[[concept:nope]]"})
    r = wq.submit_with_retry(build, max_attempts=5)
    assert isinstance(r, LinkError)          # not retried forever


def test_generated_pages_are_exempt(store, wq):
    """The §7.2 decision-log narrative legitimately contains
    ``[[src:not-ingested]]`` (renderer fallback). Hygiene must NOT
    reject it — that would break the canonical→projection invariant."""
    log = DecisionLog("bl", store.layout, wq)
    log.append(stage="methods", action="pick:ODF", rationale="r",
               evidence=["src:not-ingested-yet"])
    page, _ = store.read_page("proj:bl-decision-log")
    assert page.generated is True
    assert "[[src:not-ingested-yet]]" in page.body            # not rejected


def test_duplicate_links_allowed_but_lintable(wq, store):
    _concept(wq, "Alpha")
    r = wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Beta", "status": "canonical",
        "body": "[[concept:alpha]] then again [[concept:alpha]]"}))
    assert isinstance(r, Applied)            # duplicates don't reject
    from helix.atlas.lint import Linter
    kinds = {f.kind for f in Linter(store).lint_page("concept:beta")}
    assert "duplicate_link" in kinds         # but lint flags them
