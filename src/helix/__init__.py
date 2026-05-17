"""Helix — research co-pilot + knowledge atlas.

This package currently implements the load-bearing persistence core
(Appendix A.1, build order steps 1-3):

  1. Atlas write model + stable ids   (helix.ids, helix.pages, helix.atlas)
  2. Decision-log single source of truth (helix.decisionlog)
  3. Snapshot composite-commit + branches (helix.snapshot)
  4. Model & provider router          (helix.routing)

Everything else in HELIX.md (CLI, queue, agents, retriever, Loom/Prism)
is designed but not yet implemented and is built on top of this core.
"""

__version__ = "0.0.1"
