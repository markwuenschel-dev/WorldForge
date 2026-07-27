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

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/scene_survey_evidence.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as C  # noqa: E402

RT_EVIDENCE = "wf.scene_survey.evidence_record.v1"
RT_RAW_BUNDLE = "wf.scene_survey.raw_evidence_bundle.v1"


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
    """Resolve one raw_ref against a bundle, or None."""
    if not isinstance(ref, str) or "#" not in ref:
        return None
    kind, _, ident = ref.partition("#")
    return (bundle or {}).get(kind, {}).get(ident)


def unresolved_refs(bundle, refs):
    return [r for r in (refs or []) if resolve_raw(bundle, r) is None]


# --------------------------------------------------------------------------- #
# Derivations. Pure functions over RAW observations.
# --------------------------------------------------------------------------- #
# Each returns (value, inputs_description). Each is paired with a SUFFICIENCY
# precondition stating what raw is required before the question is even askable.
# Sufficiency is separate from the derivation on purpose: an empty input list will
# happily produce a confident-looking answer from `all()` or `sum()`, and that is
# exactly the "empty result mistaken for a valid zero" failure mode.

def sufficiency_actor_bounds(raw):
    """Bounds validity needs per-actor bounds records, not a count."""
    actors = (raw or {}).get("actor", {})
    if not actors:
        return False, ("no per-actor records were collected — an actor COUNT "
                       "cannot answer whether bounds are valid")
    with_bounds = [a for a in actors.values() if _has_extent(a)]
    if not with_bounds:
        return False, ("{} actor record(s) collected, none carrying bounds extent"
                       .format(len(actors)))
    return True, "{} actor record(s), {} with bounds extent".format(
        len(actors), len(with_bounds))


def derive_actor_bounds_valid(raw):
    """Every collected actor must carry a finite, non-degenerate bounds extent."""
    actors = (raw or {}).get("actor", {})
    bad = []
    for ident, a in sorted(actors.items()):
        ext = a.get("bounds_extent")
        if not _finite3(ext):
            bad.append((ident, "extent not a finite vec3: {!r}".format(ext))); continue
        if all(float(v) == 0.0 for v in ext):
            bad.append((ident, "degenerate zero extent"))
    return (not bad), {"actors_checked": len(actors),
                       "actors_rejected": [b[0] for b in bad],
                       "reasons": [b[1] for b in bad[:5]]}


def sufficiency_markers(raw):
    markers = (raw or {}).get("marker", {})
    if not markers:
        return False, ("no per-marker records were collected — nothing to classify. "
                       "An all()/sum() over an empty list yields a confident answer "
                       "about nothing")
    return True, "{} marker record(s)".format(len(markers))


def derive_placements_grounded(raw):
    """Count markers whose GROUND CONTACT was observed — not those accepted.

    `accepted` is strictly stronger (grounded AND footprint AND clearance), so
    using it under this name under-reports grounded candidates and makes the two
    fields impossible to disagree, which destroys their diagnostic value.
    """
    markers = (raw or {}).get("marker", {})
    ids = sorted(k for k, m in markers.items() if m.get("grounded") is True)
    return len(ids), {"markers_total": len(markers), "grounded_ids": ids}


def derive_placements_accepted(raw):
    markers = (raw or {}).get("marker", {})
    ids = sorted(k for k, m in markers.items() if m.get("accepted") is True)
    return len(ids), {"markers_total": len(markers), "accepted_ids": ids}


def derive_placements_requested(raw):
    markers = (raw or {}).get("marker", {})
    return len(markers), {"markers_total": len(markers)}


def derive_overlap_count(raw):
    markers = (raw or {}).get("marker", {})
    ids = sorted(k for k, m in markers.items() if m.get("overlap") is True)
    return len(ids), {"markers_total": len(markers), "overlapping_ids": ids}


def derive_player_clearance_valid(raw):
    """Clearance from the OBSERVED capsule test, independent of acceptance.

    The previous predicate `(not accepted) or clearance` was a tautology: the C++
    defines accepted = grounded && footprint && clearance, so accepted implies
    clearance by construction. Deriving from the raw overlap observation instead
    makes the claim falsifiable — a marker CAN be observed overlapping.
    """
    markers = (raw or {}).get("marker", {})
    blocked = sorted(k for k, m in markers.items() if m.get("capsule_clear") is not True)
    return (not blocked), {"markers_total": len(markers), "blocked_ids": blocked}


def sufficiency_cleanup(raw):
    """Cleanup needs a BEFORE and an AFTER inventory, and the after must be after."""
    inv = (raw or {}).get("inventory", {})
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
    return True, "pre@{} post@{}".format(pre["stage"], post["stage"])


def derive_cleanup_verified(raw):
    """Final state must equal initial state: same actor set, no new dirty packages."""
    inv = (raw or {}).get("inventory", {})
    pre, post = inv.get("pre") or {}, inv.get("post") or {}
    pre_actors = set(pre.get("actor_paths") or [])
    post_actors = set(post.get("actor_paths") or [])
    leaked = sorted(post_actors - pre_actors)
    vanished = sorted(pre_actors - post_actors)
    pre_dirty = set(pre.get("dirty_packages") or [])
    post_dirty = set(post.get("dirty_packages") or [])
    newly_dirty = sorted(post_dirty - pre_dirty)
    ok = not leaked and not vanished and not newly_dirty
    return ok, {"leaked_actors": leaked, "vanished_actors": vanished,
                "newly_dirty_packages": newly_dirty,
                "actors_pre": len(pre_actors), "actors_post": len(post_actors)}


def derive_temporary_actor_count(raw, which):
    inv = (raw or {}).get("inventory", {}).get(which) or {}
    owned = inv.get("operation_owned_actor_paths")
    if owned is None:
        return None, {"reason": "inventory carries no operation-owned actor list"}
    return len(owned), {"operation_owned": sorted(owned)}


DERIVATIONS = {
    "actor_bounds_valid": (derive_actor_bounds_valid, sufficiency_actor_bounds),
    "temporary_placements_requested": (derive_placements_requested, sufficiency_markers),
    "temporary_placements_accepted": (derive_placements_accepted, sufficiency_markers),
    "temporary_placements_grounded": (derive_placements_grounded, sufficiency_markers),
    "overlap_count": (derive_overlap_count, sufficiency_markers),
    "player_clearance_valid": (derive_player_clearance_valid, sufficiency_markers),
    "cleanup_verified": (derive_cleanup_verified, sufficiency_cleanup),
}


def derive(field, raw):
    """Run one named derivation. Returns (ok_sufficient, value, inputs, detail)."""
    if field not in DERIVATIONS:
        return False, None, None, "no derivation registered for {!r}".format(field)
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
    if not isinstance(v, list) or len(v) != 3:
        return False
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return False
        if x != x or x in (float("inf"), float("-inf")):  # NaN / inf
            return False
    return True


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
    inv = {"inventory": {
        "pre": {"stage": "observe", "collection_ok": True, "actor_paths": ["/A"],
                "dirty_packages": []},
        "post": {"stage": "cleanup", "collection_ok": True, "actor_paths": ["/A"],
                 "dirty_packages": []}}}
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_clean_state", enough and v is True)
    inv["inventory"]["post"]["actor_paths"] = ["/A", "/LEAKED"]
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_detects_leak", enough and v is False)
    inv["inventory"]["post"]["actor_paths"] = ["/A"]
    inv["inventory"]["post"]["dirty_packages"] = ["/Game/Maps/M"]
    enough, v, _i, _d = derive("cleanup_verified", inv)
    _t("cleanup_detects_dirty", enough and v is False)

    # A post inventory taken BEFORE cleanup cannot witness cleanup.
    inv["inventory"]["post"] = {"stage": "observe", "collection_ok": True,
                                "actor_paths": ["/A"], "dirty_packages": []}
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

    print("SCENE-SURVEY EVIDENCE MODEL SELF-DOGFOOD: {} ({} derivations)".format(
        "PASS" if ok else "FAIL", len(DERIVATIONS)))
    sys.exit(0 if ok else 1)
