#!/usr/bin/env python3
"""wfcore.providers -- capability declaration, the registry, and explainable selection.

THE ONE SENTENCE
----------------
A consumer states a RESULT; this package decides which provider can produce it,
and records why that provider and not the others.

    base       what a provider must DECLARE before Core will consider it
    registry   capability -> providers, identity uniqueness, collision reporting
    selection  pick FROM the requested result, with every rejection explained

THE THREE RULES THAT SURVIVE INTO EVERY BUILD
---------------------------------------------
1. Hard statements FILTER; preferences SCORE. The two sets are read from
   ``constraints.ACCEPTANCE_LOAD_BEARING`` and ``constraints.SCORING_CLASSES``,
   which are disjoint -- so a high score can never outvote a hard invariant, and
   a preference can never fail a build.

2. Unevaluable requirements make a provider UNKNOWN. Unknown is not eligible
   (it must not be selected) and is not a failure either (it must not be
   reported as a violated requirement). It is reported as unknown, naming the
   requirement that had no observation.

3. A tie with no declared tiebreak is WF1229, not a pick. An arbitrary pick
   makes builds differ for a reason that appears nowhere in the request and
   cannot be recovered afterwards.

This lane declares and ranks capability. It executes nothing -- Core must be able
to describe a capability it cannot currently run.
"""

__all__ = [
    "base",
    "registry",
    "selection",
]
