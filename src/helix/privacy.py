"""Privacy modes — a defined degradation, not a flag flip (§9.9).

``helix init <name> --private`` specifies *exactly* what changes:

* **Agent stack downgraded and recorded.** Strict mode forces the
  model router (§11.2) to resolve every role to a ``local:`` or
  zero-data-retention provider; the substituted set is *surfaced* on
  the project so the quality trade-off is visible, never silent.
* **Write boundary (the one genuinely directional rule).** Private
  content is never folded into a ``canonical``-page write — a
  write-classification, not a bespoke retriever (§9.9). Salvage of a
  private line stays non-canonical; the Watcher won't fold a private
  source into canonical; the Maintainer won't *suggest* promoting a
  concept any private project touched.
* **No auto-promotion.** Private concepts must be manually abstracted
  first; their pages carry a ``private`` banner.

The read boundary needs no special machinery (§9.9): strict mode
already forced every role local/ZDR, so nothing the retriever returns
can leave the machine by construction.
"""

from __future__ import annotations

from typing import List, Set, Tuple


class PrivacyViolation(RuntimeError):
    """A would-be private→canonical contamination, blocked (§9.9)."""


class Privacy:
    def __init__(self, app):
        self.app = app

    def is_strict(self, project: str) -> bool:
        try:
            return self.app.projects.get(project).privacy_mode == "strict"
        except Exception:  # noqa: BLE001
            return False

    def degraded(self, project: str) -> Tuple[dict, List[str]]:
        """(resolved routing, degraded role list) under strict mode —
        the §9.9 'substituted set ... shown on the project'. Empty list
        when the project is normal."""
        if not self.is_strict(project):
            return {}, []
        try:
            return self.app.router.resolve_all(
                project=project, privacy_strict=True)
        except Exception as e:  # noqa: BLE001 — surfaced, not silent
            return {}, [f"<privacy unsatisfiable: {e}>"]

    def projects_touching(self, concept_handle: str) -> Set[str]:
        out: Set[str] = set()
        for p in self.app.projects.list():
            for e in self.app.decision_log(p.name).entries():
                if concept_handle in [str(x) for x in e.get("evidence", [])]:
                    out.add(p.name)
        return out

    def concept_is_private(self, concept_handle: str) -> bool:
        """True if ANY project that used this concept is strict — so it
        must be manually abstracted before it can become canonical."""
        return any(self.is_strict(p)
                   for p in self.projects_touching(concept_handle))

    def guard_canonical(self, project: str, what: str) -> None:
        """Raise if writing ``what`` to canonical would fold private
        content out of its boundary (§9.9 directional write rule)."""
        if self.is_strict(project):
            raise PrivacyViolation(
                f"{what}: project '{project}' is privacy=strict — private "
                f"content is never auto-folded into canonical knowledge; "
                f"manual abstraction is required first (§9.9)")
