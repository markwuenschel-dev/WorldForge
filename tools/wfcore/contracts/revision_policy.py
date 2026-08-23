#!/usr/bin/env python3
"""wfcore.contracts.revision_policy -- what Core may change, and what it may not.

A generation request is cheap to get wrong: nothing existed before, so the worst
outcome is wasted work. A REVISION is not, because the input is the consumer's
finished content. The policy is therefore an ALLOW-LIST, not a deny-list:
``permitted_mutations`` enumerates everything Core is authorised to do, and
anything absent from it is refused. A deny-list would fail open on every mutation
kind invented after the policy was written -- and the mutation kinds Core grows
next year are exactly the ones no consumer has had the chance to think about.

``prohibited_mutations`` therefore exists as a REDUNDANT statement, not as the
mechanism. It is worth carrying anyway: it records intent ("we thought about
terrain and said no"), and it lets this validator catch a policy that permits and
prohibits the same thing -- a contradiction that would otherwise be resolved by
whichever list a future reader consults first.

WHY PROTECTED SEMANTICS MUST CARRY THE PROTECTED_SEMANTICS CLASS
-----------------------------------------------------------------
``protected_semantics`` holds constraint records, and every one of them must have
``constraint_class == PROTECTED_SEMANTICS``. That is not bookkeeping. Only classes
in ``ACCEPTANCE_LOAD_BEARING`` can block acceptance; a SOFT_PREFERENCE sitting in
the protected list would be structurally incapable of stopping anything, while
reading -- in the policy, in a report, to a human -- as protection. It would be
scored, weighed against other preferences, and traded away. So the class mismatch
is WF1204, the class-authority violation, and it fails the policy outright.

WHY AN UNPROTECTED POLICY MUST SAY SO OUT LOUD
-----------------------------------------------
A policy with no protected content and no protected semantics is legal: "change
whatever you need to" is a real thing a consumer may mean. But it is
indistinguishable from a policy where somebody forgot to fill the section in, and
those two have opposite consequences. So it must be stated
(``unprotected_acknowledged: true``) rather than inferred from two empty lists.
"""

from typing import Any, Dict, List

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from . import (Check, check_bool, check_enum, check_int, check_is_object,
               check_no_unknown, check_required, check_schema_version,
               check_str, check_str_list, prefixed, require_caller_owned)

RT_REVISION_POLICY = "wf.core.revision_policy.v1"

# The closed set of things Core can be authorised to do to existing content.
# Structural verbs only -- what changes, never which of the consumer's things.
MUTATION_KINDS = (
    "add_geometry",
    "remove_geometry",
    "move_geometry",
    "replace_surface_material",
    "adjust_terrain_height",
    "adjust_lighting",
    "add_population",
    "remove_population",
    "move_population",
    "adjust_navigation",
    "adjust_volumes",
    "adjust_audio",
    "retag_metadata",
)

ROLLBACK_GRANULARITIES = ("per_mutation", "per_transaction", "whole_revision",
                          "none")

ROLLBACK_REQUIRED_FIELDS = ("rollback_required", "rollback_granularity",
                            "max_revision_attempts")

REVISION_POLICY_REQUIRED = (
    "policy_id",
    "consumer_id",
    "permitted_mutations",
    "prohibited_mutations",
    "protected_content",
    "protected_semantics",
    "rollback",
    "schema_version",
)
REVISION_POLICY_ALLOWED = REVISION_POLICY_REQUIRED + (
    "unprotected_acknowledged",
    "created_by",
    "created_at",
    "report_type",
    "meta",
    "notes",
)

# ``permitted_mutations`` and ``protected_content`` are the two halves of the
# consumer's authorisation, and ``protected_content`` names the consumer's own
# assets. Core defaulting either one would be Core writing its own permission
# slip -- in the permitted case granting itself powers, in the protected case
# deciding on the consumer's behalf that nothing needs protecting.
CALLER_OWNED_FIELDS = ("policy_id", "consumer_id", "permitted_mutations",
                       "protected_content")

_P = "rp::"


def validate_revision_policy(obj: Any, strict: bool = False) -> List[Check]:
    code = C.CORE_REVISION_POLICY_INVALID
    ch = check_is_object(obj, code, _P, "revision_policy")
    if ch:
        return ch

    ch += check_required(obj, REVISION_POLICY_REQUIRED, code, _P)
    ch += check_no_unknown(obj, REVISION_POLICY_ALLOWED, code, _P, strict)
    ch += check_str(obj, "policy_id", code, _P)
    ch += check_str(obj, "consumer_id", code, _P)
    ch += check_schema_version(obj, RT_REVISION_POLICY, code, _P)
    ch += check_str_list(obj, "permitted_mutations", code, _P, min_len=1)
    ch += check_str_list(obj, "prohibited_mutations", code, _P, min_len=0)
    ch += check_str_list(obj, "protected_content", code, _P, min_len=0)

    ch += _rail_mutation_vocabulary(obj, code)
    ch += _rail_permit_prohibit_disjoint(obj, code)
    ch += _rail_protected_semantics(obj, strict)
    ch += _rail_protection_is_stated(obj, code)
    ch += _rail_rollback(obj, code)
    return ch


def _rail_mutation_vocabulary(obj: Dict[str, Any], code: str) -> List[Check]:
    """Every named mutation must be one Core actually knows how to bound.

    An unknown mutation kind in ``permitted_mutations`` is the dangerous
    direction: it reads as an authorisation, but no planner will ever match it, so
    the consumer believes it granted something it did not. WF1214 names it as what
    it is -- a mutation that is not permitted, because it is not a mutation.
    """
    out: List[Check] = []
    for field in ("permitted_mutations", "prohibited_mutations"):
        vals = obj.get(field)
        if not isinstance(vals, (list, tuple)):
            continue
        unknown = sorted({v for v in vals if v not in MUTATION_KINDS})
        ok = not unknown
        out.append((_P + field + "_in_vocabulary", ok,
                    "{} names {} which are not in {}; an unrecognised kind reads "
                    "as an authorisation while matching no planner, so the "
                    "consumer believes it granted something it did not".format(
                        field, unknown, MUTATION_KINDS) if unknown
                    else "{} are all known mutation kinds".format(field),
                    None if ok else C.CORE_MUTATION_NOT_PERMITTED))
    return out


def _rail_permit_prohibit_disjoint(obj: Dict[str, Any], code: str) -> List[Check]:
    permitted = obj.get("permitted_mutations")
    prohibited = obj.get("prohibited_mutations")
    if not isinstance(permitted, (list, tuple)) or not isinstance(
            prohibited, (list, tuple)):
        return []
    both = sorted(set(permitted) & set(prohibited))
    ok = not both
    return [(_P + "permit_prohibit_disjoint", ok,
             "mutation kind(s) {} are both permitted and prohibited; the policy "
             "has no answer, so the answer becomes whichever list the next reader "
             "consults first".format(both) if both
             else "permitted and prohibited sets are disjoint",
             None if ok else code)]


def _rail_protected_semantics(obj: Dict[str, Any], strict: bool) -> List[Check]:
    """Protected semantics are constraints, and they must carry the right class."""
    out: List[Check] = []
    protected = obj.get("protected_semantics")
    if not isinstance(protected, (list, tuple)):
        return [(_P + "protected_semantics_is_list", False,
                 "protected_semantics must be a list (use [] to state that no "
                 "semantics are protected), got {}".format(type(protected).__name__),
                 C.CORE_REVISION_POLICY_INVALID)]

    for idx, c in enumerate(protected):
        out += prefixed(K.validate_constraint(c, strict=strict),
                        "{}protected[{}].".format(_P, idx))

    wrong_class = sorted({
        "{}:{}".format(c.get("constraint_id"), c.get("constraint_class"))
        for c in protected
        if isinstance(c, dict)
        and c.get("constraint_class") != K.PROTECTED_SEMANTICS})
    ok = not wrong_class
    out.append((_P + "protected_semantics_carry_protected_class", ok,
                "protected_semantics member(s) {} do not carry class {!r}; only "
                "classes in ACCEPTANCE_LOAD_BEARING can block, so a member of "
                "another class is structurally incapable of protecting anything "
                "while reading -- in this policy and in every report -- as "
                "protection".format(wrong_class, K.PROTECTED_SEMANTICS)
                if wrong_class else "every protected semantic carries the "
                                    "protected_semantics class",
                None if ok else C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION))
    return out


def _rail_protection_is_stated(obj: Dict[str, Any], code: str) -> List[Check]:
    """Protecting nothing is legal -- but it must be said, not inferred."""
    content = obj.get("protected_content")
    semantics = obj.get("protected_semantics")
    empty = (isinstance(content, (list, tuple)) and not content
             and isinstance(semantics, (list, tuple)) and not semantics)
    if not empty:
        return [(_P + "protection_is_stated", True,
                 "policy protects {} content id(s) and {} semantic(s)".format(
                     len(content or []), len(semantics or [])), None)]

    ack = obj.get("unprotected_acknowledged")
    ok = ack is True
    return [(_P + "protection_is_stated", ok,
             "protected_content and protected_semantics are both empty; that is "
             "a legal statement ('change whatever you need to') but it is "
             "indistinguishable from a section nobody filled in, so it must be "
             "acknowledged explicitly with unprotected_acknowledged=true (got "
             "{!r})".format(ack), None if ok else code)]


def _rail_rollback(obj: Dict[str, Any], code: str) -> List[Check]:
    """Rollback expectations must be executable, not aspirational."""
    out: List[Check] = []
    rb = obj.get("rollback")
    if not isinstance(rb, dict):
        return [(_P + "rollback_is_object", False,
                 "rollback must be an object, got {}".format(type(rb).__name__),
                 code)]

    out += check_required(rb, ROLLBACK_REQUIRED_FIELDS, code, _P + "rollback.")
    out += check_bool(rb, "rollback_required", code, _P + "rollback.")
    out += check_enum(rb, "rollback_granularity", ROLLBACK_GRANULARITIES, code,
                      _P + "rollback.")
    out += check_int(rb, "max_revision_attempts", code, _P + "rollback.",
                     minimum=1)

    if rb.get("rollback_required") is True:
        gran = rb.get("rollback_granularity")
        ok = gran in ROLLBACK_GRANULARITIES and gran != "none"
        out.append((_P + "required_rollback_has_granularity", ok,
                    "rollback_required=True with rollback_granularity={!r}; a "
                    "rollback that is demanded but has no unit to roll back to "
                    "cannot be performed, and the demand will be discovered as "
                    "unmeetable only after something has already changed".format(
                        gran), None if ok else code))
    return out


def mutation_verdict(policy: Dict[str, Any], mutation_kind: str) -> str:
    """Tri-verdict for "may Core perform this mutation?". Assumes a valid policy.

    Permitted and not prohibited is SATISFIED. Anything else is VIOLATED, because
    ``permitted_mutations`` is an ALLOW-LIST: absence from it is a refusal, and
    there is no third state where Core gets to proceed unsure. The one UNKNOWN
    case is a policy with no permitted list at all -- nothing has been stated, and
    Core answering on the consumer's behalf is the failure this whole module
    exists to prevent.
    """
    permitted = policy.get("permitted_mutations")
    if not isinstance(permitted, (list, tuple)):
        return tri.UNKNOWN
    prohibited = policy.get("prohibited_mutations") or []
    return tri.from_bool(mutation_kind in permitted
                         and mutation_kind not in prohibited, measured=True)


def build_revision_policy(**over: Any) -> Dict[str, Any]:
    """Build a policy. ``CALLER_OWNED_FIELDS`` are REQUIRED -- no defaults.

    Note what the defaults do NOT include: there is no default
    ``permitted_mutations``. A default there -- even an empty one -- would be Core
    deciding the shape of its own authorisation, and an empty default in
    particular would fail the non-empty rail in a way that looks like a validation
    bug rather than like a consumer who has not stated permissions yet.
    """
    require_caller_owned(over, CALLER_OWNED_FIELDS, "revision_policy")
    d: Dict[str, Any] = dict(
        prohibited_mutations=[],
        protected_semantics=[],
        rollback={
            "rollback_required": True,
            "rollback_granularity": "per_transaction",
            "max_revision_attempts": 3,
        },
        schema_version=RT_REVISION_POLICY,
        report_type=RT_REVISION_POLICY,
    )
    d.update(over)
    return d


def _example_revision_policy(**over: Any) -> Dict[str, Any]:
    """Canonical-valid policy. ``**over`` spawns the known-bads."""
    d: Dict[str, Any] = dict(
        policy_id="policy_placeholder",
        consumer_id="consumer_placeholder",
        permitted_mutations=[
            "add_geometry",
            "move_geometry",
            "adjust_terrain_height",
            "adjust_navigation",
        ],
        prohibited_mutations=["remove_geometry", "adjust_lighting"],
        protected_content=[
            "protected_content_id_a",
            "protected_content_id_b",
        ],
        protected_semantics=[
            {
                "constraint_id": "ps_landmark_identity",
                "constraint_class": K.PROTECTED_SEMANTICS,
                "subject": "landmark.identity",
                "detail": ("landmarks the consumer authored keep their identity "
                           "and role across a revision"),
                "protected_ids": ["protected_content_id_a"],
            },
        ],
        rollback={
            "rollback_required": True,
            "rollback_granularity": "per_transaction",
            "max_revision_attempts": 3,
        },
    )
    d.update(over)
    return build_revision_policy(**d)
