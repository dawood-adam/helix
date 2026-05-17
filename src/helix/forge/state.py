"""Forge state schema (HELIX.md §5.5).

Working memory of an active workflow. In §5.5 this is a LangGraph
``TypedDict``; here it is a dataclass so step-8 control logic is
validated and testable now. LangGraph accepts a dataclass state schema,
so this stays forward-compatible with the step-9 wiring.

Only the fields the control skeleton needs are modelled in depth;
version-control pointers live in :mod:`helix.snapshot` and are bound in
step 9, not duplicated here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional

# The five explicit human gates (§5.2), keyed by short name. Autonomy
# is per-gate (§5.3).
GATES = ("scope", "methods", "plan", "build", "results")

# Workflow nodes (§5.1 roster) — route targets.
NODES = (
    "SCOUT", "CRITIC_METHODS", "PLANNER", "BUILDER",
    "VALIDATOR", "CRITIC_RESULTS", "MAINTAINER",
)

AutonomyMode = str  # "always_ask" | "ask_if_concerning" | "auto"
_VALID_MODES = {"always_ask", "ask_if_concerning", "auto"}


class Severity(IntEnum):
    """Typed critique severity (§5.3): the critic MUST emit one of these;
    the router validates it — free prose is treated as malformed."""

    INFO = 0
    WARNING = 1
    BLOCKING = 2

    @classmethod
    def parse(cls, value: Any) -> Optional["Severity"]:
        """None when missing/malformed → fail-closed upstream."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls[value.strip().upper()]
            except KeyError:
                return None
        return None


def default_autonomy() -> Dict[str, str]:
    """Every gate starts at ``always_ask`` — the safe default (§5.3)."""
    return {g: "always_ask" for g in GATES}


@dataclass
class ForgeState:
    # Identity
    project_name: str = ""
    research_question: str = ""
    domain_context: str = ""
    project_tier: str = "scratch"
    privacy_mode: str = "normal"

    # HITL autonomy, per gate (§5.3)
    autonomy: Dict[str, str] = field(default_factory=default_autonomy)

    # Validator output (§5.4). ``None`` means "not written" — distinct
    # from an explicit clean run; absence is fail-closed, never clean.
    sanity_check_flags: Optional[List[str]] = None
    validator_complete: bool = False

    # Critiques: structured pointers + a typed severity the router
    # validates (§4.3, §5.3). Each: {gate?, severity, ref?, summary?}.
    critiques: List[Dict[str, Any]] = field(default_factory=list)

    # Contradictions newly flagged vs a canonical page touched this step
    # (§5.3 condition 4). The detector is the (not-faked) LLM-critic
    # concern; the router only reads this structured field.
    contradiction_flags: List[Dict[str, Any]] = field(default_factory=list)

    # Observability + ENFORCED budget (§5.5): a node that would exceed
    # its allocation halts and raises gate_budget — enforced, not shown.
    token_budget_remaining: int = 1_000_000
    cost_so_far: float = 0.0
    cost_cap: float = math.inf
    budget_hard_stop: bool = False

    # Trust telemetry (§5.6): per-gate recent "approved unchanged?".
    gate_agreement: Dict[str, List[bool]] = field(default_factory=dict)

    # Agent working data (§5.5) — populated by the workflow nodes.
    candidate_approaches: List[Dict[str, Any]] = field(default_factory=list)
    chosen_approach_id: Optional[str] = None
    scout_summary_ref: Optional[str] = None
    project_plan: Dict[str, Any] = field(default_factory=dict)
    code_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    experiment_results: List[Dict[str, Any]] = field(default_factory=list)

    # Routing
    next_action: str = ""

    def mode_for(self, gate: str) -> str:
        m = self.autonomy.get(gate, "always_ask")
        return m if m in _VALID_MODES else "always_ask"  # fail-safe
