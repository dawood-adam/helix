# Guide 5 — Model routing & regulated/private work

**Goal:** control which model each role uses (per-role, per-project,
global, per-step), and run a regulated/PHI project with the privacy
degradation + PI co-sign attestation that make the decision log a
defensible audit trail (§13).

**Prerequisites:** install per [getting-started](../getting-started.md);
offline.

```bash
export HELIX_HOME=/tmp/g5 HELIX_EXPLORE_BACKEND=fake HELIX_AGENTS=fake
helix setup --model anthropic:claude-sonnet-4.6        # (output omitted)
```

## Part A — model & provider routing

```text
$ helix model list
  explore         anthropic:claude-sonnet-4.6   [default]
  critic-methods  anthropic:claude-sonnet-4.6   [default]
  planner         anthropic:claude-sonnet-4.6   [default]
  builder         anthropic:claude-sonnet-4.6   [default]
  ... (one row per role) ...

$ helix model set builder local:qwen2.5-coder:32b
builder → local:qwen2.5-coder:32b

$ helix model list | head -4
  explore         anthropic:claude-sonnet-4.6   [default]
  critic-methods  anthropic:claude-sonnet-4.6   [default]
  planner         anthropic:claude-sonnet-4.6   [default]
  builder         local:qwen2.5-coder:32b       [role]      ← layer that won

$ helix model use local:qwen2.5:32b
global default → local:qwen2.5:32b
```

`model list` shows the **resolved** model per role and *which config
layer won* (`[default]` → `[role]` → `[project]` → per-step `--model`).
`model set <role> <ref> [--project P]` sets a role (optionally
per-project); `model use <ref>` switches the global default (e.g. fully
offline). Per-step override: `helix explore "<q>" --model openai:gpt-5`
(one run, no config change). Unresolvable/invalid refs fail closed with
a clear error (never a silent fallback).

## Part B — regulated/PHI project (privacy + PI co-sign)

```text
$ helix init trial --private --pi "Dr Shin"
$ helix peek trial
catch-me-up: trial, since earlier today: init (...). Idle at 'notes'.
trial  ·  rung: notes  ·  privacy: strict
  privacy=strict — degraded roles (§9.9, visible): (configure a [privacy] model)

$ helix run trial                                 # then resolve gates:
$ helix trial --approve --why "clinically sound"  # (×N)

$ helix freeze trial
Error: cannot freeze trial: 5 high-stakes decision(s) await PI co-sign — `helix trial --cosign --as <pi>` (§13 attestation trail).

$ helix
... (badge/triage) ...
NEEDS YOU NOW (1)
  ▸ trial — 5 decision(s) await PI co-sign (§13)

$ helix trial --cosign --as "Dr Shin"
PI 'Dr Shin' co-signed 5 decision(s): trial#decision-2, trial#decision-3, trial#decision-4, trial#decision-5, trial#decision-6 (§13 attestation, logged + Snapshotted).

$ helix freeze trial
trial frozen → published.
```

## Expected output / notes

- **`--private` is a *defined degradation*, not a flag flip (§9.9).**
  `peek` surfaces the degraded roles so the quality trade-off is
  *visible, never silent*. Here it prints
  `(configure a [privacy] model)` because no local/ZDR `[privacy]`
  model is set — honest output, not an error. The directional write
  boundary (private content is never auto-folded into canonical) and
  no-auto-promotion apply throughout; pages carry a `private` banner.
- **`--pi` makes co-sign required (opt-in, §13/§9.3).** It is *not*
  forced on the solo non-regulated user (that paternalism is
  explicitly avoided). `helix freeze` is **blocked** with a clean,
  actionable message until every high-stakes human decision is
  countersigned; the pending co-sign is a real NEEDS-YOU queue item.
  `--cosign --as <pi>` records the attestation (logged + Snapshotted);
  freeze is then permitted.

## Common variations

- **Both knobs together:** `helix init study --private --pi "Dr Shin"`
  — strict routing *and* the attestation trail (the §13 compliance
  posture).
- **Fork redaction:** `helix fork <private-project>` produces a
  privacy-redacted bundle (the Loom/Prism + Atlas subgraph honour the
  boundary).
- **Per-project model:** `helix model set builder local:qwen … --project trial`
  routes just that project's Builder while others stay on the default.
