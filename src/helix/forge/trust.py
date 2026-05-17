"""Trust telemetry → data-driven autonomy (HELIX.md §5.6).

Autonomy modes are inert if the user has no basis for trusting an
agent. Helix already logs every gate decision, so it closes the loop at
zero extra cost:

* After each gate, record whether the human approved the recommendation
  **unchanged** (``gate_agreement``).
* When recent agreement is consistently high, *propose* raising that
  gate's autonomy — a one-tap suggestion, **never** automatic.
* If an auto-approved step is later reverted or salvaged, that gate
  **auto-demotes** to ``always_ask`` and says why.

The asymmetry is deliberate: promotion is opt-in and evidence-gated;
demotion is automatic and immediate. Trust is earned slowly, lost fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from helix.forge.state import ForgeState

_LADDER = ["always_ask", "ask_if_concerning", "auto"]
_HISTORY_CAP = 20
DEFAULT_PROMOTE_AFTER = 3  # N approved-unchanged in a row to suggest


@dataclass
class AutonomySuggestion:
    gate: str
    current: str
    proposed: str
    streak: int
    rationale: str


def record_gate_outcome(
    state: ForgeState, gate: str, approved_unchanged: bool
) -> None:
    """Append one gate outcome to the trust history (bounded)."""
    hist = state.gate_agreement.setdefault(gate, [])
    hist.append(bool(approved_unchanged))
    if len(hist) > _HISTORY_CAP:
        del hist[:-_HISTORY_CAP]


def autonomy_suggestion(
    state: ForgeState, gate: str, *, promote_after: int = DEFAULT_PROMOTE_AFTER
) -> Optional[AutonomySuggestion]:
    """Propose (never apply) raising a gate one rung when the last
    ``promote_after`` outcomes were all approved-unchanged."""
    mode = state.mode_for(gate)
    if mode == "auto":
        return None  # already at the top rung
    hist = state.gate_agreement.get(gate, [])
    if len(hist) < promote_after or not all(hist[-promote_after:]):
        return None
    proposed = _LADDER[_LADDER.index(mode) + 1]
    return AutonomySuggestion(
        gate=gate, current=mode, proposed=proposed,
        streak=_trailing_streak(hist),
        rationale=(f"You approved {gate} unchanged "
                   f"{_trailing_streak(hist)}× in a row — raise autonomy "
                   f"to '{proposed}'? (one-tap; reversible)"),
    )


def _trailing_streak(hist: List[bool]) -> int:
    n = 0
    for v in reversed(hist):
        if not v:
            break
        n += 1
    return n


def apply_autonomy(state: ForgeState, gate: str, mode: str) -> None:
    """Apply an accepted suggestion (explicit user action only)."""
    if mode not in _LADDER:
        raise ValueError(f"invalid autonomy mode: {mode!r}")
    state.autonomy[gate] = mode


def auto_demote_on_revert(
    state: ForgeState, gate: str, *, cause: str = "revert"
) -> str:
    """An auto-approved step was reverted/salvaged (§6.4): drop the gate
    straight back to ``always_ask`` and clear its trust history so the
    streak must be re-earned. Returns a human-readable reason."""
    state.autonomy[gate] = "always_ask"
    state.gate_agreement[gate] = []
    return (f"gate '{gate}' auto-demoted to always_ask: an auto-approved "
            f"step was {cause} — trust must be re-earned")
