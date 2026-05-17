import datetime as dt
import threading

from helix.atlas.writequeue import Intent
from helix.decisionlog import DecisionLog


def _log(store, wq):
    fixed = dt.datetime(2026, 5, 15, 16, 4, 12, tzinfo=dt.timezone.utc)
    return DecisionLog("bowel-length", store.layout, wq, clock=lambda: fixed)


def _seed_evidence(wq):
    wq.submit(Intent(op="create", payload={
        "type": "source", "title": "2024 Zhang Bowel Anatomy",
        "status": "canonical", "body": "src"}))
    wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "ODF Direction Prediction",
        "status": "canonical", "body": "concept"}))


def test_append_canonical_shape_and_head(store, wq):
    log = _log(store, wq)
    e = log.append(stage="methods", action="pick:ODF", chosen_id="approach-3",
                    rationale="ODF survives crossings.", auto_or_human="human")
    assert e["id"] == "bowel-length#decision-1"
    assert e["timestamp"] == "2026-05-15T16:04:12Z"
    assert e["stage"] == "methods"
    assert log.head() == "bowel-length#decision-1"
    log.append(stage="plan", action="approve")
    assert log.head() == "bowel-length#decision-2"


def test_narrative_is_generated_page_through_queue(store, wq):
    log = _log(store, wq)
    log.append(stage="methods", action="pick:ODF",
               rationale="ODF survives crossings.")
    page, _ = store.read_page(log._narrative_handle)
    assert page.generated is True
    assert "## Decision 1 — Pick ODF" in page.body
    assert "do not edit" in store.read_raw(
        store.index.path_for(log._narrative_handle))


def test_narrative_is_deterministic_and_idempotent(store, wq):
    log = _log(store, wq)
    log.append(stage="methods", action="pick:ODF", rationale="because.")
    once = log.render_narrative()
    twice = log.render_narrative()
    assert once == twice  # pure projection


def test_evidence_ids_become_resolved_wikilinks(store, wq):
    _seed_evidence(wq)
    log = _log(store, wq)
    log.append(
        stage="methods", action="pick:ODF",
        rationale="ODF represents multimodal direction",
        evidence=["src:2024-zhang-bowel-anatomy",
                  "concept:odf-direction-prediction"],
        rejected=[{"id": "approach-1", "label": "single-vector",
                   "reason": "can't represent two directions"}],
        next="Planner drafts validation cascade.",
    )
    body = store.read_page(log._narrative_handle)[0].body
    assert "[[sources/2024-zhang-bowel-anatomy]]" in body
    assert "[[concepts/odf-direction-prediction]]" in body
    assert "- approach-1 (single-vector): can't represent two directions" in body
    assert "Next: Planner drafts validation cascade." in body


def test_unresolvable_evidence_falls_back_to_raw_ref(store, wq):
    log = _log(store, wq)
    log.append(stage="methods", action="pick:ODF", rationale="r",
               evidence=["src:not-ingested-yet"])
    assert "[[src:not-ingested-yet]]" in log.render_narrative()


def test_fold_promotes_prose_into_canonical_json(store, wq):
    """§7.2: a human edit to the generated file is folded into the
    canonical rationale — never tolerated as a divergent copy."""
    log = _log(store, wq)
    log.append(stage="methods", action="pick:ODF", rationale="Base reason.")
    log.fold_into_rationale("bowel-length#decision-1", "Human-added nuance.")
    entry = log.get("bowel-length#decision-1")
    assert "Base reason." in entry["rationale"]
    assert "Human-added nuance." in entry["rationale"]
    # The narrative regenerates *from* the JSON, staying a pure projection.
    assert "Human-added nuance." in store.read_page(log._narrative_handle)[0].body


def test_concurrent_appends_across_instances_no_loss(store, wq):
    """Regression (review finding #3): separate DecisionLog instances
    for one project, sharing the WriteQueue's global lock, must
    serialize — no duplicate ids, no lost decisions. §7 demands the
    *strongest* consistency for the canonical artifact."""
    n = 16

    def worker():
        DecisionLog("bl", store.layout, wq).append(
            stage="methods", action="approve")

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entries = DecisionLog("bl", store.layout, wq).entries()
    ids = [e["id"] for e in entries]
    assert len(ids) == n
    assert len(set(ids)) == n                                   # no dupes
    assert sorted(ids) == sorted(f"bl#decision-{i}" for i in range(1, n + 1))


def test_why_bullets(store, wq):
    log = _log(store, wq)
    e = log.append(stage="methods", action="pick:ODF",
                   rationale="ODF survives crossings.",
                   rejected=[{"id": "approach-1", "reason": "x"}],
                   evidence=["src:zhang"])
    bullets = log.why_bullets(e)
    assert bullets[0] == "ODF survives crossings."
    assert any("approach-1" in b for b in bullets)
    assert any("src:zhang" in b for b in bullets)
    assert len(bullets) <= 3
