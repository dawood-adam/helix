import pytest

from helix.atlas import AtlasStore, WriteQueue


@pytest.fixture
def store(tmp_path):
    return AtlasStore(tmp_path / "atlas")


@pytest.fixture
def wq(store):
    return WriteQueue(store)


@pytest.fixture
def helix_app(tmp_path):
    from helix.app import Helix

    return Helix(home=tmp_path / "home")


@pytest.fixture
def run(tmp_path):
    """Invoke the `helix` CLI against an isolated home."""
    from click.testing import CliRunner

    from helix.cli import cli

    runner = CliRunner()
    home = str(tmp_path / "home")

    def _run(*args, env=None):
        return runner.invoke(cli, ["--home", home, *args], env=env)

    return _run


@pytest.fixture
def ready_run(run):
    """`run`, with `helix setup` already completed."""
    res = run("setup", "--model", "anthropic:claude-sonnet-4.6")
    assert res.exit_code == 0, res.output
    return run
