"""The gate-view model (HELIX.md §9.3, §7.4).

A blocking gate opens into a decision view designed so the common path
is a single tap and depth is available but never required:

* the **recommended** option, pre-selected;
* a **3-bullet why** (the §7 decision-log renderer — free);
* a **confidence/abstention** signal (deterministic proxy from the
  structural critic — honestly not LLM self-consistency);
* **pick-not-type** alternatives — tap the rationale that matches, free
  typing is the escape hatch (§9.3);
* **tier-scoped teach-back** — OFF on notes/project tiers (banner only),
  ON on published / privacy-strict (the attestation trail is the
  deliverable there, §9.3);
* a **soft-commit window** (default 20s) — nothing irreversible runs
  until it elapses, and ``helix undo`` reverts regardless;
* a **branch compare** block when >1 research line exists (§7.4): the
  gate is a side-by-side, not a one-shot irreversible pick.

This module is a pure data model; the CLI/queue render it and the
LangGraph interrupt carries it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from helix.forge.router import gate_decision
from helix.forge.state import ForgeState

GATE_TITLES = {
    "scope": "Approve the scope?",
    "methods": "Approve the approach?",
    "plan": "Approve the plan?",
    "build": "Approve the build?",
    "results": "Approve the results?",
    "budget": "Budget exceeded — how to proceed?",
}

# Per-gate actionable options. ``pick:<id>`` is expanded per candidate.
GATE_OPTIONS = {
    "scope": [("approve", "Approve scope"),
              ("redo_with_focus", "Re-scan with a tighter focus"),
              ("abandon", "Abandon")],
    "methods": [("revise", "Send back to Critic-Methods"),
                ("back_to_scout", "Back to Scout")],
    "plan": [("approve", "Approve plan"), ("trim", "Trim scope"),
             ("expand", "Expand scope"),
             ("back_to_methods", "Back to methods")],
    "build": [("approve", "Approve build"), ("fix", "Request a fix"),
              ("back_to_planner", "Back to planner")],
    "results": [("ship", "Ship"), ("rebuild", "Rebuild"),
                ("replan", "Replan"), ("reread_lit", "Re-read literature"),
                ("abandon", "Abandon")],
}
SOFT_COMMIT_SECONDS = 20


@dataclass
class GateOption:
    id: str
    label: str
    recommended: bool = False


@dataclass
class GateView:
    project: str
    gate: str
    title: str
    options: List[GateOption]
    recommended: str
    why: List[str]
    confidence: float
    unsure_about: str
    would_change_my_mind: str
    alternatives: List[str]
    teach_back_required: bool
    soft_commit_seconds: int
    cosign_required: bool = False
    pause_reasons: List[str] = field(default_factory=list)
    compare: List[Dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "project": self.project, "gate": self.gate,
            "title": self.title, "recommended": self.recommended,
            "options": [{"id": o.id, "label": o.label,
                         "recommended": o.recommended} for o in self.options],
            "why": self.why, "confidence": self.confidence,
            "unsure_about": self.unsure_about,
            "would_change_my_mind": self.would_change_my_mind,
            "alternatives": self.alternatives,
            "teach_back_required": self.teach_back_required,
            "cosign_required": self.cosign_required,
            "soft_commit_seconds": self.soft_commit_seconds,
            "pause_reasons": self.pause_reasons,
            "compare": self.compare,
        }


def _worst_severity(state: ForgeState, gate: str) -> str:
    worst = "none"
    order = {"none": 0, "info": 1, "warning": 2, "blocking": 3}
    for c in state.critiques:
        if c.get("gate") not in (None, gate):
            continue
        sev = str(c.get("severity", "")).lower()
        if order.get(sev, 0) > order.get(worst, 0):
            worst = sev
    return worst


def _confidence(worst: str) -> float:
    # Deterministic proxy from the structural critic — NOT LLM
    # self-consistency. Lower confidence ⇒ §9.3 adds friction.
    return {"none": 0.85, "info": 0.85, "warning": 0.5,
            "blocking": 0.2}.get(worst, 0.5)


def _options_for(state: ForgeState, gate: str, recommended: str
                 ) -> List[GateOption]:
    opts: List[GateOption] = []
    if gate in ("methods",):
        for c in state.candidate_approaches:
            opts.append(GateOption(f"pick:{c['id']}",
                                   f"Pick {c.get('label', c['id'])}"))
    for oid, label in GATE_OPTIONS.get(gate, [("approve", "Approve")]):
        opts.append(GateOption(oid, label))
    if not opts:
        opts = [GateOption("approve", "Approve")]
    for o in opts:
        o.recommended = (o.id == recommended)
    return opts


def _recommended(state: ForgeState, gate: str) -> str:
    if gate == "methods" and state.candidate_approaches:
        return f"pick:{state.candidate_approaches[0]['id']}"
    if gate == "scope":
        return "approve" if state.candidate_approaches else "redo_with_focus"
    if gate == "results":
        return "ship"
    return "approve"


def _teach_back_required(app, project: str, state: ForgeState) -> bool:
    """Tier-scoped (§9.3): OFF on notes/project, ON on published or
    any privacy-strict / regulated project."""
    if state.privacy_mode == "strict":
        return True
    try:
        tier = app.projects.get(project).tier
    except Exception:  # noqa: BLE001
        tier = state.project_tier
    return tier in ("published", "archived")


def _compare(app, project: str) -> List[Dict[str, Any]]:
    """§7.4: when >1 research line exists the gate is a side-by-side."""
    snaps = app.snapshots(project)
    branches = snaps.branches()
    if len(branches) < 2:
        return []
    log = app.decision_log(project)
    entries = log.entries()
    last = entries[-1]["rationale"] if entries else ""
    return [{"branch": b, "head": h, "parked": snaps.is_parked(b),
             "last_rationale": last} for b, h in sorted(branches.items())]


def _cosign_required(app, project: str) -> bool:
    try:
        from helix.cosign import CoSign
        return CoSign(app).required(project)
    except Exception:  # noqa: BLE001
        return False


def build_gateview(app, project: str, state: ForgeState,
                    gate: str) -> GateView:
    rec = _recommended(state, gate)
    worst = _worst_severity(state, gate)
    decision = gate_decision(state, gate)
    log = app.decision_log(project)
    entries = log.entries()
    why = (log.why_bullets(entries[-1]) if entries
           else ["No prior decision yet."])
    if worst in ("warning", "blocking"):
        why = [f"Critic-{gate} severity: {worst}"] + why
    label_of = {f"pick:{c['id']}": c.get("label", c["id"])
                for c in state.candidate_approaches}
    alts = [
        f"{label_of.get(rec, rec)} best addresses the critique",
        "It has the strongest supporting evidence",
        "It carries the fewest known failure modes",
    ]
    return GateView(
        project=project, gate=gate,
        title=GATE_TITLES.get(gate, f"Approve {gate}?"),
        options=_options_for(state, gate, rec),
        recommended=rec, why=why,
        confidence=_confidence(worst),
        unsure_about=(f"structural signal only ({worst}); the LLM critic "
                      f"upgrade adds semantic judgement"),
        would_change_my_mind=("a blocking critique, a sanity flag, or a "
                               "contradiction vs canonical knowledge"),
        alternatives=alts,
        teach_back_required=_teach_back_required(app, project, state),
        cosign_required=_cosign_required(app, project),
        soft_commit_seconds=SOFT_COMMIT_SECONDS,
        pause_reasons=decision.reasons,
        compare=_compare(app, project),
    )
