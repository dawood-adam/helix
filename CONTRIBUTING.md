# Contributing

Read [`CLAUDE.md`](CLAUDE.md) first — it states the load-bearing
invariants and the working discipline this project holds itself to.
`HELIX.md` is the authoritative spec; code cites it by section (`§`).

## Dev environment (delta from getting-started)

Follow [docs/getting-started.md](docs/getting-started.md) to create
`.venv` and `pip install -e ".[dev]"` (the `[dev]` extra adds
`pytest`). That is the whole dev setup — there is no separate
toolchain. The test suite is configured with `pythonpath = ["src"]`,
so tests run without an editable install if you prefer.

## Running tests

```bash
.venv/bin/python -m pytest -q                       # full suite
.venv/bin/python -m pytest -q tests/test_vc.py::test_history_is_the_commit_graph   # one test
.venv/bin/python -m pytest -q -k "crossproc or privacy"                            # by keyword
```

- The suite is the **only** enforced gate (see Linting). It must stay
  **green and deterministic** — re-run a few times when touching
  anything concurrent.
- Concurrency / multiprocess (`test_crossproc.py`) / web tests are
  **real**, not mocked. Offline-by-design: anything touching
  feeds/agents/models uses the `*_=fake` hooks
  (`HELIX_EXPLORE_BACKEND=fake`, `HELIX_AGENTS=fake`); fixtures wire
  these (`tests/conftest.py`: `helix_app`, `run`, `ready_run`). Do not
  add tests that depend on network or real models.

## Linting & code style

**No linter or formatter is configured** — `pyproject.toml` declares
only `[tool.pytest.ini_options]`; pytest is the sole automated gate.
The following are *observed conventions* in the codebase, **not**
tool-enforced — match them for consistency:

- `from __future__ import annotations` at the top of every module;
- lines wrapped at ~79 columns;
- a module docstring citing the relevant `HELIX.md §`;
- intentional broad excepts are narrow-scoped and marked
  `# noqa: BLE001` with a one-line reason;
- no leading-underscore symbols in the public surface
  (see [docs/reference/](docs/reference/)).

## The discipline (enforced by review, not tooling)

These are the project's non-negotiables (expanded in `CLAUDE.md`):

1. **No fake success.** Never fabricate a result when a dependency or
   service is absent — fail closed with an actionable message. Honest
   deferrals are labelled in-code (`build step …`, `not faked`, `v1.5`,
   `§7.6`) and must stay accurate; a deferral whose premise has shipped
   is a bug.
2. **Trust but verify.** Prove every fix: add a regression test and
   demonstrate it *fails without the change*. Concurrency tests must
   fail loudly — no swallowed thread exceptions, no assertions that
   pass vacuously (masking tests have bitten this repo before).
3. **Spec is normative.** If code and `HELIX.md` disagree, surface it
   (flag as an open question); don't silently rewrite docs/docstrings
   to paper over a spec gap. Cite `§` in new code and tests.
4. **One ordered writer.** All Atlas writes go through `WriteQueue`;
   `DecisionLog`/`SnapshotStore`/`ProjectStore` share the process-
   global `ProcessLock`. Don't add a write path that bypasses it.

## Branching / PR conventions

Not yet codified — at the time of writing the repository has **no
commit history, remotes, CI, or pre-commit config** to derive
conventions from. Until a maintainer establishes them, the sensible
default: short-lived feature branches off `master`, one logical change
per commit, the full suite green (and re-run for flakes on concurrent
changes) before merge. This section should be updated once real
conventions exist — it is intentionally not invented here.
