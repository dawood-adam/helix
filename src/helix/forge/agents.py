"""Agent bodies (HELIX.md §5.1, §11.1).

The workflow graph (step 9) is orchestration; the *bodies* are a
pluggable seam. Per §11.1 the **default** bodies are zero-integration
and deterministic — they do real, lightweight work and are honest
about their limits. They are NOT pretending to be the LLM agents:

* **Scout** reuses the built-in Explore (real arXiv search, step 6)
  and derives *seed* candidate approaches from the coverage gaps —
  labelled heuristic seeds, not LLM-synthesised method designs.
* **Critic-Methods/Results** are deterministic **structural**
  pre-flight checkers that emit the typed ``severity`` the router
  validates (§5.3) — not an LLM forming an opinion.
* **Planner** emits a template plan scaffold.
* **Builder** writes a code scaffold + records a content sha — not a
  trained model (that's the Claude Code upgrade).
* **Validator** computes the §5.4 flag detectors from *actually
  recorded* results; with no results it leaves flags absent so the
  router fails closed — it never invents metrics.

The LLM upgrade (FutureHouse / Claude Code / reflection critics) plugs
into this same protocol; it is intentionally not implemented here
rather than faked. ``FakeAgents`` gives tests deterministic, offline,
fully-controllable bodies.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Protocol

from helix.forge.state import ForgeState


class Agents(Protocol):
    def scout(self, app, project: str, s: ForgeState) -> Dict[str, Any]: ...
    def critic_methods(self, app, project: str,
                        s: ForgeState) -> Dict[str, Any]: ...
    def planner(self, app, project: str, s: ForgeState) -> Dict[str, Any]: ...
    def builder(self, app, project: str, s: ForgeState) -> Dict[str, Any]: ...
    def validator(self, app, project: str,
                   s: ForgeState) -> Dict[str, Any]: ...
    def critic_results(self, app, project: str,
                        s: ForgeState) -> Dict[str, Any]: ...


def _crit(gate: str, severity: str, summary: str) -> Dict[str, Any]:
    return {"gate": gate, "severity": severity, "summary": summary}


class BuiltinAgents:
    """Zero-integration deterministic bodies (§11.1 default)."""

    def scout(self, app, project, s) -> Dict[str, Any]:
        query = s.research_question or project.replace("-", " ")
        cands: List[Dict[str, Any]] = []
        try:
            result = app.explorer().run(query, limit=8)
            for i, gap in enumerate(result.gaps[:3], 1):
                cands.append({
                    "id": f"approach-{i}",
                    "label": gap,
                    "summary": (f"Address the under-covered area "
                                f"'{gap}' surfaced by the literature scan."),
                    "evidence": result.source_handles[:3],
                })
        except Exception as e:  # noqa: BLE001 — honest: no fake papers
            return {"candidate_approaches": [],
                    "next_action": "scout_failed",
                    "critiques": s.critiques + [_crit(
                        "scope", "blocking",
                        f"literature scan failed: {e}")]}
        return {"candidate_approaches": cands,
                "scout_summary_ref": query}

    def critic_methods(self, app, project, s) -> Dict[str, Any]:
        n = len(s.candidate_approaches)
        if n == 0:
            c = _crit("methods", "blocking", "no candidate approaches")
        elif n == 1:
            c = _crit("methods", "warning",
                      "only one approach — thin alternative set "
                      "(consider `helix branch`)")
        else:
            c = _crit("methods", "info", f"{n} candidate approaches")
        return {"critiques": s.critiques + [c]}

    def planner(self, app, project, s) -> Dict[str, Any]:
        chosen = s.chosen_approach_id or (
            s.candidate_approaches[0]["id"] if s.candidate_approaches
            else None)
        return {"project_plan": {
            "chosen_approach": chosen,
            "phases": ["build", "validate"],
            "target_metrics": {"primary": {
                "name": "error", "target_band": [0.0, 0.10]}},
            "validation_cascade": ["sanity", "holdout"],
            "_note": "template scaffold (built-in Planner); the LLM "
                     "Planner upgrade refines this",
        }}

    def builder(self, app, project, s) -> Dict[str, Any]:
        plan = s.project_plan or {}
        scaffold = (f"# scaffold for {project}\n"
                    f"# approach={plan.get('chosen_approach')}\n"
                    f"def run():\n    raise NotImplementedError\n")
        rel = f"projects/{project}/code/scaffold.py"
        dest = app.store.abspath(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(scaffold)
        sha = "sha256:" + hashlib.sha256(scaffold.encode()).hexdigest()[:12]
        return {"code_artifacts": [
            {"path": rel, "purpose": "scaffold", "git_sha": sha}]}

    def validator(self, app, project, s) -> Dict[str, Any]:
        """Deterministic §5.4 flag detectors over *recorded* results.

        Results manifest: ``projects/<p>/results/latest.json``. Absent →
        flags stay absent and the router fails closed (no fake metrics).
        """
        path = app.store.layout.project_dir(project) / "results" / \
            "latest.json"
        if not path.exists():
            return {"validator_complete": False,
                    "sanity_check_flags": None}
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"validator_complete": False,
                    "sanity_check_flags": None}
        flags: List[str] = []
        if data.get("train_test_overlap"):
            flags.append("leakage_detected")     # deterministic integrity
        band = ((s.project_plan or {}).get("target_metrics", {})
                .get("primary", {}).get("target_band"))
        metric = data.get("error")
        if band and metric is not None and not (
                band[0] <= metric <= band[1]):
            flags.append("plan_violation")        # deterministic band miss
        return {"experiment_results": [data],
                "validator_complete": True,
                "sanity_check_flags": flags or ["clean"]}

    def critic_results(self, app, project, s) -> Dict[str, Any]:
        if not s.experiment_results:
            c = _crit("results", "blocking", "no experiment results")
        else:
            c = _crit("results", "info",
                      "results present; structural check passed")
        return {"critiques": s.critiques + [c]}


class FakeAgents(BuiltinAgents):
    """Deterministic, offline, fully controllable — for tests.

    ``inject`` lets a test force Validator flags to exercise the §5.4
    auto-routing without any real run.
    """

    def __init__(self, n_candidates: int = 2, inject_flags=("clean",),
                 validator_complete: bool = True):
        self.n_candidates = n_candidates
        # None means "Validator wrote nothing" — exercises the §5.4
        # fail-closed path; only listify a real flag set.
        self.inject_flags = (None if inject_flags is None
                             else list(inject_flags))
        self.validator_complete = validator_complete

    def scout(self, app, project, s) -> Dict[str, Any]:
        return {"candidate_approaches": [
            {"id": f"approach-{i}", "label": f"opt{i}",
             "summary": f"deterministic approach {i}", "evidence": []}
            for i in range(1, self.n_candidates + 1)],
            "scout_summary_ref": "fake"}

    def builder(self, app, project, s) -> Dict[str, Any]:
        return {"code_artifacts": [
            {"path": "fake.py", "purpose": "fake", "git_sha": "sha256:fake"}]}

    def validator(self, app, project, s) -> Dict[str, Any]:
        return {"experiment_results": [{"error": 0.05}],
                "validator_complete": self.validator_complete,
                "sanity_check_flags": (list(self.inject_flags)
                                       if self.inject_flags is not None
                                       else None)}
