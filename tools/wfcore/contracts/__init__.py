#!/usr/bin/env python3
"""wfcore.contracts -- the five reusable consumer contracts, and their shared rails.

WHAT LIVES HERE
---------------
An importing game describes what it needs through exactly five records:

    consumer_profile     WHO is calling -- identity, engine/project, the metrics
                         its player and camera actually have, and the standing
                         preferences that hold across every request it makes.
    asset_catalog        WHAT Core is authorised to build with. A CLOSED world:
                         an asset that is not in the catalog is not usable, and
                         absence is a denial rather than a gap to be filled.
    world_request        ONE concrete ask -- a new world or a revision -- carried
                         as a constraint set plus the semantic content (landmarks,
                         affordances, population, environment) the consumer wants.
    revision_policy      WHAT Core may change, what it must not touch, and what
                         rollback the consumer expects when it does change things.
    acceptance_criteria  HOW the consumer decides the result is acceptable, built
                         from the same constraint taxonomy so acceptance is a fold
                         over declared classes rather than a private opinion.

WHY THE SHARED CHECK HELPERS LIVE IN ``__init__`` AND NOT IN ONE OF THE FIVE
---------------------------------------------------------------------------
All five validators need the same primitives (required-field presence, closed
vocabularies, measures that may be honestly unknown, schema identity). Putting
them in one of the five modules would make the other four import a sibling for
reasons that have nothing to do with that sibling's subject, and the first person
to split a module would carry the helpers to the wrong place. They are the
package's shared vocabulary, so they live at the package root. This module
imports none of the five, so there is no cycle.

TWO RULES THAT ARE ENFORCED HERE RATHER THAN DOCUMENTED
-------------------------------------------------------
1. **Caller-owned fields have NO default.** Every contract declares
   ``CALLER_OWNED_FIELDS`` -- the fields that name something inside the
   consumer's project or state the consumer's intent. ``build_X()`` fails closed
   via :func:`require_caller_owned` when one is missing, exactly as
   ``tools/bridge/schema.py:build_request`` does with ``target_map``. Core
   inventing a subject, a catalog, or a constraint set is the authority inversion
   this architecture exists to remove -- and a default is how that inversion gets
   introduced without anyone deciding to introduce it.

2. **An unknown is stated, never fabricated as a zero.** :func:`check_measure`
   accepts a positive number or the literal ``tri.UNKNOWN`` and REJECTS ``0``.
   A zero-valued metric reads downstream as a measured value; "we do not know the
   step height" and "the step height is 0cm" produce entirely different worlds,
   and only one of them was ever true.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .. import tri

# Check = (check_name, ok, detail, failure_code) -- the exact tuple shape
# ValidationReport.check already consumes, so these validators drop into the
# existing gates without an adapter.
Check = Tuple[str, bool, str, Optional[str]]

__all__ = [
    "Check",
    "ContractAuthorityError",
    "UNKNOWN",
    "require_caller_owned",
    "check_is_object",
    "check_required",
    "check_no_unknown",
    "check_str",
    "check_bool",
    "check_int",
    "check_enum",
    "check_str_list",
    "check_measure",
    "check_schema_version",
    "check_object_field",
    "prefixed",
    "consumer_profile",
    "asset_catalog",
    "world_request",
    "revision_policy",
    "acceptance_criteria",
]

# The single spelling of "honestly not known" across every contract. Re-exported
# from tri rather than re-typed: a second literal "unknown" in this package would
# be a second vocabulary that drifts silently.
UNKNOWN = tri.UNKNOWN


class ContractAuthorityError(ValueError):
    """Raised when a contract factory is asked to invent something the caller owns.

    Deliberately an exception rather than a check tuple: a missing caller-owned
    field is not a record that failed validation, it is a record that must never
    be constructed. Returning a "default" object here -- even a clearly-marked
    placeholder one -- would put a Core-chosen subject into the pipeline, and the
    placeholder would be indistinguishable from a real value three hops later.
    """


def require_caller_owned(over: Dict[str, Any],
                         caller_owned: Sequence[str],
                         contract_name: str) -> None:
    """Fail closed when a caller-owned argument was not supplied.

    Mirrors ``bridge.schema.build_request``: the check is on PRESENCE of the key,
    not on its truthiness. An empty list or an empty string is a legal, explicit
    statement ("no constraints beyond these", "no protected content"); omission is
    not a statement at all, and Core has no standing to turn it into one.
    """
    missing = [f for f in caller_owned if f not in over]
    if missing:
        raise ContractAuthorityError(
            "build_{}() is missing caller-owned argument(s) {}: WorldForge Core "
            "owns capability, the importing game owns intent, so these have no "
            "default. Each names something inside the consumer's project or "
            "states the consumer's intent; a default here would let Core choose "
            "a subject nobody asked for.".format(contract_name, missing))


def check_is_object(obj: Any, code: str, prefix: str, what: str) -> List[Check]:
    """Return a single failing check when ``obj`` is not a dict; else empty list."""
    if isinstance(obj, dict):
        return []
    return [("{}is_object".format(prefix), False,
             "{} must be an object, got {}".format(what, type(obj).__name__),
             code)]


def check_required(obj: Any, fields: Sequence[str], code: str,
                   prefix: str) -> List[Check]:
    """Every named field must be PRESENT. Presence, not truthiness.

    ``None`` counts as absent: a key whose value is None carries no more
    information than a missing key, and letting it pass means the difference
    between "not stated" and "stated as nothing" is decided by whichever serialiser
    ran last.
    """
    out: List[Check] = []
    for fld in fields:
        present = isinstance(obj, dict) and obj.get(fld) is not None
        out.append(("{}has_{}".format(prefix, fld), present,
                    "required field {!r} {}".format(
                        fld, "present" if present else "missing"),
                    None if present else code))
    return out


def check_no_unknown(obj: Any, allowed: Sequence[str], code: str, prefix: str,
                     strict: bool = False) -> List[Check]:
    """Strict-mode only: reject fields outside the declared surface."""
    if not strict or not isinstance(obj, dict):
        return []
    extra = sorted(set(obj) - set(allowed))
    ok = not extra
    return [("{}no_unknown_fields".format(prefix), ok,
             "unexpected field(s) {}".format(extra) if extra
             else "no unexpected fields",
             None if ok else code)]


def check_str(obj: Any, field: str, code: str, prefix: str) -> List[Check]:
    """A required identifier/path/version string: a str, and not blank."""
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, str) and bool(v.strip())
    return [("{}{}_nonempty_str".format(prefix, field), ok,
             "{} must be a non-empty string (got {!r})".format(field, v), code)]


def check_bool(obj: Any, field: str, code: str, prefix: str) -> List[Check]:
    """An EXPLICIT boolean. Truthy strings and 0/1 are rejected on purpose."""
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, bool)
    return [("{}{}_bool".format(prefix, field), ok,
             "{} must be an explicit boolean (got {!r}); a truthy value that is "
             "not a bool means somebody's serialiser decided this, not the "
             "consumer".format(field, v), code)]


def check_int(obj: Any, field: str, code: str, prefix: str,
              minimum: int = 0) -> List[Check]:
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = (isinstance(v, int) and not isinstance(v, bool) and v >= minimum)
    return [("{}{}_int_min_{}".format(prefix, field, minimum), ok,
             "{} must be an integer >= {} (got {!r})".format(field, minimum, v),
             code)]


def check_enum(obj: Any, field: str, vocab: Sequence[str], code: str,
               prefix: str) -> List[Check]:
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = v in vocab
    return [("{}{}_in_vocabulary".format(prefix, field), ok,
             "{}={!r} must be one of {}".format(field, v, tuple(vocab)), code)]


def check_str_list(obj: Any, field: str, code: str, prefix: str,
                   min_len: int = 0, unique: bool = True) -> List[Check]:
    v = obj.get(field) if isinstance(obj, dict) else None
    is_list = isinstance(v, (list, tuple))
    shaped = (is_list and len(v) >= min_len
              and all(isinstance(x, str) and x.strip() for x in v))
    out: List[Check] = [
        ("{}{}_str_list".format(prefix, field), shaped,
         "{} must be a list of >= {} non-empty strings (got {!r})".format(
             field, min_len, v), code)]
    if unique and is_list:
        dupes = sorted({x for x in v if isinstance(x, str) and v.count(x) > 1})
        ok = not dupes
        out.append(("{}{}_unique".format(prefix, field), ok,
                    "{} contains duplicate value(s) {}; a duplicate inflates a "
                    "declared set without adding anything to it".format(
                        field, dupes) if dupes else "{} has no duplicates".format(field),
                    None if ok else code))
    return out


def check_measure(obj: Any, field: str, code: str, prefix: str) -> List[Check]:
    """A physical measure: a POSITIVE number, or the literal ``unknown``.

    Zero is rejected. This is the single most important helper in this module:
    an unmeasured quantity that arrives as ``0`` is indistinguishable from a
    measured zero, and every downstream consumer of that field will treat the
    fabrication as an observation. ``unknown`` propagates as unknown through
    ``wfcore.tri`` and blocks acceptance, which is the correct and honest cost of
    not having measured something.
    """
    v = obj.get(field) if isinstance(obj, dict) else None
    if v == UNKNOWN:
        return [("{}{}_measure".format(prefix, field), True,
                 "{} is declared {!r} -- honest, and it will block acceptance "
                 "until measured".format(field, UNKNOWN), None)]
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    return [("{}{}_measure".format(prefix, field), ok,
             "{} must be a positive number or the literal {!r} (got {!r}); zero "
             "is rejected because an unmeasured quantity arriving as 0 reads "
             "downstream as a measurement".format(field, UNKNOWN, v), code)]


def check_schema_version(obj: Any, expected: str, code: str,
                         prefix: str) -> List[Check]:
    v = obj.get("schema_version") if isinstance(obj, dict) else None
    ok = v == expected
    return [("{}schema_version".format(prefix), ok,
             "schema_version must be {!r} (got {!r})".format(expected, v), code)]


def check_object_field(obj: Any, field: str, required_keys: Sequence[str],
                       code: str, prefix: str) -> List[Check]:
    """A nested object field: present, a dict, and carrying its required keys."""
    v = obj.get(field) if isinstance(obj, dict) else None
    is_obj = isinstance(v, dict)
    out: List[Check] = [
        ("{}{}_is_object".format(prefix, field), is_obj,
         "{} must be an object (got {})".format(field, type(v).__name__), code)]
    if is_obj:
        out += check_required(v, required_keys, code,
                              "{}{}.".format(prefix, field))
    return out


def prefixed(checks: Iterable[Check], prefix: str) -> List[Check]:
    """Re-prefix another validator's checks so the caller can see whose they are.

    Used to fold ``constraints.validate_constraint_set`` results into a contract's
    check list WITHOUT reimplementing them. The constraint taxonomy has exactly one
    validator; a contract that re-derived those rules would be a second authority
    that drifts the moment the taxonomy grows a class.
    """
    return [("{}{}".format(prefix, name), ok, detail, code)
            for (name, ok, detail, code) in checks]
