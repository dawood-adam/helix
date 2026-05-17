"""The §5.2 workflow loop end-to-end (LangGraph + step-8 rules)."""

from helix.forge.agents import FakeAgents
from helix.forge.state import GATES
from helix.forge.workflow import WorkflowEngine


def _engine(app, **fake_kw):
    app.projects.create("bl")                 # project dir for log/snaps
    return WorkflowEngine(app, FakeAgents(**fake_kw))


def test_default_always_ask_interrupts_at_first_gate(helix_app):
    eng = _engine(helix_app)
    st = eng.start("bl", research_question="bowel length")
    assert st["status"] == "interrupted"
    assert st["gate"]["title"] == "Approve the scope?"
    # The gate view carries the §9.3 affordances.
    g = st["gate"]
    assert g["recommended"] and g["options"] and g["why"]
    assert 0.0 <= g["confidence"] <= 1.0
    assert g["soft_commit_seconds"] == 20


def test_cross_process_resume(helix_app):
    """A fresh engine (≈ a separate `helix` process) sees the pending
    gate and resumes it — the SqliteSaver checkpoint, spike-proven."""
    _engine(helix_app).start("bl")
    fresh = WorkflowEngine(helix_app, FakeAgents())
    assert fresh.pending("bl")["status"] == "interrupted"
    st = fresh.resume("bl", "approve")
    assert st["status"] == "interrupted"
    assert st["gate"]["title"] == "Approve the approach?"   # advanced


def test_full_human_path_records_decisions_and_snapshots(helix_app):
    eng = _engine(helix_app)
    eng.start("bl")
    eng.resume("bl", "approve")                 # gate_scope
    eng.resume("bl", "pick:approach-1")         # gate_methods
    eng.resume("bl", "approve")                 # gate_plan
    eng.resume("bl", "approve")                 # gate_build
    st = eng.resume("bl", "ship")               # gate_results -> maintainer
    assert st["status"] == "done"
    actions = [e["action"] for e in helix_app.decision_log("bl").entries()]
    assert "init" in actions                    # from ProjectStore.create
    assert "approve" in actions and "pick:approach-1" in actions
    assert "ship" in actions
    # Every meaningful point minted a Snapshot (§7.3).
    assert len(helix_app.snapshots("bl").all()) >= 6


def test_autonomy_auto_runs_clean_to_done(helix_app):
    eng = _engine(helix_app)
    auto = {g: "auto" for g in GATES}
    st = eng.start("bl", autonomy=auto)
    assert st["status"] == "done"               # no human needed when clear
    actions = [e["action"] for e in helix_app.decision_log("bl").entries()]
    assert any(a.startswith("pick:") for a in actions)


def test_sanity_autoroute_plan_violation(helix_app):
    eng = _engine(helix_app, inject_flags=["plan_violation"])
    auto = {g: "auto" for g in GATES}
    st = eng.start("bl", autonomy=auto)
    # Validator's deterministic flag auto-routes back to Planner (§5.4)
    # WITHOUT a human, and the loop re-enters — it never silently ships.
    assert st["status"] in ("interrupted", "running", "done")
    actions = [e["action"] for e in helix_app.decision_log("bl").entries()]
    assert any(a == "auto_route:plan_violation" for a in actions)
    autos = [e for e in helix_app.decision_log("bl").entries()
             if e["action"] == "auto_route:plan_violation"]
    assert autos[0]["auto_or_human"] == "auto"


def test_fail_closed_survives_full_pipeline(helix_app):
    """The whole point of §5.3/§5.4: even with EVERY gate forced to
    auto, absent Validator flags must NOT silently complete — the
    pipeline fails closed at the results gate."""
    eng = _engine(helix_app, inject_flags=None)   # Validator wrote nothing
    auto = {g: "auto" for g in GATES}
    st = eng.start("bl", autonomy=auto)
    assert st["status"] == "interrupted"
    assert st["gate"]["title"] == "Approve the results?"
    assert any("absent" in r for r in st["gate"]["pause_reasons"])


def test_workflow_snapshots_are_fully_bound(helix_app):
    """Regression for HIGH-2: the keystone Snapshot (§7.3) must bind
    code_sha + Atlas page versions from the workflow — not just
    decision_head + model_routing (which made diff/checkout hollow)."""
    from helix import vc
    from helix.ids import make_handle

    helix_app.projects.create("bl")
    eng = WorkflowEngine(helix_app, FakeAgents())
    eng.start("bl", autonomy={g: "auto" for g in GATES})
    snaps = helix_app.snapshots("bl").all()

    bound = [s for s in snaps if s.code_sha]
    assert bound, "no Snapshot bound a code sha — keystone still hollow"
    assert bound[-1].code_sha == "sha256:fake"      # the Builder's artifact
    assert any(s.atlas_pages for s in snaps), "no Atlas page versions bound"
    h = make_handle("project", "bl")                # the overview page id
    assert any(h in s.atlas_pages for s in snaps)

    # The §7.5 semantic diff is no longer hollow (the step-10 review's
    # exact evidence was: only decision_head/model_routing ever differed).
    d = vc.diff(helix_app, "bl", snaps[0].id, snaps[-1].id).binding
    assert "code_sha" in d or "atlas_pages" in d


def test_branch_compare_in_gate_view(helix_app):
    eng = _engine(helix_app)
    helix_app.snapshots("bl").mint(decision_head=None, reason="seed")
    helix_app.snapshots("bl").fork("single-vector", decision_head=None)
    st = eng.start("bl")
    # >1 research line ⇒ the gate is a side-by-side, not a one-shot pick.
    assert len(st["gate"]["compare"]) >= 2
    branches = {c["branch"] for c in st["gate"]["compare"]}
    assert {"main", "single-vector"} <= branches
