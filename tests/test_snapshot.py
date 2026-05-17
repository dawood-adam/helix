import threading

from helix.decisionlog import DecisionLog
from helix.snapshot import Snapshot, SnapshotStore


def test_mint_content_hash_and_parent_chain(store):
    s = SnapshotStore("bowel-length", store.layout)
    a = s.mint(decision_head="bowel-length#decision-1", reason="gate_methods")
    b = s.mint(decision_head="bowel-length#decision-2", reason="gate_plan",
               atlas_pages={"concept:odf": "v4"})
    assert a.id == "snap:bowel-length@1"
    assert a.verify() and b.verify()
    assert b.parent == a.id
    assert s.head() == b.id
    # Tampering is detectable (helix doctor integrity check, §9.11).
    b.atlas_pages["concept:odf"] = "v999"
    assert not b.verify()


def test_fork_creates_parallel_line_without_switching_active(store):
    s = SnapshotStore("bl", store.layout)
    s.mint(decision_head="bl#decision-1", reason="gate_methods")
    fork = s.fork("single-vector", decision_head="bl#decision-1")
    assert s.active_branch == "main"            # unchanged
    assert "single-vector" in s.branches()
    assert fork.branch == "single-vector"
    assert fork.parent == s.head("main")        # dashed fork connector


def test_park_and_resume_round_trip(store):
    s = SnapshotStore("bl", store.layout)
    s.mint(decision_head="bl#decision-1")
    s.fork("single-vector", decision_head="bl#decision-1")
    assert s.active_branch == "main"
    s.park("single-vector", decision_head="bl#decision-1")
    assert s.is_parked("single-vector")
    # Regression (review finding #2): parking a line must NOT make that
    # parked line the active branch — you stay where you were.
    assert s.active_branch == "main"
    s.park("main", decision_head="bl#decision-1")
    assert s.active_branch == "main"            # parking active: no steal
    s.resume("single-vector", decision_head="bl#decision-2")
    assert not s.is_parked("single-vector")
    assert s.active_branch == "single-vector"   # resume switches working line


def test_enclosing_resolves_coalesced_autoroute(store):
    """Auto-routed decisions coalesce into the next meaningful Snapshot
    (§7.3); checkout of decision-2 resolves to its enclosing Snapshot."""
    s = SnapshotStore("bl", store.layout)
    s.mint(decision_head="bl#decision-1", reason="gate_methods")
    # decision-2 is a pure auto-route -> no Snapshot of its own.
    enc = s.mint(decision_head="bl#decision-3", reason="gate_plan")
    resolved = s.enclosing("bl#decision-2")
    assert resolved is not None and resolved.id == enc.id


def test_binding_diff_is_semantic(store):
    s = SnapshotStore("bl", store.layout)
    a = s.mint(decision_head="bl#decision-1", code_sha="git:aaa",
               atlas_pages={"concept:odf": "v1"})
    b = s.mint(decision_head="bl#decision-2", code_sha="git:bbb",
               atlas_pages={"concept:odf": "v2"})
    delta = a.binding_diff(b)
    assert delta["code_sha"] == {"from": "git:aaa", "to": "git:bbb"}
    assert delta["atlas_pages"]["concept:odf"] == {"from": "v1", "to": "v2"}
    assert delta["decision_head"]["to"] == "bl#decision-2"


def test_snapshot_persists_and_reloads(store):
    s = SnapshotStore("bl", store.layout)
    s.mint(decision_head="bl#decision-1", model_routing={"builder": "local:qwen"})
    reloaded = SnapshotStore("bl", store.layout)
    snap = reloaded.get("snap:bl@1")
    assert isinstance(snap, Snapshot)
    assert snap.model_routing == {"builder": "local:qwen"}
    assert snap.verify()


def test_concurrent_mints_across_instances_no_corruption(store):
    """Regression (review finding #4): separate SnapshotStore instances
    sharing the process-global write lock must serialize mints — no
    duplicate seq, no lost snapshot in the keystone DAG."""
    shared = threading.RLock()
    n = 12

    def worker():
        SnapshotStore("bl", store.layout, lock=shared).mint(
            decision_head="bl#decision-1", reason="gate")

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snaps = SnapshotStore("bl", store.layout).all()
    seqs = sorted(s.seq for s in snaps)
    assert seqs == list(range(1, n + 1))          # unique + contiguous
    assert len({s.id for s in snaps}) == n        # no id collision
    assert all(s.verify() for s in snaps)


def test_gate_decision_binds_log_and_snapshot(store, wq):
    """Integration: a HITL gate appends a decision and mints a Snapshot
    that binds its head — the §7.3 'meaningful point' contract."""
    log = DecisionLog("bl", store.layout, wq)
    s = SnapshotStore("bl", store.layout)
    e = log.append(stage="methods", action="pick:ODF", rationale="r")
    snap = s.mint(decision_head=log.head(), reason="gate_methods")
    assert snap.decision_head == e["id"]
    assert s.enclosing(e["id"]).id == snap.id
