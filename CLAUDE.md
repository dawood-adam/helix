# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## The spec is the source of truth

`HELIX.md` is the complete, authoritative system specification. Code, comments, and tests cite it by section (e.g. `§6.4.1`, `§7.3`). When changing behavior, reconcile with `HELIX.md` first; if the code and spec disagree, that is a bug to surface, not a free choice. The implementation follows the spec's build order (`HELIX.md` Appendix A.1, steps 1–14) and that ordering explains why lower-numbered subsystems are deliberately dependency-light.

## Commands

No `uv`; a venv lives at `.venv`. `pyproject.toml` sets `pythonpath = ["src"]`, so tests/CLI run without installing.

- All tests: `.venv/bin/python -m pytest -q`
- One test: `.venv/bin/python -m pytest -q tests/test_workflow.py::test_full_human_path_records_decisions_and_snapshots`
- By keyword: `.venv/bin/python -m pytest -q -k "crossproc or privacy"`
- Run the CLI without installing: `PYTHONPATH=src .venv/bin/python -m helix.cli --home /tmp/h <args>` (installed entrypoint is `helix`).

There is no linter/formatter configured; pytest is the only gate. The suite is fully deterministic and must stay green and flake-free — concurrency/multiprocess/web tests are real, not mocked.

### Offline test/dev hooks (important)

The sandbox has no reliable network and no LLM/external services. Anything touching feeds, agents, or models must run offline:

- `HELIX_EXPLORE_BACKEND=fake` — deterministic offline literature backend (vs. real `arxiv`).
- `HELIX_AGENTS=fake` — deterministic offline agent bodies (vs. `builtin`).
- `HELIX_HOME=<dir>` — isolates all state (Atlas, checkpoints, config) for a run.

Test fixtures (`tests/conftest.py`: `helix_app`, `run`, `ready_run`) wire these automatically. When writing tests that exercise Explore/Watcher/the workflow, use the fakes — never depend on network or real models.

## Architecture (the big picture)

Two stateful layers, one user surface (`HELIX.md` §3). **Forge** = workflow runtime (LangGraph); **Atlas** = durable knowledge (markdown + git). `src/helix/app.py::Helix` is the **single wiring point** — it constructs every store and threads the shared write lock through. Construct `Helix` (or use the fixtures); do not instantiate stores ad hoc.

Load-bearing invariants that span multiple files — violating any of these is a serious regression:

- **One ordered writer, including across processes.** All Atlas writes go through `atlas/writequeue.py::WriteQueue`, serialized by `atlas/proclock.py::ProcessLock` (re-entrant `RLock` + `fcntl.flock` on `.helix/write.lock`). `DecisionLog`, `SnapshotStore`, and `ProjectStore` compound ops serialize on the *same* `wq.lock`. The cron Watcher runs as a separate process, so cross-process safety is required, not optional (`tests/test_crossproc.py`).
- **The decision log is the only canonical narrative source.** `decisionlog.py` holds structured JSON; the markdown narrative, Loom (`loom.py`), and Prism (`prism.py`) are *pure deterministic projections* — never a second source of truth. Generated pages carry a banner and are exempt from link-hygiene rejection so the projection invariant holds.
- **The Snapshot is the keystone.** `snapshot.py` binds decision head + code sha + Atlas page versions + data hashes + model routing. Every meaningful point (gates, branch ops, lifecycle changes) mints a complete Snapshot via the shared `project_atlas_binding` / `cas.project_data_hashes` helpers — both workflow and ProjectStore mints, so diff/checkout/repro are never hollow.
- **Fail-closed HITL.** `forge/router.py` gate/sanity routing pauses on any missing/malformed signal; absence is never the happy path. `forge/state.py` `ForgeState` is the LangGraph state schema; `forge/workflow.py` is orchestration only — all decisions are the pure step-8 rules.
- **Agent/integration seam pattern.** External work (Explore feeds, agent bodies, FutureHouse/Claude Code/etc.) sits behind a swappable seam with a real default, a deterministic offline fake, and honest fail-closed adapters (`upgrades.py`). Selecting an unconfigured upgrade errors with instructions.

## Conventions specific to this codebase

- **No fake success.** Never fabricate results when a dependency/service is absent — fail closed with an actionable message. Honest deferrals are labeled in-code (search `build step`, `not faked`, `§7.6`, `v1.5`) and must stay accurate; a deferral whose deadline passed is a bug (it has happened — review found one).
- **Trust but verify.** After any fix, prove it: a regression test must fail without the change (demonstrate it), and concurrency tests must not mask failures (no swallowed thread exceptions, no assertions that pass vacuously).
- Cite the relevant `HELIX.md §` in new code and tests, as the existing code does.
