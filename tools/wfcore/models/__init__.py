#!/usr/bin/env python3
"""wfcore.models -- the typed world models Core reasons over.

THREE MODELS, TWO OF WHICH MUST NEVER BE CONFUSED
-------------------------------------------------
``desired_world``   the world the consumer WANTS. AUTHORED from a request.
``observed_world``  the world as MEASURED. NEVER authored, under any pressure.
``graphs``          the experience graph (ordered consumer-facing beats and their
                    connectivity) and the environmental-state graph (states and
                    the transitions between them permitted), with honest
                    three-valued reachability over both.

WHY THE DESIRED/OBSERVED SPLIT IS A HARD BOUNDARY AND NOT A NAMING CONVENTION
-----------------------------------------------------------------------------
Planning is ``difference(desired, observed) -> plan``. That subtraction is only
meaningful if the right-hand operand is a measurement. If any part of the
observed model can be authored -- defaulted, zero-filled, or copied from the
request -- then the difference silently shrinks toward zero and the planner
concludes the world already matches. The plan comes back empty or trivial, the
gate goes green, and nothing was ever built. Every fake-green in this
repository's history reduces to that shape.

So the two models are deliberately NOT the same type with a flag:

* a desired field is a plain value, because intent needs no evidence;
* an observed field is an ``ObservedField`` record -- a value that CANNOT be
  written down without simultaneously naming what observed it, in which
  operation, and against which evidence entries.

There is no provenance value in ``observed_world`` meaning "the caller told me".
That omission is the design: a caller-supplied value has a home already (the
desired model), and giving it a home in the observed model is precisely how a
request gets laundered into a measurement.

IDENTITY IS PART OF BOTH, AND IT IS MEASURED ON THE OBSERVED SIDE
------------------------------------------------------------------
Differencing two models that describe DIFFERENT worlds produces a plausible,
entirely meaningless plan -- it will read as a large, confident set of changes.
So both models carry a world identity, the observed one carries it as an
observed field (read back out of the world, never copied from the request), and
:func:`wfcore.models.observed_world.validate_model_pair` refuses the pair when
they disagree (``CORE_MODEL_IDENTITY_MISMATCH``) or when the observed identity
was never established (``CORE_OBSERVED_WORLD_UNBACKED``). Those are different
facts and they carry different codes.

HOUSE STYLE
-----------
stdlib only; ``RT_X = "wf.core.<thing>.v1"``; frozen tuple enums;
``X_REQUIRED`` / ``X_ALLOWED``; ``validate_X(obj, strict=False) -> List[Check]``
with ``Check = (check_name, ok, detail, failure_code)``; ``_example_X(**over)``
factories whose ``**over`` spawns the known-bads.

No consumer vocabulary appears here, including in the examples. Core owns
capability; the importing game owns intent, and a Core example that names a
caller's content has already chosen a subject nobody asked for.
"""

__all__ = [
    "desired_world",
    "observed_world",
    "graphs",
]
