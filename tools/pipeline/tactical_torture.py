#!/usr/bin/env python3
"""tactical_torture.py — v2.4 hostile torture battery (Wave R).

Proves the tactical honesty detectors reject the ways a tactical-behavior report can fake
success. Dogfood-based: constructs the hostile states in-code and asserts each is caught for
its OWNING code, certifying the DETECTORS (not the live evidence). Each mode is the tactical
form of a fake-green from handoff §7/§13.

Torture modes: profile weight out of range, role preferred∉allowed, malformed cover
affordance, spawn tile outside allowed scope, unknown stimulus, a valid flank option with no
route, an invalid option with no reason, a trace selecting a rejected option, a clean trace
with no state delta, a state delta claiming change with equal hashes, quest pressure with no
context, a coordinated group of one NPC, suppression with no suppressor, a clean runtime
report with zero valid decisions / a failed save / an exceeded budget, a live-runtime
overclaim with no evidence, a roundtrip save with no NPC hashes, a budget overrun marked
pass, a partial 23/24 matrix, a stale git_sha, missing action coverage, a scenario view with
no decision trace, and an NPC view that acted with no state delta.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/tactical_torture.py --strict
Reports -> procedural/reports/tactical/negatives/tactical_torture_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as e
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "negatives"


def modes():
    return [
        ("profile_weight_out_of_range", e.validate_tactical_behavior_profile,
         e._example_tactical_behavior_profile(aggression=1.5), F.TACTICAL_PROFILE_INVALID),
        ("role_preferred_not_allowed", e.validate_tactical_role_definition,
         e._example_tactical_role_definition(preferred_actions=["flank_via_route"]),
         F.TACTICAL_ROLE_INVALID),
        ("affordance_bad_cover", e.validate_tactical_affordance_map,
         e._example_tactical_affordance_map(cover_points=[{"cover_id": "c"}]),
         F.TACTICAL_COVER_REFERENCE_INVALID),
        ("binding_tile_not_allowed", e.validate_tactical_npc_binding,
         e._example_tactical_npc_binding(tile_id="tile_nowhere"), F.TACTICAL_NPC_BINDING_INVALID),
        ("input_unknown_stimulus", e.validate_tactical_decision_input,
         e._example_tactical_decision_input(active_stimuli=["telepathy"]),
         F.TACTICAL_UNKNOWN_STIMULUS),
        ("option_flank_no_route", e.validate_tactical_decision_option,
         e._example_tactical_decision_option(target_route_id="none"), F.TACTICAL_FLANK_ROUTE_MISSING),
        ("option_invalid_no_reason", e.validate_tactical_decision_option,
         e._example_tactical_decision_option(valid=False, rejection_reason="none"),
         F.TACTICAL_DECISION_OPTION_INVALID),
        ("trace_selects_invalid", e.validate_tactical_decision_trace,
         e._example_tactical_decision_trace(selected_option_id="opt_flank"),
         F.TACTICAL_SELECTED_INVALID_OPTION),
        ("trace_no_state_delta", e.validate_tactical_decision_trace,
         e._example_tactical_decision_trace(state_delta_id="none"), F.TACTICAL_STATE_NOT_MUTATED),
        ("delta_change_equal_hash", e.validate_tactical_state_delta,
         e._example_tactical_state_delta(post_state_hash="sha256:pre_0001"),
         F.TACTICAL_STATE_NOT_MUTATED),
        ("delta_quest_no_context", e.validate_tactical_state_delta,
         e._example_tactical_state_delta(quest_pressure_changed=True), F.TACTICAL_QUEST_STATE_MISSING),
        ("group_coordinated_one", e.validate_tactical_group_state,
         e._example_tactical_group_state(npc_ids=["only_one"]), F.TACTICAL_COORDINATION_INVALID),
        ("group_suppression_no_suppressor", e.validate_tactical_group_state,
         e._example_tactical_group_state(roles_present=["skirmisher"]), F.TACTICAL_COORDINATION_INVALID),
        ("runtime_zero_valid", e.validate_tactical_runtime_report,
         e._example_tactical_runtime_report(valid_decision_count=0), F.TACTICAL_RUNTIME_REPORT_INVALID),
        ("runtime_save_failed", e.validate_tactical_runtime_report,
         e._example_tactical_runtime_report(save_load_result="roundtrip_failed"),
         F.TACTICAL_SAVE_LOAD_FAILED),
        ("runtime_budget_exceeded", e.validate_tactical_runtime_report,
         e._example_tactical_runtime_report(budget_result="exceeded"), F.TACTICAL_BUDGET_EXCEEDED),
        ("runtime_live_no_evidence", e.validate_tactical_runtime_report,
         e._example_tactical_runtime_report(runtime_mode="live_tactical_runtime"),
         F.TACTICAL_NAVMESH_OVERCLAIM),
        ("save_no_npc_hashes", e.validate_tactical_save_state,
         e._example_tactical_save_state(npc_state_hashes={}), F.TACTICAL_SAVE_LOAD_MISSING),
        ("budget_npc_overrun_pass", e.validate_tactical_budget_report,
         e._example_tactical_budget_report(npc_count=999), F.TACTICAL_BUDGET_EXCEEDED),
        ("index_partial_matrix", e.validate_tactical_evidence_index,
         e._example_tactical_evidence_index(scenario_count_seen=23), F.TACTICAL_PARTIAL_MATRIX),
        ("index_stale_sha", e.validate_tactical_evidence_index,
         e._example_tactical_evidence_index(git_sha="unknown"), F.TACTICAL_STALE_EVIDENCE),
        ("index_action_coverage_missing", e.validate_tactical_evidence_index,
         e._example_tactical_evidence_index(actions_covered=["hold_position"]),
         F.TACTICAL_ACTION_COVERAGE_MISSING),
        ("scenario_view_no_trace", e.validate_operator_tactical_scenario_view,
         e._example_operator_tactical_scenario_view(decision_trace_paths=[]),
         F.TACTICAL_OPERATOR_VIEW_INVALID),
        ("npc_view_no_state_delta", e.validate_operator_tactical_npc_view,
         e._example_operator_tactical_npc_view(state_delta_paths=[]), F.TACTICAL_STATE_NOT_MUTATED),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical torture battery.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "tactical_torture", strict=strict)
    ms = modes()
    rep.check("torture::nonempty", len(ms) >= 20,
              "torture battery must carry >= 20 modes (got {})".format(len(ms)),
              code=F.TACTICAL_TORTURE_FAILED)
    for label, validate, rec, owning in ms:
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("torture::{}::caught".format(label), len(fails) > 0,
                  "hostile state was ACCEPTED (fake green)", code=F.TACTICAL_TORTURE_FAILED)
        rep.check("torture::{}::owning_code".format(label), owning in codes,
                  "must be caught for {} (got {})".format(owning, sorted(str(x) for x in codes)[:4]),
                  code=F.TACTICAL_TORTURE_FAILED)
    rep.finalize()
    rep.set_meta(build_meta(
        command="tactical-torture", pack=None, strict=strict, status=rep.status,
        record_count=len(ms), records_total=len(ms), report_type="wf.tactical.torture.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "tactical_torture_report.json")
    rep.print_summary("tactical-torture")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
