# Guide 2 — Git for research: history, diff, checkout, repro, bisect, fork

**Goal:** treat a project's reasoning like version control — inspect
the decision DAG, diff two points semantically, resolve/verify a
Snapshot, get a reproduction manifest, locate a regression, and export
a self-contained bundle.

**Prerequisites:** a project that has run through the workflow (do
[Guide 1](01-first-project.md) first; this guide reuses
`HELIX_HOME=/tmp/g1`, project `bowel-length`). Offline; no network/keys.

```bash
export HELIX_HOME=/tmp/g1        # the project from Guide 1
```

## Steps

`history` (the commit graph) → `diff A B` (semantic, not text) →
`checkout REF` (resolve + verify) → `repro REF` (reproduction
manifest) → `bisect` (find the regressing decision) → `fork` (export a
bundle). Refs are a snapshot id (`snap:p@3`), a tag, or a decision id
(`p#decision-3`, resolved to its enclosing Snapshot).

## Runnable example (real output)

```text
$ helix history bowel-length
  bowel-length#decision-1  init                  snap:bowel-length@1   [human]
  bowel-length#decision-2  approve               snap:bowel-length@2   [human]
  bowel-length#decision-3  pick:approach-1       snap:bowel-length@3   [human]
  bowel-length#decision-4  approve               snap:bowel-length@4   [human]
  bowel-length#decision-5  approve               snap:bowel-length@5   [human]
  bowel-length#decision-6  ship                  snap:bowel-length@6   [human]
  bowel-length#decision-7  freeze                snap:bowel-length@7   [human]
  bowel-length#decision-8  maintainer_freeze     —                     [auto]

$ helix diff bowel-length bowel-length#decision-1 bowel-length#decision-3
diff snap:bowel-length@1 → snap:bowel-length@3
  decision_head: {'from': 'bowel-length#decision-1', 'to': 'bowel-length#decision-3'}
  model_routing: {'builder': {'from': None, 'to': 'anthropic:claude-sonnet-4.6'}, ... }
  + decision bowel-length#decision-2: approve
  + decision bowel-length#decision-3: pick:approach-1

$ helix checkout bowel-length bowel-length#decision-3
  snapshot: snap:bowel-length@3
  branch: main
  decision_head: bowel-length#decision-3
  integrity_ok: True
  code_sha: None
  code_present: False
  atlas_pages: {'proj:bowel-length': 'v1', 'src:2026-1-centerline-tracing-study-1': 'v1', ... }
  data_hashes: {}
  env_lock: None
  model_routing: {'explore': 'anthropic:claude-sonnet-4.6', ... }
  materialisation_note: binding resolved + verified. Restoring historical Atlas page *bodies*
  needs the content-addressed page-version store (§7.6 — build step 14); current page
  versions and code sha are referenced above.

$ helix repro bowel-length snap:bowel-length@3
reproducible: True  (integrity True)
  models: {'explore': 'anthropic:claude-sonnet-4.6', ...}
  re-run with model_routing above for model-faithful reproduction (§11.2 / §7.3)

$ helix bisect bowel-length
no plan_violation regression in the decision log

$ helix fork bowel-length --to /tmp/bl-fork
forked → /tmp/bl-fork  (decision history + Snapshots + Atlas subgraph + Loom + Prism)
# /tmp/bl-fork contains:
#   README.md  decision-log.json  project.json  snapshots/
#   atlas-subgraph/  loom.svg  loom.txt  prism.svg  prism.txt
```

## Expected output / notes

- **`history` is the commit graph** — the decision DAG itself; the
  `[auto]`/`[human]` column is the §13 attestation signal. Auto-routed
  steps that coalesced show `—` for snapshot (resolved to the enclosing
  Snapshot on checkout).
- **`diff` is semantic, not textual** — it reports the structured
  binding delta (decision head, model routing, atlas page versions,
  data hashes) plus which decisions landed between the two points.
- **`checkout`/`repro` resolve and integrity-verify** the Snapshot and
  print exactly what would be materialised. **Honest boundary:**
  historical Atlas page *bodies* are not re-materialised (the §7.6
  content-addressed page-version store) — `materialisation_note` says
  so. `code_sha`/`data_hashes` are empty here because the offline
  `fake` Builder/Validator write no real code/results — these bind
  when the real (non-`fake`) Builder/Validator produce artifacts on
  disk (the offline guides use the fakes, so they stay empty).
- **`repro` on a gate Snapshot** (e.g. `@3`) carries `model_routing`;
  on a *lifecycle* Snapshot (e.g. the freeze `@7`) `models` is `{}`.
  Known limitation: workflow gate mints bind model routing; lifecycle
  (freeze/promote) mints currently do not (they *do* bind atlas page
  versions and data hashes). For a model-faithful reproduction, pick a
  gate Snapshot.
- **`bisect`** is deterministic: it finds the first decision whose
  Validator logged a `plan_violation`; "none" here because the clean
  fake run never violated the plan band.

## Common variations

- **Name/return to any point:** Snapshots are nameable
  (`SnapshotStore.name`); `diff`/`checkout`/`repro` accept the tag.
- **Bisect a real regression:** with the workflow's Validator detecting
  a metric outside the plan band, `helix bisect` reports
  `first bad: <decision> (<snapshot>)` and the reason.
- **Fork to share:** the bundle is self-contained (decision history +
  Snapshots + the referenced Atlas subgraph + Loom/Prism). A
  privacy-strict project's bundle is redacted (see Guide 5).
