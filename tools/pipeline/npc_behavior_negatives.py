#!/usr/bin/env python3
"""npc_behavior_negatives.py — WorldForge v1.7 NPCForge negative-fixture gate.

Known-bad NPC/behavior inputs must be REJECTED, and rejected for the RIGHT owning
failure code — a validator that fails for the wrong reason is not real coverage.
Covers the contract / spawn / route / perception / pressure / runtime-fake-green
negatives the v1.7 brief enumerates.

Acceptance: `make npc-negative-validators STRICT=1`.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
import npc_pack as NP
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F


def without(d, *keys):
    d = dict(d)
    for k in keys:
        d.pop(k, None)
    return d


def _tel_complete_missing_pressure():
    events = [t for t in NX.COMPLETION_REQUIRED_EVENTS if t != "behavior.pressure.applied"]
    return {"events": [{"event_type": t} for t in events]}


def cases():
    A, SG, PM, PR = (NX._example_archetype, NX._example_spawn_group,
                     NX._example_perception, NX._example_pressure)
    BP, SC, CMP = NX._example_behavior_profile, NX._example_behavior_scenario, NX._example_completion
    v_tel = lambda o, strict=False: NX.validate_telemetry(o, strict=strict, require_completion=True)
    return [
        # ---- contract negatives ----
        ("archetype_missing_movement_model", NX.validate_archetype,
         without(A(), "movement_model"), F.NPC_ARCHETYPE_SCHEMA_FAILURE),
        ("archetype_missing_perception_model", NX.validate_archetype,
         A(perception_model=""), F.NPC_ARCHETYPE_SCHEMA_FAILURE),
        ("archetype_unknown_field_strict", NX.validate_archetype,
         dict(A(), bogus_field=1), F.NPC_ARCHETYPE_SCHEMA_FAILURE),
        ("spawn_group_empty_archetypes", NX.validate_spawn_group,
         SG(npc_archetype_ids=[]), F.NPC_SPAWN_GROUP_SCHEMA_FAILURE),
        ("profile_unknown_encounter_archetype", NX.validate_behavior_profile,
         BP(encounter_archetype="not_an_archetype"), F.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE),
        ("scenario_missing_save_load", NX.validate_behavior_scenario,
         without(SC(), "save_load_required"), F.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE),
        ("scenario_missing_ground_ref", NX.validate_behavior_scenario,
         SC(ground_scenario_id=""), F.NPC_ROUTE_GRAPH_MISSING),
        ("behavior_state_unknown_state", NX.validate_behavior_state,
         NX._example_behavior_state(current_state="teleporting"), F.NPC_ENCOUNTER_STATE_FAILURE),
        # ---- spawn negatives ----
        ("spawn_group_walkability_not_required", NX.validate_spawn_group,
         SG(walkability_required=False), F.NPC_SPAWN_OFF_WALKABLE_SURFACE),
        ("spawn_group_no_anchors", NX.validate_spawn_group,
         SG(spawn_anchor_ids=[]), F.NPC_SPAWN_POINT_MISSING),
        ("spawn_group_exceeds_density", NX.validate_spawn_group,
         SG(count=9, spawn_anchor_ids=["a0"], max_density=1.0), F.NPC_DENSITY_BUDGET_FAILURE),
        # ---- route binding negatives ----
        ("archetype_route_requires_flight", NX.validate_archetype,
         A(allowed_route_modes=["continuous_flight"]), F.NPC_ROUTE_FLIGHT_REQUIRED),
        ("archetype_route_requires_teleport", NX.validate_archetype,
         A(allowed_route_modes=["teleport"]), F.NPC_ROUTE_FLIGHT_REQUIRED),
        ("archetype_can_block_but_policy_never_violated", NX.validate_archetype,
         A(can_block_route=False, route_blocking_policy="guard_zone_only"), F.NPC_ROUTE_BLOCKS_MISSION_PATH),
        # ---- perception negatives ----
        ("perception_los_no_occlusion", NX.validate_perception_model,
         PM(line_of_sight_required=True, occlusion_policy="none"), F.NPC_PERCEPTION_FAILURE),
        ("perception_detect_threshold_invalid", NX.validate_perception_model,
         PM(detection_threshold=1.5), F.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE),
        ("perception_fov_invalid", NX.validate_perception_model,
         PM(field_of_view_degrees=0), F.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE),
        ("perception_loss_gt_detect", NX.validate_perception_model,
         PM(detection_threshold=0.4, loss_threshold=0.9), F.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE),
        # ---- pressure negatives ----
        ("pressure_no_events", NX.validate_pressure_model,
         PR(telemetry_events=[]), F.NPC_PRESSURE_MODEL_SCHEMA_FAILURE),
        ("pressure_never_expires", NX.validate_pressure_model,
         PR(max_pressure_duration=0), F.NPC_PRESSURE_FAILURE),
        ("pressure_too_low_nontelemetry", NX.validate_pressure_model,
         PR(pressure_type="contact_pressure", pressure_value=0.0), F.NPC_PRESSURE_TOO_LOW),
        # ---- runtime fake-green negatives (completion report) ----
        ("completion_zero_npcs_success", NX.validate_completion_report,
         CMP(npc_count=0), F.NPC_ACTOR_MISSING),
        ("completion_zero_pressure_success", NX.validate_completion_report,
         CMP(pressure_events_seen=0), F.NPC_NO_PRESSURE_EVENTS),
        ("completion_no_telemetry_success", NX.validate_completion_report,
         CMP(telemetry_path=""), F.NPC_TELEMETRY_MISSING),
        ("completion_save_load_skipped_success", NX.validate_completion_report,
         CMP(save_load_result="skipped"), F.NPC_SAVE_LOAD_FAILURE),
        ("completion_mission_not_done_success", NX.validate_completion_report,
         CMP(mission_completed=False), F.NPC_MISSION_COMPLETION_BLOCKED),
        ("telemetry_complete_missing_pressure", v_tel,
         _tel_complete_missing_pressure(), F.NPC_NO_PRESSURE_EVENTS),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "npc_behavior_negatives", strict=strict)

    # Function-level negatives: an anchor inside collision / not valid_spawn is not placeable.
    rep.check("neg::anchor_inside_collision_rejected",
              NP.anchor_is_placeable({"world_position": [0, 0, 0], "collision": True}) is False,
              "an anchor flagged inside collision must not be placeable", code=F.NPC_SPAWN_INSIDE_COLLISION)
    rep.check("neg::anchor_off_walkable_rejected",
              NP.anchor_is_placeable({"world_position": [0, 0, 0], "valid_spawn": False}) is False,
              "a valid_spawn=false anchor must not be placeable", code=F.NPC_SPAWN_OFF_WALKABLE_SURFACE)
    rep.check("neg::anchor_no_position_rejected",
              NP.anchor_is_placeable({"kind": "spawn"}) is False,
              "an anchor with no world position must not be placeable", code=F.NPC_SPAWN_POINT_MISSING)

    cs = cases()
    for label, fn, bad, code in cs:
        fails = [c for c in fn(bad, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad '{}' must be rejected".format(label), code=code)
        rep.check("neg::{}::owning_code".format(label), code in codes,
                  "'{}' rejected for owning code {} (got {})".format(label, code, sorted(codes)[:3]),
                  code=code)

    rep.finalize()
    rep.set_meta(build_meta(command="npc-negative-validators", pack="encounter_loop_world",
                            strict=strict, status=rep.status, record_count=len(cs) + 3,
                            report_type="wf.npc.negatives.v1"))
    rep.write(REPO_ROOT / "procedural/reports/npc/negatives", "npc_behavior_negatives_report.json")
    rep.print_summary("npc-negative-validators")
    print("[npc-negative-validators] {} negative fixtures, each rejected for its owning code".format(len(cs) + 3))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
