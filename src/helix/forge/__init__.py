"""Forge — the workflow runtime control logic (HELIX.md §5).

This package is the *control skeleton* (build step 8): the pure,
dependency-free routing rules that decide when a gate may auto-approve,
how Validator sanity flags route, when the budget halts a run, and how
trust telemetry proposes autonomy changes. The LangGraph wiring that
calls these rules is build step 9.

Everything here is deliberately **non-LLM and deterministic** — that is
the whole point of §5.3: pause/route decisions are hard rules a router
validates, never an agent self-assessing whether it is "concerning
enough" (which fails silent). Absence is never the happy path.
"""

from helix.forge.router import (
    BudgetOutcome,
    GateOutcome,
    RouteDecision,
    budget_check,
    commit_cost,
    gate_decision,
    sanity_route,
)
from helix.forge.state import (
    GATES,
    AutonomyMode,
    ForgeState,
    Severity,
    default_autonomy,
)
from helix.forge.trust import (
    AutonomySuggestion,
    apply_autonomy,
    auto_demote_on_revert,
    autonomy_suggestion,
    record_gate_outcome,
)
from helix.forge.agents import Agents, BuiltinAgents, FakeAgents
from helix.forge.gateview import GateView, build_gateview
from helix.forge.workflow import WorkflowEngine, build_graph

__all__ = [
    "ForgeState",
    "AutonomyMode",
    "Severity",
    "GATES",
    "default_autonomy",
    "gate_decision",
    "sanity_route",
    "budget_check",
    "commit_cost",
    "GateOutcome",
    "RouteDecision",
    "BudgetOutcome",
    "record_gate_outcome",
    "autonomy_suggestion",
    "apply_autonomy",
    "auto_demote_on_revert",
    "AutonomySuggestion",
    "Agents",
    "BuiltinAgents",
    "FakeAgents",
    "GateView",
    "build_gateview",
    "WorkflowEngine",
    "build_graph",
]
