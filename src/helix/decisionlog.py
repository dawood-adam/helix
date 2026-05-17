"""Decision log — one source of truth (HELIX.md §7.1, §7.2).

The structured JSON is **canonical**; the markdown narrative is a
**deterministic render of it**, regenerated on every append. There is
no dual-write and no sync step — the narrative is a pure projection.

* Canonical: ``projects/<name>/.decision-log.json`` (append-only list).
* Rendered: ``projects/<name>/decision-log-narrative.md`` — a
  ``generated: true`` page written **through the WriteQueue**, so the
  single serial applier owns the derived re-render (§6.4.1).

The same renderer powers the gate "why" bullets (§9.3) and the
catch-me-up digest (§9.6) "for free".
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from helix.atlas.store import AtlasLayout
from helix.atlas.writequeue import Intent, WriteQueue


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _humanize(action: str) -> str:
    """Deterministic action -> heading text. ``pick:ODF`` -> ``Pick ODF``."""
    verb, _, rest = action.partition(":")
    words = verb.replace("_", " ").strip()
    head = words[:1].upper() + words[1:]
    return f"{head} {rest}".strip() if rest else head


class DecisionLog:
    """Per-project append-only log + its deterministic narrative."""

    def __init__(
        self,
        project: str,
        layout: AtlasLayout,
        write_queue: WriteQueue,
        *,
        clock: Callable[[], _dt.datetime] = _utcnow,
    ):
        self.project = project
        self.layout = layout
        self.wq = write_queue
        self._clock = clock
        # The decision log is THE canonical artifact (§7, §14); §7 is
        # explicit that it must have the *strongest* consistency model.
        # So its read-modify-write serializes on the same process-global
        # ordered-writer lock as every other Atlas write — not a private
        # per-instance lock (which would let two instances race the
        # `n = len()+1` id assignment; review finding #3). The lock is
        # re-entrant, so the nested narrative-regenerate submit is safe.
        self._lock = write_queue.lock
        self._json_path: Path = layout.decision_log_json(project)
        self._narrative_handle = f"proj:{project}-decision-log"
        self._narrative_path = str(
            layout.decision_log_narrative(project).relative_to(layout.root)
        )

    # ---- canonical store --------------------------------------------

    def entries(self) -> List[Dict[str, Any]]:
        if not self._json_path.exists():
            return []
        return json.loads(self._json_path.read_text())

    def head(self) -> Optional[str]:
        """Id of the latest decision (the Snapshot ``decision_head``)."""
        items = self.entries()
        return items[-1]["id"] if items else None

    def get(self, decision_id: str) -> Dict[str, Any]:
        for e in self.entries():
            if e["id"] == decision_id:
                return e
        raise KeyError(decision_id)

    def _write_json(self, items: List[Dict[str, Any]]) -> None:
        self._json_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, indent=2))
        tmp.replace(self._json_path)  # atomic on POSIX

    def append(self, **fields: Any) -> Dict[str, Any]:
        """Append one decision; regenerate the narrative through the queue.

        Required: ``stage``, ``action``. Optional but recommended:
        ``rationale``, ``evidence``, ``rejected``, ``chosen_id``,
        ``auto_or_human``, ``autonomy_mode``, ``next``, ``title``.
        """
        if "stage" not in fields or "action" not in fields:
            raise ValueError("decision requires 'stage' and 'action'")
        with self._lock:
            items = self.entries()
            n = len(items) + 1
            entry: Dict[str, Any] = {
                "id": f"{self.project}#decision-{n}",
                "timestamp": self._clock()
                .isoformat()
                .replace("+00:00", "Z"),
                "stage": fields["stage"],
                "action": fields["action"],
                "chosen_id": fields.get("chosen_id"),
                "rejected": fields.get("rejected", []),
                "rationale": fields.get("rationale", ""),
                "evidence": fields.get("evidence", []),
                "atlas_ref": fields.get("atlas_ref", f"proj:{self.project}"),
                "wiki_pages_touched": fields.get("wiki_pages_touched", []),
                "auto_or_human": fields.get("auto_or_human", "human"),
                "autonomy_mode": fields.get("autonomy_mode", "always_ask"),
            }
            for opt in ("title", "next"):
                if opt in fields:
                    entry[opt] = fields[opt]
            items.append(entry)
            self._write_json(items)
            self._regenerate_narrative(items)
            return entry

    def fold_into_rationale(self, decision_id: str, prose: str) -> Dict[str, Any]:
        """Resolve a §7.2 fold: a human's edit to the generated narrative
        is promoted into the canonical JSON ``rationale`` (never tolerated
        as a divergent copy), then the narrative regenerates from it.
        """
        with self._lock:
            items = self.entries()
            for e in items:
                if e["id"] == decision_id:
                    base = e.get("rationale", "").strip()
                    e["rationale"] = (base + "\n\n" + prose.strip()).strip()
                    self._write_json(items)
                    self._regenerate_narrative(items)
                    return e
            raise KeyError(decision_id)

    # ---- deterministic renderer (pure projection) -------------------

    def _wikilink(self, ref: str) -> str:
        from helix.ids import split_ref

        base, frag = split_ref(ref)
        try:
            path = self.wq.store.index.path_for(base)
            target = path[:-3] if path.endswith(".md") else path
        except KeyError:
            target = ref
        return f"[[{target}#{frag}]]" if frag else f"[[{target}]]"

    @staticmethod
    def _join(links: List[str]) -> str:
        if not links:
            return ""
        if len(links) == 1:
            return links[0]
        return ", ".join(links[:-1]) + " and " + links[-1]

    def render_entry(self, entry: Dict[str, Any]) -> str:
        n = entry["id"].rsplit("-", 1)[-1]
        heading = entry.get("title") or _humanize(entry["action"])
        date = entry["timestamp"][:10]
        gate = f"gate_{entry['stage']}"
        who = (
            "human-decided"
            if entry.get("auto_or_human", "human") == "human"
            else "auto-routed"
        )
        lines = [
            f"## Decision {n} — {heading}",
            f"*{date}, {gate}, {who}*  · "
            f"*(generated from .decision-log.json — do not edit)*",
            "",
        ]
        rationale = entry.get("rationale", "").strip()
        evidence = entry.get("evidence", [])
        para = rationale
        if evidence:
            links = self._join([self._wikilink(r) for r in evidence])
            para = (para + f" — see {links}.").strip() if para else f"See {links}."
        if para:
            lines += [para, ""]
        rejected = entry.get("rejected", [])
        if rejected:
            lines.append("Rejected:")
            for r in rejected:
                label = f" ({r['label']})" if r.get("label") else ""
                lines.append(f"- {r['id']}{label}: {r.get('reason', '')}")
            lines.append("")
        if entry.get("next"):
            lines += [f"Next: {entry['next']}", ""]
        return "\n".join(lines).rstrip() + "\n"

    def render_narrative(self, items: Optional[List[Dict[str, Any]]] = None) -> str:
        items = self.entries() if items is None else items
        out = [f"# Decision log — {self.project}", ""]
        for e in items:
            out.append(self.render_entry(e))
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    def why_bullets(self, entry: Dict[str, Any]) -> List[str]:
        """The 3-bullet gate 'why' (§9.3) — same renderer, no extra cost."""
        bullets: List[str] = []
        rationale = entry.get("rationale", "").strip()
        if rationale:
            bullets.append(rationale.split("\n")[0])
        if entry.get("rejected"):
            ids = ", ".join(r["id"] for r in entry["rejected"])
            bullets.append(f"Ruled out: {ids}")
        if entry.get("evidence"):
            bullets.append("Evidence: " + ", ".join(entry["evidence"]))
        return bullets[:3]

    def _regenerate_narrative(self, items: List[Dict[str, Any]]) -> None:
        self.wq.submit(
            Intent(
                op="upsert",
                payload={
                    "handle": self._narrative_handle,
                    "type": "project",
                    "title": f"{self.project} — decision log",
                    "status": "active",
                    "path": self._narrative_path,
                    "body": self.render_narrative(items),
                },
            )
        )
