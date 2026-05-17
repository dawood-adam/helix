"""Regression for the docs-pass reconciliation fixes (#1, #2).

#1: `helix status <name>` must filter the queue to that project
    (HELIX.md §9.7) — previously NAME was validated then ignored.
#2: `helix undo` must not advertise a shipped step as unbuilt.
"""

from helix.queue import FYI, NEEDS_YOU, Queue, QueueItem


def test_queue_collect_filters_by_project(helix_app):
    q = Queue(helix_app)
    q.register(lambda app: [
        QueueItem(NEEDS_YOU, "alpha", "gate"),
        QueueItem(NEEDS_YOU, "beta", "gate"),
        QueueItem(FYI, "Explore done", 'on "x"', command="helix init beta"),
    ])
    allc = q.collect()
    assert len(allc[NEEDS_YOU]) == 2 and len(allc[FYI]) == 1
    a = q.collect("alpha")
    assert [i.title for i in a[NEEDS_YOU]] == ["alpha"] and not a[FYI]
    b = q.collect("beta")               # title match + command match
    assert {i.title for i in b[NEEDS_YOU]} == {"beta"}
    assert len(b[FYI]) == 1             # matched via `command`
    assert q.render("alpha").count("beta") == 0
    assert "Nothing needs you on 'zeta'." in q.render("zeta")


def test_status_cli_is_filtered(ready_run):
    ready_run("init", "alpha")
    ready_run("init", "beta")
    ready_run("run", "alpha", env={"HELIX_AGENTS": "fake"})  # gate on alpha
    full = ready_run("status")
    assert "alpha" in full.output and "NEEDS YOU NOW" in full.output
    scoped_other = ready_run("status", "beta")
    assert "alpha" not in scoped_other.output
    assert "Nothing needs you on 'beta'." in scoped_other.output
    scoped_self = ready_run("status", "alpha")
    assert "alpha" in scoped_self.output
    assert "NEEDS YOU NOW" in scoped_self.output
    bad = ready_run("status", "ghost")
    assert bad.exit_code != 0 and "no such project" in bad.output


def test_undo_message_is_accurate(ready_run):
    ready_run("init", "bl")
    ready_run("promote", "bl")          # a snapshot with a parent
    r = ready_run("undo", "bl")
    assert r.exit_code == 0
    assert "reverted to" in r.output
    assert "build step 10" not in r.output      # the stale claim is gone
    assert "§7.6" in r.output and "helix checkout bl" in r.output
