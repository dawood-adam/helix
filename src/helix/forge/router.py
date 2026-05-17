"""Hard-rule routing (HELIX.md §5.3-5.5).

Three deterministic, non-LLM decisions:

* :func:`gate_decision` — may a HITL gate auto-approve? Only when
  *every* objective hard-rule trigger is clear (§5.3). **Fail-closed**:
  any missing/malformed required signal → pause. Absence is never the
  happy path on a safety-relevant branch.
* :func:`sanity_route` — Validator flags drive automatic loop-back
  (§5.4). Only the two deterministic detector outputs auto-route
  without a human; a judgement signal pauses for a one-tap confirm;
  absent/unknown flags fail closed to a human.
* :func:`budget_check` / :func:`commit_cost` — the budget is *enforced*
  (§5.5): a step that would exceed its allocation halts and raises
  ``gate_budget`` rather than silently overspending.

``ask_if_concerning`` vs ``auto``: both use the same four hard-rule
conditions and the same fail-closed rule. The one principled
difference (matching their names and the §5.3 table) is critique
sensitivity — ``ask_if_concerning`` pauses on a ``WARNING`` critique
("concerning"), ``auto`` only on ``BLOCKING`` ("hard violation").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from helix.forge.state import ForgeState, Severity

# §5.4 — only these two are deterministic detector outputs that may
# auto-route WITHOUT a human. Order = severity: a data-integrity
# failure (leakage) is fixed before a metric-band miss (plan).
_AUTO_ROUTES = (
    ("leakage_detected", "BUILDER",
     "deterministic: pipeline integrity check failed (e.g. train/test "
     "overlap)"),
    ("plan_violation", "PLANNER",
     "deterministic: actual metric outside the plan's target band"),
)
_KNOWN_FLAGS = {"clean", "leakage_detected", "plan_violation", "drift_severe"}


@dataclass
class GateOutcome:
    action: str                 # "auto_approve" | "pause"
    gate: str
    mode: str
    reasons: List[str] = field(default_factory=list)

    @property
    def auto_approved(self) -> bool:
        return self.action == "auto_approve"


@dataclass
class RouteDecision:
    target: str                 # node name | "gate_results" | "gate_budget"
    mode: str                   # "auto" | "human_gate" | "pause" | "proceed"
    reason: str
    flag: Optional[str] = None

    @property
    def needs_human(self) -> bool:
        return self.mode in ("human_gate", "pause")


@dataclass
class BudgetOutcome:
    halt: bool
    target: Optional[str]       # "gate_budget" when halting
    reasons: List[str] = field(default_factory=list)


# ---- §5.3 hard-rule gate decision ----------------------------------


def _hard_rule_reasons(state: ForgeState, gate: str, mode: str) -> List[str]:
    """The four §5.3 conditions + fail-closed. Empty list ⇒ clear."""
    reasons: List[str] = []

    # (1) Validator sanity flags. For the post-Validator gate, absence
    # is fail-closed (§5.4 "(none / missing) → pause"). Pre-Validator
    # gates may legitimately have no flags; only malformed is a fault.
    flags = state.sanity_check_flags
    if flags is not None and not isinstance(flags, list):
        reasons.append("fail-closed: sanity_check_flags malformed")
    elif gate == "results" and flags is None:
        reasons.append("fail-closed: Validator sanity flags absent "
                       "(absence is not 'clean')")
    elif isinstance(flags, list):
        set_flags = [f for f in flags if f != "clean"]
        if set_flags:
            reasons.append(f"sanity flags set: {set_flags}")

    # (2) Structured critique severity (typed enum, router-validated —
    # not free prose). ask_if_concerning is stricter than auto.
    threshold = Severity.BLOCKING if mode == "auto" else Severity.WARNING
    for c in state.critiques:
        if c.get("gate") not in (None, gate):
            continue  # not relevant to this step
        sev = Severity.parse(c.get("severity"))
        if sev is None:
            reasons.append("fail-closed: critique present with "
                           "missing/invalid severity")
        elif sev >= threshold:
            reasons.append(f"critique severity {sev.name.lower()}")

    # (3) Budget within allocation (§5.5).
    if state.budget_hard_stop:
        reasons.append("budget hard stop is set")
    elif state.token_budget_remaining is None or \
            state.token_budget_remaining <= 0:
        reasons.append("token budget exhausted")
    elif state.cost_so_far > state.cost_cap:
        reasons.append("cost over cap")

    # (4) Contradiction newly flagged vs a canonical page this step.
    if state.contradiction_flags:
        reasons.append(
            f"contradiction vs canonical ({len(state.contradiction_flags)})")

    return reasons


def gate_decision(state: ForgeState, gate: str) -> GateOutcome:
    """May ``gate`` auto-approve? (§5.3)"""
    mode = state.mode_for(gate)
    if mode == "always_ask":
        return GateOutcome("pause", gate, mode,
                           ["autonomy=always_ask (you review every time)"])
    reasons = _hard_rule_reasons(state, gate, mode)
    if reasons:
        return GateOutcome("pause", gate, mode, reasons)
    return GateOutcome("auto_approve", gate, mode,
                       ["all hard-rule triggers clear"])


# ---- §5.4 sanity-flag auto-routing ---------------------------------


def sanity_route(state: ForgeState) -> RouteDecision:
    """Validator → next node. Only deterministic detector outputs
    auto-route without a human; everything else fails closed."""
    flags = state.sanity_check_flags
    if flags is None or not isinstance(flags, list):
        return RouteDecision(
            "gate_results", "pause",
            "fail-closed: sanity flags absent/missing — absence is not "
            "treated as clean (§5.4)")

    set_flags = [f for f in flags if f != "clean"]
    if not set_flags:
        if state.validator_complete:
            return RouteDecision("CRITIC_RESULTS", "proceed",
                                 "Validator ran clean", "clean")
        return RouteDecision(
            "gate_results", "pause",
            "fail-closed: no flags and Validator not marked complete")

    unknown = [f for f in set_flags if f not in _KNOWN_FLAGS]
    if unknown:
        return RouteDecision(
            "gate_results", "pause",
            f"fail-closed: unrecognized sanity flags {unknown}")

    for flag, target, why in _AUTO_ROUTES:
        if flag in set_flags:
            return RouteDecision(target, "auto", why, flag)

    if "drift_severe" in set_flags:
        # A judgement, not a mechanical check; the most expensive loop
        # (re-reading the literature) always pauses for a one-tap
        # human confirm rather than auto-routing silently (§5.4).
        return RouteDecision(
            "SCOUT", "human_gate",
            "judgement signal: re-read literature — one-tap confirm",
            "drift_severe")

    return RouteDecision("gate_results", "pause",
                         "fail-closed: unhandled flag combination")


# ---- §5.5 enforced budget ------------------------------------------


def budget_check(
    state: ForgeState, *, tokens: int = 0, cost: float = 0.0
) -> BudgetOutcome:
    """Would running a step exceed allocation? If so, HALT to
    ``gate_budget`` — the budget is enforced, not merely displayed."""
    reasons: List[str] = []
    if state.token_budget_remaining - tokens < 0:
        reasons.append(
            f"would exceed token budget by "
            f"{tokens - state.token_budget_remaining}")
    if state.cost_so_far + cost > state.cost_cap:
        reasons.append(
            f"would exceed cost cap "
            f"(${state.cost_so_far + cost:.2f} > ${state.cost_cap:.2f})")
    if reasons:
        return BudgetOutcome(True, "gate_budget", reasons)
    return BudgetOutcome(False, None, [])


def commit_cost(state: ForgeState, *, tokens: int = 0,
                cost: float = 0.0) -> None:
    """Deduct an actual spend; trip ``budget_hard_stop`` if exhausted."""
    state.token_budget_remaining -= tokens
    state.cost_so_far += cost
    if state.token_budget_remaining <= 0 or \
            state.cost_so_far > state.cost_cap:
        state.budget_hard_stop = True
