"""PI co-sign on high-stakes gates (HELIX.md §13, §9.3).

In regulated biomedical/IRB/PHI work an "AI chose, human rubber-
stamped" record is *exposure*. Helix turns this around: ``auto_or_human``
+ the teach-back sentence + an optional **PI co-sign** make the
decision log a defensible audit/attestation trail (§13).

A project is **high-stakes** when it is ``published``-tier or
privacy=strict (the regulated/IRB/PHI proxy, consistent with the §9.3
tier-scoped teach-back). For such a project every human gate decision
needs a PI countersignature. Research still proceeds on the
researcher's decision — but the *attestable artifact is incomplete*,
and the Maintainer **refuses to freeze/publish** until every
high-stakes decision is co-signed. The enforcement lives at the one
genuinely high-stakes moment (publication), not as a second interrupt
on every gate — the value §13 wants is the recorded countersignature,
not doubled HITL.
"""

from __future__ import annotations

from typing import List

_SIGNABLE = {"approve", "ship", "pick", "trim", "expand", "rebuild",
             "replan", "fix", "freeze"}


def _is_signable(action: str) -> bool:
    return (action.split(":", 1)[0] in _SIGNABLE
            or action.startswith("pick:"))


class CoSign:
    def __init__(self, app):
        self.app = app

    def required(self, project: str) -> bool:
        """High-stakes ⇒ regulated/IRB/PHI. §13 makes co-sign
        **optional**; §9.3 warns against paternalism on the solo
        non-regulated user. So the trigger is *opt-in*: privacy=strict
        (a strong PHI proxy) OR an explicit ``--pi`` on the project —
        not merely 'it got published'."""
        try:
            p = self.app.projects.get(project)
        except Exception:  # noqa: BLE001
            return False
        return p.privacy_mode == "strict" or bool(p.pi)

    def pending(self, project: str) -> List[str]:
        """Human gate decisions on an opt-in high-stakes project with no
        PI countersignature yet (the compliance gap)."""
        if not self.required(project):
            return []
        entries = self.app.decision_log(project).entries()
        signed = {ev for e in entries if e["action"] == "cosign"
                  for ev in e.get("evidence", [])}
        return [e["id"] for e in entries
                if e.get("auto_or_human") == "human"
                and _is_signable(e["action"])
                and e["id"] not in signed]

    def sign(self, project: str, pi: str,
             decision_id: str = "") -> List[str]:
        """Record a PI countersignature (a logged + Snapshotted
        attestation). Signs the given decision, or all pending."""
        targets = [decision_id] if decision_id else self.pending(project)
        if not targets:
            return []
        log = self.app.decision_log(project)
        log.append(
            stage="attestation", action="cosign",
            rationale=f"PI '{pi}' countersigned {len(targets)} "
                      f"high-stakes decision(s): {', '.join(targets)} "
                      f"(§13 attestation trail).",
            evidence=list(targets), auto_or_human="human")
        self.app.snapshots(project).mint(
            decision_head=log.head(), reason="cosign")
        return targets
