#!/usr/bin/env python3
"""streaming_negatives.py — v2.3 StreamingForge hostile negative-fixture suite.

Proves the streaming schema spine REJECTS known-bad records — each for its OWNING
failure code, because a validator that fails for the wrong reason is not real
coverage. Fixtures are generated in-code: each is a canonical streaming_contracts.
_example_* with a single targeted override violating exactly one honesty invariant.

These are the known-bad cases from handoff §7/§12: disconnected region graph,
non-reciprocal neighbor, broken anchor link, route across a bad tile sequence, a
navmesh OVERCLAIM, a scenario that completes without a transition, a missing tile
load, a reload that loses state, a save/load claim without tile hashes, an NPC
claiming pressure outside its allowed tiles, a budget overrun reported as pass, a
partial 23/24 matrix claiming full, a stale git_sha, and an unknown failure code.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/streaming_negatives.py --strict
Reports -> procedural/reports/streaming/negatives/streaming_negatives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "negatives"

RD = SC.validate_region_definition
TD = SC.validate_tile_definition
AN = SC.validate_cross_tile_anchor
RT = SC.validate_cross_tile_route
MB = SC.validate_streamed_mission_binding
NB = SC.validate_streamed_npc_binding
BP = SC.validate_streaming_budget_profile
TL = SC.validate_tile_lifecycle_report
SR = SC.validate_streaming_runtime_report
SS = SC.validate_cross_tile_save_state
EI = SC.validate_streaming_evidence_index
OR = SC.validate_operator_region_view
OT = SC.validate_operator_tile_view


def cases():
    c = []
    e = SC
    # --- RegionDefinition ---
    c.append(("rd:entry_not_in_tiles", RD, e._example_region_definition(entry_tile_id="nope"),
              F.STREAMING_TILE_GRAPH_DISCONNECTED))
    c.append(("rd:exit_not_in_tiles", RD, e._example_region_definition(exit_tile_ids=["ghost"]),
              F.STREAMING_TILE_GRAPH_DISCONNECTED))
    c.append(("rd:unknown_profile", RD, e._example_region_definition(streaming_profile="warp"),
              F.STREAMING_REGION_CONTRACT_INVALID))
    c.append(("rd:too_few_tiles", RD, e._example_region_definition(tile_ids=["only_one"]),
              F.STREAMING_REGION_CONTRACT_INVALID))
    # --- StreamingTileDefinition ---
    c.append(("td:self_neighbor", TD, e._example_tile_definition(
        neighbor_tile_ids=["tile_alpine_hub_entry"]), F.STREAMING_NEIGHBOR_NOT_RECIPROCAL))
    c.append(("td:bad_bounds", TD, e._example_tile_definition(tile_bounds={"origin": [0, 0]}),
              F.STREAMING_TILE_CONTRACT_INVALID))
    c.append(("td:unknown_role", TD, e._example_tile_definition(tile_role="dungeon"),
              F.STREAMING_TILE_CONTRACT_INVALID))
    c.append(("td:unknown_load_policy", TD, e._example_tile_definition(load_policy="teleport"),
              F.STREAMING_TILE_CONTRACT_INVALID))
    # --- CrossTileAnchor ---
    c.append(("an:transition_no_link", AN, e._example_cross_tile_anchor(linked_anchor_ids=[]),
              F.STREAMING_ANCHOR_LINK_BROKEN))
    c.append(("an:self_link", AN, e._example_cross_tile_anchor(
        linked_anchor_ids=["anchor_alpine_hub_to_a"]), F.STREAMING_ANCHOR_LINK_BROKEN))
    c.append(("an:bad_world_location", AN, e._example_cross_tile_anchor(world_location=[1, 2]),
              F.STREAMING_ANCHOR_INVALID))
    c.append(("an:incompatible_type_role", AN, e._example_cross_tile_anchor(
        tile_role="route", anchor_type="mission_objective"), F.STREAMING_ANCHOR_INVALID))
    # --- CrossTileRoute ---
    c.append(("rt:navmesh_overclaim", RT, e._example_cross_tile_route(traversal_mode="grounded_navmesh"),
              F.STREAMING_NAVMESH_OVERCLAIM))
    c.append(("rt:failed_claims_pass", RT, e._example_cross_tile_route(traversal_mode="failed"),
              F.STREAMING_ROUTE_UNREACHABLE))
    c.append(("rt:single_tile_sequence", RT, e._example_cross_tile_route(
        tile_sequence=["tile_alpine_hub_entry"]), F.STREAMING_ROUTE_TILE_SEQUENCE_INVALID))
    c.append(("rt:no_transition_points", RT, e._example_cross_tile_route(stream_transition_points=[]),
              F.STREAMING_TRANSITION_POINT_INVALID))
    c.append(("rt:repeated_tile", RT, e._example_cross_tile_route(
        tile_sequence=["t_a", "t_a"], stream_transition_points=[{"x": 1}]),
        F.STREAMING_ROUTE_TILE_SEQUENCE_INVALID))
    # --- StreamedMissionBinding ---
    c.append(("mb:single_required_tile", MB, e._example_streamed_mission_binding(
        required_tile_ids=["tile_alpine_hub_entry"]), F.STREAMING_MISSION_BINDING_INVALID))
    c.append(("mb:no_required_routes", MB, e._example_streamed_mission_binding(
        required_cross_tile_routes=[]), F.STREAMING_ROUTE_INVALID))
    c.append(("mb:non_machine_claims", MB, e._example_streamed_mission_binding(
        runtime_claims_required=["reach the objective"]), F.STREAMING_MISSION_BINDING_INVALID))
    # --- StreamedNPCBinding ---
    c.append(("nb:pressure_escapes_allowed", NB, e._example_streamed_npc_binding(
        pressure_tile_scope=["tile_far_away"]), F.STREAMING_NPC_PRESSURE_MISSING))
    c.append(("nb:combat_escapes_allowed", NB, e._example_streamed_npc_binding(
        combat_tile_scope=["tile_far_away"]), F.STREAMING_COMBAT_EVIDENCE_MISSING))
    c.append(("nb:unknown_stream_policy", NB, e._example_streamed_npc_binding(
        stream_in_policy="warp_in"), F.STREAMING_NPC_BINDING_INVALID))
    # --- StreamingBudgetProfile ---
    c.append(("bp:zero_loaded_tiles", BP, e._example_streaming_budget_profile(max_loaded_tiles=0),
              F.STREAMING_BUDGET_PROFILE_INVALID))
    c.append(("bp:negative_memory", BP, e._example_streaming_budget_profile(max_memory_mb=-1),
              F.STREAMING_BUDGET_PROFILE_INVALID))
    # --- TileLifecycleReport ---
    c.append(("tl:active_no_load", TL, e._example_tile_lifecycle_report(load_completed=False),
              F.STREAMING_TILE_LOAD_MISSING))
    c.append(("tl:reload_state_lost", TL, e._example_tile_lifecycle_report(state_preserved=False),
              F.STREAMING_TILE_STATE_LOST))
    c.append(("tl:clean_budget_exceeded", TL, e._example_tile_lifecycle_report(budget_result="exceeded"),
              F.STREAMING_BUDGET_EXCEEDED))
    # --- StreamingRuntimeReport ---
    c.append(("sr:no_transition", SR, e._example_streaming_runtime_report(stream_transitions_seen=0),
              F.STREAMING_REQUIRED_TRANSITION_MISSING))
    c.append(("sr:single_tile", SR, e._example_streaming_runtime_report(
        tile_sequence_seen=["tile_alpine_hub_entry"]), F.STREAMING_MISSION_NOT_COMPLETED))
    c.append(("sr:no_route", SR, e._example_streaming_runtime_report(routes_completed=[]),
              F.STREAMING_REQUIRED_ROUTE_NOT_COMPLETED))
    c.append(("sr:save_failed_but_clean", SR, e._example_streaming_runtime_report(
        cross_tile_save_load_result="roundtrip_failed"), F.STREAMING_CROSS_TILE_SAVE_FAILED))
    c.append(("sr:budget_exceeded_but_clean", SR, e._example_streaming_runtime_report(
        budget_result="exceeded"), F.STREAMING_BUDGET_EXCEEDED))
    c.append(("sr:ue_streaming_overclaim", SR, e._example_streaming_runtime_report(
        runtime_mode="full_ue_streaming"), F.STREAMING_NAVMESH_OVERCLAIM))
    c.append(("sr:malformed_failure_code", SR, e._example_streaming_runtime_report(
        failure_codes=["NOT_A_CODE"]), F.STREAMING_UNKNOWN_FAILURE_CODE))
    # --- CrossTileSaveState ---
    c.append(("ss:roundtrip_no_hashes", SS, e._example_cross_tile_save_state(tile_state_hashes={}),
              F.STREAMING_CROSS_TILE_SAVE_MISSING))
    c.append(("ss:bad_roundtrip", SS, e._example_cross_tile_save_state(roundtrip_result="maybe"),
              F.STREAMING_CROSS_TILE_SAVE_FAILED))
    # --- StreamingEvidenceIndex ---
    c.append(("ei:partial_matrix", EI, e._example_streaming_evidence_index(scenario_count_seen=23),
              F.STREAMING_PARTIAL_MATRIX))
    c.append(("ei:stale_sha", EI, e._example_streaming_evidence_index(git_sha="unknown"),
              F.STREAMING_STALE_EVIDENCE))
    # --- OperatorRegionView ---
    c.append(("or:no_scenarios", OR, e._example_operator_region_view(streaming_scenarios=[]),
              F.STREAMING_OPERATOR_VIEW_INVALID))
    # --- OperatorTileView ---
    c.append(("ot:pass_no_lifecycle", OT, e._example_operator_tile_view(lifecycle_reports=[]),
              F.STREAMING_TILE_LOAD_MISSING))
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 streaming negative-fixture suite.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "streaming_negatives", strict=strict)
    cs = cases()
    rep.check("suite_nonempty", len(cs) >= 24,
              "negative suite must carry >= 24 fixtures (got {})".format(len(cs)),
              code=F.STREAMING_NEGATIVE_ACCEPTED)
    for label, validate, bad, owning in cs:
        fails = [ck for ck in validate(bad, strict=True) if not ck[1]]
        codes = {ck[3] for ck in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad fixture was ACCEPTED (fake green)", code=F.STREAMING_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::owning_code".format(label), owning in codes,
                  "must be rejected for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]), code=F.STREAMING_NEGATIVE_ACCEPTED)
    for name, (validate, good, _bad) in SC.CONTRACTS.items():
        gfails = [ck for ck in validate(good(), strict=True) if not ck[1]]
        rep.check("reverse::{}::valid_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([ck[0] for ck in gfails][:4]),
                  code=F.STREAMING_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="streaming-negative-fixtures", pack=None, strict=strict,
        status=rep.status, record_count=len(cs), records_total=len(cs),
        report_type="wf.streaming.negatives.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "streaming_negatives_report.json")
    rep.print_summary("streaming-negative-fixtures")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
