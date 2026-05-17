import json

import pytest

from helix.doctor import Doctor
from helix.forge.agents import FakeAgents
from helix.forge.state import GATES
from helix.forge.workflow import WorkflowEngine
from helix.salvage import Salvager


def _run(app, project="bl"):
    app.projects.create(project)
    WorkflowEngine(app, FakeAgents()).start(
        project, autonomy={g: "auto" for g in GATES})
    return project


# ---- Salvage (§6.4) -----------------------------------------------


def test_salvage_keeps_learning_and_parks(helix_app):
    p = _run(helix_app)
    helix_app.snapshots(p).fork("single-vector", decision_head=None)
    r = Salvager(helix_app).salvage(p, "single-vector",
                                    reason="underperformed on the metric")
    snaps = helix_app.snapshots(p)
    assert snaps.is_parked("single-vector")
    assert snaps.is_salvaged("single-vector")
    page, _ = helix_app.store.read_page(r.canonical_handle)
    assert page.status == "canonical"
    assert "^dec:" in page.body                 # provenance-tagged (§6.2)
    assert "underperformed" in page.body        # death reason logged
    actions = [e["action"]
               for e in helix_app.decision_log(p).entries()]
    assert "salvage" in actions


def test_salvage_unknown_branch_errors(helix_app):
    _run(helix_app, "bl")
    with pytest.raises(ValueError):
        Salvager(helix_app).salvage("bl", "ghost")


def test_salvage_is_idempotent(helix_app):
    p = _run(helix_app)
    helix_app.snapshots(p).fork("alt", decision_head=None)
    Salvager(helix_app).salvage(p, "alt")
    r2 = Salvager(helix_app).salvage(p, "alt", reason="still dead")
    assert "still dead" in helix_app.store.read_page(
        r2.canonical_handle)[0].body


# ---- Doctor (§9.11) -----------------------------------------------


def test_doctor_all_clear_on_healthy_project(helix_app):
    p = _run(helix_app)
    checks = Doctor(helix_app).run(p)
    integ = [c for c in checks if c.area.endswith("snapshot-integrity")]
    assert integ and integ[0].ok
    assert any(c.area == "atlas-index" and c.ok for c in checks)


def test_doctor_detects_corrupt_snapshot(helix_app):
    p = _run(helix_app)
    sdir = helix_app.store.layout.snapshots_dir(p)
    f = next(x for x in sdir.glob("*.json") if x.name != "refs.json")
    data = json.loads(f.read_text())
    data["code_sha"] = "git:TAMPERED"           # break the content hash
    f.write_text(json.dumps(data))
    checks = Doctor(helix_app).run(p)
    integ = next(c for c in checks
                 if c.area.endswith("snapshot-integrity"))
    assert integ.ok is False and integ.fix


def test_doctor_flags_missing_prism_rationale(helix_app):
    helix_app.projects.create("bare")           # no decisions
    checks = Doctor(helix_app).run("bare")
    pr = next(c for c in checks if c.area.endswith("prism-rationale"))
    assert pr.ok is False
