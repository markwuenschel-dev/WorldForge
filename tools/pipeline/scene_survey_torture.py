#!/usr/bin/env python3
"""scene_survey_torture.py — v2.6 hostile torture battery (SceneSurveyForge).

Proves the scene-survey honesty detectors reject the ways a read-only spatial-survey
report can fake success, and — the other half of torture — that they still ACCEPT the
adversarial-but-honest edge records (boundary counts, tight fail-closed margins, honest
projection fallbacks, rejected placements that legitimately violate gates). Dogfood-based:
constructs the hostile / honest states in-code off the _example_* factories and asserts
each is caught for its OWNING code (or cleanly accepted), certifying the DETECTORS (not the
live evidence). Each reject mode is the scene-survey form of a fake-green from the v2.6
honesty spine (contract docstring §): a camera "captured" with no image hash; a
non-orthographic top_down passed off as true top_down; support class counts that don't sum
to the probed total; valid_support absorbing unknown/trace_error (fail-closed breach);
coverage=complete over zero probes; a survey leaning on navmesh; an accepted placement with
all-but-one gate satisfied (not grounded / overlap / clearance / edge / footprint / guessed
coordinates); a proxy list mixing attributed + unattributed entries; a disabled_verified
claim with proxies still present; a report with more valid samples than total; a declared
failure code that is not a real WF code; a clean pass with no evidence; a simulation
mislabeled live; a partial capture matrix claimed complete.

SUBJECT-BINDING reject modes (WF1106/1107/1108) attack the v2.6 ownership boundary: a
subject with neither anchor channel resolved and one with both (WorldForge would have to
choose); a resolved_by that is not "caller", seen from the subject, the report and a
profile's nested subject; an executed run that will not say where it anchored; and the pair
lies that no single object can see — a report bound to a different subject_id, a different
map, an anchor transform drifted past tolerance, or a different anchored object.

Adversarial-but-honest ACCEPT modes prove the detectors are not merely trigger-happy:
counts at the boundary that still sum to total, valid_support exactly at the
total-unknown-trace_error margin, a top_down that is truly orthographic, a top_down that
honestly flags perspective_fallback, a REJECTED placement that violates every gate (the
survey doing its job), a proxy set with no disable claim and proxies still present, a report
at exactly valid==total, an honest fail report carrying a real WF failure code, a valid
actor_object_path subject, an explicit_transform subject with no rotation, a pair anchored
at EXACTLY the 1cm tolerance boundary, and — the capture-opt-in narrowing — a clean pass
with captures_requested=[] and camera_capture_ok=False. That last one is paired with reject
modes proving the narrowing is surgical: the same report still fails when its OTHER evidence
is missing, and camera_capture_ok=False still fails the moment a capture was actually asked
for. The honesty rail is preserved exactly where it was earned.

Torture also stresses idempotence: every reject validator is run twice and must yield the
identical failing-code set (deterministic fail-closed, no order dependence).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/scene_survey_torture.py --strict
Reports -> procedural/reports/scene_survey/scene_survey_torture_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as e  # noqa: E402
from failure_codes import FailureCode as F  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey"

# Neutral fixture object paths. WorldForge owns no subject vocabulary of its own, so
# its hostile fixtures must not borrow a target game's actor names either.
OBJ_PATH_A = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.Fixture_Subject_0"
OBJ_PATH_B = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.Fixture_Other_7"


def _bind(subject, report):
    """Adapt the (subject, report) pair validator to the single-record torture shape."""
    return (lambda rec, strict=False: e.validate_subject_binding(
        rec[0], rec[1], strict=strict), (subject, report))


def _path_subject(**over):
    d = dict(subject_kind="actor", anchor_mode="actor_object_path",
             anchor_location=None, anchor_object_path=OBJ_PATH_A)
    d.update(over)
    return e._example_scene_survey_subject(**d)


def reject_modes():
    """(label, validate_fn, hostile_record, owning_code) — each must be CAUGHT."""
    return [
        # -- profile: bounded taxonomy + shape -------------------------------
        ("profile_unknown_mode", e.validate_scene_survey_profile,
         e._example_scene_survey_profile(survey_mode="telepathy_survey"),
         F.SCENE_SURVEY_UNKNOWN_MODE),
        ("profile_unknown_capture", e.validate_scene_survey_profile,
         e._example_scene_survey_profile(captures=["xray_vision"]),
         F.SCENE_SURVEY_UNKNOWN_CAPTURE),
        ("profile_zero_repeat", e.validate_scene_survey_profile,
         e._example_scene_survey_profile(repeat=0),
         F.SCENE_SURVEY_PROFILE_INVALID),

        # -- camera: capture / projection honesty ----------------------------
        ("camera_captured_no_hash", e.validate_scene_survey_camera_capture,
         e._example_scene_survey_camera_capture(image_hash=""),
         F.SCENE_SURVEY_CAMERA_CAPTURE_OVERCLAIM),
        ("camera_top_down_perspective_hidden", e.validate_scene_survey_camera_capture,
         e._example_scene_survey_camera_capture(
             capture_kind="top_down", projection="perspective",
             perspective_fallback=False),
         F.SCENE_SURVEY_CAMERA_PROJECTION_INVALID),
        ("camera_provenance_blank_anchor", e.validate_scene_survey_camera_capture,
         e._example_scene_survey_camera_capture(anchor_actor="   "),
         F.SCENE_SURVEY_CAMERA_PROVENANCE_INVALID),

        # -- support map: sum / fail-closed / coverage / navmesh -------------
        ("support_counts_dont_sum", e.validate_scene_survey_support_map,
         e._example_scene_survey_support_map(edge=999),
         F.SCENE_SURVEY_SUPPORT_MAP_INCOMPLETE),
        ("support_valid_absorbs_unknown", e.validate_scene_survey_support_map,
         e._example_scene_survey_support_map(valid_support=200),
         F.SCENE_SURVEY_SUPPORT_UNKNOWN_OVERCLAIM),
        ("support_coverage_over_zero_probes", e.validate_scene_survey_support_map,
         e._example_scene_survey_support_map(
             samples_total=0, valid_support=0, unsupported=0, edge=0, blocked=0,
             trace_error=0, unknown=0, coverage_complete=True),
         F.SCENE_SURVEY_SUPPORT_COVERAGE_OVERCLAIM),
        ("support_leans_on_navmesh", e.validate_scene_survey_support_map,
         e._example_scene_survey_support_map(uses_navmesh=True),
         F.SCENE_SURVEY_NAVMESH_OVERCLAIM),

        # -- placement: accepted marker, all-but-one gate satisfied ----------
        ("placement_accepted_not_grounded", e.validate_scene_survey_temporary_placement,
         e._example_scene_survey_temporary_placement(grounded=False),
         F.SCENE_SURVEY_PLACEMENT_NOT_GROUNDED),
        ("placement_accepted_overlap", e.validate_scene_survey_temporary_placement,
         e._example_scene_survey_temporary_placement(overlap_static=True),
         F.SCENE_SURVEY_PLACEMENT_OVERLAP_ACCEPTED),
        ("placement_accepted_no_clearance", e.validate_scene_survey_temporary_placement,
         e._example_scene_survey_temporary_placement(heart_clearance=False),
         F.SCENE_SURVEY_PLACEMENT_CLEARANCE_MISSING),
        ("placement_accepted_edge_violation", e.validate_scene_survey_temporary_placement,
         e._example_scene_survey_temporary_placement(edge_clearance=False),
         F.SCENE_SURVEY_PLACEMENT_EDGE_VIOLATION),
        ("placement_accepted_footprint_unsupported", e.validate_scene_survey_temporary_placement,
         e._example_scene_survey_temporary_placement(footprint_supported=False),
         F.SCENE_SURVEY_PLACEMENT_FOOTPRINT_UNSUPPORTED),
        ("placement_accepted_guessed_coords", e.validate_scene_survey_temporary_placement,
         e._example_scene_survey_temporary_placement(trace_backed=False),
         F.SCENE_SURVEY_PLACEMENT_GUESSED_COORDINATES),

        # -- proxy: attribution + disable verification -----------------------
        ("proxy_mix_attributed_unattributed", e.validate_scene_survey_proxy_report,
         e._example_scene_survey_proxy_report(proxies=[
             {"proxy_id": "proxy_heart_0", "category": "Heart",
              "owner_system": "FixtureHeartSystem", "owner_object": "AFixtureHeart_0"},
             {"proxy_id": "orphan_marker", "category": "RitualPoint",
              "owner_system": "", "owner_object": ""}]),
         F.SCENE_SURVEY_PROXY_UNATTRIBUTED),
        ("proxy_disable_unverified", e.validate_scene_survey_proxy_report,
         e._example_scene_survey_proxy_report(
             disabled_verified=True, proxies_present_after=2),
         F.SCENE_SURVEY_PROXY_DISABLE_UNVERIFIED),

        # -- report: cross-field honesty -------------------------------------
        ("report_valid_exceeds_total", e.validate_scene_survey_report,
         e._example_scene_survey_report(support_samples_valid=200),
         F.SCENE_SURVEY_REPORT_INVALID),
        ("report_unknown_failure_code", e.validate_scene_survey_report,
         e._example_scene_survey_report(status="fail",
                                        failure_codes=["WF9999_NOT_A_REAL_CODE"]),
         F.SCENE_SURVEY_UNKNOWN_FAILURE_CODE),
        ("report_clean_no_evidence", e.validate_scene_survey_report,
         e._example_scene_survey_report(camera_capture_ok=False),
         F.SCENE_SURVEY_EVIDENCE_MISSING),
        ("report_simulation_mislabeled_live", e.validate_scene_survey_report,
         e._example_scene_survey_report(runtime_executed=False, evidence_paths=[]),
         F.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM),

        # -- capture opt-in: the narrowing must be SURGICAL, not a hole -------
        # captures_requested=[] excuses ONLY the camera; the rest of the evidence
        # floor stands. Same report, no evidence paths -> still WF1099.
        ("report_no_captures_still_needs_evidence", e.validate_scene_survey_report,
         e._example_scene_survey_report(
             captures_requested=[], camera_capture_ok=False, evidence_paths=[],
             runtime_mode="deterministic_survey_simulation"),
         F.SCENE_SURVEY_EVIDENCE_MISSING),
        # ...and cleanup is still demanded of a capture-free survey.
        ("report_no_captures_still_needs_cleanup", e.validate_scene_survey_report,
         e._example_scene_survey_report(
             captures_requested=[], camera_capture_ok=False, cleanup_verified=False),
         F.SCENE_SURVEY_EVIDENCE_MISSING),
        # the honesty rail is preserved exactly where earned: a capture WAS asked
        # for and was not produced -> still WF1099.
        ("report_capture_requested_but_missing", e.validate_scene_survey_report,
         e._example_scene_survey_report(
             captures_requested=["gameplay"], camera_capture_ok=False),
         F.SCENE_SURVEY_EVIDENCE_MISSING),

        # -- subject: the caller-resolved subject (WF1106) --------------------
        ("subject_neither_anchor_channel", e.validate_scene_survey_subject,
         e._example_scene_survey_subject(
             anchor_location=None, anchor_object_path=None),
         F.SCENE_SURVEY_SUBJECT_UNRESOLVED),
        ("subject_both_anchor_channels", e.validate_scene_survey_subject,
         e._example_scene_survey_subject(anchor_object_path=OBJ_PATH_A),
         F.SCENE_SURVEY_SUBJECT_UNRESOLVED),
        ("subject_mode_contradicts_channel", e.validate_scene_survey_subject,
         e._example_scene_survey_subject(anchor_mode="actor_object_path"),
         F.SCENE_SURVEY_SUBJECT_UNRESOLVED),

        # -- self-resolution: WorldForge picking its own subject (WF1108) -----
        ("subject_self_resolved", e.validate_scene_survey_subject,
         e._example_scene_survey_subject(resolved_by="worldforge"),
         F.SCENE_SURVEY_SUBJECT_INFERRED),
        ("profile_nested_subject_self_resolved", e.validate_scene_survey_profile,
         e._example_scene_survey_profile(
             subject=e._example_scene_survey_subject(resolved_by="worldforge")),
         F.SCENE_SURVEY_SUBJECT_INFERRED),
        ("report_self_resolved", e.validate_scene_survey_report,
         e._example_scene_survey_report(subject_resolved_by="worldforge"),
         F.SCENE_SURVEY_SUBJECT_INFERRED),

        # -- report: the echoed subject (WF1106) ------------------------------
        ("report_executed_without_observed_anchor", e.validate_scene_survey_report,
         e._example_scene_survey_report(observed_anchor_location=None),
         F.SCENE_SURVEY_SUBJECT_UNRESOLVED),
        ("report_subject_id_blank", e.validate_scene_survey_report,
         e._example_scene_survey_report(subject_id="   "),
         F.SCENE_SURVEY_SUBJECT_UNRESOLVED),

        # -- PAIR: surveyed the wrong subject (WF1107/1108) -------------------
        # Shaped-perfectly on BOTH sides — only the pair can see the lie.
        ("binding_surveyed_wrong_subject",) + _bind(
            e._example_scene_survey_subject(),
            e._example_scene_survey_report(subject_id="subject_fixture_beta"))
        + (F.SCENE_SURVEY_SUBJECT_MISMATCH,),
        ("binding_right_subject_wrong_map",) + _bind(
            e._example_scene_survey_subject(),
            e._example_scene_survey_report(map_asset_path="/Game/Fixture/Lvl_Other"))
        + (F.SCENE_SURVEY_SUBJECT_MISMATCH,),
        # 5cm of drift against a 1cm tolerance: WorldForge moved the survey.
        ("binding_transform_drift_past_tolerance",) + _bind(
            e._example_scene_survey_subject(),
            e._example_scene_survey_report(
                observed_anchor_location=[1200.0, -450.0, 97.5]))
        + (F.SCENE_SURVEY_SUBJECT_MISMATCH,),
        ("binding_anchored_on_other_object",) + _bind(
            _path_subject(),
            e._example_scene_survey_report(observed_anchor_object_path=OBJ_PATH_B))
        + (F.SCENE_SURVEY_SUBJECT_MISMATCH,),
        ("binding_resolver_not_caller",) + _bind(
            e._example_scene_survey_subject(),
            e._example_scene_survey_report(subject_resolved_by="worldforge"))
        + (F.SCENE_SURVEY_SUBJECT_INFERRED,),

        # -- evidence index: partial matrix claimed complete -----------------
        ("index_partial_matrix_claimed_pass", e.validate_scene_survey_evidence_index,
         e._example_scene_survey_evidence_index(captures_seen=2),
         F.SCENE_SURVEY_EVIDENCE_INDEX_INVALID),
    ]


def accept_modes():
    """(label, validate_fn, honest_record) — adversarial edges that must be ACCEPTED."""
    return [
        # counts at the boundary, still summing exactly to total.
        ("support_boundary_all_valid", e.validate_scene_survey_support_map,
         e._example_scene_survey_support_map(
             samples_total=100, valid_support=100, unsupported=0, edge=0,
             blocked=0, trace_error=0, unknown=0, coverage_complete=True)),
        # valid_support exactly at the total-unknown-trace_error fail-closed margin.
        ("support_valid_at_failclosed_margin", e.validate_scene_survey_support_map,
         e._example_scene_survey_support_map(
             samples_total=100, valid_support=95, unsupported=0, edge=0,
             blocked=0, trace_error=3, unknown=2, coverage_complete=True)),
        # a top_down that is genuinely orthographic (honest true top-down).
        ("camera_top_down_true_orthographic", e.validate_scene_survey_camera_capture,
         e._example_scene_survey_camera_capture(
             camera_id="cam_top_down_player", capture_kind="top_down",
             projection="orthographic")),
        # a top_down that honestly flags the perspective fallback.
        ("camera_top_down_honest_fallback", e.validate_scene_survey_camera_capture,
         e._example_scene_survey_camera_capture(
             camera_id="cam_top_down_player", capture_kind="top_down",
             projection="perspective", perspective_fallback=True)),
        # a REJECTED placement that legitimately violates every gate — survey working.
        ("placement_rejected_violates_all_gates", e.validate_scene_survey_temporary_placement,
         e._example_scene_survey_temporary_placement(
             accepted=False, trace_backed=False, grounded=False, ground_contact=False,
             footprint_supported=False, overlap_static=True, overlap_dynamic=True,
             capsule_clearance=False, heart_clearance=False, edge_clearance=False)),
        # no disable claim, proxies still present after — honest (no overclaim).
        ("proxy_no_disable_claim_present", e.validate_scene_survey_proxy_report,
         e._example_scene_survey_proxy_report(
             disable_requested=False, disabled_verified=False,
             proxies_present_after=3)),
        # report at exactly valid == total (boundary, not an overclaim).
        ("report_valid_equals_total", e.validate_scene_survey_report,
         e._example_scene_survey_report(support_samples_valid=158)),
        # honest FAIL report carrying a real WF failure code (not clean => no evidence gate).
        ("report_honest_fail_real_code", e.validate_scene_survey_report,
         e._example_scene_survey_report(
             status="fail",
             failure_codes=[F.SCENE_SURVEY_PLACEMENT_OVERLAP_ACCEPTED])),
        # blocked integrity with a partial matrix is honest (only 'pass' demands full).
        ("index_blocked_partial_honest", e.validate_scene_survey_evidence_index,
         e._example_scene_survey_evidence_index(
             integrity_result="blocked", captures_seen=1)),
        # -- subject: both legal anchor modes must be ACCEPTED ----------------
        # the other legal channel — an object path with no transform.
        ("subject_actor_object_path_mode", e.validate_scene_survey_subject,
         _path_subject()),
        # anchor_rotation is optional-valued even for explicit_transform.
        ("subject_explicit_transform_no_rotation", e.validate_scene_survey_subject,
         e._example_scene_survey_subject(anchor_rotation=None)),
        # a point subject at the world origin — 0.0 is a real coordinate, not "absent".
        ("subject_anchor_at_world_origin", e.validate_scene_survey_subject,
         e._example_scene_survey_subject(anchor_location=[0.0, 0.0, 0.0])),
        # -- capture opt-in: the deliberate narrowing, proven live ------------
        # a survey that was never asked to render must not be failed for not
        # rendering. Every other evidence rail is still satisfied here.
        ("report_capture_optin_clean_without_camera", e.validate_scene_survey_report,
         e._example_scene_survey_report(
             captures_requested=[], camera_capture_ok=False)),
        # -- PAIR: matched bindings must pass CLEAN in both modes -------------
        ("binding_matched_explicit_transform",) + _bind(
            e._example_scene_survey_subject(), e._example_scene_survey_report()),
        ("binding_matched_object_path",) + _bind(
            _path_subject(),
            e._example_scene_survey_report(
                observed_anchor_object_path=OBJ_PATH_A)),
        # EXACTLY at the 1cm tolerance boundary — inclusive, so still honest.
        ("binding_transform_exactly_at_tolerance",) + _bind(
            e._example_scene_survey_subject(),
            e._example_scene_survey_report(
                observed_anchor_location=[1201.0, -450.0, 92.5])),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey torture battery.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "scene_survey_torture", strict=strict)
    rejects = reject_modes()
    accepts = accept_modes()

    rep.check("torture::reject_nonempty", len(rejects) >= 34,
              "reject battery must carry >= 34 hostile modes (got {})".format(len(rejects)),
              code=F.SCENE_SURVEY_TORTURE_FAILED)
    rep.check("torture::accept_nonempty", len(accepts) >= 15,
              "accept battery must carry >= 15 adversarial-but-honest modes (got {})".format(
                  len(accepts)),
              code=F.SCENE_SURVEY_TORTURE_FAILED)
    # The subject-binding lane is the v2.6 ownership boundary — it must not be
    # silently emptied out while the battery stays nominally "green".
    subject_rejects = [r for r in rejects
                       if r[0].startswith(("subject_", "binding_", "report_self",
                                           "report_executed_", "report_subject_",
                                           "profile_nested_"))]
    rep.check("torture::subject_lane_nonempty", len(subject_rejects) >= 13,
              "the subject/binding reject lane must carry >= 13 modes (got {})".format(
                  len(subject_rejects)), code=F.SCENE_SURVEY_TORTURE_FAILED)

    # Reject side: every hostile record must be caught, for its owning code, deterministically.
    for label, validate, rec, owning in rejects:
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("torture::reject::{}::caught".format(label), len(fails) > 0,
                  "hostile state was ACCEPTED (fake green)",
                  code=F.SCENE_SURVEY_TORTURE_FAILED)
        rep.check("torture::reject::{}::owning_code".format(label), owning in codes,
                  "must be caught for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]),
                  code=F.SCENE_SURVEY_TORTURE_FAILED)
        # idempotence: a second pass must yield the identical failing-code set.
        codes2 = {c[3] for c in validate(rec, strict=True) if not c[1]}
        rep.check("torture::reject::{}::idempotent".format(label), codes == codes2,
                  "validator is non-deterministic across repeated runs",
                  code=F.SCENE_SURVEY_TORTURE_FAILED)

    # Accept side: every adversarial-but-honest record must pass clean (no fake-red).
    for label, validate, rec in accepts:
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        rep.check("torture::accept::{}::clean".format(label), len(fails) == 0,
                  "honest edge record was REJECTED (fake red): {}".format(
                      [c[0] for c in fails][:6]),
                  code=F.SCENE_SURVEY_TORTURE_FAILED)

    total = len(rejects) + len(accepts)
    rep.finalize()
    rep.set_meta(build_meta(
        command="scene-survey-torture", pack=None, strict=strict, status=rep.status,
        record_count=total, records_total=total,
        report_type="wf.scene_survey.torture.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "scene_survey_torture_report.json")
    rep.print_summary("scene-survey-torture")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
