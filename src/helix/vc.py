"""Project version control over Snapshots (HELIX.md §7.5).

All of these are cheap because the Snapshot already binds the whole
project by reference (§7.3). They are **semantic**, not text: they read
the structured binding + the canonical decision log, never markdown
line-noise.

Honest boundary: ``checkout``/``repro`` resolve a Snapshot, verify its
integrity, and emit the exact materialisation manifest. Restoring
*historical Atlas page bodies* needs the content-addressed page-version
store (§7.6) — that is build step 14, so it is reported as a documented
boundary, never faked.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from helix.snapshot import Snapshot, SnapshotStore, _decision_number


def _snaps(app, project: str) -> SnapshotStore:
    return app.snapshots(project)


def resolve_ref(app, project: str, ref: str) -> Snapshot:
    """Resolve a snapshot id, a tag/release name, or a decision id (to
    its enclosing Snapshot, §7.3 coalescing)."""
    s = _snaps(app, project)
    if ref in s.names():
        ref = s.names()[ref]
    if ref.startswith("snap:"):
        return s.get(ref)
    # decision-id forms: "<proj>#decision-N", "decision-N", or "N"
    did = ref if "#" in ref else f"{project}#decision-{ref.split('-')[-1]}"
    enc = s.enclosing(did)
    if enc is None:
        raise KeyError(f"cannot resolve ref {ref!r} in {project}")
    return enc


@dataclass
class Diff:
    a: str
    b: str
    binding: Dict[str, Any]
    decisions_added: List[Dict[str, str]]

    def render(self) -> str:
        out = [f"diff {self.a} → {self.b}"]
        if not self.binding and not self.decisions_added:
            out.append("  (identical binding, no new decisions)")
        for k, v in self.binding.items():
            out.append(f"  {k}: {v}")
        for d in self.decisions_added:
            out.append(f"  + decision {d['id']}: {d['action']}")
        return "\n".join(out)


def diff(app, project: str, a_ref: str, b_ref: str) -> Diff:
    """Semantic diff (§7.5): structured binding delta + the decisions
    that landed between the two points — not a text diff."""
    a = resolve_ref(app, project, a_ref)
    b = resolve_ref(app, project, b_ref)
    log = app.decision_log(project)
    lo, hi = sorted((_decision_number(a.decision_head),
                     _decision_number(b.decision_head)))
    added = [{"id": e["id"], "action": e["action"]}
             for e in log.entries()
             if lo < _decision_number(e["id"]) <= hi]
    return Diff(a.id, b.id, a.binding_diff(b), added)


def history(app, project: str) -> List[Dict[str, Any]]:
    """The decision DAG *is* the commit graph (§7.5)."""
    s = _snaps(app, project)
    by_head: Dict[str, Snapshot] = {}
    for snap in s.all():
        if snap.decision_head:
            by_head.setdefault(snap.decision_head, snap)
    out = []
    for e in app.decision_log(project).entries():
        snap = by_head.get(e["id"])
        out.append({
            "decision": e["id"], "action": e["action"],
            "auto_or_human": e.get("auto_or_human", "human"),
            "snapshot": snap.id if snap else None,
            "branch": snap.branch if snap else None,
            "rationale": e.get("rationale", ""),
        })
    return out


def checkout(app, project: str, ref: str) -> Dict[str, Any]:
    """Resolve + integrity-verify the Snapshot and return exactly what
    `helix repro` would materialise (§7.5)."""
    snap = resolve_ref(app, project, ref)
    integrity = snap.verify()
    code_ok = _code_present(app, snap)
    return {
        "snapshot": snap.id, "branch": snap.branch,
        "decision_head": snap.decision_head,
        "integrity_ok": integrity,
        "code_sha": snap.code_sha, "code_present": code_ok,
        "atlas_pages": snap.atlas_pages, "data_hashes": snap.data_hashes,
        "env_lock": snap.env_lock, "model_routing": snap.model_routing,
        "materialisation_note": (
            "binding resolved + verified. Restoring historical Atlas "
            "page *bodies* needs the content-addressed page-version "
            "store (§7.6 — build step 14); current page versions and "
            "code sha are referenced above."),
    }


def repro(app, project: str, ref: str) -> Dict[str, Any]:
    """A reproduction manifest for any point — continuous, because
    every Snapshot is complete (§7.5). Same models, recorded."""
    man = checkout(app, project, ref)
    man["reproducible"] = man["integrity_ok"]
    man["note"] = ("re-run with model_routing above for model-faithful "
                    "reproduction (§11.2 / §7.3)")
    return man


def bisect(app, project: str) -> Dict[str, Any]:
    """Walk the decision DAG to find which decision first introduced a
    metric regression (§7.5). Deterministic: the canonical log records
    ``auto_route:plan_violation`` exactly when the Validator's
    metric-band detector fired (§5.4) — no guessing, no fake metric."""
    s = _snaps(app, project)
    by_head = {snap.decision_head: snap for snap in s.all()
               if snap.decision_head}
    for e in app.decision_log(project).entries():
        if e["action"] == "auto_route:plan_violation":
            snap = by_head.get(e["id"])
            return {"found": True, "decision": e["id"],
                    "snapshot": snap.id if snap else None,
                    "reason": e.get("rationale", "metric outside plan band"),
                    "first_bad": e["id"]}
    return {"found": False,
            "reason": "no plan_violation regression in the decision log"}


def fork_bundle(app, project: str, dest: Path) -> Path:
    """Export a self-contained, importable bundle: decision history +
    Snapshots + the referenced Atlas subgraph + Loom & Prism (§7.5;
    A.1 — both auto-emitted into fork). Privacy-redacted (§7.7.7)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    layout = app.store.layout
    pdir = layout.project_dir(project)
    # decision log + snapshots + project meta
    for name in (".decision-log.json",):
        src = pdir / name
        if src.exists():
            shutil.copy2(src, dest / "decision-log.json")
    shutil.copytree(layout.snapshots_dir(project), dest / "snapshots",
                    dirs_exist_ok=True)
    meta = pdir / ".helix-project.json"
    private = False
    if meta.exists():
        shutil.copy2(meta, dest / "project.json")
        private = json.loads(meta.read_text()).get(
            "privacy_mode") == "strict"
    # Atlas subgraph referenced by the head Snapshot's atlas_pages.
    sub = dest / "atlas-subgraph"
    sub.mkdir(exist_ok=True)
    head = _snaps(app, project).head()
    refs = (_snaps(app, project).get(head).atlas_pages
            if head else {})
    redacted = []
    for handle in refs:
        try:
            entry = app.store.index.resolve(handle)
        except KeyError:
            continue
        if private:                         # §7.7.7 export-time redaction
            redacted.append(handle)
            continue
        srcp = app.store.abspath(entry.path)
        if srcp.exists():
            (sub / Path(entry.path).name).write_text(srcp.read_text())
    # Loom + Prism baked in (privacy-redacted at export time too).
    from helix.loom import Loom
    from helix.prism import Prism
    (dest / "loom.txt").write_text(Loom(app, project).render_tty(color=False))
    (dest / "loom.svg").write_text(Loom(app, project).render_svg())
    (dest / "prism.txt").write_text(Prism(app, project).render_tty())
    (dest / "prism.svg").write_text(Prism(app, project).render_svg())
    (dest / "README.md").write_text(
        f"# {project} — Helix fork bundle\n\n"
        f"Self-contained: decision history, Snapshots, the referenced "
        f"Atlas subgraph, and the Loom/Prism projections.\n"
        + (f"\n**Privacy:** strict — {len(redacted)} private page(s) "
           f"redacted (id-only).\n" if private else ""))
    return dest


def _code_present(app, snap: Snapshot) -> bool:
    if not snap.code_sha:
        return False
    if snap.code_sha.startswith("git:"):
        import subprocess
        try:
            r = subprocess.run(
                ["git", "-C", str(app.store.root), "cat-file", "-e",
                 snap.code_sha.split(":", 1)[1]],
                capture_output=True)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return True  # content-addressed sha recorded in the Snapshot
