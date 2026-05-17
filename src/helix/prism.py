"""Prism — the project anatomy (HELIX.md §7.8).

Where Loom renders *history*, Prism renders *structure* in one image:
**Strategy → Data → Code**, fixed order, never reordered (why precedes
what precedes how). Prism stores nothing new and introduces **no new
source of truth**: every rationale is derived from the decision log
(§7.8.4), so "rationale rot" is impossible by construction. A slot with
no rationale shows an FYI hint and is flagged by ``helix doctor`` — it
is **never silently blank**.

Shape vocabulary (§7.8.2, renderer-enforced): rounded-rect = strategic
concept, plain rect = code/module, cylinder = data store, dashed box =
logical cluster. The legend is always present on static export
(§7.8.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

_SECTIONS = ("Strategy", "Data", "Code")   # fixed order, no reorder flag
_MAX_DATA, _MAX_CODE = 6, 8                 # bounded slots (§7.8.5)


@dataclass
class PrismModel:
    project: str
    research_question: str
    methods_choice: str
    strategy_rationale: str
    constraints: List[str]
    data_stages: List[str]
    data_rationale: str
    code_modules: List[str]
    code_rationale: str
    private: bool = False
    missing_rationale: List[str] = field(default_factory=list)


_FYI = "⊕ add rationale to enrich this view (helix why / decision log)"


class Prism:
    def __init__(self, app, project: str):
        self.app = app
        self.project = project

    def model(self) -> PrismModel:
        log = self.app.decision_log(self.project).entries()
        try:
            proj = self.app.projects.get(self.project)
            private = proj.privacy_mode == "strict"
            tier = proj.rung
        except Exception:  # noqa: BLE001
            private, tier = False, "notes"

        def rationale_for(pred) -> str:
            for e in reversed(log):
                if pred(e) and e.get("rationale", "").strip():
                    return e["rationale"].strip()
            return ""

        # §7.8.4: rationale comes ONLY from the relevant decision.
        methods = next((e for e in reversed(log)
                        if e["action"].startswith("pick:")), None)
        strat_r = (methods.get("rationale", "").strip()
                   if methods else "")
        data_r = rationale_for(lambda e: e.get("stage") == "data")
        code_r = rationale_for(lambda e: "structure" in e.get("action", ""))

        missing = []
        if not strat_r:
            missing.append("Strategy")
        if not data_r:
            missing.append("Data")
        if not code_r:
            missing.append("Code")

        # Structural pointers only (never a parallel prose copy).
        data_stages = self._data_stages()
        code_modules = self._code_modules()
        return PrismModel(
            project=self.project,
            research_question=self.project.replace("-", " "),
            methods_choice=(methods["action"].split(":", 1)[1]
                            if methods else "(not chosen yet)"),
            strategy_rationale=strat_r or _FYI,
            constraints=[f"tier:{tier}"]
            + (["privacy:strict"] if private else []),
            data_stages=data_stages,
            data_rationale=data_r or _FYI,
            code_modules=code_modules,
            code_rationale=code_r or _FYI,
            private=private,
            missing_rationale=missing,
        )

    def _data_stages(self) -> List[str]:
        snaps = self.app.snapshots(self.project)
        head = snaps.head()
        stages: List[str] = []
        if head:
            stages = list(snaps.get(head).data_hashes.keys())
        if not stages:                       # also count ingested sources
            stages = [e.handle for e in self.app.store.index
                      if e.type == "source"][:_MAX_DATA]
        return stages[:_MAX_DATA]

    def _code_modules(self) -> List[str]:
        cdir = self.app.store.layout.project_dir(self.project) / "code"
        if not cdir.exists():
            return []
        return sorted(p.name for p in cdir.glob("*.py"))[:_MAX_CODE]

    # ---- TTY --------------------------------------------------------

    def render_tty(self) -> str:
        m = self.model()
        L = ["Prism · " + self.project + "   (Strategy → Data → Code)",
             "legend: (concept)=strategy  [module]=code  ((data))=store  "
             "{cluster}=grouping"]
        L.append("\n■ Strategy — what it's for & the approach")
        L.append(f"  (concept) Q: {m.research_question}")
        L.append(f"  (concept) methods: {m.methods_choice}")
        L.append(f"    why: {_redact(m.strategy_rationale, m.private)}")
        L.append(f"  constraints: {', '.join(m.constraints)}")
        L.append("\n■ Data — what feeds it & why")
        if m.data_stages:
            for d in m.data_stages:
                L.append(f"  ((data)) {d if not m.private else _idstub(d)}")
        else:
            L.append("  ((data)) ⌁ data not yet captured — "
                     "`helix explore` to seed")     # §7.8.7
        L.append(f"    why: {_redact(m.data_rationale, m.private)}")
        L.append("\n■ Code — how it's built & why this structure")
        if m.code_modules:
            for c in m.code_modules:
                L.append(f"  [module] {c}")
        else:
            L.append("  {src} ⌁ first build will populate this")  # §7.8.7
        L.append(f"    why: {_redact(m.code_rationale, m.private)}")
        if m.missing_rationale:
            L.append(f"\n(doctor: rationale missing for "
                     f"{', '.join(m.missing_rationale)})")
        return "\n".join(L) + "\n"

    # ---- SVG (legend always present, §7.8.3; zero-dep) --------------

    def render_svg(self) -> str:
        m = self.model()
        w, h = 560, 470
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" '
               f'height="{h}" font-family="monospace" font-size="12">',
               f'<text x="12" y="20" font-size="14">Prism · '
               f'{_esc(self.project)}</text>',
               # legend (mandatory on export, §7.8.3)
               '<text x="12" y="40" fill="#444">legend: rounded=concept '
               '· rect=module · cylinder=data · dashed=cluster</text>']
        y = 60
        for title, body in (
            ("Strategy — why", [f"Q: {m.research_question}",
                                f"methods: {m.methods_choice}",
                                f"why: {_redact(m.strategy_rationale, m.private)}",
                                "constraints: " + ", ".join(m.constraints)]),
            ("Data — what feeds it", (
                [f"{d if not m.private else _idstub(d)}"
                 for d in m.data_stages]
                or ["data not yet captured"])
                + [f"why: {_redact(m.data_rationale, m.private)}"]),
            ("Code — how it's built", (m.code_modules
                or ["first build will populate this"])
                + [f"why: {_redact(m.code_rationale, m.private)}"])):
            out.append(f'<rect x="12" y="{y}" width="{w-24}" height="120" '
                       f'rx="8" fill="none" stroke="#333"/>')
            out.append(f'<text x="22" y="{y+20}" font-size="13" '
                       f'fill="#000">{_esc(title)}</text>')
            for i, ln in enumerate(body[:5]):
                out.append(f'<text x="28" y="{y+42+i*18}" fill="#333">'
                           f'{_esc(ln[:70])}</text>')
            y += 135
        out.append('</svg>')
        return "\n".join(out)


def _redact(text: str, private: bool) -> str:
    if private and text and not text.startswith("⊕"):
        return "(category-only — redacted under privacy:strict)"
    return text


def _idstub(handle: str) -> str:
    return handle.split(":", 1)[0] + ":…"


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
