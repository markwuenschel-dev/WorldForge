#!/usr/bin/env python3
"""wfcore.transaction -- the bounded, transactional world delta and its executor.

THE ONE SENTENCE
----------------
A plan step declares WHAT IT MAY TOUCH; this package makes that declaration
enforceable against what a provider ACTUALLY touched, and makes the undo path
something that is measured rather than asserted.

    delta      the WorldDelta record: what was really created/modified/deleted,
               by which step and provider, with a before-state sufficient to undo
               each one -- plus the validators over its shape and coherence
    executor   apply a delta under the single-writer lock, refuse anything
               outside the bound, roll back in reverse order on failure, and
               re-observe to decide whether the rollback actually worked

THE FOUR THINGS THIS PACKAGE REFUSES TO ROUND OFF
-------------------------------------------------
1. THE BOUND IS CHECKED AGAINST WHAT HAPPENED, NOT WHAT WAS INTENDED.
   Checking a mutation's declared target against its own declared bound is
   circular -- it can only ever pass. The bound is therefore enforced against the
   set of targets the SINK reports it actually wrote, after each apply. A provider
   that quietly touches one extra package is exactly the case the declaration
   exists to catch, and it is the only case a declared-target check cannot see.

2. ROLLBACK COMPLETENESS IS RE-OBSERVED, NEVER INFERRED FROM THE UNDO CALL.
   ``undo()`` returning success is the undo's own opinion of itself. After every
   undo the executor re-observes the target and compares it to the captured
   before-state; that comparison, and nothing else, decides the status. An undo
   that reports success and restores nothing must be caught, because that is the
   failure mode that turns a rollback into a silent partial commit.

3. PARTIAL COMMIT IS ITS OWN OUTCOME AND IS NEVER ROUNDED.
   A transaction whose rollback could not fully restore is neither committed nor
   rolled back. Reporting it as either is a lie about the state of the world, and
   both lies are load-bearing: "committed" invites the caller to build on content
   that is half-undone, "rolled back" invites it to retry from a base that no
   longer exists. ``is_committed`` and ``is_rolled_back`` both return False for it.

4. AN UNVERIFIED COMMIT IS A CLAIM, NOT A RESULT.
   A commit with no post-observation has had its postconditions ASSERTED rather
   than MEASURED. It is reported as its own outcome carrying
   ``CORE_DELTA_UNVERIFIED``, never as a plain success -- the whole point of the
   three-valued logic in ``wfcore.tri`` is that "we did not look" must not be
   spendable as "it was fine".

TESTABLE WITHOUT AN EDITOR, BY CONSTRUCTION
-------------------------------------------
All engine contact is behind ``MutationSink`` (observe / apply / undo / report
what was touched). This package ships an in-memory implementation and imports no
engine module. An engine-backed sink is a later, separate piece of work; nothing
here may grow a dependency on one, because a transaction rail that can only be
exercised with a live editor open is a rail that stops being exercised.
"""

__all__ = [
    "delta",
    "executor",
]
