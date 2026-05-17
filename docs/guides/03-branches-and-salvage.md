# Guide 3 — Parallel research lines & salvaging dead ends

**Goal:** keep an alternative bet as a real branch, park it when it
doesn't pan out, see Helix flag the abandoned line, and **salvage** it
so the learning survives even though the path didn't.

**Honest scope note.** `HELIX.md §9.7` lists `helix branch/park/resume`
as verbs, but **those CLI commands are not yet implemented** — branches
are a `SnapshotStore` API operation today, surfaced through the
gate-compare view, the Loom map, the queue FYI, and the `helix salvage`
command. This guide uses the real API for branch creation and real CLI
for everything else; it does not invent a `helix branch` command.

**Prerequisites:** install per [getting-started](../getting-started.md);
offline.

```bash
export HELIX_HOME=/tmp/g3 HELIX_EXPLORE_BACKEND=fake HELIX_AGENTS=fake
```

## Steps

1. Create + run a project. 2. Fork a parallel line (API). 3. Park it
(a bet you stepped away from). 4. See Loom + the queue flag it as
*abandoned without salvage*. 5. `helix salvage` it — durable claims go
to canonical (provenance-tagged), the branch is parked-but-resumable,
and the death reason is logged.

## Runnable example (real output)

```text
$ helix setup --model anthropic:claude-sonnet-4.6      # (output omitted)
$ helix init odf --tier project
$ helix run odf                                        # then resolve gates:
$ for i in 1..7; do helix odf --approve --why ok; done # → workflow complete

# Fork a parallel line, then park it (no `helix branch` verb yet):
$ python - <<'PY'
from helix.app import Helix
s = Helix().snapshots("odf")
s.fork("single-vector", decision_head=None)
s.park("single-vector", decision_head=None)
PY
branches: ['main', 'single-vector'] parked: ['single-vector']

$ helix loom odf
Loom · odf · 8 snapshot(s)
legend: ● active  ◦ parked  ⊘ salvaged  ✓ published   (· fork  * since last view)

main  ▸ phase: lifecycle
  ✓*1:init ─ ✓*2:approve ─ ✓*3:pick:approach-1 ─ ✓*4:approve ─ ✓*5:approve ─ ✓*6:ship ─ ✓*7:freeze

single-vector [parked]  ▸ phase: —
  ◦*8:fork from main ─ ◦*9:parked

⚠ branch 'single-vector' abandoned without salvage — `helix salvage single-vector` to capture the learning

$ helix
... (badge/triage lines) ...
FYI (1)
  · odf/single-vector — branch abandoned without salvage
      → helix salvage odf single-vector

$ helix salvage odf single-vector --reason "underperformed on the new metric"
salvaged 'single-vector': 8 durable claim(s) → concept:salvaged-odf-single-vector (canonical, provenance-tagged); branch parked + resumable.

$ helix history odf | tail -3
  odf#decision-7           freeze                snap:odf@7            [human]
  odf#decision-8           maintainer_freeze     —                     [auto]
  odf#decision-9           salvage               snap:odf@10           [human]
```

## Expected output / notes

- **The Loom glyph is authoritative** (status-only, grayscale/`NO_COLOR`
  legible): `✓` published · `◦` parked · `⊘` salvaged · `●` active.
  `main` is always the top lane; forked lines hang below.
- **The abandoned-without-salvage signal fires for a *parked* line,
  not a freshly-forked one.** A fork you keep working is just another
  active lane; only a *parked* line that was never salvaged is flagged
  (Loom `⚠` line + a single batched FYI with the exact `helix salvage`
  command).
- **`salvage` keeps the learning, not the path:** it writes a
  `canonical` concept page whose claims are provenance-tagged
  (`^dec:`/`^src:`), parks the branch (still resumable), and logs the
  death reason as its own decision (`decision-9 salvage`). Re-running
  it is idempotent.

## Common variations

- **Privacy-strict project:** `salvage` keeps the page **non-canonical
  + privately bannered** (the learning is not auto-folded out of the
  privacy boundary, §9.9). See [Guide 5](05-models-and-privacy.md).
- **Compare lines at a gate:** when >1 research line exists the
  gate-view carries a `compare` block (side-by-side branch + head +
  last rationale) — visible in `helix <project>` while a gate is
  pending.
- **Resume a parked line:** `SnapshotStore.resume(branch)` brings it
  back as the active line (programmatic today; the parked Snapshot is
  retained so nothing is lost).
