import pytest

from helix.pages import Page, is_generated_markdown


def test_frontmatter_roundtrip():
    p = Page(
        id="abc", title="Sim-to-Real Imaging", type="concept",
        status="canonical", summary="Training on synthetic data.",
        tags=["imaging", "ml"], body="Body line one.\n\nLine two.",
        referenced_by=["proj:bowel-length"],
    )
    back = Page.from_markdown(p.to_markdown())
    assert back.id == "abc"
    assert back.title == "Sim-to-Real Imaging"
    assert back.type == "concept"
    assert back.status == "canonical"
    assert back.tags == ["imaging", "ml"]
    assert back.referenced_by == ["proj:bowel-length"]
    assert back.body == "Body line one.\n\nLine two."


def test_missing_id_rejected():
    with pytest.raises(ValueError, match="missing required 'id'"):
        Page.from_markdown("---\ntitle: x\ntype: concept\nstatus: scratch\n---\nbody")


def test_invalid_type_and_status_rejected():
    with pytest.raises(ValueError):
        Page(id="a", title="t", type="bogus", status="scratch")
    with pytest.raises(ValueError):
        Page(id="a", title="t", type="concept", status="bogus")


def test_generated_banner_present_and_detected():
    p = Page(id="a", title="Decision log", type="project",
             status="active", generated=True, body="## Decision 1")
    md = p.to_markdown()
    assert "generated: true" in md
    assert "do not edit" in md
    assert is_generated_markdown(md) is True
    # Banner is stripped back out of the stored body on re-parse.
    assert "do not edit" not in Page.from_markdown(md).body


def test_unknown_frontmatter_keys_preserved():
    src = ("---\nid: a\ntitle: t\ntype: concept\nstatus: scratch\n"
           "custom_field: keepme\n---\nbody\n")
    p = Page.from_markdown(src)
    assert p.extra["custom_field"] == "keepme"
    assert "custom_field: keepme" in p.to_markdown()


def test_non_frontmatter_text_rejected():
    with pytest.raises(ValueError, match="no YAML frontmatter"):
        Page.from_markdown("just some text, no fence")
