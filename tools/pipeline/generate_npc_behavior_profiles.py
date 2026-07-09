#!/usr/bin/env python3
"""generate_npc_behavior_profiles.py — WorldForge v1.7 behavior-profile generator.

Emits one BehaviorProfile per v1.4 encounter archetype (all 8), mapping it to a
behavior profile kind and NPC archetype roster via npc_pack.ENCOUNTER_BEHAVIOR_MAP.
Every v1.4 archetype maps to behavior — none is silently unsupported (STRICT rule).

Acceptance: `make npc-behavior-profiles PACK=encounter_loop_world STRICT=1`.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
import npc_pack as NP
from npc_gen_common import run_generator
from report_meta import strict_from_env
from failure_codes import FailureCode


def build_profile(encounter_archetype):
    kind, roster = NP.ENCOUNTER_BEHAVIOR_MAP[encounter_archetype]
    return {
        "behavior_profile_id": NP.profile_id(kind) + "_" + encounter_archetype,
        "encounter_archetype": encounter_archetype, "pressure_profile": "standard_pressure",
        "npc_archetypes": list(roster), "profile_kind": kind,
        "spawn_group_rules": {"formation": "perimeter" if "guard" in kind else "scatter",
                              "walkability_required": True, "min_dist_objective": 400.0,
                              "min_dist_player_spawn": 1500.0},
        "route_rules": {"binding": "guard_anchor" if "guard" in kind else "patrol_segment",
                        "modes": ["grounded_worldforge_route", "grounded_manual_waypoint"],
                        "no_flight": True, "no_teleport": True, "no_block_mission_path": True},
        "perception_rules": {"detect_on": "engagement_radius", "lose_on": "disengagement_radius"},
        "engagement_rules": {"enter_state": "engaging", "hysteresis": True},
        "pressure_rules": {"kind": kind, "expires": True, "cooldown": True},
        "resolution_rules": {"on_pawn_leaves": "return_to_anchor", "expire_after": 60.0,
                             "resolved_state": "resolved"},
        "mission_completion_policy": "must_remain_possible_under_baseline",
        "save_load_policy": {"persist": ["current_state", "current_route_node", "pressure_state"]},
        "telemetry_requirements": ["behavior.npc.spawned", "behavior.npc.route.bound",
                                   "behavior.pressure.applied", "behavior.encounter.state_changed"],
        "balance_requirements": ["baseline_winnable", "pressure_events_seen", "no_permanent_route_block"],
        "created_by": NP.CREATED_BY, "created_at": NP.CREATED_AT,
        "schema_version": NX.BEHAVIOR_PROFILE_SCHEMA_VERSION,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    profiles = [build_profile(a) for a in NX.ENCOUNTER_ARCHETYPES]

    # Coverage: every required behavior profile kind is represented.
    kinds = {p["profile_kind"] for p in profiles}
    missing_kinds = [k for k in NX.BEHAVIOR_PROFILE_KINDS if k not in kinds]
    extra = [("profiles::all_encounter_archetypes_mapped",
              len(profiles) == len(NX.ENCOUNTER_ARCHETYPES), "not all 8 encounter archetypes mapped",
              FailureCode.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE),
             ("profiles::required_kinds_covered", not missing_kinds,
              "missing behavior profile kinds: {}".format(missing_kinds),
              FailureCode.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE)]

    run_generator("generate-npc-behavior-profiles", args.pack, profiles,
                  NX.validate_behavior_profile, NX.BEHAVIOR_PROFILE_GENERATED_REL,
                  "behavior_profile_id", "procedural/reports/npc/behavior_profiles",
                  "generate_npc_behavior_profiles_report.json", NX.RT_BEHAVIOR_PROFILE,
                  FailureCode.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE, strict=strict, extra_checks=extra)


if __name__ == "__main__":
    main()
