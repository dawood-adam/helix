import pytest

from helix.atlas.writequeue import Intent
from helix.forge.agents import FakeAgents
from helix.forge.workflow import WorkflowEngine
from helix.queue import watcher_fyi_provider
from helix.watcher import Watcher


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("HELIX_EXPLORE_BACKEND", "fake")


def test_off_by_default(helix_app):
    helix_app.projects.create("bl")
    rep = Watcher(helix_app).run()
    assert rep.ran is False and "off" in rep.note
    # nothing ingested while disabled
    assert not any(e.type == "source" for e in helix_app.store.index)


def test_run_ingests_scratch_only(helix_app):
    helix_app.projects.create("bl")
    w = Watcher(helix_app)
    w.enable("0 7 * * *")
    rep = w.run()
    assert rep.ran and rep.ingested > 0
    sources = [e for e in helix_app.store.index if e.type == "source"]
    assert sources
    # §6.4.1: the Watcher writes ONLY to scratch — never canonical/active
    assert all(e.status == "scratch" for e in sources)
    assert all("watcher" in
               helix_app.store.read_page(e.handle)[0].tags
               for e in sources)


def test_dedupe_across_runs(helix_app):
    helix_app.projects.create("bl")
    w = Watcher(helix_app)
    w.enable()
    first = w.run()
    second = w.run()
    assert first.ingested > 0
    assert second.ingested == 0 and second.skipped_seen >= first.ingested


def test_overlap_proposal_against_canonical(helix_app):
    helix_app.wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Centerline Tracing",
        "status": "canonical", "summary": "centerline tracing",
        "body": "centerline tracing"}))
    w = Watcher(helix_app)
    w.enable()
    w.watch("centerline tracing")
    w.run()
    props = w.open_proposals()
    assert any(p["target_concept"] == "concept:centerline-tracing"
               for p in props)


def test_apply_links_into_canonical_and_is_idempotent(helix_app):
    helix_app.wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Centerline Tracing",
        "status": "canonical", "summary": "centerline tracing",
        "body": "base"}))
    w = Watcher(helix_app)
    w.enable()
    w.watch("centerline tracing")
    w.run()
    prop = next(p for p in w.open_proposals()
                if p["target_concept"] == "concept:centerline-tracing")
    msg = w.apply(prop["id"])
    assert "linked" in msg
    body = helix_app.store.read_page("concept:centerline-tracing")[0].body
    assert "Watcher addition" in body and "^src:" in body
    assert w.apply(prop["id"]) == "already applied"


def test_never_writes_behind_in_flight_project(helix_app):
    helix_app.projects.create("bl")
    helix_app.wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Bl", "status": "canonical",
        "summary": "bl bowel", "body": "base body"}))
    # Start (and leave interrupted) bl's workflow → it is in-flight.
    WorkflowEngine(helix_app, FakeAgents()).start("bl")
    w = Watcher(helix_app)
    w.enable()
    w.run()
    deferred = [p for p in w.open_proposals()
                if p["project"] == "bl" and p["deferred"]]
    assert deferred, "proposals against an in-flight project must defer"
    # apply refuses to write behind the in-flight project (§6.4.1)
    out = w.apply(deferred[0]["id"])
    assert "deferred" in out and "in-flight" in out
    assert "Watcher addition" not in \
        helix_app.store.read_page("concept:bl")[0].body   # not written


def test_status_and_crontab(helix_app):
    w = Watcher(helix_app)
    assert w.status()["enabled"] is False
    w.enable("30 6 * * 1")
    w.watch("sim to real")
    st = w.status()
    assert st["enabled"] and "sim to real" in st["watch"]
    assert "helix watcher run" in w.crontab_line()


def test_queue_provider_aggregates(helix_app):
    helix_app.projects.create("bl")
    w = Watcher(helix_app)
    w.enable()
    w.run()
    items = watcher_fyi_provider(helix_app)
    assert items and items[0].bucket == "FYI"
    assert "may overlap" in items[0].title
    assert items[0].command == "helix watcher"


def test_cli_watcher_lifecycle(ready_run):
    off = ready_run("watcher", "status")
    assert "enabled: False" in off.output
    sch = ready_run("watcher", "schedule", "0 7 * * *")
    assert "crontab" in sch.output and "helix watcher run" in sch.output
    ready_run("init", "bl")
    run = ready_run("watcher", "run", env={"HELIX_EXPLORE_BACKEND": "fake"})
    assert "new source" in run.output and "scratch-only" in run.output
    q = ready_run()
    assert "Watcher:" in q.output
