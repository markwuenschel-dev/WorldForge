#!/usr/bin/env python3
"""wfcore.planning -- the typed generation/revision plan, and how one is synthesised.

THE ONE SENTENCE
----------------
A plan is a PROMISE about what will change, written down before anything changes,
in a shape the transaction executor can hold the execution to.

    plan    the record: steps, their order, and the bound each one may touch
    synth   turn a constraint analysis into that record -- and only that record

WHAT THE PLAN LAYER IS FOR
--------------------------
Between "the world does not satisfy the contract" and "the world has been
changed" there must be a written, checkable artifact. Without it, three questions
have no answer after the fact: what was allowed to change, why this provider ran,
and what exactly must be undone if it goes wrong. The plan answers all three
BEFORE execution, which is the only time the answers can still be enforced.

THE FOUR RULES THAT SURVIVE INTO EVERY EXECUTION
------------------------------------------------
1. ``expected_changed_packages`` + ``expected_changed_actors`` are THE mutation
   bound. A step that mutates and enumerates nothing cannot be rolled back
   completely -- there is no list of what to undo -- so it is rejected at
   authoring time rather than discovered mid-transaction.

2. VIOLATED is the only thing a mutating step may address. An UNKNOWN
   constraint's remedy is to MEASURE it; turning one into a change authors work
   nobody established was needed, and the measurement that would have said so is
   exactly what was skipped.

3. Providers are SELECTED, never named. A step carries the selection result that
   produced its provider, so "why this one?" is answerable months later from the
   plan alone.

4. Step order is DERIVED and deterministic. A plan whose execution order depends
   on how its steps happened to be assembled makes a failure non-reproducible,
   which makes it undiagnosable.

This lane authors and validates plans. It executes nothing.
"""

__all__ = [
    "plan",
    "synth",
]
