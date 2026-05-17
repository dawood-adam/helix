"""Regression for security review Vuln 1 — path traversal / arbitrary
file write via an unsanitized ``project`` (notably the web surface).

Pre-fix: `project_dir("../evil")` returned a path outside root,
`_write_file` had no containment, and `POST /resolve` had no project
guard — so two token-authenticated requests created files outside the
Atlas root. These assertions fail without the fix.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from helix.atlas.store import AtlasStore, UnsafePath
from helix.forge.agents import FakeAgents
from helix.forge.workflow import WorkflowEngine


@pytest.mark.parametrize("bad", [
    "../evil", "../../tmp/x", "..", ".", "", "a/b", "a\\b",
    ".hidden", "x/../../../etc",
])
def test_project_dir_rejects_traversal(store, bad):
    with pytest.raises(UnsafePath):
        store.layout.project_dir(bad)


def test_project_dir_allows_normal_names(store):
    # Guard against over-blocking legitimate names.
    for ok in ("bowel-length", "p1", "single-vector", "demo_2"):
        p = store.layout.project_dir(ok)
        assert p.name == ok and "projects" in p.parts


def test_write_file_containment(store):
    with pytest.raises(UnsafePath):
        store._write_file("../escape.md", "x")
    with pytest.raises(UnsafePath):
        store._write_file("projects/../../escape.md", "x")
    store._write_file("concepts/ok.md", "fine")          # normal still works
    assert (store.root / "concepts" / "ok.md").read_text() == "fine"


def test_projects_exists_is_total_for_unsafe_names(helix_app):
    # A predicate must not raise; an unsafe name simply isn't a project.
    assert helix_app.projects.exists("../../etc") is False
    assert helix_app.projects.exists("") is False


def _serve(app):
    from helix.web import serve
    httpd, url, token = serve(app, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, url.split("/?")[0], token


def test_web_resolve_blocks_path_traversal(helix_app, tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_AGENTS", "fake")
    # A real, interrupted project so the legit path is live.
    helix_app.projects.create("real")
    WorkflowEngine(helix_app, FakeAgents()).start("real")   # pauses at gate

    httpd, base, token = _serve(helix_app)
    try:
        pwn = tmp_path / "helix_pwn"                 # outside the Atlas root
        traversal = f"../../../../../../../../../..{pwn}"
        # The 2-request exploit, now blocked at the boundary → 404.
        for _ in range(2):
            req = urllib.request.Request(
                f"{base}/resolve?t={token}", method="POST",
                data=f"project={traversal}&option=approve&why=x".encode())
            try:
                urllib.request.urlopen(req)
                assert False, "expected 404"
            except urllib.error.HTTPError as e:
                assert e.code == 404
        assert not pwn.exists(), "traversal wrote outside the Atlas root"

        # /gate path-form traversal also blocked.
        try:
            urllib.request.urlopen(f"{base}/gate/{traversal}?t={token}")
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404

        # The legitimate project still resolves (guard not over-broad).
        ok = urllib.request.urlopen(urllib.request.Request(
            f"{base}/resolve?t={token}", method="POST",
            data=b"project=real&option=approve&why=ok"))
        assert ok.status == 200
        assert json.loads(ok.read())["status"] in (
            "interrupted", "running", "done")
    finally:
        httpd.shutdown()
