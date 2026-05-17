# Guide 1 — From an idea to a finished project

**Goal:** take a research idea through the full Helix loop —
explore the literature, commit a project, drive it through the
human-in-the-loop workflow, and freeze it for publication.

**Prerequisites:** install per [getting-started](../getting-started.md).
Every command below runs **offline** (no network/keys) using the
documented fake hooks. Commands are shown as `helix …` (console
script); without installing, prefix
`PYTHONPATH=src .venv/bin/python -m helix.cli`.

```bash
export HELIX_HOME=/tmp/g1                 # isolated state
export HELIX_EXPLORE_BACKEND=fake         # offline literature backend
export HELIX_AGENTS=fake                  # offline deterministic agents
```

## Steps

1. **Set up** (one decision). 2. **Think** freely (ticket-free).
3. **Explore** the literature. 4. **Commit** a project from that
context. 5. Check the **queue**. 6. **Run** the workflow and **resolve
gates**. 7. Inspect **why**/**peek**. 8. **Freeze**.

## Runnable example (real output)

```text
$ helix setup --model anthropic:claude-sonnet-4.6
Ready. Atlas: /tmp/g1/atlas
       Models: anthropic:claude-sonnet-4.6  (change: helix model use ...)
Available upgrades (opt-in, off the critical path) — `helix upgrades`:
  [○ available] Explore body: built-in arXiv search  →  FutureHouse / Open Deep Research (...)
  ... (8 upgrade lines) ...
Next:  helix think "<your question>"

$ helix think "synthetic CT for bowel length"
Noted in Think (ticket-free): "synthetic CT for bowel length"
  scratch page: scratch:synthetic-ct-for-bowel-length
Nothing is blocked on you; this created no queue item.
Commit it when ready:  helix init <name> --from-think

$ helix explore "centerline tracing"
Explore done: "centerline tracing"  ·  model: anthropic:claude-sonnet-4.6
  12 papers → Notes (scratch)
  gaps: centerline, tracing, investigate
Ticket-free: no gate, no notification. It's in the queue as FYI.

$ helix init bowel-length --from-think --tier project
Committed 'bowel-length' at rung 'project' (seeded from Think: 13 pages, 1 explore result(s))
  history starts here — Snapshot snap:bowel-length@1
Next:  helix bowel-length    (or: helix peek bowel-length)

$ helix
🔔 badge: 0   (0 batched)
   quiet hours on — only the badge updates in real time; everything below is batched, nothing pinged

Nothing needs you yet.
  Your projects:
    · bowel-length  [project]   ·   helix peek bowel-length

$ helix run bowel-length

bowel-length: next decision —
Approve the scope?  (bowel-length)
  confidence: 0.85  ·  unsure: structural signal only (none); the LLM critic upgrade adds semantic judgement
  • Project committed at rung 'project', seeded from Think (13 refs).
  • Evidence: src:2026-2-centerline-tracing-study-2, ... (13 refs)
  paused because: autonomy=always_ask (you review every time)
  options:
    [approve] Approve scope ◀ recommended
    [redo_with_focus] Re-scan with a tighter focus
    [abandon] Abandon
Resolve:  helix bowel-length --approve   |   helix bowel-length --option <id>
          (recommended: approve)  --why optional (pick-not-type; logged if given)

$ helix bowel-length --approve --why "ODF survives crossings"
Recorded 'approve'. Soft-commit: ~20s — `helix undo bowel-length` reverts (logged).

bowel-length: next decision —
... (repeat `helix bowel-length --approve --why ok` for each gate) ...
bowel-length: workflow complete.

$ helix why bowel-length
## Decision 8 — Maintainer freeze
*2026-05-17, gate_lifecycle, auto-routed*  · *(generated from .decision-log.json — do not edit)*

Maintainer froze bowel-length: lint 6 finding(s), repro ok, drafts methods.md, limitations.md, rebuttals.md, references.bib.

Why (one-tap summary):
  • Maintainer froze bowel-length: lint 6 finding(s), repro ok, drafts ...

$ helix peek bowel-length
catch-me-up: bowel-length, since earlier today: ship (ok) → freeze (...) → maintainer_freeze (...). Frozen — published.
bowel-length  ·  rung: published  ·  privacy: normal
  branch: main   head: snap:bowel-length@7
  last decision: maintainer_freeze — Maintainer froze bowel-length: ...

$ helix freeze bowel-length
bowel-length frozen → published.
  Atlas lint: 6 finding(s) · repro: ok
  drafts (from the decision log): methods.md, limitations.md, rebuttals.md, references.bib
  supplement (Loom + Prism): /tmp/g1/atlas/projects/bowel-length/supplement
```

## Expected output / what just happened

- `setup` records the one model decision and prints the opt-in upgrade
  registry; nothing else is asked.
- `think`/`explore` write to **Notes (`scratch`)** only — no gates, no
  tickets. `init --from-think` seeds the project from that context and
  **consumes** the explore FYI (hence the queue's badge is `0`
  afterwards — that is correct, not a missing item).
- `run` starts the LangGraph workflow; with the default `always_ask`
  autonomy it **pauses at every gate** with a progressive-disclosure
  view (recommended option, confidence, why-bullets, pause reason).
- Resolving gates records each decision (with your `--why`) into the
  **canonical decision log** and mints a Snapshot; reaching the end
  runs the **Maintainer**, which freezes and emits the §13
  within-project drafts + the Loom/Prism supplement. Running
  `helix freeze` again is idempotent.

## Common variations

- **Skip the gates (trust the agents):** the workflow honours
  per-gate autonomy. A fully-auto run completes without prompts (used
  by the test suite via `autonomy=auto`).
- **Daily loop:** bare `helix` is the queue (badge + batched digest +
  three buckets). After >24h idle it leads with a per-project
  catch-me-up line. `helix peek <name>` is the read-only form (never
  advances the idle cursor, creates no tickets).
- **Lifecycle:** `helix promote/demote <name>` moves one rung
  (`notes→project→published`); `helix archive <name>` retires it.
  Every rung change is logged + Snapshotted and is reversible.
- **Mistake?** `helix undo <name>` rewinds to the prior checkpoint and
  logs the reversal as its own decision.
- **Real backends:** drop the `*_=fake` exports to use the real arXiv
  Explore backend (needs network); see Guide 5 for LLM model routing.
