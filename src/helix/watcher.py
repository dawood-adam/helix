"""The Watcher — async passive enrichment (HELIX.md §5.1, §6.4.1, §11.1).

The Watcher runs on a cron schedule and is **off by default** (§11.1).
When it runs it:

* searches the paper feeds (reusing the Explore backend — real arXiv,
  or the offline fake) for each watched topic;
* ingests genuinely-new papers as **`scratch/` source pages only**
  (§6.4.1 — never canonical/active), through the one ordered write
  queue, deduped against a per-Watcher seen-cursor;
* **proposes** diffs against canonical/active concept pages (overlap
  via the §7 retriever) — proposals are surfaced as **FYI** (batched by
  the §9.5 triage, never per-event pings) and only applied on accept;
* **never writes behind an in-flight project**: a proposal whose target
  is tied to a project whose workflow is running/interrupted is marked
  ``deferred`` and ``apply`` refuses until the project is idle.

Its state lives in its **own namespace** (``.helix/watcher/``), separate
from the Forge checkpoint, so it never contends with the project
workflow; all Atlas writes still go through the single writer (§6.4.1).

Honesty: ``helix watcher run`` does a real pass you can cron-wrap;
``schedule`` records the cadence and prints the crontab line. Helix
does not fork a daemon and pretend it is scheduling itself.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from helix.atlas.writequeue import Intent
from helix.explore import make_backend
from helix.ids import make_handle


@dataclass
class Proposal:
    id: str
    query: str
    project: Optional[str]
    paper_handle: str
    target_concept: Optional[str]
    reason: str
    deferred: bool = False
    consumed: bool = False


@dataclass
class RunReport:
    ran: bool
    ingested: int = 0
    proposals: int = 0
    deferred: int = 0
    skipped_seen: int = 0
    note: str = ""


class WatcherStore:
    def __init__(self, layout):
        self._dir = layout.helix_dir / "watcher"   # own namespace (§6.4.1)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _read(self, name: str, default):
        p = self._dir / name
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return default

    def _write(self, name: str, data) -> None:
        # Unique temp name: overlapping `helix watcher run` invocations
        # (cron re-firing before a slow run finishes) are not on the
        # ProcessLock path, so a fixed ".tmp" could race cross-process
        # (companion to review finding #7).
        import os
        import threading

        tmp = self._dir / f".{name}.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self._dir / name)

    @property
    def config(self) -> Dict[str, Any]:
        return self._read("config.json",
                          {"enabled": False, "schedule": None,
                           "watch": []})

    def save_config(self, cfg) -> None:
        self._write("config.json", cfg)

    def seen(self) -> Dict[str, bool]:
        return self._read("seen.json", {})

    def mark_seen(self, ids) -> None:
        s = self.seen()
        for i in ids:
            s[i] = True
        self._write("seen.json", s)

    def proposals(self) -> List[Dict[str, Any]]:
        return self._read("proposals.json", [])

    def save_proposals(self, items) -> None:
        self._write("proposals.json", items)


class Watcher:
    def __init__(self, app):
        self.app = app
        self.store = WatcherStore(app.store.layout)

    # ---- config / schedule (off by default, §11.1) ------------------

    def enable(self, schedule: Optional[str] = None) -> None:
        cfg = self.store.config
        cfg["enabled"] = True
        if schedule:
            cfg["schedule"] = schedule
        self.store.save_config(cfg)

    def disable(self) -> None:
        cfg = self.store.config
        cfg["enabled"] = False
        self.store.save_config(cfg)

    def watch(self, query: str) -> None:
        cfg = self.store.config
        if query not in cfg["watch"]:
            cfg["watch"].append(query)
        self.store.save_config(cfg)

    def status(self) -> Dict[str, Any]:
        cfg = self.store.config
        return {"enabled": cfg["enabled"], "schedule": cfg["schedule"],
                "watch": cfg["watch"],
                "seen": len(self.store.seen()),
                "open_proposals": len([p for p in self.store.proposals()
                                       if not p["consumed"]])}

    def crontab_line(self) -> str:
        sched = self.store.config.get("schedule") or "0 7 * * *"
        return f"{sched}  cd $PWD && helix watcher run   # Helix Watcher"

    # ---- in-flight guard (§6.4.1 'never behind an in-flight project')

    def _in_flight(self, project: str) -> bool:
        if not (self.app.home / "forge.sqlite").exists():
            return False
        try:
            return self.app.workflow().pending(project)["status"] in (
                "interrupted", "running")
        except Exception:  # noqa: BLE001
            return False

    # ---- the pass (cron-wrapped) ------------------------------------

    def _queries(self) -> List[tuple]:
        """(query, project|None). Explicit watches + every active
        project (scooping alerts, §9.1)."""
        out = [(q, None) for q in self.store.config["watch"]]
        for p in self.app.projects.list():
            if p.tier != "archived":
                out.append((p.name.replace("-", " "), p.name))
        return out

    def run(self, *, limit: int = 6) -> RunReport:
        cfg = self.store.config
        if not cfg["enabled"]:
            return RunReport(False, note="Watcher is off — "
                             "`helix watcher run` after `watcher schedule`")
        backend = make_backend(
            __import__("os").environ.get("HELIX_EXPLORE_BACKEND", "arxiv"))
        seen = self.store.seen()
        proposals = self.store.proposals()
        ingested = skipped = deferred = new_props = 0
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")

        for query, project in self._queries():
            try:
                papers = backend.search(query, limit=limit)
            except Exception:  # noqa: BLE001 — honest: no fake on feed fail
                continue
            inflight = self._in_flight(project) if project else False
            for p in papers:
                if seen.get(p.source_id):
                    skipped += 1
                    continue
                seen[p.source_id] = True
                # scratch-only ingest through the single writer (§6.4.1)
                try:
                    r = self.app.wq.submit(Intent(op="create", payload={
                        "type": "source", "title": p.slug_title(),
                        "status": "scratch", "summary": p.summary(),
                        "tags": ["watcher"],
                        "body": f"# {p.title}\n\n_Watcher-ingested "
                                f"(scratch) for '{query}'._\n\n{p.abstract}"}))
                    handle = r.handle
                    ingested += 1
                except ValueError:
                    handle = make_handle("source", p.slug_title())
                # propose a diff vs canonical/active concepts (overlap)
                target = self._overlap(p)
                if target or project:
                    if inflight:
                        deferred += 1
                    proposals.append(vars(Proposal(
                        id=f"w-{ts}-{new_props}", query=query,
                        project=project, paper_handle=handle,
                        target_concept=target,
                        reason=(f"new paper may overlap "
                                f"{target or project}"),
                        deferred=inflight)))
                    new_props += 1

        self.store.mark_seen(list(seen))
        self.store.save_proposals(proposals)
        return RunReport(True, ingested, new_props, deferred, skipped,
                         note="scratch-only; proposals are FYI until "
                              "accepted (§6.4.1)")

    def _overlap(self, paper) -> Optional[str]:
        try:
            ctx = self.app.retriever.retrieve(
                f"{paper.title} {paper.abstract}", max_hops=1,
                max_tokens=2000,
                status_filter=["canonical", "active"])
        except Exception:  # noqa: BLE001
            return None
        for it in ctx.items:
            if it.handle.startswith("concept:"):
                return it.handle
        return None

    # ---- proposals + accept -----------------------------------------

    def open_proposals(self) -> List[Dict[str, Any]]:
        return [p for p in self.store.proposals() if not p["consumed"]]

    def apply(self, proposal_id: str) -> str:
        items = self.store.proposals()
        for p in items:
            if p["id"] != proposal_id:
                continue
            if p["consumed"]:
                return "already applied"
            # Re-check in-flight at apply time — never write behind a
            # project that is mid-workflow (§6.4.1).
            if p["project"] and self._in_flight(p["project"]):
                p["deferred"] = True
                self.store.save_proposals(items)
                return (f"deferred: {p['project']} is in-flight — the "
                        f"Watcher will not write behind it; retry when "
                        f"the project is idle")
            tgt = p["target_concept"]
            # §9.9 directional boundary: never fold into a canonical
            # page on behalf of a private project.
            if tgt and self.app.store.index.has(tgt):
                from helix.privacy import Privacy

                entry = self.app.store.index.resolve(tgt)
                if entry.status == "canonical" and p["project"] and \
                        Privacy(self.app).is_strict(p["project"]):
                    p["consumed"] = True
                    self.store.save_proposals(items)
                    return (f"blocked: '{p['project']}' is privacy=strict "
                            f"— not folding into canonical {tgt} (§9.9); "
                            f"kept in scratch")
            if tgt and self.app.store.index.has(tgt):
                page, ver = self.app.store.read_page(tgt)
                add = (f"\n\n## Watcher addition\n"
                       f"- See [[{p['paper_handle']}]] "
                       f"^src:{p['paper_handle'].split(':', 1)[1]}\n")
                self.app.wq.submit(Intent(
                    op="update", ref=p["target_concept"],
                    base_version=ver,
                    payload={"body": page.body + add}))
                msg = f"linked {p['paper_handle']} into {p['target_concept']}"
            else:
                msg = (f"kept {p['paper_handle']} in scratch "
                       f"(no canonical target)")
            p["consumed"] = True
            self.store.save_proposals(items)
            return msg
        raise KeyError(proposal_id)
