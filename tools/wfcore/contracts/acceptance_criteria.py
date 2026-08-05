#!/usr/bin/env python3
"""wfcore.contracts.acceptance_criteria -- how the consumer decides "yes".

Acceptance here is a FOLD, not a score. The verdict is
``constraints.fold_acceptance`` over the acceptance-load-bearing members of a
declared constraint set, and it must come out ``tri.SATISFIED`` -- never merely
"not VIOLATED". There is deliberately no threshold, no percentage, and no
weighted total anywhere in this module: the moment acceptance becomes a number,
a hard invariant can be outvoted by enough soft preferences, and the consumer's
non-negotiables become negotiable without anyone editing them.

THE THREE RAILS THAT DO THE REAL WORK
-------------------------------------
1. ``every_load_bearing_constraint_is_evaluable`` (WF1202). A load-bearing
   constraint with no evaluation requirement is never measured, so it folds
   UNKNOWN forever and acceptance can never be reached. The criteria look
   complete; the pipeline simply never finishes. Catching it at authoring time
   costs one check; catching it in production costs a run that ends in an unknown
   nobody can resolve.

2. ``must_block_ids_are_load_bearing`` (WF1204). A consumer naming a
   SOFT_PREFERENCE among the things it expects to block acceptance has a false
   model of its own contract -- the fold does not read that class, and it never
   will. Failing here tells the consumer the truth once, instead of letting it
   discover, after a bad world ships, that the thing it thought was a gate was a
   ranking hint.

3. ``unknown_handling_blocks``. The vocabulary contains only blocking values, on
   purpose. If a consumer could declare "treat unknown as satisfied", every
   guarantee in ``wfcore.tri`` would be available to opt out of, and the option
   would be taken by whoever was closest to a deadline.

WHY ``acceptance_verdict`` DEFAULTS A MISSING EVALUATION TO UNKNOWN
--------------------------------------------------------------------
Not to SATISFIED, obviously. But also not by SKIPPING it: dropping an unevaluated
constraint from the fold silently shrinks the set being checked, and ``conj`` of
the survivors returns SATISFIED. That is the fake-green this architecture is
built against, and it arrives as a one-line "filter out the ones we don't have
data for" that reads like housekeeping.
"""

from typing import Any, Dict, List, Tuple

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from . import (Check, check_enum, check_is_object, check_no_unknown,
               check_required, check_schema_version, check_str, prefixed,
               require_caller_owned)

RT_ACCEPTANCE_CRITERIA = "wf.core.acceptance_criteria.v1"

# How a constraint is to be evaluated. The consumer states this per constraint so
# that "unevaluated" is a schedulable gap rather than a mystery.
EVIDENCE_KINDS = (
    "static_analysis",
    "authoring_time_check",
    "runtime_observation",
    "human_review",
    "external_measurement",
)

# Every member blocks. The tuple has more than one entry only to distinguish
# "stop" from "stop and go measure it"; there is no non-blocking value here and
# adding one would make every guarantee in wfcore.tri optional.
UNKNOWN_HANDLINGS = ("block", "block_and_request_measurement")

EVALUATION_REQUIREMENT_REQUIRED = ("constraint_id", "evidence_kind")
EVALUATION_REQUIREMENT_ALLOWED = EVALUATION_REQUIREMENT_REQUIRED + (
    "evaluator", "detail", "notes",
)

ACCEPTANCE_CRITERIA_REQUIRED = (
    "criteria_id",
    "consumer_id",
    "request_id",
    "constraints",
    "evaluation_requirements",
    "must_block_ids",
    "unknown_handling",
    "schema_version",
)
ACCEPTANCE_CRITERIA_ALLOWED = ACCEPTANCE_CRITERIA_REQUIRED + (
    "created_by", "created_at", "report_type", "meta", "notes",
)

# The criteria ARE the consumer's definition of "good enough", and ``request_id``
# binds them to the specific ask they judge. Core supplying either would mean Core
# grading its own homework against a standard it wrote.
CALLER_OWNED_FIELDS = ("criteria_id", "consumer_id", "request_id", "constraints")

_P = "acc::"


def validate_acceptance_criteria(obj: Any, strict: bool = False) -> List[Check]:
    code = C.CORE_ACCEPTANCE_CRITERIA_INVALID
    ch = check_is_object(obj, code, _P, "acceptance_criteria")
    if ch:
        return ch

    ch += check_required(obj, ACCEPTANCE_CRITERIA_REQUIRED, code, _P)
    ch += check_no_unknown(obj, ACCEPTANCE_CRITERIA_ALLOWED, code, _P, strict)
    for fld in ("criteria_id", "consumer_id", "request_id"):
        ch += check_str(obj, fld, code, _P)
    ch += check_schema_version(obj, RT_ACCEPTANCE_CRITERIA, code, _P)
    ch += check_enum(obj, "unknown_handling", UNKNOWN_HANDLINGS, code, _P)

    # One authority for constraint shape; this module folds its checks in.
    ch += prefixed(K.validate_constraint_set(obj.get("constraints"), strict=strict),
                   _P + "constraints.")

    ch += _rail_evaluation_requirements(obj, code)
    ch += _rail_must_block_ids(obj, code)
    return ch


def _constraint_index(obj: Dict[str, Any]) -> Dict[Any, Dict[str, Any]]:
    return {c.get("constraint_id"): c
            for c in (obj.get("constraints") or []) if isinstance(c, dict)}


def _rail_evaluation_requirements(obj: Dict[str, Any], code: str) -> List[Check]:
    """Every load-bearing constraint must have a way to be evaluated."""
    out: List[Check] = []
    reqs = obj.get("evaluation_requirements")
    if not isinstance(reqs, (list, tuple)):
        return [(_P + "evaluation_requirements_is_list", False,
                 "evaluation_requirements must be a list, got {}".format(
                     type(reqs).__name__), code)]

    index = _constraint_index(obj)

    for idx, r in enumerate(reqs):
        p = "{}evaluation[{}].".format(_P, idx)
        if not isinstance(r, dict):
            out.append((p + "is_object", False,
                        "evaluation requirement must be an object, got {}".format(
                            type(r).__name__), code))
            continue
        out += check_required(r, EVALUATION_REQUIREMENT_REQUIRED, code, p)
        out += check_str(r, "constraint_id", code, p)
        out += check_enum(r, "evidence_kind", EVIDENCE_KINDS, code, p)

    dangling = sorted({
        r.get("constraint_id") for r in reqs
        if isinstance(r, dict) and r.get("constraint_id") not in index}, key=str)
    ok = not dangling
    out.append((_P + "evaluation_requirements_resolve", ok,
                "evaluation requirement(s) name constraint_id(s) {} that are not "
                "in this criteria's constraint set; the evidence would be "
                "collected for something nothing accepts on".format(dangling)
                if dangling else "every evaluation requirement resolves to a "
                                 "constraint in this set",
                None if ok else code))

    evaluated = {r.get("constraint_id") for r in reqs if isinstance(r, dict)}
    # DECLARED_UNKNOWN is exempt: it evaluates to tri.UNKNOWN BY CONSTRUCTION and
    # is resolved by the consumer deciding, not by Core measuring. Demanding an
    # evidence kind for it would ask Core to go observe the consumer's own
    # undecided intent -- which is the authority inversion, wearing a check.
    unevaluable = sorted(
        (cid for cid, c in index.items()
         if cid is not None
         and K.is_acceptance_load_bearing(c)
         and c.get("constraint_class") != K.DECLARED_UNKNOWN
         and cid not in evaluated), key=str)
    ok = not unevaluable
    out.append((_P + "every_load_bearing_constraint_is_evaluable", ok,
                "acceptance-load-bearing constraint(s) {} have no evaluation "
                "requirement; nothing will ever measure them, so they fold "
                "UNKNOWN forever and acceptance can never be reached -- the "
                "criteria read complete while the pipeline simply never "
                "finishes".format(unevaluable) if unevaluable
                else "every load-bearing constraint has an evaluation "
                     "requirement",
                None if ok else C.CORE_CONSTRAINT_NOT_EVALUATED))
    return out


def _rail_must_block_ids(obj: Dict[str, Any], code: str) -> List[Check]:
    """The consumer's expectation of what can block must match what CAN block."""
    out: List[Check] = []
    must_block = obj.get("must_block_ids")
    if not isinstance(must_block, (list, tuple)):
        return [(_P + "must_block_ids_is_list", False,
                 "must_block_ids must be a list (use [] to state no explicit "
                 "expectation), got {}".format(type(must_block).__name__), code)]

    index = _constraint_index(obj)

    dangling = sorted({i for i in must_block if i not in index}, key=str)
    ok = not dangling
    out.append((_P + "must_block_ids_resolve", ok,
                "must_block_ids names {} which are not constraints in this set"
                .format(dangling) if dangling
                else "every must_block_id resolves to a constraint in this set",
                None if ok else code))

    not_load_bearing = sorted(
        "{}:{}".format(i, index[i].get("constraint_class"))
        for i in must_block
        if i in index and not K.is_acceptance_load_bearing(index[i]))
    ok = not not_load_bearing
    out.append((_P + "must_block_ids_are_load_bearing", ok,
                "must_block_ids names {} whose class is not in "
                "ACCEPTANCE_LOAD_BEARING {}; the acceptance fold does not read "
                "those classes and never will, so the consumer believes it has a "
                "gate where it has a ranking hint".format(
                    not_load_bearing, K.ACCEPTANCE_LOAD_BEARING)
                if not_load_bearing
                else "every must_block_id is an acceptance-load-bearing class",
                None if ok else C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION))
    return out


def acceptance_verdict(criteria: Dict[str, Any],
                       evaluations_by_id: Dict[str, str]
                       ) -> Tuple[str, List[Dict[str, Any]]]:
    """Fold declared constraints + observed evaluations into ONE verdict.

    Returns ``(tri_value, blockers)``. The verdict comes from
    ``constraints.fold_acceptance`` and the blockers from
    ``constraints.unresolved_blockers`` -- neither is reimplemented here, so the
    class-authority rules hold by construction rather than by this module
    remembering them.

    A constraint with no entry in ``evaluations_by_id`` is folded as
    ``tri.UNKNOWN``. It is NOT skipped: skipping shrinks the set and lets the
    survivors fold to SATISFIED, which is precisely the fake-green this whole
    layer exists to make impossible.

    Callers turn the verdict into a decision with ``tri.accepts(verdict)`` --
    never ``verdict != VIOLATED``, which differs exactly on the unknowns.
    """
    pairs: List[Tuple[Dict[str, Any], str]] = []
    for c in (criteria.get("constraints") or []):
        if not isinstance(c, dict):
            continue
        value = evaluations_by_id.get(c.get("constraint_id"), tri.UNKNOWN)
        pairs.append((c, value))
    return K.fold_acceptance(pairs), K.unresolved_blockers(pairs)


def build_acceptance_criteria(**over: Any) -> Dict[str, Any]:
    """Build criteria. ``CALLER_OWNED_FIELDS`` are REQUIRED -- no defaults.

    ``unknown_handling`` defaults to ``"block"`` because that is Core's rule, not
    the consumer's preference: there is no other legal value, and offering the
    choice would imply one exists.
    """
    require_caller_owned(over, CALLER_OWNED_FIELDS, "acceptance_criteria")
    d: Dict[str, Any] = dict(
        evaluation_requirements=[],
        must_block_ids=[],
        unknown_handling="block",
        schema_version=RT_ACCEPTANCE_CRITERIA,
        report_type=RT_ACCEPTANCE_CRITERIA,
    )
    d.update(over)
    return d


def _example_acceptance_criteria(**over: Any) -> Dict[str, Any]:
    """Canonical-valid criteria. ``**over`` spawns the known-bads.

    Mirrors ``world_request._example_world_request``'s constraint set so the pair
    can be read together: the same ids, judged here.
    """
    d: Dict[str, Any] = dict(
        criteria_id="criteria_placeholder_0001",
        consumer_id="consumer_placeholder",
        request_id="request_placeholder_0001",
        constraints=[
            {
                "constraint_id": "afford_traversal_spine",
                "constraint_class": K.HARD_INVARIANT,
                "subject": "afford_traversal_spine",
                "detail": ("a continuous traversable route must connect the entry "
                           "landmark to every landmark in the objective role"),
            },
            {
                "constraint_id": "c_generation_budget",
                "constraint_class": K.BUDGET,
                "subject": "generation.wall_clock",
                "detail": "generation must complete within the stated budget",
                "limit": 900,
                "unit": "seconds",
            },
            {
                "constraint_id": "c_silhouette_variety",
                "constraint_class": K.SOFT_PREFERENCE,
                "subject": "composition.silhouette_variety",
                "detail": "prefer varied skyline silhouettes over uniform ones",
                "weight": 0.4,
            },
        ],
        evaluation_requirements=[
            {
                "constraint_id": "afford_traversal_spine",
                "evidence_kind": "runtime_observation",
                "evaluator": "navigation reachability probe",
            },
            {
                "constraint_id": "c_generation_budget",
                "evidence_kind": "external_measurement",
            },
        ],
        must_block_ids=["afford_traversal_spine", "c_generation_budget"],
        unknown_handling="block",
    )
    d.update(over)
    return build_acceptance_criteria(**d)
