from helix.atlas.writequeue import Intent
from helix.forge.agents import FakeAgents
from helix.forge.state import GATES
from helix.forge.workflow import WorkflowEngine
from helix.maintainer import Maintainer
from helix.queue import maintainer_fyi_provider


def _shipped(app, project="bl"):
    app.projects.create(project)
    WorkflowEngine(app, FakeAgents()).start(
        project, autonomy={g: "auto" for g in GATES})
    return project


# ---- freeze + within-project value (§13) --------------------------


def test_freeze_writes_repro_drafts_and_supplement(helix_app):
    p = _shipped(helix_app)
    rep = Maintainer(helix_app).freeze(p)
    pdir = helix_app.store.layout.project_dir(p)
    assert (pdir / "repro.md").exists()
    for f in ("methods.md", "limitations.md", "rebuttals.md"):
        assert (pdir / f).exists() and f in rep.drafts
    assert (pdir / "supplement" / "loom.svg").exists()
    assert helix_app.projects.get(p).tier == "published"
    actions = [e["action"] for e in helix_app.decision_log(p).entries()]
    assert "maintainer_freeze" in actions
    assert isinstance(rep.lint_findings, int)


def test_methods_and_rebuttals_come_from_decision_log(helix_app):
    p = _shipped(helix_app)
    helix_app.snapshots(p).fork("alt", decision_head=None)
    helix_app.snapshots(p).park("alt", decision_head=None)
    Maintainer(helix_app).freeze(p)
    pdir = helix_app.store.layout.project_dir(p)
    methods = (pdir / "methods.md").read_text()
    assert "pick:approach-1" in methods            # from the pick decision
    assert "deterministic roll-up" in methods.lower()   # honest banner
    reb = (pdir / "rebuttals.md").read_text()
    assert "alt" in reb and "Why didn't you" in reb     # §13 rebuttal


def test_bibtex_from_source_pages(helix_app):
    helix_app.wq.submit(Intent(op="create", payload={
        "type": "source", "title": "2024 Zhang Bowel Anatomy",
        "status": "canonical", "body": "abstract"}))
    p = _shipped(helix_app)
    Maintainer(helix_app).freeze(p)
    bib = (helix_app.store.layout.project_dir(p) / "references.bib")
    assert bib.exists() and "@misc{" in bib.read_text()


def test_freeze_is_idempotent(helix_app):
    p = _shipped(helix_app)
    Maintainer(helix_app).freeze(p)
    rep2 = Maintainer(helix_app).freeze(p)            # no crash on re-freeze
    assert rep2.project == p


# ---- promotion-as-suggestion (§9.4) -------------------------------


def test_freeze_suggestion_when_shipped_not_frozen(helix_app):
    helix_app.projects.create("bl")
    helix_app.decision_log("bl").append(
        stage="results", action="ship", rationale="done")
    sugg = Maintainer(helix_app).suggestions()
    assert any(s.kind == "freeze" and "bl" in s.command for s in sugg)
    # The queue carries it as a one-tap FYI with the exact command.
    items = maintainer_fyi_provider(helix_app)
    assert any("helix freeze bl" == i.command for i in items)


def test_freeze_suggestion_clears_after_maintainer_freeze(helix_app):
    # A full auto workflow already runs the Maintainer (it freezes at
    # the end, §5.2), so build the shipped-but-not-yet-frozen state
    # explicitly to exercise the suggestion lifecycle.
    helix_app.projects.create("bl")
    helix_app.decision_log("bl").append(
        stage="results", action="ship", rationale="done")
    assert any(s.kind == "freeze"
               for s in Maintainer(helix_app).suggestions())
    Maintainer(helix_app).freeze("bl")
    assert not any(s.kind == "freeze"
                   for s in Maintainer(helix_app).suggestions())


def test_promote_suggestion_for_cross_project_concept(helix_app):
    helix_app.wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Crossing Point Failure",
        "status": "active", "body": "x"}))
    for proj in ("p1", "p2"):
        helix_app.projects.create(proj)
        helix_app.decision_log(proj).append(
            stage="methods", action="pick:a", rationale="r",
            evidence=["concept:crossing-point-failure"])
    sugg = Maintainer(helix_app).suggestions()
    promo = [s for s in sugg if s.kind == "promote"]
    assert promo and "concept:crossing-point-failure" in promo[0].command
    assert "2 projects" in promo[0].title
