#!/usr/bin/env python3
"""SceneSurveyForge (v2.6) contract spine — schema-only, no I/O.

Design mirrors tactical_contracts.py / streaming_contracts.py exactly: a bounded
taxonomy (one source of truth), small local scalar helpers wrapping runtime_schema
primitives, and a per-record triplet (validate_X, _example_X) plus a registry tail
(CONTRACTS / CONTRACT_GROUPS / KNOWN_BAD_OWNING_CODE / SCENE_SURVEY_CODES).

The honesty invariants are the point, not the type checks. v2.6 is the first
READ-ONLY spatial survey of a real external UE 5.8 target (Gloamstead). A record is
rejected when it is shaped-but-dishonest: a camera "ok" with no image hash; a
non-orthographic top-down passed off as true top-down; a support sample counted
valid while classified unknown/trace_error (fail-closed); a coverage=complete claim
over zero probed samples; a temporary marker claimed grounded while floating; a
placement accepted despite an overlap / clearance / edge violation; a placement
coordinate not backed by a trace (guessed); a proxy with no owner/category binding;
a proxies-disabled claim with proxies still present; a cleanup claim whose final
state != initial; a clean report with no evidence; a simulated result mislabeled as
live runtime. Owning codes live in the WF1061–1105 band.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_schema as RS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402

# --------------------------------------------------------------------------- #
# schema_version / report_type dotted namespaces (wf.scene_survey.<type>.v1)
# --------------------------------------------------------------------------- #
RT_PROFILE = "wf.scene_survey.survey_profile.v1"
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
# What the survey may anchor its capture frame + sample region on.
SURVEY_ANCHORS = ("player", "heart")
# MeshForge proxy categories (Gloamstead-owned; PathCue/CorruptionFeedback exist
# in the enum but are not built by the current adapter — still bounded/known).
PROXY_CATEGORIES = ("Heart", "RitualPoint", "LanternRestore", "InteractionRadius",
                    "NightFeedback", "PathCue", "CorruptionFeedback")
# Honest runtime-mode labels: a deterministic simulation must NOT be labeled a live
# survey. Both acceptable if labeled honestly (mirrors v2.4 §12).
RUNTIME_MODES = ("deterministic_survey_simulation", "live_survey_runtime")
LIVE_RUNTIME_MODES = ("live_survey_runtime",)
# Report / evidence-index verdicts.
SURVEY_STATUS = ("pass", "fail", "blocked")
INTEGRITY_RESULTS = ("pass", "fail", "blocked")

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


def _bool(obj, field, code, prefix):
    v = obj.get(field) if isinstance(obj, dict) else None
    return [("{}{}_bool".format(prefix, field), isinstance(v, bool),
             "{} must be an explicit boolean (got {!r})".format(field, v), code)]


def _int(obj, field, code, prefix, allow_zero=True):
    ch = RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)
    v = obj.get(field) if isinstance(obj, dict) else None
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


_META_FIELDS = ("meta", "report_type", "created_by", "created_at", "notes", "display_key")


# =========================================================================== #
# 1. SceneSurveyProfile (WF1061) — the bounded survey configuration.
# =========================================================================== #
PROFILE_REQUIRED = (
    "profile_id", "survey_mode", "anchor", "captures", "sample_radius_cm",
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
    ch += RS.check_enum(obj, "anchor", SURVEY_ANCHORS, code, prefix="sp::")
    ch += _subset(obj, "captures", CAMERA_KINDS, C.SCENE_SURVEY_UNKNOWN_CAPTURE, "sp::", min_len=1)
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
        "profile_id": "survey_profile_gloam_courtyard_readonly",
        "survey_mode": "read_only_survey",
        "anchor": "player",
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
# 2. SceneSurveyCameraCapture (WF1068–1071) — one deterministic fixed camera.
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
        "camera_id": "cam_gameplay_player",
        "capture_kind": "gameplay",
        "projection": "perspective",
        "location": [1200.0, -450.0, 260.0],
        "rotation": [0.0, -12.0, 90.0],
        "fov": 90.0,
        "aspect_ratio": 1.7778,
        "anchor_actor": "BP_ThirdPersonCharacter_C_0",
        "captured": True,
        "image_path": "procedural/reports/scene_survey/captures/cam_gameplay_player.png",
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
# 3. SceneSurveySupportMap (WF1075–1081) — downward-trace support classification.
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
    ch += RS.check_enum(obj, "anchor", SURVEY_ANCHORS, code, prefix="sm::")
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
        "support_map_id": "support_map_gloam_courtyard_player",
        "anchor": "player",
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
# 4. SceneSurveyTemporaryPlacement (WF1082–1088) — a runtime-only marker candidate.
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
# 5. SceneSurveyProxyReport (WF1089–1093) — MeshForge proxy provenance + toggle.
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
        "proxy_report_id": "proxy_report_gloam_courtyard",
        "proxies": [
            {"proxy_id": "heart", "category": "Heart",
             "owner_system": "VeilHeart", "owner_object": "AVeilHeart_0"},
            {"proxy_id": "interaction_radius_heart", "category": "InteractionRadius",
             "owner_system": "VeilHeart", "owner_object": "AVeilHeart_0"},
            {"proxy_id": "ritual_0", "category": "RitualPoint",
             "owner_system": "PCGSubsystem", "owner_object": "GloamsteadPCGSubsystem"},
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
# 6. SceneSurveyReport (WF1062) — the machine-readable survey result.
# =========================================================================== #
REPORT_REQUIRED = (
    "report_id", "operation_id", "map_asset_path", "anchor",
    "camera_capture_ok", "actor_bounds_valid", "support_samples_total",
    "support_samples_valid", "unsupported_regions", "edge_regions",
    "proxy_owners", "proxies_disabled", "temporary_placements_grounded",
    "overlap_count", "player_clearance_valid", "cleanup_verified",
    "determinism_hash", "runtime_mode", "runtime_executed", "evidence_paths",
    "failure_codes", "status", "schema_version",
)
REPORT_ALLOWED = REPORT_REQUIRED + _META_FIELDS


def validate_scene_survey_report(obj, strict=False):
    code = C.SCENE_SURVEY_REPORT_INVALID
    ch = RS.check_required(obj, REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, REPORT_ALLOWED, code, strict)
    ch += _str(obj, "report_id", code, "sr::")
    ch += _str(obj, "operation_id", code, "sr::")
    ch += _str(obj, "map_asset_path", code, "sr::")
    ch += RS.check_enum(obj, "anchor", SURVEY_ANCHORS, code, prefix="sr::")
    for f in ("camera_capture_ok", "actor_bounds_valid", "proxies_disabled",
              "player_clearance_valid", "cleanup_verified", "runtime_executed"):
        ch += _bool(obj, f, code, "sr::")
    for f in ("support_samples_total", "support_samples_valid", "unsupported_regions",
              "edge_regions", "proxy_owners", "temporary_placements_grounded",
              "overlap_count"):
        ch += _int(obj, f, code, "sr::", allow_zero=True)
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
    positive = (obj.get("camera_capture_ok") is True
                and obj.get("actor_bounds_valid") is True
                and RS.is_number(tot) and tot > 0
                and obj.get("cleanup_verified") is True
                and isinstance(obj.get("evidence_paths"), list)
                and len(obj.get("evidence_paths")) > 0)
    ch.append(("sr::clean_requires_evidence", (not clean) or positive,
               "a pass report with no failure codes must carry positive evidence "
               "(cameras, bounds, samples>0, cleanup, non-empty evidence_paths)",
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
    ch += _schema_version(obj, RT_SURVEY_REPORT, code, "sr::")
    return ch


def _example_scene_survey_report(**over):
    d = {
        "report_id": "scene_survey_report_gloam_courtyard_run1",
        "operation_id": "op_v2_6_scene_survey_0001",
        "map_asset_path": "/Game/ThirdPerson/Lvl_ThirdPerson",
        "anchor": "player",
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
            "procedural/reports/scene_survey/captures/cam_gameplay_player.png",
            "procedural/reports/scene_survey/support_map_gloam_courtyard_player.json",
        ],
        "failure_codes": [],
        "status": "pass",
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_SURVEY_REPORT,
        "report_type": RT_SURVEY_REPORT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 7. SceneSurveyEvidenceIndex (WF1063) — the auditable capture/evidence matrix.
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
        "index_id": "scene_survey_evidence_index_gloam_courtyard",
        "integrity_result": "pass",
        "captures_expected": 3,
        "captures_seen": 3,
        "evidence_entries": [
            "procedural/reports/scene_survey/captures/cam_gameplay_player.png",
            "procedural/reports/scene_survey/captures/cam_elevated_oblique_player.png",
            "procedural/reports/scene_survey/captures/cam_top_down_player.png",
        ],
        "created_by": "worldforge.v2.6",
        "created_at": AUTHORING_TS,
        "schema_version": RT_EVIDENCE_INDEX,
        "report_type": RT_EVIDENCE_INDEX,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry tail — CONTRACTS / CONTRACT_GROUPS / KNOWN_BAD_OWNING_CODE / codes.
# --------------------------------------------------------------------------- #
CONTRACTS = {
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
    "profile": ("SceneSurveyProfile",),
    "capture": ("SceneSurveyCameraCapture",),
    "spatial": ("SceneSurveySupportMap", "SceneSurveyTemporaryPlacement"),
    "proxy": ("SceneSurveyProxyReport",),
    "report_index": ("SceneSurveyReport", "SceneSurveyEvidenceIndex"),
}

KNOWN_BAD_OWNING_CODE = {
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


# The set of failure codes this milestone owns (WF1061–1105). Uses a 4-digit slice.
SCENE_SURVEY_CODES = tuple(
    v for k, v in vars(C).items()
    if not k.startswith("_") and isinstance(v, str)
    and 1061 <= (int(v[2:6]) if v[2:6].isdigit() else -1) <= 1105
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
    if not SCENE_SURVEY_CODES:
        print("BAND FAIL: SCENE_SURVEY_CODES is empty"); ok = False
    print("SELF-DOGFOOD: {} ({} contracts, {} owned codes)".format(
        "PASS" if ok else "FAIL", len(CONTRACTS), len(SCENE_SURVEY_CODES)))
    sys.exit(0 if ok else 1)
