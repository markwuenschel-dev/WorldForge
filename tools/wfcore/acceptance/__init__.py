#!/usr/bin/env python3
"""wfcore.acceptance -- judge a produced result against the consumer's criteria.

WHAT THIS LAYER IS FOR
----------------------
Everything upstream of here produces a *claim*: the analysis claims what it
compared, the plan claims what it would change, the delta claims what it did.
This layer is the one place that turns claims into a VERDICT, and it is therefore
the one place where a fake-green is worth the most.

So acceptance here is built out of three refusals rather than one predicate:

1. IT REFUSES TO ACCEPT ON UNKNOWNS. The verdict is ``tri.accepts(fold)``, never
   ``fold != VIOLATED``. Those two differ exactly on the constraints nobody
   measured -- and "everything passed because nothing was measured" is the
   failure this whole package exists against (WF1257).

2. IT REFUSES STALE EVIDENCE. An observation taken under a different operation,
   or taken before the change under judgement landed, describes the PREVIOUS
   world. Folding it accepts a world that no longer exists (WF1258).

3. IT REFUSES TO JUDGE AN UNRELOADED RESULT. An in-memory world can satisfy
   criteria that a saved-and-reloaded one does not, so a judgement with no
   reload-backed observation is refused outright rather than downgraded (WF1259).

And one state it refuses to round off: a delta that is a PARTIAL_COMMIT can never
be accepted, and is reported AS partial rather than as a failure. It is a world
state no contract describes, and calling it "rejected" invites a retry on top of
a half-changed world.

WHAT THIS LAYER DOES NOT DECIDE
-------------------------------
It does not decide which constraints matter (the class does, via
``constraints.ACCEPTANCE_LOAD_BEARING``), and it does not decide what the
consumer wanted (``contracts.acceptance_criteria`` carries that). It re-derives
evidence and folds; every authority it uses belongs to somebody else.

HOUSE STYLE
-----------
stdlib only; ``RT_X = "wf.core.<thing>.v1"``; frozen tuple enums;
``X_REQUIRED`` / ``X_ALLOWED``; ``validate_X(obj, strict=False) -> List[Check]``
with ``Check = (check_name, ok, detail, failure_code)``; ``_example_X(**over)``
factories whose ``**over`` spawns the known-bads.

No consumer vocabulary appears here, including in the examples.
"""

__all__ = [
    "evaluate_acceptance",
]
