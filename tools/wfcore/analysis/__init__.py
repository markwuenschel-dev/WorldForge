#!/usr/bin/env python3
"""wfcore.analysis -- constraint analysis: DESIRED reconciled against OBSERVED.

WHAT THIS LAYER PRODUCES
------------------------
``reconcile`` is the step between "we have two models" and "we have a plan". It
answers, per declared constraint: what was compared, against which measurement,
with what slack, what the three-valued verdict is, and -- when the verdict is not
SATISFIED -- whether the remedy is to GO MEASURE or to CHANGE THE WORLD.

That last distinction is the reason this layer is typed rather than a dict of
booleans. A planner handed "not satisfied" cannot tell an unmeasured constraint
from a violated one, and the two demand opposite actions: one schedules an
observation, the other authors a change. Conflating them makes the planner author
changes nobody established were needed -- confidently, and against a world it
never looked at.

WHAT THIS LAYER REFUSES TO DO
-----------------------------
It refuses to reconcile two models that do not describe the same world. The
difference between unrelated worlds is arithmetically fine and semantically
empty: it reads as a large, confident set of changes to a subject nobody asked
about. ``models.observed_world.validate_model_pair`` is the authority, and the
refusal carries ``CORE_MODEL_IDENTITY_MISMATCH``.

It also refuses to invent the consumer's intent. Where the desired model declares
nothing to compare against, the verdict is UNKNOWN -- never a default that
happens to pass.

HOUSE STYLE
-----------
stdlib only; ``RT_X = "wf.core.<thing>.v1"``; frozen tuple enums;
``X_REQUIRED`` / ``X_ALLOWED``; ``validate_X(obj, strict=False) -> List[Check]``
with ``Check = (check_name, ok, detail, failure_code)``; ``_example_X(**over)``
factories whose ``**over`` spawns the known-bads.

No consumer vocabulary appears here, including in the examples.
"""

__all__ = [
    "reconcile",
]
