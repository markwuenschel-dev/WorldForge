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


# The kinds that carry MEASURED observations, as emitted by
# `_new_raw_bundle` in tools/bridge/scene_survey_far_side.py. `binding` is absent:
# it is a projection of a report, not a collector's output, and its finiteness is
# policed by the component that needs it (with a far more specific reason) rather
# than by the bundle-wide numeric gate.
RAW_OBSERVATION_KINDS = ("world", "actor", "component", "trace", "marker",
                         "proxy", "temporary_placement", "inventory")


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
    numeric = {k: (bundle or {}).get(k) for k in RAW_OBSERVATION_KINDS
               if isinstance((bundle or {}).get(k), dict)}
    ok_num, num_detail = numeric_hygiene_ok(numeric)
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
    """The object was RE-OBSERVED to be gone, not merely destroy()'d.

    `absent_after_cleanup` is set from a fresh level enumeration
    (`_SpawnLedger.cleanup`) and is None when that
    enumeration could not be run. `destroy_returned` is recorded separately and is
    deliberately not consulted here — a destroy call's return value is the
    runtime's claim about itself.
    """
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
    return True, "pre@{} post@{}, with D, T and M measured on both".format(
        pre["stage"], post["stage"])


def derive_cleanup_verified(raw):
    """CleanupVerified = (D_f = D_i) AND (T_f = T_i) AND (M_f = M_i).

    EQUALITY, not containment, on every one of the three. The previous rule only
    looked for NEWLY dirty packages; a package that stops being dirty was written
    to disk, and a survey that saves a map has mutated the project just as surely
    as one that dirties it. The actor-set comparison is retained on top —
    strictly additional, never a replacement.
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

    ok = (not leaked and not vanished and not newly_dirty and not no_longer_dirty
          and not temp_leaked and not temp_released and map_identity_stable)
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
        "leaked_actors": leaked, "vanished_actors": vanished,
        "actors_pre": len(pre_actors), "actors_post": len(post_actors),
    }


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

    inv = {"inventory": {"pre": _snap("observe"), "post": _snap("cleanup")}}
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_clean_state", enough and v is True, (enough, v))
    inv["inventory"]["post"]["actor_paths"] = ["/A", "/LEAKED"]
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_detects_leak", enough and v is False)
    inv["inventory"]["post"]["actor_paths"] = ["/A"]
    inv["inventory"]["post"]["dirty_packages"] = ["/Game/Maps/M"]
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_detects_dirty", enough and v is False)

    # D_f = D_i is EQUALITY: a package that STOPS being dirty was saved to disk,
    # which the old containment rule (post - pre) could not see at all.
    _inv = {"inventory": {"pre": _snap("observe", dirty_packages=["/Game/Maps/M"]),
                          "post": _snap("cleanup", dirty_packages=[])}}
    enough, v, i, _d = derive("cleanup_verified", _inv)
    _t("cleanup_detects_package_saved",
       enough and v is False and i["no_longer_dirty_packages"] == ["/Game/Maps/M"],
       (enough, v))
    # T_f = T_i — a temporary object still owned after cleanup is a leak.
    _inv = {"inventory": {
        "pre": _snap("observe"),
        "post": _snap("cleanup", operation_owned_actor_paths=["/Temp_0"])}}
    enough, v, i, _d = derive("cleanup_verified", _inv)
    _t("cleanup_detects_temporary_leak",
       enough and v is False and i["temporary_objects_leaked"] == ["/Temp_0"],
       (enough, v))
    # T absent is UNKNOWN, never the empty set — this is the exact door a
    # hard-coded cleanup_verified=True walks back in through.
    _inv = {"inventory": {"pre": _snap("observe"), "post": _snap("cleanup")}}
    del _inv["inventory"]["post"]["operation_owned_actor_paths"]
    enough, _v, _i, d = derive("cleanup_verified", _inv)
    _t("cleanup_absent_owned_set_is_unknown", not enough, d)
    # M_f = M_i — the map identity must be the same world on both sides.
    _inv = {"inventory": {"pre": _snap("observe"),
                          "post": _snap("cleanup", map_identity="/Game/Maps/OTHER",
                                        package_identity="/Game/Maps/OTHER")}}
    enough, v, i, _d = derive("cleanup_verified", _inv)
    _t("cleanup_detects_map_identity_drift",
       enough and v is False and i["map_identity_equal"] is False, (enough, v))
    _inv = {"inventory": {"pre": _snap("observe", map_identity=None),
                          "post": _snap("cleanup")}}
    enough, _v, _i, d = derive("cleanup_verified", _inv)
    _t("cleanup_absent_map_identity_is_unknown", not enough, d)

    # A post inventory taken BEFORE cleanup cannot witness cleanup.
    inv["inventory"]["post"] = _snap("observe")
    enough, _v, _i, d = derive("cleanup_verified", inv)
    _t("cleanup_rejects_stage_inversion", not enough, d)

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
        "temporary_placement": {"t0": {"absent_after_cleanup": False}},
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
