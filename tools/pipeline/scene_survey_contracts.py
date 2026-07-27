#!/usr/bin/env python3
"""SceneSurveyForge (v2.6) contract spine — schema-only, no I/O.

Design mirrors tactical_contracts.py / streaming_contracts.py exactly: a bounded
taxonomy (one source of truth), small local scalar helpers wrapping runtime_schema
primitives, and a per-record triplet (validate_X, _example_X) plus a registry tail
(CONTRACTS / CONTRACT_GROUPS / KNOWN_BAD_OWNING_CODE / SCENE_SURVEY_CODES).

The honesty invariants are the point, not the type checks. v2.6 is the first
READ-ONLY spatial survey of a real external UE 5.8 target. A record is
rejected when it is shaped-but-dishonest: a camera "ok" with no image hash; a
non-orthographic top-down passed off as true top-down; a support sample counted
valid while classified unknown/trace_error (fail-closed); a coverage=complete claim
over zero probed samples; a temporary marker claimed grounded while floating; a
placement accepted despite an overlap / clearance / edge violation; a placement
coordinate not backed by a trace (guessed); a proxy with no owner/category binding;
a proxies-disabled claim with proxies still present; a cleanup claim whose final
state != initial; a clean report with no evidence; a simulated result mislabeled as
live runtime; a survey subject WorldForge picked for itself; a report anchored
somewhere other than the subject it was handed. Owning codes live in the
WF1061–1109 band.

Ownership boundary: the CALLER owns intent and hands WorldForge an already-resolved
SceneSurveySubject; WorldForge owns execution and its job is to verify and echo that
subject, never to go find one. Hence there is no anchor vocabulary here — the two
anchor *modes* are storage shapes, not choices WorldForge is allowed to make.
"""

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_schema as RS  # noqa: E402
import scene_survey_evidence as EV  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402

# --------------------------------------------------------------------------- #
# schema_version / report_type dotted namespaces (wf.scene_survey.<type>.v1)
# --------------------------------------------------------------------------- #
RT_PROFILE = "wf.scene_survey.survey_profile.v1"
RT_SUBJECT = "wf.scene_survey.survey_subject.v1"
RT_CAMERA = "wf.scene_survey.camera_capture.v1"
RT_SUPPORT_MAP = "wf.scene_survey.support_map.v1"
RT_PLACEMENT = "wf.scene_survey.temporary_placement.v1"
RT_PROXY_REPORT = "wf.scene_survey.proxy_report.v1"
RT_SURVEY_REPORT = "wf.scene_survey.survey_report.v1"
RT_EVIDENCE_INDEX = "wf.scene_survey.evidence_index.v1"

# --------------------------------------------------------------------------- #
# Bounded taxonomy (one source of truth).
# --------------------------------------------------------------------------- #
# v2.6 first trial is read-only w.r.t. the courtyard. live_survey_runtime is the
# only mode that touches a real editor; the deterministic simulation is for fuzz.
SURVEY_MODES = ("read_only_survey",)
# The three deterministic fixed cameras (handoff §5).
CAMERA_KINDS = ("gameplay", "elevated_oblique", "top_down")
PROJECTIONS = ("perspective", "orthographic")
# The 6-class fail-closed support taxonomy. unknown/trace_error never count valid.
SUPPORT_CLASSES = ("valid_support", "unsupported", "edge", "blocked",
                   "trace_error", "unknown")
VALID_SUPPORT_CLASSES = ("valid_support",)
# How the caller expressed the subject's anchor. Caller-declared: WorldForge stores
# and echoes these; it must never interpret them or pick one for itself.
ANCHOR_MODES = ("explicit_transform", "actor_object_path")
# What kind of thing the caller resolved. Opaque to WorldForge beyond the enum.
SUBJECT_KINDS = ("actor", "area", "point")
# Provenance of the resolution. "caller" is the ONLY legal value in a production
# run. Any other value means WorldForge resolved the subject itself => WF1108.
SUBJECT_RESOLVERS = ("caller",)
# Proxy categories — a bounded taxonomy supplied by the caller (PathCue /
# CorruptionFeedback exist in the enum but are not built by the current adapter
# — still bounded/known).
PROXY_CATEGORIES = ("Heart", "RitualPoint", "LanternRestore", "InteractionRadius",
                    "NightFeedback", "PathCue", "CorruptionFeedback")
# Honest runtime-mode labels: a deterministic simulation must NOT be labeled a live
# survey. Both acceptable if labeled honestly (mirrors v2.4 §12).
RUNTIME_MODES = ("deterministic_survey_simulation", "live_survey_runtime")
LIVE_RUNTIME_MODES = ("live_survey_runtime",)
# Report / evidence-index verdicts.
SURVEY_STATUS = ("pass", "fail", "blocked")
INTEGRITY_RESULTS = ("pass", "fail", "blocked")
# Acceptance eligibility vocabulary. Defined ONCE in the evidence model (where the
# derivation lives) and re-exported here so the contract surface, the exporter and
# the validator lane all read the same tuple instead of three copies that drift.
ACCEPTANCE_COMPONENTS = EV.ACCEPTANCE_COMPONENTS
ACCEPTANCE_INELIGIBILITY_REASONS = EV.ACCEPTANCE_INELIGIBILITY_REASONS

# The shared deterministic authoring timestamp (NOT wall-clock).
AUTHORING_TS = "2026-07-19T00:00:00+00:00"

# Generated / report roots (repo-relative).
SURVEY_PROFILES_REL = "procedural/generated/scene_survey/profiles"
SURVEY_REPORTS_REL = "procedural/reports/scene_survey"


# --------------------------------------------------------------------------- #
# small local helpers (mirror tactical_contracts.py / streaming_contracts.py)
# --------------------------------------------------------------------------- #
def _str(obj, field, code, prefix):
    ch = RS.check_type(obj, field, str, code, prefix=prefix)
    v = obj.get(field) if isinstance(obj, dict) else None
    ch.append(("{}{}_nonempty".format(prefix, field),
               isinstance(v, str) and bool(v.strip()),
               "{} must be a non-empty string".format(field), code))
    return ch


def _bool(obj, field, code, prefix, nullable=False):
    """Type rail for a boolean field.

    ``nullable=True`` means None is a legal value carrying the meaning "unknown —
    this was never observed". It is NOT a licence to omit the measurement: the
    honesty rails (sr::unobserved_forbids_pass, sr::clean_requires_evidence) make an
    unknown incompatible with a pass, so declining to measure costs a green result.
    Without this, the only way to satisfy the type rail is a fabricated False, which
    is a populated field with no observation chain behind it.
    """
    v = obj.get(field) if isinstance(obj, dict) else None
    if nullable and v is None:
        return []
    return [("{}{}_bool".format(prefix, field), isinstance(v, bool),
             "{} must be an explicit boolean (got {!r})".format(field, v), code)]


def _int(obj, field, code, prefix, allow_zero=True, nullable=False):
    """Type rail for an integer field. See _bool for what ``nullable`` means and
    why it does not weaken the contract."""
    v = obj.get(field) if isinstance(obj, dict) else None
    if nullable and v is None:
        return []
    ch = RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)
    is_int = RS.is_number(v) and float(v).is_integer()
    ch.append(("{}{}_integer".format(prefix, field), is_int,
               "{} must be an integer (got {!r})".format(field, v), code))
    return ch


def _num(obj, field, code, prefix, allow_zero=True):
    return RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)


def _subset(obj, field, allowed, code, prefix, min_len=0):
    v = obj.get(field) if isinstance(obj, dict) else None
    is_list = isinstance(v, list) and all(isinstance(x, str) for x in v)
    ok = is_list and len(v) >= min_len and all(x in allowed for x in v)
    bad = sorted(set(v) - set(allowed)) if is_list else v
    return [("{}{}_subset".format(prefix, field), ok,
             "{} must be a >= {}-length subset of the bounded set (unknown: {})".format(
                 field, min_len, bad), code)]


def _list_of_str(obj, field, code, prefix, min_len=0):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) >= min_len and all(isinstance(x, str) for x in v)
    return [("{}{}_str_list".format(prefix, field), ok,
             "{} must be a list of >= {} strings".format(field, min_len), code)]


def _finite_vec(v, n=3):
    return isinstance(v, list) and len(v) == n and all(RS.is_number(x) for x in v)


def _vec3(obj, field, code, prefix):
    v = obj.get(field) if isinstance(obj, dict) else None
    return [("{}{}_vec3".format(prefix, field), _finite_vec(v, 3),
             "{} must be a 3-element finite numeric vector".format(field), code)]


def _schema_version(obj, expected, code, prefix):
    sv = obj.get("schema_version") if isinstance(obj, dict) else None
    return [("{}schema_version".format(prefix), sv == expected,
             "schema_version must be {!r} (got {!r})".format(expected, sv), code)]


def _nested(prefix, name):
    """Re-prefix a delegated sub-record check name so it stays unique in the parent.

    A sub-record's own rails already carry its 'xx::' namespace (swap it for the
    parent's), while the shared runtime_schema checks (field::*, no_unknown_fields)
    carry none and would otherwise collide with the parent's identically-named ones.
    """
    head, sep, tail = name.partition("::")
    return prefix + (tail if sep and len(head) == 2 else name)


_META_FIELDS = ("meta", "report_type", "created_by", "created_at", "notes", "display_key")

# Version of the caller-facing contract SURFACE (the set of records, their fields,
# and their rails) — distinct from the per-record RT_* schema_version strings, which
# version one record shape each. Exported artifacts carry this so a caller can state
# which surface it generated against. Bump when a field or rail changes meaning.
CONTRACT_VERSION = "wf.scene_survey.contract.v2_6.1"


# =========================================================================== #
# 1. SceneSurveySubject (WF1106) — the caller-resolved subject of the survey.
# =========================================================================== #
# WorldForge NEVER produces one of these; it receives one and verifies it. Every
# field is caller-owned. subject_id is opaque here — WorldForge does not parse it,
# it only echoes it back so the caller can prove the survey it got back is the
# survey it asked for.
SUBJECT_REQUIRED = (
    "subject_id",           # opaque to WorldForge; non-empty str
    "subject_kind",         # enum SUBJECT_KINDS
    "map_asset_path",       # "/Game/..." package path, non-empty str
    "anchor_mode",          # enum ANCHOR_MODES
    "anchor_location",      # [x,y,z] finite numbers, or None
    "anchor_rotation",      # [p,y,r] finite numbers, or None
    "anchor_object_path",   # full object path str, or None
    "resolved_by",          # enum SUBJECT_RESOLVERS
    "schema_version",       # RT_SUBJECT
)
SUBJECT_ALLOWED = SUBJECT_REQUIRED + _META_FIELDS
# These three are mode-dependent: the key must be PRESENT (an absent key is itself
# a report-integrity smell) but exactly one of location/object_path carries a value.
_SUBJECT_NULLABLE = ("anchor_location", "anchor_rotation", "anchor_object_path")


def validate_scene_survey_subject(obj, strict=False):
    code = C.SCENE_SURVEY_SUBJECT_UNRESOLVED
    ch = RS.check_required(obj, SUBJECT_REQUIRED, code, nullable=_SUBJECT_NULLABLE)
    ch += RS.check_no_unknown(obj, SUBJECT_ALLOWED, code, strict)
    ch += _str(obj, "subject_id", code, "ss::")
    ch += _str(obj, "map_asset_path", code, "ss::")
    ch += RS.check_enum(obj, "subject_kind", SUBJECT_KINDS, code, prefix="ss::")
    ch += RS.check_enum(obj, "anchor_mode", ANCHOR_MODES, code, prefix="ss::")
    ch += RS.check_enum(obj, "resolved_by", SUBJECT_RESOLVERS,
                        C.SCENE_SURVEY_SUBJECT_INFERRED, prefix="ss::")
    mode = obj.get("anchor_mode") if isinstance(obj, dict) else None
    loc = obj.get("anchor_location") if isinstance(obj, dict) else None
    rot = obj.get("anchor_rotation") if isinstance(obj, dict) else None
    opath = obj.get("anchor_object_path") if isinstance(obj, dict) else None
    has_path = isinstance(opath, str) and bool(opath.strip())
    # shape: the optional-valued anchor fields are either None or well-formed.
    ch.append(("ss::anchor_location_shape", loc is None or _finite_vec(loc, 3),
               "anchor_location must be a 3-element finite numeric vector or None "
               "(got {!r})".format(loc), code))
    ch.append(("ss::anchor_rotation_shape", rot is None or _finite_vec(rot, 3),
               "anchor_rotation must be a 3-element finite numeric vector or None "
               "(got {!r})".format(rot), code))
    ch.append(("ss::anchor_object_path_shape", opath is None or isinstance(opath, str),
               "anchor_object_path must be a string or None (got {!r})".format(opath), code))
    # honesty: an explicit_transform subject must actually carry the transform, and
    # must not smuggle an object path the caller expects WorldForge to go resolve.
    ch.append(("ss::explicit_transform_complete",
               mode != "explicit_transform" or (_finite_vec(loc, 3) and opath is None),
               "anchor_mode=explicit_transform requires a finite vec3 anchor_location "
               "and anchor_object_path=None (an unresolved subject)", code))
    # honesty: an actor_object_path subject must carry the full object path, and must
    # not also carry a transform (two channels that could disagree — see WF1109).
    ch.append(("ss::object_path_complete",
               mode != "actor_object_path" or (has_path and loc is None),
               "anchor_mode=actor_object_path requires a non-empty anchor_object_path "
               "and anchor_location=None (an unresolved subject)", code))
    # honesty: exactly one anchor channel is populated. Zero means the caller never
    # resolved the subject; two means WorldForge would have to choose — it may not.
    ch.append(("ss::mode_exclusive", (loc is None) != (opath is None),
               "exactly one of anchor_location / anchor_object_path must be non-None "
               "(got location={!r}, object_path={!r})".format(loc, opath), code))
    # honesty: a subject WorldForge resolved for itself is not a caller intent.
    ch.append(("ss::resolved_by_caller", obj.get("resolved_by") == "caller"
               if isinstance(obj, dict) else False,
               "resolved_by must be 'caller' — WorldForge must never resolve the "
               "survey subject itself", C.SCENE_SURVEY_SUBJECT_INFERRED))
    ch += _schema_version(obj, RT_SUBJECT, code, "ss::")
    return ch


def _example_scene_survey_subject(**over):
    d = {
        "subject_id": "subject_fixture_alpha",
        "subject_kind": "point",
        "map_asset_path": "/Game/Fixture/Lvl_Fixture",
        "anchor_mode": "explicit_transform",
        "anchor_location": [1200.0, -450.0, 92.5],
        "anchor_rotation": [0.0, 90.0, 0.0],
        "anchor_object_path": None,
        "resolved_by": "caller",
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_SUBJECT,
        "report_type": RT_SUBJECT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 2. SceneSurveyProfile (WF1061) — the bounded survey configuration.
# =========================================================================== #
PROFILE_REQUIRED = (
    "profile_id", "survey_mode", "subject", "captures", "sample_radius_cm",
    "sample_step_cm", "temporary_markers", "disable_debug_proxies", "cleanup",
    "repeat", "strict", "schema_version",
)
PROFILE_ALLOWED = PROFILE_REQUIRED + _META_FIELDS


def validate_scene_survey_profile(obj, strict=False):
    code = C.SCENE_SURVEY_PROFILE_INVALID
    ch = RS.check_required(obj, PROFILE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, PROFILE_ALLOWED, code, strict)
    ch += _str(obj, "profile_id", code, "sp::")
    ch += RS.check_enum(obj, "survey_mode", SURVEY_MODES, C.SCENE_SURVEY_UNKNOWN_MODE, prefix="sp::")
    # the caller-resolved subject rides nested inside the profile. There is no
    # nesting precedent in this module, so we delegate to the record's own
    # validator and re-prefix its check names (ss:: -> sp::subject::) so the
    # combined list stays unique and the failing rail is still self-describing.
    sub = obj.get("subject") if isinstance(obj, dict) else None
    ch.append(("sp::subject_is_object", isinstance(sub, dict),
               "subject must be a nested SceneSurveySubject object "
               "(got {!r})".format(type(sub).__name__),
               C.SCENE_SURVEY_SUBJECT_UNRESOLVED))
    if isinstance(sub, dict):
        ch += [(_nested("sp::subject::", n), ok, d, c)
               for (n, ok, d, c) in validate_scene_survey_subject(sub, strict=strict)]
    # capture is opt-in: an empty captures list is legal (a survey that was never
    # asked to render must not be failed for not rendering).
    ch += _subset(obj, "captures", CAMERA_KINDS, C.SCENE_SURVEY_UNKNOWN_CAPTURE, "sp::", min_len=0)
    ch += _num(obj, "sample_radius_cm", code, "sp::", allow_zero=False)
    ch += _num(obj, "sample_step_cm", code, "sp::", allow_zero=False)
    ch += _int(obj, "temporary_markers", code, "sp::", allow_zero=True)
    ch += _bool(obj, "disable_debug_proxies", code, "sp::")
    ch += _bool(obj, "cleanup", code, "sp::")
    ch += _int(obj, "repeat", code, "sp::", allow_zero=False)
    ch += _bool(obj, "strict", code, "sp::")
    ch += _schema_version(obj, RT_PROFILE, code, "sp::")
    return ch


def _example_scene_survey_profile(**over):
    d = {
        "profile_id": "survey_profile_fixture_readonly",
        "survey_mode": "read_only_survey",
        "subject": _example_scene_survey_subject(),
        "captures": list(CAMERA_KINDS),
        "sample_radius_cm": 3000,
        "sample_step_cm": 100,
        "temporary_markers": 3,
        "disable_debug_proxies": True,
        "cleanup": True,
        "repeat": 2,
        "strict": True,
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_PROFILE,
        "report_type": RT_PROFILE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 3. SceneSurveyCameraCapture (WF1068–1071) — one deterministic fixed camera.
# =========================================================================== #
CAMERA_REQUIRED = (
    "camera_id", "capture_kind", "projection", "location", "rotation", "fov",
    "aspect_ratio", "anchor_actor", "captured", "image_path", "image_hash",
    "operation_id", "schema_version",
)
CAMERA_ALLOWED = CAMERA_REQUIRED + _META_FIELDS + ("perspective_fallback",)


def validate_scene_survey_camera_capture(obj, strict=False):
    code = C.SCENE_SURVEY_CAMERA_CAPTURE_MISSING
    ch = RS.check_required(obj, CAMERA_REQUIRED, code)
    ch += RS.check_no_unknown(obj, CAMERA_ALLOWED, code, strict)
    ch += _str(obj, "camera_id", code, "cc::")
    ch += RS.check_enum(obj, "capture_kind", CAMERA_KINDS, C.SCENE_SURVEY_UNKNOWN_CAPTURE, prefix="cc::")
    ch += RS.check_enum(obj, "projection", PROJECTIONS, C.SCENE_SURVEY_CAMERA_PROJECTION_INVALID, prefix="cc::")
    ch += _vec3(obj, "location", C.SCENE_SURVEY_CAMERA_PROVENANCE_INVALID, "cc::")
    ch += _vec3(obj, "rotation", C.SCENE_SURVEY_CAMERA_PROVENANCE_INVALID, "cc::")
    ch += _num(obj, "fov", code, "cc::", allow_zero=False)
    ch += _num(obj, "aspect_ratio", code, "cc::", allow_zero=False)
    ch += _str(obj, "anchor_actor", C.SCENE_SURVEY_CAMERA_PROVENANCE_INVALID, "cc::")
    ch += _bool(obj, "captured", code, "cc::")
    ch += _str(obj, "operation_id", code, "cc::")
    # honesty: a capture that claims captured=True must carry a real image + hash.
    captured = obj.get("captured") is True
    img = obj.get("image_path")
    h = obj.get("image_hash")
    has_img = isinstance(img, str) and bool(img.strip())
    has_hash = isinstance(h, str) and bool(h.strip())
    ch.append(("cc::captured_has_evidence", (not captured) or (has_img and has_hash),
               "captured=True requires a non-empty image_path and image_hash "
               "(overclaim: a screenshot claimed with no image)",
               C.SCENE_SURVEY_CAMERA_CAPTURE_OVERCLAIM))
    # honesty: a top_down camera must be truly orthographic, OR honestly flag the
    # perspective fallback. A perspective top_down that hides the fallback is a lie.
    top_down = obj.get("capture_kind") == "top_down"
    ortho = obj.get("projection") == "orthographic"
    fallback = obj.get("perspective_fallback") is True
    ch.append(("cc::top_down_projection_honest", (not top_down) or ortho or fallback,
               "top_down must be orthographic, or explicitly set perspective_fallback=True",
               C.SCENE_SURVEY_CAMERA_PROJECTION_INVALID))
    ch += _schema_version(obj, RT_CAMERA, code, "cc::")
    return ch


def _example_scene_survey_camera_capture(**over):
    d = {
        "camera_id": "cam_gameplay_fixture",
        "capture_kind": "gameplay",
        "projection": "perspective",
        "location": [1200.0, -450.0, 260.0],
        "rotation": [0.0, -12.0, 90.0],
        "fov": 90.0,
        "aspect_ratio": 1.7778,
        "anchor_actor": "BP_FixtureSubject_C_0",
        "captured": True,
        "image_path": "procedural/reports/scene_survey/captures/cam_gameplay_fixture.png",
        "image_hash": "sha256:cam0001gameplay",
        "operation_id": "op_v2_6_scene_survey_0001",
        "perspective_fallback": False,
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_CAMERA,
        "report_type": RT_CAMERA,
    }
    d.update(over)
    return d


# =========================================================================== #
# 4. SceneSurveySupportMap (WF1075–1081) — downward-trace support classification.
# =========================================================================== #
SUPPORT_REQUIRED = (
    "support_map_id", "anchor", "sample_radius_cm", "sample_step_cm",
    "samples_total", "valid_support", "unsupported", "edge", "blocked",
    "trace_error", "unknown", "coverage_complete", "uses_navmesh", "schema_version",
)
SUPPORT_ALLOWED = SUPPORT_REQUIRED + _META_FIELDS + ("samples",)
_SUPPORT_COUNT_FIELDS = ("valid_support", "unsupported", "edge", "blocked",
                        "trace_error", "unknown")


def validate_scene_survey_support_map(obj, strict=False):
    code = C.SCENE_SURVEY_SUPPORT_SAMPLE_INVALID
    ch = RS.check_required(obj, SUPPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SUPPORT_ALLOWED, code, strict)
    ch += _str(obj, "support_map_id", code, "sm::")
    # the sampled region's anchor is the caller's opaque subject_id, echoed. It is
    # deliberately NOT an enum: WorldForge has no vocabulary of subjects to check
    # it against, and inventing one would be WorldForge choosing the subject.
    ch += _str(obj, "anchor", code, "sm::")
    ch += _num(obj, "sample_radius_cm", code, "sm::", allow_zero=False)
    ch += _num(obj, "sample_step_cm", code, "sm::", allow_zero=False)
    ch += _int(obj, "samples_total", code, "sm::", allow_zero=True)
    for f in _SUPPORT_COUNT_FIELDS:
        ch += _int(obj, f, code, "sm::", allow_zero=True)
    ch += _bool(obj, "coverage_complete", code, "sm::")
    ch += _bool(obj, "uses_navmesh", code, "sm::")
    # honesty: the six class counts must sum to samples_total (no lost samples).
    counts = [obj.get(f) for f in _SUPPORT_COUNT_FIELDS]
    total = obj.get("samples_total")
    if RS.is_number(total) and all(RS.is_number(c) for c in counts):
        ch.append(("sm::counts_sum_to_total", sum(counts) == total,
                   "class counts must sum to samples_total (sum={}, total={})".format(
                       sum(counts), total),
                   C.SCENE_SURVEY_SUPPORT_MAP_INCOMPLETE))
        # fail-closed: unknown and trace_error are NOT support. valid_support must
        # never absorb them — enforced structurally by separate buckets, and here
        # we assert valid_support does not exceed (total - unknown - trace_error).
        vs = obj.get("valid_support")
        unk = obj.get("unknown")
        te = obj.get("trace_error")
        if all(RS.is_number(x) for x in (vs, unk, te, total)):
            ch.append(("sm::valid_excludes_unknown", vs <= total - unk - te,
                       "valid_support must exclude unknown/trace_error samples "
                       "(fail-closed): vs={} > total-unknown-trace_error={}".format(
                           vs, total - unk - te),
                       C.SCENE_SURVEY_SUPPORT_UNKNOWN_OVERCLAIM))
    # honesty: coverage_complete=True requires that samples were actually probed.
    ch.append(("sm::coverage_backed_by_samples",
               obj.get("coverage_complete") is not True or (RS.is_number(total) and total > 0),
               "coverage_complete=True requires samples_total > 0 (overclaim over zero probes)",
               C.SCENE_SURVEY_SUPPORT_COVERAGE_OVERCLAIM))
    # honesty: the survey must not lean on navmesh (collision/geometry evidence only).
    ch.append(("sm::no_navmesh_dependency", obj.get("uses_navmesh") is False,
               "uses_navmesh must be False — support is collision/geometry evidence, not navmesh",
               C.SCENE_SURVEY_NAVMESH_OVERCLAIM))
    ch += _schema_version(obj, RT_SUPPORT_MAP, code, "sm::")
    return ch


def _example_scene_survey_support_map(**over):
    d = {
        "support_map_id": "support_map_fixture_alpha",
        "anchor": "subject_fixture_alpha",
        "sample_radius_cm": 3000,
        "sample_step_cm": 100,
        "samples_total": 158,
        "valid_support": 120,
        "unsupported": 20,
        "edge": 10,
        "blocked": 6,
        "trace_error": 2,
        "unknown": 0,
        "coverage_complete": True,
        "uses_navmesh": False,
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_SUPPORT_MAP,
        "report_type": RT_SUPPORT_MAP,
    }
    d.update(over)
    return d


# =========================================================================== #
# 5. SceneSurveyTemporaryPlacement (WF1082–1088) — a runtime-only marker candidate.
# =========================================================================== #
PLACEMENT_REQUIRED = (
    "marker_id", "location", "trace_backed", "grounded", "ground_contact",
    "footprint_supported", "overlap_static", "overlap_dynamic",
    "capsule_clearance", "heart_clearance", "edge_clearance", "accepted",
    "schema_version",
)
PLACEMENT_ALLOWED = PLACEMENT_REQUIRED + _META_FIELDS
# Every predicate an accepted placement must satisfy -> owning code when violated.
_PLACEMENT_GATES = (
    ("grounded", True, C.SCENE_SURVEY_PLACEMENT_NOT_GROUNDED),
    ("ground_contact", True, C.SCENE_SURVEY_PLACEMENT_NOT_GROUNDED),
    ("footprint_supported", True, C.SCENE_SURVEY_PLACEMENT_FOOTPRINT_UNSUPPORTED),
    ("overlap_static", False, C.SCENE_SURVEY_PLACEMENT_OVERLAP_ACCEPTED),
    ("overlap_dynamic", False, C.SCENE_SURVEY_PLACEMENT_OVERLAP_ACCEPTED),
    ("capsule_clearance", True, C.SCENE_SURVEY_PLACEMENT_CLEARANCE_MISSING),
    ("heart_clearance", True, C.SCENE_SURVEY_PLACEMENT_CLEARANCE_MISSING),
    ("edge_clearance", True, C.SCENE_SURVEY_PLACEMENT_EDGE_VIOLATION),
    ("trace_backed", True, C.SCENE_SURVEY_PLACEMENT_GUESSED_COORDINATES),
)


def validate_scene_survey_temporary_placement(obj, strict=False):
    code = C.SCENE_SURVEY_PLACEMENT_INVALID
    ch = RS.check_required(obj, PLACEMENT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, PLACEMENT_ALLOWED, code, strict)
    ch += _str(obj, "marker_id", code, "tp::")
    ch += _vec3(obj, "location", code, "tp::")
    for f in ("trace_backed", "grounded", "ground_contact", "footprint_supported",
              "overlap_static", "overlap_dynamic", "capsule_clearance",
              "heart_clearance", "edge_clearance", "accepted"):
        ch += _bool(obj, f, code, "tp::")
    # honesty: an accepted marker must satisfy every placement gate. A rejected
    # candidate may violate any of them (that is the survey doing its job).
    accepted = obj.get("accepted") is True
    for field, want, gate_code in _PLACEMENT_GATES:
        ok = (not accepted) or (obj.get(field) is want)
        ch.append(("tp::accepted_requires_{}".format(field), ok,
                   "accepted placement requires {}={} (got {!r})".format(
                       field, want, obj.get(field)),
                   gate_code))
    ch += _schema_version(obj, RT_PLACEMENT, code, "tp::")
    return ch


def _example_scene_survey_temporary_placement(**over):
    d = {
        "marker_id": "marker_probe_00",
        "location": [1180.0, -420.0, 92.5],
        "trace_backed": True,
        "grounded": True,
        "ground_contact": True,
        "footprint_supported": True,
        "overlap_static": False,
        "overlap_dynamic": False,
        "capsule_clearance": True,
        "heart_clearance": True,
        "edge_clearance": True,
        "accepted": True,
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_PLACEMENT,
        "report_type": RT_PLACEMENT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 6. SceneSurveyProxyReport (WF1089–1093) — MeshForge proxy provenance + toggle.
# =========================================================================== #
PROXY_REPORT_REQUIRED = (
    "proxy_report_id", "proxies", "proxies_before", "proxies_present_after",
    "disable_requested", "disabled_verified", "schema_version",
)
PROXY_REPORT_ALLOWED = PROXY_REPORT_REQUIRED + _META_FIELDS


def _proxy_entry_ok(p):
    if not isinstance(p, dict):
        return False
    pid = p.get("proxy_id")
    cat = p.get("category")
    osys = p.get("owner_system")
    oobj = p.get("owner_object")
    return (isinstance(pid, str) and bool(pid.strip())
            and cat in PROXY_CATEGORIES
            and isinstance(osys, str) and bool(osys.strip())
            and isinstance(oobj, str) and bool(oobj.strip()))


def validate_scene_survey_proxy_report(obj, strict=False):
    code = C.SCENE_SURVEY_PROXY_ENUMERATION_INVALID
    ch = RS.check_required(obj, PROXY_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, PROXY_REPORT_ALLOWED, code, strict)
    ch += _str(obj, "proxy_report_id", code, "pr::")
    ch += _int(obj, "proxies_before", code, "pr::", allow_zero=True)
    ch += _int(obj, "proxies_present_after", code, "pr::", allow_zero=True)
    ch += _bool(obj, "disable_requested", code, "pr::")
    ch += _bool(obj, "disabled_verified", code, "pr::")
    proxies = obj.get("proxies")
    is_list = isinstance(proxies, list)
    ch.append(("pr::proxies_is_list", is_list, "proxies must be a list", code))
    # honesty: every enumerated proxy must carry a bounded category + a real owner.
    if is_list:
        all_attributed = all(_proxy_entry_ok(p) for p in proxies)
        ch.append(("pr::proxies_attributed", all_attributed,
                   "every proxy must carry a bounded category and non-empty "
                   "owner_system/owner_object (unattributed proxy)",
                   C.SCENE_SURVEY_PROXY_UNATTRIBUTED))
    # honesty: a disabled_verified claim requires zero proxies present after.
    ch.append(("pr::disable_verified_absent",
               obj.get("disabled_verified") is not True or obj.get("proxies_present_after") == 0,
               "disabled_verified=True requires proxies_present_after == 0 "
               "(the CVar does not despawn; verify absence for real)",
               C.SCENE_SURVEY_PROXY_DISABLE_UNVERIFIED))
    ch += _schema_version(obj, RT_PROXY_REPORT, code, "pr::")
    return ch


def _example_scene_survey_proxy_report(**over):
    d = {
        "proxy_report_id": "proxy_report_fixture_alpha",
        "proxies": [
            {"proxy_id": "proxy_heart_0", "category": "Heart",
             "owner_system": "FixtureHeartSystem", "owner_object": "AFixtureHeart_0"},
            {"proxy_id": "proxy_interaction_radius_0", "category": "InteractionRadius",
             "owner_system": "FixtureHeartSystem", "owner_object": "AFixtureHeart_0"},
            {"proxy_id": "proxy_ritual_0", "category": "RitualPoint",
             "owner_system": "PCGSubsystem", "owner_object": "FixturePCGSubsystem"},
        ],
        "proxies_before": 3,
        "proxies_present_after": 0,
        "disable_requested": True,
        "disabled_verified": True,
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_PROXY_REPORT,
        "report_type": RT_PROXY_REPORT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 7. SceneSurveyReport (WF1062) — the machine-readable survey result.
# =========================================================================== #
REPORT_REQUIRED = (
    "report_id", "operation_id", "map_asset_path", "subject_id",
    "observed_anchor_location", "observed_anchor_object_path",
    "subject_resolved_by", "captures_requested",
    "camera_capture_ok", "actor_bounds_valid", "support_samples_total",
    "support_samples_valid", "unsupported_regions", "edge_regions",
    "proxy_owners", "proxies_disabled", "temporary_placements_grounded",
    "overlap_count", "player_clearance_valid", "cleanup_verified",
    "determinism_hash", "runtime_mode", "runtime_executed", "evidence_paths",
    "failure_codes", "status",
    # Whether this survey is eligible to back an ACCEPTANCE decision, and — when
    # it is not — which of the five identifiability components denied it. See
    # evaluate_acceptance_eligibility below; the claim is required (never absent)
    # because "makes no acceptance claim" and "claims ineligible" must not be the
    # same document.
    "acceptance_eligible", "acceptance_ineligibility_reason",
    "schema_version",
)
REPORT_ALLOWED = REPORT_REQUIRED + _META_FIELDS
# Mode-dependent observations: the key must be PRESENT, but a run that never
# executed has nothing to report as observed (sr::observed_anchor_present below
# is what makes an executed run carry it). acceptance_ineligibility_reason is
# nullable in the same sense: None is the ONLY legal value when eligible=True, and
# the key is still required so an absent reason cannot pass for "no problem".
# The five below are nullable for one reason only: NOTHING IN THE CURRENT PASS
# OBSERVES THEM. sample_survey_support returns a bare total with no per-sample
# records (scene_survey_far_side.py, sample_survey_support call site), and the
# proxy pass needs a -game boot this editor pass never performs. Before this, the
# contract demanded a non-null int/bool, so the ONLY way to satisfy it was to
# fabricate 0/False/True — the exact "populated field without an observation
# chain" the production standard forbids. Null here means "unknown", never
# "measured zero".
#
# Nullability is NOT a licence to skip measurement: sr::unobserved_forbids_pass
# below makes any null observation incompatible with status="pass", so the cost of
# not measuring is a report that cannot claim success. Once a real observation
# channel exists for one of these, REMOVE it from this tuple — leaving it nullable
# after it becomes observable would let a regression pass as an unknown.
_REPORT_NULLABLE = ("observed_anchor_location", "observed_anchor_object_path",
                    "acceptance_ineligibility_reason",
                    "support_samples_valid", "unsupported_regions", "edge_regions",
                    "proxy_owners", "proxies_disabled")

# The subset of _REPORT_NULLABLE that represents an OBSERVATION rather than a
# mode-dependent or by-construction-null field. A null in any of these means the
# measurement did not happen.
_UNOBSERVED_SENTINEL_FIELDS = ("support_samples_valid", "unsupported_regions",
                               "edge_regions", "proxy_owners", "proxies_disabled")


def validate_scene_survey_report(obj, strict=False):
    code = C.SCENE_SURVEY_REPORT_INVALID
    ch = RS.check_required(obj, REPORT_REQUIRED, code, nullable=_REPORT_NULLABLE)
    ch += RS.check_no_unknown(obj, REPORT_ALLOWED, code, strict)
    ch += _str(obj, "report_id", code, "sr::")
    ch += _str(obj, "operation_id", code, "sr::")
    ch += _str(obj, "map_asset_path", code, "sr::")
    # the caller-owned subject, echoed back so the caller can bind request<->result.
    ch += _str(obj, "subject_id", C.SCENE_SURVEY_SUBJECT_UNRESOLVED, "sr::")
    ch += _subset(obj, "captures_requested", CAMERA_KINDS,
                  C.SCENE_SURVEY_UNKNOWN_CAPTURE, "sr::", min_len=0)
    obs_loc = obj.get("observed_anchor_location") if isinstance(obj, dict) else None
    obs_path = obj.get("observed_anchor_object_path") if isinstance(obj, dict) else None
    ch.append(("sr::observed_anchor_location_shape",
               obs_loc is None or _finite_vec(obs_loc, 3),
               "observed_anchor_location must be a 3-element finite numeric vector "
               "or None (got {!r})".format(obs_loc), C.SCENE_SURVEY_SUBJECT_UNRESOLVED))
    ch.append(("sr::observed_anchor_object_path_shape",
               obs_path is None or isinstance(obs_path, str),
               "observed_anchor_object_path must be a string or None "
               "(got {!r})".format(obs_path), C.SCENE_SURVEY_SUBJECT_UNRESOLVED))
    # honesty: a run that actually executed must say where it actually anchored.
    ch.append(("sr::observed_anchor_present",
               obj.get("runtime_executed") is not True or _finite_vec(obs_loc, 3),
               "runtime_executed=True requires a finite vec3 observed_anchor_location "
               "(a survey that ran must report where it anchored)",
               C.SCENE_SURVEY_SUBJECT_UNRESOLVED))
    # honesty: a subject WorldForge resolved for itself is not a caller intent.
    ch.append(("sr::subject_resolved_by_caller",
               obj.get("subject_resolved_by") == "caller" if isinstance(obj, dict) else False,
               "subject_resolved_by must be 'caller' — WorldForge must never resolve "
               "the survey subject itself", C.SCENE_SURVEY_SUBJECT_INFERRED))
    # Nullability is driven by _REPORT_NULLABLE, never hand-listed here — a second
    # list would drift from the first and silently re-forbid an honest unknown.
    for f in ("camera_capture_ok", "actor_bounds_valid", "proxies_disabled",
              "player_clearance_valid", "cleanup_verified", "runtime_executed"):
        ch += _bool(obj, f, code, "sr::", nullable=(f in _REPORT_NULLABLE))
    for f in ("support_samples_total", "support_samples_valid", "unsupported_regions",
              "edge_regions", "proxy_owners", "temporary_placements_grounded",
              "overlap_count"):
        ch += _int(obj, f, code, "sr::", allow_zero=True,
                   nullable=(f in _REPORT_NULLABLE))
    ch += _str(obj, "determinism_hash", code, "sr::")
    ch += RS.check_enum(obj, "runtime_mode", RUNTIME_MODES, code, prefix="sr::")
    ch += RS.check_enum(obj, "status", SURVEY_STATUS, code, prefix="sr::")
    ch += _list_of_str(obj, "evidence_paths", code, "sr::")
    ch += _list_of_str(obj, "failure_codes", code, "sr::")
    # honesty: valid support samples can never exceed the total probed.
    tot = obj.get("support_samples_total")
    val = obj.get("support_samples_valid")
    if RS.is_number(tot) and RS.is_number(val):
        ch.append(("sr::valid_le_total", val <= tot,
                   "support_samples_valid must be <= support_samples_total "
                   "(got {} > {})".format(val, tot), code))
    # honesty: every declared failure code must be a real WF code.
    fcs = obj.get("failure_codes")
    fcs_ok = True
    if isinstance(fcs, list):
        valid_codes = _all_wf_codes()
        fcs_ok = all(isinstance(x, str) and x in valid_codes for x in fcs)
    ch.append(("sr::failure_codes_known", fcs_ok,
               "every failure code must be a registered WF code",
               C.SCENE_SURVEY_UNKNOWN_FAILURE_CODE))
    # honesty: a clean report (status pass, no failure codes) must carry positive
    # evidence — you cannot pass a survey that saw nothing.
    clean = obj.get("status") == "pass" and isinstance(fcs, list) and len(fcs) == 0
    # capture is opt-in: camera_capture_ok is only demanded of a survey that was
    # actually asked to render. This narrows an over-broad precondition — it does
    # not relax any of the other evidence the rail has always required.
    creq = obj.get("captures_requested")
    captures_asked = isinstance(creq, list) and len(creq) > 0
    positive = ((obj.get("camera_capture_ok") is True or not captures_asked)
                and obj.get("actor_bounds_valid") is True
                and RS.is_number(tot) and tot > 0
                and obj.get("cleanup_verified") is True
                and isinstance(obj.get("evidence_paths"), list)
                and len(obj.get("evidence_paths")) > 0)
    # honesty: an unknown is not a pass. A null in any observation field means the
    # measurement never happened, and a survey that did not measure cannot claim
    # success — this is what stops nullability (added so honest unknowns are
    # expressible) from becoming a cheaper route to green than measuring.
    _unobs = [f for f in _UNOBSERVED_SENTINEL_FIELDS if obj.get(f) is None] \
        if isinstance(obj, dict) else list(_UNOBSERVED_SENTINEL_FIELDS)
    ch.append(("sr::unobserved_forbids_pass",
               (obj.get("status") if isinstance(obj, dict) else None) != "pass"
               or not _unobs,
               "status='pass' is incompatible with unobserved field(s) {} — a null "
               "here means the measurement did not happen, and a survey that did not "
               "measure cannot claim success. Report 'blocked' instead."
               .format(_unobs),
               C.SCENE_SURVEY_EVIDENCE_MISSING))
    ch.append(("sr::clean_requires_evidence", (not clean) or positive,
               "a pass report with no failure codes must carry positive evidence "
               "(bounds, samples>0, cleanup, non-empty evidence_paths — plus cameras "
               "whenever captures_requested is non-empty)",
               C.SCENE_SURVEY_EVIDENCE_MISSING))
    # honesty: a live_survey_runtime claim requires a real run + real evidence.
    live = obj.get("runtime_mode") in LIVE_RUNTIME_MODES
    live_ok = (not live) or (obj.get("runtime_executed") is True
                             and isinstance(obj.get("evidence_paths"), list)
                             and len(obj.get("evidence_paths")) > 0)
    ch.append(("sr::live_mode_executed", live_ok,
               "live_survey_runtime requires runtime_executed=True and non-empty "
               "evidence (a simulation must not be labeled live)",
               C.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM))
    ch += _acceptance_claim_checks(obj)
    ch += _schema_version(obj, RT_SURVEY_REPORT, code, "sr::")
    return ch


def _acceptance_claim_checks(obj):
    """Report-LOCAL rails on the acceptance-eligibility claim.

    These are the rails a single report can carry on its own back. They cannot see
    the subject, so they cannot re-derive the verdict — that is the pair validator's
    job (sb::acceptance_* in validate_subject_binding, which calls
    evaluate_acceptance_eligibility). What they CAN do is reject a claim that
    contradicts the report's own observation vector, and every one of them is
    reachable:

      * eligible=True on a report with no observed actor object path. Under
        explicit_transform the subject carries no object path, so the report has
        none to observe either (ss::explicit_transform_complete /
        sb::object_path_match) — which makes this the report-local form of "an
        explicit_transform pair may never claim acceptance eligibility".
      * eligible=True with no observed transform, or with runtime_executed False:
        an eligibility claim over an observation that was never taken.
      * a reason carried alongside eligible=True (a document arguing with itself),
        an absent/blank reason alongside eligible=False (an ineligibility with no
        stated cause is unauditable), or a reason outside the closed enum.
    """
    code = C.SCENE_SURVEY_REPORT_INVALID
    unsupported = C.SCENE_SURVEY_EVIDENCE_UNSUPPORTED_CLAIM
    ch = _bool(obj, "acceptance_eligible", code, "sr::")
    eligible = obj.get("acceptance_eligible") is True if isinstance(obj, dict) else False
    reason = obj.get("acceptance_ineligibility_reason") if isinstance(obj, dict) else None
    obs_loc = obj.get("observed_anchor_location") if isinstance(obj, dict) else None
    obs_path = obj.get("observed_anchor_object_path") if isinstance(obj, dict) else None
    has_path = isinstance(obs_path, str) and bool(obs_path.strip())

    ch.append(("sr::acceptance_requires_observed_actor_path",
               (not eligible) or has_path,
               "acceptance_eligible=True requires a non-empty "
               "observed_anchor_object_path — only an actor_object_path survey "
               "observes the subject's anchor independently of the request; an "
               "explicit_transform survey copies it and can never be eligible",
               unsupported))
    ch.append(("sr::acceptance_requires_observed_transform",
               (not eligible) or _finite_vec(obs_loc, 3),
               "acceptance_eligible=True requires a finite vec3 "
               "observed_anchor_location (an eligibility claim over a transform "
               "that was never observed)", unsupported))
    ch.append(("sr::acceptance_requires_executed",
               (not eligible) or obj.get("runtime_executed") is True,
               "acceptance_eligible=True requires runtime_executed=True — a survey "
               "that never ran observed nothing to be identifiable from",
               unsupported))
    ch.append(("sr::acceptance_eligible_reason_null",
               (not eligible) or reason is None,
               "acceptance_eligible=True requires acceptance_ineligibility_reason="
               "None (got {!r}) — a report must not claim eligibility and a reason "
               "for ineligibility at once".format(reason), code))
    ineligible = (isinstance(obj, dict)
                  and obj.get("acceptance_eligible") is False)
    ch.append(("sr::acceptance_ineligible_reason_present",
               (not ineligible)
               or (isinstance(reason, str) and bool(reason.strip())),
               "acceptance_eligible=False requires a non-empty "
               "acceptance_ineligibility_reason (got {!r}) — an ineligibility with "
               "no stated cause cannot be audited or lifted".format(reason), code))
    ch.append(("sr::acceptance_reason_known",
               reason is None or reason in ACCEPTANCE_INELIGIBILITY_REASONS,
               "acceptance_ineligibility_reason must be None or one of {} (got "
               "{!r}) — the reason is a closed enum, not free text".format(
                   list(ACCEPTANCE_INELIGIBILITY_REASONS), reason), code))
    return ch


def _example_scene_survey_report(**over):
    d = {
        "report_id": "scene_survey_report_fixture_alpha_run1",
        "operation_id": "op_v2_6_scene_survey_0001",
        "map_asset_path": "/Game/Fixture/Lvl_Fixture",
        "subject_id": "subject_fixture_alpha",
        "observed_anchor_location": [1200.0, -450.0, 92.5],
        "observed_anchor_object_path": None,
        "subject_resolved_by": "caller",
        "captures_requested": list(CAMERA_KINDS),
        "camera_capture_ok": True,
        "actor_bounds_valid": True,
        "support_samples_total": 158,
        "support_samples_valid": 120,
        "unsupported_regions": 20,
        "edge_regions": 10,
        "proxy_owners": 3,
        "proxies_disabled": True,
        "temporary_placements_grounded": 3,
        "overlap_count": 0,
        "player_clearance_valid": True,
        "cleanup_verified": True,
        "determinism_hash": "sha256:survey_run1_deterministic",
        "runtime_mode": "live_survey_runtime",
        "runtime_executed": True,
        "evidence_paths": [
            "procedural/reports/scene_survey/captures/cam_gameplay_fixture.png",
            "procedural/reports/scene_survey/support_map_fixture_alpha.json",
        ],
        "failure_codes": [],
        "status": "pass",
        # The fixture subject is explicit_transform, so this otherwise-clean survey
        # is honestly INELIGIBLE for acceptance: its anchor was copied from the
        # request, never observed. A valid survey that cannot back an acceptance
        # decision is exactly the state the invariant exists to make sayable.
        "acceptance_eligible": False,
        "acceptance_ineligibility_reason": EV.REASON_ANCHOR_NOT_OBSERVABLE,
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_SURVEY_REPORT,
        "report_type": RT_SURVEY_REPORT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 8. SceneSurveyEvidenceIndex (WF1063) — the auditable capture/evidence matrix.
# =========================================================================== #
INDEX_REQUIRED = (
    "index_id", "integrity_result", "captures_expected", "captures_seen",
    "evidence_entries", "schema_version",
)
INDEX_ALLOWED = INDEX_REQUIRED + _META_FIELDS


def validate_scene_survey_evidence_index(obj, strict=False):
    code = C.SCENE_SURVEY_EVIDENCE_INDEX_INVALID
    ch = RS.check_required(obj, INDEX_REQUIRED, code)
    ch += RS.check_no_unknown(obj, INDEX_ALLOWED, code, strict)
    ch += _str(obj, "index_id", code, "ei::")
    ch += RS.check_enum(obj, "integrity_result", INTEGRITY_RESULTS, code, prefix="ei::")
    ch += _int(obj, "captures_expected", code, "ei::", allow_zero=False)
    ch += _int(obj, "captures_seen", code, "ei::", allow_zero=True)
    ch += _list_of_str(obj, "evidence_entries", code, "ei::")
    # honesty: an integrity "pass" requires the full capture matrix + real entries.
    passing = obj.get("integrity_result") == "pass"
    seen = obj.get("captures_seen")
    exp = obj.get("captures_expected")
    entries = obj.get("evidence_entries")
    full = (RS.is_number(seen) and RS.is_number(exp) and seen == exp
            and isinstance(entries, list) and len(entries) > 0)
    ch.append(("ei::pass_requires_full_matrix", (not passing) or full,
               "integrity_result=pass requires captures_seen == captures_expected "
               "and non-empty evidence_entries (partial matrix claimed complete)",
               code))
    ch += _schema_version(obj, RT_EVIDENCE_INDEX, code, "ei::")
    return ch


def _example_scene_survey_evidence_index(**over):
    d = {
        "index_id": "scene_survey_evidence_index_fixture_alpha",
        "integrity_result": "pass",
        "captures_expected": 3,
        "captures_seen": 3,
        "evidence_entries": [
            "procedural/reports/scene_survey/captures/cam_gameplay_fixture.png",
            "procedural/reports/scene_survey/captures/cam_elevated_oblique_fixture.png",
            "procedural/reports/scene_survey/captures/cam_top_down_fixture.png",
        ],
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_EVIDENCE_INDEX,
        "report_type": RT_EVIDENCE_INDEX,
    }
    d.update(over)
    return d


# =========================================================================== #
# 9. subject <-> report PAIR invariants (WF1107) — not visible from one object.
# =========================================================================== #
def evaluate_acceptance_eligibility(subject, report):
    """THE definition of acceptance eligibility. One function, no second copy.

        acceptance_eligible = anchor_mode == "actor_object_path"
                              AND observed_world_identity_valid
                              AND observed_actor_identity_valid
                              AND observed_actor_transform_valid
                              AND survey_bound_to_observed_actor

        explicit_transform -> survey_valid MAY be true, but
                              acceptance_eligible is ALWAYS false, with
                              reason "independent_subject_anchor_not_observable".

    WHY THE MODE DECIDES THIS — IDENTIFIABILITY, NOT POLICY
    -------------------------------------------------------
    A survey's observation vector about its subject is (observed world package,
    resolved actor object path, observed actor transform).

    Under ``actor_object_path`` all three coordinates are MEASURED on the far side
    and vary independently of the request: the editor may open a different world,
    resolve a different actor, or report a transform the caller never mentioned,
    and each disagreement is visible from the pair. Subject identity is therefore
    identifiable from the observation, and a wrong subject is detectable.

    Under ``explicit_transform`` only the world is independently observed. The
    anchor components are COPIED from the caller's input — the far side is handed
    a location and hands the same location back — so the observation map is
    rank-deficient with respect to subject identity. Comparing observed to
    requested compares a value to a copy of itself, and NO comparison over such a
    vector can distinguish correct subject coordinates from arbitrary
    caller-supplied ones. The survey can still be VALID (its samples, bounds and
    cleanup are real measurements); what it can never be is acceptance-eligible,
    because acceptance is a claim about the SUBJECT and the subject's coordinates
    were never observed.

    This is why the rule must not be "simplified" into a mode allow-list: a later
    reader seeing two enum values with one blessed will helpfully bless the other.

    Args:
        subject: a SceneSurveySubject dict (caller-resolved).
        report:  a SceneSurveyReport dict.
    Both are plain dicts on purpose: this predicate must be callable by the
    assembler, the validator and any caller-side tool with nothing but the two
    JSON documents in hand.

    Returns a structured verdict (JSON-portable, no objects):
        {"eligible": bool,
         "reason": str | None,              # a member of ACCEPTANCE_INELIGIBILITY_REASONS
         "components": {name: bool, ...},   # per-component verdicts
         "failed_components": [name, ...],  # in precedence order
         "anchor_mode": str | None,
         "sufficient": bool,                # False only for a malformed bundle
         "detail": str}
    A malformed input is never a confident answer: ``sufficient`` goes False and
    ``eligible`` is False with the first-component reason, i.e. fail-closed.
    """
    raw = EV.acceptance_raw(subject, report)
    enough, value, inputs, detail = EV.derive("acceptance_eligible", raw)
    if not enough:
        return {"eligible": False,
                "reason": EV.ACCEPTANCE_INELIGIBILITY_REASONS[0],
                "components": {c: False for c in EV.ACCEPTANCE_COMPONENTS},
                "failed_components": list(EV.ACCEPTANCE_COMPONENTS),
                "anchor_mode": None,
                "sufficient": False,
                "detail": detail}
    return {"eligible": bool(value),
            "reason": inputs["reason"],
            "components": dict(inputs["components"]),
            "failed_components": list(inputs["failed_components"]),
            "anchor_mode": inputs["anchor_mode"],
            "sufficient": True,
            "detail": detail}


def acceptance_eligibility_record(subject, report, stage="assemble",
                                  collector="assembler", refs=None):
    """The same verdict as an EVIDENCE RECORD, so it is never a free-floating bool.

    Carries its classification (derived_from_observed), the derivation name, the
    raw records it was computed from, and the per-component verdicts under
    ``inputs``. A validator can re-derive it with
    ``scene_survey_evidence.rederive_and_compare("acceptance_eligible", rec, raw)``
    where ``raw`` is rebuilt independently from the same pair.
    """
    raw = EV.acceptance_raw(subject, report)
    if refs is None:
        refs = ["binding#requested", "binding#observed", "binding#echoed"]
    return EV.derived_record("acceptance_eligible", raw, stage=stage,
                             collector=collector, refs=refs)


def validate_subject_binding(subject, report, strict=False, tolerance_cm=1.0):
    """Return a list of (name, ok, detail, code) subject<->report pair checks.

    Mirrors the request<->response pair-validator precedent in
    tools/bridge/probe.py:105 (validate_bridge_response), which owns WF1026/WF1030
    for exactly this reason: a report that surveyed a DIFFERENT subject than the one
    it was handed is shaped-perfectly on both sides and only the pair can see it.

    ``strict`` is accepted for signature symmetry with the single-object validators;
    every pair rail here is unconditional, so there are no strict-only pair checks
    today. Each object's own strict-mode checks belong to its own validator.
    """
    code = C.SCENE_SURVEY_SUBJECT_MISMATCH
    s = subject if isinstance(subject, dict) else {}
    r = report if isinstance(report, dict) else {}
    ch = []
    # continuity: the report must echo the subject_id it was handed (WF1107).
    sid = s.get("subject_id")
    ch.append(("sb::subject_id_match",
               isinstance(sid, str) and bool(sid.strip()) and r.get("subject_id") == sid,
               "report subject_id {!r} != subject subject_id {!r}".format(
                   r.get("subject_id"), sid), code))
    # continuity: surveying the right subject in the wrong map is still the wrong survey.
    smap = s.get("map_asset_path")
    ch.append(("sb::map_match",
               isinstance(smap, str) and bool(smap.strip()) and r.get("map_asset_path") == smap,
               "report map_asset_path {!r} != subject map_asset_path {!r}".format(
                   r.get("map_asset_path"), smap), code))
    mode = s.get("anchor_mode")
    # honesty: an explicit_transform subject must have been anchored where the caller
    # said, within tolerance. Drift beyond tolerance means WorldForge moved the survey.
    want = s.get("anchor_location")
    got = r.get("observed_anchor_location")
    if _finite_vec(want, 3) and _finite_vec(got, 3):
        dist = math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(want, got)))
    else:
        dist = None
    ch.append(("sb::transform_within_tolerance",
               mode != "explicit_transform"
               or (dist is not None and dist <= tolerance_cm),
               "observed_anchor_location {!r} is {} from subject anchor_location {!r} "
               "(tolerance {}cm)".format(got, "not comparable" if dist is None
                                         else "{:.4f}cm".format(dist), want, tolerance_cm),
               code))
    # honesty: an actor_object_path subject must have been anchored on that exact object.
    wpath = s.get("anchor_object_path")
    ch.append(("sb::object_path_match",
               mode != "actor_object_path"
               or (isinstance(wpath, str) and bool(wpath.strip())
                   and r.get("observed_anchor_object_path") == wpath),
               "observed_anchor_object_path {!r} != subject anchor_object_path {!r}".format(
                   r.get("observed_anchor_object_path"), wpath), code))
    # ownership: neither side may claim a resolver other than the caller (WF1108).
    ch.append(("sb::resolver_not_worldforge",
               r.get("subject_resolved_by") == "caller" and s.get("resolved_by") == "caller",
               "both sides must declare resolved_by='caller' (subject={!r}, report={!r}) "
               "— WorldForge must never resolve the survey subject itself".format(
                   s.get("resolved_by"), r.get("subject_resolved_by")),
               C.SCENE_SURVEY_SUBJECT_INFERRED))
    # acceptance eligibility: re-derived from the pair, never read off the claim.
    # DIRECTIONAL, and deliberately so. Only the OVER-claim is rejected here — a
    # report claiming eligibility the observation vector does not support. The
    # symmetric rail (claimed False while the evidence supports True) is NOT
    # installed: under-claiming cannot cause a false accept, so it fails safe, and
    # installing exact equality today would red an existing positive control that
    # this lane does not own (scene_survey_fuzz.py:203-215 builds a matched
    # actor_object_path pair out of the default report example, whose acceptance
    # claim is the explicit_transform one). The correct end state IS exact
    # equality, once that fixture states its own acceptance claim.
    verdict = evaluate_acceptance_eligibility(s, r)
    claimed = r.get("acceptance_eligible")
    ch.append(("sb::acceptance_not_overclaimed",
               claimed is not True or verdict["eligible"] is True,
               "report claims acceptance_eligible=True but the subject<->report "
               "pair re-derives ineligible ({}): failed component(s) {}".format(
                   verdict["reason"], verdict["failed_components"]),
               C.SCENE_SURVEY_EVIDENCE_UNSUPPORTED_CLAIM))
    # An ineligible report must state the reason the evidence actually gives. A
    # true verdict with a false cause sends the caller to fix the wrong thing —
    # e.g. an explicit_transform survey blaming world identity would have someone
    # chasing a map bug that does not exist. Scoped to pairs the re-derivation also
    # finds ineligible, so it never fires on a conservative under-claim.
    ch.append(("sb::acceptance_reason_matches_evidence",
               claimed is not False or verdict["eligible"] is True
               or r.get("acceptance_ineligibility_reason") == verdict["reason"],
               "report states acceptance_ineligibility_reason={!r} but the pair "
               "re-derives {!r} (failed component(s) {})".format(
                   r.get("acceptance_ineligibility_reason"), verdict["reason"],
                   verdict["failed_components"]),
               C.SCENE_SURVEY_EVIDENCE_REDERIVATION_MISMATCH))
    return ch


# --------------------------------------------------------------------------- #
# Registry tail — CONTRACTS / CONTRACT_GROUPS / KNOWN_BAD_OWNING_CODE / codes.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "SceneSurveySubject": (
        validate_scene_survey_subject, _example_scene_survey_subject,
        # an empty subject_id -> the caller never resolved the subject (WF1106).
        lambda: _example_scene_survey_subject(subject_id="")),
    "SceneSurveyProfile": (
        validate_scene_survey_profile, _example_scene_survey_profile,
        # unknown survey mode -> WF1064.
        lambda: _example_scene_survey_profile(survey_mode="telepathy_survey")),
    "SceneSurveyCameraCapture": (
        validate_scene_survey_camera_capture, _example_scene_survey_camera_capture,
        # captured=True but no image hash -> capture overclaim (WF1070).
        lambda: _example_scene_survey_camera_capture(image_hash="")),
    "SceneSurveySupportMap": (
        validate_scene_survey_support_map, _example_scene_survey_support_map,
        # coverage_complete over zero probed samples -> coverage overclaim (WF1078).
        lambda: _example_scene_survey_support_map(
            samples_total=0, valid_support=0, unsupported=0, edge=0, blocked=0,
            trace_error=0, unknown=0, coverage_complete=True)),
    "SceneSurveyTemporaryPlacement": (
        validate_scene_survey_temporary_placement, _example_scene_survey_temporary_placement,
        # accepted marker that is not grounded -> not grounded (WF1083).
        lambda: _example_scene_survey_temporary_placement(grounded=False)),
    "SceneSurveyProxyReport": (
        validate_scene_survey_proxy_report, _example_scene_survey_proxy_report,
        # a proxy with no owner -> unattributed proxy (WF1090).
        lambda: _example_scene_survey_proxy_report(proxies=[
            {"proxy_id": "heart", "category": "Heart",
             "owner_system": "", "owner_object": ""}])),
    "SceneSurveyReport": (
        validate_scene_survey_report, _example_scene_survey_report,
        # more valid samples than total -> report invalid (WF1062).
        lambda: _example_scene_survey_report(support_samples_valid=200)),
    "SceneSurveyEvidenceIndex": (
        validate_scene_survey_evidence_index, _example_scene_survey_evidence_index,
        # integrity pass but only 2/3 captures seen -> index invalid (WF1063).
        lambda: _example_scene_survey_evidence_index(captures_seen=2)),
}

CONTRACT_GROUPS = {
    "subject": ("SceneSurveySubject",),
    "profile": ("SceneSurveyProfile",),
    "capture": ("SceneSurveyCameraCapture",),
    "spatial": ("SceneSurveySupportMap", "SceneSurveyTemporaryPlacement"),
    "proxy": ("SceneSurveyProxyReport",),
    "report_index": ("SceneSurveyReport", "SceneSurveyEvidenceIndex"),
}

KNOWN_BAD_OWNING_CODE = {
    "SceneSurveySubject": C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
    "SceneSurveyProfile": C.SCENE_SURVEY_UNKNOWN_MODE,
    "SceneSurveyCameraCapture": C.SCENE_SURVEY_CAMERA_CAPTURE_OVERCLAIM,
    "SceneSurveySupportMap": C.SCENE_SURVEY_SUPPORT_COVERAGE_OVERCLAIM,
    "SceneSurveyTemporaryPlacement": C.SCENE_SURVEY_PLACEMENT_NOT_GROUNDED,
    "SceneSurveyProxyReport": C.SCENE_SURVEY_PROXY_UNATTRIBUTED,
    "SceneSurveyReport": C.SCENE_SURVEY_REPORT_INVALID,
    "SceneSurveyEvidenceIndex": C.SCENE_SURVEY_EVIDENCE_INDEX_INVALID,
}


def _all_wf_codes():
    """The set of every registered WF code string (for report failure-code checks)."""
    return {v for k, v in vars(C).items()
            if not k.startswith("_") and isinstance(v, str) and v.startswith("WF")}


# The set of failure codes this milestone owns (WF1061–1130). Uses a 4-digit slice.
# Widened from 1109 to the full reserved band when the runtime evidence model
# landed: codes defined outside this slice pass every gate but are silently absent
# from the exported caller manifest, so the caller lane would never learn they
# exist. Silent invisibility is the likelier bug here than a red gate.
SCENE_SURVEY_CODES = tuple(
    v for k, v in vars(C).items()
    if not k.startswith("_") and isinstance(v, str)
    and 1061 <= (int(v[2:6]) if v[2:6].isdigit() else -1) <= 1130
)


if __name__ == "__main__":
    # Lightweight self-dogfood: valid examples pass clean; known-bads rejected for
    # their owning code; groups partition; band non-empty. The real gate is
    # validate_scene_survey_contracts.py — this is a fast local smoke.
    ok = True
    seen_in_groups = [n for g in CONTRACT_GROUPS.values() for n in g]
    if sorted(seen_in_groups) != sorted(CONTRACTS):
        print("PARTITION FAIL: groups != contracts"); ok = False
    if len(seen_in_groups) != len(set(seen_in_groups)):
        print("PARTITION FAIL: overlap in groups"); ok = False
    for name, (validate, good, bad) in CONTRACTS.items():
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        if gfails:
            print("DOGFOOD FAIL {}: valid example has {} failing check(s): {}".format(
                name, len(gfails), [c[0] for c in gfails])); ok = False
        bfails = [c for c in validate(bad(), strict=True) if not c[1]]
        codes = {c[3] for c in bfails}
        owning = KNOWN_BAD_OWNING_CODE[name]
        if not bfails:
            print("DOGFOOD FAIL {}: known-bad accepted (fake green)".format(name)); ok = False
        elif owning not in codes:
            print("DOGFOOD FAIL {}: known-bad not rejected for owning code {} (got {})".format(
                name, owning, sorted(codes))); ok = False
    # pair validator: the matched subject<->report pair is clean, and a report that
    # surveyed a different subject is rejected FOR the pair's owning code (WF1107).
    _pair_good = [c for c in validate_subject_binding(
        _example_scene_survey_subject(), _example_scene_survey_report(),
        strict=True) if not c[1]]
    if _pair_good:
        print("DOGFOOD FAIL SubjectBinding: matched pair has {} failing check(s): {}".format(
            len(_pair_good), [c[0] for c in _pair_good])); ok = False
    _pair_bad = [c for c in validate_subject_binding(
        _example_scene_survey_subject(),
        _example_scene_survey_report(subject_id="subject_fixture_beta"),
        strict=True) if not c[1]]
    if C.SCENE_SURVEY_SUBJECT_MISMATCH not in {c[3] for c in _pair_bad}:
        print("DOGFOOD FAIL SubjectBinding: mismatched pair not rejected for {} (got {})".format(
            C.SCENE_SURVEY_SUBJECT_MISMATCH, sorted({c[3] for c in _pair_bad}))); ok = False
    # ---- acceptance eligibility: the ONE definition, positive AND negative ---- #
    # Vocabulary agreement: the evidence model holds the strings, this module holds
    # the enums they must be members of. Two copies that drift silently is the
    # failure this pair of checks exists to prevent.
    if EV.CALLER_RESOLVER not in SUBJECT_RESOLVERS:
        print("VOCAB FAIL: EV.CALLER_RESOLVER {!r} not in SUBJECT_RESOLVERS {}".format(
            EV.CALLER_RESOLVER, SUBJECT_RESOLVERS)); ok = False
    if EV.OBSERVABLE_ANCHOR_MODE not in ANCHOR_MODES:
        print("VOCAB FAIL: EV.OBSERVABLE_ANCHOR_MODE {!r} not in ANCHOR_MODES {}".format(
            EV.OBSERVABLE_ANCHOR_MODE, ANCHOR_MODES)); ok = False

    _PATH_A = ("/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel."
               "Fixture_Subject_0")

    def _path_subject(**over):
        return _example_scene_survey_subject(
            subject_kind="actor", anchor_mode="actor_object_path",
            anchor_location=None, anchor_object_path=_PATH_A, **over)

    def _eligible_report(**over):
        base = {"observed_anchor_object_path": _PATH_A, "acceptance_eligible": True,
                "acceptance_ineligibility_reason": None}
        base.update(over)
        return _example_scene_survey_report(**base)

    def _rails(subject, report):
        """Failing rail names across BOTH the report contract and the pair."""
        return ([c[0] for c in validate_scene_survey_report(report, strict=True)
                 if not c[1]]
                + [c[0] for c in validate_subject_binding(subject, report, strict=True)
                   if not c[1]])

    def _expect_clean(label, subject, report):
        bad = _rails(subject, report)
        if bad:
            print("ACCEPTANCE FAIL {}: expected clean, got {}".format(label, bad))
            return False
        return True

    def _expect_rail(label, subject, report, rail):
        bad = _rails(subject, report)
        if rail not in bad:
            print("ACCEPTANCE FAIL {}: rail {!r} did not fire (got {})".format(
                label, rail, bad))
            return False
        return True

    # POSITIVE 1 — the fixture explicit_transform pair: valid survey, honestly
    # ineligible, with the identifiability reason. Must be clean on both sides.
    _v = evaluate_acceptance_eligibility(_example_scene_survey_subject(),
                                         _example_scene_survey_report())
    if _v["eligible"] is not False or _v["reason"] != EV.REASON_ANCHOR_NOT_OBSERVABLE:
        print("ACCEPTANCE FAIL explicit_transform verdict: {}".format(_v)); ok = False
    if not _expect_clean("explicit_transform_pair", _example_scene_survey_subject(),
                         _example_scene_survey_report()):
        ok = False
    # POSITIVE 2 — a fully observable actor_object_path pair IS eligible, and a
    # report claiming so with a null reason is clean. Without this the negatives
    # below would pass trivially on a predicate that always says "ineligible".
    _v = evaluate_acceptance_eligibility(_path_subject(), _eligible_report())
    if _v["eligible"] is not True or _v["reason"] is not None:
        print("ACCEPTANCE FAIL actor_object_path verdict: {}".format(_v)); ok = False
    if not _expect_clean("actor_object_path_pair", _path_subject(), _eligible_report()):
        ok = False
    # POSITIVE 3 — the verdict is an evidence record, not a bare boolean.
    _rec = acceptance_eligibility_record(_path_subject(), _eligible_report())
    if (_rec.get("classification") != EV.DERIVED or _rec.get("value") is not True
            or not _rec.get("raw_refs")):
        print("ACCEPTANCE FAIL record shape: {}".format(_rec)); ok = False

    # NEGATIVE — one per new rail. Each mutates a single field of an otherwise
    # clean artifact, so the named rail is the reason it fails.
    for _label, _subject, _report, _rail in (
            # the locked rule: an explicit_transform pair may never claim eligible.
            ("explicit_transform_claims_eligible",
             _example_scene_survey_subject(),
             _example_scene_survey_report(acceptance_eligible=True,
                                          acceptance_ineligibility_reason=None),
             "sr::acceptance_requires_observed_actor_path"),
            # ...and the pair validator catches it independently of the report rail.
            ("explicit_transform_claims_eligible_pair",
             _example_scene_survey_subject(),
             _example_scene_survey_report(acceptance_eligible=True,
                                          acceptance_ineligibility_reason=None),
             "sb::acceptance_not_overclaimed"),
            # eligible with a reason: a document arguing with itself.
            ("eligible_with_reason", _path_subject(),
             _eligible_report(
                 acceptance_ineligibility_reason=EV.REASON_ANCHOR_NOT_OBSERVABLE),
             "sr::acceptance_eligible_reason_null"),
            # ineligible with no stated cause, both shapes of "no cause".
            ("ineligible_null_reason", _example_scene_survey_subject(),
             _example_scene_survey_report(acceptance_ineligibility_reason=None),
             "sr::acceptance_ineligible_reason_present"),
            ("ineligible_blank_reason", _example_scene_survey_subject(),
             _example_scene_survey_report(acceptance_ineligibility_reason="   "),
             "sr::acceptance_ineligible_reason_present"),
            # a reason outside the closed enum.
            ("reason_off_enum", _example_scene_survey_subject(),
             _example_scene_survey_report(
                 acceptance_ineligibility_reason="the vibes were off"),
             "sr::acceptance_reason_known"),
            # a true verdict with a false cause: ineligible, wrong reason.
            ("wrong_reason", _example_scene_survey_subject(),
             _example_scene_survey_report(
                 acceptance_ineligibility_reason=EV.REASON_WORLD_IDENTITY_UNVERIFIED),
             "sb::acceptance_reason_matches_evidence"),
            # eligibility claimed over observations that were never taken.
            ("eligible_without_transform", _path_subject(),
             _eligible_report(observed_anchor_location=None),
             "sr::acceptance_requires_observed_transform"),
            ("eligible_without_run", _path_subject(),
             _eligible_report(runtime_executed=False),
             "sr::acceptance_requires_executed"),
            # eligibility claimed on the wrong world / wrong actor: the report is
            # locally consistent, and only the PAIR can see it.
            ("eligible_wrong_world", _path_subject(),
             _eligible_report(map_asset_path="/Game/Fixture/Lvl_Other"),
             "sb::acceptance_not_overclaimed"),
            ("eligible_wrong_actor", _path_subject(),
             _eligible_report(observed_anchor_object_path=_PATH_A + "_OTHER"),
             "sb::acceptance_not_overclaimed"),
            # a non-boolean claim is not a claim.
            ("eligible_not_a_bool", _example_scene_survey_subject(),
             _example_scene_survey_report(acceptance_eligible="yes",
                                          acceptance_ineligibility_reason=None),
             "sr::acceptance_eligible_bool")):
        if not _expect_rail(_label, _subject, _report, _rail):
            ok = False
    # A report that drops the acceptance claim entirely must be rejected, not
    # treated as "no claim, therefore fine".
    _dropped = _example_scene_survey_report()
    del _dropped["acceptance_eligible"]
    if "field::acceptance_eligible" not in [
            c[0] for c in validate_scene_survey_report(_dropped, strict=True)
            if not c[1]]:
        print("ACCEPTANCE FAIL dropped_claim: an absent acceptance_eligible was "
              "accepted"); ok = False
    _dropped = _example_scene_survey_report()
    del _dropped["acceptance_ineligibility_reason"]
    if "field::acceptance_ineligibility_reason" not in [
            c[0] for c in validate_scene_survey_report(_dropped, strict=True)
            if not c[1]]:
        print("ACCEPTANCE FAIL dropped_reason: an absent reason key was accepted")
        ok = False

    if not SCENE_SURVEY_CODES:
        print("BAND FAIL: SCENE_SURVEY_CODES is empty"); ok = False
    print("SELF-DOGFOOD: {} ({} contracts, {} owned codes)".format(
        "PASS" if ok else "FAIL", len(CONTRACTS), len(SCENE_SURVEY_CODES)))
    sys.exit(0 if ok else 1)
