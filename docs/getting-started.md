# Getting started

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | **≥ 3.12** (`pyproject.toml requires-python`); validated on **3.13.5** | Uses `tomllib` (3.11+) and modern typing. |
| OS | POSIX (macOS / Linux) | The cross-process write lock uses `fcntl.flock`. On non-POSIX it degrades to an in-process lock **with a `RuntimeWarning`** (concurrent `helix` processes are then not serialized — see Troubleshooting). |
| `git` | any (validated 2.50.0) | **Optional.** Used to version-track Atlas and tag on freeze; if absent, `helix setup` warns and continues. |
| Build/runtime deps | `pyyaml>=6.0`, `click>=8`, `langgraph>=1,<2`, `langgraph-checkpoint-sqlite>=2` | Installed automatically from `pyproject.toml`. There is **no lockfile** — `pyproject.toml` is the manifest. Validated versions: PyYAML 6.0.3, click 8.4.0, langgraph 1.2.0, langgraph-checkpoint-sqlite 3.1.0, pytest 9.0.3. |
| Network / API keys | **Not required for the default path** | Built-in workflow agents are deterministic; no LLM/API key is needed to install, run, or test. The default Explore backend hits arXiv (network); the offline `fake` backend needs nothing (see env vars). |

No `uv`/`poetry`/`pipenv` — plain `venv` + `pip` against `pyproject.toml`.

## Install

```bash
git clone <repo-url> helix && cd helix
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"     # editable + pytest
```

`-e ".[dev]"` installs the runtime deps **and** `pytest`, and puts the
`helix` console script on `.venv/bin`. For runtime only, use
`-e .` (no pytest). If you prefer not to install, every command also
works as `PYTHONPATH=src .venv/bin/python -m helix.cli …` (the test
suite is configured this way via `pythonpath = ["src"]`).

## Environment variables

Every variable the code actually reads:

| Variable | Read in | Default | Purpose / example |
|---|---|---|---|
| `HELIX_HOME` | `app.py` | `~/.helix` | Root of all state (config, `models.toml`, Atlas, `forge.sqlite`). Example: `HELIX_HOME=/tmp/helix-demo`. The CLI's `--home` overrides it. |
| `HELIX_AGENTS` | `app.py` | `builtin` | Workflow agent bodies. `fake` = deterministic offline agents (no network/LLM) — use for tests/demos. |
| `HELIX_EXPLORE_BACKEND` | `app.py`, `watcher.py` | `arxiv` | Literature backend. `fake` = deterministic offline; `futurehouse`/`opendeepresearch` = opt-in (fails closed unless configured). |
| `NO_COLOR` | `loom.py` | unset | If set, `helix loom` TTY emits no ANSI colour (the status glyph stays authoritative — Loom is colour-blind/grayscale legible). |
| `FUTUREHOUSE_API_KEY` | `upgrades.py` | unset | Presence marks the FutureHouse Explore upgrade as "configured" (§11.1). |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY` | `routing.py` (readiness) | unset | Read **only** when a provider that declares that `key_env` is selected and readiness is checked (e.g. `helix doctor`, or an LLM-backed role). **Not needed for the default deterministic path.** The set is whatever your `models.toml` providers declare — these four are the built-in provider defaults. |

## First run

`helix setup` takes exactly one decision. Use `--model` for a
non-interactive run (without it, on a TTY, it prompts):

```bash
export HELIX_HOME=/tmp/helix-demo
.venv/bin/helix setup --model anthropic:claude-sonnet-4.6
.venv/bin/helix think "synthetic CT for bowel length"
```

The model string is just **recorded** (routing config); no key is
needed until you opt into an LLM-backed role. To run a whole project
offline end-to-end:

```bash
export HELIX_EXPLORE_BACKEND=fake HELIX_AGENTS=fake
.venv/bin/helix explore "centerline tracing"
.venv/bin/helix init demo --from-think
.venv/bin/helix run demo                 # pauses at the first gate
.venv/bin/helix demo --approve --why ok  # resolve gates until complete
```

## Verify the install

```bash
.venv/bin/helix --help                   # CLI loads
.venv/bin/python -m pytest -q            # full suite must pass
HELIX_HOME=/tmp/helix-check .venv/bin/helix setup --model anthropic:claude-sonnet-4.6
HELIX_HOME=/tmp/helix-check .venv/bin/helix doctor   # cross-layer check
```

Success looks like: `helix --help` lists the commands; `pytest`
reports `233 passed`; `helix doctor` prints `all clear`.

## Validation report

The Install + Verify steps above were executed in a **fresh venv**
(`/tmp/helix-fresh`, separate from the dev `.venv`) on macOS / Python
3.13.5. Results:

| Step | Result |
|---|---|
| `python3 -m venv` + `pip install -e ".[dev]"` | ✅ resolved & installed pyyaml 6.0.3, click 8.4.0, langgraph 1.2.0, langgraph-checkpoint-sqlite 3.1.0, pytest 9.0.3; `helix` script created |
| `helix --help` | ✅ lists all commands |
| `python -m pytest -q` | ✅ `233 passed` |
| `helix setup --model …` (clean `HELIX_HOME`) | ✅ wrote `models.toml`, created Atlas + `ATLAS.md`, `git init`'d, printed the upgrade registry |
| `helix doctor` | ✅ `all clear` |
| Offline end-to-end (`think → init → run → resolve`) with `*_=fake` | ✅ workflow ran to completion offline |

**Fixes applied during validation:** none — the documented steps
worked as written in a clean environment. (See the in-band report in
the chat response for the exact captured output.)

## Troubleshooting

Only issues actually encountered or documented in the codebase:

- **`helix: command not found` / `ModuleNotFoundError: No module named 'helix'`** — the package isn't installed in the active environment. Run `pip install -e .` in the venv, or invoke as `PYTHONPATH=src .venv/bin/python -m helix.cli …`.
- **`could not reach arXiv …` from `helix explore`** — the default backend needs network and **fails closed (no fabricated results)**. Use `HELIX_EXPLORE_BACKEND=fake` for offline work, or configure the FutureHouse upgrade.
- **`RuntimeWarning: fcntl unavailable …`** — you're on a platform without `fcntl` (e.g. Windows). The Atlas write lock falls back to in-process only; concurrent `helix` processes (e.g. a cron Watcher alongside an interactive session) are **not** serialized. POSIX is required for the cross-process guarantee.
- **`(note: git not available — Atlas is not version-tracked yet …)`** during `helix setup` — `git` isn't on `PATH`. Helix still works; install `git` and run `git init` in the Atlas dir to get version tracking + freeze tags.
- **`Helix isn't set up yet. Run: helix setup`** — you ran a command before `helix setup`; run setup first (this is expected, not an error).
