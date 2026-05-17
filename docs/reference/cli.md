# Reference — `helix` CLI (`src/helix/cli.py`)

The CLI is the only end-user entry point. Console script: `helix`
(`pyproject.toml [project.scripts] helix = "helix.cli:main"`). Uninstalled:
`PYTHONPATH=src .venv/bin/python -m helix.cli …`.

**Global behavior**

- Group option `--home PATH` (default `$HELIX_HOME` or `~/.helix`) — sets where all state lives; applies to every subcommand: `helix --home /tmp/h <cmd>`.
- `helix` with **no subcommand** renders the queue (see `status`).
- `helix <project> …` — if the first token is not a known command it is dispatched to `act <project>` (`HelixGroup.resolve_command`).
- **Error convention:** recoverable errors raise `click.ClickException` → message on stderr, exit code 2. Bare `helix` before `helix setup` prints a setup hint (exit 0).
- **Offline/test env:** `HELIX_EXPLORE_BACKEND=fake` (offline Explore), `HELIX_AGENTS=fake` (offline workflow agents), `HELIX_HOME` (isolated state). Without setup most commands still run but model-dependent paths are inert.

Examples below assume `export HELIX_HOME=/tmp/h` and a completed `helix setup`.

---

## Setup & configuration

### `helix setup`
Zero-integration bootstrap (§11.1/§A.2). Writes `models.toml`, creates the Atlas dir + starter `ATLAS.md`, `git init`s the Atlas repo, prints the opt-in upgrade registry.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--model` | `provider:model` | prompt | The one decision, e.g. `anthropic:claude-sonnet-4.6`, `local:qwen2.5:32b`. Without it on a TTY, `click.prompt` asks (default `anthropic:claude-sonnet-4.6`). |
| `--force` | flag | off | Re-run even if already set up. |

**Behavior:** idempotent — if `models.toml` exists and not `--force`, prints "Already set up" and exits 0. Validates the ref via `ModelRef.parse` *before* writing anything.
**Errors:** invalid `--model` → `ClickException("… — nothing was changed.")` (fail-closed; no files written). Missing `git` → warning, continues (Atlas just isn't version-tracked).
**Example:** `helix setup --model anthropic:claude-sonnet-4.6`

### `helix config show`
Prints `home`, `atlas_root`, and every key in `config.json`. No args. Example: `helix config show`

### `helix config set KEY VALUE`
Writes `KEY=VALUE` into `config.json` (atomic). Recognized keys include `atlas_root`, `quiet_hours` (`on`/`off`). Example: `helix config set quiet_hours off`

### `helix model list`
Resolved model per role, showing which config layer won (§11.2).

| Option | Meaning |
|---|---|
| `--project NAME` | Resolve with that project's overrides. |
| `--privacy-strict` | Show the strict-mode (local/ZDR) substitution. |

**Errors:** unresolvable routing → `ClickException` (fail-closed). **Example:** `helix model list --project bowel-length`

### `helix model use REF`
Sets the global default model for every role. **Errors:** malformed `REF` → `ClickException`. **Example:** `helix model use local:qwen2.5:32b`

### `helix model set ROLE REF [--project NAME]`
Sets a per-role (optionally per-project) model. **Example:** `helix model set builder local:qwen2.5-coder:32b`

### `helix upgrades`
Lists opt-in upgrades + status (`built-in` / `configured` / `available`). None are on the critical path; selecting an unconfigured one fails closed with instructions. No args.

---

## Core verbs (§9.0)

### `helix` / `helix status [NAME]`
Renders the unified queue: optional >24h catch-me-up digest, the notification badge + triage summary (one batched digest, blocking-only "push"), then the three buckets (NEEDS YOU NOW / WORKING / FYI). Bare `helix`/`status` advances the idle cursor (view-state). With `NAME`, the queue **is filtered** to items whose title or suggested command concerns that project, the catch-me-up is scoped to it, the empty case prints `Nothing needs you on '<name>'.`, and the global idle cursor is **not** advanced by a scoped check. Unknown `NAME` → `ClickException`. **Example:** `helix` · `helix status bowel-length`

### `helix think [TOPIC]`
Ticket-free exploration (§9.10): writes a `scratch` page, **no** queue item/gate. Without `TOPIC`, prints usage. Duplicate topic → reuses the page (prints a note). **Example:** `helix think "synthetic CT for bowel length"`

### `helix explore QUERY`
One-shot literature scan → `scratch` source pages (§9.10); surfaces an FYI, never a gate.

| Option | Default | Meaning |
|---|---|---|
| `--scope` | — | Extra scope terms. |
| `--limit` | 12 | Max papers to ingest. |
| `--model` | — | One-shot model override (§11.2). |

**Errors:** backend failure (e.g. no network on the real `arxiv` backend) → `ClickException` with the cause; **no fabricated results**. **Example:** `HELIX_EXPLORE_BACKEND=fake helix explore "centerline tracing"`

### `helix init NAME`
Commits an idea to a project; mints `Snapshot@1` (history starts here, §9.10).

| Option | Default | Meaning |
|---|---|---|
| `--from-think` | off | Seed from all current `scratch` pages; consumes pending explore results. |
| `--tier` | `notes` | `notes` or `project` starting rung. |
| `--at PATH` | — | Intended location (§9.10), **recorded as project metadata only — tree relocation is not yet implemented**. |
| `--private` | off | Strict privacy (§9.9). |
| `--pi NAME` | — | Require this PI to co-sign high-stakes decisions (§13, opt-in). |

**Errors:** project already exists → `ClickException`. **Example:** `helix init bowel-length --from-think --tier project`

### `helix run NAME [--question TEXT]`
Starts (or reports) the LangGraph workflow (§5.2). If already interrupted at a gate or running, prints guidance instead of restarting. **Errors:** unknown project → `ClickException`. **Example:** `HELIX_AGENTS=fake helix run bowel-length`

### `helix NAME` / `helix act NAME` — act on the pending item (§9.0)
Resolves the pending gate, or co-signs.

| Option | Meaning |
|---|---|
| `--approve` | Take the recommended option. |
| `--option ID` | Resolve with a specific option id (e.g. `pick:approach-2`, `ship`). |
| `--why TEXT` | Reasoning logged into the decision rationale (required when the gate is teach-back-scoped). |
| `--cosign` | Record a PI countersignature for pending high-stakes decisions (§13). |
| `--as PI` | PI identity (required with `--cosign`). |

**Behavior:** with no resolving flag, renders the gate view (title, confidence, why-bullets, pause reasons, branch compare, options, resolve hints). With a flag, resumes the workflow and prints the soft-commit/undo note + next status.
**Errors:** unknown project → `ClickException` (with `helix init` hint); `--cosign` without `--as` → `ClickException`; teach-back-required gate without `--why` → `ClickException`.
**Example:** `helix bowel-length --approve --why "ODF survives crossings"`

### `helix why TARGET`
Prints the rendered decision + 3-bullet "why" (§14 artifact). `TARGET` is a project name (latest decision) or a decision id (`proj#decision-2`). **Errors:** unknown project / unknown decision → `ClickException`. **Example:** `helix why bowel-length`

### `helix peek [NAME]`
READ-ONLY status + catch-me-up; never advances the idle cursor, never creates tickets (§9.6/§9.7). No `NAME`: lists projects + per-project digests. With `NAME`: rung, privacy (+ degraded roles if strict), branch/head, last decision, parked lines. **Example:** `helix peek bowel-length`

### `helix undo NAME`
Rewinds to the prior checkpoint and logs the reversal as its own decision + Snapshot (§9.3). At project start → "nothing to undo". Output points to `helix checkout <name> <parent>` to inspect/verify the prior point; restoring historical Atlas page **bodies** is the §7.6 boundary (bindings resolve + verify, bodies are not re-materialised). **Example:** `helix undo bowel-length`

---

## Lifecycle ladder (§9.4)

### `helix promote NAME [--to RUNG]`
One rung up (`notes→project→published`); `--to` for a multi-rung jump. **Errors:** invalid move → `ClickException` (`LadderError`). **Example:** `helix promote bowel-length`

### `helix demote NAME [--to RUNG]`
One rung down; `--to` accepts ladder rungs or `archived`. **Example:** `helix demote bowel-length`

### `helix freeze NAME [--status published|paused]`
`published` (default) runs the real Maintainer: full Atlas lint, repro manifest, Methods/Limitations/rebuttals/BibTeX drafts, Loom+Prism supplement, git tag. `paused` parks the active line. **Errors:** high-stakes project with un-cosigned decisions → `ClickException` ("await PI co-sign", §13). **Example:** `helix freeze bowel-length`

### `helix archive NAME`
Archive (demote past the bottom rung); reversible via `promote`. **Example:** `helix archive bowel-length`

---

## Version control over Snapshots (§7.5)

All take `NAME` and error with `ClickException` on unknown project.

| Command | Args | Behavior |
|---|---|---|
| `helix history NAME` | — | The decision DAG (decision · action · snapshot · auto/human). |
| `helix diff NAME A B` | two refs (snap id, tag, or decision id) | Semantic binding diff + decisions added. Bad ref → `ClickException`. |
| `helix checkout NAME REF` | ref | Resolve + integrity-verify a Snapshot; prints the materialisation manifest. |
| `helix repro NAME REF` | ref | Reproduction manifest (integrity, model routing, note). |
| `helix bisect NAME` | — | First decision/snapshot that introduced a `plan_violation` regression, or "none". |
| `helix fork NAME [--to DIR]` | — | Self-contained bundle (decision log + Snapshots + Atlas subgraph + Loom + Prism). Default dir `./<name>-fork`. |

**Example:** `helix diff bowel-length bowel-length#decision-1 bowel-length#decision-3`

---

## Knowledge views & diagnostics

### `helix loom NAME [--export PATH]`
Project map (§7.7), Map mode. No `--export`: grayscale-legible TTY (status glyph authoritative). `--export`: writes grayscale SVG. **Example:** `helix loom bowel-length --export /tmp/loom.svg`

### `helix prism NAME [--export PATH]`
Project anatomy (§7.8): fixed Strategy→Data→Code. TTY or SVG (legend included). **Example:** `helix prism bowel-length`

### `helix atlas search QUERY`
GraphRAG retrieval within a token budget (§8.4).

| Option | Default | Meaning |
|---|---|---|
| `--scope NAME` | — | Restrict to a project. |
| `--budget N` | 10000 | Token budget. |
| `--notes` | off | Also search `scratch` (hidden by default, §6.3). |
| `--show N` | 3 | Print the top-N bodies/summaries. |

**Behavior:** distinguishes "no pages" vs "matches out of default scope (use `--notes`)". **Example:** `helix atlas search "centerline tracing" --notes`

### `helix atlas lint [--project NAME]`
Full-corpus lint sweep (§6.4): broken/duplicate/orphan/stale-provenance, grouped. (Contradiction lint is not faked.) **Example:** `helix atlas lint`

### `helix salvage NAME BRANCH [--reason TEXT]`
Keeps a dead line's learning → canonical (provenance-tagged), parks the branch (§6.4). For a privacy-strict project the page stays non-canonical (§9.9). **Errors:** unknown branch → `ClickException`. **Example:** `helix salvage bowel-length single-vector --reason "underperformed"`

### `helix doctor [NAME]`
One cross-layer diagnostic (§9.11): index/WAL, Snapshot integrity, decision↔Snapshot consistency, broken refs, Prism rationale slots. Prints `all clear`/`ISSUES` + per-check detail and fixes. **Example:** `helix doctor bowel-length`

---

## Watcher (async passive enrichment, off by default — §5.1)

| Command | Behavior |
|---|---|
| `helix watcher status` | enabled? schedule? watched topics, seen count, open proposals. |
| `helix watcher schedule [CRON]` | Enable + record cadence; prints the crontab line to install (Helix does not daemonize). |
| `helix watcher off` | Disable. |
| `helix watcher watch QUERY` | Add a watched topic. |
| `helix watcher run` | One pass (cron-wrap this): ingests new papers to `scratch` only, dedupes, emits FYI proposals. No-op (honest message) if disabled. |
| `helix watcher apply PROPOSAL_ID` | Fold a proposal into canonical (blocked if privacy-strict or project in-flight). Unknown id → `ClickException`. |

**Example:** `helix watcher schedule "0 7 * * *" && HELIX_EXPLORE_BACKEND=fake helix watcher run`

---

## Web view

### `helix serve [--host H] [--port P]`
Runs the zero-dep token-paired web gate view (§11). Defaults `127.0.0.1:8765`. Prints the pairing URL + token; renders an ASCII QR if the optional `qrcode` package is installed, else prints how to get one. Token auth is **advisory (loopback dev tool), not a security boundary**. Blocks until Ctrl-C. See `docs/reference/web.md` for routes. **Example:** `helix serve --port 8765`
