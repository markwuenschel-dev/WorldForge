#!/usr/bin/env python3
"""tools.consumers -- the importing games, and the contract every one of them meets.

WHY THIS PACKAGE EXISTS OUTSIDE ``tools/wfcore/``
------------------------------------------------
WorldForge Core owns CAPABILITY. The importing game owns INTENT. That split is
only real if the two live in different places and the boundary between them is
mechanically checked, so consumers live here and Core lives there, and
``tools/core_boundary_proof.py`` proves a consumer run changed nothing on the
other side of the line.

Registering a consumer has a deliberate side effect: ``wfcore.hygiene`` DERIVES
its forbidden vocabulary from the directory names under this package, so creating
``tools/consumers/<consumer_id>/`` automatically bans ``<consumer_id>`` and its
alphabetic stem from every file in Core. The gate therefore gets stricter as the
platform grows -- the only direction a safety gate may drift.

WHAT IS IN HERE
---------------
``adapter``      the contract a thin consumer adapter must meet, plus the two
                 validators that make it enforceable rather than aspirational.
``wfdemo_*/``    WorldForge-authored DEMONSTRATION consumers. They are not real
                 games and they say so in their own provenance records; see
                 ``adapter.ORIGINATION_WORLDFORGE_DEMO`` for why that admission is
                 a validated field and not a comment.
"""

__all__ = ["adapter"]
