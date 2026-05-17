"""The project workflow loop — LangGraph wired through Atlas (§5.2, §9.3).

Orchestration only: every *decision* is a step-8 pure rule
(:func:`gate_decision`, :func:`sanity_route`, :func:`budget_check`),
every gate is a LangGraph ``interrupt`` (HITL, §9.3), and every
meaningful point appends a canonical decision-log entry **and** mints a
Snapshot (§5.4, §7.3) through the shared single-writer core. Forge
state is checkpointed in SQLite (the §11 local default) so a gate can
be resolved by a *separate* ``helix`` process.

Agent bodies are the pluggable seam from :mod:`helix.forge.agents`
(deterministic built-ins by default; FakeAgents in tests).
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Any, Dict, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from helix.forge.agents import Agents, BuiltinAgents
from helix.forge.gateview import build_gateview
from helix.forge.router import budget_check, commit_cost, gate_decision, \
    sanity_route
from helix.forge.state import ForgeState

_BUILD_TOKEN_EST = 500          # the "expensive" loop, for the budget gate
_AGENT_TOKEN_EST = 200          # tiny built-in cost so the meter is real

# next_action -> graph node id
_ROUTE = {
    "SCOUT": "scout", "CRITIC_METHODS": "critic_methods",
    "PLANNER": "planner", "BUILDER": "builder", "VALIDATOR": "validator",
    "CRITIC_RESULTS": "critic_results", "MAINTAINER": "maintainer",
    "END": END,
}


def _record(app, project: str, gate: str, action: str, *,
            state: "ForgeState", rationale: str, auto: bool,
            evidence=None) -> None:
    """One canonical decision-log entry + one *fully-bound* Snapshot.

    §7.3 keystone: the Snapshot binds decision head, **code sha**
    (from the Builder's artifact in ForgeState), **Atlas page versions**
    and model routing. ``data_hashes``/``env_lock`` stay empty — they
    are the content-addressed data store + env capture (§7.6), build
    step 14 — and are honestly left unbound rather than faked.
    """
    log = app.decision_log(project)
    log.append(stage=gate, action=action, rationale=rationale,
               evidence=list(evidence or []),
               auto_or_human="auto" if auto else "human")
    try:
        # §9.9: a strict project records its DEGRADED (local/ZDR)
        # routing in the Snapshot — the trade-off is visible + the
        # repro is faithful to what actually ran.
        routing, _ = app.router.resolve_all(
            project=project,
            privacy_strict=state.privacy_mode == "strict")
    except Exception:  # noqa: BLE001 — routing optional / privacy unsat
        routing = {}
    code_sha = (state.code_artifacts[-1].get("git_sha")
                if state.code_artifacts else None)
    from helix.cas import project_data_hashes
    from helix.snapshot import project_atlas_binding

    app.snapshots(project).mint(
        decision_head=log.head(), reason=f"gate_{gate}",
        code_sha=code_sha,
        atlas_pages=project_atlas_binding(
            app.store.index, project, state.scout_summary_ref,
            app.decision_log(project).entries()),
        data_hashes=project_data_hashes(app, project),
        model_routing=routing)


def _resume_choice(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise the value the CLI passes via Command(resume=...)."""
    if isinstance(payload, dict):
        return {"option": payload.get("option", "approve"),
                "rationale": payload.get("rationale", "")}
    return {"option": str(payload), "rationale": ""}


def build_graph(app, project: str, agents: Agents):
    """Compile the §5.2 graph for one project, checkpointed in SQLite."""

    # ---- agent nodes -------------------------------------------------

    def _agent(fn_name: str):
        def node(state: ForgeState) -> Dict[str, Any]:
            upd = getattr(agents, fn_name)(app, project, state)
            commit_cost(state, tokens=_AGENT_TOKEN_EST)
            upd["token_budget_remaining"] = state.token_budget_remaining
            upd["cost_so_far"] = state.cost_so_far
            upd["budget_hard_stop"] = state.budget_hard_stop
            return upd
        return node

    # ---- a HITL gate -------------------------------------------------

    def _gate(gate: str):
        def node(state: ForgeState) -> Dict[str, Any]:
            decision = gate_decision(state, gate)
            if decision.auto_approved:
                opt = _default_option(state, gate)
                return _apply_gate(app, project, state, gate, opt,
                                   rationale="auto: all hard-rule "
                                             "triggers clear", auto=True)
            gv = build_gateview(app, project, state, gate)
            # Suspends here; a separate process resolves it (spike-proven).
            choice = _resume_choice(interrupt(gv.to_payload()))
            return _apply_gate(app, project, state, gate, choice["option"],
                               rationale=choice["rationale"]
                               or f"human: {choice['option']}", auto=False)
        return node

    # ---- the §5.5 enforced budget gate ------------------------------

    def gate_budget(state: ForgeState) -> Dict[str, Any]:
        bc = budget_check(state, tokens=_BUILD_TOKEN_EST)
        if not bc.halt:
            return {"next_action": "BUILDER"}
        choice = _resume_choice(interrupt({
            "project": project, "gate": "budget",
            "title": "Budget exceeded — how to proceed?",
            "pause_reasons": bc.reasons,
            "options": [{"id": "continue", "label": "Continue anyway"},
                        {"id": "abandon", "label": "Abandon"}],
            "recommended": "abandon"}))
        if choice["option"] == "continue":
            _record(app, project, "budget", "override", state=state,
                    rationale="human accepted over-budget continuation",
                    auto=False)
            return {"next_action": "BUILDER"}
        _record(app, project, "budget", "abandon", state=state,
                rationale="abandoned at budget gate", auto=False)
        return {"next_action": "END"}

    # ---- the §5.4 Validator -> auto-route edge -----------------------

    def sanity(state: ForgeState) -> Dict[str, Any]:
        rd = sanity_route(state)
        if rd.mode == "proceed":
            return {"next_action": "CRITIC_RESULTS"}
        if rd.mode == "auto":
            _record(app, project, "results", f"auto_route:{rd.flag}",
                    state=state, rationale=rd.reason, auto=True)
            return {"next_action":
                    "PLANNER" if rd.target == "PLANNER" else "BUILDER"}
        if rd.mode == "human_gate":           # drift_severe one-tap confirm
            interrupt({"project": project, "gate": "results",
                       "title": "Literature drift — re-read? (one tap)",
                       "pause_reasons": [rd.reason],
                       "options": [{"id": "confirm", "label": "Re-read"},
                                   {"id": "skip", "label": "Skip"}],
                       "recommended": "confirm"})
            _record(app, project, "results", "auto_route:drift_severe",
                    state=state, rationale=rd.reason, auto=False)
            return {"next_action": "SCOUT"}
        # pause / fail-closed -> the human gate
        return {"next_action": "GATE_RESULTS"}

    g = StateGraph(ForgeState)
    for nid, fn in (("scout", "scout"), ("critic_methods", "critic_methods"),
                    ("planner", "planner"), ("builder", "builder"),
                    ("validator", "validator"),
                    ("critic_results", "critic_results")):
        g.add_node(nid, _agent(fn))
    g.add_node("maintainer", _maintainer(app, project))
    for gate in ("scope", "methods", "plan", "build", "results"):
        g.add_node(f"gate_{gate}", _gate(gate))
    g.add_node("gate_budget", gate_budget)
    g.add_node("sanity", sanity)

    g.add_edge(START, "scout")
    g.add_edge("scout", "gate_scope")
    g.add_edge("critic_methods", "gate_methods")
    g.add_edge("planner", "gate_plan")
    g.add_edge("builder", "gate_build")
    g.add_edge("validator", "sanity")
    g.add_edge("critic_results", "gate_results")
    g.add_edge("maintainer", END)

    g.add_conditional_edges("gate_scope", _next, {
        "CRITIC_METHODS": "critic_methods", "SCOUT": "scout", "END": END})
    g.add_conditional_edges("gate_methods", _next, {
        "PLANNER": "planner", "CRITIC_METHODS": "critic_methods",
        "SCOUT": "scout", "END": END})
    g.add_conditional_edges("gate_plan", _next, {
        "BUILDER": "gate_budget", "CRITIC_METHODS": "critic_methods",
        "END": END})
    g.add_conditional_edges("gate_budget", _next, {
        "BUILDER": "builder", "END": END})
    g.add_conditional_edges("gate_build", _next, {
        "VALIDATOR": "validator", "BUILDER": "builder",
        "PLANNER": "planner", "END": END})
    g.add_conditional_edges("sanity", _next, {
        "CRITIC_RESULTS": "critic_results", "PLANNER": "planner",
        "BUILDER": "builder", "SCOUT": "scout",
        "GATE_RESULTS": "gate_results"})
    g.add_conditional_edges("gate_results", _next, {
        "MAINTAINER": "maintainer", "BUILDER": "builder",
        "PLANNER": "planner", "SCOUT": "scout", "END": END})

    app.home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(app.home / "forge.sqlite"),
                           check_same_thread=False)
    return g.compile(checkpointer=SqliteSaver(conn))


def _maintainer(app, project: str):
    def node(state: ForgeState) -> Dict[str, Any]:
        # The real §5.1 Maintainer: full Atlas lint, repro manifest,
        # within-project drafts (§13), supplement, git tag, and the
        # logged + Snapshotted freeze. (The human 'ship' was already
        # logged at gate_results; this is the distinct freeze action.)
        from helix.maintainer import AttestationIncomplete, Maintainer

        try:
            Maintainer(app).freeze(project)
        except AttestationIncomplete:
            # High-stakes project (§13): research is done, but the
            # attestable artifact awaits the PI countersignature.
            # End gracefully — the cosign NEEDS-YOU queue item carries
            # it; `helix freeze` completes once co-signed. Crashing the
            # workflow here would be wrong.
            app.decision_log(project).append(
                stage="lifecycle", action="awaiting_cosign",
                rationale="Shipped; freeze deferred until PI co-sign "
                          "(§13 attestation trail).",
                auto_or_human="auto")
        return {"next_action": "END"}
    return node


def _next(state: ForgeState) -> str:
    return state.next_action or "END"


def _default_option(state: ForgeState, gate: str) -> str:
    from helix.forge.gateview import _recommended
    return _recommended(state, gate)


def _apply_gate(app, project: str, state: ForgeState, gate: str,
                option: str, *, rationale: str, auto: bool) -> Dict[str, Any]:
    """Map a resolved gate option to a decision-log entry + a route."""
    upd: Dict[str, Any] = {}
    if option.startswith("pick:"):
        upd["chosen_approach_id"] = option.split(":", 1)[1]
        nxt = "PLANNER"
    else:
        nxt = _OPTION_ROUTE.get(gate, {}).get(option, "END")
    _record(app, project, gate, option, state=state, rationale=rationale,
            auto=auto,
            evidence=[state.scout_summary_ref] if state.scout_summary_ref
            else [])
    upd["next_action"] = nxt
    return upd


_OPTION_ROUTE = {
    "scope": {"approve": "CRITIC_METHODS", "redo_with_focus": "SCOUT",
              "abandon": "END"},
    "methods": {"revise": "CRITIC_METHODS", "back_to_scout": "SCOUT"},
    "plan": {"approve": "BUILDER", "trim": "BUILDER", "expand": "BUILDER",
             "back_to_methods": "CRITIC_METHODS"},
    "build": {"approve": "VALIDATOR", "fix": "BUILDER",
              "back_to_planner": "PLANNER"},
    "results": {"ship": "MAINTAINER", "rebuild": "BUILDER",
                "replan": "PLANNER", "reread_lit": "SCOUT",
                "abandon": "END"},
}


class WorkflowEngine:
    """Per-project workflow control (start / resume / inspect)."""

    def __init__(self, app, agents: Optional[Agents] = None):
        self.app = app
        self.agents = agents or BuiltinAgents()

    def _graph_cfg(self, project: str):
        graph = build_graph(self.app, project, self.agents)
        return graph, {"configurable": {"thread_id": project}}

    def start(self, project: str, *, research_question: str = "",
              autonomy: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        graph, cfg = self._graph_cfg(project)
        st = ForgeState(project_name=project,
                        research_question=research_question or project)
        if autonomy:
            st.autonomy.update(autonomy)
        try:
            st.privacy_mode = self.app.projects.get(project).privacy_mode
        except Exception:  # noqa: BLE001
            pass
        graph.invoke(st, cfg)
        return self.pending(project, _graph=graph, _cfg=cfg)

    def resume(self, project: str, option: str,
               rationale: str = "") -> Dict[str, Any]:
        graph, cfg = self._graph_cfg(project)
        graph.invoke(Command(resume={"option": option,
                                     "rationale": rationale}), cfg)
        return self.pending(project, _graph=graph, _cfg=cfg)

    def pending(self, project: str, *, _graph=None, _cfg=None
                ) -> Dict[str, Any]:
        if _graph is None:
            _graph, _cfg = self._graph_cfg(project)
        snap = _graph.get_state(_cfg)
        for task in snap.tasks:
            if task.interrupts:
                return {"status": "interrupted",
                        "gate": task.interrupts[0].value}
        if snap.next:
            return {"status": "running", "next": list(snap.next)}
        return {"status": "done"}
