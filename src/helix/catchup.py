"""Catch-me-up on re-entry (HELIX.md §9.6).

When the queue is opened after >24h idle, each active project leads
with a 2–3 line generated digest. It is the **same deterministic
renderer as §7** (the decision log) — so it costs nothing extra and
can never drift: returning after a week never means reconstructing
state by hand.

The "last opened" pointer is **view state** (like the Loom cursor,
§7.7.5): a per-home timestamp that is never written to a Snapshot, the
decision log, or a fork bundle, and for which "out of sync" is
meaningless. Opening the queue (`helix`) advances it; a read-only
`helix peek` does NOT (a peek is a look, not an open).
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from typing import Callable, List, Optional

IDLE_HOURS = 24


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _humanize_since(ts: _dt.datetime, now: _dt.datetime) -> str:
    delta = now - ts
    days = delta.days
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    return f"{days // 7} weeks ago"


@dataclass
class CatchUp:
    app: object
    now: Callable[[], _dt.datetime] = _now

    # ---- idle cursor (pure view state, §7.7.5 semantics) ------------

    def _cursor_path(self):
        d = self.app.home / ".helix"
        d.mkdir(parents=True, exist_ok=True)
        return d / "last-open.json"

    def last_open(self) -> Optional[_dt.datetime]:
        p = self._cursor_path()
        if not p.exists():
            return None
        try:
            return _dt.datetime.fromisoformat(
                json.loads(p.read_text())["ts"])
        except (OSError, ValueError, KeyError):
            return None

    def mark_opened(self) -> None:
        self._cursor_path().write_text(
            json.dumps({"ts": self.now().isoformat()}))

    def is_idle_reentry(self) -> bool:
        lo = self.last_open()
        if lo is None:
            return False  # first ever open is not a "re-entry"
        return (self.now() - lo) > _dt.timedelta(hours=IDLE_HOURS)

    # ---- the per-project digest (decision-log projection) -----------

    def project_digest(self, project: str) -> Optional[str]:
        log = self.app.decision_log(project)
        entries = log.entries()
        if not entries:
            return None
        recent = entries[-3:]
        first_ts = _parse_ts(recent[0].get("timestamp"))
        since = (_humanize_since(first_ts, self.now())
                 if first_ts else "recently")
        chain = " → ".join(_short(e) for e in recent)
        return f"{project}, since {since}: {chain}. {self._status(project)}"

    def _status(self, project: str) -> str:
        # Workflow status if a run exists; else lifecycle tier.
        if (self.app.home / "forge.sqlite").exists():
            try:
                st = self.app.workflow().pending(project)
                if st["status"] == "interrupted":
                    return "**Waiting on your approval.**"
                if st["status"] == "running":
                    return f"Running ({', '.join(st.get('next', []))})."
            except Exception:  # noqa: BLE001 — never break catch-me-up
                pass
        try:
            tier = self.app.projects.get(project).rung
            return ("Frozen — published." if tier == "published"
                    else f"Idle at '{tier}'.")
        except Exception:  # noqa: BLE001
            return "Up to date."

    def all_active(self) -> List[str]:
        out = []
        for p in self.app.projects.list():
            if p.tier != "archived" and self.app.decision_log(
                    p.name).entries():
                out.append(p.name)
        return out


def _short(entry: dict) -> str:
    act = entry.get("action", "?")
    rat = (entry.get("rationale") or "").strip().split(".")[0]
    rat = rat.split("(")[0].strip()
    return f"{act}" + (f" ({rat[:48]})" if rat and rat != act else "")


def _parse_ts(ts: Optional[str]) -> Optional[_dt.datetime]:
    if not ts:
        return None
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
