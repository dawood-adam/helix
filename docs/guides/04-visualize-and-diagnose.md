# Guide 4 — Visualize & diagnose a project

**Goal:** read a project's *shape* (Prism — anatomy) and *history*
(Loom — map), retrieve from the knowledge base (GraphRAG), run the
linter, and get one cross-layer health check.

**Prerequisites:** a run project (reuses Guide 1's
`HELIX_HOME=/tmp/g1`, `bowel-length`). Offline.

```bash
export HELIX_HOME=/tmp/g1
```

## Steps

`prism` (Strategy→Data→Code) → `loom` (map; `--export` for grayscale
SVG) → `doctor` (cross-layer) → `atlas search` (GraphRAG, token-budgeted)
→ `atlas lint` (full sweep).

## Runnable example (real output)

```text
$ helix prism bowel-length
Prism · bowel-length   (Strategy → Data → Code)
legend: (concept)=strategy  [module]=code  ((data))=store  {cluster}=grouping

■ Strategy — what it's for & the approach
  (concept) Q: bowel length
  (concept) methods: approach-1
    why: ok
  constraints: tier:published

■ Data — what feeds it & why
  ((data)) repro
    why: ⊕ add rationale to enrich this view (helix why / decision log)

■ Code — how it's built & why this structure
  {src} ⌁ first build will populate this
    why: ⊕ add rationale to enrich this view (helix why / decision log)

(doctor: rationale missing for Data, Code)

$ helix loom bowel-length --export /tmp/loom.svg
Loom SVG (grayscale) → /tmp/loom.svg
# /tmp/loom.svg starts: <svg xmlns="http://www.w3.org/2000/svg" width="1170" height="120" ...

$ helix doctor bowel-length
helix doctor — ISSUES (8 checks)
  ✓ atlas-index: 15 page(s) indexed, index loads
  ✓ atlas-wal: 52 write record(s)
  ✓ bowel-length: snapshot-integrity: all Snapshot content hashes verify
  ✓ bowel-length: snapshot-head: head snap:bowel-length@8 resolves
  ✓ bowel-length: decision-binding: every Snapshot decision_head exists in the log
  ✗ bowel-length: broken-refs: 5 broken link(s)
      fix: regenerate the source, or `helix atlas lint`
  ✗ bowel-length: prism-rationale: rationale missing for Data, Code
      fix: add reasoning at the relevant gate (helix why)
  ✓ forge: workflow checkpoint store present

$ helix atlas search "centerline tracing" --notes --show 1
5 pages · ~675 tok · graph
  [3] src:2026-4-centerline-tracing-study-4  (0.88, ~135 tok)
  [3] src:2026-8-centerline-tracing-study-8  (0.88, ~135 tok)
  ... (ranked, tier-3 = full body within the token budget) ...

--- src:2026-4-centerline-tracing-study-4  (tier 3) ---
... (page body, truncated to --show) ...

$ helix atlas lint
Atlas lint: 6 finding(s)
  broken_link (5):
    - proj:bowel-length-decision-log: unresolved [[fake]]
    ... (×5) ...
  ... other kinds ...
(contradiction lint needs the LLM critic — not faked here.)
```

## Expected output / notes

- **Prism is a pure projection** in fixed order Strategy→Data→Code.
  Rationale comes *only* from the decision log; where none exists it
  shows the honest FYI hint (`⊕ add rationale …`) and **never a blank
  slot** — and `doctor` flags exactly those slots.
- **Loom** TTY is glyph-authoritative (grayscale/`NO_COLOR` legible);
  `--export` writes a real grayscale SVG (publication supplement).
- **`doctor` is honest about the fake run.** The `broken-refs` /
  `atlas lint` `[[fake]]` findings are *correct*: the offline `fake`
  Scout uses a placeholder summary ref, so the generated decision-log
  narrative legitimately contains an unresolved `[[fake]]` link — this
  demonstrates lint/doctor actually catching something. With real
  agents those refs resolve. Generated pages are exempt from
  *write-time* hygiene rejection but are still *linted* (by design).
- **`atlas search`** is GraphRAG: BM25-anchored, hop-bounded, within a
  token budget; tier-3 = full body, lower tiers = summaries as the
  budget runs out. `scratch` is hidden unless `--notes` (§6.3).
- **Contradiction lint is not faked** — it needs the LLM critic and
  says so rather than emitting a keyword heuristic.

## Common variations

- `helix prism <p> --export out.svg` / `helix loom <p>` (TTY) — same
  projections, different surface; both are auto-emitted into
  `helix freeze` and `helix fork` bundles.
- `helix atlas search "<q>"` (no `--notes`) restricts to
  active/canonical/published; `--scope <project>` narrows it;
  `--budget N` changes the token budget.
- `helix doctor` (no project) checks every project + global stores.
