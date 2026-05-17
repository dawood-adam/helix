"""Opt-in upgrade registry (HELIX.md §11.1).

The stack in §11 is the *full* configuration; the **default** is
deliberately minimal and every heavy integration is an opt-in upgrade
off the zero-integration critical path. This module is the single
registry of those upgrades + their honest adapters.

The load-bearing rule here is **no fake success**: an upgrade that
needs an external service / API key / extra package that is not
present **fails closed with exact instructions** when selected — it
never returns fabricated results. These adapters can't be verified in
a sandbox without the services, so faking them would be a lie; the
honest, testable contract is "select it unconfigured → actionable
error", which *is* verified.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import List, Optional


class UpgradeNotConfigured(RuntimeError):
    """Selected an opt-in upgrade whose dependency/key/service is
    absent. Carries exactly how to enable it (never a fake fallback)."""


@dataclass
class Upgrade:
    id: str
    capability: str
    default: str
    upgrade: str
    how: str                      # exactly how to enable it
    env: Optional[str] = None     # env var that signals "configured"
    module: Optional[str] = None  # importable that signals "configured"

    def configured(self) -> bool:
        if self.env and os.environ.get(self.env):
            return True
        if self.module and importlib.util.find_spec(self.module) is not None:
            return True
        return False

    def require(self) -> None:
        if not self.configured():
            raise UpgradeNotConfigured(
                f"{self.capability}: the '{self.upgrade}' upgrade is not "
                f"configured. {self.how} (Helix will not fabricate "
                f"results — §11.1 no-fake-success.)")


REGISTRY: List[Upgrade] = [
    Upgrade("explore-futurehouse", "Explore body",
            "built-in arXiv search", "FutureHouse / Open Deep Research",
            "set $FUTUREHOUSE_API_KEY and `helix config set "
            "explore.backend futurehouse`", env="FUTUREHOUSE_API_KEY"),
    Upgrade("builder-claude-code", "Builder",
            "local scaffold sandbox", "Claude Code / Deep Agents",
            "install the Claude Code CLI and `helix config set "
            "builder.backend claude-code`", module="claude_code"),
    Upgrade("validator-langsmith", "Validator tracking",
            "local run-log file", "LangSmith + MLflow",
            "pip install langsmith mlflow and set $LANGSMITH_API_KEY",
            module="langsmith"),
    Upgrade("checkpointer-postgres", "State / Atlas checkpointer",
            "SQLite (local)", "Postgres checkpointer",
            "pip install langgraph-checkpoint-postgres and `helix config "
            "set checkpointer.dsn postgresql://...`",
            module="langgraph.checkpoint.postgres"),
    Upgrade("data-dvc", "Data store",
            "built-in content-addressed store (.helix/cas)",
            "DVC / git-LFS",
            "install dvc and `helix config set data.backend dvc`",
            module="dvc"),
    Upgrade("qr-image", "Mobile pairing",
            "printed pairing URL + token", "scannable QR image",
            "pip install qrcode to render a scannable code",
            module="qrcode"),
    Upgrade("gates-mobile", "Gates surface",
            "the `helix` queue (CLI)", "mobile push + QR web view",
            "`helix serve` then open the printed URL on your phone "
            "(built-in, zero-dep — already available)"),
    Upgrade("watcher", "Watcher", "off",
            "cron + paper feeds",
            "`helix watcher schedule` then cron-wrap `helix watcher run` "
            "(built-in — already available)"),
]


def by_id(uid: str) -> Upgrade:
    for u in REGISTRY:
        if u.id == uid:
            return u
    raise KeyError(uid)


def status_lines() -> List[str]:
    out = []
    for u in REGISTRY:
        builtin = u.how.endswith("already available)")
        mark = ("✓ built-in" if builtin else
                ("✓ configured" if u.configured() else "○ available"))
        out.append(f"  [{mark}] {u.capability}: {u.default}"
                   + (f"  →  {u.upgrade} ({u.how})" if not builtin
                      else ""))
    return out
