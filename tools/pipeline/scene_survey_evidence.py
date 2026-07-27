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
        (``scene_survey_far_side.py:295-301`` sets observed_world_package /
        observed_anchor_location / observed_anchor_object_path from the live
        editor), i.e. the only channel that can DISAGREE with the request.
      * ``echoed``    — CALLER_SUPPLIED on both sides. subject_id and resolved_by
        are caller vocabulary; WorldForge has no channel that could observe either
        (``run_scene_survey_probe.py:311-316`` says so explicitly). They give
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

    print("SCENE-SURVEY EVIDENCE MODEL SELF-DOGFOOD: {} ({} derivations)".format(
        "PASS" if ok else "FAIL", len(DERIVATIONS)))
    sys.exit(0 if ok else 1)
