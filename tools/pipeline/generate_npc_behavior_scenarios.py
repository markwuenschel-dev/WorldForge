#!/usr/bin/env python3
"""generate_npc_behavior_scenarios.py — WorldForge v1.7 behavior-scenario generator.

Produces the behavior scenario matrix: one BehaviorScenario per v1.4 encounter,
each grounded on the v1.6z route plan whose scenario_id is
rt_<encounter_id>__<pressure_profile>. That link makes NPC movement bind to the
validated grounded_worldforge_route substrate — never flight, never teleport. Each
scenario references its spawn groups + behavior profile and declares the NPC
states, perception/pressure events, and encounter-state transitions the runtime
must produce, plus that mission completion remains possible under baseline pressure.

Acceptance: `make npc-behavior-scenarios PACK=encounter_loop_world STRICT=1`.
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


def build_scenarios(pack):
    plans = NP.load_route_plans()
    scenarios = []
    for eid, enc in NP.iter_encounters(pack):
        earch = enc.get("encounter_archetype")
        if earch not in NP.ENCOUNTER_BEHAVIOR_MAP:
            continue
        kind, _ = NP.ENCOUNTER_BEHAVIOR_MAP[earch]
        profile = enc.get("encounter_profile", "standard_pressure")
        sid, plan = NP.route_plan_for_encounter(plans, eid, profile)
        # ground_scenario_id must reference a real, valid grounded route plan.
        if plan is None:
            # Emit a scenario that fails its own contract check (ground ref missing)
            # so the generator surfaces the gap rather than silently dropping it.
            ground_ref = ""
        else:
            ground_ref = sid
        map_id = enc.get("mission_id", "").replace("mission_", "") or eid.replace("enc_lp_", "")
        n_groups = len(enc.get("spawn_groups", []))
        spawn_group_ids = ["sg_{}_{}".format(eid, i) for i in range(max(1, n_groups))]
        scenarios.append({
            "behavior_scenario_id": "bs_{}__{}".format(eid, profile),
            "runtime_scenario_id": sid, "ground_scenario_id": ground_ref,
            "pack": pack, "map_id": map_id, "mission_id": enc.get("mission_id"),
            "encounter_id": eid, "biome": enc.get("biome_family"),
            "mission_archetype": enc.get("mission_archetype"), "pressure_profile": profile,
            "seed": int(enc.get("seed", 0)),
            "spawn_groups": spawn_group_ids,
            "behavior_profiles": [NP.profile_id(kind) + "_" + earch],
            "expected_npc_states": ["spawned", "idle", "alerted", "engaging", "pressuring", "resolved"],
            "expected_perception_events": ["behavior.perception.checked", "behavior.perception.detected"],
            "expected_pressure_events": ["behavior.pressure.applied", "behavior.pressure.expired"],
            "expected_encounter_state_transitions": ["idle->alerted", "alerted->pressuring",
                                                     "pressuring->resolved"],
            "expected_mission_completion": True, "save_load_required": True,
            "timeout_seconds": 180.0,
            "validation_requirements": ["telemetry", "route_binding", "perception", "pressure",
                                        "mission_completion", "save_load", "no_permanent_block"],
            "created_by": NP.CREATED_BY, "created_at": NP.CREATED_AT,
            "schema_version": NX.BEHAVIOR_SCENARIO_SCHEMA_VERSION,
        })
    return scenarios


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    scenarios = build_scenarios(args.pack)
    # Matrix-integrity: every scenario must ground on a real route plan (no silent drop).
    grounded = sum(1 for s in scenarios if s["ground_scenario_id"])
    extra = [("scenarios::all_grounded", grounded == len(scenarios),
              "{}/{} scenarios lack a grounded route plan".format(len(scenarios) - grounded, len(scenarios)),
              FailureCode.NPC_ROUTE_GRAPH_MISSING)]

    run_generator("generate-npc-behavior-scenarios", args.pack, scenarios,
                  NX.validate_behavior_scenario, NX.BEHAVIOR_SCENARIO_GENERATED_REL,
                  "behavior_scenario_id", "procedural/reports/npc/behavior_scenarios",
                  "generate_npc_behavior_scenarios_report.json", NX.RT_SCENARIO_MANIFEST,
                  FailureCode.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE, strict=strict, extra_checks=extra)


if __name__ == "__main__":
    main()
