"""Notification triage — one digest, not a stream of pings (§9.5).

The user is interrupted exactly when work is genuinely blocked on them,
and never otherwise — which is what makes running several projects at
once tolerable. So:

* only **Needs-you-now** items are real-time *push*-worthy;
* **Working** completions and **FYI** items (Watcher, Maintainer
  suggestions, budget warnings) **batch into one digest**, never
  per-event pings;
* **one badge** = the Needs-you-now count;
* **quiet hours on by default** — during quiet hours even the
  push-worthy items only update the badge; nothing interrupts.

This module is the triage *policy* + the batched digest. The actual
push transport (mobile/QR, §11) is the build-step-14 opt-in — it is
deliberately NOT faked here; nothing pretends a notification was sent.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Callable, List

from helix.queue import FYI, NEEDS_YOU, WORKING, QueueItem


def _now() -> _dt.datetime:
    return _dt.datetime.now()


@dataclass
class Triage:
    badge: int                                  # the one badge (§9.5)
    push: List[QueueItem] = field(default_factory=list)     # blocking only
    digest: List[QueueItem] = field(default_factory=list)    # batched
    quiet: bool = True

    def summary(self) -> str:
        if self.quiet:
            note = ("quiet hours on — only the badge updates in real "
                    "time; everything below is batched, nothing pinged")
        elif self.push:
            note = (f"{len(self.push)} blocking item(s) are push-worthy; "
                    f"{len(self.digest)} batched (no per-event pings)")
        else:
            note = (f"nothing blocking — {len(self.digest)} item(s) "
                    f"batched in this digest, no pings")
        return (f"🔔 badge: {self.badge}   "
                f"({len(self.digest)} batched)\n   {note}")


def in_quiet_hours(now: _dt.datetime, start: int = 22, end: int = 7) -> bool:
    """Default quiet hours 22:00–07:00 local. On by default (§9.5)."""
    h = now.hour
    return h >= start or h < end


def triage(items: dict, *, quiet_hours_enabled: bool = True,
           now: Callable[[], _dt.datetime] = _now) -> Triage:
    """Classify collected queue buckets into push vs one batched digest.

    Push = Needs-you-now only. Working completions + FYI are batched —
    never per-event. During quiet hours nothing is push-worthy (badge
    only); the digest is unaffected (it was never a ping anyway).
    """
    needs = list(items.get(NEEDS_YOU, []))
    batched = list(items.get(WORKING, [])) + list(items.get(FYI, []))
    quiet = quiet_hours_enabled and in_quiet_hours(now())
    return Triage(
        badge=len(needs),
        push=[] if quiet else needs,
        digest=batched,
        quiet=quiet,
    )
