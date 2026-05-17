import pytest

from helix.ids import (
    IdIndex,
    PageEntry,
    UnknownReference,
    is_uuid,
    make_handle,
    new_page_id,
    slugify,
    split_ref,
)


def test_new_id_is_uuid():
    pid = new_page_id()
    assert is_uuid(pid)
    assert not is_uuid("concept:foo")


def test_handle_and_slug():
    assert slugify("Sim-to-Real Imaging!") == "sim-to-real-imaging"
    assert make_handle("source", "2024 Zhang Bowel") == "src:2024-zhang-bowel"
    assert make_handle("project", "Bowel Length") == "proj:bowel-length"
    with pytest.raises(ValueError):
        make_handle("nope", "x")


def test_split_ref_fragment():
    assert split_ref("proj:bowel#hypothesis") == ("proj:bowel", "hypothesis")
    assert split_ref("concept:odf") == ("concept:odf", None)


def test_resolve_by_uuid_and_handle(tmp_path):
    idx = IdIndex(tmp_path / "index.json")
    pid = new_page_id()
    idx.register(PageEntry(pid, "concepts/odf.md", 1, "concept",
                            "canonical", "ODF", "concept:odf"))
    assert idx.path_for(pid) == "concepts/odf.md"
    assert idx.path_for("concept:odf") == "concepts/odf.md"
    assert idx.resolve("concept:odf#section").id == pid
    assert idx.has("concept:odf")
    with pytest.raises(UnknownReference):
        idx.resolve("concept:missing")


def test_move_never_breaks_reference(tmp_path):
    """The §6.2 keystone: path changes, id/handle resolution does not."""
    idx = IdIndex(tmp_path / "index.json")
    pid = new_page_id()
    idx.register(PageEntry(pid, "scratch/odf.md", 1, "concept",
                           "scratch", "ODF", "concept:odf"))
    idx.set_path(pid, "concepts/odf.md")
    assert idx.path_for(pid) == "concepts/odf.md"
    assert idx.path_for("concept:odf") == "concepts/odf.md"


def test_persistence_roundtrip(tmp_path):
    p = tmp_path / "index.json"
    idx = IdIndex(p)
    pid = new_page_id()
    idx.register(PageEntry(pid, "concepts/odf.md", 3, "concept",
                           "canonical", "ODF", "concept:odf"))
    idx.save()
    reloaded = IdIndex(p)
    assert reloaded.version_for("concept:odf") == 3
    assert reloaded.resolve(pid).title == "ODF"


def test_handle_collision_rejected(tmp_path):
    idx = IdIndex(tmp_path / "index.json")
    idx.register(PageEntry("id1", "a.md", 1, "concept", "scratch",
                           "ODF", "concept:odf"))
    with pytest.raises(ValueError, match="already maps"):
        idx.register(PageEntry("id2", "b.md", 1, "concept", "scratch",
                               "ODF", "concept:odf"))
