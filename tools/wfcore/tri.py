#!/usr/bin/env python3
"""wfcore.tri -- three-valued satisfaction logic (Kleene strong K3).

WHY THREE VALUES AND NOT TWO
----------------------------
A boolean cannot distinguish these two statements:

    "we evaluated the constraint and it does not hold"
    "we could not evaluate the constraint"

Collapsing them is the single most productive source of fake-green in this
repository's history: an unobserved value defaults to ``False``, ``False`` reads
as "no violations found", and a gate goes green on evidence that was never
collected. So satisfaction is a THREE-valued quantity and the third value is
load-bearing.

    SATISFIED  the constraint was evaluated against real observation and holds
    VIOLATED   the constraint was evaluated against real observation and fails
    UNKNOWN    the constraint was NOT evaluated -- no observation supports either
               verdict

THE TWO RULES THAT MAKE IT HONEST
---------------------------------
1. UNKNOWN is never coerced. Not to SATISFIED (that fabricates evidence), and
   not to VIOLATED either (that fabricates a *failure*, which is a different lie
   and corrupts repair: the repair planner would try to fix something that was
   merely unmeasured). ``unknown`` propagates as itself.

2. UNKNOWN BLOCKS ACCEPTANCE. Acceptance requires ``conj(...) is SATISFIED``,
   never ``conj(...) is not VIOLATED``. Those two predicates differ exactly on
   UNKNOWN, and that difference is the whole point.

Rule 2 is why ``accepts()`` exists as a named function rather than being spelled
out at each call site: written by hand, ``!= VIOLATED`` is a one-character
mistake that silently restores two-valued behaviour, and it reads as correct.

KLEENE SEMANTICS
----------------
``conj`` (AND) -- a constraint SET holds only if every member holds:

        AND  | SAT  VIO  UNK
        -----+----------------
        SAT  | SAT  VIO  UNK
        VIO  | VIO  VIO  VIO
        UNK  | UNK  VIO  UNK

    Note ``VIO AND UNK == VIO``: one confirmed violation is decisive regardless
    of what else went unmeasured. This is sound -- a known failure cannot be
    rescued by an unknown -- and it is what lets a plan fail fast without
    collecting every remaining observation.

``disj`` (OR) -- used for alternative satisfaction paths (e.g. a soft preference
satisfiable by any of several providers):

        OR   | SAT  VIO  UNK
        -----+----------------
        SAT  | SAT  SAT  SAT
        VIO  | SAT  VIO  UNK
        UNK  | SAT  UNK  UNK

``neg`` swaps SAT/VIO and fixes UNK. Negation of "we don't know" is still "we
don't know".

IDENTITIES (proved by test_tri.py, not asserted here)
-----------------------------------------------------
* conj is commutative, associative, and has identity SATISFIED
* disj is commutative, associative, and has identity VIOLATED
* de Morgan holds: neg(conj(a,b)) == disj(neg(a), neg(b))
* neg is an involution: neg(neg(a)) == a
* conj of the empty set is SATISFIED (vacuous truth); disj of the empty set is
  VIOLATED. An empty constraint set therefore ACCEPTS -- callers that consider a
  request with zero constraints to be malformed must reject it upstream, in
  contract validation, not here. Silently returning UNKNOWN for the empty case
  would break associativity and make fold order observable.
"""

from typing import Iterable

# --------------------------------------------------------------------------- #
# the three values. plain strings: they cross the JSON evidence boundary
# constantly, and an enum that serialises to something else would need a
# translation layer on both sides -- one more place for the vocabularies to drift.
# --------------------------------------------------------------------------- #
SATISFIED = "satisfied"
VIOLATED = "violated"
UNKNOWN = "unknown"

TRI_VALUES = (SATISFIED, VIOLATED, UNKNOWN)


class TriValueError(ValueError):
    """Raised when a value outside TRI_VALUES enters the logic.

    Deliberately fail-closed and loud. The most likely culprit is a raw ``bool``
    arriving from code that has not been converted -- and ``bool`` is exactly the
    two-valued thinking this module exists to prevent, so it must not be
    silently accepted. Use :func:`from_bool` at the measurement boundary, where
    the author has to state what an unmeasured value means.
    """


def _check(value: str) -> str:
    if value not in TRI_VALUES:
        raise TriValueError(
            "not a tri-value: {!r}. Expected one of {}. If this is a bool, "
            "convert it at the measurement site with from_bool(observed, "
            "measured=...) so the unmeasured case is stated explicitly rather "
            "than defaulting.".format(value, TRI_VALUES))
    return value


def from_bool(observed: bool, measured: bool = True) -> str:
    """Lift a measurement into the tri-logic at the boundary where it is taken.

    ``measured`` is mandatory in spirit: it is the caller's declaration that an
    observation actually happened. ``from_bool(x, measured=False)`` is UNKNOWN
    regardless of ``x``, because an unmeasured value carries no information --
    including when it happens to be ``False``.
    """
    if not measured:
        return UNKNOWN
    return SATISFIED if observed else VIOLATED


def neg(a: str) -> str:
    """Negation. Involutive; UNKNOWN is a fixed point."""
    _check(a)
    if a == SATISFIED:
        return VIOLATED
    if a == VIOLATED:
        return SATISFIED
    return UNKNOWN


def conj(values: Iterable[str]) -> str:
    """Kleene AND over a set. Identity SATISFIED; VIOLATED is absorbing.

    Absorption is what makes evaluation order irrelevant: a single VIOLATED
    fixes the result no matter what follows, so a caller may short-circuit
    without changing the answer.
    """
    saw_unknown = False
    for v in values:
        _check(v)
        if v == VIOLATED:
            return VIOLATED
        if v == UNKNOWN:
            saw_unknown = True
    return UNKNOWN if saw_unknown else SATISFIED


def disj(values: Iterable[str]) -> str:
    """Kleene OR over a set. Identity VIOLATED; SATISFIED is absorbing."""
    saw_unknown = False
    for v in values:
        _check(v)
        if v == SATISFIED:
            return SATISFIED
        if v == UNKNOWN:
            saw_unknown = True
    return UNKNOWN if saw_unknown else VIOLATED


def accepts(value: str) -> bool:
    """The ONLY sanctioned way to turn a tri-value into an accept/reject boolean.

    ``accepts(v)`` is ``v is SATISFIED`` -- deliberately NOT ``v != VIOLATED``.

    The two differ precisely on UNKNOWN, and every fake-green this module exists
    to prevent lives in that gap. Route every acceptance decision through here so
    the choice is made once, in a tested place, instead of being re-typed (and
    eventually mistyped) at each gate.
    """
    _check(value)
    return value == SATISFIED


def blocks_acceptance(value: str) -> bool:
    """True when this value prevents acceptance -- VIOLATED *or* UNKNOWN.

    Distinct from ``not accepts(...)`` only in intent: use this when reporting
    WHY something failed, so the reason string can name unknown-ness as unknown
    instead of laundering it into a violation that was never observed.
    """
    return not accepts(value)
