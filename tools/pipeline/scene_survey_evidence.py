#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WorldForge v2.6 — the scene-survey runtime EVIDENCE MODEL.

Schema-only and pure: no I/O, no Unreal, no subprocess. This module defines what
an evidence-bearing value IS, and how a derived value is computed from raw
observations. It does not collect evidence and it does not decide verdicts.

WHY THIS EXISTS
---------------
Before this module, the report carried bare scalars, and several of them were
literals: `cleanup_verified: True`, `proxy_owners: 0`, `proxies_disabled: False`,
`engine_root: "resolved"`. Others were worse than literals because they looked
computed: `actor_bounds_valid` was `actors > 0 and not error` (a count, not a
bounds check); `temporary_placements_grounded` carried the ACCEPTED count while
the real grounded value was parsed and thrown away; `player_clearance_valid` was
`(not accepted) or clearance`, which is a tautology because the C++ defines
`accepted = grounded && footprint && clearance` — it cannot evaluate False for
any input the far side can emit, and it is vacuously True when no markers ran.

A scalar cannot distinguish "measured 0" from "never collected" from "collection
failed". That distinction is the whole difference between evidence and decoration,
so the unit of a report field is no longer a scalar — it is a record carrying the
value, how it was obtained, and what it was obtained from.

THE NON-CIRCULARITY RULE
------------------------
The three roles are deliberately separated:

    far side   -> RAW observations only. Forbidden to emit a verdict boolean.
    assembler  -> derives a value from raw, and must state its inputs.
    validator  -> RE-DERIVES from the same raw, independently, and compares.

The derivation functions here are shared by the assembler and the validator on
purpose. That is not circular trust: the shared function is a SPECIFICATION, and
the independent input is the raw evidence. If an assembler writes a value the raw
does not support, re-derivation disagrees and the claim is rejected. What would be
circular — and is forbidden — is a validator that reads a success flag the runtime
declared about itself. Every rail here consumes raw observations, never verdicts.

A derived claim must therefore satisfy THREE independent conditions, not one:

    1. its classification is acceptable for a runtime rail;
    2. its raw_refs resolve to raw records actually present in the bundle;
    3. the raw is SUFFICIENT for the claim (a precondition per field), and
       re-derivation reproduces the claimed value exactly.

Condition 3 is what defeats "populate the expected JSON keys": the keys are easy
to write and the supporting raw is not.

THE EVIDENCE MATHEMATICS
------------------------
Everything below is stated once, formally, and implemented exactly once.

(1) TRI-STATE SUFFICIENCY. Every measured predicate is x in {true, false,
    unknown}. `unknown` means collection did not occur or was insufficient, and it
    is NEVER coerced to `false`. For n records with observations x_i:

        O_x = SUM 1[x_i in {true,false}]      decided observations
        S_x = (n > 0) AND (O_x = n)           sufficiency
        V_x = AND_i x_i   if S_x   else unknown

    Completeness is reported SEPARATELY from result, as a triple per predicate:

        <name>_observed          bool  — was the population fully observed
        <name>_valid             true / false / unknown
        <name>_unobserved_count  int

    Two conjunctions live here and they are deliberately different:
      * ACROSS a population (V_x above) sufficiency is STRICT — one undecided
        record makes the aggregate unknown, because a count or an all() over a
        partially-observed population is a confident answer about nothing.
      * WITHIN one record, across the components of a compound predicate (G_m
        below), conjunction is KLEENE — false dominates unknown, because a
        component measured and failed decides the record no matter what else went
        uncollected. Kleene never returns true on incomplete input, so this is
        fail-closed in the only direction that matters.

(2) BOUNDS. Validity is a property of the INTERVAL, never of the actor count:

        B_i = finite(b_i^min) AND finite(b_i^max)
              AND FORALL a in {x,y,z}: b_{i,a}^min <= b_{i,a}^max
        ActorBoundsValid = (n > 0) AND AND_{i=1..n} B_i

(3) GROUNDING. Per marker m, with named contract constants (see
    CONTRACT_CONSTANTS — every threshold carries a unit and validation bounds and
    is checked at import):

        G_m = C_m
              AND (A_supported,m / A_required,m >= SUPPORT_AREA_RATIO_MIN)
              AND (|dz_m| <= GROUND_DZ_TOLERANCE_CM)
              AND (n_m . z >= cos(GROUND_MAX_SLOPE_DEG))

(4) CLEANUP. The operation must leave the world as it found it:

        CleanupVerified = (D_f = D_i) AND (T_f = T_i) AND (M_f = M_i)

    D = dirty-package set, T = operation-owned temporary-object set, M = the
    persistent map/package identity. T_i = T_f = {} is a MEASUREMENT the far side
    takes (`_SpawnLedger.owned_paths` in tools/bridge/scene_survey_far_side.py),
    never an assumption, so an inventory that omits the owned set yields unknown
    rather than an empty set. Equality, not containment: a package that STOPS
    being dirty was written to disk, which is also a mutation.

(5) NUMERIC HYGIENE. FORALL v in numeric evidence: isfinite(v). NaN and Infinity
    are rejected, never tolerated — `json.loads` parses both by default, so they
    reach this module as real floats.

(6) REFERENCE INTEGRITY. Every `*_ref` / `*_refs` entry must resolve to a record
    present in the same bundle and carrying the same operation_id. Missing refs,
    duplicate record ids, cross-operation refs and contradictory atoms all FAIL
    CLOSED: `derive` refuses to answer at all rather than answering confidently
    from a bundle that contradicts itself.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/scene_survey_evidence.py
"""

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as C  # noqa: E402

RT_EVIDENCE = "wf.scene_survey.evidence_record.v1"
RT_RAW_BUNDLE = "wf.scene_survey.raw_evidence_bundle.v1"


# --------------------------------------------------------------------------- #
# (1) Tri-state sufficiency — the core model.
# --------------------------------------------------------------------------- #
# x in {True, False, UNKNOWN}. UNKNOWN means collection did not occur or was
# insufficient. It is a THIRD value, not a shade of False: `unknown` and `false`
# are both non-satisfying, but only `false` is a measurement, and only `false`
# names a defect in the world rather than a defect in the pass.
UNKNOWN = "unknown"
TRISTATE = (True, False, UNKNOWN)


def is_decided(x):
    """True only for a genuine boolean observation.

    Strict identity against the singletons on purpose. A 1, a "true", or a None
    is NOT a decided observation — JSON is a wide door and a truthiness test at
    this seam is how "the collector emitted a string" becomes "the world is
    fine".
    """
    return x is True or x is False


def tri(x):
    """Coerce a raw observation into the tri-state domain. Never fabricates."""
    return x if is_decided(x) else UNKNOWN


def tri_not(x):
    return (not x) if is_decided(x) else UNKNOWN


def tri_and(values):
    """KLEENE conjunction, for components WITHIN one record.

    False dominates UNKNOWN: a component measured and failed decides the record
    regardless of what else went uncollected. This can never return True on
    incomplete input, which is the only direction that has to be safe.

    This is deliberately NOT the rule used ACROSS a population — see `aggregate`,
    where sufficiency is strict, because a count or an all() over a
    partially-observed population is a confident answer about nothing.
    """
    seen_unknown = False
    for v in values:
        if v is False:
            return False
        if not is_decided(v):
            seen_unknown = True
    return UNKNOWN if seen_unknown else True


def aggregate(observations):
    """The population model, exactly as specified.

        O_x = |{i : x_i in {true,false}}|
        S_x = (n > 0) and (O_x = n)
        V_x = AND_i x_i  if S_x  else UNKNOWN

    Returns a dict so completeness travels WITH the result and cannot be dropped
    on the way to the report.
    """
    obs = list(observations)
    n = len(obs)
    decided = [x for x in obs if is_decided(x)]
    o = len(decided)
    sufficient = (n > 0) and (o == n)
    return {
        "n": n,
        "decided": o,
        "observed": sufficient,
        "valid": (all(decided) if sufficient else UNKNOWN),
        "unobserved_count": n - o,
    }


# --------------------------------------------------------------------------- #
# (5) Numeric hygiene. FORALL v in numeric evidence: isfinite(v).
# --------------------------------------------------------------------------- #
# `json.loads` accepts NaN, Infinity and -Infinity by default, so these arrive as
# real Python floats from a perfectly well-formed-looking document. Every
# comparison against a NaN is False, which means an untested NaN silently turns
# every threshold rail into a pass-through. They are rejected here, once.

def is_finite_number(v):
    """The predicate other lanes should use for any numeric evidence value.

    bool is excluded even though `isinstance(True, int)` holds: a boolean is a
    verdict-shaped value, not a measurement, and admitting it here would let
    `True` satisfy a distance or an area.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False


def nonfinite_findings(obj, path="$", _seen=None):
    """Every non-finite numeric leaf reachable from `obj`, as [(path, value)]."""
    out = []
    _seen = set() if _seen is None else _seen
    if id(obj) in _seen:
        return out
    if isinstance(obj, dict):
        _seen.add(id(obj))
        for k in sorted(obj, key=lambda x: str(x)):
            out.extend(nonfinite_findings(obj[k], "{}.{}".format(path, k), _seen))
    elif isinstance(obj, (list, tuple)):
        _seen.add(id(obj))
        for i, v in enumerate(obj):
            out.extend(nonfinite_findings(v, "{}[{}]".format(path, i), _seen))
    elif isinstance(obj, float) and not math.isfinite(obj):
        out.append((path, repr(obj)))
    return out


def numeric_hygiene_ok(obj):
    """(ok, detail). NaN / Infinity anywhere in numeric evidence is a rejection."""
    bad = nonfinite_findings(obj)
    if not bad:
        return True, "no non-finite numeric values"
    return False, ("non-finite numeric evidence at {} — NaN/Infinity are rejected, "
                   "not tolerated (every comparison against NaN is False, which "
                   "turns a threshold rail into a pass-through)".format(
                       ", ".join("{}={}".format(p, v) for p, v in bad[:5])))


# --------------------------------------------------------------------------- #
# (3) Contract constants. Named, united, bounded, and validated AT IMPORT.
# --------------------------------------------------------------------------- #
# Every threshold in the grounding predicate is here, with its unit, its legal
# range, and the observation it came from. A bare 0.9 in an expression is a
# number nobody can argue with because nobody can tell what it means; a named
# constant with a provenance line can be disagreed with, which is the point.
CONTRACT_CONSTANTS = {
    "SUPPORT_AREA_RATIO_MIN": {
        "value": 1.0,
        "unit": "dimensionless (supported footprint area / required footprint area)",
        "lo": 0.0, "lo_inclusive": False,
        "hi": 1.0, "hi_inclusive": True,
        "why": ("mirrors the compiled primitive, which requires ALL four footprint "
                "corner traces to hit before it sets bFootprint "
                "(`ProbeTempMarker` in SceneSurvey.cpp; restated in Python by "
                "`_collect_marker_record`). Lowering this "
                "below 1.0 makes the Python derivation more permissive than the "
                "C++ it claims to be re-deriving, so the two channels could no "
                "longer disagree — which is the whole reason both exist."),
    },
    "GROUND_DZ_TOLERANCE_CM": {
        "value": 45.0,
        "unit": "cm (|candidate Z - observed ground impact Z|)",
        "lo": 0.0, "lo_inclusive": False,
        "hi": None, "hi_inclusive": False,
        "why": ("the survey's own step-height budget, MaxStepH = 45.f "
                "(`MaxStepH` in SceneSurvey.cpp). A candidate further than one step above or "
                "below the surface it traced is not standing on that surface."),
    },
    "GROUND_MAX_SLOPE_DEG": {
        "value": 44.0,
        "unit": "degrees from world up",
        "lo": 0.0, "lo_inclusive": False,
        "hi": 90.0, "hi_inclusive": False,
        "why": ("the survey's own MaxSlope = 44.f (SceneSurvey.cpp), the same "
                "number the walkability probe uses independently "
                "(MAX_SLOPE_DEG in tools/unreal/ground_walkability_probe.py). Note this "
                "DISAGREES with MAX_SLOPE_DEG in generate_entity_anchors.py (35 deg); the "
                "survey mirrors the survey."),
    },
}


def validate_contract_constants(table=None):
    """House `(name, ok, detail, code)` rails over the constant table itself.

    Exposed as a function rather than done inline so the validator can be
    dogfooded with a deliberately broken table — a validator that has never been
    shown to reject anything is decoration.
    """
    code = C.SCENE_SURVEY_PROFILE_INVALID
    table = CONTRACT_CONSTANTS if table is None else table
    ch = []
    for name in sorted(table):
        spec = table[name] if isinstance(table.get(name), dict) else {}
        p = "const::{}::".format(name)
        v = spec.get("value")
        ch.append((p + "finite", is_finite_number(v),
                   "value must be a finite number (got {!r})".format(v), code))
        ch.append((p + "unit", bool(str(spec.get("unit") or "").strip()),
                   "a threshold without a unit is a magic number", code))
        ch.append((p + "why", bool(str(spec.get("why") or "").strip()),
                   "a threshold without a stated provenance is a magic number", code))
        if not is_finite_number(v):
            continue
        lo, hi = spec.get("lo"), spec.get("hi")
        if lo is not None:
            ok = (v >= lo) if spec.get("lo_inclusive") else (v > lo)
            ch.append((p + "lower_bound", ok,
                       "value {} violates lower bound {} (inclusive={})".format(
                           v, lo, bool(spec.get("lo_inclusive"))), code))
        if hi is not None:
            ok = (v <= hi) if spec.get("hi_inclusive") else (v < hi)
            ch.append((p + "upper_bound", ok,
                       "value {} violates upper bound {} (inclusive={})".format(
                           v, hi, bool(spec.get("hi_inclusive"))), code))
    return ch


_CONST_FAILURES = [c for c in validate_contract_constants() if not c[1]]
if _CONST_FAILURES:  # pragma: no cover - import-time guard
    raise ValueError(
        "scene_survey_evidence contract constants are invalid: "
        + "; ".join("{}: {}".format(c[0], c[2]) for c in _CONST_FAILURES))

SUPPORT_AREA_RATIO_MIN = CONTRACT_CONSTANTS["SUPPORT_AREA_RATIO_MIN"]["value"]
GROUND_DZ_TOLERANCE_CM = CONTRACT_CONSTANTS["GROUND_DZ_TOLERANCE_CM"]["value"]
GROUND_MAX_SLOPE_DEG = CONTRACT_CONSTANTS["GROUND_MAX_SLOPE_DEG"]["value"]
# cos(theta_max), precomputed once. The comparison is n_hat . z_hat >= this.
GROUND_MAX_SLOPE_COS = math.cos(math.radians(GROUND_MAX_SLOPE_DEG))


# --------------------------------------------------------------------------- #
# Classifications.
# --------------------------------------------------------------------------- #
# The taxonomy is closed. An unrecognised classification is a hard failure rather
# than a permissive default, because "unknown provenance" must never read as
# "fine".
OBSERVED = "observed"
DERIVED = "derived_from_observed"
CALLER_SUPPLIED = "caller_supplied"
NOT_REQUESTED = "not_requested"
UNSUPPORTED = "unsupported"
FAILED = "failed"

CLASSIFICATIONS = (OBSERVED, DERIVED, CALLER_SUPPLIED, NOT_REQUESTED,
                   UNSUPPORTED, FAILED)

# Only these two may satisfy a runtime acceptance rail. caller_supplied
# establishes INTENT and can never prove EXECUTION — that separation is the
# ownership boundary expressed in the evidence layer.
ACCEPTANCE_CLASSIFICATIONS = (OBSERVED, DERIVED)

# not_requested / unsupported / failed are honest terminal states. They do not
# satisfy a rail, but they are not defects either: a capability the caller did not
# ask for, or that this pass genuinely cannot provide, must be SAYABLE. Collapsing
# them into a zero or a False is how "unsupported" becomes a silent lie.
NON_SATISFYING = (NOT_REQUESTED, UNSUPPORTED, FAILED)

# Stages, in execution order. A record's stage is load-bearing: an inventory taken
# at `observe` cannot prove anything about the world after `cleanup`.
STAGES = ("preparation", "boot", "map_load", "world_identity", "anchor_bind",
          "observe", "classify", "cleanup", "assemble")
STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}


# --------------------------------------------------------------------------- #
# The temporary-object ledger's vocabulary.
# --------------------------------------------------------------------------- #
# CLOSED sets, mirroring the literals the far side writes
# (tools/bridge/scene_survey_far_side.py: PRESENCE_STATES / DESTRUCTION_RESULTS,
# declared beside `_SpawnLedger`). Duplicated as strings rather than imported
# because the far side runs inside the UE interpreter and cannot import this
# module — the STRINGS are the contract, and the ledger record emits both tuples so
# a drift between the two files is visible in the evidence itself.
PRESENCE_NEVER_CREATED = "never_created"
PRESENCE_ABSENT = "absent"
PRESENCE_PRESENT = "present"
PRESENCE_UNKNOWN = "unknown"
PRESENCE_STATES = (PRESENCE_NEVER_CREATED, PRESENCE_ABSENT, PRESENCE_PRESENT,
                   PRESENCE_UNKNOWN)
# The two that DECIDE the per-object conjunct. `unknown` is excluded on purpose:
# an unwitnessed final state makes the claim insufficient, never false and never
# true.
PRESENCE_DECIDED = (PRESENCE_NEVER_CREATED, PRESENCE_ABSENT, PRESENCE_PRESENT)

DESTRUCTION_NOT_ATTEMPTED = "not_attempted"
DESTRUCTION_DESTROYED = "destroyed"
DESTRUCTION_RETURNED_FALSE = "destroy_returned_false"
DESTRUCTION_ERROR = "error"
DESTRUCTION_UNKNOWN = "unknown"
DESTRUCTION_RESULTS = (DESTRUCTION_NOT_ATTEMPTED, DESTRUCTION_DESTROYED,
                       DESTRUCTION_RETURNED_FALSE, DESTRUCTION_ERROR,
                       DESTRUCTION_UNKNOWN)

# Where the ledger's own record lives. Under `document`, NOT under
# `temporary_placement`, so it is not mistaken for a placement and does not join
# that predicate's population.
LEDGER_KIND = "document"
LEDGER_IDENT = "temporary_object_ledger"
LEDGER_REF = LEDGER_KIND + "#" + LEDGER_IDENT


def temporary_object_ledger(raw):
    """The operation's temporary-object ledger record, or None.

    None is the load-bearing answer. Two inventory snapshots can only ever compare
    the world before against the world after; an object that was created AND
    destroyed between them is invisible to that comparison, and so is an object
    created before the pre snapshot by a spawn path nobody tracked. The ledger is
    the only artifact that enumerates O_created, so without it the per-object
    conjunct of CleanupVerified is not false — it is UNASKABLE, and
    `sufficiency_cleanup` refuses on exactly that basis.
    """
    doc = (raw or {}).get(LEDGER_KIND)
    led = doc.get(LEDGER_IDENT) if isinstance(doc, dict) else None
    return led if isinstance(led, dict) else None


def ledger_declared_ids(led):
    """The object ids the ledger claims as its own. None when unmeasured."""
    ids = (led or {}).get("object_ids")
    if not isinstance(ids, list):
        return None
    return [str(i) for i in ids]


def _placements(raw):
    p = (raw or {}).get("temporary_placement")
    return p if isinstance(p, dict) else {}


# --------------------------------------------------------------------------- #
# Evidence records.
# --------------------------------------------------------------------------- #
_RECORD_REQUIRED = (
    "value", "classification", "stage", "collector", "collection_ok", "raw_refs",
)
_RECORD_ALLOWED = _RECORD_REQUIRED + (
    "api", "world", "derivation", "inputs", "detail", "after_cleanup",
)


def record(value, classification, stage=None, collector=None, api=None,
           world=None, raw_refs=(), collection_ok=None, derivation=None,
           inputs=None, detail=None, after_cleanup=None):
    """Build one evidence record.

    `collection_ok` is intentionally tri-state (True / False / None). None means
    "collection was never attempted", which is a different fact from "attempted
    and failed", and both differ from "attempted, succeeded, and the answer was
    zero". Folding these together is the specific mistake this model exists to
    prevent.
    """
    rec = {
        "value": value,
        "classification": classification,
        "stage": stage,
        "collector": collector,
        "collection_ok": collection_ok,
        "raw_refs": list(raw_refs or ()),
    }
    if api is not None:
        rec["api"] = api
    if world is not None:
        rec["world"] = world
    if derivation is not None:
        rec["derivation"] = derivation
    if inputs is not None:
        rec["inputs"] = inputs
    if detail is not None:
        rec["detail"] = detail
    if after_cleanup is not None:
        rec["after_cleanup"] = bool(after_cleanup)
    return rec


def caller_supplied(value, detail=None):
    """A value taken from the request. States intent; proves no execution."""
    return record(value, CALLER_SUPPLIED, stage="preparation",
                  collector="request", collection_ok=True, detail=detail)


def unsupported(detail, stage=None, collector=None):
    """A capability this pass genuinely cannot provide. Value is None, never a zero."""
    return record(None, UNSUPPORTED, stage=stage, collector=collector,
                  collection_ok=False, detail=detail)


def not_requested(detail, stage=None):
    """The caller did not ask for this. Value is None, never False."""
    return record(None, NOT_REQUESTED, stage=stage, collector="request",
                  collection_ok=None, detail=detail)


def failed(detail, stage=None, collector=None):
    """Collection was attempted and failed. Value is None, never a default."""
    return record(None, FAILED, stage=stage, collector=collector,
                  collection_ok=False, detail=detail)


def validate_record(obj, field="?", strict=False):
    """House `(name, ok, detail, code)` rails for one evidence record."""
    code = C.SCENE_SURVEY_EVIDENCE_CLASSIFICATION_INVALID
    ch = []
    p = "ev::{}::".format(field)

    if not isinstance(obj, dict):
        return [(p + "is_object", False, "evidence record must be an object", code)]

    missing = [k for k in _RECORD_REQUIRED if k not in obj]
    ch.append((p + "required", not missing,
               "missing required key(s) {}".format(missing), code))

    unknown = sorted(k for k in obj if k not in _RECORD_ALLOWED)
    ch.append((p + "no_unknown_fields", (not unknown) or (not strict),
               "unknown key(s) {}".format(unknown), code))

    cls = obj.get("classification")
    ch.append((p + "classification_known", cls in CLASSIFICATIONS,
               "classification must be one of {} (got {!r})".format(
                   list(CLASSIFICATIONS), cls), code))

    stage = obj.get("stage")
    ch.append((p + "stage_known", stage in STAGES,
               "stage must be one of {} (got {!r})".format(list(STAGES), stage),
               code))

    ch.append((p + "raw_refs_list", isinstance(obj.get("raw_refs"), list),
               "raw_refs must be a list", code))

    # A derived claim MUST name its inputs. "Derived from nothing" is an assertion
    # wearing a derivation's clothes.
    if cls == DERIVED:
        ch.append((p + "derivation_named", bool(obj.get("derivation")),
                   "a derived_from_observed record must name its derivation",
                   code))
        ch.append((p + "derived_has_raw_refs",
                   isinstance(obj.get("raw_refs"), list) and len(obj["raw_refs"]) > 0,
                   "a derived_from_observed record must cite the raw records it "
                   "was computed from — a derivation with no inputs is an "
                   "assertion", code))

    # An observed claim must have actually collected something.
    if cls == OBSERVED:
        ch.append((p + "observed_collection_ok", obj.get("collection_ok") is True,
                   "an observed record must report collection_ok=True; a value "
                   "whose collection never ran or failed is not an observation",
                   code))
        ch.append((p + "observed_has_collector", bool(obj.get("collector")),
                   "an observed record must name the collector that produced it",
                   code))

    # The honest terminal states must NOT smuggle a usable-looking value.
    if cls in NON_SATISFYING:
        ch.append((p + "non_satisfying_value_is_null", obj.get("value") is None,
                   "a {} record must carry value=None — a zero or False here is "
                   "indistinguishable from a real measurement".format(cls), code))
        ch.append((p + "non_satisfying_has_detail", bool(obj.get("detail")),
                   "a {} record must explain itself".format(cls), code))

    return ch


def satisfies_rail(rec):
    """True only if this record may satisfy a runtime acceptance rail."""
    return (isinstance(rec, dict)
            and rec.get("classification") in ACCEPTANCE_CLASSIFICATIONS
            and rec.get("collection_ok") is True)


# --------------------------------------------------------------------------- #
# Raw evidence bundle addressing.
# --------------------------------------------------------------------------- #
# A raw_ref is "<kind>#<id>". The bundle is {kind: {id: record}}. Refs are opaque
# strings in the report so the report stays JSON-portable; resolution happens here.
def raw_ref(kind, ident):
    return "{}#{}".format(kind, ident)


def resolve_raw(bundle, ref):
    """Resolve one raw_ref against a bundle, or None.

    Idents may themselves contain '::' (``trace#marker_000::ground``), so the
    split is on the FIRST '#' only. A bundle slot that is not a mapping — the
    bundle also carries a `schema_version` string at top level
    (`_new_raw_bundle` in tools/bridge/scene_survey_far_side.py) — resolves to None
    raising.
    """
    if not isinstance(ref, str) or "#" not in ref:
        return None
    kind, _, ident = ref.partition("#")
    items = (bundle or {}).get(kind)
    if not isinstance(items, dict):
        return None
    return items.get(ident)


def unresolved_refs(bundle, refs):
    return [r for r in (refs or []) if resolve_raw(bundle, r) is None]


# Kinds EXEMPT from the bundle-wide numeric gate. This is a DENY-list, and the
# direction is the entire point.
#
# It used to be an allow-list of eight kinds. The far side then grew
# `overlap_query`, `capture` and `document` (`_new_raw_bundle` in
# tools/bridge/scene_survey_far_side.py now pre-creates eleven), and all three were
# silently skipped by `numeric_hygiene_ok`. `overlap_query` carries real
# measurements, so a NaN there would have sailed through the gate that exists to
# reject exactly that. An allow-list fails OPEN for anything added later, which is
# the wrong shape for a safety gate: forgetting to update it costs an unchecked
# value rather than a loud error.
#
# `binding` is exempt because it is a projection of a report rather than a
# collector's output; its finiteness is policed by the component that consumes it,
# with a far more specific reason than a bundle-wide sweep could give.
RAW_NON_OBSERVATION_KINDS = ("binding",)

# Retained for readability and for tests asserting the known surface. NOT used to
# select what gets checked — see `observation_kinds_in`.
RAW_OBSERVATION_KINDS = ("world", "actor", "component", "trace", "overlap_query",
                         "marker", "proxy", "capture", "temporary_placement",
                         "inventory", "document")


def observation_kinds_in(bundle):
    """Every dict-valued kind in `bundle` subject to the numeric gate.

    Default-deny by construction: a kind the far side adds tomorrow is checked
    today, with nobody having to remember a list. Scalar bundle metadata
    (`schema_version`, `record_schema_version`) is excluded by the dict test rather
    than by name — naming it would reintroduce the same staleness one level down.
    """
    b = bundle if isinstance(bundle, dict) else {}
    return {k: v for k, v in b.items()
            if isinstance(v, dict) and k not in RAW_NON_OBSERVATION_KINDS}


def iter_refs(rec):
    """Yield (field, ref) for every `*_ref` scalar and `*_refs` list entry.

    Covers the whole live vocabulary: `actor_ref`, `component_refs`,
    `ground_trace_ref`, `footprint_trace_refs`
    (set by `_collect_actor_records` / `_collect_marker_record`) and the evidence
    record's own `raw_refs`.
    """
    if not isinstance(rec, dict):
        return
    for k in sorted(rec):
        v = rec[k]
        if k.endswith("_refs"):
            if isinstance(v, (list, tuple)):
                for x in v:
                    yield k, x
            elif v is not None:
                yield k, v
        elif k.endswith("_ref") and v is not None:
            yield k, v


def _iter_bundle_records(bundle):
    """Yield (kind, ident, record) over every mapping slot of a raw bundle."""
    for kind in sorted(bundle or {}):
        items = (bundle or {})[kind]
        if not isinstance(items, dict):
            continue
        for ident in sorted(items, key=lambda x: str(x)):
            rec = items[ident]
            if isinstance(rec, dict):
                yield kind, ident, rec


def contradictory_atoms(bundle):
    """Atoms that cannot all be true at once. A bundle that argues with itself
    cannot be the ground truth for anything, so these FAIL CLOSED.

    The two marker rules are not style preferences, they are identities the
    collectors are defined by:

      * ``capsule_clear = not overlap`` — set as literally that assignment at
        `_collect_marker_record`. If they ever agree, one of
        them was written by something else.
      * ``accepted = grounded AND footprint AND clearance`` — the compiled
        primitive's definition (`bAccepted` in SceneSurvey.cpp). `accepted` True beside any
        decided-False conjunct means the two channels are describing different
        markers.
    """
    out = []
    for ident, m in sorted((bundle or {}).get("marker", {}).items()
                           if isinstance((bundle or {}).get("marker"), dict) else []):
        if not isinstance(m, dict):
            continue
        cc, ov = m.get("capsule_clear"), m.get("overlap")
        if is_decided(cc) and is_decided(ov) and cc == ov:
            out.append("marker#{}: capsule_clear={} and overlap={} are not "
                       "complements (_collect_marker_record defines capsule_clear "
                       "= not overlap)".format(ident, cc, ov))
        ct, gr = m.get("contact"), m.get("grounded")
        if is_decided(ct) and is_decided(gr) and ct != gr:
            out.append("marker#{}: contact={} and grounded={} restate the SAME "
                       "ground-trace hit and cannot disagree".format(ident, ct, gr))
        if m.get("accepted") is True:
            for f in ("grounded", "footprint", "capsule_clear"):
                if m.get(f) is False:
                    out.append("marker#{}: accepted=True contradicts {}=False "
                               "(SceneSurvey.cpp defines accepted = grounded "
                               "AND footprint AND clearance)".format(ident, f))
            if m.get("overlap") is True:
                out.append("marker#{}: accepted=True contradicts overlap=True"
                           .format(ident))
    for which in ("pre", "post"):
        inv = (bundle or {}).get("inventory")
        rec = inv.get(which) if isinstance(inv, dict) else None
        if not isinstance(rec, dict) or rec.get("collection_ok") is not True:
            continue
        for f in ("actor_paths", "dirty_packages"):
            if not isinstance(rec.get(f), list):
                out.append("inventory#{}: collection_ok=True contradicts {}={!r} "
                           "(`_inventory` sets collection_ok only when both "
                           "sets were actually read)".format(which, f, rec.get(f)))
    out.extend(_placement_contradictions(bundle))
    out.extend(_ledger_contradictions(bundle))
    return out


def _ledger_contradictions(bundle):
    """The ledger's SUMMARY fields against the atoms they summarise.

    `object_count`, `created_object_ids` and `created_object_count` are aggregates
    the far side writes beside the enumeration they were computed from
    (`_SpawnLedger.write_manifest` in tools/bridge/scene_survey_far_side.py). No
    derivation in this module reads them — `_ledger_verdict` recomputes O_created
    from the per-object `creation_observed` atoms — which is exactly why they have
    to be checked HERE rather than trusted or ignored.

    Ignoring a lying aggregate is not safe just because nothing consumes it. A
    manifest whose count disagrees with its own list was written by something other
    than the ledger that produced the atoms, and that is the same forgery shape as
    an overwritten `post_cleanup_presence`: leave the atoms honest, restate them
    wrongly one level up, and hope the reader takes the summary. A bundle in that
    state is not answered from at all.

    The duplicate rule mirrors `check_reference_integrity`'s: an id listed twice in
    a set of owned objects is a ledger that cannot say how many objects it owns, and
    it silently inflates every count derived from the list.

    `created_object_ids` is compared only against the DECLARED ids. A placement the
    ledger never declared is a different defect with a different verdict — it is a
    measured contamination, reported as False by `_ledger_verdict`, not an
    unanswerable bundle.
    """
    out = []
    led = temporary_object_ledger(bundle)
    if led is None:
        return out
    addr = LEDGER_REF
    declared = ledger_declared_ids(led)
    if declared is None:
        return out
    dupes = sorted({i for i in declared if declared.count(i) > 1})
    if dupes:
        out.append("{}: object_ids lists {} more than once — a ledger that names an "
                   "object twice cannot say how many objects it owns, and every "
                   "count taken over that list is inflated".format(addr, dupes))
    n = led.get("object_count")
    if isinstance(n, int) and not isinstance(n, bool) and n != len(set(declared)):
        out.append("{}: object_count={} contradicts its own object_ids ({} distinct "
                   "id(s)) — the aggregate does not summarise the enumeration it "
                   "sits beside".format(addr, n, len(set(declared))))
    created = led.get("created_object_ids")
    if not isinstance(created, list):
        return out
    created = [str(i) for i in created]
    c_dupes = sorted({i for i in created if created.count(i) > 1})
    if c_dupes:
        out.append("{}: created_object_ids lists {} more than once".format(
            addr, c_dupes))
    m = led.get("created_object_count")
    if isinstance(m, int) and not isinstance(m, bool) and m != len(set(created)):
        out.append("{}: created_object_count={} contradicts created_object_ids ({} "
                   "distinct id(s))".format(addr, m, len(set(created))))
    stray = sorted(set(created) - set(declared))
    if stray:
        out.append("{}: created_object_ids names {} which object_ids does not "
                   "declare — the ledger claims to have created an object it does "
                   "not claim to own".format(addr, stray))
    placements = _placements(bundle)
    from_atoms = {i for i in set(declared)
                  if isinstance(placements.get(i), dict)
                  and placements[i].get("creation_observed") is True}
    if from_atoms != set(created) & set(declared):
        out.append("{}: created_object_ids={} contradicts the creation_observed "
                   "atoms of the declared placements, which say {} — the summary "
                   "and the measurements it summarises disagree".format(
                       addr, sorted(set(created) & set(declared)),
                       sorted(from_atoms)))
    return out


def _placement_contradictions(bundle):
    """Temporary-placement atoms that cannot all be true at once.

    `post_cleanup_presence` is DERIVED from `absent_after_cleanup`
    (`_SpawnLedger.cleanup` registers it in `derived_fields`), so the two are one
    measurement under two names and can only disagree if something other than the
    ledger wrote one of them. That is the exact shape of a forged cleanup claim:
    leave the atom honest and overwrite the summary. Same for a record that says
    the object was never created while also reporting a destroy attempt against it,
    and for a value outside either closed vocabulary — an unrecognised state must
    never be silently read as "fine".
    """
    out = []
    items = (bundle or {}).get("temporary_placement")
    if not isinstance(items, dict):
        return out
    for ident in sorted(items, key=str):
        p = items[ident]
        if not isinstance(p, dict):
            continue
        addr = "temporary_placement#{}".format(ident)
        presence = p.get("post_cleanup_presence")
        if presence is not None and presence not in PRESENCE_STATES:
            out.append("{}: post_cleanup_presence {!r} is outside the closed set "
                       "{}".format(addr, presence, list(PRESENCE_STATES)))
        result = p.get("destruction_result")
        if result is not None and result not in DESTRUCTION_RESULTS:
            out.append("{}: destruction_result {!r} is outside the closed set "
                       "{}".format(addr, result, list(DESTRUCTION_RESULTS)))
        absent = p.get("absent_after_cleanup")
        if is_decided(absent) and presence in (PRESENCE_ABSENT, PRESENCE_PRESENT):
            if (presence == PRESENCE_ABSENT) is not bool(absent):
                out.append(
                    "{}: post_cleanup_presence={!r} contradicts "
                    "absent_after_cleanup={!r} — post_cleanup_presence is DERIVED "
                    "from that atom (_SpawnLedger.cleanup), so they restate one "
                    "is_valid measurement and cannot disagree".format(
                        addr, presence, absent))
        if presence == PRESENCE_NEVER_CREATED and p.get("creation_observed") is True:
            out.append("{}: post_cleanup_presence='never_created' contradicts "
                       "creation_observed=True".format(addr))
        if presence == PRESENCE_NEVER_CREATED and p.get("destruction_attempted") is True:
            out.append("{}: post_cleanup_presence='never_created' contradicts "
                       "destruction_attempted=True — an object that was never "
                       "created cannot have been destroyed".format(addr))
        if p.get("creation_observed") is not True \
                and result == DESTRUCTION_DESTROYED:
            out.append("{}: destruction_result='destroyed' with "
                       "creation_observed={!r} — nothing was observed to exist for "
                       "the destroy to have removed".format(
                           addr, p.get("creation_observed")))
    return out


def check_reference_integrity(bundle, operation_id=None):
    """(ok, findings). Every finding is a REJECTION, never a downgrade.

    Rules, all of which fail closed:
      1. a `record_id` must be a non-empty string, unique across the bundle, and
         must not contradict the address it is filed under;
      2. every `*_ref` / `*_refs` entry must be a well-formed `<kind>#<id>` and
         must RESOLVE to a record present in this same bundle;
      3. a ref may not cross operations — referrer and referent must agree on
         `operation_id`, and both must agree with `operation_id` when one is
         supplied by the caller;
      4. contradictory atoms (see `contradictory_atoms`).

    Note what rule 2 buys concretely: the grounding derivation reads the surface
    normal by following a marker's `ground_trace_ref`. A dangling ref there would
    otherwise silently degrade the slope component to unknown, which reads as
    "not measured" when the truth is "the bundle is broken".
    """
    findings = []
    seen_ids = {}
    for kind, ident, rec in _iter_bundle_records(bundle):
        addr = raw_ref(kind, ident)
        rid = rec.get("record_id")
        if rid is not None:
            if not isinstance(rid, str) or not rid.strip():
                findings.append("{}: record_id must be a non-empty string (got "
                                "{!r})".format(addr, rid))
            elif rid in seen_ids and seen_ids[rid] != addr:
                findings.append("duplicate record_id {!r} at {} and {} — a "
                                "record id that addresses two records addresses "
                                "neither".format(rid, seen_ids[rid], addr))
            else:
                seen_ids[rid] = addr
                if rid not in (ident, addr):
                    findings.append("{}: record_id {!r} contradicts the address it "
                                    "is filed under".format(addr, rid))
        rec_op = rec.get("operation_id")
        if operation_id is not None and rec_op is not None and rec_op != operation_id:
            findings.append("{}: operation_id {!r} does not belong to operation "
                            "{!r}".format(addr, rec_op, operation_id))
    for kind, ident, rec in _iter_bundle_records(bundle):
        addr = raw_ref(kind, ident)
        for field, ref in iter_refs(rec):
            if not isinstance(ref, str) or "#" not in ref:
                findings.append("{}.{}: {!r} is not a well-formed <kind>#<id> "
                                "reference".format(addr, field, ref))
                continue
            target = resolve_raw(bundle, ref)
            if target is None:
                findings.append("{}.{}: {!r} does not resolve to any record in "
                                "this bundle".format(addr, field, ref))
                continue
            if isinstance(target, dict):
                t_op = target.get("operation_id")
                r_op = rec.get("operation_id")
                if t_op is not None and r_op is not None and t_op != r_op:
                    findings.append("{}.{}: cross-operation reference — referrer "
                                    "is {!r} but {!r} is {!r}".format(
                                        addr, field, r_op, ref, t_op))
                elif operation_id is not None and t_op is not None \
                        and t_op != operation_id:
                    findings.append("{}.{}: {!r} belongs to operation {!r}, not "
                                    "{!r}".format(addr, field, ref, t_op,
                                                  operation_id))
    findings.extend(contradictory_atoms(bundle))
    return (not findings), findings


def bundle_integrity(bundle, operation_id=None):
    """(ok, detail) — the precondition every derivation is gated on.

    Reference integrity over the whole bundle, plus numeric hygiene over the
    observation kinds. A bundle that fails either is not answered from at all:
    `derive` reports insufficiency, which is `unknown`, which never satisfies a
    rail. That is the "fail closed" requirement stated as one function.
    """
    ok_refs, findings = check_reference_integrity(bundle, operation_id=operation_id)
    ok_num, num_detail = numeric_hygiene_ok(observation_kinds_in(bundle))
    if ok_refs and ok_num:
        return True, "bundle integrity ok"
    parts = []
    if not ok_refs:
        parts.append("reference integrity: " + "; ".join(findings[:5]))
    if not ok_num:
        parts.append(num_detail)
    return False, " | ".join(parts)


# --------------------------------------------------------------------------- #
# Measured predicates — the tri-state triples other lanes emit.
# --------------------------------------------------------------------------- #
# Each observer maps ONE raw record to True / False / UNKNOWN. None of them ever
# invents a value: a field that was not collected yields UNKNOWN, full stop.
PRED_GROUND_CONTACT = "ground_contact"
PRED_FOOTPRINT_SUPPORT = "footprint_support"
PRED_CAPSULE_CLEARANCE = "capsule_clearance"
PRED_OVERLAP_FREE = "overlap_free"
PRED_SUPPORT_TRACE = "support_trace"
PRED_ACTOR_BOUNDS = "actor_bounds"
PRED_PROXY_STATE = "proxy_state"
PRED_PACKAGE_CLEAN = "package_cleanliness"
PRED_TEMPORARY_CLEANUP = "temporary_cleanup"


def _obs_marker_grounded(rec, _bundle=None):
    return tri(rec.get("grounded"))


def _obs_marker_footprint(rec, _bundle=None):
    return tri(rec.get("footprint"))


def _obs_marker_capsule_clear(rec, _bundle=None):
    return tri(rec.get("capsule_clear"))


def _obs_marker_overlap_free(rec, _bundle=None):
    """The GOOD direction of the overlap observation, so AND is meaningful.

    `overlap` True is a bad outcome; aggregating it with AND would read
    backwards. Negated once, here, rather than at every call site.
    """
    return tri_not(rec.get("overlap"))


def _obs_marker_support_traces(rec, _bundle=None):
    """All four footprint corner traces hit, from the ATOMS not the restatement.

    `footprint_trace_hits` is the list of four tri-state trace results
    (set by `_collect_marker_record`). One uncollected corner makes the
    marker's support unknown — not unsupported.
    """
    hits = rec.get("footprint_trace_hits")
    if not isinstance(hits, (list, tuple)) or not hits:
        return UNKNOWN
    if any(not is_decided(h) for h in hits):
        return UNKNOWN
    return all(hits)


def _obs_actor_bounds(rec, _bundle=None):
    return bounds_interval(rec)[0]


def _obs_proxy_state(rec, _bundle=None):
    """Proxy state is UNKNOWN unless a boolean was actually observed.

    The far side files `{"value": None, "collection_ok": False}` for runtime
    proxies because they spawn at BeginPlay and a -nullrhi editor load never
    reaches it (`_record_proxy_unobserved`). That record must
    read as unknown forever, and a `proxy_owners: 0` must never be able to
    impersonate it.
    """
    if rec.get("collection_ok") is not True:
        return UNKNOWN
    return tri(rec.get("value"))


def _obs_inventory_clean(rec, _bundle=None):
    """This snapshot observed an empty dirty-package set.

    Dirtiness is only observable as membership of the engine's dirty sets
    (`_dirty_packages`), so an unread set is None and
    stays unknown. Note this is a per-snapshot measurement; the cleanup RULE is
    the pre/post equality in `derive_cleanup_verified`, not this predicate.
    """
    if rec.get("collection_ok") is not True:
        return UNKNOWN
    d = rec.get("dirty_packages")
    if not isinstance(d, list):
        return UNKNOWN
    return not d


def _obs_temporary_cleanup(rec, _bundle=None):
    """One owned object's cleanup, from BOTH channels, neither of them sufficient.

        cleaned(x) = destroyed(x) AND NOT present_final(x)

    `destruction_result` is the destroy CALL's outcome — the runtime's claim about
    itself — and `post_cleanup_presence` is the independent re-observation through
    `SystemLibrary.is_valid`. Requiring both is the point: the whole hazard is a
    destroy that returns success over an object that is still there, and either
    field alone would report that as a clean run.

    `absent_after_cleanup` is the raw atom `post_cleanup_presence` is derived from
    (`_SpawnLedger.cleanup`); it is read here too so the derivation cannot be
    forged past the atom it claims to come from, and `contradictory_atoms` rejects
    the bundle outright if the two disagree.

    The three decided shapes, and why each is what it is:

      * `present`      -> False. Measured, and bad: the object outlived cleanup.
      * `never_created`-> True only when creation was measured False. Nothing was
                          created, so nothing can have leaked; that is an
                          observation of this operation, not an empty default.
      * `absent`       -> True only with creation observed, a destroy attempted,
                          the destroy reporting success, and the is_valid atom
                          agreeing.

    Anything else — an unread presence, a record with no ledger vocabulary at all —
    is UNKNOWN. There is no legacy fallback to `absent_after_cleanup` alone: a
    record carrying only that field could be produced by a spawn path the ledger
    never saw, and reading it as a pass is the fake-green this predicate exists to
    prevent.
    """
    presence = rec.get("post_cleanup_presence")
    created = tri(rec.get("creation_observed"))
    if presence == PRESENCE_PRESENT:
        return False
    if presence == PRESENCE_NEVER_CREATED:
        return True if created is False else UNKNOWN
    if presence != PRESENCE_ABSENT:
        return UNKNOWN
    if created is not True or rec.get("destruction_attempted") is not True:
        return UNKNOWN
    if rec.get("destruction_result") != DESTRUCTION_DESTROYED:
        return False
    return tri(rec.get("absent_after_cleanup"))


MEASURED_PREDICATES = {
    PRED_GROUND_CONTACT: ("marker", _obs_marker_grounded),
    PRED_FOOTPRINT_SUPPORT: ("marker", _obs_marker_footprint),
    PRED_CAPSULE_CLEARANCE: ("marker", _obs_marker_capsule_clear),
    PRED_OVERLAP_FREE: ("marker", _obs_marker_overlap_free),
    PRED_SUPPORT_TRACE: ("marker", _obs_marker_support_traces),
    PRED_ACTOR_BOUNDS: ("actor", _obs_actor_bounds),
    PRED_PROXY_STATE: ("proxy", _obs_proxy_state),
    PRED_PACKAGE_CLEAN: ("inventory", _obs_inventory_clean),
    PRED_TEMPORARY_CLEANUP: ("temporary_placement", _obs_temporary_cleanup),
}
PREDICATE_NAMES = tuple(sorted(MEASURED_PREDICATES))


def predicate_observations(raw, name):
    """[(ident, tri)] for one predicate over its whole population."""
    kind, fn = MEASURED_PREDICATES[name]
    items = (raw or {}).get(kind)
    if not isinstance(items, dict):
        return []
    out = []
    for ident in sorted(items, key=lambda x: str(x)):
        rec = items[ident]
        out.append((ident, fn(rec, raw) if isinstance(rec, dict) else UNKNOWN))
    return out


def predicate_state(raw, name):
    """The full tri-state picture for one predicate, ids included."""
    obs = predicate_observations(raw, name)
    st = aggregate([v for _i, v in obs])
    st["predicate"] = name
    st["kind"] = MEASURED_PREDICATES[name][0]
    st["unobserved_ids"] = [i for i, v in obs if not is_decided(v)]
    st["false_ids"] = [i for i, v in obs if v is False]
    return st


def predicate_triple(raw, name):
    """The three report fields for one predicate.

    Completeness is exposed SEPARATELY from result. This is the direct fix for
    the defect where a marker population with nothing observed and a marker
    population observed and blocked produced byte-identical output: the first now
    reads `_valid: "unknown", _observed: False, _unobserved_count: n`, the second
    `_valid: False, _observed: True, _unobserved_count: 0`.
    """
    st = predicate_state(raw, name)
    return {
        name + "_observed": st["observed"],
        name + "_valid": st["valid"],
        name + "_unobserved_count": st["unobserved_count"],
    }


def predicate_triples(raw):
    """Every measured predicate's triple, for an assembler to splice into a report."""
    out = {}
    for name in PREDICATE_NAMES:
        out.update(predicate_triple(raw, name))
    return out


def _sufficiency_from_predicate(raw, name, empty_detail=None):
    """Strict population sufficiency: S_x = (n > 0) and (O_x = n)."""
    st = predicate_state(raw, name)
    if st["n"] == 0:
        return False, (empty_detail or
                       "no {} record(s) were collected — there is no population to "
                       "evaluate {} over, and an all()/sum() over an empty list "
                       "yields a confident answer about nothing".format(
                           st["kind"], name))
    if not st["observed"]:
        return False, ("{} of {} {} record(s) never had {} observed (e.g. {}) — the "
                       "aggregate is UNKNOWN, and unknown is not false".format(
                           st["unobserved_count"], st["n"], st["kind"], name,
                           st["unobserved_ids"][:5]))
    return True, "{} of {} {} record(s) observed for {}".format(
        st["decided"], st["n"], st["kind"], name)


def _predicate_inputs(st):
    return {
        "predicate": st["predicate"],
        "records_total": st["n"],
        "records_decided": st["decided"],
        st["predicate"] + "_observed": st["observed"],
        st["predicate"] + "_unobserved_count": st["unobserved_count"],
        "unobserved_ids": st["unobserved_ids"],
        "false_ids": st["false_ids"],
    }


def _predicate_derivation(name):
    """Build the (derive, sufficiency) pair for a straight population predicate."""
    def _d(raw, _n=name):
        st = predicate_state(raw, _n)
        return st["valid"], _predicate_inputs(st)

    def _s(raw, _n=name):
        return _sufficiency_from_predicate(raw, _n)
    return _d, _s


# --------------------------------------------------------------------------- #
# (2) Bounds. A property of the INTERVAL, never of the actor count.
# --------------------------------------------------------------------------- #
def bounds_interval(rec):
    """(B_i, detail) with B_i in {True, False, UNKNOWN}.

        B_i = finite(b^min) AND finite(b^max)
              AND FORALL a in {x,y,z}: b_a^min <= b_a^max

    The far side encodes bounds as origin+extent, never as min/max
    (`_collect_actor_records`), so both encodings are
    accepted and min/max is computed as origin -/+ extent.

    The UNKNOWN / False split is the whole point:
      * bounds never collected at all -> UNKNOWN. The far side emits
        `bounds_extent: None` for any actor whose location could not be read
        (the degraded branch of `_collect_actor_records`), and reading that as "bounds
        invalid" is exactly the coercion this module forbids.
      * bounds collected and bad (non-finite, inverted, or zero-volume) -> False.
        We have the numbers and the numbers are wrong. That is a measurement.
    """
    if not isinstance(rec, dict):
        return UNKNOWN, "not a record"
    lo, hi = rec.get("bounds_min"), rec.get("bounds_max")
    source = "bounds_min/bounds_max"
    if lo is None and hi is None:
        ext = rec.get("bounds_extent")
        if ext is None:
            return UNKNOWN, ("no bounds were collected for this actor (neither "
                             "bounds_min/bounds_max nor bounds_extent)")
        if not _finite3(ext):
            return False, "bounds_extent is not a finite vec3: {!r}".format(ext)
        org = rec.get("bounds_origin")
        if org is None:
            org = [0.0, 0.0, 0.0]
        elif not _finite3(org):
            return False, "bounds_origin is not a finite vec3: {!r}".format(org)
        lo = [float(org[a]) - float(ext[a]) for a in range(3)]
        hi = [float(org[a]) + float(ext[a]) for a in range(3)]
        source = "bounds_origin -/+ bounds_extent"
    if not _finite3(lo):
        return False, "bounds_min is not a finite vec3: {!r}".format(lo)
    if not _finite3(hi):
        return False, "bounds_max is not a finite vec3: {!r}".format(hi)
    inverted = [a for a in range(3) if float(lo[a]) > float(hi[a])]
    if inverted:
        return False, ("inverted interval on axis {}: min={!r} max={!r}".format(
            ["x", "y", "z"][inverted[0]], lo, hi))
    if all(float(hi[a]) == float(lo[a]) for a in range(3)):
        return False, ("degenerate zero-volume bounds (min == max on every axis): "
                       "{!r}".format(lo))
    return True, "finite non-degenerate interval from {}".format(source)


# --------------------------------------------------------------------------- #
# (3) Grounding. G_m, component by component.
# --------------------------------------------------------------------------- #
def _contact_component(rec, _bundle=None):
    """C_m. `contact` is the far side's explicit atom; `grounded` is its older
    restatement of the same trace hit. Either decides, and they cannot disagree
    without the bundle being contradictory."""
    c = tri(rec.get("contact"))
    return c if is_decided(c) else tri(rec.get("grounded"))


def _support_area_component(rec, _bundle=None):
    """A_supported / A_required >= SUPPORT_AREA_RATIO_MIN.

    Three encodings of the same ratio are accepted, most specific first, because
    the collector names them differently as it matures:

      1. `supported_footprint_area_cm2` / `required_footprint_area_cm2` — the
         areas the far side derives (the denominator is the capsule's full
         cross-section, pi * r^2);
      2. `footprint_supported_sample_count` / `footprint_sample_count` — the
         sample counts those areas were computed from. Equal by construction to
         (1), and read so the ratio survives either field surviving;
      3. `support_area_supported` / `support_area_required` — a generic pair, for
         a collector that measures true area rather than samples;
      4. `footprint_trace_hits` — the raw per-corner trace atoms.

    A_required <= 0 is UNKNOWN, not a division by zero and not a pass: a ratio
    over an empty sample set is exactly the empty-population mistake this module
    exists to prevent.
    """
    for sup_key, req_key in (("supported_footprint_area_cm2",
                              "required_footprint_area_cm2"),
                             ("footprint_supported_sample_count",
                              "footprint_sample_count"),
                             ("support_area_supported", "support_area_required")):
        sup, req = rec.get(sup_key), rec.get(req_key)
        if is_finite_number(sup) and is_finite_number(req):
            if float(req) <= 0.0:
                return UNKNOWN
            return (float(sup) / float(req)) >= SUPPORT_AREA_RATIO_MIN
    hits = rec.get("footprint_trace_hits")
    if isinstance(hits, (list, tuple)) and hits and all(is_decided(h) for h in hits):
        return (sum(1 for h in hits if h) / float(len(hits))) >= SUPPORT_AREA_RATIO_MIN
    return UNKNOWN


def _ground_dz_component(rec, _bundle=None):
    """|dz| <= GROUND_DZ_TOLERANCE_CM.

    `ground_delta_z_cm` is the far side's signed delta and is preferred. Failing
    that the delta is reconstructed from `location[2]` and `ground_impact_z`,
    which is an ABSOLUTE Z rather than a delta.
    """
    dz = rec.get("ground_delta_z_cm")
    if not is_finite_number(dz):
        loc, iz = rec.get("location"), rec.get("ground_impact_z")
        if not (_finite3(loc) and is_finite_number(iz)):
            return UNKNOWN
        dz = float(loc[2]) - float(iz)
    return abs(float(dz)) <= GROUND_DZ_TOLERANCE_CM


def _slope_component(rec, bundle=None):
    """n_hat . z_hat >= cos(GROUND_MAX_SLOPE_DEG).

    The far side computes n_hat . z_hat itself and says, in the record, that it
    supplies no theta_max because "grounding thresholds are policy, not
    observations" (`GROUNDING_THRESHOLDS` in
    tools/bridge/scene_survey_far_side.py). This function is the deriving side
    that supplies it — the observation and the threshold stay in different files
    on purpose.

    Resolution order: the precomputed dot; then the normal on the marker; then the
    normal on the ground trace the marker REFERENCES. That last hop is why
    reference integrity is load-bearing here rather than decorative: a dangling
    `ground_trace_ref` would otherwise degrade this component to unknown, which
    reads as "not measured" when the truth is "the bundle is broken" — which is
    why `derive` rejects such a bundle outright before this is ever reached.
    """
    dot = rec.get("ground_surface_normal_dot_up")
    if is_finite_number(dot):
        return float(dot) >= GROUND_MAX_SLOPE_COS
    n = None
    for key in ("ground_surface_normal_unit", "ground_surface_normal",
                "ground_normal"):
        if _finite3(rec.get(key)):
            n = rec.get(key)
            break
    if n is None:
        trace = resolve_raw(bundle, rec.get("ground_trace_ref"))
        n = trace.get("impact_normal") if isinstance(trace, dict) else None
    if not _finite3(n):
        return UNKNOWN
    mag = math.sqrt(sum(float(c) ** 2 for c in n))
    if not is_finite_number(mag) or mag <= 0.0:
        return UNKNOWN  # a zero-length normal is not a direction
    return (float(n[2]) / mag) >= GROUND_MAX_SLOPE_COS


GROUNDING_COMPONENTS = ("contact", "support_area", "ground_dz", "slope")


def ground_contact_observation(rec, bundle=None):
    """(G_m, components) — Kleene conjunction of the four grounding components."""
    comps = {
        "contact": _contact_component(rec, bundle),
        "support_area": _support_area_component(rec, bundle),
        "ground_dz": _ground_dz_component(rec, bundle),
        "slope": _slope_component(rec, bundle),
    }
    return tri_and(comps[c] for c in GROUNDING_COMPONENTS), comps


def _obs_marker_grounding(rec, bundle=None):
    return ground_contact_observation(rec, bundle)[0]


def sufficiency_grounding(raw):
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    if not markers:
        return False, ("no per-marker records were collected — G_m has no "
                       "population")
    undecided = []
    for ident in sorted(markers):
        rec = markers[ident]
        g, comps = ground_contact_observation(rec if isinstance(rec, dict) else {},
                                              raw)
        if not is_decided(g):
            undecided.append("{} ({})".format(
                ident, ", ".join(sorted(c for c in GROUNDING_COMPONENTS
                                        if not is_decided(comps[c])))))
    if undecided:
        return False, ("G_m is UNKNOWN for {} of {} marker(s) because a component "
                       "was never observed: {} — an unobserved component is not a "
                       "failed one".format(len(undecided), len(markers),
                                           undecided[:5]))
    return True, "G_m decided for all {} marker(s)".format(len(markers))


def derive_grounding_valid(raw):
    """AND_m G_m over the marker population, with the per-component breakdown."""
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    per = {}
    for ident in sorted(markers):
        rec = markers[ident]
        g, comps = ground_contact_observation(rec if isinstance(rec, dict) else {},
                                              raw)
        per[ident] = {"G_m": g, "components": comps}
    st = aggregate([v["G_m"] for v in per.values()])
    return st["valid"], {
        "markers_total": st["n"],
        "grounding_observed": st["observed"],
        "grounding_unobserved_count": st["unobserved_count"],
        "rejected_ids": sorted(k for k, v in per.items() if v["G_m"] is False),
        "unobserved_ids": sorted(k for k, v in per.items()
                                 if not is_decided(v["G_m"])),
        "thresholds": {"SUPPORT_AREA_RATIO_MIN": SUPPORT_AREA_RATIO_MIN,
                       "GROUND_DZ_TOLERANCE_CM": GROUND_DZ_TOLERANCE_CM,
                       "GROUND_MAX_SLOPE_DEG": GROUND_MAX_SLOPE_DEG},
        "per_marker": per,
    }


# --------------------------------------------------------------------------- #
# Derivations. Pure functions over RAW observations.
# --------------------------------------------------------------------------- #
# Each returns (value, inputs_description). Each is paired with a SUFFICIENCY
# precondition stating what raw is required before the question is even askable.
# Sufficiency is separate from the derivation on purpose: an empty input list will
# happily produce a confident-looking answer from `all()` or `sum()`, and that is
# exactly the "empty result mistaken for a valid zero" failure mode.

def sufficiency_actor_bounds(raw):
    """Bounds validity needs per-actor bounds INTERVALS, not a count.

    Strict: every collected actor must have had its bounds observed. Previously
    ONE actor carrying an extent was enough, and every actor without one was then
    scored as a bounds FAILURE — so an actor whose location could not even be
    read manufactured a confident `actor_bounds_valid: False`.
    That is unknown wearing false's clothes, and it is gone.
    """
    return _sufficiency_from_predicate(
        raw, PRED_ACTOR_BOUNDS,
        empty_detail=("no per-actor records were collected — an actor COUNT "
                      "cannot answer whether bounds are valid"))


def derive_actor_bounds_valid(raw):
    """ActorBoundsValid = (n > 0) AND AND_i B_i. See `bounds_interval` for B_i."""
    actors = (raw or {}).get("actor")
    actors = actors if isinstance(actors, dict) else {}
    st = predicate_state(raw, PRED_ACTOR_BOUNDS)
    reasons = []
    for ident in st["false_ids"][:5] + st["unobserved_ids"][:5]:
        reasons.append("{}: {}".format(ident, bounds_interval(actors.get(ident))[1]))
    inputs = _predicate_inputs(st)
    inputs.update({"actors_checked": st["n"],
                   "actors_rejected": st["false_ids"],
                   "actors_unobserved": st["unobserved_ids"],
                   "reasons": reasons})
    return st["valid"], inputs


def sufficiency_markers(raw):
    """Existence of a marker POPULATION only.

    This establishes that there is something to count. It deliberately does NOT
    establish that any observation was made about those markers, so it is valid
    ONLY for `temporary_placements_requested`, which counts records. Every
    predicate ABOUT the markers uses a per-field sufficiency instead — using this
    one for them was the defect that made "never measured" and "measured and
    blocked" produce identical output.
    """
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    if not markers:
        return False, ("no per-marker records were collected — nothing to classify. "
                       "An all()/sum() over an empty list yields a confident answer "
                       "about nothing")
    return True, "{} marker record(s)".format(len(markers))


def sufficiency_marker_accepted(raw):
    """`accepted` is a VERDICT the far side echoes, so it gets its own rail.

    It is not registered as a measured predicate: the non-circularity rule says a
    validator may not consume a success flag the runtime declared about itself.
    Counting it is allowed (the count is diagnostic, and disagreement between it
    and the grounded count is the signal), but the count must still be sound —
    an undecided `accepted` makes the count unknown.
    """
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    if not markers:
        return False, "no per-marker records were collected"
    undecided = sorted(k for k, m in markers.items()
                       if not is_decided((m or {}).get("accepted")))
    if undecided:
        return False, ("{} of {} marker(s) never had `accepted` decided ({}) — a "
                       "count over undecided observations is not a count".format(
                           len(undecided), len(markers), undecided[:5]))
    return True, "accepted decided for all {} marker(s)".format(len(markers))


def derive_placements_grounded(raw):
    """Count markers whose GROUND CONTACT was observed — not those accepted.

    `accepted` is strictly stronger (grounded AND footprint AND clearance), so
    using it under this name under-reports grounded candidates and makes the two
    fields impossible to disagree, which destroys their diagnostic value.
    """
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    ids = sorted(k for k, m in markers.items() if (m or {}).get("grounded") is True)
    return len(ids), {"markers_total": len(markers), "grounded_ids": ids}


def derive_placements_accepted(raw):
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    ids = sorted(k for k, m in markers.items() if (m or {}).get("accepted") is True)
    return len(ids), {"markers_total": len(markers), "accepted_ids": ids}


def derive_placements_requested(raw):
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    return len(markers), {"markers_total": len(markers)}


def derive_overlap_count(raw):
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    ids = sorted(k for k, m in markers.items() if (m or {}).get("overlap") is True)
    return len(ids), {"markers_total": len(markers), "overlapping_ids": ids}


def sufficiency_player_clearance(raw):
    return _sufficiency_from_predicate(raw, PRED_CAPSULE_CLEARANCE)


def derive_player_clearance_valid(raw):
    """Clearance from the OBSERVED capsule test, independent of acceptance.

    The previous predicate `(not accepted) or clearance` was a tautology: the C++
    defines accepted = grounded && footprint && clearance, so accepted implies
    clearance by construction. Deriving from the raw overlap observation instead
    makes the claim falsifiable — a marker CAN be observed overlapping.

    `blocked_ids` now means DECIDED-blocked. It used to mean `capsule_clear is
    not True`, which swept the never-measured markers in with the blocked ones;
    they are reported apart, under `unobserved_ids`.
    """
    st = predicate_state(raw, PRED_CAPSULE_CLEARANCE)
    inputs = _predicate_inputs(st)
    inputs.update({"markers_total": st["n"], "blocked_ids": st["false_ids"]})
    return st["valid"], inputs


def _map_identity(inv):
    """M — the persistent map/package identity a snapshot witnessed, or None.

    The far side sets `map_identity` and `package_identity` from the same
    observed world package (`_inventory` in the far side); both are carried so
    that a future divergence between them is visible rather than silently
    collapsed.
    """
    if not isinstance(inv, dict):
        return None
    m, p = inv.get("map_identity"), inv.get("package_identity")
    if not isinstance(m, str) or not m.strip():
        return None
    return (m, p)


def sufficiency_cleanup(raw):
    """Cleanup needs a BEFORE and an AFTER inventory, and the after must be after.

    It also needs all three sets of the CleanupVerified identity to have been
    MEASURED on both sides:

        D — dirty_packages           (None when the engine set was unreadable)
        T — operation_owned_actor_paths ([] is a measurement; absent is not)
        M — map_identity / package_identity

    T is the one worth stating twice. `_SpawnLedger.owned_paths()` returns [] and
    that emptiness is a real observation of a real ledger
    (`_SpawnLedger.owned_paths`). An inventory that OMITS the
    key is a different fact, and defaulting it to the empty set would make
    "nothing was tracked" and "nothing was left behind" the same sentence — which
    is precisely how a hard-coded `cleanup_verified=True` gets rebuilt by
    accident.
    """
    inv = (raw or {}).get("inventory")
    inv = inv if isinstance(inv, dict) else {}
    pre, post = inv.get("pre"), inv.get("post")
    if pre is None or post is None:
        return False, ("cleanup requires both a pre and a post inventory (have "
                       "pre={}, post={})".format(pre is not None, post is not None))
    if pre.get("stage") not in STAGES or post.get("stage") not in STAGES:
        return False, "inventory records must name a known stage"
    # The post inventory must be taken at cleanup or later AND strictly after the
    # pre inventory. Two snapshots from the same stage witness nothing: an
    # inventory taken before cleanup ran cannot testify about the state cleanup
    # left behind, however honestly it was collected.
    if STAGE_ORDER[post["stage"]] < STAGE_ORDER["cleanup"]:
        return False, ("the post inventory was taken at stage {!r}, before cleanup "
                       "ran — it cannot witness cleanup".format(post["stage"]))
    if STAGE_ORDER[post["stage"]] <= STAGE_ORDER[pre["stage"]]:
        return False, ("the post inventory stage {!r} does not strictly follow the "
                       "pre inventory stage {!r}".format(post["stage"], pre["stage"]))
    if post.get("collection_ok") is not True or pre.get("collection_ok") is not True:
        return False, "an inventory whose collection failed proves nothing"
    for which, snap in (("pre", pre), ("post", post)):
        for field, label in (("actor_paths", "the level actor set"),
                             ("dirty_packages", "D, the dirty-package set"),
                             ("operation_owned_actor_paths",
                              "T, the operation-owned temporary-object set")):
            if not isinstance(snap.get(field), list):
                return False, ("the {} inventory carries no {} ({}={!r}) — an "
                               "unmeasured set must not be read as the empty set"
                               .format(which, label, field, snap.get(field)))
        if _map_identity(snap) is None:
            return False, ("the {} inventory carries no M, the persistent map "
                           "identity (map_identity={!r})".format(
                               which, snap.get("map_identity")))
    ok_led, led_detail = _ledger_sufficiency(raw)
    if not ok_led:
        return False, led_detail
    return True, ("pre@{} post@{}, with D, T and M measured on both, and {}".format(
        pre["stage"], post["stage"], led_detail))


def _ledger_sufficiency(raw):
    """(ok, detail) for the per-object conjunct's inputs. NO ledger => NOT ENOUGH.

    This is the whole reason the ledger exists. `(O_1 == O_0) AND (D_1 == D_0) AND
    (P_1 == P_0)` is computed from two snapshots of the world, and two snapshots
    cannot see an object that was created AND destroyed between them: it is absent
    from both, so every set comparison agrees and the verdict comes out True. The
    fourth conjunct —

        for every x in O_created: destroyed(x) AND NOT present_final(x)

    — is the only one that ranges over objects rather than over states of the
    world, and O_created can only come from a ledger that was watching the spawn
    path. Its absence therefore yields `unknown`. It must NEVER yield success,
    because "no ledger" and "a ledger that recorded nothing" are the same bytes to
    a consumer that defaults the missing one to the empty set.

    Everything refused here is refused as INSUFFICIENT (unknown), not as False. A
    verdict of False would claim a defect in the world; these are all defects in
    the observation.
    """
    led = temporary_object_ledger(raw)
    if led is None:
        return False, (
            "no temporary-object ledger at {} — the operation filed no record of "
            "what it created, so O_created is unknown and the per-object cleanup "
            "conjunct is unaskable. Deriving cleanup from the pre/post inventories "
            "alone would report success for an object created AND destroyed "
            "between the two snapshots, which neither snapshot can see.".format(
                LEDGER_REF))
    if led.get("collection_ok") is not True:
        return False, ("the temporary-object ledger reports collection_ok={!r} — a "
                       "ledger that did not collect witnesses nothing".format(
                           led.get("collection_ok")))
    if led.get("cleanup_ran") is not True:
        return False, ("the temporary-object ledger reports cleanup_ran={!r}: the "
                       "operation never reached its cleanup stage, so the post "
                       "inventory describes a world cleanup was never run "
                       "on".format(led.get("cleanup_ran")))
    tag = led.get("ownership_tag")
    if not (isinstance(tag, str) and tag.strip()):
        return False, ("the temporary-object ledger carries no ownership_tag "
                       "({!r}) — without one, an object it lists cannot be "
                       "attributed to this operation".format(tag))
    declared = ledger_declared_ids(led)
    if declared is None:
        return False, ("the temporary-object ledger carries no object_ids list "
                       "({!r}) — an unmeasured set must not be read as the empty "
                       "set".format(led.get("object_ids")))
    # An introspection hole is not an observation. `unledgered_spawn_call_sites`
    # is None when the far side could not read its own source; that does not block
    # (it is a fact about the collector, not about the world), but a POSITIVE count
    # does: a second spawn path means O_created can be incomplete, and a conjunct
    # quantified over an incomplete set is vacuous rather than satisfied.
    stray = led.get("unledgered_spawn_call_sites")
    if isinstance(stray, int) and not isinstance(stray, bool) and stray > 0:
        return False, ("the far side measured {} spawn call site(s) outside "
                       "`_SpawnLedger.spawn_transient` — the ledger cannot be shown "
                       "to enumerate every object this operation created, so "
                       "O_created is incomplete".format(stray))
    placements = _placements(raw)
    missing = [i for i in declared if not isinstance(placements.get(i), dict)]
    if missing:
        return False, ("the ledger declares object id(s) {} with no matching "
                       "temporary_placement record — a declared object with no "
                       "record cannot be checked for removal".format(missing[:5]))
    # Every CREATED object must have answered both channels. An unread final state
    # is the one thing that must not round to either verdict.
    for oid in declared:
        p = placements[oid]
        born = tri(p.get("creation_observed"))
        # `creation_observed` is the gate on the whole per-object conjunct, so an
        # undecided one must REFUSE, not skip. Skipping it treats "we do not know
        # whether this operation created the object" as "it created nothing", which
        # is the tri-state collapse this module exists to prevent — and it is
        # trivially forgeable: blank one field on a leaked object's record and the
        # object drops out of `for every x in O_created` entirely, taking its
        # witnessed leak with it. The far side never emits it undecided
        # (`_SpawnLedger.spawn_transient` writes False at record creation and True
        # only on a returned handle), so anything undecided arriving here is a
        # degraded or edited bundle, and neither may be answered from.
        if born is UNKNOWN:
            # ...UNLESS the object's final state already decides the record. A
            # `present` object filed under this operation's ledger is a measured
            # leak whatever the creation channel says, and refusing as unknown there
            # would upgrade a witnessed defect in the WORLD into a defect in the
            # pass. This is the same Kleene rule `_obs_temporary_cleanup` applies
            # within a record: false dominates unknown; unknown never becomes true.
            if p.get("post_cleanup_presence") == PRESENCE_PRESENT:
                continue
            return False, ("temporary_placement#{}: creation_observed={!r} is not a "
                           "decided observation — whether this operation created "
                           "the object is unknown, so `for every x in O_created` "
                           "cannot be asked of it. unknown is not 'never "
                           "created'.".format(oid, p.get("creation_observed")))
        if born is False:
            continue
        presence = p.get("post_cleanup_presence")
        if presence not in PRESENCE_DECIDED:
            return False, ("temporary_placement#{}: creation was observed but the "
                           "final state was not — post_cleanup_presence={!r}. An "
                           "unwitnessed removal is unknown, never clean.".format(
                               oid, presence))
        if p.get("destruction_result") not in DESTRUCTION_RESULTS:
            return False, ("temporary_placement#{}: destruction_result={!r} is "
                           "outside the closed vocabulary {}".format(
                               oid, p.get("destruction_result"),
                               list(DESTRUCTION_RESULTS)))
        if presence == PRESENCE_ABSENT and not is_decided(
                p.get("absent_after_cleanup")):
            return False, ("temporary_placement#{}: post_cleanup_presence='absent' "
                           "but the atom it is derived from, absent_after_cleanup, "
                           "is {!r} — a summary with no measurement under it".format(
                               oid, p.get("absent_after_cleanup")))
    return True, ("a temporary-object ledger that ran cleanup over {} declared "
                  "object(s), {} of them created".format(
                      len(declared),
                      sum(1 for i in declared
                          if placements[i].get("creation_observed") is True)))


def derive_cleanup_verified(raw):
    """The operator's CleanupVerified, in full.

        O_0, O_1 = operation-owned objects before execution / after cleanup
        D_0, D_1 = dirty-package sets before / after
        P_0, P_1 = persistent package identity (and, where observable, content)

        CleanupVerified = (O_1 == O_0) AND (D_1 == D_0) AND (P_1 == P_0)
                          AND for every x in O_created:
                                  destroyed(x) AND NOT present_final(x)

    EQUALITY, not containment, on the set terms. The rule this replaced only looked
    for NEWLY dirty packages; a package that STOPS being dirty was written to disk,
    and a survey that saves a map has mutated the project just as surely as one
    that dirties it. The actor-set comparison is retained on top — strictly
    additional, never a replacement.

    THE FOURTH CONJUNCT IS NOT REDUNDANT. The first three range over states of the
    world at two instants; the fourth ranges over OBJECTS. An object created after
    the pre snapshot and destroyed before the post snapshot is absent from both, so
    every set comparison agrees and the first three conjuncts are all True while
    the operation did in fact mutate the level. Only the ledger can see it, which
    is why `sufficiency_cleanup` refuses to answer at all without one.

    P has two halves and only one is observable from UE Python. The IDENTITY half
    (which package is open) is `map_identity` / `package_identity` and is ANDed in
    as `persistent_package_identity_equal`. The CONTENT half (a hash of the
    persistent package) has no Python api at all — see the far side's
    PACKAGE_HASH_UNSUPPORTED_REASON — so it is reported as
    `persistent_package_hash_supported: False` with a NULL comparison and is NOT
    folded into the AND. An unavailable comparison is never coerced into agreement.

    Empty is the expected case: an operation that begins with no owned temporary
    objects has O_0 == O_1 == {} and a vacuously satisfied fourth conjunct, and
    that reads True — but only because the ledger was present and said so.
    """
    snapshot_ok, inputs = _inventory_only_cleanup_verdict(raw)
    ledger = _ledger_verdict(raw)
    inputs.update(ledger)
    return bool(snapshot_ok and ledger["ledger_conjunct"]), inputs


def _inventory_only_cleanup_verdict(raw):
    """(ok, inputs) for the THREE SNAPSHOT conjuncts alone: O, D and P-identity.

    Split out under a name that says what it is, for two reasons. It keeps the
    formula's snapshot half readable next to its object half — and it is the exact
    rule this module applied BEFORE the ledger existed, so a test can call it
    directly and demonstrate that it answers True for a bundle in which an object
    was created and destroyed between the two snapshots
    (tools/pipeline/test_negative_scene_survey_cleanup.py, mutant 1). That
    demonstration is what makes the ledger's necessity a measurement instead of an
    argument.

    NEVER call this as the cleanup verdict. It cannot fail on a short-lived object,
    which is the entire reason `derive_cleanup_verified` ANDs the ledger conjunct on
    top and `sufficiency_cleanup` refuses to answer without one.
    """
    inv = (raw or {}).get("inventory")
    inv = inv if isinstance(inv, dict) else {}
    pre, post = inv.get("pre") or {}, inv.get("post") or {}

    pre_actors = set(pre.get("actor_paths") or [])
    post_actors = set(post.get("actor_paths") or [])
    leaked = sorted(post_actors - pre_actors)
    vanished = sorted(pre_actors - post_actors)

    d_i = set(pre.get("dirty_packages") or [])
    d_f = set(post.get("dirty_packages") or [])
    newly_dirty = sorted(d_f - d_i)
    no_longer_dirty = sorted(d_i - d_f)

    t_i = set(pre.get("operation_owned_actor_paths") or [])
    t_f = set(post.get("operation_owned_actor_paths") or [])
    temp_leaked = sorted(t_f - t_i)
    temp_released = sorted(t_i - t_f)

    m_i, m_f = _map_identity(pre), _map_identity(post)
    map_identity_stable = (m_i is not None and m_i == m_f)

    hash_supported, hash_equal, hash_detail = _persistent_hash_comparison(pre, post)

    ok = (not leaked and not vanished and not newly_dirty and not no_longer_dirty
          and not temp_leaked and not temp_released and map_identity_stable
          # `is not False`, not `is True`: an UNSUPPORTED comparison must not block
          # the verdict (it is not evidence of a mutation), and a SUPPORTED one that
          # disagrees must. The distinction is the whole reason this is tri-state.
          and hash_equal is not False)
    return ok, {
        "dirty_packages_equal": d_i == d_f,
        "newly_dirty_packages": newly_dirty,
        "no_longer_dirty_packages": no_longer_dirty,
        "temporary_objects_equal": t_i == t_f,
        "temporary_objects_leaked": temp_leaked,
        "temporary_objects_released": temp_released,
        "operation_owned_pre": sorted(t_i), "operation_owned_post": sorted(t_f),
        "map_identity_equal": map_identity_stable,
        "map_identity_pre": m_i, "map_identity_post": m_f,
        # P, named as the formula names it. The identity half is the same
        # comparison as map_identity_equal and IS in the AND; the content half is
        # unsupported and is NOT. Both are stated so no reader has to work out
        # which half of P was actually checked.
        "persistent_package_identity_equal": map_identity_stable,
        "persistent_package_hash_supported": hash_supported,
        "persistent_package_hash_equal": hash_equal,
        "persistent_package_hash_detail": hash_detail,
        "persistent_package_hash_pre": pre.get("persistent_package_hash"),
        "persistent_package_hash_post": post.get("persistent_package_hash"),
        "leaked_actors": leaked, "vanished_actors": vanished,
        "actors_pre": len(pre_actors), "actors_post": len(post_actors),
        "snapshot_conjuncts_ok": ok,
    }


_HASH_UNSUPPORTED_DETAIL = (
    "no UE Python api exposes a content hash of a persistent package; the content "
    "half of P_1 == P_0 is unsupported and is deliberately NOT folded into the "
    "conjunction (see the far side's PACKAGE_HASH_UNSUPPORTED_REASON)")


def _persistent_hash_comparison(pre, post):
    """(supported, equal, detail) for the CONTENT half of P, READ FROM THE RAW.

    These three used to be written as the literals `False`, `None` and a fixed
    sentence — correct for today's far side, which has no hash api, and fail-OPEN
    for any far side that gains one. A hardcoded `supported=False` cannot be made to
    disagree by any input, so the moment the collector starts emitting real hashes
    the consumer would keep reporting the comparison unavailable and a MUTATED
    persistent package would derive as clean. That is the same shape as the
    allow-list this module already replaced with a deny-list in
    `observation_kinds_in`: forgetting to update it must cost a loud error, not an
    unchecked value.

    Tri-state, and the three states mean different things:

        supported=False, equal=None   the far side declares no hash channel. NOT
                                      folded into the AND — an unavailable
                                      comparison is never coerced into agreement.
        supported=True,  equal=True   both snapshots hashed and the hashes match.
        supported=True,  equal=False  the persistent package's CONTENT changed. A
                                      measured mutation, and a False verdict.

    Support requires BOTH snapshots to declare it AND both to carry a real string.
    A snapshot that claims support while carrying no hash has declared a channel it
    did not read, and half a comparison is not a comparison.
    """
    h_i, h_f = pre.get("persistent_package_hash"), post.get("persistent_package_hash")
    declared = (pre.get("persistent_package_hash_supported") is True
                and post.get("persistent_package_hash_supported") is True)
    readable = (isinstance(h_i, str) and h_i.strip()
                and isinstance(h_f, str) and h_f.strip())
    if not declared:
        return False, None, _HASH_UNSUPPORTED_DETAIL
    if not readable:
        return False, None, (
            "both snapshots declare persistent_package_hash_supported=True but the "
            "hashes read {!r} / {!r} — a declared channel that carried no value is "
            "still an unavailable comparison, never an agreeing one".format(h_i, h_f))
    return True, (h_i == h_f), (
        "persistent package content hash {} -> {}".format(h_i, h_f))


def _ledger_verdict(raw):
    """The per-object conjunct: FORALL x in O_created: destroyed(x) AND NOT present(x).

    Reached only after `_ledger_sufficiency` passed, so every created object here
    has a decided final state and a destruction result inside the closed
    vocabulary. Everything this function can report is therefore a MEASUREMENT of
    the world, and every one of them is a False rather than an unknown.

    Two contamination checks ride along, because both make the quantifier lie
    rather than fail:

      * an UNLEDGERED placement — a temporary_placement record the ledger's
        `object_ids` does not list. The record exists, so something created it; the
        ledger did not see it, so `for every x in O_created` never visits it.
      * a FOREIGN placement — a record whose `operation_id` is not this operation's.
        Another operation's object cannot be cleaned up by this one, and counting
        its clean removal towards this operation's verdict would let one run
        inherit another's evidence.
    """
    led = temporary_object_ledger(raw) or {}
    placements = _placements(raw)
    declared = ledger_declared_ids(led) or []
    declared_set = set(declared)
    op = led.get("operation_id")

    unledgered = sorted(str(k) for k in placements if str(k) not in declared_set)
    foreign = sorted(
        str(k) for k, r in placements.items()
        if isinstance(r, dict) and r.get("operation_id") is not None
        and op is not None and r.get("operation_id") != op)
    tag = led.get("ownership_tag")
    misattributed = sorted(
        str(k) for k, r in placements.items()
        if isinstance(r, dict) and r.get("ownership_tag") is not None
        and tag is not None and r.get("ownership_tag") != tag)

    created, not_destroyed, still_present, creation_undecided = [], [], [], []
    for oid in sorted(declared_set):
        p = placements.get(oid)
        if not isinstance(p, dict):
            continue
        # A DECIDED `present` is collected BEFORE the creation gate. It is a
        # measurement that an object filed under this operation's ledger id was
        # still in the world after cleanup, and that is a leak whatever the creation
        # channel says. Gating it on `creation_observed is True` would mean blanking
        # that one field erases a witnessed leak from the verdict.
        if p.get("post_cleanup_presence") == PRESENCE_PRESENT:
            still_present.append(oid)
        born = tri(p.get("creation_observed"))
        if born is UNKNOWN:
            # Reported, never voted on. An undecided creation makes the conjunct
            # UNASKABLE for this object, which is `unknown` — and unknown is a
            # sufficiency answer, not a verdict. `_ledger_sufficiency` refuses the
            # whole derivation on it, so this list is empty by the time a value is
            # returned; it is carried so the input record shows why, and so this
            # function is not silently permissive if it is ever called directly.
            creation_undecided.append(oid)
            continue
        if born is not True:
            continue
        created.append(oid)
        if p.get("destruction_result") != DESTRUCTION_DESTROYED:
            not_destroyed.append(oid)
        if p.get("post_cleanup_presence") != PRESENCE_ABSENT \
                and oid not in still_present:
            still_present.append(oid)

    foreign_world = _foreign_world_placements(raw, led, placements)

    conjunct = not (unledgered or foreign or misattributed or not_destroyed
                    or still_present or foreign_world)
    return {
        "ledger_present": temporary_object_ledger(raw) is not None,
        # NOT named `*_ref`: this is an evidence-record input, and every `*_ref`
        # suffix in this codebase is walked by a raw-bundle reference resolver
        # (`iter_refs`). A field that looks addressable but is not is a trap.
        "ledger_record_id": LEDGER_REF,
        "ledger_ownership_tag": tag,
        "ledger_cleanup_ran": led.get("cleanup_ran") is True,
        "ledger_declared_object_ids": sorted(declared_set),
        "ledger_created_object_ids": created,
        "ledger_created_count": len(created),
        "ledger_objects_not_destroyed": not_destroyed,
        "ledger_objects_present_after_cleanup": still_present,
        "ledger_objects_creation_undecided": creation_undecided,
        "ledger_unledgered_placements": unledgered,
        "ledger_foreign_operation_placements": foreign,
        "ledger_misattributed_placements": misattributed,
        "ledger_foreign_world_placements": foreign_world,
        "ledger_conjunct": conjunct,
    }


def _witnessed_world_identities(raw, led):
    """Every non-empty world/package identity this operation's evidence witnessed.

    Three independent witnesses: the ledger's own `package_identity`, and the map
    identity of each inventory snapshot. All three are read from the live editor by
    the far side (`_world_identity` / `_inventory`), never back-filled from the
    request, so they are measurements rather than echoes.
    """
    inv = (raw or {}).get("inventory")
    inv = inv if isinstance(inv, dict) else {}
    seen = [(led or {}).get("package_identity")]
    for which in ("pre", "post"):
        ident = _map_identity(inv.get(which))
        if ident is not None:
            seen.extend(ident)
    return {v for v in seen if isinstance(v, str) and v.strip()}


def _foreign_world_placements(raw, led, placements):
    """Placements claiming a world this operation's inventories never witnessed.

    An object recorded as created in a world other than the one the snapshots were
    taken in cannot be reasoned about by those snapshots at all: its removal was
    never in their scope, so counting it towards this operation's cleanup imports
    evidence from a world nobody here looked at. Same family as the foreign
    `operation_id` and the misattributed `ownership_tag` — a contaminant that makes
    the quantifier lie rather than fail — and reported the same way, as a measured
    False.

    Compared only when BOTH sides are non-empty strings. `_world_identity()` is None
    until `_record_world` has read the editor, and an unread identity is not a
    mismatch.
    """
    witnessed = _witnessed_world_identities(raw, led)
    if not witnessed:
        return []
    out = []
    for k, r in (placements or {}).items():
        if not isinstance(r, dict):
            continue
        claimed = [v for v in (r.get("world_identity"), r.get("package_identity"))
                   if isinstance(v, str) and v.strip()]
        if claimed and not (set(claimed) & witnessed):
            out.append(str(k))
    return sorted(out)


def derive_temporary_actor_count(raw, which):
    inv = (raw or {}).get("inventory")
    inv = (inv if isinstance(inv, dict) else {}).get(which) or {}
    owned = inv.get("operation_owned_actor_paths")
    if not isinstance(owned, list):
        return None, {"reason": "inventory carries no operation-owned actor list"}
    return len(owned), {"operation_owned": sorted(owned)}


# --------------------------------------------------------------------------- #
# Acceptance eligibility — the identifiability invariant, as evidence.
# --------------------------------------------------------------------------- #
# Acceptance eligibility is NOT a policy switch and NOT a free-floating boolean.
# It is a derived claim like any other in this module: it has raw inputs, a stated
# derivation, and a sufficiency precondition, and it can be independently
# re-derived by a validator that never reads the claim itself.
#
# WHY ONE ANCHOR MODE AND NOT THE OTHER
# -------------------------------------
# The reason is IDENTIFIABILITY, not preference. Consider the observation vector a
# survey can produce about its subject:
#
#     (observed world package, resolved actor object path, observed actor transform)
#
# Under `actor_object_path` all three coordinates are measured on the far side and
# vary INDEPENDENTLY of the request: the editor can open a different world, resolve
# a different actor, or report a transform the caller never mentioned, and each of
# those disagreements is visible from the pair. The map from subject identity to
# observation is injective on the components that matter, so a wrong subject is
# detectable.
#
# Under `explicit_transform` only the world is independently observed. The anchor
# coordinates are COPIED from the caller's own input — the far side is handed a
# location and reports back the location it was handed — so the observation map is
# rank-deficient with respect to subject identity. Comparing the observed anchor to
# the requested anchor compares a value to a copy of itself, and no comparison over
# such a vector can distinguish correct subject coordinates from arbitrary
# caller-supplied ones. A survey can still be VALID under this mode (its samples,
# bounds and cleanup are real measurements); what it can never be is ACCEPTANCE-
# eligible, because acceptance is a claim about the SUBJECT, and the subject's
# coordinates were never independently observed.
#
# Do not "simplify" this into a mode allow-list without the reasoning: the next
# reader will see two enum values and one of them arbitrarily blessed, and will
# helpfully bless the other one too.

# The resolver every honest side must declare. Mirrors
# scene_survey_contracts.SUBJECT_RESOLVERS, which is ("caller",); the contracts
# module dogfood asserts the two still agree.
CALLER_RESOLVER = "caller"
# The ONLY anchor mode whose subject coordinates are independently observable.
# Mirrors a member of scene_survey_contracts.ANCHOR_MODES (same dogfood check).
OBSERVABLE_ANCHOR_MODE = "actor_object_path"

# Component verdicts, in PRECEDENCE order. The first False component names the
# ineligibility reason, so this order is load-bearing: anchor-mode observability is
# checked first because when it fails the remaining components are not merely
# false, they are unaskable.
ACCEPTANCE_COMPONENTS = (
    "anchor_mode_observable",
    "observed_world_identity_valid",
    "observed_actor_identity_valid",
    "observed_actor_transform_valid",
    "survey_bound_to_observed_actor",
)

REASON_ANCHOR_NOT_OBSERVABLE = "independent_subject_anchor_not_observable"
REASON_WORLD_IDENTITY_UNVERIFIED = "observed_world_identity_unverified"
REASON_ACTOR_IDENTITY_UNVERIFIED = "observed_actor_identity_unverified"
REASON_ACTOR_TRANSFORM_UNOBSERVED = "observed_actor_transform_unobserved"
REASON_SURVEY_NOT_BOUND = "survey_not_bound_to_observed_actor"

# component -> the reason emitted when that component is the first to fail.
ACCEPTANCE_COMPONENT_REASON = (
    ("anchor_mode_observable", REASON_ANCHOR_NOT_OBSERVABLE),
    ("observed_world_identity_valid", REASON_WORLD_IDENTITY_UNVERIFIED),
    ("observed_actor_identity_valid", REASON_ACTOR_IDENTITY_UNVERIFIED),
    ("observed_actor_transform_valid", REASON_ACTOR_TRANSFORM_UNOBSERVED),
    ("survey_bound_to_observed_actor", REASON_SURVEY_NOT_BOUND),
)
# The closed enum of legal ineligibility reasons. A reason outside this set is a
# rejected report, not a free-text excuse.
ACCEPTANCE_INELIGIBILITY_REASONS = tuple(r for _c, r in ACCEPTANCE_COMPONENT_REASON)


def acceptance_raw(subject, report):
    """Project a (subject, report) pair into the raw bundle the derivation reads.

    THREE records, deliberately classified apart, because collapsing them is the
    lie this whole module exists to prevent:

      * ``requested`` — CALLER_SUPPLIED. The request vector. States intent; proves
        nothing about execution.
      * ``observed``  — OBSERVED when the report claims a completed run, otherwise
        an honest ``failed`` record. These are the far side's measurements
        (``scene_survey_far_side`` sets observed_world_package /
        observed_anchor_location / observed_anchor_object_path from the live
        editor), i.e. the only channel that can DISAGREE with the request.
      * ``echoed``    — CALLER_SUPPLIED on both sides. subject_id and resolved_by
        are caller vocabulary; WorldForge has no channel that could observe either
        (``run_scene_survey_probe`` says so explicitly). They give
        CONTINUITY — this report belongs to this request — and never evidence that
        the right subject was surveyed.
    """
    s = subject if isinstance(subject, dict) else {}
    r = report if isinstance(report, dict) else {}
    requested = caller_supplied(
        {"anchor_mode": s.get("anchor_mode"),
         "map_asset_path": s.get("map_asset_path"),
         "anchor_object_path": s.get("anchor_object_path")},
        detail="the caller-resolved subject's request vector")
    if r.get("runtime_executed") is True:
        observed = record(
            {"world_package": r.get("map_asset_path"),
             "actor_object_path": r.get("observed_anchor_object_path"),
             "actor_location": r.get("observed_anchor_location"),
             "runtime_executed": True},
            OBSERVED, stage="anchor_bind", collector="scene_survey_far_side",
            collection_ok=True,
            detail="observation vector measured on the far side and echoed by the "
                   "report")
    else:
        observed = failed(
            "the report does not claim a completed runtime run "
            "(runtime_executed={!r}) — there is no observation vector to be "
            "identifiable from".format(r.get("runtime_executed")),
            stage="anchor_bind", collector="scene_survey_far_side")
    echoed = caller_supplied(
        {"subject_id_request": s.get("subject_id"),
         "subject_id_report": r.get("subject_id"),
         "resolved_by_request": s.get("resolved_by"),
         "resolved_by_report": r.get("subject_resolved_by")},
        detail="caller vocabulary echoed by both sides — continuity, never evidence")
    return {"binding": {"requested": requested, "observed": observed,
                        "echoed": echoed}}


def sufficiency_acceptance_eligibility(raw):
    """Eligibility needs all three binding records; a missing one is not a False.

    Note what is NOT a sufficiency failure: an ``observed`` record that honestly
    reports a failed collection IS sufficient — it answers the question (nothing
    was observed, therefore nothing is identifiable, therefore ineligible). Only a
    malformed bundle, which cannot answer the question at all, is insufficient.
    """
    b = (raw or {}).get("binding", {})
    missing = [k for k in ("requested", "observed", "echoed")
               if not isinstance(b.get(k), dict)]
    if missing:
        return False, ("acceptance eligibility needs the binding records {} — build "
                       "the bundle with acceptance_raw(subject, report)".format(missing))
    return True, "binding records present (observed classification={!r})".format(
        b["observed"].get("classification"))


def derive_acceptance_eligibility(raw):
    """Return (eligible, inputs) — the five-component identifiability verdict.

    Every component is a comparison between an INDEPENDENTLY OBSERVED value and the
    request, except the last, which is stated honestly for what it is (see the
    ``echoed`` note in ``acceptance_raw``). Under explicit_transform component 1
    fails and the verdict is ineligible no matter how clean the rest of the survey
    is — that is the locked invariant, and it is expressed here as ordinary
    conjunction rather than as a special case, so there is no branch to forget.
    """
    b = (raw or {}).get("binding", {})
    req = (b.get("requested") or {}).get("value") or {}
    obs = (b.get("observed") or {}).get("value") or {}
    ech = (b.get("echoed") or {}).get("value") or {}

    want_map = req.get("map_asset_path")
    got_map = obs.get("world_package")
    want_path = req.get("anchor_object_path")
    got_path = obs.get("actor_object_path")
    sid_req, sid_rep = ech.get("subject_id_request"), ech.get("subject_id_report")

    comp = {
        # 1. is the subject's anchor observable AT ALL under this mode?
        "anchor_mode_observable": req.get("anchor_mode") == OBSERVABLE_ANCHOR_MODE,
        # 2. did the editor open the world the caller named? (measured, not copied)
        "observed_world_identity_valid": (
            isinstance(got_map, str) and bool(got_map.strip())
            and isinstance(want_map, str) and got_map == want_map),
        # 3. did it resolve the exact actor the caller named? (measured)
        "observed_actor_identity_valid": (
            isinstance(got_path, str) and bool(got_path.strip())
            and isinstance(want_path, str) and got_path == want_path),
        # 4. did it report a real transform for that actor? Under this mode the
        #    caller supplied none, so a finite vector here can only have been read
        #    off the resolved actor.
        "observed_actor_transform_valid": _finite3(obs.get("actor_location")),
        # 5. did a run actually happen, and is this report continuous with THIS
        #    request? Weakest of the five and honestly so: continuity over caller
        #    vocabulary proves the report belongs to the request, not that each
        #    spatial sample was taken relative to the observed actor. No per-sample
        #    anchor provenance exists in the report contract to check that with.
        "survey_bound_to_observed_actor": (
            obs.get("runtime_executed") is True
            and isinstance(sid_req, str) and bool(sid_req.strip())
            and sid_req == sid_rep
            and ech.get("resolved_by_request") == CALLER_RESOLVER
            and ech.get("resolved_by_report") == CALLER_RESOLVER),
    }
    failed_components = [c for c in ACCEPTANCE_COMPONENTS if not comp[c]]
    reason = None
    for name, why in ACCEPTANCE_COMPONENT_REASON:
        if not comp[name]:
            reason = why
            break
    eligible = not failed_components
    return eligible, {"components": comp,
                      "failed_components": failed_components,
                      "reason": reason,
                      "anchor_mode": req.get("anchor_mode"),
                      "observed_classification":
                          (b.get("observed") or {}).get("classification")}


DERIVATIONS = {
    "acceptance_eligible": (derive_acceptance_eligibility,
                            sufficiency_acceptance_eligibility),
    "actor_bounds_valid": (derive_actor_bounds_valid, sufficiency_actor_bounds),
    "temporary_placements_requested": (derive_placements_requested, sufficiency_markers),
    "temporary_placements_accepted": (derive_placements_accepted,
                                      sufficiency_marker_accepted),
    "temporary_placements_grounded": (derive_placements_grounded,
                                      _predicate_derivation(PRED_GROUND_CONTACT)[1]),
    "overlap_count": (derive_overlap_count,
                      _predicate_derivation(PRED_OVERLAP_FREE)[1]),
    "player_clearance_valid": (derive_player_clearance_valid,
                               sufficiency_player_clearance),
    "cleanup_verified": (derive_cleanup_verified, sufficiency_cleanup),
    "grounding_valid": (derive_grounding_valid, sufficiency_grounding),
}

# One registered derivation per measured predicate, so every triple in
# `predicate_triples` also has a re-derivable, forgery-checkable claim behind it.
for _pname in PREDICATE_NAMES:
    DERIVATIONS.setdefault(_pname + "_valid", _predicate_derivation(_pname))
del _pname


def derive(field, raw):
    """Run one named derivation. Returns (ok_sufficient, value, inputs, detail).

    Three gates, in order, and each one can only ever REFUSE:

      1. the field is registered;
      2. the bundle is internally consistent — refs resolve, ids are unique, no
         cross-operation reference, no contradictory atoms, no NaN/Infinity in
         numeric evidence. A bundle that argues with itself is not answered from
         at ALL, because a confident answer computed from a self-contradictory
         bundle is worse than no answer: it looks like evidence;
      3. the raw is sufficient for this particular claim.

    `ok_sufficient=False` is the module's `unknown`. It never becomes a False.
    """
    if field not in DERIVATIONS:
        return False, None, None, "no derivation registered for {!r}".format(field)
    intact, why = bundle_integrity(raw)
    if not intact:
        return False, None, None, ("raw bundle failed integrity, so no claim about "
                                   "{} may be derived from it: {}".format(field, why))
    fn, suff = DERIVATIONS[field]
    enough, detail = suff(raw)
    if not enough:
        return False, None, None, detail
    value, inputs = fn(raw)
    return True, value, inputs, detail


def derived_record(field, raw, stage, collector, world=None, refs=()):
    """Derive a field and wrap it, or return an honest `failed` record."""
    enough, value, inputs, detail = derive(field, raw)
    if not enough:
        return failed(detail, stage=stage, collector=collector)
    return record(value, DERIVED, stage=stage, collector=collector, world=world,
                  raw_refs=list(refs), collection_ok=True, derivation=field,
                  inputs=inputs, detail=detail)


def rederive_and_compare(field, claimed, raw):
    """The validator's rail: re-derive independently and compare.

    Returns (ok, detail). This never reads a success flag from the claim; it
    consumes only `raw` and the claimed VALUE.
    """
    if not isinstance(claimed, dict):
        return False, "claim is not an evidence record"
    enough, value, _inputs, detail = derive(field, raw)
    if not enough:
        return False, ("raw evidence is insufficient to support any claim about "
                       "{}: {}".format(field, detail))
    if claimed.get("value") != value:
        return False, ("claimed {!r} but the raw evidence re-derives to {!r} — the "
                       "report does not follow from its own evidence".format(
                           claimed.get("value"), value))
    return True, "re-derived {!r} from raw and it matches ({})".format(value, detail)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _finite3(v):
    """A finite 3-vector. Tuples are accepted; bools and NaN/Inf are not."""
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return False
    return all(is_finite_number(x) for x in v)


def _has_extent(a):
    return isinstance(a, dict) and _finite3(a.get("bounds_extent"))


if __name__ == "__main__":
    ok = True

    def _t(label, cond, detail=""):
        global ok
        if not cond:
            print("FAIL {}: {}".format(label, detail))
            ok = False

    # A tautology must not survive: a marker observed overlapping makes the
    # clearance claim False. Under the old predicate this was unreachable.
    raw = {"marker": {"m0": {"grounded": True, "accepted": False,
                             "overlap": True, "capsule_clear": False}}}
    val, _ = derive_player_clearance_valid(raw)
    _t("clearance_falsifiable", val is False, "observed overlap must yield False")

    # Empty inputs must be INSUFFICIENT, not a confident True.
    enough, _v, _i, d = derive("player_clearance_valid", {"marker": {}})
    _t("empty_markers_insufficient", not enough, d)

    # grounded must not equal accepted.
    raw = {"marker": {"a": {"grounded": True, "accepted": False},
                      "b": {"grounded": True, "accepted": True}}}
    g, _ = derive_placements_grounded(raw)
    a, _ = derive_placements_accepted(raw)
    _t("grounded_differs_from_accepted", g == 2 and a == 1,
        "grounded={} accepted={}".format(g, a))

    # A count cannot satisfy bounds.
    enough, _v, _i, d = derive("actor_bounds_valid", {"actor": {}})
    _t("count_cannot_prove_bounds", not enough, d)
    enough, v, _i, _d = derive("actor_bounds_valid",
                               {"actor": {"a": {"bounds_extent": [1.0, 2.0, 3.0]}}})
    _t("real_bounds_accepted", enough and v is True)
    enough, v, _i, _d = derive("actor_bounds_valid",
                               {"actor": {"a": {"bounds_extent": [0.0, 0.0, 0.0]}}})
    _t("degenerate_bounds_rejected", enough and v is False)

    # Cleanup needs both inventories, in the right order.
    enough, _v, _i, d = derive("cleanup_verified", {"inventory": {}})
    _t("cleanup_needs_inventories", not enough, d)

    def _snap(stage, **over):
        s = {"stage": stage, "collection_ok": True, "actor_paths": ["/A"],
             "dirty_packages": [], "operation_owned_actor_paths": [],
             "map_identity": "/Game/Maps/M", "package_identity": "/Game/Maps/M"}
        s.update(over)
        return s

    # ---- the ledger, without which no cleanup claim is answerable at all ---- #
    _OP = "op-A"

    def _ledger(**over):
        led = {"record_id": LEDGER_REF, "record_type": LEDGER_KIND,
               "record_ident": LEDGER_IDENT, "operation_id": _OP,
               "is_temporary_object_ledger": True, "collection_ok": True,
               "ownership_tag": "worldforge.scene_survey/" + _OP,
               "cleanup_ran": True,
               "object_ids": [], "object_count": 0,
               "created_object_ids": [], "created_object_count": 0,
               "spawn_call_sites_in_module": 1, "spawn_call_sites_in_ledger": 1,
               "unledgered_spawn_call_sites": 0,
               "persistent_package_hash": None,
               "persistent_package_hash_supported": False}
        led.update(over)
        return led

    def _placed(oid, **over):
        """One CLEANLY handled owned object: created, destroyed, witnessed gone."""
        p = {"record_id": "temporary_placement#" + oid,
             "record_type": "temporary_placement", "record_ident": oid,
             "operation_id": _OP, "object_id": oid,
             "ownership_tag": "worldforge.scene_survey/" + _OP,
             "creation_observed": True, "creation_stage": "observe",
             "destruction_attempted": True,
             "destruction_result": DESTRUCTION_DESTROYED,
             "post_cleanup_presence": PRESENCE_ABSENT,
             "absent_after_cleanup": True, "collection_ok": True}
        p.update(over)
        return p

    def _cb(pre=None, post=None, ledger=None, placements=None):
        """A cleanup bundle whose ledger SUMMARISES its own placements.

        The aggregate fields are computed here from the placements the fixture was
        given, exactly as `_SpawnLedger.write_manifest` computes them from the
        records it filed. They used to be hand-written, and every fixture below that
        declared an object inherited `object_count: 0` and `created_object_ids: []`
        beside it — a manifest no producer can emit, and one `_ledger_contradictions`
        now rejects outright. Fixtures that lie about their own producer prove
        nothing about a consumer.

        An explicit override still wins, which is how the lying-summary rails below
        build their mutants.
        """
        over = dict(ledger or {})
        places = dict(placements or {})
        led = _ledger(**over)
        ids = ledger_declared_ids(led) or []
        if "object_count" not in over:
            led["object_count"] = len(set(ids))
        if "created_object_ids" not in over:
            led["created_object_ids"] = sorted(
                i for i in set(ids)
                if isinstance(places.get(i), dict)
                and places[i].get("creation_observed") is True)
        if "created_object_count" not in over:
            led["created_object_count"] = len(set(led["created_object_ids"]))
        return {"inventory": {"pre": _snap("observe", **(pre or {})),
                              "post": _snap("cleanup", **(post or {}))},
                LEDGER_KIND: {LEDGER_IDENT: led},
                "temporary_placement": places}

    inv = _cb()
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_clean_state", enough and v is True, (enough, v, _d))
    inv["inventory"]["post"]["actor_paths"] = ["/A", "/LEAKED"]
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_detects_leak", enough and v is False)
    inv["inventory"]["post"]["actor_paths"] = ["/A"]
    inv["inventory"]["post"]["dirty_packages"] = ["/Game/Maps/M"]
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_detects_dirty", enough and v is False)

    # D_f = D_i is EQUALITY: a package that STOPS being dirty was saved to disk,
    # which the old containment rule (post - pre) could not see at all.
    _inv = _cb(pre={"dirty_packages": ["/Game/Maps/M"]}, post={"dirty_packages": []})
    enough, v, i, _d = derive("cleanup_verified", _inv)
    _t("cleanup_detects_package_saved",
       enough and v is False and i["no_longer_dirty_packages"] == ["/Game/Maps/M"],
       (enough, v))
    # T_f = T_i — a temporary object still owned after cleanup is a leak.
    _inv = _cb(post={"operation_owned_actor_paths": ["/Temp_0"]})
    enough, v, i, _d = derive("cleanup_verified", _inv)
    _t("cleanup_detects_temporary_leak",
       enough and v is False and i["temporary_objects_leaked"] == ["/Temp_0"],
       (enough, v))
    # T absent is UNKNOWN, never the empty set — this is the exact door a
    # hard-coded cleanup_verified=True walks back in through.
    _inv = _cb()
    del _inv["inventory"]["post"]["operation_owned_actor_paths"]
    enough, _v, _i, d = derive("cleanup_verified", _inv)
    _t("cleanup_absent_owned_set_is_unknown", not enough, d)
    # M_f = M_i — the map identity must be the same world on both sides.
    _inv = _cb(post={"map_identity": "/Game/Maps/OTHER",
                     "package_identity": "/Game/Maps/OTHER"})
    enough, v, i, _d = derive("cleanup_verified", _inv)
    _t("cleanup_detects_map_identity_drift",
       enough and v is False and i["map_identity_equal"] is False, (enough, v))
    _inv = _cb(pre={"map_identity": None})
    enough, _v, _i, d = derive("cleanup_verified", _inv)
    _t("cleanup_absent_map_identity_is_unknown", not enough, d)

    # A post inventory taken BEFORE cleanup cannot witness cleanup.
    inv["inventory"]["post"] = _snap("observe")
    enough, _v, _i, d = derive("cleanup_verified", inv)
    _t("cleanup_rejects_stage_inversion", not enough, d)

    # ---- THE LEDGER RAILS -------------------------------------------------- #
    # MUTANT 1 — no ledger at all. Two clean inventories, nothing else. The old
    # rule answered True here, which is the entire defect: an object created and
    # destroyed between the snapshots is absent from both.
    _m1 = _cb()
    del _m1[LEDGER_KIND][LEDGER_IDENT]
    enough, v, _i, d = derive("cleanup_verified", _m1)
    _t("ledger_absent_is_unknown_not_success",
       (not enough) and v is None and "no temporary-object ledger" in d, (enough, v, d))
    # ...and the same bundle WITH a ledger is answerable, so the refusal above is
    # attributable to the ledger and not to some other hole in the fixture.
    enough, v, _i, _d = derive("cleanup_verified", _cb())
    _t("ledger_present_makes_it_answerable", enough and v is True, (enough, v))
    # A ledger that never reached cleanup is also unknown: the post inventory then
    # describes a world cleanup was never run on.
    enough, v, _i, d = derive("cleanup_verified", _cb(ledger={"cleanup_ran": False}))
    _t("ledger_cleanup_not_run_is_unknown", (not enough) and v is None, (enough, v, d))
    # An unmeasured object_ids list must not be read as the empty set.
    enough, v, _i, d = derive("cleanup_verified", _cb(ledger={"object_ids": None}))
    _t("ledger_unmeasured_object_ids_is_unknown", not enough, d)
    # A second spawn path in the module means O_created can be incomplete.
    enough, v, _i, d = derive("cleanup_verified",
                              _cb(ledger={"unledgered_spawn_call_sites": 1}))
    _t("ledger_stray_spawn_path_is_unknown", not enough, d)

    # MUTANT 2 — created and destroyed BETWEEN the snapshots, so both inventories
    # agree exactly; destruction_result forged to success; the independent
    # re-observation still says the object is there.
    _m2 = _cb(placements={"t0": _placed("t0",
                                        post_cleanup_presence=PRESENCE_PRESENT,
                                        absent_after_cleanup=False)},
              ledger={"object_ids": ["t0"], "object_count": 1,
                      "created_object_ids": ["t0"], "created_object_count": 1})
    enough, v, i, d = derive("cleanup_verified", _m2)
    _t("ledger_catches_survivor_invisible_to_inventories",
       enough and v is False
       and i["ledger_objects_present_after_cleanup"] == ["t0"]
       and i["temporary_objects_equal"] is True
       and i["dirty_packages_equal"] is True
       and i["map_identity_equal"] is True,
       (enough, v, d))
    # The honest version of the same object passes, so the rail above is the
    # presence field doing the work rather than the fixture being broken.
    _ok2 = _cb(placements={"t0": _placed("t0")},
               ledger={"object_ids": ["t0"], "object_count": 1,
                       "created_object_ids": ["t0"], "created_object_count": 1})
    enough, v, _i, d = derive("cleanup_verified", _ok2)
    _t("ledger_clean_object_passes", enough and v is True, (enough, v, d))
    # ...and a destroy that never succeeded fails even with the object gone, because
    # the conjunct is destroyed(x) AND NOT present(x), not either one alone.
    _m2b = _cb(placements={"t0": _placed(
        "t0", destruction_result=DESTRUCTION_RETURNED_FALSE)},
        ledger={"object_ids": ["t0"], "object_count": 1})
    enough, v, i, _d = derive("cleanup_verified", _m2b)
    _t("ledger_requires_destroy_and_absence",
       enough and v is False and i["ledger_objects_not_destroyed"] == ["t0"],
       (enough, v))
    # An UNWITNESSED final state is unknown, never clean.
    _m2c = _cb(placements={"t0": _placed(
        "t0", post_cleanup_presence=PRESENCE_UNKNOWN, absent_after_cleanup=None)},
        ledger={"object_ids": ["t0"], "object_count": 1})
    enough, _v, _i, d = derive("cleanup_verified", _m2c)
    _t("ledger_unwitnessed_removal_is_unknown", not enough, d)
    # A placement the ledger does not list makes the quantifier vacuous.
    _m2d = _cb(placements={"t0": _placed("t0")})
    enough, v, i, _d = derive("cleanup_verified", _m2d)
    _t("ledger_unlisted_placement_is_false",
       enough and v is False and i["ledger_unledgered_placements"] == ["t0"],
       (enough, v))

    # MUTANT 3 — a package dirtied. D_1 != D_0.
    _m3 = _cb(post={"dirty_packages": ["/Game/Maps/M"]})
    enough, v, i, _d = derive("cleanup_verified", _m3)
    _t("ledger_bundle_still_detects_dirty_package",
       enough and v is False and i["dirty_packages_equal"] is False
       and i["newly_dirty_packages"] == ["/Game/Maps/M"], (enough, v))

    # MUTANT 4 — a placement record belonging to a DIFFERENT operation.
    # Not listed by the ledger, which is the realistic shape of contamination: the
    # record is both foreign and unledgered, and either one alone decides False.
    _m4 = _cb(placements={"t9": _placed("t9", operation_id="op-B",
                                        ownership_tag="worldforge.scene_survey/op-B")})
    enough, v, i, _d = derive("cleanup_verified", _m4)
    _t("ledger_foreign_operation_placement_is_false",
       enough and v is False
       and i["ledger_foreign_operation_placements"] == ["t9"]
       and i["ledger_misattributed_placements"] == ["t9"], (enough, v, i))
    # ...and when the ledger DOES claim the foreign record, the bundle is
    # cross-operation and reference integrity rejects it before any claim is
    # derived. Still never a success — refused one gate earlier.
    _m4b = _cb(placements={"t9": _placed("t9", operation_id="op-B")},
               ledger={"object_ids": ["t9"], "object_count": 1,
                       "temporary_object_refs": ["temporary_placement#t9"]})
    enough, v, _i, d = derive("cleanup_verified", _m4b)
    _t("ledger_claimed_foreign_record_fails_integrity",
       (not enough) and v is None and "operation" in d, (enough, v, d))

    # A forged summary over an honest atom is a CONTRADICTION, not a pass: the
    # bundle is rejected outright rather than answered from.
    _forge = _cb(placements={"t0": _placed("t0", absent_after_cleanup=False)},
                 ledger={"object_ids": ["t0"], "object_count": 1})
    enough, _v, _i, d = derive("cleanup_verified", _forge)
    _t("ledger_presence_cannot_contradict_its_own_atom",
       (not enough) and "contradicts absent_after_cleanup" in d, d)
    # A presence value outside the closed vocabulary is rejected, never ignored.
    _oov = _cb(placements={"t0": _placed("t0", post_cleanup_presence="cleaned")},
               ledger={"object_ids": ["t0"], "object_count": 1})
    enough, _v, _i, d = derive("cleanup_verified", _oov)
    _t("ledger_presence_vocabulary_is_closed", not enough, d)

    # An UNDECIDED creation_observed gates the whole per-object conjunct, so it must
    # refuse rather than skip. Skipping reads "we do not know whether this operation
    # created the object" as "it created nothing", and a forger who blanks that one
    # field drops the object — and its fate — out of `for every x in O_created`.
    _m2e = _cb(placements={"t0": _placed(
        "t0", creation_observed=None, destruction_attempted=False,
        destruction_result=DESTRUCTION_NOT_ATTEMPTED,
        post_cleanup_presence=PRESENCE_UNKNOWN, absent_after_cleanup=None)},
        ledger={"object_ids": ["t0"]})
    enough, _v, _i, d = derive("cleanup_verified", _m2e)
    _t("ledger_undecided_creation_is_unknown",
       (not enough) and "creation_observed" in d, d)
    # ...but a WITNESSED survivor still decides the record False. Within a record
    # false dominates unknown, so blanking the creation atom must not erase a
    # measured leak — that direction would be the fake green.
    _m2f = _cb(placements={"t0": _placed(
        "t0", creation_observed=None,
        destruction_result=DESTRUCTION_RETURNED_FALSE,
        post_cleanup_presence=PRESENCE_PRESENT, absent_after_cleanup=False)},
        ledger={"object_ids": ["t0"]})
    enough, v, i, _d = derive("cleanup_verified", _m2f)
    _t("ledger_undecided_creation_cannot_hide_a_survivor",
       enough and v is False
       and i["ledger_objects_present_after_cleanup"] == ["t0"]
       and i["ledger_objects_creation_undecided"] == ["t0"], (enough, v))

    # The ledger's AGGREGATES against the atoms they summarise. Nothing derives from
    # them — O_created is recomputed from `creation_observed` — which is exactly why
    # a lying one must be rejected rather than ignored: a manifest whose counts
    # disagree with its own enumeration was written by something other than the
    # ledger that produced the atoms.
    _agg = _cb(placements={"t0": _placed("t0")},
               ledger={"object_ids": ["t0"], "object_count": 7})
    enough, _v, _i, d = derive("cleanup_verified", _agg)
    _t("ledger_object_count_must_summarise_object_ids",
       (not enough) and "object_count=7" in d, d)
    _agg2 = _cb(placements={"t0": _placed("t0")},
                ledger={"object_ids": ["t0"], "created_object_ids": [],
                        "created_object_count": 0})
    enough, _v, _i, d = derive("cleanup_verified", _agg2)
    _t("ledger_created_summary_must_match_the_atoms",
       (not enough) and "creation_observed atoms" in d, d)
    _dup = _cb(placements={"t0": _placed("t0")},
               ledger={"object_ids": ["t0", "t0"]})
    enough, _v, _i, d = derive("cleanup_verified", _dup)
    _t("ledger_duplicate_object_id_is_unknown",
       (not enough) and "more than once" in d, d)

    # A placement claiming a world the snapshots never witnessed is a contaminant of
    # the same family as a foreign operation_id: it makes the quantifier lie.
    _fw = _cb(placements={"t0": _placed("t0", world_identity="/Game/Maps/Other",
                                        package_identity="/Game/Maps/Other")},
              ledger={"object_ids": ["t0"], "package_identity": "/Game/Maps/M"})
    enough, v, i, _d = derive("cleanup_verified", _fw)
    _t("ledger_foreign_world_placement_is_false",
       enough and v is False and i["ledger_foreign_world_placements"] == ["t0"],
       (enough, v))

    # P's CONTENT half is read from the snapshots, never asserted. A hardcoded
    # `supported=False` cannot be made to disagree by any input, so the day the far
    # side grows a hash api is the day a mutated package starts deriving clean.
    def _hashed(pre_h, post_h):
        return _cb(pre={"persistent_package_hash": pre_h,
                        "persistent_package_hash_supported": True},
                   post={"persistent_package_hash": post_h,
                         "persistent_package_hash_supported": True})
    _h_ok, _h_in = derive_cleanup_verified(_hashed("h:a", "h:b"))
    _t("persistent_package_hash_change_is_false",
       _h_ok is False and _h_in["persistent_package_hash_supported"] is True
       and _h_in["persistent_package_hash_equal"] is False, _h_in)
    _h_ok, _h_in = derive_cleanup_verified(_hashed("h:a", "h:a"))
    _t("persistent_package_hash_match_does_not_block",
       _h_ok is True and _h_in["persistent_package_hash_equal"] is True, _h_in)
    _h_ok, _h_in = derive_cleanup_verified(_hashed("h:a", None))
    _t("persistent_package_hash_half_read_is_unsupported",
       _h_ok is True and _h_in["persistent_package_hash_supported"] is False
       and _h_in["persistent_package_hash_equal"] is None, _h_in)

    # P: the content half is UNSUPPORTED and must not be folded into the AND.
    _p_ok, _p_inputs = derive_cleanup_verified(_cb())
    _t("persistent_package_hash_is_unsupported_not_agreed",
       _p_ok is True
       and _p_inputs["persistent_package_hash_supported"] is False
       and _p_inputs["persistent_package_hash_equal"] is None
       and _p_inputs["persistent_package_identity_equal"] is True, _p_inputs)

    # The per-object predicate is wired and can decide in both directions.
    _t("temporary_cleanup_predicate_registered",
       "temporary_cleanup_valid" in DERIVATIONS
       and "package_cleanliness_valid" in DERIVATIONS)
    enough, v, _i, d = derive("temporary_cleanup_valid",
                              _cb(placements={"t0": _placed("t0")},
                                  ledger={"object_ids": ["t0"]}))
    _t("temporary_cleanup_valid_true_on_clean_object", enough and v is True,
       (enough, v, d))
    enough, v, _i, d = derive("temporary_cleanup_valid",
                              _cb(placements={"t0": _placed(
                                  "t0", post_cleanup_presence=PRESENCE_PRESENT,
                                  absent_after_cleanup=False)},
                                  ledger={"object_ids": ["t0"]}))
    _t("temporary_cleanup_valid_false_on_survivor", enough and v is False,
       (enough, v, d))
    enough, _v, _i, d = derive("temporary_cleanup_valid", _cb())
    _t("temporary_cleanup_valid_empty_population_is_unknown", not enough, d)
    # A refused spawn is a MEASUREMENT that nothing was created — not a hole.
    enough, v, _i, d = derive("temporary_cleanup_valid",
                              _cb(placements={"t0": _placed(
                                  "t0", creation_observed=False,
                                  destruction_attempted=False,
                                  destruction_result=DESTRUCTION_NOT_ATTEMPTED,
                                  post_cleanup_presence=PRESENCE_NEVER_CREATED,
                                  absent_after_cleanup=None)},
                                  ledger={"object_ids": ["t0"]}))
    _t("never_created_object_is_clean", enough and v is True, (enough, v, d))

    # Re-derivation must catch a forged claim.
    good = {"marker": {"m0": {"grounded": True, "accepted": True,
                              "overlap": False, "capsule_clear": True}}}
    forged = record(False, DERIVED, stage="classify", collector="x",
                    raw_refs=["marker#m0"], collection_ok=True,
                    derivation="player_clearance_valid")
    r_ok, d = rederive_and_compare("player_clearance_valid", forged, good)
    _t("rederivation_catches_forgery", not r_ok, d)

    # A derived record with no raw_refs must be rejected.
    bad = record(True, DERIVED, stage="classify", collector="x",
                 collection_ok=True, derivation="cleanup_verified")
    fails = [c for c in validate_record(bad, "cleanup_verified", strict=True) if not c[1]]
    _t("derived_needs_raw_refs",
       any("derived_has_raw_refs" in c[0] for c in fails), [c[0] for c in fails])

    # unsupported must not carry a usable value.
    bad = record(False, UNSUPPORTED, stage="observe", collector="x",
                 collection_ok=False, detail="no RHI")
    fails = [c for c in validate_record(bad, "camera_capture_ok", strict=True) if not c[1]]
    _t("unsupported_value_must_be_null",
       any("non_satisfying_value_is_null" in c[0] for c in fails), [c[0] for c in fails])

    # caller_supplied can never satisfy a rail.
    _t("caller_supplied_cannot_satisfy",
       not satisfies_rail(caller_supplied("/Game/Maps/M")))
    _t("unsupported_cannot_satisfy", not satisfies_rail(unsupported("no RHI")))
    _t("observed_can_satisfy",
       satisfies_rail(record(3, OBSERVED, stage="observe", collector="c",
                             collection_ok=True)))

    # --- acceptance eligibility ------------------------------------------- #
    # Vocabulary is closed and self-consistent.
    _t("acceptance_reason_enum_closed",
       len(ACCEPTANCE_INELIGIBILITY_REASONS) == len(ACCEPTANCE_COMPONENTS)
       and all(isinstance(r, str) and r.strip()
               for r in ACCEPTANCE_INELIGIBILITY_REASONS)
       and len(set(ACCEPTANCE_INELIGIBILITY_REASONS))
       == len(ACCEPTANCE_INELIGIBILITY_REASONS),
       ACCEPTANCE_INELIGIBILITY_REASONS)
    _t("acceptance_component_reason_covers_components",
       tuple(c for c, _r in ACCEPTANCE_COMPONENT_REASON) == ACCEPTANCE_COMPONENTS)

    _MAP = "/Game/Fixture/Lvl_Fixture"
    _PATH = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.Fixture_Subject_0"

    def _pair(anchor_mode=OBSERVABLE_ANCHOR_MODE, **over):
        subject = {"subject_id": "s0", "map_asset_path": _MAP,
                   "anchor_mode": anchor_mode, "resolved_by": CALLER_RESOLVER,
                   "anchor_object_path": _PATH if anchor_mode == OBSERVABLE_ANCHOR_MODE
                   else None,
                   "anchor_location": None if anchor_mode == OBSERVABLE_ANCHOR_MODE
                   else [1.0, 2.0, 3.0]}
        report = {"subject_id": "s0", "map_asset_path": _MAP,
                  "subject_resolved_by": CALLER_RESOLVER, "runtime_executed": True,
                  "observed_anchor_object_path":
                      _PATH if anchor_mode == OBSERVABLE_ANCHOR_MODE else None,
                  "observed_anchor_location": [1.0, 2.0, 3.0]}
        subject.update(over.pop("subject", {}))
        report.update(over.pop("report", {}))
        return acceptance_raw(subject, report)

    # POSITIVE: a fully observable actor_object_path pair is eligible, no reason.
    enough, v, inp, _d = derive("acceptance_eligible", _pair())
    _t("acceptance_positive", enough and v is True and inp["reason"] is None,
       (enough, v, inp))
    # NEGATIVE, the locked rule: explicit_transform is NEVER eligible, and its
    # reason is the identifiability one — even though every other component holds.
    enough, v, inp, _d = derive("acceptance_eligible", _pair("explicit_transform"))
    _t("acceptance_explicit_transform_never_eligible",
       enough and v is False and inp["reason"] == REASON_ANCHOR_NOT_OBSERVABLE,
       (enough, v, inp))
    # NEGATIVE, one per remaining component — each must be able to fire alone.
    for _label, _over, _want in (
            ("world", {"report": {"map_asset_path": "/Game/Fixture/Lvl_Other"}},
             REASON_WORLD_IDENTITY_UNVERIFIED),
            ("world_unobserved", {"report": {"map_asset_path": ""}},
             REASON_WORLD_IDENTITY_UNVERIFIED),
            ("actor", {"report": {"observed_anchor_object_path": _PATH + "_OTHER"}},
             REASON_ACTOR_IDENTITY_UNVERIFIED),
            ("actor_absent", {"report": {"observed_anchor_object_path": None}},
             REASON_ACTOR_IDENTITY_UNVERIFIED),
            ("transform", {"report": {"observed_anchor_location": None}},
             REASON_ACTOR_TRANSFORM_UNOBSERVED),
            ("transform_short", {"report": {"observed_anchor_location": [1.0, 2.0]}},
             REASON_ACTOR_TRANSFORM_UNOBSERVED),
            ("subject_drift", {"report": {"subject_id": "s1"}},
             REASON_SURVEY_NOT_BOUND),
            ("self_resolved", {"report": {"subject_resolved_by": "worldforge"}},
             REASON_SURVEY_NOT_BOUND)):
        enough, v, inp, _d = derive("acceptance_eligible", _pair(**_over))
        _t("acceptance_negative_" + _label,
           enough and v is False and inp["reason"] == _want, (enough, v, inp))
    # A report that never ran observed nothing: the observed record is `failed`,
    # not a False, and the verdict is ineligible rather than insufficient.
    _raw = _pair(report={"runtime_executed": False})
    _t("acceptance_unexecuted_observation_is_failed",
       _raw["binding"]["observed"]["classification"] == FAILED
       and _raw["binding"]["observed"]["value"] is None)
    enough, v, inp, _d = derive("acceptance_eligible", _raw)
    _t("acceptance_unexecuted_ineligible", enough and v is False, (enough, v, inp))
    # The echo channel is never classified as an observation.
    _t("acceptance_echo_is_caller_supplied",
       _pair()["binding"]["echoed"]["classification"] == CALLER_SUPPLIED
       and not satisfies_rail(_pair()["binding"]["echoed"]))
    # A malformed bundle is INSUFFICIENT, never a confident False.
    enough, _v, _i, d = derive("acceptance_eligible", {"binding": {}})
    _t("acceptance_malformed_bundle_insufficient", not enough, d)
    # Re-derivation catches a forged eligibility claim on an ineligible pair.
    _forged = record(True, DERIVED, stage="assemble", collector="assembler",
                     raw_refs=["binding#observed"], collection_ok=True,
                     derivation="acceptance_eligible")
    r_ok, d = rederive_and_compare("acceptance_eligible", _forged,
                                   _pair("explicit_transform"))
    _t("acceptance_rederivation_catches_forgery", not r_ok, d)
    # ...and accepts an honest one, or the rail above is just failing always.
    _honest = record(True, DERIVED, stage="assemble", collector="assembler",
                     raw_refs=["binding#observed"], collection_ok=True,
                     derivation="acceptance_eligible")
    r_ok, d = rederive_and_compare("acceptance_eligible", _honest, _pair())
    _t("acceptance_rederivation_accepts_honest", r_ok, d)
    # The wrapped record is a well-formed DERIVED claim (names its derivation and
    # cites raw), so acceptance eligibility is an evidence record, not a bare bool.
    _rec = derived_record("acceptance_eligible", _pair(), stage="assemble",
                          collector="assembler", refs=["binding#observed",
                                                       "binding#requested"])
    _t("acceptance_record_is_derived",
       _rec["classification"] == DERIVED and _rec["value"] is True
       and _rec["derivation"] == "acceptance_eligible"
       and not [c for c in validate_record(_rec, "acceptance_eligible", strict=True)
                if not c[1]],
       [c[0] for c in validate_record(_rec, "acceptance_eligible", strict=True)
        if not c[1]])

    # --- (1) tri-state sufficiency ---------------------------------------- #
    # THE headline invariant: an all-unknown population aggregates to UNKNOWN.
    # If this ever reads False, every rail downstream is reporting a defect in
    # the world that is actually a defect in the pass.
    _all_unknown = {"marker": {"m0": {}}, "actor": {"a0": {}},
                    "proxy": {"p0": {"value": None, "collection_ok": False}},
                    "inventory": {"pre": {}},
                    "temporary_placement": {"t0": {}}}
    for _p in PREDICATE_NAMES:
        _st = predicate_state(_all_unknown, _p)
        _t("unknown_never_coerced_to_false::" + _p,
           _st["n"] > 0 and _st["valid"] == UNKNOWN and _st["valid"] is not False
           and _st["observed"] is False and _st["unobserved_count"] == _st["n"], _st)
    # ...and every predicate must still be ABLE to be False, or the line above is
    # satisfied by a predicate that simply never decides anything.
    _neg = {
        "marker": {"m0": {"grounded": False, "footprint": False,
                          "capsule_clear": False, "overlap": True,
                          "footprint_trace_hits": [True, False, True, True]}},
        "actor": {"a0": {"bounds_extent": [0.0, 0.0, 0.0]}},
        "proxy": {"p0": {"value": False, "collection_ok": True}},
        "inventory": {"pre": {"collection_ok": True, "actor_paths": [],
                              "dirty_packages": ["/Game/Maps/M"]}},
        # Mutant-2 shaped: the destroy call claims success and the independent
        # re-observation says the object is still there. Exactly one of the two
        # channels is lying, and the predicate must read it as a measured FAILURE.
        "temporary_placement": {"t0": {"creation_observed": True,
                                       "creation_stage": "observe",
                                       "destruction_attempted": True,
                                       "destruction_result": DESTRUCTION_DESTROYED,
                                       "post_cleanup_presence": PRESENCE_PRESENT,
                                       "absent_after_cleanup": False}},
    }
    for _p in PREDICATE_NAMES:
        _st = predicate_state(_neg, _p)
        _t("predicate_can_fail::" + _p,
           _st["valid"] is False and _st["observed"] is True, _st)
    _t("kleene_false_dominates_unknown", tri_and([True, UNKNOWN, False]) is False)
    _t("kleene_unknown_survives", tri_and([True, UNKNOWN]) == UNKNOWN)
    _t("kleene_all_true", tri_and([True, True]) is True)
    _t("is_decided_rejects_truthy_non_bool",
       not is_decided(1) and not is_decided("true") and not is_decided(None))

    # THE named defect: "never measured" and "measured and blocked" used to
    # produce byte-identical output. They must now be distinguishable.
    _never = {"marker": {"m0": {}}}
    _blocked = {"marker": {"m0": {"capsule_clear": False, "overlap": True}}}
    _tri_n = predicate_triple(_never, PRED_CAPSULE_CLEARANCE)
    _tri_b = predicate_triple(_blocked, PRED_CAPSULE_CLEARANCE)
    _t("never_measured_distinguishable_from_blocked",
       _tri_n != _tri_b
       and _tri_n["capsule_clearance_valid"] == UNKNOWN
       and _tri_n["capsule_clearance_observed"] is False
       and _tri_n["capsule_clearance_unobserved_count"] == 1
       and _tri_b["capsule_clearance_valid"] is False
       and _tri_b["capsule_clearance_observed"] is True
       and _tri_b["capsule_clearance_unobserved_count"] == 0, (_tri_n, _tri_b))
    _en, _vn, _in, _dn = derive("player_clearance_valid", _never)
    _eb, _vb, _ib, _db = derive("player_clearance_valid", _blocked)
    _t("never_measured_insufficient_blocked_decided",
       (not _en) and _vn is None and _eb and _vb is False, (_en, _vn, _eb, _vb))
    _t("triples_cover_every_predicate",
       len(predicate_triples(_neg)) == 3 * len(PREDICATE_NAMES)
       and all(p + "_observed" in predicate_triples(_neg)
               and p + "_valid" in predicate_triples(_neg)
               and p + "_unobserved_count" in predicate_triples(_neg)
               for p in PREDICATE_NAMES), sorted(predicate_triples(_neg)))

    # --- (2) bounds -------------------------------------------------------- #
    _t("bounds_minmax_accepted",
       bounds_interval({"bounds_min": [0.0, 0.0, 0.0],
                        "bounds_max": [1.0, 1.0, 1.0]})[0] is True)
    _t("bounds_inverted_rejected",
       bounds_interval({"bounds_min": [5.0, 0.0, 0.0],
                        "bounds_max": [1.0, 1.0, 1.0]})[0] is False)
    _t("bounds_nonfinite_rejected",
       bounds_interval({"bounds_extent": [1.0, float("inf"), 1.0]})[0] is False)
    _t("bounds_missing_is_unknown_not_false",
       bounds_interval({})[0] == UNKNOWN and bounds_interval({})[0] is not False)
    _t("bounds_origin_offset_respected",
       bounds_interval({"bounds_origin": [10.0, 0.0, 0.0],
                        "bounds_extent": [1.0, 1.0, 1.0]})[0] is True)
    # A count still cannot prove bounds — now because n actors with no observed
    # interval is an UNKNOWN population, not because of a special case.
    _t("bounds_not_derived_from_actor_count",
       predicate_state({"actor": {"a": {}, "b": {}, "c": {}}},
                       PRED_ACTOR_BOUNDS)["valid"] == UNKNOWN)
    _e, _v, _i, _d = derive("actor_bounds_valid",
                            {"actor": {"a": {"bounds_extent": [1.0, 2.0, 3.0]},
                                       "b": {}}})
    _t("bounds_partial_population_is_unknown_not_false", (not _e) and _v is None, _d)

    # --- (3) grounding ----------------------------------------------------- #
    def _gm(marker=None, trace=None):
        m = {"grounded": True, "location": [0.0, 0.0, 100.0],
             "ground_impact_z": 100.0,
             "footprint_trace_hits": [True, True, True, True],
             "ground_trace_ref": "trace#m0::ground"}
        m.update(marker or {})
        tr = {"hit": True, "impact_normal": [0.0, 0.0, 1.0]}
        tr.update(trace or {})
        return {"marker": {"m0": m}, "trace": {"m0::ground": tr}}

    _e, _v, _i, _d = derive("grounding_valid", _gm())
    _t("grounding_positive", _e and _v is True, (_e, _v, _d))
    for _label, _over, _comp in (
            ("contact", {"marker": {"grounded": False}}, "contact"),
            ("support_area",
             {"marker": {"footprint_trace_hits": [True, True, True, False]}},
             "support_area"),
            ("ground_dz", {"marker": {"ground_impact_z": 0.0}}, "ground_dz"),
            ("slope", {"trace": {"impact_normal": [1.0, 0.0, 1.0]}}, "slope")):
        _raw_g = _gm(**_over)
        _e, _v, _i, _d = derive("grounding_valid", _raw_g)
        _t("grounding_negative_" + _label,
           _e and _v is False and "m0" in _i["rejected_ids"]
           and _i["per_marker"]["m0"]["components"][_comp] is False,
           (_e, _v, _d))
    # An UNOBSERVED component is unknown, never a rejection. The far side emits no
    # surface normal on the marker, so this is the live production case.
    _raw_g = _gm(trace={"impact_normal": None})
    _e, _v, _i, _d = derive("grounding_valid", _raw_g)
    _t("grounding_missing_normal_is_unknown", (not _e) and _v is None, _d)
    # The SAME predicate driven by the far side's own field vocabulary
    # (`contact`, `ground_delta_z_cm`, `footprint_*_sample_count`,
    # `ground_surface_normal_dot_up`) rather than by the fallbacks. If these names
    # ever stop being read, these four negatives go quiet.
    def _gm_native(**over):
        m = {"contact": True, "ground_delta_z_cm": 0.0,
             "footprint_sample_count": 4, "footprint_supported_sample_count": 4,
             "ground_surface_normal_dot_up": 1.0}
        m.update(over)
        return {"marker": {"m0": m}}

    _e, _v, _i, _d = derive("grounding_valid", _gm_native())
    _t("grounding_native_vocabulary_positive", _e and _v is True, (_e, _v, _d))
    for _label, _over, _comp in (
            ("contact", {"contact": False}, "contact"),
            ("support_area", {"footprint_supported_sample_count": 3},
             "support_area"),
            ("ground_dz", {"ground_delta_z_cm": GROUND_DZ_TOLERANCE_CM + 1.0},
             "ground_dz"),
            ("slope", {"ground_surface_normal_dot_up": GROUND_MAX_SLOPE_COS - 0.01},
             "slope")):
        _e, _v, _i, _d = derive("grounding_valid", _gm_native(**_over))
        _t("grounding_native_negative_" + _label,
           _e and _v is False
           and _i["per_marker"]["m0"]["components"][_comp] is False, (_e, _v, _d))
    _t("support_area_zero_samples_is_unknown",
       _support_area_component({"footprint_sample_count": 0,
                                "footprint_supported_sample_count": 0}) == UNKNOWN)
    # The far side's derived AREA pair must drive the same ratio as the counts.
    _t("support_area_from_cm2_areas_positive",
       _support_area_component({"required_footprint_area_cm2": 3631.68,
                                "supported_footprint_area_cm2": 3631.68}) is True)
    _t("support_area_from_cm2_areas_negative",
       _support_area_component({"required_footprint_area_cm2": 3631.68,
                                "supported_footprint_area_cm2": 2723.76}) is False)
    _t("atoms_contact_grounded_must_agree",
       not check_reference_integrity(
           {"marker": {"m0": {"contact": True, "grounded": False}}})[0])
    _t("grounding_thresholds_are_named",
       derive_grounding_valid(_gm())[1]["thresholds"] == {
           "SUPPORT_AREA_RATIO_MIN": SUPPORT_AREA_RATIO_MIN,
           "GROUND_DZ_TOLERANCE_CM": GROUND_DZ_TOLERANCE_CM,
           "GROUND_MAX_SLOPE_DEG": GROUND_MAX_SLOPE_DEG})
    # The constants table validates itself, and the validator can actually reject.
    _t("contract_constants_valid",
       not [c for c in validate_contract_constants() if not c[1]],
       [c[0] for c in validate_contract_constants() if not c[1]])
    for _label, _tbl in sorted({
            "nonfinite_value": {"X": {"value": float("nan"), "unit": "cm",
                                      "why": "w"}},
            "missing_unit": {"X": {"value": 1.0, "unit": "", "why": "w"}},
            "missing_provenance": {"X": {"value": 1.0, "unit": "cm", "why": ""}},
            "below_exclusive_lower": {"X": {"value": 0.0, "unit": "d", "why": "w",
                                            "lo": 0.0, "lo_inclusive": False}},
            "above_inclusive_upper": {"X": {"value": 1.5, "unit": "d", "why": "w",
                                            "hi": 1.0, "hi_inclusive": True}},
            "at_or_above_slope_ceiling": {"X": {"value": 90.0, "unit": "deg",
                                                "why": "w", "hi": 90.0,
                                                "hi_inclusive": False}},
    }.items()):
        _t("contract_constant_rejects_" + _label,
           bool([c for c in validate_contract_constants(_tbl) if not c[1]]), _tbl)

    # --- (5) numeric hygiene ----------------------------------------------- #
    _t("nan_is_not_finite", not is_finite_number(float("nan")))
    _t("inf_is_not_finite", not is_finite_number(float("inf"))
       and not is_finite_number(float("-inf")))
    _t("bool_is_not_numeric_evidence",
       not is_finite_number(True) and not is_finite_number(False))
    _t("real_number_is_finite", is_finite_number(0.0) and is_finite_number(-3))
    _hok, _hd = numeric_hygiene_ok({"a": [1.0, {"z": float("nan")}]})
    _t("hygiene_finds_nested_nan", not _hok, _hd)
    _t("hygiene_passes_clean", numeric_hygiene_ok({"a": [1.0, {"z": -2.5}]})[0])
    _e, _v, _i, _d = derive("player_clearance_valid",
                            {"marker": {"m0": {"capsule_clear": True,
                                               "location": [0.0, 0.0,
                                                            float("nan")]}}})
    _t("derive_rejects_nan_bundle", (not _e) and _v is None, _d)

    # --- (6) reference integrity — every rule must FAIL CLOSED ------------- #
    _t("refs_intact_bundle_passes",
       check_reference_integrity({"marker": {"m0": {"ground_trace_ref": "trace#t"}},
                                  "trace": {"t": {"hit": True}}})[0])
    _t("refs_dangling_rejected",
       not check_reference_integrity(
           {"marker": {"m0": {"ground_trace_ref": "trace#missing"}}})[0])
    _t("refs_malformed_rejected",
       not check_reference_integrity({"marker": {"m0": {"actor_ref": "no-hash"}}})[0])
    _t("refs_list_entries_checked",
       not check_reference_integrity(
           {"actor": {"a": {"component_refs": ["component#gone"]}}})[0])
    _t("refs_duplicate_record_id_rejected",
       not check_reference_integrity(
           {"actor": {"a": {"record_id": "a"}, "b": {"record_id": "a"}}})[0])
    _t("refs_cross_operation_rejected",
       not check_reference_integrity(
           {"actor": {"a": {"operation_id": "op1",
                            "component_refs": ["component#c"]}},
            "component": {"c": {"operation_id": "op2"}}})[0])
    _t("refs_foreign_operation_rejected",
       not check_reference_integrity({"actor": {"a": {"operation_id": "op2"}}},
                                     operation_id="op1")[0])
    _t("refs_same_operation_accepted",
       check_reference_integrity({"actor": {"a": {"operation_id": "op1"}}},
                                 operation_id="op1")[0])
    _t("atoms_clearance_overlap_must_be_complements",
       not check_reference_integrity(
           {"marker": {"m0": {"capsule_clear": True, "overlap": True}}})[0])
    _t("atoms_accepted_contradiction_rejected",
       not check_reference_integrity(
           {"marker": {"m0": {"accepted": True, "grounded": False}}})[0])
    _t("atoms_inventory_collection_ok_contradiction_rejected",
       not check_reference_integrity(
           {"inventory": {"pre": {"collection_ok": True, "actor_paths": None,
                                  "dirty_packages": []}}})[0])
    # ...and a broken bundle must not be ANSWERED from. Without the gate this
    # exact input derives a confident `player_clearance_valid: True`.
    _e, _v, _i, _d = derive("player_clearance_valid",
                            {"marker": {"m0": {"capsule_clear": True,
                                               "overlap": True}}})
    _t("derive_fails_closed_on_contradiction", (not _e) and _v is None, _d)
    _e, _v, _i, _d = derive("grounding_valid",
                            _gm(marker={"ground_trace_ref": "trace#gone"}))
    _t("derive_fails_closed_on_dangling_ref", (not _e) and _v is None, _d)
    _t("bundle_integrity_tolerates_schema_version",
       bundle_integrity({"schema_version": RT_RAW_BUNDLE, "marker": {}})[0])

    # Re-derivation must catch forgery on the NEW predicates too, or the whole
    # section is unenforced.
    for _field, _raw_f in (("grounding_valid", _gm({"grounded": False})),
                           ("actor_bounds_valid",
                            {"actor": {"a": {"bounds_extent": [0.0, 0.0, 0.0]}}}),
                           ("cleanup_verified",
                            {"inventory": {
                                "pre": _snap("observe"),
                                "post": _snap("cleanup",
                                              operation_owned_actor_paths=["/T"])}})):
        _forged = record(True, DERIVED, stage="assemble", collector="assembler",
                         raw_refs=["marker#m0"], collection_ok=True,
                         derivation=_field)
        _r_ok, _rd = rederive_and_compare(_field, _forged, _raw_f)
        _t("rederivation_catches_forgery::" + _field, not _r_ok, _rd)

    print("SCENE-SURVEY EVIDENCE MODEL SELF-DOGFOOD: {} ({} derivations, "
          "{} measured predicates)".format(
              "PASS" if ok else "FAIL", len(DERIVATIONS), len(PREDICATE_NAMES)))
    sys.exit(0 if ok else 1)
