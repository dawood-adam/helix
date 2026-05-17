"""Step-14 opt-in upgrades: privacy, PI co-sign, CAS, registry, web."""

import json
import threading
import urllib.request

import pytest

from helix.atlas.writequeue import Intent
from helix.cas import CAS, project_data_hashes
from helix.cosign import CoSign
from helix.forge.agents import FakeAgents
from helix.forge.state import GATES
from helix.forge.workflow import WorkflowEngine
from helix.maintainer import AttestationIncomplete, Maintainer
from helix.pages import PRIVATE_BANNER, Page
from helix.privacy import Privacy
from helix.salvage import Salvager
from helix.upgrades import REGISTRY, UpgradeNotConfigured, by_id, status_lines


# ---- §9.9 privacy degradation -------------------------------------


def test_private_banner_round_trips():
    p = Page(id="a", title="t", type="concept", status="active",
             private=True, body="x")
    md = p.to_markdown()
    assert PRIVATE_BANNER in md and "private: true" in md
    back = Page.from_markdown(md)
    assert back.private is True and PRIVATE_BANNER not in back.body


def test_salvage_of_private_project_stays_non_canonical(helix_app):
    helix_app.projects.create("sec", privacy=True)
    WorkflowEngine(helix_app, FakeAgents()).start("sec")
    helix_app.snapshots("sec").fork("alt", decision_head=None)
    r = Salvager(helix_app).salvage("sec", "alt", reason="dead")
    page, _ = helix_app.store.read_page(r.canonical_handle)
    assert page.status == "active"            # NOT canonical (§9.9)
    assert page.private is True
    # a normal project DOES canonicalise
    helix_app.projects.create("open")
    WorkflowEngine(helix_app, FakeAgents()).start("open")
    helix_app.snapshots("open").fork("alt", decision_head=None)
    r2 = Salvager(helix_app).salvage("open", "alt")
    assert helix_app.store.read_page(r2.canonical_handle)[0].status == \
        "canonical"


def test_maintainer_skips_promote_for_private_touched_concept(helix_app):
    helix_app.wq.submit(Intent(op="create", payload={
        "type": "concept", "title": "Shared C", "status": "active",
        "body": "x"}))
    helix_app.projects.create("pub")
    helix_app.projects.create("sec", privacy=True)
    for proj in ("pub", "sec"):
        helix_app.decision_log(proj).append(
            stage="methods", action="pick:a", rationale="r",
            evidence=["concept:shared-c"])
    promos = [s for s in Maintainer(helix_app).suggestions()
              if s.kind == "promote"]
    assert not any("shared-c" in s.command for s in promos)  # §9.9


# ---- §13 PI co-sign ------------------------------------------------


def test_cosign_required_is_opt_in_only(helix_app):
    helix_app.projects.create("plain")
    helix_app.projects.create("reg", pi="Dr Shin")
    helix_app.projects.create("phi", privacy=True)
    cs = CoSign(helix_app)
    assert cs.required("plain") is False      # no paternalism (§9.3)
    assert cs.required("reg") is True
    assert cs.required("phi") is True


def test_cosign_pending_sign_and_freeze_block(helix_app):
    helix_app.projects.create("reg", pi="Dr Shin")
    eng = WorkflowEngine(helix_app, FakeAgents())
    eng.start("reg")
    for _ in range(6):
        st = eng.pending("reg")
        if st["status"] != "interrupted":
            break
        eng.resume("reg", st["gate"].get("recommended", "approve"), "ok")
    cs = CoSign(helix_app)
    assert cs.pending("reg"), "human decisions must await co-sign"
    with pytest.raises(AttestationIncomplete):
        Maintainer(helix_app).freeze("reg")   # blocked until co-signed
    signed = cs.sign("reg", "Dr Shin")
    assert signed and not cs.pending("reg")
    # attestation is in the canonical log
    assert any(e["action"] == "cosign"
               for e in helix_app.decision_log("reg").entries())
    Maintainer(helix_app).freeze("reg")       # now permitted


def test_plain_project_freeze_not_blocked(helix_app):
    helix_app.projects.create("plain")
    WorkflowEngine(helix_app, FakeAgents()).start(
        "plain", autonomy={g: "auto" for g in GATES})
    Maintainer(helix_app).freeze("plain")     # no co-sign nag


# ---- §7.6 content-addressed store ---------------------------------


def test_cas_roundtrip_and_dedup(helix_app):
    cas = CAS(helix_app.store.layout)
    h1 = cas.put_bytes(b"weights-v1")
    h2 = cas.put_bytes(b"weights-v1")
    assert h1 == h2 and h1.startswith("sha256:")
    assert cas.has(h1) and cas.get(h1) == b"weights-v1"
    assert cas.get("sha256:deadbeef") is None


def test_project_data_hashes_only_binds_real_artifacts(helix_app):
    helix_app.projects.create("bl")
    # Nothing on disk yet → honestly empty (no fabricated hashes).
    assert project_data_hashes(helix_app, "bl") == {}
    pdir = helix_app.store.layout.project_dir("bl")
    (pdir / "results").mkdir(parents=True, exist_ok=True)
    (pdir / "results" / "latest.json").write_text('{"error": 0.05}')
    hashes = project_data_hashes(helix_app, "bl")
    assert "results" in hashes and hashes["results"].startswith("sha256:")
    assert CAS(helix_app.store.layout).has(hashes["results"])


def test_workflow_binds_data_hashes_when_results_exist(helix_app):
    helix_app.projects.create("bl")
    pdir = helix_app.store.layout.project_dir("bl")
    (pdir / "results").mkdir(parents=True, exist_ok=True)
    (pdir / "results" / "latest.json").write_text('{"error": 0.04}')
    WorkflowEngine(helix_app, FakeAgents()).start(
        "bl", autonomy={g: "auto" for g in GATES})
    snaps = helix_app.snapshots("bl").all()
    assert any(s.data_hashes for s in snaps), "real data not bound (§7.6)"
    from helix import vc
    assert vc.repro(helix_app, "bl", snaps[-1].id)["data_hashes"]


# ---- §11.1 upgrade registry (honest, fail-closed) -----------------


def test_registry_and_status():
    ids = {u.id for u in REGISTRY}
    assert {"explore-futurehouse", "builder-claude-code",
            "checkpointer-postgres", "qr-image"} <= ids
    lines = "\n".join(status_lines())
    assert "built-in" in lines and "available" in lines


def test_unconfigured_upgrade_fails_closed_not_faked(monkeypatch):
    monkeypatch.delenv("FUTUREHOUSE_API_KEY", raising=False)
    with pytest.raises(UpgradeNotConfigured) as e:
        by_id("explore-futurehouse").require()
    assert "FUTUREHOUSE_API_KEY" in str(e.value)
    # the explore seam selects it and fails closed (never fake papers)
    from helix.explore import ExploreError, make_backend
    with pytest.raises((UpgradeNotConfigured, ExploreError)):
        make_backend("futurehouse").search("q", limit=3)


def test_cli_freeze_blocked_is_clean_not_a_traceback(ready_run):
    ready_run("init", "reg", "--pi", "Dr Shin")
    ready_run("run", "reg", env={"HELIX_AGENTS": "fake"})
    for _ in range(6):
        st = ready_run("reg", "--approve", env={"HELIX_AGENTS": "fake"})
        if "complete" in st.output or "deferred" in st.output \
                or "blocked" in st.output:
            break
    r = ready_run("freeze", "reg")
    assert r.exit_code != 0
    assert "await PI co-sign" in r.output         # clean ClickException
    assert "Traceback" not in r.output            # not a raw crash
    ok = ready_run("reg", "--cosign", "--as", "Dr Shin")
    assert "co-signed" in ok.output
    assert ready_run("freeze", "reg").exit_code == 0


def test_helix_upgrades_cli(ready_run):
    out = ready_run("upgrades")
    assert out.exit_code == 0
    assert "Opt-in upgrades" in out.output
    assert "never fabricates" in out.output


# ---- §11 minimal mobile/QR web view -------------------------------


def test_web_view_token_auth_and_resolve(helix_app):
    helix_app.projects.create("bl")
    WorkflowEngine(helix_app, FakeAgents()).start("bl")   # gate pending
    from helix.web import serve

    httpd, url, token = serve(helix_app, port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = url.split("/?")[0]
        # missing token → 403, never leaks the queue
        try:
            urllib.request.urlopen(base + "/queue")
            assert False, "expected 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # paired → queue JSON (NEEDS YOU NOW has the gate)
        q = json.loads(urllib.request.urlopen(
            f"{base}/queue?t={token}").read())
        assert "NEEDS YOU NOW" in q
        # one-tap resolve advances the workflow
        body = b"project=bl&option=approve&why=ok"
        req = urllib.request.Request(f"{base}/resolve?t={token}",
                                     data=body, method="POST")
        res = json.loads(urllib.request.urlopen(req).read())
        assert res["status"] in ("interrupted", "running", "done")
    finally:
        httpd.shutdown()
