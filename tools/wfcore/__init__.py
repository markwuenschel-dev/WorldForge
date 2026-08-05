#!/usr/bin/env python3
"""wfcore — WorldForge Core: the game-agnostic world-generation/authoring kernel.

WHAT THIS PACKAGE IS
--------------------
The reusable flow, end to end:

    consumer profile + world request
      -> desired-world model
      -> observed-world model
      -> constraint analysis
      -> typed generation/revision plan
      -> provider selection
      -> bounded transactional world delta
      -> Unreal authoring
      -> save, reload, runtime validation
      -> acceptance evaluation
      -> evidence-driven repair
      -> accepted playable result

THE BOUNDARY THIS PACKAGE DEFENDS
---------------------------------
WorldForge owns CAPABILITY. The importing game owns INTENT.

Concretely, and enforced by ``wfcore.hygiene``: nothing under ``tools/wfcore/``
may name a specific game, map, actor, faction, biome, or asset. A default that
names a caller's content is not a convenience -- it is WorldForge silently
choosing a subject nobody asked for, which makes the resulting work meaningless.
Consumers live OUTSIDE Core, under ``tools/consumers/<consumer_id>/``.

That separation is also what makes the Core claim FALSIFIABLE: a second,
substantially different consumer must drive this same flow with an empty
``git diff -- tools/wfcore/``. A Core that needs editing per consumer is not a
platform; it is a pile of special cases wearing one.

HOUSE STYLE (matches tools/pipeline/*_contract*.py)
---------------------------------------------------
* stdlib only -- no jsonschema, no third-party deps at runtime
* frozen tuple enums; one source of truth per vocabulary
* ``validate_X(obj, strict=False) -> List[Check]`` where
  ``Check = (check_name, ok, detail, failure_code)`` -- the exact shape the
  existing ``ValidationReport.check`` consumes, so Core validators drop into the
  existing gates without adaptation
* ``_example_X(**over)`` canonical-valid factories; ``d.update(over)`` spawns the
  known-bads the negative suites need

There is exactly ONE failure-code authority in this repository
(``tools/pipeline/failure_codes.py``). ``wfcore.failure`` re-exports it rather
than defining a second one -- see the module docstring there for why.

ANTI-FAKE-GREEN
---------------
Satisfaction is THREE-valued (``wfcore.tri``): SATISFIED / VIOLATED / UNKNOWN.
An unknown is never coerced to satisfied, and never quietly rewritten as
violated either -- it is carried as unknown and it BLOCKS acceptance. A gate that
cannot tell the difference between "we checked and it held" and "we could not
check" is not a gate.
"""

__all__ = [
    "tri",
    "constraints",
    "failure",
    "hygiene",
    "contracts",
    "models",
    "providers",
]
