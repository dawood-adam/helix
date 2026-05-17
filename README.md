# Helix

**Git for research projects, with a second brain underneath.** Helix is
a two-layer research co-pilot for solo researchers: **Forge** (a
LangGraph workflow runtime that drives a project from idea to
publication with human-in-the-loop gates) over **Atlas** (a durable,
git-tracked knowledge layer with a canonical, append-only decision
log). It runs entirely locally with no required external services — the
default path needs one model decision and no API key — and is honest by
construction: where a capability isn't built it fails closed with
instructions rather than faking a result.

## Key features

- **Project-level version control** — Snapshots + branches: `diff`,
  `history`, `checkout`, `repro`, `bisect`, `fork` over the decision
  DAG (not just code).
- **HITL workflow** with fail-closed gates, tier-scoped teach-back, and
  trust telemetry that calibrates autonomy from evidence.
- **The decision log is the canonical artifact** — the narrative, the
  Loom (project map) and Prism (project anatomy) are pure
  deterministic projections of it; no second source of truth.
- **Compounding knowledge** — GraphRAG retrieval, continuous lint, the
  Watcher (off by default), and salvage that keeps a dead end's
  learning.
- **Within-project payoff** — auto-drafted Methods/Limitations/reviewer
  rebuttals + a reproduction manifest at freeze.
- **Regulated-ready** — defined privacy degradation and opt-in PI
  co-sign attestation (§9.9, §13).
- **Zero-integration default**; every heavy integration
  (FutureHouse, Claude Code, LangSmith, Postgres, …) is an opt-in
  upgrade off the critical path.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"
export HELIX_HOME=/tmp/helix-demo HELIX_EXPLORE_BACKEND=fake HELIX_AGENTS=fake
.venv/bin/helix setup --model anthropic:claude-sonnet-4.6
.venv/bin/helix explore "centerline tracing" && .venv/bin/helix init demo --from-think
.venv/bin/helix run demo            # then: helix demo --approve --why ok  (per gate)
```

(The `*_=fake` hooks run everything offline with no network/keys.
Requires Python ≥3.12 and a POSIX OS — see getting-started.)

## Documentation

- **[HELIX.md](HELIX.md)** — the authoritative system specification
  (the single source of truth; all code cites it by `§`).
- **[docs/getting-started.md](docs/getting-started.md)** — prerequisites,
  install, environment variables, verification (validated in a clean
  shell).
- **[docs/guides/](docs/guides/)** — task-oriented tutorials with
  runnable, executed examples (first project, version control,
  branches & salvage, visualize & diagnose, models & privacy, watcher
  & web).
- **[docs/architecture.md](docs/architecture.md)** — the as-built
  component map, runtime boundaries, data flows, and open questions.
- **[docs/reference/](docs/reference/)** — the public surface: the
  [CLI](docs/reference/cli.md), the [`Helix` facade](docs/reference/app.md),
  the [web routes](docs/reference/web.md).
- **[CONTRIBUTING.md](CONTRIBUTING.md)** / **[CLAUDE.md](CLAUDE.md)** —
  dev workflow and the project's working discipline.

## Status

The full spec (build order 1–14) is implemented; the load-bearing
invariants (single ordered writer incl. cross-process, fail-closed
HITL, decision-log-as-source-of-truth, pure projections,
no-fake-success) hold and are covered by the test suite. Remaining
deferrals are the genuinely external integrations — and those fail
closed with instructions, never pretend.
