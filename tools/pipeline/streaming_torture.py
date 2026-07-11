#!/usr/bin/env python3
"""streaming_torture.py — v2.3 hostile torture battery (Wave R).

Proves the streaming honesty detectors reject the ways a streamed-region report can
fake success. Dogfood-based: constructs the hostile states in-code and asserts each
is caught for its OWNING code, certifying the DETECTORS (not the live evidence).
Each mode is the streaming form of a fake-green from handoff §7/§12.

Torture modes: disconnected region graph, self-neighbor tile, broken anchor link,
navmesh overclaim, failed route claiming pass, scenario completing with zero
transitions, tile active with no completed load, reload losing state, budget
exceeded reported clean, save/load claiming roundtrip with no tile hashes, NPC
pressure escaping allowed tiles, partial 23/24 matrix claiming full, stale git_sha,
full_ue_streaming overclaim, and a passing tile view with no lifecycle report.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/streaming_torture.py --strict
Reports -> procedural/reports/streaming/negatives/streaming_torture_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as e
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "negatives"


def modes():
    return [
        ("region_disconnected", e.validate_region_definition,
         e._example_region_definition(entry_tile_id="ghost"), F.STREAMING_TILE_GRAPH_DISCONNECTED),
        ("tile_self_neighbor", e.validate_tile_definition,
         e._example_tile_definition(neighbor_tile_ids=["tile_alpine_hub_entry"]),
         F.STREAMING_NEIGHBOR_NOT_RECIPROCAL),
        ("anchor_link_broken", e.validate_cross_tile_anchor,
         e._example_cross_tile_anchor(linked_anchor_ids=[]), F.STREAMING_ANCHOR_LINK_BROKEN),
        ("route_navmesh_overclaim", e.validate_cross_tile_route,
         e._example_cross_tile_route(traversal_mode="grounded_navmesh"), F.STREAMING_NAVMESH_OVERCLAIM),
        ("route_failed_claims_pass", e.validate_cross_tile_route,
         e._example_cross_tile_route(traversal_mode="failed"), F.STREAMING_ROUTE_UNREACHABLE),
        ("runtime_no_transition", e.validate_streaming_runtime_report,
         e._example_streaming_runtime_report(stream_transitions_seen=0),
         F.STREAMING_REQUIRED_TRANSITION_MISSING),
        ("runtime_single_tile", e.validate_streaming_runtime_report,
         e._example_streaming_runtime_report(tile_sequence_seen=["t_only"]),
         F.STREAMING_MISSION_NOT_COMPLETED),
        ("runtime_save_failed_clean", e.validate_streaming_runtime_report,
         e._example_streaming_runtime_report(cross_tile_save_load_result="roundtrip_failed"),
         F.STREAMING_CROSS_TILE_SAVE_FAILED),
        ("runtime_budget_exceeded_clean", e.validate_streaming_runtime_report,
         e._example_streaming_runtime_report(budget_result="exceeded"), F.STREAMING_BUDGET_EXCEEDED),
        ("runtime_ue_overclaim", e.validate_streaming_runtime_report,
         e._example_streaming_runtime_report(runtime_mode="full_ue_streaming"),
         F.STREAMING_NAVMESH_OVERCLAIM),
        ("lifecycle_active_no_load", e.validate_tile_lifecycle_report,
         e._example_tile_lifecycle_report(load_completed=False), F.STREAMING_TILE_LOAD_MISSING),
        ("lifecycle_reload_state_lost", e.validate_tile_lifecycle_report,
         e._example_tile_lifecycle_report(state_preserved=False), F.STREAMING_TILE_STATE_LOST),
        ("save_no_tile_hashes", e.validate_cross_tile_save_state,
         e._example_cross_tile_save_state(tile_state_hashes={}), F.STREAMING_CROSS_TILE_SAVE_MISSING),
        ("npc_pressure_escapes", e.validate_streamed_npc_binding,
         e._example_streamed_npc_binding(pressure_tile_scope=["tile_far"]),
         F.STREAMING_NPC_PRESSURE_MISSING),
        ("budget_zero_tiles", e.validate_streaming_budget_profile,
         e._example_streaming_budget_profile(max_loaded_tiles=0), F.STREAMING_BUDGET_PROFILE_INVALID),
        ("index_partial_matrix", e.validate_streaming_evidence_index,
         e._example_streaming_evidence_index(scenario_count_seen=23), F.STREAMING_PARTIAL_MATRIX),
        ("index_stale_sha", e.validate_streaming_evidence_index,
         e._example_streaming_evidence_index(git_sha="unknown"), F.STREAMING_STALE_EVIDENCE),
        ("tile_view_no_lifecycle", e.validate_operator_tile_view,
         e._example_operator_tile_view(lifecycle_reports=[]), F.STREAMING_TILE_LOAD_MISSING),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 streaming torture battery.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "streaming_torture", strict=strict)
    ms = modes()
    rep.check("torture::nonempty", len(ms) >= 14,
              "torture battery must carry >= 14 modes (got {})".format(len(ms)),
              code=F.STREAMING_TORTURE_FAILED)
    for label, validate, rec, owning in ms:
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("torture::{}::caught".format(label), len(fails) > 0,
                  "hostile state was ACCEPTED (fake green)", code=F.STREAMING_TORTURE_FAILED)
        rep.check("torture::{}::owning_code".format(label), owning in codes,
                  "must be caught for {} (got {})".format(owning, sorted(str(x) for x in codes)[:4]),
                  code=F.STREAMING_TORTURE_FAILED)
    rep.finalize()
    rep.set_meta(build_meta(
        command="streaming-torture", pack=None, strict=strict, status=rep.status,
        record_count=len(ms), records_total=len(ms), report_type="wf.streaming.torture.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "streaming_torture_report.json")
    rep.print_summary("streaming-torture")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
