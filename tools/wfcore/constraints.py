#!/usr/bin/env python3
"""wfcore.constraints -- the constraint taxonomy every consumer contract speaks.

WHY A TAXONOMY AND NOT A LIST OF RULES
--------------------------------------
An importing game states many things it wants. Those statements are NOT
interchangeable, and flattening them into one "requirements" list destroys the
only information that makes automated planning safe:

  * some statements must hold or the result is WRONG and must be rejected
  * some statements are wishes -- missing them makes the result WORSE, never invalid
  * some statements are directions to optimise along, with no pass/fail at all
  * some statements name things that must NOT happen
  * some statements name things WorldForge must not touch
  * some are numeric ceilings
  * some are the slack allowed when comparing two numbers
  * and some are honest admissions that the consumer does not know yet

If a soft preference can fail a build, consumers learn to stop declaring
preferences. If a hard invariant can be scored away, the platform will happily
ship a world that violates it. So the class is declared per constraint, and the
class -- not the call site -- decides whether it can block acceptance.

THE ONE RULE THAT MATTERS
-------------------------
``ACCEPTANCE_LOAD_BEARING`` is the closed set of classes that may block
acceptance. Acceptance is::

    tri.conj(evaluation(c) for c in constraints
             if c.constraint_class in ACCEPTANCE_LOAD_BEARING)

and it must equal SATISFIED (``tri.accepts``), not merely "not VIOLATED". A soft
preference or an optimisation target is structurally incapable of blocking --
not by convention, but because it is not in the set that the fold reads.

Equally: a hard invariant is structurally incapable of being scored away, because
the scorer only reads the non-load-bearing classes. The two halves cannot leak
into each other, which is the property that makes consumer contracts trustworthy
in both directions.

WHY ``UNKNOWN`` IS A CONSTRAINT CLASS AND NOT AN ABSENCE
--------------------------------------------------------
A consumer that has not decided something should SAY so. The alternative --
omitting the constraint -- is indistinguishable from "this does not matter to
me", and those two have opposite correct behaviours: an omitted constraint is
free to be anything, while an undecided one must block acceptance until it is
resolved. ``DECLARED_UNKNOWN`` makes the difference statable, and it evaluates
to ``tri.UNKNOWN`` by construction -- so it blocks acceptance without ever being
reported as a violation of something that was never measured.

TOLERANCE IS A MODIFIER, NOT A PREDICATE
----------------------------------------
A tolerance has no truth value of its own -- "0.5cm" is neither satisfied nor
violated. It parameterises the comparison inside ANOTHER constraint. It is
therefore not acceptance-load-bearing, and a tolerance that names no target
constraint is a malformed record (WF1205), not a vacuously-true one.
"""

from typing import Any, Dict, List, Optional, Tuple

from . import tri
from .failure import FailureCode as C

# --------------------------------------------------------------------------- #
# schema identity (house convention: wf.<domain>.<thing>.v<N>)
# --------------------------------------------------------------------------- #
RT_CONSTRAINT = "wf.core.constraint.v1"

# --------------------------------------------------------------------------- #
# the eight classes. one source of truth; the contract layer imports these
# rather than re-typing string literals.
# --------------------------------------------------------------------------- #
HARD_INVARIANT = "hard_invariant"
PROHIBITED_OUTCOME = "prohibited_outcome"
PROTECTED_SEMANTICS = "protected_semantics"
BUDGET = "budget"
SOFT_PREFERENCE = "soft_preference"
OPTIMIZATION_TARGET = "optimization_target"
TOLERANCE = "tolerance"
DECLARED_UNKNOWN = "declared_unknown"

CONSTRAINT_CLASSES = (
    HARD_INVARIANT,
    PROHIBITED_OUTCOME,
    PROTECTED_SEMANTICS,
    BUDGET,
    SOFT_PREFERENCE,
    OPTIMIZATION_TARGET,
    TOLERANCE,
    DECLARED_UNKNOWN,
)

# The closed set that may block acceptance. Adding a class here is a semantic
# change to every consumer contract in existence, so it is deliberately a single
# visible tuple rather than a predicate scattered across call sites.
#
# DECLARED_UNKNOWN is in this set on purpose: an undecided constraint must hold
# up acceptance. It evaluates to tri.UNKNOWN, so it blocks via the ordinary fold
# without ever being misreported as a violation.
ACCEPTANCE_LOAD_BEARING = (
    HARD_INVARIANT,
    PROHIBITED_OUTCOME,
    PROTECTED_SEMANTICS,
    BUDGET,
    DECLARED_UNKNOWN,
)

# Classes that feed ranking (provider/plan selection) instead of pass/fail.
SCORING_CLASSES = (SOFT_PREFERENCE, OPTIMIZATION_TARGET)

# Optimisation direction vocabulary.
MINIMIZE = "minimize"
MAXIMIZE = "maximize"
OPTIMIZATION_DIRECTIONS = (MINIMIZE, MAXIMIZE)

# --------------------------------------------------------------------------- #
# record shape
# --------------------------------------------------------------------------- #
CONSTRAINT_REQUIRED = (
    "constraint_id",       # stable, consumer-authored identity
    "constraint_class",    # one of CONSTRAINT_CLASSES
    "subject",             # WHAT the constraint is about, consumer vocabulary
    "detail",              # human-readable statement of the constraint
)

CONSTRAINT_ALLOWED = CONSTRAINT_REQUIRED + (
    "limit",               # BUDGET: numeric ceiling
    "unit",                # BUDGET / TOLERANCE: unit of measure
    "direction",           # OPTIMIZATION_TARGET: minimize | maximize
    "weight",              # SOFT_PREFERENCE / OPTIMIZATION_TARGET: relative weight
    "applies_to",          # TOLERANCE: constraint_id this tolerance parameterises
    "protected_ids",       # PROTECTED_SEMANTICS: identities that must not change
    "resolution_owner",    # DECLARED_UNKNOWN: who must decide, consumer-side
)

Check = Tuple[str, bool, str, Optional[str]]


def is_acceptance_load_bearing(constraint: Dict[str, Any]) -> bool:
    """True when this constraint's CLASS permits it to block acceptance.

    Reads the class, never the constraint's content or its current evaluation:
    whether something *may* block is a property of what kind of statement it is,
    fixed when the consumer authored it. Deciding that per-evaluation is how a
    soft preference eventually acquires the power to fail a build.
    """
    return constraint.get("constraint_class") in ACCEPTANCE_LOAD_BEARING


def evaluate_declared_unknown(_constraint: Dict[str, Any]) -> str:
    """A DECLARED_UNKNOWN always evaluates to UNKNOWN. That is its entire content.

    Separate named function so the behaviour is testable and so no evaluator is
    tempted to "resolve" an unknown by inspecting the observed world. The
    consumer, not WorldForge, owns that resolution -- WorldForge inferring it
    would be the capability layer inventing the domain layer's intent.
    """
    return tri.UNKNOWN


def fold_acceptance(evaluations: List[Tuple[Dict[str, Any], str]]) -> str:
    """Fold (constraint, tri-value) pairs into ONE acceptance tri-value.

    Only acceptance-load-bearing classes are read. Non-load-bearing evaluations
    are ignored here by design -- they are the scorer's input, and letting them
    reach this fold is precisely how a preference becomes a blocker.

    Vacuous case: zero load-bearing constraints folds to SATISFIED, following
    ``tri.conj``'s identity. A consumer request carrying no acceptance-load-
    bearing constraint at all is a malformed REQUEST -- rejected in contract
    validation (WF1202), not silently downgraded to UNKNOWN here, which would
    make the fold non-associative.
    """
    return tri.conj(
        value for (constraint, value) in evaluations
        if is_acceptance_load_bearing(constraint))


def unresolved_blockers(
        evaluations: List[Tuple[Dict[str, Any], str]]) -> List[Dict[str, Any]]:
    """Return the load-bearing constraints that are blocking, WITH their reason.

    Distinguishes VIOLATED from UNKNOWN in the emitted reason. That distinction
    drives repair: a violation is something to fix in the world, while an unknown
    is something to go measure. Conflating them sends the repair planner to
    author a change nobody established was needed.
    """
    out: List[Dict[str, Any]] = []
    for constraint, value in evaluations:
        if not is_acceptance_load_bearing(constraint):
            continue
        if tri.accepts(value):
            continue
        out.append({
            "constraint_id": constraint.get("constraint_id"),
            "constraint_class": constraint.get("constraint_class"),
            "evaluation": value,
            "blocking_reason": (
                "violated_by_observation" if value == tri.VIOLATED
                else "not_evaluated_no_observation_supports_a_verdict"),
        })
    return out


def validate_constraint(constraint: Any, strict: bool = False) -> List[Check]:
    """Validate ONE constraint record. Returns house-shape check tuples.

    Cross-field rails, each of which encodes a way the taxonomy can be abused:
      * a BUDGET without a numeric ``limit`` is not a ceiling, it is a wish
      * an OPTIMIZATION_TARGET without a ``direction`` cannot rank anything
      * a TOLERANCE that names no ``applies_to`` parameterises nothing
      * a PROTECTED_SEMANTICS with an empty ``protected_ids`` protects nothing
        while reading, in a report, as though it protected something
    """
    checks: List[Check] = []

    if not isinstance(constraint, dict):
        checks.append(("constraint_is_object", False,
                       "constraint must be an object, got {}".format(
                           type(constraint).__name__),
                       C.CORE_CONSTRAINT_INVALID))
        return checks

    for fld in CONSTRAINT_REQUIRED:
        present = constraint.get(fld) not in (None, "")
        checks.append(("constraint_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing/empty"),
                       None if present else C.CORE_CONSTRAINT_INVALID))

    klass = constraint.get("constraint_class")
    known = klass in CONSTRAINT_CLASSES
    checks.append(("constraint_class_known", known,
                   "constraint_class {!r} {}".format(
                       klass,
                       "is known" if known
                       else "is not one of {}".format(CONSTRAINT_CLASSES)),
                   None if known else C.CORE_CONSTRAINT_UNKNOWN_CLASS))

    if strict:
        unknown_fields = sorted(set(constraint) - set(CONSTRAINT_ALLOWED))
        ok = not unknown_fields
        checks.append(("constraint_no_unknown_fields", ok,
                       "unexpected field(s) {}".format(unknown_fields)
                       if unknown_fields else "no unexpected fields",
                       None if ok else C.CORE_CONSTRAINT_INVALID))

    if klass == BUDGET:
        limit = constraint.get("limit")
        ok = isinstance(limit, (int, float)) and not isinstance(limit, bool)
        checks.append(("budget_has_numeric_limit", ok,
                       "BUDGET declares limit={!r}; a budget without a numeric "
                       "ceiling cannot be exceeded, so it can never fail and is "
                       "a wish wearing a budget's name".format(limit),
                       None if ok else C.CORE_CONSTRAINT_INVALID))

    if klass == OPTIMIZATION_TARGET:
        direction = constraint.get("direction")
        ok = direction in OPTIMIZATION_DIRECTIONS
        checks.append(("optimization_has_direction", ok,
                       "OPTIMIZATION_TARGET direction={!r}, expected one of {}; "
                       "without a direction there is no ordering to rank by"
                       .format(direction, OPTIMIZATION_DIRECTIONS),
                       None if ok else C.CORE_CONSTRAINT_INVALID))

    if klass == TOLERANCE:
        applies_to = constraint.get("applies_to")
        ok = bool(applies_to)
        checks.append(("tolerance_targets_a_constraint", ok,
                       "TOLERANCE applies_to={!r}; a tolerance has no truth "
                       "value of its own and must name the constraint whose "
                       "comparison it widens".format(applies_to),
                       None if ok else C.CORE_TOLERANCE_WITHOUT_TARGET))

    if klass == PROTECTED_SEMANTICS:
        protected = constraint.get("protected_ids")
        ok = isinstance(protected, (list, tuple)) and len(protected) > 0
        checks.append(("protected_semantics_names_ids", ok,
                       "PROTECTED_SEMANTICS protected_ids={!r}; an empty "
                       "protection set protects nothing while still reading as "
                       "protection in a report".format(protected),
                       None if ok else C.CORE_CONSTRAINT_INVALID))

    return checks


def validate_constraint_set(constraints: Any, strict: bool = False) -> List[Check]:
    """Validate a constraint SET: every member, plus set-level coherence rails."""
    checks: List[Check] = []

    if not isinstance(constraints, (list, tuple)):
        checks.append(("constraint_set_is_list", False,
                       "constraint set must be a list, got {}".format(
                           type(constraints).__name__),
                       C.CORE_CONSTRAINT_INVALID))
        return checks

    for idx, c in enumerate(constraints):
        for (name, ok, detail, code) in validate_constraint(c, strict=strict):
            checks.append(("constraint[{}].{}".format(idx, name), ok, detail, code))

    ids = [c.get("constraint_id") for c in constraints if isinstance(c, dict)]
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    ok = not dupes
    checks.append(("constraint_ids_unique", ok,
                   "duplicate constraint_id(s) {}; a duplicate id makes an "
                   "evaluation ambiguous and lets one record silently shadow "
                   "another".format(dupes) if dupes else "all constraint_ids unique",
                   None if ok else C.CORE_CONSTRAINT_INVALID))

    # A request whose every constraint is non-load-bearing cannot be accepted OR
    # rejected on evidence -- it would fold to vacuous SATISFIED and accept
    # anything. That is a malformed request, caught here rather than at the fold.
    load_bearing = [c for c in constraints
                    if isinstance(c, dict) and is_acceptance_load_bearing(c)]
    ok = len(load_bearing) > 0
    checks.append(("constraint_set_has_load_bearing_member", ok,
                   "{} acceptance-load-bearing constraint(s); a set with none "
                   "folds to vacuous SATISFIED and would accept any world"
                   .format(len(load_bearing)),
                   None if ok else C.CORE_NO_LOAD_BEARING_CONSTRAINT))

    # Every TOLERANCE must point at a constraint that actually exists in this set.
    id_set = {i for i in ids if i is not None}
    dangling = sorted({
        c.get("applies_to") for c in constraints
        if isinstance(c, dict) and c.get("constraint_class") == TOLERANCE
        and c.get("applies_to") not in id_set})
    ok = not dangling
    checks.append(("tolerance_targets_resolve", ok,
                   "tolerance applies_to {} names no constraint in this set"
                   .format(dangling) if dangling
                   else "every tolerance resolves to a constraint in this set",
                   None if ok else C.CORE_TOLERANCE_WITHOUT_TARGET))

    return checks


def _example_constraint(**over: Any) -> Dict[str, Any]:
    """Canonical-valid constraint. ``**over`` spawns the known-bads.

    Deliberately domain-neutral: Core owns no game's vocabulary, so the example
    names a generic measurable rather than any map, actor, or asset.
    """
    d: Dict[str, Any] = {
        "constraint_id": "c_traversable_connectivity",
        "constraint_class": HARD_INVARIANT,
        "subject": "navigation.reachability",
        "detail": "every gameplay anchor must be reachable from the entry anchor",
    }
    d.update(over)
    return d
