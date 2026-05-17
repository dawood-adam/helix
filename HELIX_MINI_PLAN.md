# Helix Mini — Plan

A minimal implementation of Forge + Atlas that achieves the core goal: **run a research pipeline over input folders, capture every decision, and build a persistent LLM wiki that compounds across projects.**

---

## Core Concept

You point helix-mini at one or more folders of source material. For each folder, Scout ingests the files, the Forge pipeline runs (identifying approaches, critiquing, planning, building, validating), and every agent reads from and writes to a shared **Atlas** — an LLM-maintained wiki of markdown pages that accumulates knowledge across all projects.

```
helix-mini run ./papers/cardiac ./papers/genomics --lightspeed
```

Two folders = two parallel Forge pipelines, both reading from and writing to the same Atlas.

---

## Atlas — The LLM Wiki (minimal, scalable)

Atlas is the LLM Wiki pattern reduced to its simplest viable form:

### Three layers

```
~/.helix-mini/
├── atlas/                    # THE WIKI (LLM-written, human-readable)
│   ├── index.md              # Catalog of all pages + one-line summaries
│   ├── log.md                # Append-only: what happened and when
│   ├── sources/              # One summary page per ingested source file
│   ├── concepts/             # Cross-cutting ideas, methods, themes
│   ├── entities/             # People, datasets, tools, orgs
│   └── projects/             # One page per Forge project run
├── raw/                      # IMMUTABLE SOURCES (copies/symlinks of input files)
└── config.toml               # Model config + API key env var name
```

### How it works

- **`index.md`** — The LLM reads this first to find relevant pages. A flat list: `- [Page Title](path) — one-line summary`. Updated on every write. At moderate scale (~hundreds of pages), this is sufficient for navigation without embeddings or vector search.

- **`log.md`** — Append-only chronological record. Each entry: `## [2026-05-17] ingest | filename.pdf` or `## [2026-05-17] scout | project-name`. Gives the LLM temporal context.

- **`sources/`** — One markdown page per raw source file. Created during Scout's ingest. Contains: title, key claims, methods used, relevance to research question, cross-references to concept/entity pages.

- **`concepts/`** — Emerge organically. When Scout or any agent identifies a concept mentioned across multiple sources, it gets its own page. Updated by subsequent agents as understanding deepens.

- **`entities/`** — Datasets, tools, authors, organizations that appear across sources. Simple factual pages with back-references.

- **`projects/`** — One page per Forge run. Updated at each gate with the decision rationale, chosen approach, plan, results.

### Atlas operations (what agents do)

Each Forge agent gets two Atlas primitives:

```python
class Atlas:
    def read(self, query: str) -> List[Page]:
        """Read index.md, find relevant pages, return their content."""

    def write(self, writes: List[PageWrite]) -> None:
        """Create/update pages, update index.md, append to log.md."""
```

That's the entire API. `read` is "scan index, read matching pages." `write` is "upsert pages + maintain index + append log." No embedding DB, no vector search, no special infrastructure. Just markdown files and an index.

### Scalability path (built in, not built yet)

The design scales without architectural changes:
- **Small** (~50 pages): index.md scanning is instant
- **Medium** (~500 pages): add a simple grep/ripgrep search over wiki files
- **Large** (~5000+ pages): plug in a search tool (qmd, embeddings, whatever) behind the same `Atlas.read()` interface

The interface stays the same; only the retrieval implementation changes.

---

## Input: Folders as Projects

### How Scout ingests a folder

```
helix-mini run ./my-research-folder --lightspeed
```

1. Recursively read all files in the folder (`.md`, `.txt`, `.pdf`, `.py`, `.json`, etc.)
2. Copy/symlink originals into `raw/` (immutable archive)
3. For each file, create a source summary page in `atlas/sources/`
4. Cross-reference: update concept/entity pages that emerge from the sources
5. Update `index.md` and `log.md`
6. Use the synthesized knowledge to identify candidate approaches

Scout's LLM call gets the file contents (or summaries of large files) as context, plus any existing relevant Atlas pages. It outputs: candidate approaches + Atlas writes (source pages, new concepts).

### Multiple folders = parallel projects

```
helix-mini run ./folder-a ./folder-b ./folder-c --lightspeed
```

Each folder becomes an independent Forge pipeline. They run in parallel (`asyncio.gather` or `concurrent.futures`). All pipelines share the same Atlas — so if folder-b's Scout finds a concept that folder-a already wrote about, it reads and builds on that page rather than starting from scratch.

Atlas writes are serialized with a simple file lock (single-process `threading.Lock`) to prevent clobbering. Reads are lock-free.

---

## Architecture

```
helix-mini/
├── pyproject.toml
├── src/
│   └── helix_mini/
│       ├── __init__.py
│       ├── app.py            # Wiring: Atlas + config + parallel runner
│       ├── atlas.py          # Atlas read/write (index.md, log.md, pages)
│       ├── state.py          # ForgeState dataclass
│       ├── workflow.py       # LangGraph 7-node pipeline
│       ├── router.py         # Gate decision + sanity routing (pure rules)
│       ├── agents.py         # LLM-backed agent bodies (read/write Atlas)
│       ├── llm.py            # Thin LLM call wrapper (litellm or httpx)
│       ├── models.py         # Model config + provider resolution
│       ├── decisions.py      # Decision log (JSON + markdown render)
│       ├── snapshots.py      # Lightweight snapshot store
│       └── cli.py            # CLI commands
├── tests/
│   ├── conftest.py
│   ├── test_workflow.py
│   ├── test_atlas.py
│   └── test_lightspeed.py
└── README.md
```

**~13 source files, ~1800 lines estimated.**

---

## The Two Modes

### 1. Normal Mode (default)
- Gates set to `always_ask` — CLI pauses at each gate for human review
- Uses whatever model you configured
- You review Scout's ingest, pick an approach, approve the plan, etc.

### 2. Lightspeed Mode (`--lightspeed`)
- All gates set to `auto` — only pauses on BLOCKING critiques
- Uses the cheapest/fastest model (e.g. haiku, gpt-4o-mini)
- Runs the entire Forge pipeline start-to-finish with no human interaction
- Still writes to Atlas, still logs every decision, still mints snapshots
- ~7 LLM calls per project, ~$0.01-0.05, ~30-60s wall clock

---

## Detailed Design

### `atlas.py` — The LLM Wiki

```python
from pathlib import Path
from dataclasses import dataclass
import threading

@dataclass
class Page:
    path: str           # relative to atlas root, e.g. "concepts/variational-inference.md"
    title: str
    content: str

@dataclass
class PageWrite:
    path: str           # where to write (creates if new, overwrites if exists)
    title: str
    content: str        # full markdown body
    summary: str        # one-line for index.md

class Atlas:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()
        self._ensure_structure()

    def _ensure_structure(self):
        for d in ("sources", "concepts", "entities", "projects"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        if not (self.root / "index.md").exists():
            (self.root / "index.md").write_text("# Atlas Index\n")
        if not (self.root / "log.md").exists():
            (self.root / "log.md").write_text("# Atlas Log\n")

    def read(self, query: str, limit: int = 20) -> List[Page]:
        """Read index.md, find pages whose title/summary matches query keywords,
        return their full content. Simple substring/keyword match."""
        index = (self.root / "index.md").read_text()
        # Parse index lines, match query keywords, read matching files
        ...

    def read_all_summaries(self) -> str:
        """Return the full index.md content (for LLM context)."""
        return (self.root / "index.md").read_text()

    def write(self, writes: List[PageWrite], log_entry: str) -> None:
        """Atomic batch: write pages, update index, append log."""
        with self._lock:
            for w in writes:
                path = self.root / w.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# {w.title}\n\n{w.content}")
            self._update_index(writes)
            self._append_log(log_entry)

    def _update_index(self, writes: List[PageWrite]):
        """Add/update entries in index.md."""
        ...

    def _append_log(self, entry: str):
        """Append timestamped entry to log.md."""
        ...

    def ingest_folder(self, folder: Path) -> List[Page]:
        """Read all files from a folder, return as Page objects for LLM processing.
        Copy originals to raw/. Returns content ready to feed to Scout."""
        ...
```

### `state.py` — ForgeState

```python
@dataclass
class ForgeState:
    project_name: str = ""
    research_question: str = ""
    input_folder: str = ""            # path to source folder

    # HITL
    autonomy: Dict[str, str] = field(default_factory=dict)

    # Agent working data
    source_content: List[Dict] = field(default_factory=list)  # ingested file summaries
    candidate_approaches: List[Dict] = field(default_factory=list)
    chosen_approach_id: Optional[str] = None
    project_plan: Dict[str, Any] = field(default_factory=dict)
    code_artifacts: List[Dict] = field(default_factory=list)
    experiment_results: List[Dict] = field(default_factory=list)

    # Routing
    sanity_check_flags: Optional[List[str]] = None
    critiques: List[Dict] = field(default_factory=list)
    next_action: str = ""

    # Budget
    cost_so_far: float = 0.0
    cost_cap: float = 5.0
```

### `agents.py` — LLM Agents That Read/Write Atlas

Each agent: reads relevant Atlas pages as context, makes one LLM call, writes results back to Atlas.

```python
class LLMAgents:
    def __init__(self, llm, atlas: Atlas):
        self.llm = llm
        self.atlas = atlas

    def scout(self, state: ForgeState) -> Dict:
        # 1. Ingest: read raw files from input_folder
        sources = self.atlas.ingest_folder(Path(state.input_folder))

        # 2. Get existing Atlas context (what do we already know?)
        existing = self.atlas.read_all_summaries()

        # 3. One LLM call: "Given these sources + existing knowledge,
        #    identify 2-3 candidate research approaches.
        #    Also output: source summary pages, any new concepts/entities."
        resp = self.llm(
            system="You are a research scout. Ingest these sources, "
                   "identify candidate approaches, and output wiki updates.",
            user=f"## Existing Atlas\n{existing}\n\n"
                 f"## New Sources\n{_format_sources(sources)}\n\n"
                 f"Research question: {state.research_question}",
            schema=ScoutOutput  # structured: approaches + atlas_writes
        )

        # 4. Write to Atlas
        self.atlas.write(resp.atlas_writes,
                         f"[{now()}] scout | {state.project_name}")

        return {"candidate_approaches": resp.approaches,
                "source_content": resp.source_summaries}

    def critic_methods(self, state) -> Dict:
        # Read relevant concept pages from Atlas
        context = self.atlas.read(state.chosen_approach_id or "methods")

        resp = self.llm(
            system="Evaluate these candidate approaches for feasibility...",
            user=f"## Atlas Context\n{_format_pages(context)}\n\n"
                 f"## Candidates\n{json.dumps(state.candidate_approaches)}",
            schema=CriticOutput
        )

        # Write critique findings back to Atlas (update concept pages, etc.)
        if resp.atlas_writes:
            self.atlas.write(resp.atlas_writes,
                             f"[{now()}] critic-methods | {state.project_name}")
        return {"critiques": resp.critiques}

    def planner(self, state) -> Dict:
        context = self.atlas.read(state.chosen_approach_id or "plan")
        # ... one LLM call, writes plan page to atlas/projects/
        ...

    def builder(self, state) -> Dict:
        context = self.atlas.read("implementation " + state.project_name)
        # ... one LLM call, writes code, updates project page
        ...

    def validator(self, state) -> Dict:
        # Deterministic: check results against plan bands
        # No LLM call needed (same as full Helix)
        ...

    def critic_results(self, state) -> Dict:
        context = self.atlas.read("results " + state.project_name)
        # ... one LLM call, updates project page with findings
        ...
```

**Pattern**: Every agent does `Atlas.read → LLM call → Atlas.write`. The wiki grows with every stage.

### `llm.py` — Thin Wrapper

```python
def call_llm(*, model: str, system: str, user: str,
             provider: str, api_key: str, schema=None) -> Any:
    """One LLM call. If schema provided, parse structured JSON output."""
    ...
```

Use `litellm` for provider routing, or raw `httpx` for zero-dep.

### `models.py` — Config

```toml
# ~/.helix-mini/config.toml
[default]
model = "anthropic:claude-sonnet-4-20250514"

[lightspeed]
model = "anthropic:claude-haiku-4-5-20251001"
```

API key from env var. That's it.

### `workflow.py` — Pipeline + Parallel Runner

```python
# Per-project pipeline (same as before)
# START → scout → gate_scope → critic_methods → gate_methods → planner
#       → gate_plan → builder → gate_build → validator → sanity_route
#       → critic_results → gate_results → done

# Parallel runner for multiple folders
async def run_parallel(folders: List[Path], atlas: Atlas, lightspeed: bool):
    tasks = [run_project(folder, atlas, lightspeed) for folder in folders]
    await asyncio.gather(*tasks)
```

### `router.py` — Gate Logic

Identical to full Helix. Pure, simple, ~80 lines. gate_decision + sanity_route.

### `decisions.py` — Decision Log

Per-project, stored in `atlas/projects/<name>/.decisions.json` + rendered narrative.

### `cli.py` — Commands

```
helix-mini run <folder> [<folder>...] [--lightspeed]   # Run forge on folder(s)
helix-mini status                                       # Show running/pending projects
helix-mini log <project>                                # Print decision log
helix-mini atlas search <query>                         # Search the wiki
helix-mini setup                                        # Configure model + API key
```

---

## What Happens End-to-End

```bash
$ helix-mini run ./cardiac-papers --lightspeed
```

1. **Scout** reads all files in `./cardiac-papers/` (PDFs, markdown, whatever)
2. Scout creates `atlas/sources/paper-1.md`, `atlas/sources/paper-2.md`, ...
3. Scout identifies concepts → creates `atlas/concepts/cardiac-modeling.md`, etc.
4. Scout proposes 3 candidate approaches
5. **gate_scope** auto-approves (lightspeed)
6. **Critic-Methods** reads relevant Atlas pages, evaluates approaches
7. **gate_methods** auto-picks best approach
8. **Planner** reads Atlas, designs validation plan, writes `atlas/projects/cardiac/plan.md`
9. **gate_plan** auto-approves
10. **Builder** writes code scaffold, updates project page
11. **gate_build** auto-approves
12. **Validator** checks results against plan
13. **Critic-Results** evaluates, updates Atlas with findings
14. **gate_results** ships
15. Done. Atlas is richer. Decision log is complete.

### Output structure

```
~/.helix-mini/
├── atlas/
│   ├── index.md                          # Updated with all new pages
│   ├── log.md                            # 15+ entries from this run
│   ├── sources/
│   │   ├── chen-2024-cardiac-sim.md      # Summary of each input file
│   │   ├── wang-2025-fluid-dynamics.md
│   │   └── ...
│   ├── concepts/
│   │   ├── cardiac-modeling.md           # Emerged from multiple sources
│   │   ├── fluid-structure-interaction.md
│   │   └── ...
│   ├── entities/
│   │   ├── openfoam.md                   # Tool mentioned across papers
│   │   └── ...
│   └── projects/
│       └── cardiac-papers/
│           ├── overview.md               # Project page (updated each stage)
│           ├── plan.md                   # Validation plan
│           ├── .decisions.json           # Structured decision log
│           ├── decisions.md              # Rendered narrative
│           └── .snapshots/
│               └── snap-1.json ... snap-5.json
├── raw/
│   ├── cardiac-papers/                   # Immutable copies of input files
│   │   ├── chen-2024.pdf
│   │   └── ...
└── config.toml
```

---

## Parallel Example

```bash
$ helix-mini run ./cardiac ./genomics ./neuro --lightspeed
```

Three Forge pipelines run concurrently. They share the Atlas:
- If genomics Scout finds a concept that cardiac already wrote, it reads and extends that page
- Cross-project links emerge naturally ("cardiac-modeling" page gets a "see also: genomics" reference)
- Atlas grows richer from the overlap

Writes are serialized (threading.Lock). Reads are concurrent. Simple and correct.

---

## Dependencies

```toml
[project]
name = "helix-mini"
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.2",
    "litellm>=1.0",
    "click>=8.0",
]

[project.optional-dependencies]
pdf = ["pymupdf>=1.24"]   # for PDF ingestion
```

Three core deps. PDF support optional.

---

## Build Order

1. **`atlas.py`** — Read/write/index/log (filesystem only, no LLM)
2. **`state.py`** — ForgeState dataclass
3. **`router.py`** — gate_decision + sanity_route (pure logic)
4. **`decisions.py`** — Decision log append + render
5. **`snapshots.py`** — Snapshot mint
6. **`llm.py`** — LLM call wrapper
7. **`models.py`** — Config loading
8. **`agents.py`** — 6 agent bodies (each = Atlas.read → LLM → Atlas.write)
9. **`workflow.py`** — LangGraph pipeline + parallel folder runner
10. **`app.py`** — Facade wiring
11. **`cli.py`** — Commands
12. **Tests** — with fake LLM responses + real Atlas filesystem ops

---

## Design Principles

1. **Atlas is just markdown files + an index** — no DB, no embeddings, no infrastructure. Scales later by swapping the read implementation.
2. **Every agent reads from and writes to Atlas** — the wiki compounds with every stage of every project.
3. **Folders are the input interface** — drop files in a folder, point helix-mini at it.
4. **Parallel projects share one Atlas** — cross-project knowledge emerges naturally.
5. **One LLM call per stage** — fast, auditable, cheap.
6. **Lightspeed = same pipeline, cheapest model, auto-gates** — not a different code path.
7. **No web access except LLM API** — all knowledge comes from your input files.
8. **No fake success** — if the LLM fails, the pipeline pauses.
