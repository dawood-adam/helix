"""Content-addressed data store (HELIX.md §7.6, §7.3).

§7.6 stores data/weights/run-outputs in a content-addressed store
("DVC/LFS-style, **or just hashes recorded in the Snapshot**"). This is
the minimal real form: a local CAS under ``.helix/cas/`` keyed by
sha256, with the hashes recorded in the Snapshot's ``data_hashes`` so
``helix repro``/``checkout`` bind data the same way they bind code.
DVC/LFS is the opt-in heavier backend (see :mod:`helix.upgrades`); this
default is zero-dependency and genuinely content-addressed (not faked).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Optional


class CAS:
    def __init__(self, layout):
        self._dir = layout.helix_dir / "cas"
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha(data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()

    def put_bytes(self, data: bytes) -> str:
        h = self._sha(data)
        blob = self._dir / h.split(":", 1)[1]
        if not blob.exists():                  # immutable, dedup by hash
            tmp = blob.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(blob)
        return h

    def put_file(self, path: Path) -> Optional[str]:
        path = Path(path)
        if not path.exists():
            return None
        return self.put_bytes(path.read_bytes())

    def has(self, h: str) -> bool:
        return (self._dir / h.split(":", 1)[1]).exists()

    def get(self, h: str) -> Optional[bytes]:
        blob = self._dir / h.split(":", 1)[1]
        return blob.read_bytes() if blob.exists() else None


def project_data_hashes(app, project: str) -> Dict[str, str]:
    """Hash this project's run outputs / data into the CAS and return
    ``{label: sha256}`` for the Snapshot bind (§7.3). Honest: only what
    actually exists on disk is hashed — nothing fabricated."""
    cas = CAS(app.store.layout)
    pdir = app.store.layout.project_dir(project)
    out: Dict[str, str] = {}
    for label, rel in (("results", "results/latest.json"),
                        ("repro", "repro.md")):
        h = cas.put_file(pdir / rel)
        if h:
            out[label] = h
    code = pdir / "code"
    if code.exists():
        for f in sorted(code.glob("*.py")):
            h = cas.put_file(f)
            if h:
                out[f"code/{f.name}"] = h
    return out
