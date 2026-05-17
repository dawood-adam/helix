"""Process-global write lock (HELIX.md §6.4.1, §7).

§6.4.1 requires **one writer at a time, globally** — and §7 demands the
*strongest* consistency for the canonical artifact. A ``threading``
lock only serialises threads *within one process*. But the real
deployment is multi-process: the cron-wrapped Watcher (``helix watcher
run``, build step 13) runs concurrently with an interactive ``helix
<project>``. Each ``helix`` invocation is a separate OS process with
its own ``WriteQueue``; an in-process lock does nothing between them,
so two processes could lose updates / mint duplicate decision ids /
race the Snapshot counter.

:class:`ProcessLock` closes that gap (the step-1 review finding #7,
promised for step 13). It composes:

* a ``threading.RLock`` — fast in-process serialisation + re-entrancy
  (a decision append re-enters via the narrative regenerate; the
  ProjectStore compound op nests mint() under the same lock); and
* an advisory ``fcntl.flock`` on a lock file, taken only on the
  *outermost* entry per process and released on the outermost exit, so
  exactly one process is ever inside the critical section.

POSIX only. If ``fcntl`` is unavailable (Windows) it degrades to the
in-process lock with a one-time warning — honest about the limitation
rather than silently pretending cross-process safety.
"""

from __future__ import annotations

import threading
import warnings
from pathlib import Path
from typing import Optional

try:
    import fcntl  # POSIX
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - non-POSIX fallback
    _HAVE_FCNTL = False


class ProcessLock:
    """Re-entrant, process-global advisory write lock."""

    def __init__(self, lock_path: Path):
        self._path = Path(lock_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._rlock = threading.RLock()
        self._depth = 0
        # Open the lock file ONCE for the process lifetime and flock the
        # persistent fd. Opening/closing it per critical section adds two
        # syscalls per write and starves tight retry loops (a real
        # regression the in-process concurrency test caught).
        self._fd: Optional[int] = None
        if _HAVE_FCNTL:
            import os
            self._fd = os.open(str(self._path),
                               os.O_CREAT | os.O_RDWR, 0o644)
        if not _HAVE_FCNTL:
            warnings.warn(
                "fcntl unavailable: the Atlas write lock is process-local "
                "only; concurrent `helix` processes (e.g. the cron Watcher "
                "and an interactive session) are NOT serialised on this "
                "platform.", RuntimeWarning, stacklevel=2)

    # ---- context-manager API (drop-in for the old RLock) ------------

    def acquire(self) -> bool:
        # The RLock guarantees a single thread of THIS process is inside
        # at a time, so depth is only ever mutated single-threaded.
        self._rlock.acquire()
        self._depth += 1
        if self._depth == 1 and self._fd is not None:
            # Outermost entry for this process → take the file lock on
            # the persistent fd, blocking until any *other* process
            # leaves its section.
            fcntl.flock(self._fd, fcntl.LOCK_EX)
        return True

    def release(self) -> None:
        if self._depth == 1 and self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._depth -= 1
        self._rlock.release()

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
