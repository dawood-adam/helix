# Reference — Application facade (`src/helix/app.py`)

The single wiring path (§9.11). Construct one `Helix` per process (the
CLI does this once per invocation); it builds and shares every store
and threads the process-global write lock through `DecisionLog` /
`SnapshotStore` / `ProjectStore`. Library integrators use this class as
the entry point — do not instantiate subsystem stores directly.

## `default_home() -> pathlib.Path`

Returns `$HELIX_HOME` if set, else `~/.helix`. Used as the `Helix`
default home. Example: `from helix.app import default_home`.

## `class Helix(home: str | Path | None = None)`

**Constructor.** `home=None` → `default_home()`. On construction it:
loads `config.json` (if present), resolves `atlas_root`
(`config["atlas_root"]` or `<home>/atlas`), builds `AtlasStore`,
`WriteQueue`, `Router`, `ProjectStore`, `ExploreStore`, `Retriever`,
`Linter`, and registers continuous incremental lint as the write
queue's `on_applied` hook. No exceptions for a fresh/empty home (it is
usable before `helix setup`; `is_set_up` is then `False`).

### Attributes (public)

| Attribute | Type | Meaning |
|---|---|---|
| `home` | `Path` | State root. |
| `config_path` | `Path` | `<home>/config.json`. |
| `models_path` | `Path` | `<home>/models.toml`. |
| `atlas_root` | `Path` | Atlas tree root. |
| `store` | `AtlasStore` | Filesystem layout + page IO + id index. |
| `wq` | `WriteQueue` | The one ordered writer (owns the process-global lock). |
| `router` | `Router` | `models.toml` resolver (§11.2). |
| `projects` | `ProjectStore` | Project meta + lifecycle ladder. |
| `explore_store` | `ExploreStore` | Persisted explore results. |
| `retriever` | `Retriever` | GraphRAG retrieval. |
| `linter` | `Linter` | Atlas lint. |
| `last_lint` | `list` | Findings from the most recent incremental lint (best-effort). |

### Methods & properties

#### `workflow() -> WorkflowEngine`
Returns a Forge `WorkflowEngine`. Agent bodies: `BuiltinAgents` by
default, `FakeAgents` when `HELIX_AGENTS=fake` (offline/deterministic).
Example: `app.workflow().start("bowel-length")`.

#### `explorer() -> Explorer`
Returns an `Explorer`. Backend: real `ArxivBackend` by default;
`HELIX_EXPLORE_BACKEND=fake` selects the deterministic offline backend;
other values map via `helix.explore.make_backend`. Example:
`app.explorer().run("centerline tracing", limit=5)`.

#### `decision_log(project: str) -> DecisionLog`
A `DecisionLog` for `project`, bound to the shared `wq.lock` (so
canonical-state writes serialize across threads and processes).

#### `snapshots(project: str) -> SnapshotStore`
A `SnapshotStore` for `project`, constructed with `lock=self.wq.lock`
(keystone DAG is race-free in the running app).

#### `config_get(key) -> Any` / `config_set(key, value) -> None`
Read / write a single config key. `config_set` persists `config.json`
atomically (creates `home` if needed).

#### `save_config() -> None`
Atomically writes the current in-memory config to `config.json`.

#### `config` *(property) -> dict*
A copy of the current config mapping.

#### `is_set_up` *(property) -> bool*
`True` once `models.toml` exists (i.e. `helix setup` has run).

### Minimal example

```python
import os
os.environ["HELIX_HOME"] = "/tmp/h"
os.environ["HELIX_AGENTS"] = "fake"          # offline
from helix.app import Helix

app = Helix()                                # wires everything
app.projects.create("demo")                  # init decision + Snapshot@1
eng = app.workflow()
print(eng.start("demo")["status"])           # 'interrupted' (gate) or 'done'
print(app.is_set_up)                         # False until `helix setup`
```

### Errors

The constructor does not raise on a missing/empty home. Subsystem
methods raise their own documented errors (e.g. `Router` raises
`RoutingError` on unresolvable routing; `ProjectStore.create` raises
`LadderError` on a duplicate). Malformed `config.json` will raise
`json.JSONDecodeError` at construction (it is read eagerly).
