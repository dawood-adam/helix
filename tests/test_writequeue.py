import threading
import time

from helix.atlas.writequeue import Applied, Conflict, FoldSuggestion, Intent
from helix.pages import Page


def _create(wq, title="ODF", type="concept", status="scratch", body="v1"):
    return wq.submit(Intent(op="create", payload={
        "type": type, "title": title, "status": status, "body": body}))


def test_create_indexes_and_writes_file(wq, store):
    r = _create(wq)
    assert isinstance(r, Applied) and r.ok
    assert r.version == 1
    assert store.abspath(r.path).exists()
    page, ver = store.read_page("concept:odf")
    assert page.body == "v1" and ver == 1


def test_update_with_correct_base_version(wq, store):
    _create(wq)
    _, ver = store.read_page("concept:odf")
    r = wq.submit(Intent(op="update", ref="concept:odf",
                         base_version=ver, payload={"body": "v2"}))
    assert isinstance(r, Applied) and r.version == 2
    assert store.read_page("concept:odf")[0].body == "v2"


def test_stale_base_version_conflicts_and_does_not_mutate(wq, store):
    _create(wq)
    wq.submit(Intent(op="update", ref="concept:odf",
                      base_version=1, payload={"body": "v2"}))
    # Writer still thinks it is at v1 -> optimistic-concurrency reject.
    r = wq.submit(Intent(op="update", ref="concept:odf",
                         base_version=1, payload={"body": "stale"}))
    assert isinstance(r, Conflict) and not r.ok
    assert r.expected_version == 1 and r.actual_version == 2
    assert store.read_page("concept:odf")[0].body == "v2"  # unchanged


def test_submit_with_retry_resolves_conflict(wq, store):
    _create(wq)

    def build():
        _, ver = store.read_page("concept:odf")  # fresh read each attempt
        return Intent(op="update", ref="concept:odf",
                      base_version=ver, payload={"body": "retried"})

    r = wq.submit_with_retry(build)
    assert isinstance(r, Applied) and r.ok
    assert store.read_page("concept:odf")[0].body == "retried"


def test_promotion_moves_file_but_reference_survives(wq, store):
    """§6.2/§7 keystone: set_status relocates the file across tiers,
    yet the uuid AND the handle still resolve — no pointer breaks."""
    r = _create(wq, status="scratch")
    pid = r.page_id
    old_path = r.path
    assert old_path.startswith("scratch/")

    _, ver = store.read_page("concept:odf")
    pr = wq.submit(Intent(op="set_status", ref=pid, base_version=ver,
                          payload={"status": "canonical"}))
    assert isinstance(pr, Applied)
    assert pr.path.startswith("concepts/")
    assert not store.abspath(old_path).exists()
    # Both identifier forms still resolve to the new location.
    assert store.read_page(pid)[0].status == "canonical"
    assert store.read_page("concept:odf")[0].status == "canonical"


def test_human_edit_of_generated_file_is_not_clobbered(wq, store):
    gen = Page(id="genid", title="Decision log", type="project",
               status="active", generated=True, body="## Decision 1")
    r = wq.submit(Intent(op="ingest_human_edit", payload={
        "rel_path": "projects/x/decision-log-narrative.md",
        "text": gen.to_markdown() + "\nHUMAN ADDED A LINE\n"}))
    assert isinstance(r, FoldSuggestion) and not r.ok
    assert r.page_id == "genid"
    assert "HUMAN ADDED A LINE" in r.human_text


def test_human_edit_of_normal_page_is_ingested(wq, store):
    _create(wq)
    page, _ = store.read_page("concept:odf")
    page.body = "edited in obsidian"
    r = wq.submit(Intent(op="ingest_human_edit", payload={
        "rel_path": store.index.path_for("concept:odf"),
        "text": page.to_markdown()}))
    assert isinstance(r, Applied)
    assert store.read_page("concept:odf")[0].body == "edited in obsidian"


def test_single_ordered_writer_no_lost_updates(wq, store):
    """The §6.4.1 guarantee: optimistic concurrency + retry-to-success
    ⇒ no lost updates. Each worker retries until it APPLIES (production
    agents do the same), so this verifies the queue invariant, not an
    arbitrary retry budget. Correctness invariant asserted directly:
    the final value equals the number of successful applies."""
    _create(wq, body="0")
    n_threads = 8
    applied = []
    applied_lock = threading.Lock()

    def bump():
        for _ in range(1000):  # safety cap: a livelock fails loudly
            def build():
                page, ver = store.read_page("concept:odf")
                return Intent(op="update", ref="concept:odf",
                              base_version=ver,
                              payload={"body": str(int(page.body) + 1)})
            r = wq.submit(build())
            if isinstance(r, Applied):
                with applied_lock:
                    applied.append(r.version)
                return
            # Model the real re-read cost (agents re-read via slow LLM
            # calls, not a tight CPU loop) — avoids a synthetic
            # thundering-herd that doesn't reflect production.
            time.sleep(0.0005)
        raise AssertionError("livelock: worker never applied")

    threads = [threading.Thread(target=bump) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final, ver = store.read_page("concept:odf")
    assert len(applied) == n_threads               # every worker applied
    assert int(final.body) == n_threads            # == #successful applies
    assert ver == n_threads + 1                    # v1 create + N updates
    assert sorted(applied) == list(range(2, n_threads + 2))  # unique versions


def test_duplicate_create_does_not_clobber_existing_file(wq, store):
    """Regression (review finding #1): a colliding create must fail
    WITHOUT mutating the existing page's bytes on disk."""
    _create(wq, body="ORIGINAL")
    import pytest
    with pytest.raises(ValueError, match="already maps"):
        wq.submit(Intent(op="create", payload={
            "type": "concept", "title": "ODF",
            "status": "canonical", "body": "CLOBBER"}))
    page, ver = store.read_page("concept:odf")
    assert page.body == "ORIGINAL"     # untouched
    assert ver == 1                    # version not bumped


def test_human_edit_conflicts_on_stale_base_version(wq, store):
    """Regression (review finding #5): a human edit submitted with a
    stale base_version must Conflict, not clobber an agent's write."""
    _create(wq)
    wq.submit(Intent(op="update", ref="concept:odf", base_version=1,
                      payload={"body": "agent wrote v2"}))
    page, _ = store.read_page("concept:odf")
    page.body = "human edit based on v1"
    r = wq.submit(Intent(op="ingest_human_edit", base_version=1, payload={
        "rel_path": store.index.path_for("concept:odf"),
        "text": page.to_markdown()}))
    assert isinstance(r, Conflict) and not r.ok
    assert store.read_page("concept:odf")[0].body == "agent wrote v2"


def test_wal_records_full_intent_with_payload(wq, store):
    import json
    _create(wq)
    wq.submit(Intent(op="update", ref="concept:odf", base_version=1,
                      payload={"body": "v2"}))
    lines = [json.loads(ln) for ln in
             store.layout.wal_path.read_text().strip().splitlines()]
    pending = [r for r in lines if r.get("status") == "pending"]
    create_rec = next(r for r in pending if r["op"] == "create")
    # The §6.4.1 record is {page_id, op, payload, base_version} — the
    # payload must be present so the WAL is genuinely replayable (#6).
    assert create_rec["payload"]["title"] == "ODF"
    assert any(r.get("status") == "applied" and "version" in r
               for r in lines)
