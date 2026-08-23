#!/usr/bin/env python3
"""wfcore.repair -- turn a non-accepted result into another attempt, or stop.

WHY A DRIVER AND NOT A FIX
--------------------------
The tempting shape for repair is a function per failure: "budget exceeded ->
trim", "invariant violated -> patch". Every one of those is a second code path
that never went through provider selection, never declared a mutation bound,
never got a rollback, and was never tested against the plan validator. It would
be the only unbounded, unrollbackable mutation path in the package -- and it
would be the one that runs when something is already wrong.

So there is no bespoke fix. A repair is synthesised through the SAME generic
planner as the first attempt (WF1267), from an analysis of the SAME kind, and
applied through the same transaction path. This module is only a DRIVER: it
decides whether to go round again, and it refuses to go round again for reasons
that would make the loop prove nothing.

THE FOUR REASONS IT STOPS
-------------------------
    accepted            the acceptance verdict came back SATISFIED
    WF1268 no evidence  it was asked to repair a failure nothing observed
    WF1269 exhausted    the consumer's ``max_revision_attempts`` is spent
    WF1270 not converging  an attempt did not REDUCE the blocker set

The last one is the one that makes the loop honest. Without it, a loop that
swaps blocker A for blocker B runs forever while every attempt reports work
done, a plan executed, and a delta committed. Convergence is therefore measured
as a STRICT SUBSET of the blocker SET -- never as a smaller count, which A-for-B
leaves unchanged, and never as "fewer failure codes", which any rewording moves.

THE DIRECTION THAT IS EASY TO GET BACKWARDS
-------------------------------------------
An UNKNOWN blocker's repair is an OBSERVATION -- go measure it. A VIOLATED
blocker's repair is a MUTATION. Backwards, the loop authors changes to the
consumer's world for constraints nobody established were wrong, and the
measurement that would have said whether they were needed is exactly the step
that was skipped. The driver checks the synthesised plan against the analysis it
came from and refuses when the two disagree.

HOUSE STYLE
-----------
stdlib only; ``RT_X = "wf.core.<thing>.v1"``; frozen tuple enums;
``X_REQUIRED`` / ``X_ALLOWED``; ``validate_X(obj, strict=False) -> List[Check]``
with ``Check = (check_name, ok, detail, failure_code)``; ``_example_X(**over)``
factories whose ``**over`` spawns the known-bads.

Nothing here imports the engine side. The whole loop is driven by injected
callables, so it is exercisable -- and falsifiable -- without an editor.
"""

__all__ = [
    "repair_loop",
]
