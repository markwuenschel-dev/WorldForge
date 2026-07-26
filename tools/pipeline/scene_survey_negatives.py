#!/usr/bin/env python3
"""scene_survey_negatives.py — v2.6 SceneSurveyForge hostile negative-fixture suite.

Proves the scene-survey schema spine REJECTS known-bad records — each for its OWNING
failure code, because a validator that fails for the wrong reason is not real coverage.
Fixtures are generated in-code: each is a canonical scene_survey_contracts._example_*
with a single targeted override violating exactly one honesty invariant.

These are the shaped-but-dishonest cases from the v2.6 handoff: an unknown survey mode,
an unknown/absent capture kind, a zero-radius probe; a camera claiming captured=True with
no image hash, a top_down passed off as perspective without the fallback flag, an unknown
capture kind, a camera location with no real provenance vector; a coverage=complete claim
over zero probed samples, class counts that do not sum to the total, valid_support absorbing
unknown/trace_error, a survey leaning on navmesh; an accepted marker that is not grounded,
that overlaps static geometry, whose coordinates were guessed (no trace), that violates edge
clearance; a proxy with an empty owner, a disabled_verified claim with proxies still present,
a proxies field that is not even a list; a report with more valid samples than total, an
unregistered failure code, a live_survey_runtime that never executed, a clean pass with no
evidence; and an evidence index claiming integrity pass over a partial matrix, with no
entries, or with an unknown integrity verdict.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/scene_survey_negatives.py --strict
Reports -> procedural/reports/scene_survey/negatives/scene_survey_negatives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as SS
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "negatives"

PROFILE = SS.validate_scene_survey_profile
CAMERA = SS.validate_scene_survey_camera_capture
SUPPORT = SS.validate_scene_survey_support_map
PLACEMENT = SS.validate_scene_survey_temporary_placement
PROXY = SS.validate_scene_survey_proxy_report
REPORT = SS.validate_scene_survey_report
INDEX = SS.validate_scene_survey_evidence_index


def cases():
    e = SS
    c = []
    # --- SceneSurveyProfile (WF1061/1064/1065) ---
    c.append(("profile:unknown_mode", PROFILE, e._example_scene_survey_profile(
        survey_mode="telepathy_survey"), F.SCENE_SURVEY_UNKNOWN_MODE))
    c.append(("profile:unknown_capture", PROFILE, e._example_scene_survey_profile(
        captures=["gameplay", "xray"]), F.SCENE_SURVEY_UNKNOWN_CAPTURE))
    c.append(("profile:zero_radius", PROFILE, e._example_scene_survey_profile(
        sample_radius_cm=0), F.SCENE_SURVEY_PROFILE_INVALID))
    # --- SceneSurveyCameraCapture (WF1069/1070/1071/1065) ---
    c.append(("camera:capture_overclaim", CAMERA, e._example_scene_survey_camera_capture(
        image_hash=""), F.SCENE_SURVEY_CAMERA_CAPTURE_OVERCLAIM))
    c.append(("camera:top_down_perspective", CAMERA, e._example_scene_survey_camera_capture(
        capture_kind="top_down", projection="perspective", perspective_fallback=False),
        F.SCENE_SURVEY_CAMERA_PROJECTION_INVALID))
    c.append(("camera:unknown_kind", CAMERA, e._example_scene_survey_camera_capture(
        capture_kind="thermal"), F.SCENE_SURVEY_UNKNOWN_CAPTURE))
    c.append(("camera:no_provenance", CAMERA, e._example_scene_survey_camera_capture(
        location=[0.0, 0.0]), F.SCENE_SURVEY_CAMERA_PROVENANCE_INVALID))
    # --- SceneSurveySupportMap (WF1076/1077/1078/1081) ---
    c.append(("support:coverage_over_zero", SUPPORT, e._example_scene_survey_support_map(
        samples_total=0, valid_support=0, unsupported=0, edge=0, blocked=0,
        trace_error=0, unknown=0, coverage_complete=True),
        F.SCENE_SURVEY_SUPPORT_COVERAGE_OVERCLAIM))
    c.append(("support:counts_dont_sum", SUPPORT, e._example_scene_survey_support_map(
        unsupported=99), F.SCENE_SURVEY_SUPPORT_MAP_INCOMPLETE))
    c.append(("support:unknown_absorbed", SUPPORT, e._example_scene_survey_support_map(
        valid_support=140, unknown=20), F.SCENE_SURVEY_SUPPORT_UNKNOWN_OVERCLAIM))
    c.append(("support:navmesh_dependency", SUPPORT, e._example_scene_survey_support_map(
        uses_navmesh=True), F.SCENE_SURVEY_NAVMESH_OVERCLAIM))
    # --- SceneSurveyTemporaryPlacement (WF1083/1084/1086/1088) ---
    c.append(("placement:accepted_not_grounded", PLACEMENT,
              e._example_scene_survey_temporary_placement(grounded=False),
              F.SCENE_SURVEY_PLACEMENT_NOT_GROUNDED))
    c.append(("placement:accepted_overlap", PLACEMENT,
              e._example_scene_survey_temporary_placement(overlap_static=True),
              F.SCENE_SURVEY_PLACEMENT_OVERLAP_ACCEPTED))
    c.append(("placement:accepted_guessed", PLACEMENT,
              e._example_scene_survey_temporary_placement(trace_backed=False),
              F.SCENE_SURVEY_PLACEMENT_GUESSED_COORDINATES))
    c.append(("placement:accepted_edge_violation", PLACEMENT,
              e._example_scene_survey_temporary_placement(edge_clearance=False),
              F.SCENE_SURVEY_PLACEMENT_EDGE_VIOLATION))
    # --- SceneSurveyProxyReport (WF1089/1090/1091) ---
    c.append(("proxy:unattributed_owner", PROXY, e._example_scene_survey_proxy_report(
        proxies=[{"proxy_id": "heart", "category": "Heart",
                  "owner_system": "", "owner_object": ""}]),
        F.SCENE_SURVEY_PROXY_UNATTRIBUTED))
    c.append(("proxy:disable_unverified", PROXY, e._example_scene_survey_proxy_report(
        proxies_present_after=2), F.SCENE_SURVEY_PROXY_DISABLE_UNVERIFIED))
    c.append(("proxy:not_a_list", PROXY, e._example_scene_survey_proxy_report(
        proxies="none"), F.SCENE_SURVEY_PROXY_ENUMERATION_INVALID))
    # --- SceneSurveyReport (WF1062/1095/1097/1099) ---
    c.append(("report:valid_exceeds_total", REPORT, e._example_scene_survey_report(
        support_samples_valid=200), F.SCENE_SURVEY_REPORT_INVALID))
    c.append(("report:unknown_failure_code", REPORT, e._example_scene_survey_report(
        failure_codes=["NOT_A_CODE"]), F.SCENE_SURVEY_UNKNOWN_FAILURE_CODE))
    c.append(("report:live_not_executed", REPORT, e._example_scene_survey_report(
        runtime_executed=False), F.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM))
    c.append(("report:clean_no_evidence", REPORT, e._example_scene_survey_report(
        runtime_mode="deterministic_survey_simulation", evidence_paths=[]),
        F.SCENE_SURVEY_EVIDENCE_MISSING))
    # --- SceneSurveyEvidenceIndex (WF1063) ---
    c.append(("index:partial_matrix", INDEX, e._example_scene_survey_evidence_index(
        captures_seen=2), F.SCENE_SURVEY_EVIDENCE_INDEX_INVALID))
    c.append(("index:pass_no_entries", INDEX, e._example_scene_survey_evidence_index(
        evidence_entries=[]), F.SCENE_SURVEY_EVIDENCE_INDEX_INVALID))
    c.append(("index:unknown_integrity", INDEX, e._example_scene_survey_evidence_index(
        integrity_result="maybe"), F.SCENE_SURVEY_EVIDENCE_INDEX_INVALID))
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey negative-fixture suite.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "scene_survey_negatives", strict=strict)
    cs = cases()
    rep.check("suite_nonempty", len(cs) >= 21,
              "negative suite must carry >= 21 fixtures (got {})".format(len(cs)),
              code=F.SCENE_SURVEY_NEGATIVE_ACCEPTED)
    for label, validate, bad, owning in cs:
        fails = [ck for ck in validate(bad, strict=True) if not ck[1]]
        codes = {ck[3] for ck in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad fixture was ACCEPTED (fake green)", code=F.SCENE_SURVEY_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::owning_code".format(label), owning in codes,
                  "must be rejected for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]), code=F.SCENE_SURVEY_NEGATIVE_ACCEPTED)
    for name, (validate, good, _bad) in SS.CONTRACTS.items():
        gfails = [ck for ck in validate(good(), strict=True) if not ck[1]]
        rep.check("reverse::{}::valid_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([ck[0] for ck in gfails][:4]),
                  code=F.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="scene-survey-negative-fixtures", pack=None, strict=strict,
        status=rep.status, record_count=len(cs), records_total=len(cs),
        report_type="wf.scene_survey.negatives.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "scene_survey_negatives_report.json")
    rep.print_summary("scene-survey-negative-fixtures")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
