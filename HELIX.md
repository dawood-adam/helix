# HELIX

**Research Co-Pilot + Knowledge Atlas — Complete System Specification**
*Current state as of May 2026*
*Rev. 2 — design-review fixes integrated: single-source-of-truth decision log, Atlas write model, stable page IDs, hard-rule HITL triggers, GraphRAG cold-start/hub handling, the unified queue UX, and a zero-integration default mode.*
*Rev. 3 — value/usability/version-control fixes: the **Snapshot** composite-commit object + first-class research **branches** (Helix is now Git-for-projects, not only Actions-for-projects), within-project value (auto methods/rebuttal), trust telemetry → autonomy suggestions, anti-knowledge-debt teach-back, the Salvage operation, the non-queue Think surface, attestation/compliance framing, and artifact-class storage layering.*
*Rev. 4 — feature additions: per-role/global **model & provider routing** (API-key or local models like Qwen, switchable per step or globally), the **Think → `helix init`** hand-off (start a project at a tier of your choosing), and an intuitive **lifecycle-ladder** CLI (`promote`/`demote`/`park`/`resume`/`peek`/`why`).*
*Rev. 5 — **Loom**: the standard visual projection of the Snapshot DAG (the project map). Optimised over the rev-4 proposal — full enumerated encoding contract with mandatory grayscale/colorblind-redundant status, the "since last view" cursor defined as pure view-state, live-resolved chip labels, Compare decoupled from the v1 branch-compare gate, and export/fork-time privacy redaction.*
*Rev. 6 — **Prism**: the standard one-page project *anatomy* (strategy → data → code), complementary to Loom's history. Optimised over the proposal — the pixel grid is replaced by a semantic layout contract, every rationale is derived from the decision log (no new authored source of truth, no rationale rot), and privacy redaction extends to export/fork time.*
*Rev. 7 — **friction & accuracy pass** (goal: a tool used with minimal friction, intuitively): a **core-verb / advanced split** so the everyday surface is the queue + ~7 verbs (§9.0); Loom/Prism **demoted from mandatory daily outputs to zero-config artifacts auto-emitted only when needed** (freeze/fork/re-entry), with their exhaustive encoding tables moved to the tracker (§7.7–7.8); the **missing first-run / 15-minute contract written** (Appendix A.2, previously a dangling reference); **derived files made non-clobbering** against human Obsidian edits (§7.2, §6.4.1); **teach-back made tier-scoped and pick-not-type by default** so friction is proportionate and escapable (§9.3); **auto-routed steps coalesced** so the Snapshot DAG matches real decisions instead of needing a fold crutch (§7.3); the headline **tagline reconciled to "Git for research"** to match the §13 #1 moat (§1, §13, §14); the privacy read-boundary explanation **de-mystified** (§9.9); and **§12 corrected** — no code exists yet.*

---

## 1. What this is, in one paragraph

**Helix** is a unified, two-layer system for solo biomedical/computational researchers. **Forge** is the workflow runtime — a LangGraph-orchestrated network of AI agents that take a research project from idea to publication, with the human approving (or auto-approving) at every gate. **Atlas** is the persistent knowledge layer — an LLM-maintained personal wiki that compiles synthesis from every paper read, decision made, and project completed, and stays useful across years and projects. The two layers are complementary: **Forge handles runtime workflow logic; Atlas handles durable content.** The decision log lives in both forms and bridges them.

**Tagline:** *"Git for research projects, with a second brain underneath."*

(The agent pipeline of §5 is the *Actions* half — how the project moves forward; Snapshots + branches, §7.3–7.4, are the *Git* half — versioning the whole project. Project-level version control is the §13 #1 moat, so the headline leads with it. Earlier revisions led with "GitHub Actions for research", which named the runtime, not the moat — §7.3–7.4 already argued the shift; §1/§13/§14 now say it consistently.)

---

## 2. Naming reference

| Component | Name | What it is |
|---|---|---|
| Whole system | **Helix** | The two-stranded architecture (state + knowledge) wrapped in one user surface |
| Workflow runtime | **Forge** | Where projects are built and shaped through agent-driven phases |
| Knowledge layer | **Atlas** | The personal research wiki — mapped, growing, navigable |
| Schema doc inside Atlas | **ATLAS.md** | The contract telling agents how to maintain Atlas |
| CLI binary | **`helix`** | Single command surface for everything |

Etymology: *Helix* = biomedical resonance + dual-strand architecture. *Forge* = active building, shaping under heat. *Atlas* = navigable map of accumulated knowledge.

---

## 3. The two-layer architecture

Helix has **two stateful layers** with distinct purposes and persistence models. Both matter.

| Layer | Role | What it holds | Persistence | Access pattern |
|---|---|---|---|---|
| **Forge state** | Working memory of an active workflow | Current node, autonomy modes, sanity flags, candidate approaches under deliberation, pointers into Atlas, runtime metrics | LangGraph checkpointer (SQLite local, Postgres production) | Read/written by routing functions on every node transition |
| **Atlas** | Long-term memory of all your research | Source pages, concept pages, entity pages, methods pages, project narratives, decision-log narrative, raw PDFs | Markdown files in a git repo | Read/written by humans and agents for substantive content |

Mental model: **Atlas = disk, Forge state = RAM.** Or: Atlas = git repo, Forge state = working tree + current branch.

### Why two layers, not one

They have different access patterns:
- Forge state is structured JSON, queryable in code, fast.
- Atlas is markdown — readable, navigable, linkable.

All-in-state → unreadable. All-in-Atlas → slow routing, agents can't do logic on it. Two layers = right tool for each job.

---

## 4. What lives where (precise breakdown)

### 4.1 Forge state only (runtime)

- `project_name`, `research_question`, `domain_context`
- Current graph position (checkpointer-managed)
- `autonomy` dict — per-gate modes
- `sanity_check_flags` — drives auto-routing
- `next_action` — routing decision
- `candidate_approaches` — working list under deliberation (each promotable to a durable **branch**, §7.4)
- `snapshot_head`, `branch`, `branches` — version-control pointers (§7.3–7.4)
- `gate_agreement` — trust telemetry that drives autonomy suggestions (§5.6)
- `token_budget_remaining`, `cost_so_far`
- `atlas_handle` — connection info (path to Atlas root)
- `project_tier` — `scratch | active | published | archived`
- `privacy_mode` — `normal | strict`

### 4.2 Atlas only (durable knowledge)

- Source pages (one per paper, with summary + key claims + your notes)
- Concept pages, entity pages (people, datasets, tools), methods pages
- Project narratives — `overview.md`, `hypothesis-evolution.md`, `validation-cascade.md`
- `decision-log-narrative.md` (human-readable)
- `raw/` folder of PDFs and original sources

### 4.3 Both, intentionally — each in its native form

- **Decision log** — **canonical** structured JSON in `projects/<name>/.decision-log.json`, with explicit `rationale` and `evidence` fields. The human-readable `projects/<name>/decision-log-narrative.md` is a **deterministic render of that JSON**, regenerated on every write. There is no dual-write and no "keep in sync" step — the narrative is a projection, never a second source of truth (see §7).
- **Project plan** — structured fields in state; prose explanation in `projects/<name>/plan.md`.
- **Repro manifest** — structured in state at freeze; readable doc in `projects/<name>/repro.md`.
- **Critiques** — state holds pointer + 1-line summary; Atlas holds full text in `projects/<name>/critiques/`.
- **Snapshot** — the composite commit that *binds* both layers plus code and data into one reproducible point. It lives in neither layer alone: it is a small content-addressed object referencing a code git sha, Atlas page versions (by id), the decision-log head, and data/artifact hashes (§7.3). This is what makes Helix version control for the *whole project*, not just the code.

---

## 5. Forge — the workflow runtime

### 5.1 The agent roster (7 nodes + 1 async)

| # | Agent | When it runs | Reads from Atlas | Writes |
|---|---|---|---|---|
| 1 | **Scout** | Front door or in-workflow | Existing concept pages on topic; gaps in current coverage | New source summaries; updates to concept/entity pages; `candidate_approaches` in state |
| 2 | **Critic-Methods** | After Scout | Concept pages on candidate approaches; "known failure modes" sections | Critique page in Atlas; refined `candidate_approaches` in state |
| 3 | **Planner** | After methods chosen | Methods pages; prior projects' validation cascades | `project_plan` in state + `plan.md` in Atlas |
| 4 | **Builder** | After plan approved | Methods pages with known implementations | Code artifacts (to git, with `git_sha` pointer in state) |
| 5 | **Validator** | After build approved | Benchmark expectations from concept/source pages | `results/run-{date}.md` in Atlas; `experiment_results` + `sanity_check_flags` in state |
| 6 | **Critic-Results** | After validation | Competing-method baselines from source pages | "Weakness analysis" page in Atlas |
| 7 | **Maintainer** | At project freeze | Whole Atlas (for lint) | Repro manifest; freezes project page; runs promotions; updates index |
| — | **Watcher** *(async)* | On cron schedule | Nothing | New source summaries; alerts about scooping/methods updates |

**Note:** Critic-Methods and Critic-Results are two distinct uses of a critique pattern at different phases — pre-build (cheap kill of bad ideas) and post-results (devil's advocate before "ship"). Different prompts, different objectives. The "Critic runs twice" framing collapses them; the truth is they are separate nodes.

### 5.2 The flow with gates and auto-routing

```
START
  ↓
SCOUT
  ↓
[gate_scope]
  ├─approve──→ CRITIC-METHODS
  ├─redo_with_focus──→ SCOUT (loop)
  └─abandon──→ END
  ↓
CRITIC-METHODS
  ↓
[gate_methods]
  ├─pick:<id>──→ PLANNER
  ├─revise──→ CRITIC-METHODS
  └─back_to_scout──→ SCOUT
  ↓
PLANNER
  ↓
[gate_plan]
  ├─approve/trim/expand──→ BUILDER
  └─back_to_methods──→ CRITIC-METHODS
  ↓
BUILDER
  ↓
[gate_build]
  ├─approve──→ VALIDATOR
  ├─fix:<note>──→ BUILDER
  └─back_to_planner──→ PLANNER
  ↓
VALIDATOR
  ↓
(check sanity_check_flags — deterministic detectors drive routing)
  ├─plan_violation──→ PLANNER (auto, no gate)
  ├─leakage_detected──→ BUILDER (auto, no gate)
  ├─drift_severe──→ one-tap human confirm ──→ SCOUT
  ├─missing/ambiguous──→ gate_results (fail-closed pause)
  └─clean──→ CRITIC-RESULTS
  ↓
CRITIC-RESULTS
  ↓
[gate_results]
  ├─ship──→ MAINTAINER
  ├─rebuild──→ BUILDER
  ├─replan──→ PLANNER
  ├─reread_lit──→ SCOUT
  └─abandon──→ END
  ↓
MAINTAINER
  ↓
END

(parallel, on cron: WATCHER → writes to Atlas, surfaces alerts via notification)
```

**Five explicit human gates:** `gate_scope`, `gate_methods`, `gate_plan`, `gate_build`, `gate_results`. The transition between Validator and Critic-Results is intentionally gate-free — Validator's structured flags drive automatic loop-back when conditions warrant.

### 5.3 HITL autonomy modes per gate

Each gate has three modes, set at project init and adjustable mid-project via state:

| Mode | Behavior |
|---|---|
| `always_ask` | Pause every time; you decide. Default. |
| `ask_if_concerning` | Auto-approve only if **every hard-rule trigger is clear**; pause otherwise |
| `auto` | Only pause on hard violations (the hard-rule triggers below) |

Mix freely — e.g., keep `gate_build` at `always_ask` (you review code) while letting `gate_plan` run `auto` once you trust the Planner.

**Pause triggers are hard rules, not agent self-assessment.** `ask_if_concerning` and `auto` never rely on a critic deciding whether its own output is "concerning enough" — that fails silent. A gate auto-approves only when *all* of these objective, non-LLM conditions are clear:

- no `sanity_check_flags` set by the Validator's deterministic flag detectors
- no critique with a structured `severity: blocking` field (severity is a typed enum the critic must emit, validated by the router — not free prose)
- the relevant token/cost budget is within allocation (see §5.5)
- no contradiction newly flagged against a `canonical` page touched this step

**Fail-closed.** If any required field is missing, malformed, or absent (e.g. `sanity_check_flags` not written), the router treats it as *not clear* and pauses for a human. Absence is never the happy path on a safety-relevant branch.

### 5.4 Auto-routing on sanity flags

Validator outputs structured flags. The router reads them and skips the human gate when appropriate:

| Flag | Auto-route target | Logic |
|---|---|---|
| `plan_violation` | Planner (auto) | Deterministic: actual metric outside plan's target band |
| `leakage_detected` | Builder (auto) | Deterministic: pipeline integrity check failed (e.g., train/test overlap) |
| `drift_severe` | **Scout, but via a human gate** | This signal is a judgement, not a mechanical check; re-reading the literature is the most expensive loop, so it always pauses for a one-tap confirm rather than auto-routing silently |
| (none / missing) | **gate_results (pause)** | Fail-closed: absence of flags is *not* treated as "clean"; the human is asked |

Only `plan_violation` and `leakage_detected` auto-route without a human (both are deterministic detector outputs). `drift_severe` and any missing/ambiguous flag set pause for a one-tap human confirm. Every auto-route is recorded once, in the canonical `.decision-log.json`; the Atlas narrative is regenerated from it (never written separately).

### 5.5 Forge state schema

```python
class ForgeState(TypedDict, total=False):
    # Identity
    project_name: str
    research_question: str
    domain_context: str
    project_tier: Literal["scratch", "active", "published", "archived"]
    privacy_mode: Literal["normal", "strict"]
    privacy_degraded: List[str]          # agents downgraded to local models under strict

    # Model/provider routing — resolved per role; the most specific wins:
    # global default < role default < project < per-step override (§11.2).
    # Values are "provider:model" e.g. "anthropic:claude-sonnet-4.6",
    # "local:qwen2.5-coder:32b". privacy=strict forces local/ZDR.
    model_routing: Dict[str, str]        # role -> "provider:model" (resolved)
    model_overrides: Dict[str, str]      # one-shot per-step overrides

    # Atlas wiring (STABLE ids, never paths — paths break on promotion)
    atlas_handle: str                    # path to Atlas root (the only path; resolved once)
    scout_summary_ref: Optional[str]     # page id
    prior_art_refs: List[str]            # page ids
    methods_critique_ref: Optional[str]  # page id
    validation_critique_ref: Optional[str]  # page id

    # Hypotheses kept alive in parallel (each promotable to a branch, §7.4)
    candidate_approaches: List[Dict[str, Any]]
    chosen_approach_id: Optional[str]

    # Project version control (§7.3–7.6)
    snapshot_head: str                   # id of current Snapshot (composite commit)
    branch: str                          # active research line; "main" by default
    branches: Dict[str, str]             # branch -> snapshot id (parked lines are resumable)

    # Plan (structured here, prose in Atlas)
    project_plan: Dict[str, Any]         # phases, compute_budget, target_metrics, validation_cascade

    # Builder (artifacts in git, pointer here)
    code_artifacts: List[Dict[str, str]] # [{path, purpose, git_sha}]

    # Data pipeline — STRUCTURAL pointers only ({dataset_id, label}).
    # The *why* for each stage is a data-choice entry in decision_log,
    # never a second authored copy here (Prism, §7.8).
    data_pipeline: List[Dict[str, str]]

    # Validator
    experiment_results: List[Dict[str, Any]]
    sanity_check_flags: List[str]

    # Maintainer
    repro_manifest: Dict[str, Any]

    # Watcher (append-only)
    new_papers_alerts: Annotated[List[Dict[str, Any]], operator.add]

    # Decision log — CANONICAL structured form. Each entry carries
    # `rationale` + `evidence` (page ids) so the Atlas narrative can be
    # regenerated deterministically. No dual-write (see §7).
    decision_log: Annotated[List[Dict[str, Any]], operator.add]

    # Routing + control
    next_action: str
    autonomy: Dict[str, str]             # {"scope":"always_ask", "build":"always_ask", ...}

    # Trust telemetry — per-gate recent "approved unchanged?" history.
    # Drives data-driven autonomy suggestions and auto-demotion (§5.6).
    gate_agreement: Dict[str, List[bool]]

    # Observability + ENFORCED budget. A node that would exceed its
    # allocation halts and raises gate_budget for a human decision —
    # the budget is enforced, not merely displayed.
    token_budget_remaining: int
    cost_so_far: float
    budget_hard_stop: bool               # set by any node that hit its cap
```

### 5.6 Trust telemetry → data-driven autonomy

Autonomy modes (§5.3) are inert if the user has no basis for deciding when to trust an agent: they either over-trust (`auto`, get burned) or never-trust (`always_ask` forever, no autonomy value). Helix already logs every decision, so it can close the loop with **zero extra cost**:

- After each gate, record whether the human approved the recommendation **unchanged** (`gate_agreement` in state).
- When a gate's recent agreement is consistently high (e.g. ≥ N approved-unchanged in a row), Helix **proposes** raising its autonomy — as a one-tap suggestion, never automatically.
- If an auto-approved step is later **reverted or salvaged** (§6.4), that gate **auto-demotes** back to `always_ask` and says why.

Autonomy becomes evidence-driven and self-correcting instead of a blind switch the user has to calibrate by gut.

---

## 6. Atlas — the knowledge layer

### 6.1 Folder structure (canonical layout)

```
atlas/                        # root, git-tracked
├── ATLAS.md                  # schema / contract
├── index.md                  # catalog of all pages
├── log.md                    # append-only event log
│
├── concepts/                 # canonical, cross-project knowledge
│   ├── sim-to-real-imaging.md
│   ├── centerline-tracing.md
│   └── odf-direction-prediction.md
│
├── entities/                 # canonical
│   ├── people/
│   │   └── dr-shin.md
│   ├── datasets/
│   │   └── cleveland-2025.md
│   └── tools/
│       └── totalsegmentator.md
│
├── methods/                  # canonical (stats, validation techniques)
│   ├── icc-bland-altman.md
│   └── physical-phantom-design.md
│
├── sources/                  # one page per paper
│   └── 2024-zhang-bowel-anatomy.md
│
├── raw/                      # immutable: PDFs, original docs
│   └── 2024-zhang-bowel-anatomy.pdf
│
├── scratch/                  # ephemeral — Scout outputs and uncommitted projects
│   ├── scout-2026-05-15/
│   └── new-vague-idea/
│
├── projects/                 # active projects
│   ├── bowel-length/
│   │   ├── overview.md
│   │   ├── plan.md
│   │   ├── hypothesis-evolution.md
│   │   ├── decision-log-narrative.md
│   │   ├── .decision-log.json         # structured sidecar
│   │   ├── validation-cascade.md
│   │   ├── critiques/
│   │   │   ├── methods-1.md
│   │   │   └── results-1.md
│   │   ├── results/
│   │   │   └── run-2026-05-20.md
│   │   └── repro.md
│   └── surgical-ml-opi/
│
└── archive/                  # published or abandoned
    └── 2024-old-project/
```

### 6.2 Page frontmatter conventions

Every page has YAML frontmatter:

```yaml
---
id: 0f3c1a9e-7b22-4c8a-9d11-2e6f5a0b3c44   # STABLE uuid — the real identity
title: "Sim-to-Real Imaging"
type: concept                  # concept | entity | method | source | project | scratch
status: canonical              # scratch | active | canonical | published | archived
summary: "Techniques for training imaging models on synthetic data..."
tags: [imaging, ml, sim-to-real]
created: 2026-04-01
updated: 2026-05-15
referenced_by: [proj:bowel-length, proj:surgical-ml-opi]   # by id, not path
---
```

The `summary` field is what the cheap retrieval tier loads. The body is loaded only when the page is selected for deep reading.

**Identity is the `id`, never the path.** Every Forge-state pointer, decision-log `atlas_ref`, and `[[wikilink]]` resolves through an id → current-path index maintained by the Atlas write layer. Promotion moves files and rewrites link *text*, but the underlying ids are unchanged, so **moving a page can never break a reference**. This removes the entire class of "promotion invalidated my pointers" bugs.

**Claim provenance.** A page body may tag individual claim lines with an inline `^src:<source-id>` or `^dec:<decision-id>` marker recording which source or decision introduced that claim. Lint uses these to distinguish *stale* claims (provenance superseded) from *current* ones — without provenance, "find stale claims" is unimplementable.

### 6.3 Status tiers and retrieval defaults

| Tier | What | Default retrieval scope |
|---|---|---|
| `scratch` | Exploratory, ephemeral | Hidden unless explicitly asked or linked |
| `active` | Real project, likely to publish | Included for current and cross-project queries |
| `canonical` | Generalizable, durable | Always included |
| `published` | Frozen at publication | Included; immutable except via promotions to canonical |
| `archived` | Abandoned or superseded | Excluded by default |

### 6.4 Operations

- **Ingest** — Scout (or you) drops a source. Atlas updates: source page created, concept pages updated, contradictions flagged, log entry appended. All via the write model below.
- **Query** — Agents call `atlas.retrieve(query, budget, scope)`. Returns ranked context within token budget.
- **Lint** — runs **continuously**, not only at freeze. Every write triggers an incremental lint of the touched pages (broken/duplicate links, orphan, contradiction, stale-by-provenance). `helix lint` / Maintainer's freeze lint is the full-corpus sweep; the incremental pass keeps retrieval quality from degrading silently between sweeps.
- **Promote** — explicit, human-initiated (usually as an *accepted suggestion*, see §9.4). Moves files across tiers and rewrites link text, but ids are stable so no pointer is invalidated. Logged as a decision-log event.
- **Salvage** — first-class action at any abandon/dead-end (research is *mostly* dead ends, so this is optimised, not an afterthought). `helix salvage <project|branch>` extracts the durable findings/claims into `canonical` *with provenance*, parks the branch's Snapshot (resumable), and logs why the line died. The learning survives even when the path doesn't — and the death reason becomes part of the §14 artifact.

#### 6.4.1 Atlas write model (single ordered writer)

Atlas is written by the project workflow, the async Watcher, the Maintainer, *and* the human in Obsidian. Concurrent prose edits to the same markdown file cannot be auto-merged by git, so Atlas does **not** allow free-for-all writes:

- **All agent writes go through one append-then-compact queue.** A writer appends an intent record (`{page_id, op, payload, base_version}`); a single serial applier validates `base_version`, applies the op, bumps the page version, and re-renders any derived files (e.g. the decision-log narrative). One writer at a time, globally — agents never touch files directly.
- **Optimistic concurrency on `base_version`.** If a page changed since the writer read it, the applier rejects the op and the agent re-reads and retries. No lost updates.
- **Human (Obsidian) edits are first-class.** A filesystem watcher ingests human saves as queue ops too, so a manual edit and an agent edit to the same page serialize instead of clobbering. **Saves to a `generated: true` file** (e.g. the decision-log narrative, Loom/Prism exports) are the one special case: not ingested as page edits and not clobbered, but diffed and offered back as a one-tap "fold into the source" suggestion (§7.2) — the projection stays pure without ever discarding the human's writing.
- **The Watcher writes only to `scratch/`** and proposes diffs against `canonical`/`active` pages; those diffs are applied by the queue (and surfaced as FYI items, §9.5), never written behind an in-flight project.
- The LangGraph checkpointer (SQLite local) is likewise single-writer; the Watcher subgraph checkpoints to its own namespace to avoid contention.

### 6.5 ATLAS.md (the schema doc)

A markdown file at the Atlas root that tells agents the conventions. Co-evolves with use. Sections include:
- Folder structure rules
- Page formats per type
- Wikilink conventions
- Status tier semantics
- Retrieval defaults
- Privacy markers (`private/` subfolders, banners)
- When to update what during ingest

---

## 7. The bridge — one decision log, one source of truth

The decision log is the bridge between machine routing and human reasoning, and it is the product's core durable artifact (§14). Precisely because it matters most, it has the *strongest* consistency model, not the weakest: **the structured JSON is canonical; the narrative is a deterministic render of it.** There is no dual-write, no sync step, and no ambiguity about which copy is correct.

### 7.1 Canonical form — structured JSON (the only writeable copy)

Each entry captures not just *what* was decided but *why* and *on what evidence*, so the prose can be regenerated without a human ever editing it:

```json
{
  "id": "bowel-length#decision-2",
  "timestamp": "2026-05-15T16:04:12Z",
  "stage": "methods",
  "action": "pick:ODF",
  "chosen_id": "approach-3",
  "rejected": [
    {"id": "approach-1", "reason": "single-vector can't represent two valid directions at crossings"},
    {"id": "approach-2", "reason": "multi-task aux head adds complexity without resolving directional ambiguity"}
  ],
  "rationale": "Critic-Methods raised the crossing-point failure mode; ODF represents multimodal direction so it survives crossings.",
  "evidence": ["src:2024-zhang-bowel-anatomy", "concept:odf-direction-prediction"],
  "atlas_ref": "proj:bowel-length",
  "wiki_pages_touched": ["concept:odf-direction-prediction", "proj:bowel-length#hypothesis-evolution"],
  "auto_or_human": "human",
  "autonomy_mode": "always_ask"
}
```

All references are **ids**, not paths (§6.2), so promotion never breaks a decision-log link.

### 7.2 Rendered form — Atlas markdown (generated, never authored)

The Atlas write layer regenerates `decision-log-narrative.md` from the JSON on every write. The renderer turns `rationale`, `rejected[].reason`, and `evidence` ids into prose and wikilinks:

```markdown
## Decision 2 — Pick ODF over single-vector
*2026-05-15, gate_methods, human-decided*  · *(generated from .decision-log.json — do not edit)*

Critic-Methods raised the crossing-point failure mode, so we picked
ODF over single-vector prediction: ODF represents multimodal
direction and survives intestinal crossings — see
[[sources/2024-zhang-bowel-anatomy]] and [[concepts/odf-direction-prediction]].

Rejected:
- approach-1 (single-vector): can't represent two valid directions at crossings
- approach-2 (multi-task aux head): adds complexity without resolving the ambiguity

Next: Planner drafts validation cascade.
```

Because the narrative is a pure projection: it can never silently diverge, "richer prose" must be captured as structured `rationale`/`evidence` (good discipline — it forces the *why* into the artifact), and the same renderer powers the **catch-me-up digest** (§9.6) and the **gate "why" bullets** (§9.3) for free.

**Human edits to a generated file are intercepted, never clobbered (this resolves the §6.4.1 tension — a real conflict, not a footnote).** A derived file carries `generated: true` in frontmatter plus the "do not edit" banner, but the banner is a courtesy, not the safeguard — the file is markdown in the user's Obsidian vault and *looks* editable. The actual safeguard: when the §6.4.1 filesystem watcher sees a human save to a `generated: true` file, the write queue neither ingests it as a page edit (it would vanish on the next regenerate) nor overwrites it blindly. It diffs the human's prose against the freshly-rendered text and routes the delta as a one-tap FYI (§9.5): *"You edited the generated decision log — fold this into Decision N's rationale?"* [ Fold ] [ Discard ]. Accepting writes the prose into the canonical JSON `rationale` (which also enriches the §14 artifact); the file then regenerates *from* it. The edit is preserved by **promoting it into the source of truth**, never by tolerating a divergent copy — so both invariants hold simultaneously: the projection stays pure *and* a human edit is never silently lost. The identical rule covers every generated file (Loom/Prism exports, the catch-me-up text). Silently eating a researcher's writing is the single worst friction this system could create; it is therefore designed out, not documented around.

### 7.3 The Snapshot — a composite commit for the whole project

§5 is the *Actions* half of the tagline (a pipeline). The decision log alone is an **event log, not version control**: you can replay what happened but you cannot *check out the project as it was at decision 4*. Without the piece below, Helix has a workflow but not a versioning data model — code, Atlas, decisions and data are independent histories that silently desync.

The fix is one keystone primitive. A **Snapshot** is a small content-addressed object that atomically binds the entire project state by reference:

```json
{
  "id": "snap:bowel-length@7",
  "decision_head": "bowel-length#decision-7",
  "code_sha": "git:9f2c1ab",
  "atlas_pages": {"concept:odf-direction-prediction": "v4", "proj:bowel-length#plan": "v9"},
  "data_hashes": {"cleveland-2025": "sha256:…", "run-2026-05-20": "sha256:…"},
  "env_lock": "sha256:…",            // resolved deps / container digest
  "branch": "main",
  "parent": "snap:bowel-length@6"
}
```

**Logging and Snapshotting are decoupled — this is what keeps the DAG decision-shaped.** *Every* decision is logged: append-only, cheap, fully replayable (§7.1). But a Snapshot is minted only at a **meaningful point** — every HITL gate decision, every branch/park/resume, every freeze. A contiguous run of pure auto-routed steps (deterministic detector outputs like `plan_violation`/`leakage_detected`, §5.4 — mechanical, not judgement) does **not** mint a Snapshot each; it **coalesces into the next meaningful Snapshot**. This is deliberate. Minting one per auto-route produced a ~200-node DAG for an 8-decision project and forced Loom to add a "fold" channel purely to stay readable; fixing the data model at the source beats rendering around the symptom, so with this rule **Loom's fold is cosmetic, not a scalability crutch** (§7.7.4). Snapshots stay cheap (references, not copies). The version-control gap is still resolved end to end: code↔Atlas↔decision desync is removed (one reference set), and **reproducibility is continuous, not freeze-only** — every *meaningful* state is fully reconstructable, not just the published one. `helix checkout <decision-id>` of a coalesced auto-routed id resolves to its enclosing Snapshot — a well-defined point; the intermediate mechanical states carry no independent value to reconstruct. The §7.4–7.6 capabilities still fall out of this almost for free.

### 7.4 Branches — parallel research lines, first-class

Research *is* branching: "what if we'd used approach-2." Today `candidate_approaches` is transient working memory — the alternatives are logged as prose then die. They are now promoted to **durable branches**:

- `helix branch <approach>` forks the current Snapshot into a named research line.
- Branches **run and resume in parallel**; the methods/results gate becomes a **compare view** (side-by-side results + decision rationale) instead of a one-shot irreversible pick.
- A rejected line is **parked, not deleted** — its Snapshot is retained and `helix resume <branch>` brings it back later. The most common real research move ("actually, go back and try the other thing") becomes one command instead of manual surgery.

This makes Helix model how research actually works — a tree of bets — and is what completes the **Git** half of the tagline: version control for the whole project, not only a pipeline over it.

### 7.5 Project version control — diff, history, bisect, fork, repro

All cheap once Snapshots exist:

| Git primitive | Helix command | How it works |
|---|---|---|
| Diff | `helix diff <snapA> <snapB>` | **Semantic**, not text: claims added/removed, target metric 0.05→0.10, candidate-set delta, plan-dict changes — using the structured fields, not markdown line-noise |
| History | `helix history` | The decision DAG *is* the project's commit graph |
| Checkout | `helix checkout <decision-id>` | Materialises that Snapshot (code + Atlas versions + data) |
| Bisect | `helix bisect` | Walks the decision DAG to find which decision introduced a metric regression |
| Tag/release | Snapshots are nameable | Not just one "published" tag — any Snapshot can be named and returned to |
| Fork | `helix fork <project>` | Exports a Snapshot + its Atlas subgraph + decision history as a self-contained importable bundle — *forking a research project with its reasoning*, not just a repo. This is what makes §13's open-source strategy actually possible |
| Repro | `helix repro <snapshot>` | Reproduces **any** point, continuously, because every Snapshot is complete |

### 7.6 Storage layering — the right store per artifact class

"Version control for the whole project" must not mean "cram everything into one markdown git repo" (PDFs/data bloat history; prose diffs are noise; the graph isn't diffable). Instead, one composite history over four right-tool stores, tied together by the Snapshot:

| Artifact class | Store |
|---|---|
| Code | git (sha referenced by the Snapshot) |
| Data, weights, run outputs | content-addressed store (DVC/LFS-style, or just hashes recorded in the Snapshot) |
| Knowledge (Atlas) | per-page-versioned graph (the write model of §6.4.1), **not** line-diff git |
| Decisions | append-only log (§7.1) — the project's commit DAG |

The Snapshot binds them by reference, so the project has one coherent version history without any single store being asked to do a job it is bad at.

### 7.7 Loom — the project map (a zero-config artifact, generated on demand)

The Snapshot DAG (§7.3) is the project's complete commit history; on its own it is a JSON graph. **Loom** is the one canonical way Helix renders that graph so the whole shape of a project — where you've been, what's parked, what's alive, why each decision was made — is comprehensible in a single image.

**Loom is not a daily surface and not something a user operates or configures.** It is **auto-emitted, fully formed, only at the moments it pays off** — `helix freeze` (publication supplement), `helix fork` (bundle), and long-idle re-entry (§9.6) — and is otherwise available on demand via `helix loom`. It is never on the path of routine work, has zero configuration, and is *not* required to run a project: the friction floor stays the seven core verbs (§9.0). Like the decision-log narrative (§7.2), the render is a **pure projection** of `decision_log` (§7.1) + the Snapshot DAG (§7.3) + the Atlas id→path index (§6.2) — there is no Loom-specific source of truth, so it costs nothing to *not* look at it until it matters.

#### 7.7.1 What Loom shows

A horizontal swim-lane timeline:

- **Node = Snapshot**; **lane = branch**, running left→right; **main is always the top lane**.
- **Fork points** are dashed connectors from the parent Snapshot down to the child lane's first node.
- **Phase label above the head node of every lane** (not just main — branches have gates too) names the gate/agent: `scout`, `methods`, `plan`, `build`, `validate`, `critique`, `frozen`.
- **Click any node** → the Snapshot detail callout: rationale, evidence, `auto_or_human`, autonomy mode at the time, confidence band (§9.3), and the four artifact chips (decision · atlas · code · data+env) showing exactly what `helix checkout <snap>` would materialise.

**Caching is split so it stays both fast and never stale:** the DAG *layout* is a pure function cached by `(project, snapshot_head)` and invalidated on every Snapshot write; chip *labels* are resolved live through the id→path index at render time, so a page rename or promotion never shows a stale label. Loom is invalidated-on-write and **rendered on demand**, never eagerly regenerated on every gate.

#### 7.7.2 The four view modes

| Mode | Use | CLI |
|---|---|---|
| **Map** (default) | Full project shape — swim lanes, all branches | `helix loom` |
| **Layers** | The Snapshot binding view — decisions/Atlas/code/data stacked, cursor on the current head; §7.6 made visible | `helix loom --layers` |
| **Compare** | Two Snapshots side-by-side | `helix loom --compare <a> <b>` |
| **Bisect** | Walks the decision DAG; the regression node lights up | `helix loom --bisect` |

All four render the same data, so modes are cheap. **Compare is decoupled from the workflow:** the v1 branch-compare gate (§7.4) uses textual `helix diff` (§7.5) and is never blocked on Loom; Loom Compare is the visual layer over that same diff, landing after Map.

#### 7.7.3 Surfaces and output

```
helix loom                      # auto-detects: TTY over SSH/no-display, web locally
helix loom --tty | --web        # force a surface
helix loom --export <path>      # static SVG + PDF (grayscale-legible — see contract)
helix loom --embed <doc>        # interactive embed for an HTML supplement
```

The interactive view runs on the **same minimal FastAPI service as the mobile gate view (§11)** — no new server. The TTY render uses Unicode box-drawing for lanes and chip rows.

#### 7.7.4 The visual-encoding contract (fixed, enforced, not user-styleable)

The encoding is fixed so Loom reads the same across wildly different projects; the renderer enforces it; users and agents never style it. The **load-bearing rules** (the parts that are design, not rendering detail):

- **Color encodes status only** (active/main · parked · salvaged · published) — never agent or gate type; those are the text label.
- **A redundant one-glyph status tag on every node is authoritative**, so status is *never carried by color alone*. The SVG is a publication artifact (journals print grayscale) and the TTY may run under `NO_COLOR` — **grayscale- and no-color legibility is mandatory, not a nicety**. No theming, no per-project palettes.
- **Node size encodes nothing** — every decision is equal; consequence is shown as outcome, not emphasis. **No animation by default.** Main lane on top; parked/salvaged below, ordered by fork point.
- **HITL decisions are never folded.** The fold channel is **cosmetic only**: per §7.3 the Snapshot DAG is already decision-shaped (auto-routed steps coalesce into the next meaningful Snapshot), so folding is a nicety, not a scalability crutch.

The exhaustive channel enumeration (exact glyphs, opacity/recency/connector/fold value lists) is a renderer concern and lives in the implementation tracker, **exactly as exact geometry already does** — the spec carries the contract, not the pixel table.

#### 7.7.5 The "since last view" cursor is *view state*, not project state

The recency ring needs a per-viewer pointer to the last Snapshot seen. This is **view state, like scroll position**: a `last_viewed_snapshot` per viewer that is **never written to a Snapshot, the decision log, or a fork bundle**, carries no authority, and for which "out of sync" is meaningless. The §7.1 purity claim is about the *project artifact*, which this does not touch. If the cursor is absent (new machine, fresh fork) Loom falls back to the §9.6 idle boundary.

#### 7.7.6 Why auto-generated, not a daily surface

A reproducibility trail no one reads is theatre — but a visual a user has to *remember to run* is also dead weight. Loom resolves both by being **auto-produced at exactly three moments and never operated in between**. All three are deferred, which is precisely why Loom adds zero daily friction:

- **Publication supplement.** `helix freeze` emits a grayscale-legible Loom SVG/PDF beside the repro manifest. Reviewers see every parked branch, every salvaged dead-end and the decision chain in one image — the §13 within-project value made visible, not just narrated.
- **Catch-me-up (§9.6).** On a long-idle project Loom is shown **alongside** the text digest — it *complements*, never *replaces* it: the digest stays the glanceable mobile form, Loom is the desktop/supplement form. Nodes added since the cursor (§7.7.5) carry the recency ring.
- **Fork onboarding (§7.5).** `helix fork` bundles the Loom render so a researcher gets the visual reasoning map *before* reading any code — what makes §13's open-source strategy usable, not just possible.

#### 7.7.7 Failure modes handled explicitly

- **Tiny projects (< 3 Snapshots)** render as a single-line strip, not a sparse empty canvas.
- **Hub blow-up** (many decisions touch one canonical page, §8.6) → chip-row clustering: shared chips collapse to `+N more` past 4 in the callout.
- **Branch abandoned without salvage** → faded (opacity channel) + an FYI queue item *"abandoned without salvage — `helix salvage` to capture the learning?"* (§9.5). The visual surfaces a cost the prose log hides.
- **Wide DAGs** → horizontal scroll with sticky left lane labels.
- **Privacy (§9.9)** → redaction happens **both at render and at export/fork time**: a private project's chip rows for shared canonical pages show only the id stub, and the *baked* SVG in a fork bundle is redacted too. Forking a private project requires the same manual-abstraction step as promotion — the bundled render can never become a back-door exfil path.

#### 7.7.8 What Loom is not

- **Not the Atlas graph.** Atlas's graph (Obsidian) is the *knowledge* graph; Loom is the *project's version-control* graph. They cross-reference by page id but render separately.
- **Not the LangGraph Studio view.** Studio renders the agent state machine for debugging (§9.2); Loom renders the history of decisions a project made.
- **Not editable.** No dragging nodes, renaming branches in place, or rearranging lanes. Loom is a projection — to change it, make a new decision and a new Snapshot. (If per-node annotation is ever added it writes to the decision log, never to Loom — no second source of truth.)

### 7.8 Prism — the project anatomy (a zero-config artifact, generated on demand)

Where Loom (§7.7) renders the project's *history*, **Prism renders the project's *structure* in one image**: the strategy that motivates it, the data that feeds it, and the code that runs it — with the *why* attached to every non-obvious choice. Like Loom it is **not a daily surface, not configured, and not required to run a project**; it is auto-emitted only at the moments it pays off — handing a collaborator the project, a publication supplement, returning after months away — and otherwise available on demand via `helix prism`. The friction floor stays §9.0's seven verbs; Prism appears fully formed when re-entry or sharing makes it worth having.

Prism stores nothing new and **introduces no new source of truth**. It is a deterministic projection of structural pointers (`project_meta`, the head Snapshot's `code_artifacts` + `data_pipeline` + `data_hashes`) and the decision-log JSON. Like Loom, it is invalidated on every Snapshot write and **rendered on demand**, and auto-emitted into `helix freeze` and `helix fork` bundles.

#### 7.8.1 The three sections — fixed order, fixed jobs

Every Prism has exactly three sections, top to bottom, never reordered:

| Section | Answers | Contents |
|---|---|---|
| **Strategy** | what is this for, and what approach was chosen | research question, methods choice + rationale, constraint chips |
| **Data** | what feeds it, and why this data | a left→right pipeline of data stages with a rationale line under each |
| **Code** | how it's organized, and why this structure | the `src/` cluster of modules + an organization-principle annotation |

The order is fixed because *why* precedes *what* precedes *how* — a reader scanning top-to-bottom reconstructs motivation → materials → methods, the same order a paper uses. "You've read one Prism, you've read them all" is the contract; there is no reorder flag, ever.

#### 7.8.2 The shape vocabulary — universal across all Prisms

Four shapes, four meanings, renderer-enforced: **rounded rect** = strategic concept, **plain rect** = code/module, **cylinder** = data store, **dashed box** = logical cluster ("grouping, not a component"). Any other shape is rejected. Runtime-component/cloud shapes are deliberately excluded — agents, orchestrators and the live queue are *workflow* (Loom's and the queue's job), not anatomy. The exact shape→element mapping is a renderer concern and lives in the tracker.

#### 7.8.3 Layout contract — semantic, not pixel

The contract is **semantic**, not a coordinate grid (exact geometry lives in the tracker, as for Loom §7.7.4). Enforced: **fixed section order Strategy → Data → Code, top to bottom**; **bounded slots** that collapse gracefully per §7.8.4 rather than overflowing; a **shape-vocabulary legend always present on static export** (`--no-legend` is interactive-only, ignored on SVG/PDF); consistent left→right / top→bottom flow, no diagonals, arrows share Loom's chevron marker. A Prism that overflows its container, overlaps text, or draws a cluster border solid is a **renderer bug, not a styling choice**. Exact slot capacities are tracker detail, not contract.

#### 7.8.4 Every rationale comes from the decision log — never a second copy

Prism's payload is the *why*, and the *why* lives in exactly one place: the decision log (§7.1). Data-choice and code-organization **are decisions**, so they are decision-log entries with `rationale` — already quality-enforced upstream by teach-back (§9.3). `project_meta`/`data_pipeline` carry only **structural pointers** (which datasets, which modules, which labels), never a parallel prose copy of the reasoning. This is deliberate: it makes Prism a genuine pure projection, and it **eliminates "rationale rot"** by construction — there is no separately-authored field that can drift from the decisions it describes.

- **Strategy** rationale = the chosen-methods decision's `rationale` (rendered as the methods box subtitle).
- **Data** rationale = the data-choice decision's `rationale` (one line under each cylinder).
- **Code** rationale = the project-structure decision's `rationale` (the organization-principle box).

If the relevant decision carries no rationale, the slot renders an FYI hint — *"add rationale to enrich this view"* (the §9.4 promotion-as-suggestion pattern) — and `helix doctor` flags it. The slot is **never silently blank**.

#### 7.8.5 Density rules — when a section is too full

Each section has a bounded slot count; over-capacity content collapses to a "+N more / +N stages / +N modules" affordance (expandable in the interactive view), never a layout overflow. The organization-principle slot is a *hard* limit — exceeding it is a project-level code smell, not a rendering problem. Hitting any limit signals the project has more substance than one page holds — exactly what the interactive click-throughs are for; the static SVG stays bounded. Exact per-section limits are a renderer-tuning concern and live in the tracker, not the contract.

#### 7.8.6 Surfaces and output

```
helix prism                     # auto-detects: TTY over SSH/no-display, web locally
helix prism --tty | --web
helix prism --export <path>     # static SVG + PDF (legend always included)
helix prism --embed <doc>       # interactive embed for an HTML supplement
helix prism --no-legend         # interactive only; ignored on export
```

Same minimal FastAPI service as the mobile gate view and Loom — no new server. Same render-pipeline scaffolding as Loom (one engine, per-surface backends) so the two visualisations don't double the maintenance surface.

#### 7.8.7 Failure modes handled explicitly

- **Empty data pipeline** (before first ingest) → cylinders are dashed-outline placeholders, hint *"data not yet captured — `helix explore` to seed"*; slots stay in place.
- **No code yet** (before first build) → empty `src/` cluster with a dashed placeholder *"first build will populate this"*.
- **Sparse rationale** → FYI hints (§7.8.4), never blank.
- **Long module/dataset names** → ellipsis truncation (itself an overflow signal) + a `helix doctor` suggestion to shorten the name upstream.
- **Privacy (§9.9)** → redaction at **render and at export/fork time**: private datasets show id-only labels and category-only rationale; the *baked* SVG in a freeze/fork bundle is redacted too. Forking a private project requires the same manual-abstraction step as promotion — the bundled Prism can never become a back-door exfil path.

#### 7.8.8 What Prism is not

- **Not the workflow view.** No Forge runtime, agents, current Snapshot, sanity flags or budget gauges — those are Loom and the queue.
- **Not a timeline.** Prism is timeless; it describes the project's shape, not its position in time (the rejected past/present/future framings conflated the two).
- **Not a dashboard.** No live counters. It changes only when the project's *structure* changes — exactly the property that makes it fit for a publication supplement.
- **Not editable.** Every element is a projection from `project_meta`, `decisions`, or `code_artifacts`. To change Prism, change the underlying state.

#### 7.8.9 The Loom + Prism pairing

| | Loom (§7.7) | Prism (§7.8) |
|---|---|---|
| Question | What *happened* in this project? | What *is* this project? |
| Axis | Time, by Snapshot | Anatomy: strategy → data → code |
| Layout | Swim lanes (one per branch) | Three fixed sections, top-to-bottom |
| Primary use | Audit, reasoning trail, bisect | Onboarding, re-entry, supplement |
| 60-second takeaway | "tried these things in this order" | "exists to solve X, uses data Y because Z, organised as W because V" |

They complement, never overlap. A published supplement ships both; a long-idle re-entry shows Prism first (orient) then Loom on a click (the timeline); a fork bundle includes both.

---

## 8. Retrieval architecture — GraphRAG over Atlas

### 8.1 Why graph

Atlas is a graph natively: pages = nodes, `[[wikilinks]]` = edges. Retrieval becomes graph traversal, which scales with **hops × pages-per-hop**, not total Atlas size — *provided* the graph is well-linked and not hub-heavy. The two ways that assumption fails (a tiny early graph, and a few over-connected hub pages) are handled explicitly in §8.6.

### 8.2 Three-tier context loading

| Tier | What | Tokens | When loaded |
|---|---|---|---|
| 1 | Title + frontmatter summary | ~30 | Always (cheap index file) |
| 2 | Full summary section | ~200 | Anchor candidates |
| 3 | Full page body | ~500–2000 | Only after ranking |

### 8.3 Token budgets per agent

| Agent | Budget | Hops | Scope default |
|---|---|---|---|
| Scout | 20k | 2–3 | Current project + active + canonical |
| Critic-Methods | 10k | 2 | Current project + active + canonical |
| Planner | 8k | 1–2 | Methods + this project's prior plan iterations |
| Builder | 5k | 1 | Methods only |
| Validator | 3k | 1 | Benchmarks only |
| Critic-Results | 10k | 2 | Sources of competing methods |
| Maintainer | unbounded | full | All (offline lint) |

### 8.4 Retrieval API

```python
class Atlas:
    def retrieve(self, query: str, *,
                 max_hops: int = 2,
                 max_tokens: int = 10_000,
                 project_scope: Optional[str] = None,
                 status_filter: Optional[List[str]] = None,
                 recency_decay: bool = True) -> RetrievedContext:
        """
        1. Find anchor pages via embedding similarity on summaries.
        2. BFS up to max_hops from anchors, weighted by edge type + recency.
        3. Rank candidates; load tier-2 summaries; expand tier-3 bodies on demand.
        4. Respect max_tokens; return what fits + a flag if budget was exceeded.
        """
```

### 8.5 Cost numbers (rough)

For a 1000-page Atlas, ~500 words each:
- Naive full-dump: ~650k tokens → doesn't fit; dollars per call
- **Graph retrieval: ~5–10k tokens per call → cents**
- Summary embedding index: ~40k tokens, embedded once, refreshes on page change
- Embedding storage: ~6 MB for 1000 pages (1536-dim float32)
- Architecture scales to ~10,000 pages on the same approach

### 8.6 When the graph assumption breaks (cold start, hubs, link hygiene)

The token math above is only true once Atlas is dense and link-clean. Three explicit safeguards keep retrieval good in the meantime:

- **Cold start (small graph).** Below a configurable page/edge threshold the retriever skips traversal and runs **flat embedding + BM25 over all summaries** (cheap because the corpus is tiny). The graph kicks in automatically once it's worth traversing. The user never sees a "graph not warmed up yet" failure mode.
- **Hub blow-up.** BFS applies a **per-node degree cap**: when a hub page exceeds the cap, its neighbours are *not* expanded blindly — only the top-k by embedding similarity to the query are followed, and the hub itself is summary-only unless it's an anchor. "pages-per-hop" is therefore bounded even for pages `referenced_by` everything.
- **Link hygiene is enforced, not hoped for.** Agents write `[[wikilinks]]` by id through the write queue, which **rejects links to nonexistent ids and normalises titles**, so broken/duplicate links can't enter the graph in the first place. The continuous lint (§6.4) catches anything that slips through on the same write. Retrieval quality cannot degrade silently between freezes.

---

## 9. UX layer

There is **one mental model — the queue** — and it is identical on every surface. The user never has to remember "which of four tools does this." Surfaces are just different windows onto the same queue; the CLI and Obsidian are accelerators, not separate workflows.

### 9.0 The core surface — seven verbs and the queue (the friction floor)

The §9.7 reference lists ~50 commands. That is the *ceiling*, for power users and scripting — **not** what anyone must learn. A solo researcher reaches first value and runs an entire project knowing only the queue and these seven verbs:

| Verb | Does | So you never learn |
|---|---|---|
| `helix` | the queue (no args): what needs you, what's running, FYI | any status/list command |
| `helix think` | open, ticket-free exploration | the whole pre-project surface |
| `helix explore "<q>"` | one-shot literature scan | Scout/Watcher internals |
| `helix init <name>` | commit an idea to a project | tier/location vocab (flags optional) |
| `helix <project>` | act on this project's pending item | every gate verb |
| `helix why <project>` | the reasoning behind where it is | the decision-log/Snapshot model |
| `helix undo <project>` | rewind the last step | branch/checkout/bisect for a plain "oops" |

Everything else (branch/park/resume, diff/history/checkout/bisect/fork/repro, promote/demote/freeze, model/provider, loom/prism, salvage, doctor) is either **surfaced as a one-tap suggestion in the queue exactly when it's relevant** (§9.4), with its precise invocation shown, or is a **power-user accelerator you opt into**. The queue prints the command it would run, so **discovery replaces memorization**. That is the operational meaning of "minimal friction": the floor is seven verbs, the ceiling is scriptable, and the queue — not the user's memory — bridges them. Every claim of "small surface" in this document means *this* floor, not the §9.7 reference.

### 9.1 The unified queue (the only thing the user has to learn)

Everything that needs the user — gates, "Scout done", Watcher findings, budget stops — lands in **one prioritised queue**. `helix` with no arguments *is* the queue. The mobile home screen *is* the queue. They render the same data:

```
$ helix
NEEDS YOU NOW (1)
  ▸ bowel-length — approve the approach? Critic flagged 3 issues      2h ago
WORKING (2)
  · surgical-ml-opi — Builder running                            ~20m left
  · explore: "synthetic CT…" — 12 papers, 2 gaps found              done
FYI (3)
  · Watcher: 2 new papers may overlap bowel-length
  · Maintainer: "crossing-point failure" seen in 3 projects → save as reusable?
  · surgical-ml-opi — budget 78% used
```

Three buckets, fixed order: **Needs you now** (blocking) → **Working** (in flight) → **FYI** (no action required). One badge count = items in *Needs you now*. The user works top-down; nothing else has to be memorised.

### 9.2 Surfaces, reframed

| Surface | Role |
|---|---|
| **Mobile / minimal web view** | Primary surface for the queue + one-tap decisions. QR-paired auth. |
| **`helix` CLI** | The same queue + power-user accelerators (scripting, batch, ad-hoc search). |
| **Obsidian** | Reading/graph-browsing Atlas. Manual edits are ingested by the write queue (§6.4.1), so editing here is safe, not forbidden. |
| **LangGraph Studio** | Contributor/debug only — never required for daily use. |

No "avoid for" column: each surface can *show the queue and act on it*. They differ in convenience, not in capability.

### 9.3 Gate decisions — progressive disclosure + an undo window

A blocking item opens into a decision view designed so the **common path is a single tap** and depth is available but never required:

1. **One line** in the queue (what's blocked, how long it's waited).
2. **Tap →** the decision, with the **recommended option pre-selected** and a 3-bullet *why* (generated from the decision-log `rationale`/`evidence`, §7 — no extra cost).
3. **Expander →** the full critique / candidates / context for users who want it.

**Reversibility removes the fat-finger anxiety of one-tap on a small screen:**

- Approving the recommended option starts a **soft-commit window** (default 20s): *"Planner starting in 20s — [Undo]"*. Nothing irreversible runs until it elapses.
- Choosing a **non-recommended** option requires one explicit confirm (this is the only place a second tap is forced — proportionate to the risk).
- Any decision remains rewindable via the decision log: `helix undo <project>` reverts to the prior checkpoint and logs the reversal as its own decision entry.

**Inverted friction (the expertise paradox).** One-tap is dangerous exactly when the user *can't* evaluate the recommendation — novice rubber-stamping is the failure mode, and it's worst on the highest-stakes calls. So friction is added where rubber-stamping is most likely, not uniformly:

- Every recommendation carries a **confidence/abstention signal** (self-consistency score + an explicit *"what I'm unsure about"* and *"what would change my mind"*).
- **High-confidence, low-stakes** items stay one-tap.
- **Low-confidence or high-stakes** items add friction proportionate to the risk *and the project's tier* — never a uniform tax that makes the tool feel like a justification grind:
  - **The default interaction is *pick*, not *type*.** The user sees the recommended rationale plus 2–3 generated alternatives and taps the one matching their reasoning — one tap, no keyboard (decisive on mobile). Free-typing is the fallback for "none of these is the real reason," not the demand. Earlier framings made typing the default; it is now the escape hatch.
  - **Teach-back is tier-scoped.** On `notes`/`project`-tier work — exploration, the headline grad-student user — it is **off by default**: a confidence banner is shown but the path stays one-tap, because nagging a researcher to justify every exploratory call is the paternalism that turns curiosity into a chore (§9.10). On `published`-tier or any project flagged regulated/IRB/PHI it is **on by default** (and may require PI co-sign, §13) — there the attestation trail *is* the deliverable. `helix config set teach-back on|off` overrides per project in either direction.
  - Whatever is picked (or, rarely, typed) is logged into the decision's `rationale` — a richer §14 artifact for free, and the **anti-knowledge-debt** mechanism *exactly where it earns its friction*, not everywhere.

### 9.4 Lifecycle as accepted suggestions, not memorised commands

Users should almost never type `promote --to canonical` or `freeze --status published`. The Maintainer already detects these moments; it now **proposes them as one-tap FYI items** in plain language:

> *"'Crossing-point failure' has shown up in 3 projects. Save it as reusable knowledge?"*  [ Save ] [ Not yet ]
> *"bowel-length looks publication-ready. Freeze it and write the repro manifest?"*  [ Freeze ] [ Not yet ]

Tiers, promotion and freezing still exist internally and the CLI verbs remain for power users — but the *required* path is answering yes/no to a suggestion. No tier vocabulary needed to be productive.

**The lifecycle ladder.** Power users don't memorise tier names either — there is one ordered ladder, and you move a project *up* or *down* one rung at a time:

```
   think  →  notes  →  project  →  published
                ↑__________↓                 → archived
              demote      promote      (freeze)
```

- `helix promote <name>` moves **one rung up** (`notes → project → published`); `helix demote <name>` moves **one rung down**. No `--to <tier>` needed for the common case — the ladder makes direction obvious. `--to <rung>` still works for a multi-rung jump.
- `notes` is the user-facing name for `scratch`, `project` for `active`, `published`/`archived` unchanged (§9.8). The ladder is the same object the one-tap suggestions act on — CLI and suggestions are two doors to one mechanism.
- Every rung change is a decision-log event and creates a Snapshot (§7.3), so promote/demote are themselves reversible and attributable.

### 9.5 Notification triage (one digest, not a stream of pings)

- Only **Needs-you-now / blocking** items trigger a real-time push.
- **Working** completions and **FYI** items (Watcher, Maintainer suggestions, budget warnings) roll into a single batched digest, not per-event pings.
- One badge: the *Needs you now* count. Quiet hours on by default.

The user is interrupted exactly when work is genuinely blocked on them, and never otherwise — which makes running several projects at once tolerable.

### 9.6 Catch-me-up on re-entry

When the queue is opened after >24h idle, each active project leads with a 2–3 line generated digest (same renderer as §7, so it's free):

> *bowel-length, since Tuesday: Validator found error 0.18 vs 0.05 target → plan auto-revised → Planner set new target 0.10. **Waiting on your approval.***

Returning after a week never means reconstructing state by hand.

### 9.7 The `helix` CLI surface (full reference — *not* the required surface)

> Skim, don't study. The required surface is the **seven core verbs in §9.0**; everything below exists for power users and is otherwise surfaced contextually by the queue (§9.4) with its exact invocation. A new user needs only the first marked group.

```
helix                                        # THE QUEUE (default, no args)  ── core (§9.0)
helix <project>                              # act on this project's pending item
helix peek [<project>]                       # READ-ONLY status + catch-me-up; no action, no tickets
helix why  <project|decision-id>             # show the decision rationale (the §14 artifact)
helix undo <project>                         # rewind to prior checkpoint (logged)

# Setup
helix setup                                  # zero-integration bootstrap (§11)
helix config show | set <key> <value>

# Think → Forge  (idea → committed project)
helix think [<topic>]                        # open, ticket-free exploration space (§9.10)
helix init  <name> [--from-think] [--tier notes|project] [--at <path>] [--private]
                                             #   ^ start a project at the rung/location you choose
helix explore "<query>" [--scope <path>]     # one-shot literature scan (was: scout)
helix watcher run|status|schedule

# Lifecycle ladder  (think → notes → project → published → archived)
helix promote <name> [--to <rung>]           # one rung up (default); multi-rung with --to
helix demote  <name> [--to <rung>]           # one rung down
helix freeze  <name> [--status published|paused]
helix archive <name>                         # = demote past the bottom rung
helix status  [<name>]                       # = the queue, filtered

# Research lines (branches & snapshots, §7.3–7.5)
helix branch  <approach>                     # fork a parallel research line
helix branches                               # list lines (active + parked)
helix park    <name|branch>                  # pause a line; Snapshot retained, resumable
helix resume  <name|branch>                  # continue a project or a parked line
helix diff    <snapA> <snapB>                # semantic diff
helix history | checkout <id> | bisect | fork <name> | repro <snapshot>
helix loom    [<project>]                    # the project map / history (§7.7) — auto TTY/web
helix loom    --tty | --web | --layers | --compare <a> <b> | --bisect | --export <path>
helix prism   [<project>]                    # the project anatomy (§7.8) — auto TTY/web
helix prism   --tty | --web | --export <path> | --embed <doc> | --no-legend

# Models & providers (§11.2) — switch per role or globally, API-key or local
helix model    list                          # show the resolved model for every role
helix model    use   <provider:model>        # set the GLOBAL default
helix model    set   <role> <provider:model> [--project <name>]   # per-role / per-project
helix <step>   --model <provider:model>      # one-shot per-step override (e.g. helix explore --model local:qwen2.5)
helix provider add   <name> --key-env <ENV>  | --local --endpoint <url>
helix provider list

# Atlas & knowledge
helix atlas search "<query>" [--scope <path>] [--budget <tokens>]
helix atlas lint [--project <name>]
helix atlas ingest <path-or-url>
helix salvage <name|branch>                  # keep the learning, park the dead end (§6.4)

# Health & cost
helix doctor [<project>]                     # one cross-layer diagnostic (§9.11)
helix cost [--period today|week|month]
helix log  <project> [--last N]
```

**This is the full reference, not the required surface.** What a user must know is the seven core verbs (§9.0); everything beyond them is a power-user accelerator or is surfaced contextually by the queue (§9.4) with its exact invocation, so it is *discovered when relevant*, never memorized up front. Verbs do still read like the mental model — you `think`, then `init`; you `promote`/`demote` along one ladder; you `branch`/`park`/`resume` research lines; you ask `why` — but that legibility is a bonus on top of not having to recall them at all.

### 9.8 Plain-language surface (internal names stay internal)

Internal architecture vocabulary is mapped once to user-facing language; the glossary (Appendix B) is a *contributor* doc, not something a user must read:

| Internal | User sees |
|---|---|
| Scout | Explore |
| gate_methods / gate_plan / … | "Approve the approach?" / "Approve the plan?" |
| canonical | "Saved (reusable) knowledge" |
| scratch | "Notes" |
| sanity flag · `plan_violation` | "Results missed the target" |
| promotion | "Save as reusable" |
| Loom map mode | "Project map" |
| Loom layers mode | "What each snapshot binds" |
| Loom compare mode | "Side-by-side" |
| Loom bisect mode | "Find where it broke" |
| Prism strategy section | "What it's for" |
| Prism data section | "What feeds it" |
| Prism code section | "How it's built" |
| Prism organization principle | "Why this structure" |
| Prism shape vocabulary | "What the icons mean" |
| Forge / Atlas | (never surfaced to end users; internal layer names) |

### 9.9 Privacy modes — a defined degradation, not a flag flip

`helix init <name> --private` does not silently swap a better product for a weaker one; it specifies *exactly* what changes:

- **Agent stack is explicitly downgraded and recorded.** Strict mode forces the model router (§11.2) to resolve every role to a `local:` or zero-data-retention provider, overriding any API-key role defaults. The substituted set is written to `privacy_degraded` in Forge state and shown on the project so the quality trade-off is visible, never silent.
- **Write boundary.** Private project pages never leave the machine; LLM calls go to local models or zero-data-retention endpoints only.
- **Read boundary (the part usually missed) — and why it needs no special machinery.** A private project may *read* shared `canonical` pages. There is **no separate "no-exfil retriever" to build or trust**: because strict mode already forced *every* role to a local/ZDR model (first bullet), nothing the retriever returns — private *or* canonical — can leave the machine, by construction. The only genuinely directional rule is on **writes**: private content is never folded into a `canonical`-page write (a write-queue classification, §6.4.1 — not a retrieval mode). The contamination boundary is one-directional and falls out of model routing plus the write model; it is not a bespoke component, and describing it as one was false sophistication.
- **No auto-promotion.** Private concepts can't auto-promote to `canonical`; they must be manually abstracted first. Pages carry a `private` banner.

### 9.10 The Think surface (so the queue doesn't become a backlog)

The queue is for work *blocked on you*. A multi-project queue is always non-empty, which silently reframes open-ended research as a ticket grind — the very usability win can make research feel like a job. So there is a distinct, deliberately separate **Think** surface:

- `helix think [<project>]` (and an Obsidian-side equivalent) — an open exploration space that **produces no queue items and no notifications**.
- Asking questions, browsing the Atlas graph, sketching, running ad-hoc `helix explore` here does **not** create gates or tickets until you explicitly say "make this a project / a branch."
- It is the default home for *curiosity*; the queue is the default home for *commitments*. Keeping them separate protects the unstructured thinking research actually needs.

**Think → Forge hand-off (`helix init`).** A Think session converts to a real project the moment you choose — never automatically. From inside Think (or from an explore result in the queue) one command commits it, and *you pick the rung and the location*:

- `helix init <name> --from-think [--tier notes|project] [--at <path>]`
- `--tier notes` (default) parks it on the bottom rung — cheap, hidden from cross-project retrieval, no gates yet. `--tier project` starts it as a full Forge workflow immediately for ideas you're already sure about.
- `--at <path>` chooses *where* it lives (e.g. a course folder, a lab repo, a specific Atlas subtree) so project level/location is the user's choice, not a fixed convention.
- The hand-off carries the Think context across: the scratch pages, explore results and any sketches become the project's seed (a Snapshot is created at `init`, so the project's history starts at the moment of commitment). Everything left behind in Think stays ticket-free.
- Reversible by design: `helix demote <name>` drops a project back toward `notes`, and `helix archive` retires it — so committing early is safe.

### 9.11 One project object, one `helix doctor`

The Forge/Atlas split is internal (§9.8) but leaks the moment something breaks. Users never debug two systems: `helix doctor [<project>]` runs one cross-layer diagnostic (state checkpoint, Atlas write-queue health, Snapshot integrity, broken refs, budget) and reports in plain language with a suggested fix. The user's mental model stays "one project," not "a runtime plus a wiki."

---

## 10. A complete day in the life

```
DAY 1, 9am — curiosity (Think surface, no tickets)
  $ helix think "synthetic CT for bowel length prediction"
  $ helix explore "..." --model local:qwen2.5      # one-shot: keep this scan offline/cheap
  → Runs in Think; writes to scratch only; no gates, no notifications

DAY 1, 11am — coffee line  (the queue, on mobile)
  📱 FYI: "Explore done — 12 papers, 2 strong gaps."  [ Make it a project ] [ Keep in Think ]
  → Tap "Make it a project" = $ helix init bowel-length --from-think --tier project --at ~/phd/
  → You chose the rung (project) and the location; Snapshot snap@1 created here
  → Workflow starts at Critic-Methods; autonomy = always_ask for all gates
  → $ helix model set builder local:qwen2.5-coder:32b   # code-gen stays local; critics on API

DAY 1, 4pm — first gate  (one line in NEEDS YOU NOW)
  📱 "bowel-length — approve the approach? Critic flagged 3 issues"
  → Tap → recommended option pre-selected + 3-bullet why + confidence signal
  → Low confidence on this call → expand + one-line teach-back required
     ("ODF beats single-vector because it represents two directions at crossings")
  → That sentence is logged into the decision's rationale; Snapshot snap@2 auto-created
  → Instead of killing approach-2, you also: `helix branch single-vector` (parked)

DAY 3 — maturing  (an accepted suggestion, not a command)
  📱 FYI: "'crossing-point failure' seen in 3 projects — save as reusable?" [ Save ]
  → One tap = helix promote on the concept; or `helix demote bowel-length` if it stalls
  → Either way it's a logged, Snapshotted, reversible rung change (§9.4 ladder)

WEEK 2 — the branch pays off
  Main line underperforms. You resume the parked branch:
  $ helix resume single-vector ; helix diff snap@2 snap@9   # semantic diff
  → Side-by-side results + rationale. single-vector wins on the new metric.
  → Salvage the loser's learning, don't just delete it:
  $ helix salvage bowel-length@main   # durable claims → canonical, branch parked, why logged

WEEK 4 — auto-loop + fail-closed pause
  Validator: target band [0.05] but actual 0.18 → deterministic flag plan_violation
  → Auto-routes to Planner (no gate; logged). Planner drafts revised plan.
  → gate_plan is ask_if_concerning, but a hard-rule trigger is set → it PAUSES
  → 📱 "Planner revised target to 0.10 with stratified validation. Approve?"

WEEK 5 — back after a week
  $ helix                       # the queue
  → Catch-me-up: "bowel-length, since last week: plan revised to 0.10, approved,
     Builder rebuilt, Validator clean. Now: Critic-Results waiting on you."

WEEK 8 — publishing  (accepted suggestion)
  📱 FYI: "bowel-length is publication-ready — freeze + write repro manifest?" [ Freeze ]
  → Maintainer runs full Atlas lint, writes repro manifest, freezes git tag,
     exports BibTeX, proposes final reusable-knowledge saves
```

---

## 11. Implementation stack

| Layer | Tool |
|---|---|
| Workflow runtime | **LangGraph** with custom nodes |
| Scout body | **Open Deep Research** (fork) or **FutureHouse API** |
| Critic bodies | LangGraph reflection-style nodes (custom prompts) |
| Builder body | **Claude Code** or **Deep Agents** in a sandbox |
| Validator | **LangSmith** (traces) + **MLflow** (model runs) + custom flag detectors |
| Maintainer | Custom (Atlas lint + freeze logic) |
| Watcher | Cron + arXiv/bioRxiv/PubMed feeds + ingestion subgraph |
| Forge state | LangGraph checkpointer (SQLite local, Postgres production) |
| Snapshot store | Content-addressed JSON objects (the composite-commit DAG, §7.3) |
| Code storage | git (sha referenced by the Snapshot) |
| Data/weights/outputs | Content-addressed store — DVC or git-LFS (hashes recorded in the Snapshot, §7.6) |
| Atlas storage | Per-page-versioned graph over local filesystem + git (not line-diff git) |
| Atlas search | Custom GraphRAG: BM25 + Chroma summary embeddings + adjacency traversal |
| Diagnostics | `helix doctor` — one cross-layer health check (§9.11) |
| Atlas viewer | Obsidian |
| CLI | Python (Typer or Click) |
| Mobile gates | Minimal FastAPI service + static HTML, QR-paired auth |
| PHI/IRB middleware | Approval middleware adapted from awesome-LangGraph |

### 11.1 Zero-integration default mode (makes "fork-and-go" real)

The open-source-first strategy (§13) only works if the default path has ~one dependency. So the stack above is the *full* configuration; the **default** configuration is deliberately minimal and every heavy integration is an opt-in upgrade:

| Capability | Default (zero-integration) | Opt-in upgrade |
|---|---|---|
| LLM calls | one API key *or* one local model | per-role / per-step model & provider routing (§11.2) |
| Explore body | built-in lightweight search | FutureHouse / Open Deep Research |
| Builder | local sandbox | Claude Code / Deep Agents |
| Validator tracking | local run-log file | LangSmith + MLflow |
| State / Atlas | files + git only | Postgres checkpointer |
| Gates | the `helix` queue (CLI) | mobile push + QR web view |
| Watcher | off | cron + paper feeds |

`helix setup` provisions the default in minutes (one key, a git repo, ATLAS.md) and prints which upgrades are available. The 15-minute promise (Appendix A.2) applies to this mode — the integration surface in the table above is never on the critical path to first value.

### 11.2 Model & provider routing (switch per step or globally; API-key or local)

Every agent call resolves a `provider:model` through one small registry. Providers are either **API-key-backed** (Anthropic, OpenAI, Google, OpenRouter, any OpenAI-compatible endpoint) or **local** (Ollama / vLLM / llama.cpp serving Qwen, Llama, Mistral, etc.). Nothing in the workflow hard-codes a model — agents request a *role*, the router resolves it.

**Config — `~/.helix/models.toml` (global), overridable per project and per step:**

```toml
[default]                       # used by any role not otherwise set
model = "anthropic:claude-sonnet-4.6"

[providers.anthropic]  key_env = "ANTHROPIC_API_KEY"
[providers.openai]     key_env = "OPENAI_API_KEY"
[providers.openrouter] key_env = "OPENROUTER_API_KEY"  base_url = "https://openrouter.ai/api/v1"
[providers.local]      runtime = "ollama"  endpoint = "http://localhost:11434"   # qwen, llama, …

[roles]                         # per-component overrides (Forge agents + Atlas ops)
explore         = "anthropic:claude-opus-4.6"
critic-methods  = "openai:gpt-5"
builder         = "local:qwen2.5-coder:32b"
validator       = "local:qwen2.5:7b"
maintainer      = "anthropic:claude-haiku-4.6"
atlas-embed     = "local:nomic-embed-text"
```

**Resolution order (most specific wins), so you can change one step or everything:**

```
per-step flag  >  per-project (helix model set --project)  >  role default  >  global default
   --model X        models.toml [project.<name>.roles]        [roles]            [default]
```

- **Globally:** `helix model use local:qwen2.5:32b` switches *every* role to a local model in one command (e.g. go fully offline). `helix model use anthropic:claude-sonnet-4.6` switches back.
- **Per component:** `helix model set builder local:qwen2.5-coder:32b` runs only the Builder locally (cheap/private code-gen) while critics stay on a frontier API model.
- **Per step, one-shot:** `helix explore --model openai:gpt-5` for a single run, no config change.
- `helix model list` prints the *resolved* model for every role (showing which layer won), so the effective configuration is never a mystery.

**Interactions, made explicit:**
- **Privacy (§9.9):** `privacy=strict` forces every role to a `local:` or zero-data-retention provider and *ignores* less-specific API-key settings; the substituted set is still recorded in `privacy_degraded` so the trade-off is visible.
- **Budget (§5.5):** per-role cost is computed from the resolved provider's price (local = ~0), so the enforced budget and `helix cost` stay accurate when you mix local and API models.
- **Reproducibility (§7.3):** the resolved `model_routing` is recorded in every Snapshot, so `helix repro` reruns a point with the *same* models it originally used.
- **Missing key / unreachable local endpoint:** `helix doctor` reports it in plain language; the run fails closed (pauses), it does not silently fall back to a different model.

---

## 12. Current state

### Status — nothing is built yet

**There is no code.** The working directory is empty; this document is the complete specification and the single source of truth for the design. No `research_workflow.py`, no Forge state module, and no wired bowel-length example exist. Earlier revisions of this section listed those three under "Built ✅" — that was inaccurate and is corrected here so no reader (or future contributor) is misled about where the project stands. Everything in §12 is **designed, not implemented**. Implementation order is Appendix A.1; the 15-minute first-run contract that gates the first release is Appendix A.2.

### Specified — load-bearing, implement first ⚙️
- **Snapshot composite-commit object + branches** — the keystone version-control primitive; unlocks diff/checkout/bisect/fork/continuous-repro (§7.3–7.6) *(load-bearing — keystone)*
- **Atlas write model** — single ordered writer, optimistic concurrency, derived-file re-render (§6.4.1) *(load-bearing — build first)*
- **Decision-log single-source-of-truth** — canonical JSON + deterministic narrative renderer (§7) *(load-bearing)*
- **Stable page ids + id→path index** — frontmatter uuids, link/pointer resolution (§6.2) *(cheap now, expensive later)*
- Hard-rule HITL triggers + fail-closed router (§5.3–5.4, ~40 lines)
- Trust telemetry → autonomy suggestions + auto-demotion (§5.6, ~30 lines)
- **Model & provider router** — `models.toml`, per-step/role/project/global resolution, local + API providers (§11.2) *(load-bearing — every agent call goes through it)*
- Salvage operation (§6.4); `helix doctor` cross-layer diagnostic (§9.11)
- `Atlas` class: three-tier retrieval + cold-start fallback + hub degree cap + continuous lint (§8, ~200 lines)
- Project tier + promotion-as-suggestion ops (§9.4, ~60 lines)
- ATLAS.md starter schema doc

### Specified — not yet implemented ⬜
- Zero-integration default mode + `helix setup` + the A.2 first-run contract (§11.1, Appendix A.2) — *the first thing a new user touches*
- The unified queue (`helix` no-args + mobile home, §9.1)
- Gate view: progressive disclosure + soft-commit/undo (§9.3)
- Notification triage + catch-me-up digest (§9.5–9.6)
- Explore body → built-in search; opt-in FutureHouse / Open Deep Research
- Critic-Methods + Critic-Results prompts (with structured `severity` enum)
- Builder → local sandbox; opt-in Claude Code
- Validator → local run-log + deterministic flag detectors; opt-in LangSmith/MLflow
- Watcher → scratch-only writer + diff proposals; cron + feeds
- Privacy-mode degradation + read-only no-exfil retriever (§9.9)
- Mobile gate web view + QR auth (opt-in upgrade)
- Semantic diff + `helix history/checkout/bisect/fork/repro` over Snapshots (§7.5)
- Branch compare/merge gate view (§7.4); content-addressed data store (§7.6)
- Within-project value: auto Methods/Limitations + reviewer-rebuttal drafts (§13)
- Confidence/abstention signal + teach-back capture into rationale (§9.3)
- The Think surface (§9.10); PI co-sign on high-stakes gates (§13)
- `helix think → init` hand-off with `--tier`/`--at` (§9.10); lifecycle-ladder `promote`/`demote`/`park`/`peek`/`why` CLI (§9.4, §9.7)
- Model/provider CLI: `helix model use|set|list`, `helix provider add|list`, per-step `--model` (§9.7, §11.2)
- **Loom** project-map renderer (§7.7): TTY → grayscale SVG/PDF → web; Map mode + fold ranges in v1, hooked into `helix freeze`/`fork`; Layers/Compare in v1.5
- **Prism** project-anatomy renderer (§7.8): three fixed sections + legend, TTY → SVG/PDF → web; rationale derived from the decision log; shares Loom's render scaffolding; auto-emitted into `helix freeze`/`fork`

---

## 13. Strategic context

### Market landscape

- **Autonomous AI scientists** — Sakana AI Scientist, Edison Scientific's Kosmos: too autonomous, quality issues, no human steering
- **Single-phase agents** — FutureHouse Crow/Falcon/Owl, Elicit, STORM: great at one phase each, no coordination across the lifecycle
- **Enterprise platforms** — Oracle Life Sciences, IQVIA, NVIDIA BioNeMo: pharma-grade, not for individuals

### Where Helix fits

An **orchestrator + persistent knowledge base for solo researchers**, composing best-in-class agents (FutureHouse for lit, Claude Code for build, MLflow for tracking) into the researcher's own workflow with HITL, reproducibility, and PHI/IRB awareness built in.

### Differentiation moats

- **Project-level version control** — Snapshots + research branches: *Git for whole projects*, not just code. No other research tool has a composite-commit model (§7.3–7.6)
- **Compounding researcher-owned knowledge** (Atlas) — the long-horizon retention moat
- **HITL across the full lifecycle**, with trust that calibrates itself from evidence (§5.6)
- **Decision log as a first-class, attestable research artifact** — captures *why*, not just *what*

### The value-timing problem, and the fix

The honest risk: compounding-knowledge value is **deferred** (years, many projects) while cost is **upfront** — and a grad student's horizon is ~2 years / 1–2 projects, so the moat may never mature for the headline user. The fix is to make the artifact pay off **within a single project**, so ROI lands in the first week like a git commit does:

- **Auto-drafted Methods + Limitations** generated from the decision log at freeze.
- **Pre-drafted reviewer rebuttals** — "why didn't you try X?" is already answered: the rejection reason + evidence are logged against every parked branch.
- **Continuous reproducibility** (any Snapshot, §7.5) — a same-week benefit, not an end-of-project ritual.

Sequencing: lead go-to-market with this **within-project wedge**; position the compounding Atlas as the **retention** mechanism for multi-year PIs/labs — do not sell the deferred benefit as the headline.

### Accountability as an asset, not a liability

In regulated biomedical/IRB/PHI work an "AI chose, human rubber-stamped" record is *exposure*. Helix turns this around: `auto_or_human` + the teach-back sentence + an optional **PI co-sign** on high-stakes gates make the decision log a defensible **audit/attestation trail**. Marketed to the regulated market, the log is a compliance asset — the inverse of the risk it would otherwise create. The teach-back (§9.3) doubles as the **anti-knowledge-debt** mechanism so the researcher's own expertise grows alongside the Atlas rather than atrophying behind it.

### Positioning

> *"Git for research projects, with a second brain underneath."*

The pitch leads with the moat (project-level version control, the #1 differentiation above), not the runtime. "Actions for research" describes how the pipeline works; "Git for research" is why it is defensible.

### Open-source-first strategy

Don't ship as a product. Ship as a template repo + open-source CLI. If forks and unsolicited adoption follow, then consider hosted version / SaaS. The strongest signal is researchers using it without you advocating for it.

---

## 14. The one-line distinction

Helix logs **why a research project went the way it did** — the alternatives kept alive (as resumable branches, not deleted prose), the critiques applied, the dead ends salvaged for their learning, the decisions you overruled the agents on, each one an attestable, teach-back-checked entry. And because every decision is a complete Snapshot, that *why* is not just narrated but **checkable-out and reproducible at any point** — version control for the whole project, not just the code. That is the research artifact no current tool captures, and what makes work reproducible *intellectually*, not just computationally.

---

## Appendix A: Build order & the first-run contract

### A.1 Build order

**Plumbing first — the load-bearing pieces are hard to retrofit, so they lead.**

1. **Atlas write model + stable ids** — single ordered writer, id→path index, optimistic concurrency. Everything else writes through this.
2. **Decision-log single source of truth** — canonical JSON schema (with `rationale`/`evidence`) + deterministic narrative renderer. No dual-write ever ships.
3. **Snapshot object (keystone) + branches** — composite commit binding code sha / Atlas versions / decision head / data hashes; auto-created at every HITL gate, branch op and freeze, with pure auto-routed runs coalescing into the next (§7.3 — every decision is logged, only meaningful points are Snapshotted). Branch fork/park/resume. Build before the workflow loop so every meaningful point emits a Snapshot from day one.
4. **Model & provider router** + `helix setup` + **zero-integration default mode** — `models.toml`, per-step/role/project/global resolution, local + API providers. Every agent call routes through this from day one (one key or one local model is enough to start).
5. `helix` CLI scaffold + **the unified queue** (no-args home) + **Think → `init`** hand-off + the **lifecycle-ladder** verbs (`promote`/`demote`/`park`/`peek`/`why`).
6. Explore mode (built-in search) — the front door, end-to-end, writing through the queue.
7. Atlas retriever — GraphRAG with three-tier loading + cold-start fallback + hub cap + continuous lint.
8. Patch the Forge skeleton — hard-rule autonomy triggers + fail-closed flag routing + enforced budget + trust telemetry.
9. Project workflow loop — wire LangGraph through Atlas; gate view with progressive disclosure + confidence/teach-back + soft-commit/undo; branch compare gate.
10. Version-control surface — `helix diff/history/checkout/bisect/fork/repro` over Snapshots; **Loom (project history): TTY → grayscale SVG/PDF → web (§7.7)** — Map + fold ranges v1, Layers/Compare v1.5; **Prism (project anatomy, §7.8): TTY → SVG/PDF → web** — all three sections + legend in v1, shares Loom's render scaffolding so it adds ~1× (fixed-slot layout, no placement pass), both auto-emitted into `helix freeze`/`fork`; Salvage; `helix doctor`.
11. Maintainer + promotion-as-suggestion ops; within-project value (auto Methods/Limitations + rebuttal drafts).
12. Notification triage + catch-me-up digest.
13. Watcher (scratch-only + diff proposals) — passive enrichment.
14. Opt-in upgrades — mobile/QR view + PI co-sign, FutureHouse, Claude Code, LangSmith/MLflow, content-addressed data store, privacy degradation.

### A.2 The first-run contract (the 15-minute promise)

This is the literal first fifteen minutes — the single highest-leverage stretch for "used with minimal friction, intuitively." It is a **contract**, not an aspiration: if a new user cannot get from `pip install` to a real literature-scan result in ≤ 15 minutes having made **exactly one decision**, that is a release-blocking bug, not a docs problem.

**The one decision.** `helix setup` asks for exactly one thing, phrased in plain language:

> *How should Helix run models? (1) paste an API key  (2) use a local model I already run  — you can change this anytime with `helix model`.*

Nothing else is asked. No account, no sign-up, no services, no tier vocabulary, no integration choices. If a local runtime is detected (Ollama/llama.cpp responding) option 2 is pre-selected; if `ANTHROPIC_API_KEY` (or similar) is already in the environment, option 1 is pre-filled. The common case is therefore *confirm one detected default and press enter*.

**What `helix setup` then does (no further prompts):** creates the Atlas git repo with a starter `ATLAS.md`, writes `~/.helix/models.toml` from the one answer, initializes the local state store (SQLite) and Snapshot store, and prints a short "ready / available upgrades" summary. It is idempotent and **fails closed**: if the one decision can't be satisfied (no key *and* no local runtime), it says exactly what to install or paste, changes nothing, and exits cleanly — never a half-initialized directory.

**The first screen.** `helix` with no args shows the queue — which is empty — with exactly **one** call to action, not a manual:

```
$ helix
Nothing needs you yet.
  ▸ Start exploring:   helix think "<your question>"
                       helix explore "<a literature question>"
```

**The golden path (the 15 minutes):**

| Min | Action | Result |
|---|---|---|
| 0–3 | `pip install helix` → `helix setup` | confirm one detected default; repo + config created |
| 3–4 | `helix` | empty queue + one CTA — no docs needed |
| 4–6 | `helix explore "<question>"` | a scan starts; progress shows in the queue |
| 6–15 | (scan runs) → `helix` | first result: papers + gaps, with `[ Make it a project ]` |

First value (a real literature scan with surfaced gaps) lands inside the window having typed two commands and answered one question. Becoming a project is the *next* tap (§9.10), never a prerequisite for value.

**Explicit non-goals for the first run** (each is an opt-in upgrade, §11.1, and none is on the critical path): mobile/QR view, the Watcher, FutureHouse/Claude Code/LangSmith bodies, the model-routing table, branches, Loom/Prism, privacy mode, tier names. A user who never learns any of these can still run whole projects on the §9.0 core surface.

This contract is what §11.1's "provisions the default in minutes" and every other "15-minute" reference in this document point to.

## Appendix B: Glossary

- **Anchor page** — the starting node for a graph retrieval traversal
- **Atlas write model** — the single ordered writer all agents/humans go through; gives Atlas its concurrency guarantees (§6.4.1)
- **Attestation trail** — the decision log read as a defensible audit record (`auto_or_human` + teach-back + optional PI co-sign); a compliance asset in regulated work (§13)
- **Autonomy mode** — per-gate setting controlling whether to pause for HITL
- **Bisect** — walking the decision DAG to find which decision introduced a regression (§7.5)
- **Branch (research line)** — a durable, resumable fork of a Snapshot for a parallel approach; parked, not deleted, when not chosen (§7.4)
- **Canonical** — Atlas tier for durable, cross-project knowledge
- **Catch-me-up** — generated 2–3 line per-project digest shown on re-entry after idle (§9.6)
- **Cold-start fallback** — flat embedding+BM25 retrieval used while the Atlas graph is too small to traverse usefully (§8.6)
- **Continuous reproducibility** — any Snapshot is fully reconstructable, so repro is a property of every point, not just publication (§7.5)
- **Fail-closed** — a missing/ambiguous safety signal causes a human pause, never a silent auto-approve (§5.3–5.4)
- **Fold range** — a *cosmetic* Loom collapse of a low-interest run into one node, expandable on click. **Not** a scalability mechanism: per §7.3 auto-routed steps already coalesce at the data layer so the DAG is decision-shaped before rendering. HITL decisions are never folded (§7.7.4)
- **Forge state** — runtime working memory managed by LangGraph checkpointer (internal layer name; not user-facing)
- **GraphRAG** — retrieval combining graph traversal with semantic embeddings over page summaries
- **Hard-rule trigger** — objective, non-LLM condition that forces a gate to pause (§5.3)
- **HITL** — human in the loop
- **Inverted friction** — adding decision friction where rubber-stamping is most likely (low-confidence/high-stakes), not uniformly (§9.3)
- **Lifecycle ladder** — the single ordered rung sequence (think → notes → project → published → archived) that `promote`/`demote` move along (§9.4)
- **Loom** — the canonical, **on-demand** visualization of a project's Snapshot DAG: a horizontal-lane map of branches, decisions and their bound artifacts; modes Map (default) / Layers / Compare / Bisect. Auto-emitted only at freeze/fork/re-entry, not a daily surface, not configured; rendered, never stored (§7.7)
- **Loom contract** — the fixed, enumerated visual-encoding rules the renderer enforces (direction, color = status only with a redundant status glyph, shape, connector, opacity, recency ring, fold); grayscale- and no-color-legible; not user-styleable (§7.7.4)
- **Loom cursor** — the per-viewer `last_viewed_snapshot` pointer driving the recency ring; pure view state, never in a Snapshot, the log, or a fork bundle (§7.7.5)
- **Model routing** — resolving each role to a `provider:model`; most-specific of per-step / project / role / global wins (§11.2)
- **Park** — pause a project or research line while retaining its Snapshot so it is resumable (§9.7)
- **Prism** — the canonical, **on-demand** one-page *anatomy* of a project: three fixed sections (strategy · data · code) with decision-log-derived rationale; complementary to Loom. Auto-emitted only at freeze/fork/re-entry, not a daily surface; rendered, never stored; no new source of truth (§7.8)
- **Prism shape vocabulary** — the universal four-shape grammar: rounded rect = strategic, plain rect = code, cylinder = data, dashed box = cluster (§7.8.2)
- **Organization principle** — Prism's code-section rationale (why the code is structured as it is); the *project-structure decision's* `rationale`, not a separately authored field (§7.8.4)
- **Rationale annotation** — any of Prism's standardized "why" elements (methods / per-stage / organization); all derived from decision-log `rationale`; never blank — empty renders an FYI hint (§7.8.4)
- **Provider** — a model backend: API-key-backed (Anthropic/OpenAI/…) or local (Ollama/vLLM serving Qwen, Llama, …) (§11.2)
- **Provenance marker** — inline `^src:`/`^dec:` tag recording which source/decision introduced a claim; lets lint find stale claims (§6.2)
- **Promotion** — operation that moves a page/concept across Atlas tiers; surfaced to users as an accepted suggestion (§9.4)
- **Queue** — the single prioritised list of everything needing the user; the default surface for *commitments* (§9.1)
- **Salvage** — at a dead-end, extract durable learning to canonical + park the branch + log why it died (§6.4)
- **Sanity flag** — structured signal output by Validator that drives auto-routing
- **Scratch** — Atlas tier for ephemeral/exploratory work
- **Semantic diff** — structured diff of Snapshots (claims, metrics, candidate set, plan), not markdown line-noise (§7.5)
- **Snapshot** — content-addressed composite commit binding code sha + Atlas page versions + decision head + data hashes + env; the keystone version-control primitive (§7.3)
- **Soft-commit window** — short undo period after approving a gate before anything irreversible runs (§9.3)
- **Stable id** — frontmatter uuid that is a page's real identity; paths/links are derived so moves never break references (§6.2)
- **Teach-back** — one-sentence "why this is right" required on low-confidence/high-stakes gates; anti-knowledge-debt, logged into rationale (§9.3)
- **Think surface** — the deliberately non-queue exploration space that produces no tickets/notifications; home for curiosity (§9.10)
- **Tier** — status level of a page or project: scratch / active / canonical / published / archived
- **Trust telemetry** — per-gate agreement history that drives data-driven autonomy suggestions and auto-demotion (§5.6)
- **Watcher** — async background agent that scans for new relevant papers; writes only to scratch + diff proposals
- **Within-project value** — making the decision-log artifact pay off in one project (auto Methods/rebuttals, continuous repro), not only over years (§13)
- **Zero-integration default mode** — the minimal one-dependency configuration `helix setup` provisions; heavy integrations are opt-in (§11.1)
