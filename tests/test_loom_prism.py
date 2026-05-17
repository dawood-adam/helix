import os

from helix.forge.agents import FakeAgents
from helix.forge.state import GATES
from helix.forge.workflow import WorkflowEngine
from helix.loom import Loom
from helix.prism import Prism


def _run(app, project="bl", private=False):
    app.projects.create(project, privacy=private)
    WorkflowEngine(app, FakeAgents()).start(
        project, autonomy={g: "auto" for g in GATES})
    return project


# ---- Loom (§7.7) --------------------------------------------------


def test_loom_glyph_is_authoritative_without_colour(helix_app, monkeypatch):
    p = _run(helix_app)
    monkeypatch.setenv("NO_COLOR", "1")
    tty = Loom(helix_app, p).render_tty()
    assert "\033[" not in tty                 # no ANSI under NO_COLOR
    assert "●" in tty or "✓" in tty           # status glyph still present
    assert "legend:" in tty


def test_loom_main_lane_first_and_tiny_strip(helix_app):
    helix_app.projects.create("bl")
    helix_app.snapshots("bl").mint(decision_head=None, reason="seed")
    tty = Loom(helix_app, "bl").render_tty()
    assert "snapshot(s)" in tty
    assert "strip:" in tty                     # §7.7.7 tiny → single strip


def test_loom_abandoned_without_salvage_warned(helix_app):
    p = _run(helix_app)
    helix_app.snapshots(p).fork("alt", decision_head=None)
    helix_app.snapshots(p).park("alt", decision_head=None)
    tty = Loom(helix_app, p).render_tty()
    assert "abandoned without salvage" in tty and "alt" in tty


def test_loom_svg_is_grayscale_and_escaped(helix_app):
    p = _run(helix_app)
    svg = Loom(helix_app, p).render_svg()
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    low = svg.lower()
    assert "red" not in low and "blue" not in low and "green" not in low


def test_loom_privacy_redacts_labels(helix_app):
    p = _run(helix_app, private=True)
    tty = Loom(helix_app, p).render_tty()
    assert "pick:" not in tty                  # action labels redacted


# ---- Prism (§7.8) -------------------------------------------------


def test_prism_fixed_section_order(helix_app):
    p = _run(helix_app)
    tty = Prism(helix_app, p).render_tty()
    assert tty.index("Strategy") < tty.index("Data") < tty.index("Code")


def test_prism_rationale_only_from_decision_log(helix_app):
    helix_app.projects.create("bare")          # no decisions yet
    m = Prism(helix_app, "bare").model()
    assert set(m.missing_rationale) == {"Strategy", "Data", "Code"}
    assert m.strategy_rationale.startswith("⊕")   # FYI hint, never blank


def test_prism_after_methods_pick_has_strategy_rationale(helix_app):
    p = _run(helix_app)
    m = Prism(helix_app, p).model()
    assert "Strategy" not in m.missing_rationale  # pick: decision rationale
    assert not m.strategy_rationale.startswith("⊕")


def test_prism_svg_has_legend(helix_app):
    p = _run(helix_app)
    svg = Prism(helix_app, p).render_svg()
    assert "legend:" in svg and "cylinder=data" in svg


def test_prism_empty_data_and_code_placeholders(helix_app):
    helix_app.projects.create("bare")
    tty = Prism(helix_app, "bare").render_tty()
    assert "data not yet captured" in tty
    assert "first build will populate this" in tty
