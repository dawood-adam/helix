"""Loom — the project map (HELIX.md §7.7).

A pure projection of decision_log + the Snapshot DAG + the Atlas
id→path index — no Loom-specific source of truth. Map mode (v1 per
A.1); Layers/Compare are v1.5 and reported as such, not faked.

The §7.7.4 load-bearing encoding contract is enforced here:

* **status only** drives the (optional) colour; agent/gate type is the
  text label, never colour;
* a **redundant one-glyph status tag on every node is authoritative** —
  so the map is fully legible in grayscale and under ``NO_COLOR`` /
  SVG (journals print grayscale). This is mandatory, not a nicety;
* node size encodes nothing; **main lane on top**, parked/salvaged
  below, ordered by fork point;
* HITL decisions are never folded — the fold channel is cosmetic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# status -> (glyph, ascii-letter, grayscale hex). Glyph is authoritative.
_STATUS = {
    "active":    ("●", "A", "#000000"),
    "parked":    ("◦", "P", "#888888"),
    "salvaged":  ("⊘", "S", "#555555"),
    "published": ("✓", "F", "#222222"),
}
_PHASE = {"scope": "scout", "methods": "methods", "plan": "plan",
          "build": "build", "results": "critique", "undo": "undo",
          "lifecycle": "lifecycle", "budget": "budget"}


@dataclass
class LoomNode:
    snap_id: str
    seq: int
    branch: str
    status: str
    phase: str
    action: str
    auto: bool
    parent: Optional[str]
    since_cursor: bool = False


@dataclass
class LoomModel:
    project: str
    lanes: List[str] = field(default_factory=list)         # branch order
    nodes: Dict[str, List[LoomNode]] = field(default_factory=dict)
    abandoned_unsalvaged: List[str] = field(default_factory=list)
    private: bool = False


class Loom:
    def __init__(self, app, project: str):
        self.app = app
        self.project = project

    # ---- projection -------------------------------------------------

    def _cursor_path(self):
        return self.app.home / ".helix" / "loom-cursor.json"

    def _cursor(self) -> Dict[str, str]:
        p = self._cursor_path()
        if p.exists():
            import json
            try:
                return json.loads(p.read_text())
            except (OSError, ValueError):
                return {}
        return {}

    def model(self) -> LoomModel:
        s = self.app.snapshots(self.project)
        log = {e["id"]: e for e in self.app.decision_log(
            self.project).entries()}
        snaps = s.all()
        try:
            private = (self.app.projects.get(self.project).privacy_mode
                       == "strict")
        except Exception:  # noqa: BLE001
            private = False
        m = LoomModel(self.project, private=private)
        cursor = self._cursor().get(self.project)
        seen_cursor = cursor is None
        # main first (top lane, §7.7.4), others by first-seq (fork point)
        branches = s.branches()
        order = (["main"] if "main" in branches else []) + sorted(
            b for b in branches if b != "main")
        for b in order:
            m.lanes.append(b)
            m.nodes[b] = []
        for snap in snaps:
            b = snap.branch
            if b not in m.nodes:
                m.lanes.append(b)
                m.nodes[b] = []
            if s.is_salvaged(b):
                status = "salvaged"
            elif s.is_parked(b):
                status = "parked"
            elif self._published():
                status = "published"
            else:
                status = "active"
            e = log.get(snap.decision_head or "", {})
            m.nodes[b].append(LoomNode(
                snap_id=snap.id, seq=snap.seq, branch=b, status=status,
                phase=_PHASE.get(e.get("stage", ""), e.get("stage", "—")),
                action=e.get("action", snap.reason or "—"),
                auto=e.get("auto_or_human") == "auto",
                parent=snap.parent,
                since_cursor=seen_cursor))
            if snap.id == cursor:
                seen_cursor = True
        # §7.7.7 abandoned-without-salvage: a parked, non-salvaged,
        # non-main line is a hidden cost the prose log doesn't show.
        for b in m.lanes:
            if b != "main" and s.is_parked(b) and not s.is_salvaged(b):
                m.abandoned_unsalvaged.append(b)
        return m

    def _published(self) -> bool:
        try:
            return self.app.projects.get(self.project).tier == "published"
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _fold(nodes: List[LoomNode]) -> List[Any]:
        """Cosmetic fold (§7.7.4): a contiguous run of AUTO nodes with
        the same phase collapses to a single '+N' marker. HITL nodes are
        never folded."""
        out: List[Any] = []
        run: List[LoomNode] = []

        def flush():
            if len(run) > 1:
                out.append(("fold", run[0].phase, len(run)))
            elif run:
                out.append(run[0])

        for n in nodes:
            if n.auto and run and run[-1].auto and run[-1].phase == n.phase:
                run.append(n)
            else:
                flush()
                run = [n]
        flush()
        return out

    # ---- TTY (grayscale-legible; glyph authoritative) ---------------

    def render_tty(self, *, color: bool = True) -> str:
        m = self.model()
        use_color = color and not os.environ.get("NO_COLOR")
        snaps = self.app.snapshots(self.project)
        total = sum(len(v) for v in m.nodes.values())
        lines = [f"Loom · {self.project} · {total} snapshot(s)"]
        legend = "  ".join(f"{g} {k}" for k, (g, _a, _h) in _STATUS.items())
        lines.append(f"legend: {legend}   (· fork  * since last view)")
        if total < 3:                       # §7.7.7 tiny → single strip
            strip = []
            for b in m.lanes:
                for n in m.nodes[b]:
                    strip.append(self._tok(n, use_color))
            lines.append("strip: " + " ".join(strip) if strip
                         else "strip: (no snapshots yet)")
            return "\n".join(lines) + "\n"
        for b in m.lanes:
            nodes = m.nodes.get(b, [])
            if not nodes:
                continue
            head_phase = nodes[-1].phase
            tag = "main" if b == "main" else b
            if snaps.is_salvaged(b):
                tag += " [salvaged]"
            elif snaps.is_parked(b):
                tag += " [parked]"
            lines.append(f"\n{tag}  ▸ phase: {head_phase}")
            row = []
            for item in self._fold(nodes):
                if isinstance(item, tuple):
                    row.append(f"⋯+{item[2]} {item[1]}")
                else:
                    row.append(self._tok(item, use_color))
            lines.append("  " + " ─ ".join(row))
        for b in m.abandoned_unsalvaged:
            lines.append(f"\n⚠ branch '{b}' abandoned without salvage — "
                         f"`helix salvage {b}` to capture the learning")
        return "\n".join(lines) + "\n"

    def _tok(self, n: LoomNode, use_color: bool) -> str:
        glyph, letter, hexv = _STATUS[n.status]
        star = "*" if n.since_cursor else ""
        label = n.action if not self._priv() else f"@{n.seq}"
        body = f"{glyph}{star}{n.seq}:{label}"
        if use_color:                       # colour = status ONLY (§7.7.4)
            code = {"active": "", "parked": "2", "salvaged": "2",
                    "published": "1"}.get(n.status, "")
            if code:
                return f"\033[{code}m{body}\033[0m"
        return body                          # glyph carries status w/o colour

    def _priv(self) -> bool:
        try:
            return (self.app.projects.get(self.project).privacy_mode
                    == "strict")
        except Exception:  # noqa: BLE001
            return False

    # ---- SVG (grayscale publication supplement; zero-dep) -----------

    def render_svg(self) -> str:
        m = self.model()
        lane_h, x0, dx = 60, 90, 120
        rows = [b for b in m.lanes if m.nodes.get(b)]
        h = max(120, 60 + lane_h * len(rows))
        w = max(360, x0 + dx * (1 + max((len(m.nodes[b]) for b in rows),
                                        default=1)))
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" '
               f'height="{h}" font-family="monospace" font-size="12">',
               f'<text x="10" y="20" font-size="14">Loom · '
               f'{_esc(self.project)} (grayscale; glyph = status)</text>']
        for li, b in enumerate(rows):
            y = 50 + li * lane_h
            out.append(f'<text x="10" y="{y - 8}" fill="#333">'
                       f'{_esc(b)}{" [parked]" if b in m.abandoned_unsalvaged or self.app.snapshots(self.project).is_parked(b) else ""}</text>')
            prevx = None
            for ni, n in enumerate(m.nodes[b]):
                x = x0 + dx * ni
                glyph, letter, hexv = _STATUS[n.status]
                if prevx is not None:
                    out.append(f'<line x1="{prevx + 14}" y1="{y}" '
                               f'x2="{x - 14}" y2="{y}" stroke="#999"/>')
                out.append(
                    f'<circle cx="{x}" cy="{y}" r="13" fill="none" '
                    f'stroke="{hexv}" stroke-width="2"/>'
                    f'<text x="{x}" y="{y + 4}" text-anchor="middle" '
                    f'fill="{hexv}">{glyph}</text>'
                    f'<text x="{x}" y="{y + 28}" text-anchor="middle" '
                    f'fill="#333">{letter}{n.seq} '
                    f'{_esc("@" + str(n.seq) if m.private else n.action)}'
                    f'</text>')
                prevx = x
        out.append('</svg>')
        return "\n".join(out)


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
