#!/usr/bin/env python3
"""tactical_negatives.py — v2.4 TacticalBehaviorForge hostile negative-fixture suite.

Proves the tactical schema spine REJECTS known-bad records — each for its OWNING failure
code, because a validator that fails for the wrong reason is not real coverage. Fixtures
are generated in-code: each is a canonical tactical_contracts._example_* with a single
targeted override violating exactly one honesty invariant.

These are the known-bad cases from handoff §7/§13: unknown role/action/stimulus, a
decision trace that selects an INVALID option, a trace missing its input evidence, a
decision option with an impossible route, a cover action without cover, a flank action
without a flank route, a retreat action without a retreat anchor, a coordinated group of
one NPC, suppression without a suppressor, a state delta that claims change with equal
hashes, a save/load claim without tactical hashes, a budget overrun marked pass, a live
runtime mode with no evidence, a partial 23/24 matrix claiming full, stale evidence, and
an unknown failure code.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/tactical_negatives.py --strict
Reports -> procedural/reports/tactical/negatives/tactical_negatives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "negatives"

BP = TC.validate_tactical_behavior_profile
RL = TC.validate_tactical_role_definition
AF = TC.validate_tactical_affordance_map
NB = TC.validate_tactical_npc_binding
DI = TC.validate_tactical_decision_input
OP = TC.validate_tactical_decision_option
TR = TC.validate_tactical_decision_trace
SD = TC.validate_tactical_state_delta
GS = TC.validate_tactical_group_state
RR = TC.validate_tactical_runtime_report
SS = TC.validate_tactical_save_state
BR = TC.validate_tactical_budget_report
EI = TC.validate_tactical_evidence_index
OS = TC.validate_operator_tactical_scenario_view
ON = TC.validate_operator_tactical_npc_view


def cases():
    e = TC
    c = []
    # --- TacticalBehaviorProfile ---
    c.append(("bp:aggression_out_of_range", BP, e._example_tactical_behavior_profile(aggression=1.5),
              F.TACTICAL_PROFILE_INVALID))
    c.append(("bp:unknown_role", BP, e._example_tactical_behavior_profile(
        roles_allowed=["sentinel", "warlock"]), F.TACTICAL_UNKNOWN_ROLE))
    c.append(("bp:unknown_action", BP, e._example_tactical_behavior_profile(
        actions_allowed=["hold_position", "cast_fireball"]), F.TACTICAL_UNKNOWN_ACTION))
    c.append(("bp:unknown_stimulus", BP, e._example_tactical_behavior_profile(
        stimuli_allowed=["player_seen", "smelled_fear"]), F.TACTICAL_UNKNOWN_STIMULUS))
    c.append(("bp:zero_cadence", BP, e._example_tactical_behavior_profile(decision_cadence_ms=0),
              F.TACTICAL_PROFILE_INVALID))
    # --- TacticalRoleDefinition ---
    c.append(("rl:preferred_not_allowed", RL, e._example_tactical_role_definition(
        preferred_actions=["flank_via_route"]), F.TACTICAL_ROLE_INVALID))
    c.append(("rl:forbidden_overlaps_allowed", RL, e._example_tactical_role_definition(
        forbidden_actions=["hold_position"]), F.TACTICAL_ROLE_INVALID))
    c.append(("rl:distances_unordered", RL, e._example_tactical_role_definition(
        min_engagement_distance=5000.0, max_engagement_distance=200.0), F.TACTICAL_ROLE_INVALID))
    c.append(("rl:unknown_role_id", RL, e._example_tactical_role_definition(role_id="warlock"),
              F.TACTICAL_UNKNOWN_ROLE))
    # --- TacticalAffordanceMap ---
    c.append(("af:malformed_cover_point", AF, e._example_tactical_affordance_map(
        cover_points=[{"cover_id": "cover_x"}]), F.TACTICAL_COVER_REFERENCE_INVALID))
    c.append(("af:no_source_reports", AF, e._example_tactical_affordance_map(source_reports=[]),
              F.TACTICAL_AFFORDANCE_MAP_INVALID))
    c.append(("af:unbounded_hazard", AF, e._example_tactical_affordance_map(
        hazard_zones=[{"hazard_id": "hz", "location": [0, 0, 0]}]),
        F.TACTICAL_AFFORDANCE_MAP_INVALID))
    # --- TacticalNPCBinding ---
    c.append(("nb:tile_not_allowed", NB, e._example_tactical_npc_binding(tile_id="tile_nowhere"),
              F.TACTICAL_NPC_BINDING_INVALID))
    c.append(("nb:scope_leak", NB, e._example_tactical_npc_binding(
        streaming_scope={"region_id": "region_alpine_hub", "allowed_tile_ids": ["tile_far"]}),
        F.TACTICAL_NPC_BINDING_INVALID))
    c.append(("nb:unknown_role", NB, e._example_tactical_npc_binding(tactical_role_id="warlock"),
              F.TACTICAL_UNKNOWN_ROLE))
    # --- TacticalDecisionInput ---
    c.append(("di:unknown_stimulus", DI, e._example_tactical_decision_input(
        active_stimuli=["telepathy"]), F.TACTICAL_UNKNOWN_STIMULUS))
    c.append(("di:bad_visibility", DI, e._example_tactical_decision_input(
        player_visibility="telepathic"), F.TACTICAL_DECISION_INPUT_INVALID))
    c.append(("di:bad_health_state", DI, e._example_tactical_decision_input(
        health_state={"hp": 200.0, "hp_max": 100.0}), F.TACTICAL_DECISION_INPUT_INVALID))
    c.append(("di:empty_stimuli", DI, e._example_tactical_decision_input(active_stimuli=[]),
              F.TACTICAL_UNKNOWN_STIMULUS))
    # --- TacticalDecisionOption ---
    c.append(("op:valid_flank_no_route", OP, e._example_tactical_decision_option(target_route_id="none"),
              F.TACTICAL_FLANK_ROUTE_MISSING))
    c.append(("op:valid_retreat_no_anchor", OP, e._example_tactical_decision_option(
        action_type="retreat_to_anchor", target_route_id="none", target_anchor_id="none"),
        F.TACTICAL_RETREAT_ROUTE_MISSING))
    c.append(("op:valid_cover_no_cover", OP, e._example_tactical_decision_option(
        action_type="use_cover", target_route_id="none", target_cover_id="none"),
        F.TACTICAL_COVER_REFERENCE_INVALID))
    c.append(("op:invalid_no_reason", OP, e._example_tactical_decision_option(
        valid=False, rejection_reason="none"), F.TACTICAL_DECISION_OPTION_INVALID))
    c.append(("op:valid_with_reason", OP, e._example_tactical_decision_option(
        rejection_reason="rejected for X"), F.TACTICAL_DECISION_OPTION_INVALID))
    c.append(("op:unknown_action", OP, e._example_tactical_decision_option(action_type="cast_fireball"),
              F.TACTICAL_UNKNOWN_ACTION))
    # --- TacticalDecisionTrace ---
    c.append(("tr:selects_invalid_option", TR, e._example_tactical_decision_trace(
        selected_option_id="opt_flank"), F.TACTICAL_SELECTED_INVALID_OPTION))
    c.append(("tr:selected_not_in_options", TR, e._example_tactical_decision_trace(
        selected_option_id="opt_ghost"), F.TACTICAL_DECISION_TRACE_INVALID))
    c.append(("tr:clean_no_state_delta", TR, e._example_tactical_decision_trace(state_delta_id="none"),
              F.TACTICAL_STATE_NOT_MUTATED))
    c.append(("tr:clean_not_completed", TR, e._example_tactical_decision_trace(
        execution_completed=False), F.TACTICAL_EXECUTION_MISSING))
    # --- TacticalStateDelta ---
    c.append(("sd:change_equal_hash", SD, e._example_tactical_state_delta(
        post_state_hash="sha256:pre_0001"), F.TACTICAL_STATE_NOT_MUTATED))
    c.append(("sd:quest_no_context", SD, e._example_tactical_state_delta(quest_pressure_changed=True),
              F.TACTICAL_QUEST_STATE_MISSING))
    c.append(("sd:faction_no_context", SD, e._example_tactical_state_delta(faction_pressure_changed=True),
              F.TACTICAL_FACTION_STATE_MISSING))
    c.append(("sd:streaming_no_transition", SD, e._example_tactical_state_delta(
        streaming_scope_changed=True), F.TACTICAL_STATE_DELTA_INVALID))
    # --- TacticalGroupState ---
    c.append(("gs:coordinated_one_npc", GS, e._example_tactical_group_state(npc_ids=["only_one"]),
              F.TACTICAL_COORDINATION_INVALID))
    c.append(("gs:flank_no_route", GS, e._example_tactical_group_state(flank_route_id="none"),
              F.TACTICAL_FLANK_ROUTE_MISSING))
    c.append(("gs:suppression_no_suppressor", GS, e._example_tactical_group_state(
        roles_present=["skirmisher"]), F.TACTICAL_COORDINATION_INVALID))
    # --- TacticalRuntimeReport ---
    c.append(("rr:clean_zero_valid", RR, e._example_tactical_runtime_report(valid_decision_count=0),
              F.TACTICAL_RUNTIME_REPORT_INVALID))
    c.append(("rr:clean_mission_incomplete", RR, e._example_tactical_runtime_report(
        mission_completed=False), F.TACTICAL_RUNTIME_REPORT_INVALID))
    c.append(("rr:clean_save_failed", RR, e._example_tactical_runtime_report(
        save_load_result="roundtrip_failed"), F.TACTICAL_SAVE_LOAD_FAILED))
    c.append(("rr:clean_budget_exceeded", RR, e._example_tactical_runtime_report(
        budget_result="exceeded"), F.TACTICAL_BUDGET_EXCEEDED))
    c.append(("rr:live_no_evidence", RR, e._example_tactical_runtime_report(
        runtime_mode="live_tactical_runtime"), F.TACTICAL_NAVMESH_OVERCLAIM))
    c.append(("rr:malformed_failure_code", RR, e._example_tactical_runtime_report(
        failure_codes=["NOT_A_CODE"]), F.TACTICAL_UNKNOWN_FAILURE_CODE))
    # --- TacticalSaveState ---
    c.append(("ss:roundtrip_no_npc_hashes", SS, e._example_tactical_save_state(npc_state_hashes={}),
              F.TACTICAL_SAVE_LOAD_MISSING))
    c.append(("ss:bad_roundtrip", SS, e._example_tactical_save_state(roundtrip_result="maybe"),
              F.TACTICAL_SAVE_LOAD_FAILED))
    # --- TacticalBudgetReport ---
    c.append(("br:npc_overrun_pass", BR, e._example_tactical_budget_report(npc_count=999),
              F.TACTICAL_BUDGET_EXCEEDED))
    c.append(("br:dpm_overrun_pass", BR, e._example_tactical_budget_report(decisions_per_minute=9999.0),
              F.TACTICAL_BUDGET_EXCEEDED))
    c.append(("br:over_budget_class_pass", BR, e._example_tactical_budget_report(
        runtime_classification="over_budget"), F.TACTICAL_BUDGET_EXCEEDED))
    # --- TacticalEvidenceIndex ---
    c.append(("ei:partial_matrix", EI, e._example_tactical_evidence_index(scenario_count_seen=23),
              F.TACTICAL_PARTIAL_MATRIX))
    c.append(("ei:stale_sha", EI, e._example_tactical_evidence_index(git_sha="unknown"),
              F.TACTICAL_STALE_EVIDENCE))
    c.append(("ei:action_coverage_missing", EI, e._example_tactical_evidence_index(
        actions_covered=["hold_position"]), F.TACTICAL_ACTION_COVERAGE_MISSING))
    # --- OperatorTacticalScenarioView ---
    c.append(("os:pass_no_trace", OS, e._example_operator_tactical_scenario_view(
        decision_trace_paths=[]), F.TACTICAL_OPERATOR_VIEW_INVALID))
    # --- OperatorTacticalNPCView ---
    c.append(("on:acted_no_trace", ON, e._example_operator_tactical_npc_view(
        decision_trace_paths=[]), F.TACTICAL_OPERATOR_VIEW_INVALID))
    c.append(("on:acted_no_state_delta", ON, e._example_operator_tactical_npc_view(
        state_delta_paths=[]), F.TACTICAL_STATE_NOT_MUTATED))
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical negative-fixture suite.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_negatives", strict=strict)
    cs = cases()
    rep.check("suite_nonempty", len(cs) >= 24,
              "negative suite must carry >= 24 fixtures (got {})".format(len(cs)),
              code=F.TACTICAL_NEGATIVE_ACCEPTED)
    for label, validate, bad, owning in cs:
        fails = [ck for ck in validate(bad, strict=True) if not ck[1]]
        codes = {ck[3] for ck in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad fixture was ACCEPTED (fake green)", code=F.TACTICAL_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::owning_code".format(label), owning in codes,
                  "must be rejected for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]), code=F.TACTICAL_NEGATIVE_ACCEPTED)
    for name, (validate, good, _bad) in TC.CONTRACTS.items():
        gfails = [ck for ck in validate(good(), strict=True) if not ck[1]]
        rep.check("reverse::{}::valid_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([ck[0] for ck in gfails][:4]),
                  code=F.TACTICAL_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="tactical-negative-fixtures", pack=None, strict=strict,
        status=rep.status, record_count=len(cs), records_total=len(cs),
        report_type="wf.tactical.negatives.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "tactical_negatives_report.json")
    rep.print_summary("tactical-negative-fixtures")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
