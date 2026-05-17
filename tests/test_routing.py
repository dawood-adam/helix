import pytest

from helix.routing import (
    ModelRef,
    PrivacyUnsatisfiable,
    Router,
    UnknownProvider,
    UnresolvableRole,
    default_config_toml,
)


@pytest.fixture
def cfg(tmp_path):
    return tmp_path / "models.toml"


def write(path, text):
    path.write_text(text)
    return Router(path)


# ---- ModelRef ------------------------------------------------------


def test_modelref_splits_on_first_colon_only():
    r = ModelRef.parse("local:qwen2.5-coder:32b")
    assert r.provider == "local" and r.model == "qwen2.5-coder:32b"
    assert str(r) == "local:qwen2.5-coder:32b"
    assert ModelRef.parse("anthropic:claude-sonnet-4.6").model == \
        "claude-sonnet-4.6"


@pytest.mark.parametrize("bad", ["", "noseparator", "anthropic:", ":model"])
def test_modelref_invalid(bad):
    with pytest.raises(ValueError):
        ModelRef.parse(bad)


# ---- precedence (§11.2) -------------------------------------------


def test_resolution_precedence(cfg):
    r = write(cfg, """
[default]
model = "anthropic:claude-sonnet-4.6"
[roles]
builder = "openai:gpt-5"
[project.bowel-length.roles]
builder = "local:qwen2.5-coder:32b"
""")
    # default wins for an unset role
    assert r.resolve("planner").source == "default"
    assert str(r.resolve("planner").ref) == "anthropic:claude-sonnet-4.6"
    # role default beats global default
    assert r.resolve("builder").source == "role"
    # per-project beats role default
    pr = r.resolve("builder", project="bowel-length")
    assert pr.source == "project"
    assert str(pr.ref) == "local:qwen2.5-coder:32b"
    # per-step flag beats everything
    st = r.resolve("builder", project="bowel-length",
                   step_override="openai:gpt-5-mini")
    assert st.source == "step" and str(st.ref) == "openai:gpt-5-mini"


def test_builtin_provider_needs_only_default(cfg):
    r = write(cfg, '[default]\nmodel = "anthropic:claude-sonnet-4.6"\n')
    res = r.resolve("explore")
    assert r.provider("anthropic").key_env == "ANTHROPIC_API_KEY"
    assert res.source == "default" and not res.degraded


def test_unknown_provider_fails_closed(cfg):
    r = write(cfg, '[default]\nmodel = "mystery:x"\n')
    with pytest.raises(UnknownProvider):
        r.resolve("explore")


def test_unresolvable_role_fails_closed(cfg):
    r = write(cfg, "# empty\n")
    with pytest.raises(UnresolvableRole):
        r.resolve("explore")


# ---- privacy (§9.9) -----------------------------------------------


def test_privacy_strict_blocks_api_model_when_no_fallback(cfg):
    r = write(cfg, '[default]\nmodel = "anthropic:claude-sonnet-4.6"\n')
    with pytest.raises(PrivacyUnsatisfiable):
        r.resolve("explore", privacy_strict=True)


def test_privacy_strict_substitutes_and_records_degradation(cfg):
    r = write(cfg, """
[default]
model = "anthropic:claude-sonnet-4.6"
[privacy]
model = "local:qwen2.5:32b"
""")
    res = r.resolve("explore", privacy_strict=True)
    assert res.source == "privacy"
    assert str(res.ref) == "local:qwen2.5:32b"
    assert res.degraded and str(res.degraded_from) == \
        "anthropic:claude-sonnet-4.6"


def test_privacy_strict_keeps_local_model_untouched(cfg):
    r = write(cfg, '[default]\nmodel = "local:qwen2.5:32b"\n')
    res = r.resolve("explore", privacy_strict=True)
    assert res.source == "default" and not res.degraded


def test_privacy_strict_accepts_zdr_provider(cfg):
    r = Router(cfg)
    r.add_provider("acme", key_env="ACME_KEY", zdr=True)
    r.set_global("acme:big-model")
    res = r.resolve("explore", privacy_strict=True)
    assert not res.degraded and res.source == "default"


def test_privacy_fallback_must_itself_be_private(cfg):
    r = write(cfg, """
[default]
model = "anthropic:claude-sonnet-4.6"
[privacy]
model = "openai:gpt-5"
""")
    with pytest.raises(PrivacyUnsatisfiable, match="not local/ZDR"):
        r.resolve("explore", privacy_strict=True)


# ---- readiness (helix doctor) -------------------------------------


def test_readiness_missing_api_key(cfg):
    r = write(cfg, '[default]\nmodel = "anthropic:claude-sonnet-4.6"\n')
    res = r.resolve("explore")
    rd = r.readiness(res, env={})
    assert not rd.ok and "ANTHROPIC_API_KEY" in rd.reason


def test_readiness_api_key_present(cfg):
    r = write(cfg, '[default]\nmodel = "anthropic:claude-sonnet-4.6"\n')
    rd = r.readiness(r.resolve("explore"), env={"ANTHROPIC_API_KEY": "sk-x"})
    assert rd.ok


def test_readiness_local_probe(cfg):
    r = write(cfg, '[default]\nmodel = "local:qwen2.5:7b"\n')
    res = r.resolve("explore")
    assert r.readiness(res).ok                                  # no probe
    assert not r.readiness(res, probe=lambda p: False).ok       # unreachable


# ---- resolve_all + reproducibility hook (§7.3) --------------------


def test_resolve_all_covers_every_role(cfg):
    from helix.routing import ROLES
    r = write(cfg, '[default]\nmodel = "anthropic:claude-sonnet-4.6"\n')
    routing, degraded = r.resolve_all()
    assert set(routing) == set(ROLES)
    assert degraded == []


def test_resolve_all_reports_degraded_roles_under_privacy(cfg):
    r = write(cfg, """
[default]
model = "anthropic:claude-sonnet-4.6"
[roles]
builder = "local:qwen2.5-coder:32b"
[privacy]
model = "local:qwen2.5:32b"
""")
    routing, degraded = r.resolve_all(privacy_strict=True)
    assert "builder" not in degraded            # already local
    assert "explore" in degraded                # was anthropic -> substituted
    assert routing["builder"] == "local:qwen2.5-coder:32b"


def test_routing_feeds_snapshot_reproducibly(store, cfg):
    """§7.3: the resolved routing recorded in a Snapshot round-trips so
    `helix repro` reruns a point with the same models."""
    from helix.snapshot import SnapshotStore
    r = write(cfg, '[default]\nmodel = "anthropic:claude-sonnet-4.6"\n')
    routing, _ = r.resolve_all(project="bowel-length")
    s = SnapshotStore("bowel-length", store.layout)
    snap = s.mint(decision_head="bowel-length#decision-1",
                  model_routing=routing, reason="gate_methods")
    assert snap.verify()
    assert SnapshotStore("bowel-length", store.layout).get(
        snap.id).model_routing == routing


# ---- mutators + canonical TOML writer -----------------------------


def test_mutators_round_trip_through_toml(cfg):
    r = Router(cfg)
    r.set_global("anthropic:claude-sonnet-4.6")
    r.set_role("critic-methods", "openai:gpt-5")
    r.set_project_role("bowel-length", "builder", "local:qwen2.5-coder:32b")
    r.set_privacy_model("local:qwen2.5:32b")
    r.add_provider("openrouter", key_env="OPENROUTER_API_KEY",
                   base_url="https://openrouter.ai/api/v1")
    # Reload from disk: the writer must be sound and re-parseable.
    fresh = Router(cfg)
    assert fresh.config.default_model == "anthropic:claude-sonnet-4.6"
    assert fresh.resolve("critic-methods").source == "role"
    assert str(fresh.resolve("builder", project="bowel-length").ref) == \
        "local:qwen2.5-coder:32b"
    assert fresh.config.privacy_model == "local:qwen2.5:32b"
    assert fresh.provider("openrouter").base_url == \
        "https://openrouter.ai/api/v1"


def test_default_config_toml_is_minimal_and_resolves(tmp_path):
    p = tmp_path / "models.toml"
    p.write_text(default_config_toml("local:qwen2.5:32b"))
    r = Router(p)
    assert str(r.resolve("explore").ref) == "local:qwen2.5:32b"
    with pytest.raises(ValueError):
        default_config_toml("not-a-ref")
