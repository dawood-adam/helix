"""Salvage — keep the learning when the path dies (HELIX.md §6.4).

Research is *mostly* dead ends, so this is optimised, not an
afterthought. ``helix salvage`` extracts the durable findings into a
``canonical`` page **with provenance** (so the §7 lint can later tell
stale claims from current ones), parks the branch's Snapshot
(resumable), and logs *why* the line died — the death reason becomes
part of the §14 artifact. The learning survives even when the path
doesn't.

The digest is a deterministic structured roll-up of the branch's
decision rationales + evidence (provenance-tagged), not LLM synthesis —
honest about being a roll-up, not a write-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from helix.atlas.writequeue import Intent
from helix.ids import make_handle


@dataclass
class SalvageResult:
    project: str
    branch: str
    canonical_handle: str
    claims: int
    reason: str


class Salvager:
    def __init__(self, app):
        self.app = app

    def salvage(self, project: str, branch: str, *,
                reason: str = "dead end") -> SalvageResult:
        snaps = self.app.snapshots(project)
        if branch not in snaps.branches():
            raise ValueError(f"unknown branch: {branch!r} in {project}")
        log = self.app.decision_log(project)
        entries = log.entries()

        # Durable claims = each decision's rationale, provenance-tagged
        # with ^dec:<id> (+ ^src: for its evidence) so stale-by-
        # provenance lint (§6.2/§6.4) works on the salvaged page.
        claims: List[str] = []
        for e in entries:
            r = (e.get("rationale") or "").strip().splitlines()
            if not r or not r[0]:
                continue
            prov = f" ^dec:{e['id']}"
            for ev in e.get("evidence", []):
                if str(ev).startswith("src:"):
                    prov += f" ^{ev}"
            claims.append(f"- {r[0]} {prov}")

        title = f"Salvaged: {project}/{branch}"
        handle = make_handle("concept", title)
        body = (f"# {title}\n\n"
                f"**Why this line died:** {reason}\n\n"
                f"## Durable claims (provenance-tagged)\n\n"
                + ("\n".join(claims) if claims
                   else "- (no rationale was recorded to salvage)\n") +
                "\n\n_Deterministic roll-up of the branch's decision "
                "log — not a synthesised write-up._\n")

        # §9.9 directional write boundary: a private project's learning
        # is NOT auto-folded into canonical knowledge — it stays
        # non-canonical + privately-bannered until manually abstracted.
        from helix.privacy import Privacy

        private = Privacy(self.app).is_strict(project)
        tier = "active" if private else "canonical"

        if self.app.store.index.has(handle):       # idempotent re-salvage
            page, ver = self.app.store.read_page(handle)
            self.app.wq.submit(Intent(op="update", ref=handle,
                                      base_version=ver,
                                      payload={"body": body}))
        else:
            self.app.wq.submit(Intent(op="create", payload={
                "type": "concept", "title": title, "status": tier,
                "private": private,
                "summary": f"Salvaged learning from {project}/{branch}: "
                           f"{reason}",
                "tags": ["salvage", project],
                "body": body}))

        # Park + mark salvaged (resumable) and log the death reason.
        dest = ("active (private — manual abstraction required, §9.9)"
                if private else "canonical")
        log.append(stage="lifecycle", action="salvage",
                   rationale=f"Branch '{branch}' salvaged: {reason}. "
                             f"{len(claims)} durable claim(s) → {dest}.",
                   evidence=[handle], auto_or_human="human")
        snaps.salvage(branch, decision_head=log.head())
        return SalvageResult(project, branch, handle, len(claims), reason)
