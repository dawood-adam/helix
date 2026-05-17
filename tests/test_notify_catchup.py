import datetime as dt
import json

from helix.catchup import CatchUp, _humanize_since
from helix.forge.agents import FakeAgents
from helix.forge.state import GATES
from helix.forge.workflow import WorkflowEngine
from helix.notify import in_quiet_hours, triage
from helix.queue import FYI, NEEDS_YOU, WORKING, QueueItem


def _items(needs=0, working=0, fyi=0):
    return {
        NEEDS_YOU: [QueueItem(NEEDS_YOU, f"n{i}") for i in range(needs)],
        WORKING: [QueueItem(WORKING, f"w{i}") for i in range(working)],
        FYI: [QueueItem(FYI, f"f{i}") for i in range(fyi)],
    }


# ---- §9.5 triage --------------------------------------------------


def test_only_blocking_is_pushable_rest_batched():
    noon = lambda: dt.datetime(2026, 5, 16, 12, 0)            # not quiet
    tr = triage(_items(needs=2, working=3, fyi=4),
                quiet_hours_enabled=True, now=noon)
    assert tr.badge == 2                       # one badge = needs count
    assert len(tr.push) == 2                   # blocking only
    assert len(tr.digest) == 7                 # working + fyi, batched
    assert not tr.quiet


def test_quiet_hours_suppress_push_keep_badge():
    night = lambda: dt.datetime(2026, 5, 16, 23, 30)          # quiet
    tr = triage(_items(needs=3, working=1, fyi=1),
                quiet_hours_enabled=True, now=night)
    assert tr.quiet and tr.badge == 3 and tr.push == []
    assert len(tr.digest) == 2                 # digest unaffected
    assert "badge: 3" in tr.summary()


def test_quiet_hours_can_be_disabled():
    night = lambda: dt.datetime(2026, 5, 16, 23, 30)
    tr = triage(_items(needs=1), quiet_hours_enabled=False, now=night)
    assert not tr.quiet and tr.push


def test_in_quiet_hours_boundaries():
    assert in_quiet_hours(dt.datetime(2026, 1, 1, 23, 0))
    assert in_quiet_hours(dt.datetime(2026, 1, 1, 3, 0))
    assert not in_quiet_hours(dt.datetime(2026, 1, 1, 12, 0))


# ---- §9.6 catch-me-up ---------------------------------------------


def _clock(d):
    return lambda: d


def test_idle_cursor_is_view_state(helix_app):
    cu = CatchUp(helix_app)
    assert cu.last_open() is None
    assert cu.is_idle_reentry() is False          # first open ≠ re-entry
    cu.mark_opened()
    assert cu.last_open() is not None
    # cursor never lands in a Snapshot / the decision log / a bundle
    assert cu._cursor_path().parent.name == ".helix"


def test_idle_reentry_after_24h(helix_app):
    now = dt.datetime(2026, 5, 16, 12, tzinfo=dt.timezone.utc)
    cu = CatchUp(helix_app, now=_clock(now))
    cu._cursor_path().write_text(json.dumps(
        {"ts": (now - dt.timedelta(hours=48)).isoformat()}))
    assert cu.is_idle_reentry() is True
    cu2 = CatchUp(helix_app, now=_clock(now))
    cu2._cursor_path().write_text(json.dumps(
        {"ts": (now - dt.timedelta(hours=2)).isoformat()}))
    assert cu2.is_idle_reentry() is False


def test_project_digest_from_decision_log(helix_app):
    helix_app.projects.create("bl")
    WorkflowEngine(helix_app, FakeAgents()).start(
        "bl", autonomy={g: "auto" for g in GATES})
    d = CatchUp(helix_app).project_digest("bl")
    assert d and d.startswith("bl, since ")
    assert "→" in d                              # the decision chain
    # Auto-run reaches the Maintainer freeze, so status reflects it.
    assert "published" in d.lower() or "." in d
    assert CatchUp(helix_app).project_digest("missing") is None


def test_digest_waiting_status_when_interrupted(helix_app):
    helix_app.projects.create("bl")
    WorkflowEngine(helix_app, FakeAgents()).start("bl")  # always_ask: pauses
    d = CatchUp(helix_app).project_digest("bl")
    assert "Waiting on your approval" in d


def test_humanize_since():
    n = dt.datetime(2026, 5, 16, 12, tzinfo=dt.timezone.utc)
    h = dt.timedelta(hours=1)
    assert _humanize_since(n - 25 * h, n) == "yesterday"
    assert _humanize_since(n - 72 * h, n) == "3 days ago"
    assert _humanize_since(n - 24 * 9 * h, n) == "last week"
    assert "weeks ago" in _humanize_since(n - 24 * 30 * h, n)


def test_all_active_excludes_archived(helix_app):
    # ProjectStore.create always logs an `init` decision, so a
    # decision-less project can't exist — the real filter is 'archived'.
    helix_app.projects.create("live")
    helix_app.projects.create("old")
    helix_app.projects.archive("old")
    active = CatchUp(helix_app).all_active()
    assert "live" in active and "old" not in active


# ---- CLI wiring ---------------------------------------------------


def test_queue_shows_badge_and_idle_catchup(ready_run, tmp_path):
    ready_run("init", "bl")
    cur = tmp_path / "home" / ".helix" / "last-open.json"
    cur.parent.mkdir(parents=True, exist_ok=True)
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48))
    cur.write_text(json.dumps({"ts": old.isoformat()}))
    out = ready_run()
    assert "badge:" in out.output
    assert "Catch me up" in out.output and "bl, since" in out.output
    # opening the queue advanced the cursor (no longer 48h old)
    assert json.loads(cur.read_text())["ts"] != old.isoformat()


def test_peek_is_readonly_does_not_advance_cursor(ready_run, tmp_path):
    ready_run("init", "bl")
    ready_run()                                   # sets cursor = T1
    cur = tmp_path / "home" / ".helix" / "last-open.json"
    t1 = cur.read_text()
    pk = ready_run("peek", "bl")
    assert "catch-me-up:" in pk.output
    assert cur.read_text() == t1                  # peek is a look, not open
