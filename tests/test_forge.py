import math

import pytest

from helix.forge import (
    AutonomySuggestion,
    ForgeState,
    Severity,
    apply_autonomy,
    auto_demote_on_revert,
    autonomy_suggestion,
    budget_check,
    commit_cost,
    default_autonomy,
    gate_decision,
    record_gate_outcome,
    sanity_route,
)


def clear_state(**kw) -> ForgeState:
    """A state where every §5.3 hard-rule condition is clear."""
    s = ForgeState(
        sanity_check_flags=["clean"], validator_complete=True,
        token_budget_remaining=10_000, cost_so_far=0.0, cost_cap=100.0,
    )
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ---- §5.3 gate decision -------------------------------------------


def test_default_is_always_ask_and_pauses():
    s = clear_state()
    assert s.autonomy == default_autonomy()
    out = gate_decision(s, "plan")
    assert out.action == "pause" and not out.auto_approved
    assert "always_ask" in out.reasons[0]


def test_auto_approves_only_when_all_clear():
    s = clear_state(autonomy={**default_autonomy(), "plan": "auto"})
    out = gate_decision(s, "plan")
    assert out.auto_approved and out.reasons == [
        "all hard-rule triggers clear"]


def test_sanity_flag_set_pauses():
    s = clear_state(autonomy={**default_autonomy(), "plan": "auto"},
                    sanity_check_flags=["plan_violation"])
    out = gate_decision(s, "plan")
    assert out.action == "pause"
    assert any("sanity flags set" in r for r in out.reasons)


def test_fail_closed_malformed_flags():
    s = clear_state(autonomy={**default_autonomy(), "plan": "auto"},
                    sanity_check_flags="oops-not-a-list")
    out = gate_decision(s, "plan")
    assert out.action == "pause"
    assert any("malformed" in r for r in out.reasons)


def test_fail_closed_results_gate_absent_flags():
    # Post-Validator gate: absent flags is NOT clean (§5.4 fail-closed).
    s = clear_state(autonomy={**default_autonomy(), "results": "auto"},
                    sanity_check_flags=None)
    out = gate_decision(s, "results")
    assert out.action == "pause"
    assert any("absent" in r for r in out.reasons)


def test_prevalidator_gate_absent_flags_is_ok():
    # gate_plan runs before the Validator; None flags isn't fail-closed.
    s = clear_state(autonomy={**default_autonomy(), "plan": "auto"},
                    sanity_check_flags=None)
    assert gate_decision(s, "plan").auto_approved


def test_blocking_critique_pauses_both_modes():
    for mode in ("ask_if_concerning", "auto"):
        s = clear_state(autonomy={**default_autonomy(), "methods": mode},
                        critiques=[{"gate": "methods",
                                    "severity": "blocking"}])
        assert gate_decision(s, "methods").action == "pause"


def test_warning_critique_distinguishes_modes():
    """The one principled ask_if_concerning vs auto difference (§5.3)."""
    crit = [{"gate": "methods", "severity": "warning"}]
    cautious = clear_state(
        autonomy={**default_autonomy(), "methods": "ask_if_concerning"},
        critiques=crit)
    trusting = clear_state(
        autonomy={**default_autonomy(), "methods": "auto"}, critiques=crit)
    assert gate_decision(cautious, "methods").action == "pause"
    assert gate_decision(trusting, "methods").auto_approved


def test_fail_closed_invalid_severity():
    s = clear_state(autonomy={**default_autonomy(), "methods": "auto"},
                    critiques=[{"gate": "methods", "severity": "kinda bad"}])
    out = gate_decision(s, "methods")
    assert out.action == "pause"
    assert any("missing/invalid severity" in r for r in out.reasons)


def test_critique_scoped_to_other_gate_is_ignored():
    s = clear_state(autonomy={**default_autonomy(), "plan": "auto"},
                    critiques=[{"gate": "methods", "severity": "blocking"}])
    assert gate_decision(s, "plan").auto_approved


def test_budget_and_contradiction_pause():
    s = clear_state(autonomy={**default_autonomy(), "plan": "auto"},
                    budget_hard_stop=True)
    assert gate_decision(s, "plan").action == "pause"
    s2 = clear_state(autonomy={**default_autonomy(), "plan": "auto"},
                     contradiction_flags=[{"page": "concept:x"}])
    assert gate_decision(s2, "plan").action == "pause"
    s3 = clear_state(autonomy={**default_autonomy(), "plan": "auto"},
                     token_budget_remaining=0)
    assert gate_decision(s3, "plan").action == "pause"


def test_reasons_accumulate():
    s = clear_state(autonomy={**default_autonomy(), "results": "auto"},
                    sanity_check_flags=["plan_violation"],
                    contradiction_flags=[{"p": 1}], budget_hard_stop=True)
    out = gate_decision(s, "results")
    assert len(out.reasons) >= 3


# ---- §5.4 sanity routing ------------------------------------------


def test_route_fail_closed_on_absent_or_malformed():
    assert sanity_route(ForgeState(sanity_check_flags=None)).mode == "pause"
    assert sanity_route(
        ForgeState(sanity_check_flags="x")).target == "gate_results"


def test_route_clean_requires_validator_complete():
    proceed = sanity_route(ForgeState(sanity_check_flags=["clean"],
                                      validator_complete=True))
    assert proceed.target == "CRITIC_RESULTS" and proceed.mode == "proceed"
    fc = sanity_route(ForgeState(sanity_check_flags=["clean"],
                                 validator_complete=False))
    assert fc.mode == "pause"  # fail-closed: "clean" but Validator not done


def test_route_deterministic_auto_routes():
    r1 = sanity_route(ForgeState(sanity_check_flags=["plan_violation"]))
    assert r1.target == "PLANNER" and r1.mode == "auto"
    r2 = sanity_route(ForgeState(sanity_check_flags=["leakage_detected"]))
    assert r2.target == "BUILDER" and r2.mode == "auto"


def test_route_drift_is_human_gated():
    r = sanity_route(ForgeState(sanity_check_flags=["drift_severe"]))
    assert r.target == "SCOUT" and r.mode == "human_gate" and r.needs_human


def test_route_leakage_precedes_plan_violation():
    r = sanity_route(ForgeState(
        sanity_check_flags=["plan_violation", "leakage_detected"]))
    assert r.target == "BUILDER"  # data integrity fixed first


def test_route_unknown_flag_fails_closed():
    r = sanity_route(ForgeState(sanity_check_flags=["weird_flag"]))
    assert r.mode == "pause" and "unrecognized" in r.reason


# ---- §5.5 enforced budget -----------------------------------------


def test_budget_check_allows_within():
    s = ForgeState(token_budget_remaining=1000, cost_cap=10.0)
    assert not budget_check(s, tokens=500, cost=1.0).halt


def test_budget_check_halts_on_token_or_cost():
    s = ForgeState(token_budget_remaining=100, cost_so_far=9.0,
                   cost_cap=10.0)
    tok = budget_check(s, tokens=500)
    assert tok.halt and tok.target == "gate_budget"
    cost = budget_check(s, cost=5.0)
    assert cost.halt and "cost cap" in cost.reasons[0]


def test_commit_cost_trips_hard_stop_and_then_gate_pauses():
    s = clear_state(autonomy={**default_autonomy(), "plan": "auto"},
                    token_budget_remaining=300)
    commit_cost(s, tokens=300)
    assert s.budget_hard_stop
    assert gate_decision(s, "plan").action == "pause"  # enforced, §5.5


# ---- §5.6 trust telemetry -----------------------------------------


def test_record_is_bounded():
    s = ForgeState()
    for _ in range(30):
        record_gate_outcome(s, "plan", True)
    assert len(s.gate_agreement["plan"]) == 20  # _HISTORY_CAP


def test_suggestion_only_after_streak_and_never_auto_applies():
    s = ForgeState()  # plan = always_ask
    for _ in range(2):
        record_gate_outcome(s, "plan", True)
    assert autonomy_suggestion(s, "plan") is None     # streak too short
    record_gate_outcome(s, "plan", True)              # 3 in a row
    sug = autonomy_suggestion(s, "plan")
    assert isinstance(sug, AutonomySuggestion)
    assert sug.current == "always_ask"
    assert sug.proposed == "ask_if_concerning"
    assert s.mode_for("plan") == "always_ask"          # NOT auto-applied


def test_streak_broken_no_suggestion():
    s = ForgeState()
    for v in (True, True, False, True, True):
        record_gate_outcome(s, "plan", v)
    assert autonomy_suggestion(s, "plan") is None


def test_suggestion_caps_at_auto():
    s = ForgeState(autonomy={**default_autonomy(), "plan": "auto"})
    for _ in range(5):
        record_gate_outcome(s, "plan", True)
    assert autonomy_suggestion(s, "plan") is None


def test_apply_autonomy_validates():
    s = ForgeState()
    apply_autonomy(s, "plan", "ask_if_concerning")
    assert s.mode_for("plan") == "ask_if_concerning"
    with pytest.raises(ValueError):
        apply_autonomy(s, "plan", "yolo")


def test_auto_demote_is_immediate_and_clears_trust():
    s = ForgeState(autonomy={**default_autonomy(), "plan": "auto"})
    for _ in range(5):
        record_gate_outcome(s, "plan", True)
    reason = auto_demote_on_revert(s, "plan", cause="salvaged")
    assert s.mode_for("plan") == "always_ask"
    assert s.gate_agreement["plan"] == []
    assert "re-earned" in reason
    # And the gate now pauses again (trust lost fast).
    assert gate_decision(clear_state(autonomy=s.autonomy),
                         "plan").action == "pause"


def test_severity_parse_robust():
    assert Severity.parse("BLOCKING") is Severity.BLOCKING
    assert Severity.parse(Severity.INFO) is Severity.INFO
    assert Severity.parse("nonsense") is None
    assert Severity.parse(None) is None
    assert Severity.WARNING < Severity.BLOCKING
