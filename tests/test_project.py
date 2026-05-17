import threading

import pytest

from helix.project import LadderError


def test_create_logs_decision_and_mints_snapshot(helix_app):
    p = helix_app.projects.create("bowel-length")
    assert p.tier == "scratch" and p.rung == "notes"
    log = helix_app.decision_log("bowel-length")
    assert log.entries()[0]["action"] == "init"
    # History starts at the moment of commitment (§9.10).
    assert helix_app.snapshots("bowel-length").head() == \
        "snap:bowel-length@1"


def test_ladder_promote_demote(helix_app):
    ps = helix_app.projects
    ps.create("bl")
    assert ps.promote("bl").rung == "project"      # notes -> project
    assert ps.promote("bl").rung == "published"    # project -> published
    with pytest.raises(LadderError, match="top"):
        ps.promote("bl")
    assert ps.demote("bl").rung == "project"
    assert ps.demote("bl").rung == "notes"
    # demote past the bottom rung == archive (§9.7)
    assert ps.demote("bl").rung == "archived"
    with pytest.raises(LadderError, match="archived"):
        ps.promote("bl")


def test_ladder_multi_rung_and_bad_targets(helix_app):
    ps = helix_app.projects
    ps.create("bl")
    assert ps.promote("bl", to="published").rung == "published"
    with pytest.raises(LadderError):
        ps.promote("bl", to="notes")          # not higher
    ps.demote("bl", to="notes")
    with pytest.raises(LadderError):
        ps.demote("bl", to="published")       # not lower


def test_every_rung_change_is_logged_and_snapshotted(helix_app):
    ps = helix_app.projects
    ps.create("bl")                                   # decision 1, snap 1
    ps.promote("bl")                                  # decision 2, snap 2
    ps.promote("bl")                                  # decision 3, snap 3
    log = helix_app.decision_log("bl")
    actions = [e["action"] for e in log.entries()]
    assert actions == ["init", "promote", "promote"]
    snaps = helix_app.snapshots("bl")
    assert snaps.head() == "snap:bl@3"
    assert len(snaps.all()) == 3


def test_freeze_published_and_paused(helix_app):
    ps = helix_app.projects
    ps.create("bl", tier="active")
    assert ps.freeze("bl").rung == "published"
    ps.create("opi", tier="active")
    ps.freeze("opi", status="paused")
    snaps = helix_app.snapshots("opi")
    assert snaps.is_parked(snaps.active_branch)        # paused == parked line
    assert ps.get("opi").tier == "active"              # tier unchanged


def test_private_project_records_strict(helix_app):
    p = helix_app.projects.create("secret", privacy=True)
    assert p.privacy_mode == "strict"
    assert "strict" in helix_app.decision_log("secret").entries()[0][
        "rationale"].lower()


def test_notes_tier_project_lives_under_projects_dir(helix_app):
    """Regression: a notes-tier project is scratch-*status* but its
    overview page must live at projects/<name>/, never scratch/ — and
    two notes projects must not collide on one path."""
    helix_app.projects.create("alpha")            # notes tier (scratch)
    helix_app.projects.create("beta")
    pa = helix_app.store.index.path_for("proj:alpha")
    pb = helix_app.store.index.path_for("proj:beta")
    assert pa == "projects/alpha/overview.md"
    assert pb == "projects/beta/overview.md"
    assert pa != pb
    # Promotion must NOT relocate the project dir (keyed for log/snaps).
    helix_app.projects.promote("alpha")
    assert helix_app.store.index.path_for("proj:alpha") == \
        "projects/alpha/overview.md"


def test_shared_write_lock_is_wired(helix_app):
    """Closes review fix #4's production wiring: SnapshotStore and
    DecisionLog must serialize on the WriteQueue's global lock."""
    assert helix_app.snapshots("x")._lock is helix_app.wq.lock
    assert helix_app.decision_log("x")._lock is helix_app.wq.lock


def test_concurrent_ladder_moves_serialize_via_facade(helix_app):
    """Compound tier changes (meta + overview + decision + Snapshot)
    must be atomic and serialized on the shared lock. LadderError is an
    expected outcome of racing promote/demote; ANY other exception (a
    temp-file race, a corrupted DAG) fails the test loudly — no
    swallowing thread exceptions into warnings."""
    helix_app.projects.create("bl")
    errors = []

    def churn():
        for _ in range(5):
            for move in (helix_app.projects.promote,
                         helix_app.projects.demote):
                try:
                    move("bl")
                except LadderError:
                    pass
                except Exception as e:  # noqa: BLE001
                    errors.append(repr(e))

    ts = [threading.Thread(target=churn) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == [], errors
    snaps = helix_app.snapshots("bl")
    seqs = sorted(s.seq for s in snaps.all())
    assert seqs == list(range(1, len(seqs) + 1))   # no dup/lost in the DAG
    assert all(s.verify() for s in snaps.all())
    # Decision count == Snapshot count: every tier change landed both.
    assert len(helix_app.decision_log("bl").entries()) == len(seqs)
