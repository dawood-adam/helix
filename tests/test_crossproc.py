"""Regression for review finding #7 / HIGH-1 (HELIX.md §6.4.1, §7).

Two *separate OS processes* hammer the canonical stores on the SAME
atlas — the real deployment (cron `helix watcher run` ∥ interactive
`helix <project>`). An in-process lock can't serialise this; only the
ProcessLock file lock can. Pre-fix this test produces duplicate
decision ids / colliding Snapshot seqs / lost updates.
"""

import multiprocessing as _mp
from pathlib import Path

import pytest

from helix.atlas.proclock import _HAVE_FCNTL

pytestmark = pytest.mark.skipif(
    not _HAVE_FCNTL, reason="cross-process file lock needs POSIX fcntl")

N_PROCS = 3
N_EACH = 12


def _worker(src: str, home: str, project: str, n: int) -> None:
    # Fresh process → fresh Helix → fresh WriteQueue/ProcessLock, but
    # the SAME on-disk write.lock serialises us against the others.
    # `spawn` (not fork) avoids the fork-in-multithreaded-pytest
    # deadlock class; the child re-imports, so put `src` on the path.
    import sys

    if src not in sys.path:
        sys.path.insert(0, src)
    from helix.app import Helix

    app = Helix(home=home)
    for _ in range(n):
        log = app.decision_log(project)
        log.append(stage="x", action="a", rationale="r")
        app.snapshots(project).mint(decision_head=log.head(), reason="mp")


def test_two_processes_do_not_corrupt_canonical_state(tmp_path):
    import helix
    from helix.app import Helix

    src = str(Path(helix.__file__).resolve().parent.parent)
    home = str(tmp_path / "home")
    app = Helix(home=home)
    app.projects.create("bl")              # logs decision-1 + mints snap@1

    ctx = _mp.get_context("spawn")         # no fork+threads hazard
    procs = [ctx.Process(target=_worker, args=(src, home, "bl", N_EACH))
             for _ in range(N_PROCS)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0

    fresh = Helix(home=home)
    ids = [e["id"] for e in fresh.decision_log("bl").entries()]
    expected = 1 + N_PROCS * N_EACH        # init + every worker append
    # No lost updates, no duplicate ids — strict contiguity (§7).
    assert len(ids) == expected
    assert len(set(ids)) == expected
    assert sorted(ids) == sorted(
        f"bl#decision-{i}" for i in range(1, expected + 1))

    snaps = fresh.snapshots("bl").all()
    seqs = sorted(s.seq for s in snaps)
    assert seqs == list(range(1, len(seqs) + 1))   # contiguous, no gaps
    assert len({s.id for s in snaps}) == len(snaps)
    assert all(s.verify() for s in snaps)          # no torn writes
