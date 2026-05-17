"""The Atlas page model — YAML frontmatter + markdown body (HELIX.md §6.2).

Every page carries stable ``id`` frontmatter (the real identity, §6.2).
Derived files (the decision-log narrative, Loom/Prism exports) carry
``generated: true`` and a do-not-edit banner; the write model treats
human saves to those specially instead of clobbering (§7.2).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

PAGE_TYPES = {"concept", "entity", "method", "source", "project", "scratch"}
STATUS_TIERS = {"scratch", "active", "canonical", "published", "archived"}

_FENCE = "---"
GENERATED_BANNER = (
    "<!-- generated from a canonical source — do not edit. "
    "Edits are intercepted and offered back as a fold suggestion (HELIX.md §7.2). -->"
)
PRIVATE_BANNER = (
    "<!-- PRIVATE (privacy=strict, HELIX.md §9.9): never leaves the "
    "machine; not auto-promotable to canonical — manually abstract first. -->"
)


def _today() -> str:
    return _dt.date.today().isoformat()


@dataclass
class Page:
    """An Atlas page. ``id`` is identity; ``path`` is incidental (§6.2)."""

    id: str
    title: str
    type: str
    status: str
    body: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    created: str = field(default_factory=_today)
    updated: str = field(default_factory=_today)
    referenced_by: List[str] = field(default_factory=list)
    generated: bool = False
    private: bool = False                       # §9.9 privacy banner
    # Any extra frontmatter keys are preserved round-trip rather than dropped.
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in PAGE_TYPES:
            raise ValueError(f"invalid page type: {self.type!r}")
        if self.status not in STATUS_TIERS:
            raise ValueError(f"invalid status tier: {self.status!r}")

    # ---- serialization ----------------------------------------------

    def frontmatter(self) -> Dict[str, Any]:
        fm: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "status": self.status,
            "summary": self.summary,
            "tags": list(self.tags),
            "created": self.created,
            "updated": self.updated,
            "referenced_by": list(self.referenced_by),
        }
        if self.generated:
            fm["generated"] = True
        if self.private:
            fm["private"] = True
        fm.update(self.extra)
        return fm

    def to_markdown(self) -> str:
        fm = yaml.safe_dump(
            self.frontmatter(), sort_keys=False, default_flow_style=False
        ).strip()
        parts = [_FENCE, fm, _FENCE, ""]
        if self.generated:
            parts += [GENERATED_BANNER, ""]
        if self.private:
            parts += [PRIVATE_BANNER, ""]
        parts.append(self.body.strip() + "\n" if self.body.strip() else "")
        return "\n".join(parts)

    @classmethod
    def from_markdown(cls, text: str) -> "Page":
        fm, body = _split_frontmatter(text)
        if "id" not in fm:
            raise ValueError("page is missing required 'id' frontmatter")
        known = {
            "id", "title", "type", "status", "summary", "tags",
            "created", "updated", "referenced_by", "generated", "private",
        }
        extra = {k: v for k, v in fm.items() if k not in known}
        # Strip the banners back out of the stored body.
        body = body.replace(GENERATED_BANNER, "", 1)
        body = body.replace(PRIVATE_BANNER, "", 1).strip()
        return cls(
            id=str(fm["id"]),
            title=str(fm.get("title", "")),
            type=str(fm.get("type", "scratch")),
            status=str(fm.get("status", "scratch")),
            body=body,
            summary=str(fm.get("summary", "")),
            tags=list(fm.get("tags") or []),
            created=str(fm.get("created") or _today()),
            updated=str(fm.get("updated") or _today()),
            referenced_by=list(fm.get("referenced_by") or []),
            generated=bool(fm.get("generated", False)),
            private=bool(fm.get("private", False)),
            extra=extra,
        )


def _split_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    """Parse ``---``-fenced YAML frontmatter; return ``(frontmatter, body)``."""
    stripped = text.lstrip()
    if not stripped.startswith(_FENCE):
        raise ValueError("page has no YAML frontmatter")
    # Drop everything up to the first fence, then split on the closing fence.
    after_open = stripped[len(_FENCE):].lstrip("\n")
    end = after_open.find("\n" + _FENCE)
    if end == -1:
        raise ValueError("unterminated frontmatter (missing closing '---')")
    fm_text = after_open[:end]
    body = after_open[end + len("\n" + _FENCE):].lstrip("\n")
    fm = yaml.safe_load(fm_text) or {}
    if not isinstance(fm, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return fm, body


def is_generated_markdown(text: str) -> bool:
    """True if a markdown blob declares ``generated: true`` (§7.2)."""
    try:
        fm, _ = _split_frontmatter(text)
    except ValueError:
        return False
    return bool(fm.get("generated", False))
