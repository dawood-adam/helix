from pathlib import Path

import pytest

from helix import vc
from helix.forge.agents import FakeAgents
from helix.forge.state import GATES
from helix.forge.workflow import WorkflowEngine


def _run(app, project="bl", **fake):
    app.projects.create(project)
    eng = WorkflowEngine(app, FakeAgents(**fake))
    eng.start(project, autonomy={g: "auto" for g in GATES})
    return project


def test_history_is_the_commit_graph(helix_app):
    p = _run(helix_app)
    rows = vc.history(helix_app, p)
    assert rows and any(r["action"].startswith("pick:") for r in rows)
    assert all("decision" in r and "snapshot" in r for r in rows)


def test_resolve_ref_forms_and_diff(helix_app):
    p = _run(helix_app)
    s = helix_app.snapshots(p)
    a, b = s.all()[0].id, s.all()[-1].id
    s.name("v1", a)
    assert vc.resolve_ref(helix_app, p, "v1").id == a       # tag/release
    assert vc.resolve_ref(helix_app, p, b).id == b          # snap id
    assert vc.resolve_ref(helix_app, p, f"{p}#decision-1")  # decision id
    d = vc.diff(helix_app, p, a, b)
    assert d.a == a and d.b == b
    assert d.decisions_added            # decisions landed between a and b


def test_checkout_and_repro_verify_integrity(helix_app):
    p = _run(helix_app)
    man = vc.checkout(helix_app, p, f"{p}#decision-2")
    assert man["integrity_ok"] is True
    assert "content-addressed page-version store" in \
        man["materialisation_note"]                          # honest boundary
    rep = vc.repro(helix_app, p, "v-none" if False else
                   helix_app.snapshots(p).all()[-1].id)
    assert rep["reproducible"] is True and "model_routing" in rep


def test_bisect_finds_plan_violation(helix_app):
    p = _run(helix_app, inject_flags=["plan_violation"])
    r = vc.bisect(helix_app, p)
    assert r["found"] is True
    assert r["decision"].endswith("decision-" + r["decision"].split("-")[-1])
    clean = _run(helix_app, project="bl2")
    assert vc.bisect(helix_app, clean)["found"] is False


def test_fork_bundle_is_self_contained(helix_app, tmp_path):
    p = _run(helix_app)
    out = vc.fork_bundle(helix_app, p, tmp_path / "bundle")
    for f in ("decision-log.json", "loom.svg", "loom.txt",
              "prism.svg", "prism.txt", "README.md"):
        assert (out / f).exists(), f
    assert (out / "snapshots").is_dir()


def test_fork_bundle_redacts_private(helix_app, tmp_path):
    helix_app.projects.create("secret", privacy=True)
    WorkflowEngine(helix_app, FakeAgents()).start(
        "secret", autonomy={g: "auto" for g in GATES})
    out = vc.fork_bundle(helix_app, "secret", tmp_path / "sb")
    assert "redacted" in (out / "README.md").read_text().lower()
