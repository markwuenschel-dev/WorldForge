#!/usr/bin/env python3
"""wfcore.models.observed_world -- the world as MEASURED. Never authored.

THE CENTRAL RULE
----------------
A field that was not observed is ``not_observed`` with ``value=None``. Never a
default. Never ``0``. Never ``False``. Never a copy of what the request asked
for. There is no exception, no convenience path, and no configuration flag that
relaxes it.

The reason is arithmetic, not style. Planning is ``difference(desired,
observed)``. Every fabricated value on the observed side is a difference that
does not get planned. Zero-fill an unobserved count and the planner sees a gap
it will happily "fix"; copy the requested count and the planner sees no gap at
all and ships an empty plan against a world nobody looked at. The second is
worse because it is invisible: an empty plan and a satisfied world are the same
document.

WHY A VALUE CANNOT BE WRITTEN WITHOUT ITS BACKING
-------------------------------------------------
An observed field is not a scalar. It is a record::

    {"value": <the measurement, or None>,
     "provenance": measured | derived_from_measured | not_observed |
                   observation_failed | observation_unsupported,
     "operation_id": <which observation operation produced it>,
     "observed_by":  <which collector inside that operation>,
     "collection_ok": True | False | None,
     "evidence_refs": [<entries in this model's evidence_index>],
     "derived_from": [<paths of the backed fields it was computed from>]}

There is no position anywhere in this schema where a bare scalar may sit. To
state a value you must state, in the same record, who measured it and against
what. That alone stops the careless case.

The deliberate case -- someone writing ``provenance="measured"`` by hand -- is
stopped by the rails being CROSS-RECORD rather than local:

1. ``operation_id`` must name an operation declared in this model's
   ``observation_operations``; and for a MEASURED field that operation's ``ok``
   must be ``True``. A forged field therefore also requires a forged operation.
2. Every ``evidence_refs`` entry must resolve in this model's ``evidence_index``,
   which carries a locator per entry. A forged field also requires a forged
   evidence entry with somewhere it claims to live.
3. A DERIVED field must name ``derived_from`` paths that EXIST in this same
   model and are themselves backed. A derivation cannot bottom out in thin air;
   the chain terminates at measured fields or it does not validate.
4. Entities may not appear outside a backed enumeration's extent -- you cannot
   report an entity the enumeration that found it never listed.

None of that makes forgery impossible; nothing in a data format can. What it
does is make forgery COMPOUND and VISIBLE: a single fabricated field is a
rejected document, and a self-consistent fabrication is a fabricated operation
record and a fabricated evidence entry with a locator that a downstream
integrity pass can go look for. The lie stops being a one-line default and
becomes an artifact somebody had to build on purpose.

WHAT IS DELIBERATELY ABSENT
---------------------------
There is no ``caller_supplied`` provenance. The scene-survey evidence layer has
one because its reports mix intent with observation; this model does not mix
them, because the intent side already has a home (``desired_world``). Adding
that value here would create the exact channel this file exists to close: a
request value wearing a measurement's record shape.

THREE-VALUED, NOT BOOLEAN
-------------------------
``field_evidence(field)`` returns a ``wfcore.tri`` value and never VIOLATED. A
field's evidence status answers "do we have a measurement", whose honest
negative is UNKNOWN. Reporting a missing measurement as VIOLATED would send
repair to fix a world nobody looked at.
"""

from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import tri
from ..failure import FailureCode as C
from .desired_world import (WORLD_IDENTITY_KEYS, desired_identity)

# --------------------------------------------------------------------------- #
# schema identity
# --------------------------------------------------------------------------- #
RT_OBSERVED_WORLD = "wf.core.observed_world.v1"
RT_OBSERVED_FIELD = "wf.core.observed_field.v1"

# --------------------------------------------------------------------------- #
# Provenance taxonomy. CLOSED: an unrecognised provenance is a hard failure, not
# a permissive default, because "provenance we do not recognise" must never read
# as "fine".
# --------------------------------------------------------------------------- #
MEASURED = "measured"
DERIVED = "derived_from_measured"
NOT_OBSERVED = "not_observed"
OBSERVATION_FAILED = "observation_failed"
OBSERVATION_UNSUPPORTED = "observation_unsupported"

PROVENANCE_KINDS = (MEASURED, DERIVED, NOT_OBSERVED, OBSERVATION_FAILED,
                    OBSERVATION_UNSUPPORTED)

# The only two that may carry a value. Everything else MUST carry value=None.
BACKED_PROVENANCE = (MEASURED, DERIVED)

# Honest terminal states. They are not defects -- a capability the caller did
# not exercise, one this pass cannot provide, and one that was attempted and
# failed are three different facts and all three must be sayable. Collapsing
# them into a zero is how "unsupported" becomes a silent lie.
UNBACKED_PROVENANCE = (NOT_OBSERVED, OBSERVATION_FAILED, OBSERVATION_UNSUPPORTED)

# --------------------------------------------------------------------------- #
# Observation stages, in execution order. A field's stage is load-bearing: an
# enumeration taken before the world was bound cannot describe the bound world.
# --------------------------------------------------------------------------- #
STAGE_NOT_STARTED = "not_started"
STAGE_PREPARED = "prepared"
STAGE_WORLD_BOUND = "world_bound"
STAGE_OBSERVED = "observed"
STAGE_DERIVED = "derived"
STAGE_ASSEMBLED = "assembled"

OBSERVATION_STAGES = (STAGE_NOT_STARTED, STAGE_PREPARED, STAGE_WORLD_BOUND,
                      STAGE_OBSERVED, STAGE_DERIVED, STAGE_ASSEMBLED)

# --------------------------------------------------------------------------- #
# Observation operations: the unit a field cites as its origin.
# --------------------------------------------------------------------------- #
OP_WORLD_BIND = "world_bind"
OP_ENUMERATION = "enumeration"
OP_SPATIAL_QUERY = "spatial_query"
OP_STATE_READ = "state_read"
OP_RELATION_TEST = "relation_test"
OP_DERIVATION = "derivation"

OPERATION_KINDS = (OP_WORLD_BIND, OP_ENUMERATION, OP_SPATIAL_QUERY,
                   OP_STATE_READ, OP_RELATION_TEST, OP_DERIVATION)

OPERATION_REQUIRED = ("operation_id", "operation_kind", "collector", "ok",
                      "detail")
OPERATION_ALLOWED = OPERATION_REQUIRED + ("stage", "api", "notes")

# --------------------------------------------------------------------------- #
# Evidence index entries: where a raw artifact backing a field can be found.
# --------------------------------------------------------------------------- #
EVIDENCE_RECORD = "record"
EVIDENCE_CAPTURE = "capture"
EVIDENCE_LOG = "log"
EVIDENCE_TRACE = "trace"
EVIDENCE_DOCUMENT = "document"

EVIDENCE_KINDS = (EVIDENCE_RECORD, EVIDENCE_CAPTURE, EVIDENCE_LOG,
                  EVIDENCE_TRACE, EVIDENCE_DOCUMENT)

EVIDENCE_ENTRY_REQUIRED = ("evidence_kind", "locator")
EVIDENCE_ENTRY_ALLOWED = EVIDENCE_ENTRY_REQUIRED + ("operation_id", "detail")

# --------------------------------------------------------------------------- #
# Field shape
# --------------------------------------------------------------------------- #
OBSERVED_FIELD_REQUIRED = ("value", "provenance", "operation_id", "observed_by",
                           "collection_ok", "evidence_refs")
OBSERVED_FIELD_ALLOWED = OBSERVED_FIELD_REQUIRED + ("derived_from", "detail",
                                                    "observed_at_stage")

# --------------------------------------------------------------------------- #
# Model shape. Sections mirror desired_world's sections so the two are
# differenceable field-for-field; each section is
#     {"enumeration": <field: value is the list of ids found>,
#      "entities": {entity_id: {attr_name: <field>}}}
# The enumeration is separate from the entities on purpose: a list of three
# entities does not say whether the search that produced it was exhaustive, and
# "we found three" is a different claim from "there are three".
# --------------------------------------------------------------------------- #
OBSERVED_SECTIONS = ("environmental_state", "gameplay_anchors", "population",
                     "semantic_landmarks", "spatial_relations")

ENUMERATION_KEY = "enumeration"
ENTITIES_KEY = "entities"
SECTION_ALLOWED = (ENUMERATION_KEY, ENTITIES_KEY)

OBSERVED_WORLD_REQUIRED = (
    "world_identity",
    "observation_operations",
    "evidence_index",
    "schema_version",
) + OBSERVED_SECTIONS

OBSERVED_WORLD_ALLOWED = OBSERVED_WORLD_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)

IDENTITY_PATH = "world_identity"

Check = Tuple[str, bool, str, Optional[str]]

_P = "ow::"
_FP = "of::"


class UnbackedFieldError(ValueError):
    """Raised when unbacked field data is read as though it were a measurement.

    Deliberately loud. The alternative -- returning a default -- is the exact
    fabrication this module exists to prevent, and it would be invisible at the
    call site.
    """


# --------------------------------------------------------------------------- #
# constructors. The ONLY sanctioned way to build a field: each one fixes the
# provenance/value pairing so no caller has to remember that an unbacked field
# carries None.
# --------------------------------------------------------------------------- #
def measured(value: Any, operation_id: str, observed_by: str,
             evidence_refs: Tuple[str, ...] = (), detail: Optional[str] = None,
             stage: str = STAGE_OBSERVED) -> Dict[str, Any]:
    """A value read off the world by a real operation."""
    return {
        "value": value,
        "provenance": MEASURED,
        "operation_id": operation_id,
        "observed_by": observed_by,
        "collection_ok": True,
        "evidence_refs": list(evidence_refs),
        "observed_at_stage": stage,
        "detail": detail,
    }


def derived(value: Any, operation_id: str, observed_by: str,
            derived_from: Tuple[str, ...] = (),
            evidence_refs: Tuple[str, ...] = (),
            detail: Optional[str] = None) -> Dict[str, Any]:
    """A value COMPUTED from other backed fields in this same model.

    ``derived_from`` holds field PATHS, not values: the chain must be walkable
    by a reader who has only this document, or "derived" is an assertion with a
    respectable name.
    """
    return {
        "value": value,
        "provenance": DERIVED,
        "operation_id": operation_id,
        "observed_by": observed_by,
        "collection_ok": True,
        "evidence_refs": list(evidence_refs),
        "derived_from": list(derived_from),
        "observed_at_stage": STAGE_DERIVED,
        "detail": detail,
    }


def not_observed(detail: str, stage: str = STAGE_NOT_STARTED) -> Dict[str, Any]:
    """Nobody looked. ``collection_ok`` is None -- not attempted, not failed."""
    return {
        "value": None,
        "provenance": NOT_OBSERVED,
        "operation_id": None,
        "observed_by": None,
        "collection_ok": None,
        "evidence_refs": [],
        "observed_at_stage": stage,
        "detail": detail,
    }


def observation_failed(detail: str, operation_id: Optional[str] = None,
                       observed_by: Optional[str] = None,
                       stage: str = STAGE_OBSERVED) -> Dict[str, Any]:
    """Collection was attempted and failed. Value is None, never a default."""
    return {
        "value": None,
        "provenance": OBSERVATION_FAILED,
        "operation_id": operation_id,
        "observed_by": observed_by,
        "collection_ok": False,
        "evidence_refs": [],
        "observed_at_stage": stage,
        "detail": detail,
    }


def observation_unsupported(detail: str, operation_id: Optional[str] = None,
                            observed_by: Optional[str] = None,
                            stage: str = STAGE_OBSERVED) -> Dict[str, Any]:
    """This pass genuinely cannot observe it. Sayable, and never a zero."""
    return {
        "value": None,
        "provenance": OBSERVATION_UNSUPPORTED,
        "operation_id": operation_id,
        "observed_by": observed_by,
        "collection_ok": False,
        "evidence_refs": [],
        "observed_at_stage": stage,
        "detail": detail,
    }


def operation(operation_id: str, operation_kind: str, collector: str,
              ok: bool, detail: str, stage: str = STAGE_OBSERVED
              ) -> Dict[str, Any]:
    """One observation operation. ``ok`` must be an explicit boolean."""
    return {"operation_id": operation_id, "operation_kind": operation_kind,
            "collector": collector, "ok": ok, "detail": detail, "stage": stage}


def evidence_entry(evidence_kind: str, locator: str,
                   operation_id: Optional[str] = None,
                   detail: Optional[str] = None) -> Dict[str, Any]:
    """One evidence-index entry: WHERE a backing artifact can be found."""
    d: Dict[str, Any] = {"evidence_kind": evidence_kind, "locator": locator}
    if operation_id is not None:
        d["operation_id"] = operation_id
    if detail is not None:
        d["detail"] = detail
    return d


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #
def is_backed(field: Any) -> bool:
    """True only when this field carries a measurement that actually happened."""
    return (isinstance(field, dict)
            and field.get("provenance") in BACKED_PROVENANCE
            and field.get("collection_ok") is True)


def field_evidence(field: Any) -> str:
    """The field's evidence status as a tri-value. NEVER returns VIOLATED.

    "We have no measurement" is an UNKNOWN, not a violation: a violation is
    something to go fix in the world, an unknown is something to go measure, and
    sending repair the wrong one authors changes nobody established were needed.
    """
    return tri.SATISFIED if is_backed(field) else tri.UNKNOWN


def read(field: Any) -> Tuple[bool, Any]:
    """``(has_value, value)``. When ``has_value`` is False the value is None.

    Returning a pair rather than a value-with-default is the whole point: the
    caller cannot accidentally consume an unbacked field, because there is no
    value to consume until they have looked at the flag.
    """
    if is_backed(field):
        return True, field.get("value")
    return False, None


def require_value(field: Any, path: str = "?") -> Any:
    """The value, or raise. For call sites where proceeding unmeasured is wrong."""
    has, value = read(field)
    if not has:
        raise UnbackedFieldError(
            "field {!r} carries no measurement (provenance={!r}, "
            "collection_ok={!r}). There is no default to fall back to -- an "
            "unobserved value is UNKNOWN and must block, not resolve.".format(
                path, (field or {}).get("provenance") if isinstance(field, dict)
                else None,
                (field or {}).get("collection_ok") if isinstance(field, dict)
                else None))
    return value


def _looks_like_field(x: Any) -> bool:
    return isinstance(x, dict) and "provenance" in x and "value" in x


def field_map(model: Any) -> Dict[str, Dict[str, Any]]:
    """Every observed field in the model, keyed by its canonical path.

    Paths::
        world_identity
        <section>.enumeration
        <section>.entities.<entity_id>.<attr>

    One walker, used by the validator, by ``derived_from`` resolution and by the
    tests, so all three agree on what "every field" means.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(model, dict):
        return out

    if _looks_like_field(model.get(IDENTITY_PATH)):
        out[IDENTITY_PATH] = model[IDENTITY_PATH]

    for section in OBSERVED_SECTIONS:
        block = model.get(section)
        if not isinstance(block, dict):
            continue
        enum = block.get(ENUMERATION_KEY)
        if _looks_like_field(enum):
            out["{}.{}".format(section, ENUMERATION_KEY)] = enum
        entities = block.get(ENTITIES_KEY)
        if not isinstance(entities, dict):
            continue
        for entity_id, attrs in entities.items():
            if not isinstance(attrs, dict):
                continue
            for attr, field in attrs.items():
                if _looks_like_field(field):
                    out["{}.{}.{}.{}".format(section, ENTITIES_KEY,
                                             entity_id, attr)] = field
    return out


def iter_fields(model: Any) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """``(path, field)`` for every observed field, in sorted path order."""
    fm = field_map(model)
    for path in sorted(fm):
        yield path, fm[path]


def observed_identity(model: Any) -> Optional[Dict[str, Any]]:
    """The MEASURED world identity, or None when it was never established.

    None is load-bearing. An identity that was not read back out of the world
    cannot establish that this observation describes the world the request is
    about, and a pair whose identity is unknown must not be differenced.
    """
    if not isinstance(model, dict):
        return None
    has, value = read(model.get(IDENTITY_PATH))
    if not has or not isinstance(value, dict):
        return None
    if any(value.get(k) in (None, "") for k in WORLD_IDENTITY_KEYS):
        return None
    return {k: value[k] for k in WORLD_IDENTITY_KEYS}


def declared_operation_ids(model: Any) -> List[str]:
    ops = model.get("observation_operations") if isinstance(model, dict) else None
    if not isinstance(ops, list):
        return []
    return [o.get("operation_id") for o in ops
            if isinstance(o, dict) and isinstance(o.get("operation_id"), str)]


def operation_by_id(model: Any, operation_id: Any) -> Optional[Dict[str, Any]]:
    ops = model.get("observation_operations") if isinstance(model, dict) else None
    if not isinstance(ops, list):
        return None
    for o in ops:
        if isinstance(o, dict) and o.get("operation_id") == operation_id:
            return o
    return None


# --------------------------------------------------------------------------- #
# field validator
# --------------------------------------------------------------------------- #
def validate_observed_field(field: Any, path: str = "?",
                            strict: bool = False) -> List[Check]:
    """Rails that hold for ONE field in isolation.

    The cross-record rails (does the operation exist? does the evidence ref
    resolve? does the derivation bottom out?) live in
    :func:`validate_observed_world`, because they need the whole document.
    """
    unbacked = C.CORE_OBSERVED_WORLD_UNBACKED
    invalid = C.CORE_OBSERVED_WORLD_INVALID
    p = "{}{}::".format(_FP, path)
    checks: List[Check] = []

    if not isinstance(field, dict):
        return [(p + "is_object", False,
                 "observed field must be an object, got {}".format(
                     type(field).__name__), invalid)]

    missing = [k for k in OBSERVED_FIELD_REQUIRED if k not in field]
    checks.append((p + "required", not missing,
                   "missing required key(s) {}".format(missing) if missing
                   else "all required keys present",
                   None if not missing else invalid))

    if strict:
        unknown = sorted(set(field) - set(OBSERVED_FIELD_ALLOWED))
        checks.append((p + "no_unknown_fields", not unknown,
                       "unknown key(s) {}".format(unknown) if unknown
                       else "no unknown keys",
                       None if not unknown else invalid))

    prov = field.get("provenance")
    known = prov in PROVENANCE_KINDS
    checks.append((p + "provenance_known", known,
                   "provenance {!r} is not one of {}".format(
                       prov, PROVENANCE_KINDS),
                   None if known else invalid))

    stage = field.get("observed_at_stage")
    stage_ok = stage is None or stage in OBSERVATION_STAGES
    checks.append((p + "stage_known", stage_ok,
                   "observed_at_stage {!r} is not one of {}".format(
                       stage, OBSERVATION_STAGES),
                   None if stage_ok else invalid))

    refs = field.get("evidence_refs")
    refs_ok = isinstance(refs, list) and all(isinstance(r, str) for r in refs)
    checks.append((p + "evidence_refs_list", refs_ok,
                   "evidence_refs must be a list of strings (got {!r})".format(
                       refs),
                   None if refs_ok else invalid))

    # --- THE RAIL: an unbacked field may not carry a value ------------------ #
    if prov in UNBACKED_PROVENANCE:
        ok = field.get("value") is None
        checks.append((p + "unbacked_value_is_null", ok,
                       "provenance={} carries value={!r}; a value with no "
                       "evidence behind it is indistinguishable from a real "
                       "measurement once it is one field deep in a report, and "
                       "it silently cancels the difference the planner needed "
                       "to see".format(prov, field.get("value")),
                       None if ok else unbacked))
        ok = bool(field.get("detail"))
        checks.append((p + "unbacked_has_detail", ok,
                       "a {} field must explain itself; an unexplained absence "
                       "is indistinguishable from an oversight".format(prov),
                       None if ok else invalid))
        ok = field.get("collection_ok") is not True
        checks.append((p + "unbacked_collection_not_ok", ok,
                       "provenance={} with collection_ok=True is self-"
                       "contradictory: collection succeeded but produced no "
                       "backing".format(prov),
                       None if ok else unbacked))

    # --- a backed field must actually carry its backing --------------------- #
    if prov in BACKED_PROVENANCE:
        ok = field.get("collection_ok") is True
        checks.append((p + "backed_collection_ok", ok,
                       "provenance={} requires collection_ok=True (got {!r}); a "
                       "value whose collection never ran or failed is not a "
                       "measurement".format(prov, field.get("collection_ok")),
                       None if ok else unbacked))
        ok = bool(field.get("operation_id"))
        checks.append((p + "backed_names_operation", ok,
                       "provenance={} must name the operation_id that produced "
                       "it; a measurement from no operation is an assertion"
                       .format(prov),
                       None if ok else unbacked))
        ok = bool(field.get("observed_by"))
        checks.append((p + "backed_names_observer", ok,
                       "provenance={} must name the collector that observed it"
                       .format(prov),
                       None if ok else unbacked))
        ok = isinstance(refs, list) and len(refs) > 0
        checks.append((p + "backed_cites_evidence", ok,
                       "provenance={} must cite at least one evidence_ref; a "
                       "measurement that points at no artifact cannot be "
                       "re-checked by anyone".format(prov),
                       None if ok else unbacked))

    if prov == DERIVED:
        df = field.get("derived_from")
        ok = isinstance(df, list) and len(df) > 0 and all(
            isinstance(x, str) and x for x in df)
        checks.append((p + "derived_names_inputs", ok,
                       "derived_from={!r}; a derivation with no named inputs is "
                       "an assertion wearing a derivation's clothes".format(df),
                       None if ok else unbacked))

    return checks


# --------------------------------------------------------------------------- #
# model validator
# --------------------------------------------------------------------------- #
def validate_observed_world(obj: Any, strict: bool = False) -> List[Check]:
    """Validate ONE observed-world record, including its cross-record backing."""
    invalid = C.CORE_OBSERVED_WORLD_INVALID
    unbacked = C.CORE_OBSERVED_WORLD_UNBACKED
    checks: List[Check] = []

    if not isinstance(obj, dict):
        return [(_P + "is_object", False,
                 "observed world must be an object, got {}".format(
                     type(obj).__name__), invalid)]

    for fld in OBSERVED_WORLD_REQUIRED:
        present = obj.get(fld) is not None
        checks.append((_P + "has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else invalid))

    if strict:
        unknown = sorted(set(obj) - set(OBSERVED_WORLD_ALLOWED))
        checks.append((_P + "no_unknown_fields", not unknown,
                       "unexpected field(s) {}".format(unknown) if unknown
                       else "no unexpected fields",
                       None if not unknown else invalid))

    sv = obj.get("schema_version")
    checks.append((_P + "schema_version", sv == RT_OBSERVED_WORLD,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_OBSERVED_WORLD, sv),
                   None if sv == RT_OBSERVED_WORLD else invalid))

    # --- observation operations --------------------------------------------- #
    ops = obj.get("observation_operations")
    ops_ok = isinstance(ops, list) and all(isinstance(o, dict) for o in ops)
    checks.append((_P + "operations_list_of_objects", ops_ok,
                   "observation_operations must be a list of objects",
                   None if ops_ok else invalid))
    op_ids: List[str] = []
    if ops_ok:
        for idx, op in enumerate(ops):
            for fld in OPERATION_REQUIRED:
                present = fld in op and op.get(fld) is not None
                checks.append((
                    "{}operation[{}].has_{}".format(_P, idx, fld), present,
                    "operation[{}] required field {!r} {}".format(
                        idx, fld, "present" if present else "missing"),
                    None if present else invalid))
            kind = op.get("operation_kind")
            ok = kind in OPERATION_KINDS
            checks.append((
                "{}operation[{}].kind_known".format(_P, idx), ok,
                "operation_kind {!r} is not one of {}".format(
                    kind, OPERATION_KINDS),
                None if ok else invalid))
            ok = isinstance(op.get("ok"), bool)
            checks.append((
                "{}operation[{}].ok_is_bool".format(_P, idx), ok,
                "operation.ok must be an explicit boolean (got {!r}); an "
                "operation whose outcome is implicit cannot back or fail to "
                "back anything".format(op.get("ok")),
                None if ok else invalid))
            oid = op.get("operation_id")
            if isinstance(oid, str):
                op_ids.append(oid)
        dupes = sorted({i for i in op_ids if op_ids.count(i) > 1})
        checks.append((_P + "operation_ids_unique", not dupes,
                       "duplicate operation_id(s) {}; a field citing a "
                       "duplicated id resolves to two different outcomes"
                       .format(dupes) if dupes else "operation ids unique",
                       None if not dupes else invalid))

    # --- evidence index ------------------------------------------------------ #
    index = obj.get("evidence_index")
    index_ok = isinstance(index, dict)
    checks.append((_P + "evidence_index_is_object", index_ok,
                   "evidence_index must be an object mapping ref -> entry",
                   None if index_ok else invalid))
    if index_ok:
        for ref, entry in sorted(index.items()):
            if not isinstance(entry, dict):
                checks.append((
                    "{}evidence[{}].is_object".format(_P, ref), False,
                    "evidence entry must be an object", invalid))
                continue
            for fld in EVIDENCE_ENTRY_REQUIRED:
                present = bool(entry.get(fld))
                checks.append((
                    "{}evidence[{}].has_{}".format(_P, ref, fld), present,
                    "evidence entry {!r} required field {!r} {}".format(
                        ref, fld, "present" if present else "missing/empty"),
                    None if present else invalid))
            kind = entry.get("evidence_kind")
            ok = kind in EVIDENCE_KINDS
            checks.append((
                "{}evidence[{}].kind_known".format(_P, ref), ok,
                "evidence_kind {!r} is not one of {}".format(kind,
                                                             EVIDENCE_KINDS),
                None if ok else invalid))

    # --- sections have the declared shape ------------------------------------ #
    for section in OBSERVED_SECTIONS:
        block = obj.get(section)
        ok = isinstance(block, dict)
        checks.append((_P + section + "_is_object", ok,
                       "{} must be an object with {} and {}".format(
                           section, ENUMERATION_KEY, ENTITIES_KEY),
                       None if ok else invalid))
        if not ok:
            continue
        for key in SECTION_ALLOWED:
            present = key in block
            checks.append((
                "{}{}.has_{}".format(_P, section, key), present,
                "{} must declare {!r}".format(section, key),
                None if present else invalid))
        entities = block.get(ENTITIES_KEY)
        ent_ok = isinstance(entities, dict)
        checks.append((
            "{}{}.entities_is_object".format(_P, section), ent_ok,
            "{}.{} must be an object keyed by entity id".format(
                section, ENTITIES_KEY),
            None if ent_ok else invalid))
        if strict:
            extra = sorted(set(block) - set(SECTION_ALLOWED))
            checks.append((
                "{}{}.no_unknown_keys".format(_P, section), not extra,
                "unexpected key(s) {} in {}".format(extra, section),
                None if not extra else invalid))

        # entities must live inside the measured extent -------------------- #
        enum = block.get(ENUMERATION_KEY)
        has_extent, extent = read(enum)
        if has_extent and ent_ok:
            listed = set(extent) if isinstance(extent, (list, tuple)) else set()
            outside = sorted(set(entities) - listed)
            checks.append((
                "{}{}.entities_within_measured_extent".format(_P, section),
                not outside,
                "entities {} are absent from the backed enumeration that "
                "supposedly found them; an entity outside the measured extent "
                "was not observed by the operation the section claims"
                .format(outside) if outside
                else "every entity appears in the measured enumeration",
                None if not outside else invalid))

    # --- every field: local rails, then cross-record backing ----------------- #
    fm = field_map(obj)
    for path, field in sorted(fm.items()):
        checks.extend(validate_observed_field(field, path=path, strict=strict))

        prov = field.get("provenance")
        if prov not in BACKED_PROVENANCE:
            continue

        # 1. the cited operation must be declared in THIS model.
        oid = field.get("operation_id")
        op = operation_by_id(obj, oid)
        ok = op is not None
        checks.append((
            "{}{}::operation_declared".format(_P, path), ok,
            "field cites operation_id {!r}, which this model does not declare "
            "in observation_operations; a measurement whose operation does not "
            "exist has no origin at all".format(oid),
            None if ok else unbacked))

        # 2. a MEASURED field cannot come out of a failed operation.
        if op is not None and prov == MEASURED:
            ok = op.get("ok") is True
            checks.append((
                "{}{}::operation_succeeded".format(_P, path), ok,
                "field is measured but its operation {!r} reports ok={!r}; a "
                "failed operation produces no measurements, and a value that "
                "survives one was authored, not observed".format(
                    oid, op.get("ok")),
                None if ok else unbacked))

        # 3. every evidence ref must resolve in this model's index.
        refs = field.get("evidence_refs")
        if isinstance(refs, list) and index_ok:
            dangling = sorted(r for r in refs if r not in index)
            checks.append((
                "{}{}::evidence_refs_resolve".format(_P, path), not dangling,
                "evidence_ref(s) {} resolve to nothing in evidence_index; a "
                "citation nobody can follow is not evidence".format(dangling)
                if dangling else "all evidence_refs resolve",
                None if not dangling else unbacked))

        # 4. a derivation must bottom out in backed fields OF THIS MODEL.
        if prov == DERIVED:
            df = field.get("derived_from")
            names = df if isinstance(df, list) else []
            missing = sorted(n for n in names if n not in fm)
            checks.append((
                "{}{}::derivation_inputs_exist".format(_P, path), not missing,
                "derived_from names {} which are not fields of this model; a "
                "derivation chain that leaves the document cannot be walked by "
                "the reader who has to trust it".format(missing) if missing
                else "all derivation inputs exist",
                None if not missing else unbacked))
            unbacked_inputs = sorted(n for n in names
                                     if n in fm and not is_backed(fm[n]))
            checks.append((
                "{}{}::derivation_inputs_backed".format(_P, path),
                not unbacked_inputs,
                "derived_from names {} which are themselves unbacked; a "
                "derivation from an unknown is an unknown, not a measurement"
                .format(unbacked_inputs) if unbacked_inputs
                else "all derivation inputs are backed",
                None if not unbacked_inputs else unbacked))
            self_ref = path in names
            checks.append((
                "{}{}::derivation_not_self".format(_P, path), not self_ref,
                "field derives from itself; a self-derivation is a value "
                "asserting its own evidence",
                None if not self_ref else unbacked))

    # --- world identity must be a measured identity block -------------------- #
    ident_field = obj.get(IDENTITY_PATH)
    if _looks_like_field(ident_field):
        has, value = read(ident_field)
        if has:
            shape_ok = isinstance(value, dict) and all(
                value.get(k) not in (None, "") for k in WORLD_IDENTITY_KEYS)
            checks.append((_P + "identity_value_shape", shape_ok,
                           "a backed world_identity must carry every key of {} "
                           "(got {!r}); a partial identity compares equal on the "
                           "keys it happens to have".format(
                               WORLD_IDENTITY_KEYS, value),
                           None if shape_ok else invalid))
        prov_ok = ident_field.get("provenance") in BACKED_PROVENANCE or \
            ident_field.get("provenance") in UNBACKED_PROVENANCE
        checks.append((_P + "identity_provenance_declared", prov_ok,
                       "world_identity must declare a known provenance; the "
                       "identity is the one field that decides whether this "
                       "observation may be differenced at all",
                       None if prov_ok else invalid))

    return checks


# --------------------------------------------------------------------------- #
# the desired <-> observed pair
# --------------------------------------------------------------------------- #
def same_world(desired: Any, observed: Any) -> str:
    """Do these two models describe the SAME world? A tri-value.

        SATISFIED  the observed identity was measured and equals the desired one
        VIOLATED   the observed identity was measured and DIFFERS
        UNKNOWN    the observed identity was never established

    All three are distinct outcomes with distinct correct behaviours, which is
    why this is not a boolean: a mismatch is a wrong subject (stop, the plan
    would be meaningless), while an unknown is an unmeasured subject (go bind
    the world and observe again).
    """
    want = desired_identity(desired)
    got = observed_identity(observed)
    if want is None or got is None:
        return tri.UNKNOWN
    return tri.SATISFIED if want == got else tri.VIOLATED


def differenceable(desired: Any, observed: Any) -> str:
    """May these two models be differenced? ``same_world`` is the whole test.

    Routed through :func:`wfcore.tri.accepts` at the call site, never
    ``!= VIOLATED`` -- those differ exactly on UNKNOWN, and differencing against
    an unidentified observation is the failure this function exists to stop.
    """
    return same_world(desired, observed)


def validate_model_pair(desired: Any, observed: Any,
                        strict: bool = False) -> List[Check]:
    """Rails that are invisible from either model alone.

    Two SEPARATE checks with two SEPARATE codes, because "these are different
    worlds" and "we never established which world this is" are different facts
    and lead to different repairs:

      * VIOLATED -> ``CORE_MODEL_IDENTITY_MISMATCH`` -- stop; the plan would be
        a confident set of changes to the wrong world.
      * UNKNOWN  -> ``CORE_OBSERVED_WORLD_UNBACKED`` -- the identity was never
        measured; go observe, do not report a mismatch nobody saw.
    """
    checks: List[Check] = []
    want = desired_identity(desired)
    got = observed_identity(observed)
    verdict = same_world(desired, observed)

    established = got is not None
    checks.append((
        "pair::observed_identity_established", established,
        "the observed model carries no MEASURED world identity (got {!r}); "
        "without it nothing establishes that this observation is of the world "
        "the request is about, and the difference would be computed across two "
        "unrelated worlds".format(got),
        None if established else C.CORE_OBSERVED_WORLD_UNBACKED))

    declared = want is not None
    checks.append((
        "pair::desired_identity_declared", declared,
        "the desired model declares no complete world identity {} (got {!r})"
        .format(WORLD_IDENTITY_KEYS, want),
        None if declared else C.CORE_DESIRED_WORLD_INVALID))

    # Reported ONLY on VIOLATED. On UNKNOWN this check stays silent-passing so
    # an unmeasured identity is never laundered into a mismatch that was never
    # observed -- the established rail above is what blocks that case.
    matched = verdict != tri.VIOLATED
    checks.append((
        "pair::identity_matches", matched,
        "desired identity {!r} != observed identity {!r}; differencing two "
        "unrelated worlds produces a plausible, entirely meaningless plan"
        .format(want, got),
        None if matched else C.CORE_MODEL_IDENTITY_MISMATCH))

    # The acceptance-shaped restatement, routed through tri.accepts so UNKNOWN
    # blocks. Code selection follows the fact, not the convenience.
    ok = tri.accepts(verdict)
    checks.append((
        "pair::differenceable", ok,
        "differenceable verdict is {} ({})".format(
            verdict,
            "identities agree" if ok else
            "identities disagree" if verdict == tri.VIOLATED else
            "observed identity was never measured"),
        None if ok else (C.CORE_MODEL_IDENTITY_MISMATCH
                         if verdict == tri.VIOLATED
                         else C.CORE_OBSERVED_WORLD_UNBACKED)))

    return checks


# --------------------------------------------------------------------------- #
# canonical example
# --------------------------------------------------------------------------- #
def _example_observed_world(**over: Any) -> Dict[str, Any]:
    """Canonical-valid observed world matching ``_example_desired_world``.

    Deliberately PARTIAL: the population count is ``observation_unsupported``
    and one anchor's state is ``not_observed``. A canonical example in which
    everything happens to have been measured teaches the wrong lesson -- that a
    complete observation is the normal case -- and the shape that must be
    obviously legal is the honest partial one.
    """
    ops = [
        operation("operation_bind", OP_WORLD_BIND, "world_binder", True,
                  "bound the world and read its stamped identity",
                  stage=STAGE_WORLD_BOUND),
        operation("operation_enumerate", OP_ENUMERATION, "entity_enumerator",
                  True, "enumerated declared entity kinds in the bound world"),
        operation("operation_state_read", OP_STATE_READ, "state_reader", True,
                  "read environmental state dimensions"),
        operation("operation_relation", OP_RELATION_TEST, "relation_tester",
                  True, "tested declared spatial relations"),
        operation("operation_derive", OP_DERIVATION, "deriver", True,
                  "computed derived quantities from measured fields",
                  stage=STAGE_DERIVED),
    ]
    index = {
        "record#bind": evidence_entry(EVIDENCE_RECORD, "observation/bind.json",
                                      "operation_bind"),
        "record#enumeration": evidence_entry(
            EVIDENCE_RECORD, "observation/enumeration.json",
            "operation_enumerate"),
        "record#state": evidence_entry(EVIDENCE_RECORD,
                                       "observation/state.json",
                                       "operation_state_read"),
        "record#relations": evidence_entry(EVIDENCE_RECORD,
                                           "observation/relations.json",
                                           "operation_relation"),
        "record#derivation": evidence_entry(EVIDENCE_DOCUMENT,
                                            "observation/derivation.json",
                                            "operation_derive"),
    }

    d: Dict[str, Any] = {
        "world_identity": measured(
            {"world_id": "world_0001", "request_id": "request_0001",
             "revision": 1},
            "operation_bind", "world_binder", ("record#bind",),
            detail="identity read back out of the bound world, not copied "
                   "from the request",
            stage=STAGE_WORLD_BOUND),
        "semantic_landmarks": {
            ENUMERATION_KEY: measured(
                ["landmark_a"], "operation_enumerate", "entity_enumerator",
                ("record#enumeration",),
                detail="one landmark found; the enumeration ran to completion"),
            ENTITIES_KEY: {
                "landmark_a": {
                    "present": measured(True, "operation_enumerate",
                                        "entity_enumerator",
                                        ("record#enumeration",)),
                    "role": measured("orientation_reference",
                                     "operation_enumerate", "entity_enumerator",
                                     ("record#enumeration",)),
                },
            },
        },
        "gameplay_anchors": {
            ENUMERATION_KEY: measured(
                ["anchor_entry", "anchor_objective"], "operation_enumerate",
                "entity_enumerator", ("record#enumeration",)),
            ENTITIES_KEY: {
                "anchor_entry": {
                    "present": measured(True, "operation_enumerate",
                                        "entity_enumerator",
                                        ("record#enumeration",)),
                },
                "anchor_objective": {
                    "present": measured(True, "operation_enumerate",
                                        "entity_enumerator",
                                        ("record#enumeration",)),
                    # honest gap: the pass never queried this attribute.
                    "role": not_observed(
                        "role attribution was not part of this observation "
                        "pass"),
                },
            },
        },
        "population": {
            ENUMERATION_KEY: measured(
                ["population_group_a"], "operation_enumerate",
                "entity_enumerator", ("record#enumeration",)),
            ENTITIES_KEY: {
                "population_group_a": {
                    "present": measured(True, "operation_enumerate",
                                        "entity_enumerator",
                                        ("record#enumeration",)),
                    # honest gap: NOT a zero.
                    "count": observation_unsupported(
                        "this observation pass cannot count group members",
                        "operation_enumerate", "entity_enumerator"),
                },
            },
        },
        "environmental_state": {
            ENUMERATION_KEY: measured(
                ["state_illumination", "state_visibility"],
                "operation_state_read", "state_reader", ("record#state",)),
            ENTITIES_KEY: {
                "state_illumination": {
                    "state_value": measured("high", "operation_state_read",
                                            "state_reader", ("record#state",)),
                },
                "state_visibility": {
                    "state_value": measured("unobstructed",
                                            "operation_state_read",
                                            "state_reader", ("record#state",)),
                },
            },
        },
        "spatial_relations": {
            ENUMERATION_KEY: measured(
                ["relation_1", "relation_2"], "operation_relation",
                "relation_tester", ("record#relations",)),
            ENTITIES_KEY: {
                "relation_1": {
                    "holds": measured(True, "operation_relation",
                                      "relation_tester", ("record#relations",)),
                },
                "relation_2": {
                    "holds": measured(False, "operation_relation",
                                      "relation_tester", ("record#relations",)),
                    "holds_both_ways": derived(
                        False, "operation_derive", "deriver",
                        derived_from=(
                            "spatial_relations.entities.relation_2.holds",),
                        evidence_refs=("record#derivation",),
                        detail="a relation that does not hold cannot hold "
                               "symmetrically"),
                },
            },
        },
        "observation_operations": ops,
        "evidence_index": index,
        "created_by": "wfcore.models",
        "schema_version": RT_OBSERVED_WORLD,
        "report_type": RT_OBSERVED_WORLD,
    }
    d.update(over)
    return d
