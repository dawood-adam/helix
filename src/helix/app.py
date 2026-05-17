"""The Helix application facade — one wiring path (HELIX.md §9.11).

The Forge/Atlas split is internal; users see "one project". This
facade is the single place every store is constructed and wired, so
the CLI and tests share identical wiring.

Critically, this is where the **shared process-global write lock** is
threaded through: ``WriteQueue`` owns it, and ``SnapshotStore`` /
``DecisionLog`` serialize on the *same* lock — so the §7
"strongest consistency for the canonical artifact" guarantee actually
holds in the running app (this closes the production-wiring half of
review finding #4; the unit tests only proved it with a hand-passed
lock).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from helix.atlas import AtlasStore, WriteQueue
from helix.decisionlog import DecisionLog
from helix.routing import Router
from helix.snapshot import SnapshotStore


def default_home() -> Path:
    return Path(os.environ.get("HELIX_HOME", str(Path.home() / ".helix")))


class Helix:
    """Constructs and wires Atlas store, write queue, router, projects."""

    def __init__(self, home: Optional[Path] = None):
        self.home = Path(home) if home is not None else default_home()
        self.config_path = self.home / "config.json"
        self.models_path = self.home / "models.toml"
        self._config = self._load_config()
        self.atlas_root = Path(
            self._config.get("atlas_root", str(self.home / "atlas"))
        )
        self.store = AtlasStore(self.atlas_root)
        self.wq = WriteQueue(self.store)
        self.router = Router(self.models_path)
        from helix.atlas.lint import Linter
        from helix.atlas.retriever import Retriever
        # Imported here to avoid a circular import (project -> app).
        from helix.explore import ExploreStore
        from helix.project import ProjectStore

        self.projects = ProjectStore(self)
        self.explore_store = ExploreStore(self.store.layout)
        self.retriever = Retriever(self.store)
        self.linter = Linter(self.store)
        # Continuous lint (§6.4): every successful write incrementally
        # lints the touched page. Best-effort — lint never breaks a
        # write; findings are stashed for `helix atlas lint` / doctor.
        self.wq.on_applied = self._lint_after_write
        self.last_lint = []

    def _lint_after_write(self, result) -> None:
        try:
            self.last_lint = self.linter.lint_page(result.handle)
        except Exception:  # noqa: BLE001 — lint must never break a write
            self.last_lint = []

    def workflow(self):
        """The Forge workflow engine. Default agent bodies are the
        zero-integration built-ins; ``$HELIX_AGENTS=fake`` is the
        offline/test hook (deterministic, no network, no LLM)."""
        from helix.forge.agents import BuiltinAgents, FakeAgents
        from helix.forge.workflow import WorkflowEngine

        name = os.environ.get("HELIX_AGENTS", "builtin")
        agents = FakeAgents() if name == "fake" else BuiltinAgents()
        return WorkflowEngine(self, agents)

    def explorer(self):
        """The Explore body. Default backend is the real arXiv search
        (§11.1 zero-integration); ``$HELIX_EXPLORE_BACKEND=fake`` is the
        offline/test hook (deterministic, never network)."""
        from helix.explore import Explorer, make_backend

        name = os.environ.get("HELIX_EXPLORE_BACKEND", "arxiv")
        return Explorer(self, backend=make_backend(name))

    # ---- config -----------------------------------------------------

    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {}

    def save_config(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._config, indent=2, sort_keys=True))
        tmp.replace(self.config_path)

    def config_get(self, key: str):
        return self._config.get(key)

    def config_set(self, key: str, value: str) -> None:
        self._config[key] = value
        self.save_config()

    @property
    def config(self) -> dict:
        return dict(self._config)

    @property
    def is_set_up(self) -> bool:
        """Setup is complete once the one routing decision is recorded."""
        return self.models_path.exists()

    # ---- per-project canonical stores (shared write lock) -----------

    def decision_log(self, project: str) -> DecisionLog:
        # DecisionLog grabs self.wq.lock internally (review fix #3).
        return DecisionLog(project, self.store.layout, self.wq)

    def snapshots(self, project: str) -> SnapshotStore:
        # The shared lock is what makes the keystone DAG race-free in
        # the real app (review fix #4 production wiring).
        return SnapshotStore(project, self.store.layout, lock=self.wq.lock)
