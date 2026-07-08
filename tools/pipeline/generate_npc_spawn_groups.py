#!/usr/bin/env python3
"""generate_npc_spawn_groups.py — WorldForge v1.7 NPC spawn-group generator.

For every v1.4 encounter, maps its encounter spawn_groups to strict NPCSpawnGroup
records: NPC archetypes resolved from the encounter archetype roster, spawn anchors
taken from the encounter's real spawn/patrol/ambush/hazard anchors, count from the
encounter count band, and distances/policies set so placement is walkability-driven
and never spawns on the mission route, at the player start, or in the objective
interaction radius. Binds to the grounded route substrate — no flight/teleport.

Acceptance: `make npc-spawn-groups PACK=encounter_loop_world STRICT=1`.
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

# encounter archetype -> spawn zone / formation / route binding policy.
_ROUTE_BINDING = {
    "guarded_objective": "guard_anchor", "patrol_route": "patrol_segment",
    "ambush_choke": "ambush_volume", "hazard_field": "hazard_zone",
    "resource_contest": "guard_anchor", "defensive_holdout": "guard_anchor",
    "roaming_threat": "roam_zone", "extraction_pressure": "guard_anchor",
}
_FORMATION = {
    "guarded_objective": "perimeter", "patrol_route": "line", "ambush_choke": "cluster",
    "hazard_field": "scatter", "resource_contest": "perimeter", "defensive_holdout": "perimeter",
    "roaming_threat": "scatter", "extraction_pressure": "perimeter",
}


def _anchor_ids_for(enc, encounter_archetype):
    """Pick the encounter's real anchors appropriate to the archetype behavior."""
    def ids(key):
        return [a.get("id") for a in enc.get(key, []) if isinstance(a, dict) and a.get("id")]
    if encounter_archetype == "patrol_route" or encounter_archetype == "roaming_threat":
        picked = ids("patrol_anchors") or ids("spawn_anchors")
    elif encounter_archetype == "ambush_choke":
        picked = ids("ambush_anchors") or ids("spawn_anchors")
    elif encounter_archetype == "hazard_field":
        picked = [z.get("id") for z in enc.get("hazard_zones", []) if isinstance(z, dict) and z.get("id")] \
            or ids("spawn_anchors")
    else:
        picked = ids("spawn_anchors")
    return picked or ids("spawn_anchors")


def build_spawn_groups(pack):
    groups = []
    for eid, enc in NP.iter_encounters(pack):
        earch = enc.get("encounter_archetype")
        if earch not in NP.ENCOUNTER_BEHAVIOR_MAP:
            continue
        kind, roster = NP.ENCOUNTER_BEHAVIOR_MAP[earch]
        profile = enc.get("encounter_profile", "standard_pressure")
        for i, eg in enumerate(enc.get("spawn_groups", [])):
            anchors = eg.get("spawn_anchor_ids") or _anchor_ids_for(enc, earch)
            if not anchors:
                continue
            count = int(eg.get("count_min") or 1)
            count = max(1, min(count, len(anchors)))  # never exceed anchor budget
            map_id = (enc.get("mission_id") or "").replace("mission_", "") or eid.split("_", 2)[-1]
            groups.append({
                "spawn_group_id": "sg_{}_{}".format(eid, i),
                "encounter_id": eid, "mission_id": enc.get("mission_id"),
                "map_id": map_id, "biome": enc.get("biome_family"),
                "pressure_profile": profile,
                "npc_archetype_ids": [NP.archetype_id(r) for r in roster],
                "spawn_anchor_ids": list(anchors), "count": count,
                "formation_policy": _FORMATION.get(earch, "scatter"),
                "route_binding_policy": _ROUTE_BINDING.get(earch, "guard_anchor"),
                "spawn_zone_policy": "walkable_off_route", "max_density": 1.0,
                "min_distance_from_objective": 400.0, "min_distance_from_player_spawn": 1500.0,
                "route_clearance_required": True, "walkability_required": True,
                "save_load_required": True,
                "validation_requirements": ["spawn_walkable", "not_on_route", "not_near_objective",
                                            "not_near_player_start", "density_within_budget"],
                "behavior_profile_id": NP.profile_id(kind) + "_" + earch,
                "created_by": NP.CREATED_BY, "created_at": NP.CREATED_AT,
                "schema_version": NX.SPAWN_GROUP_SCHEMA_VERSION,
            })
    return groups


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    groups = build_spawn_groups(args.pack)
    run_generator("generate-npc-spawn-groups", args.pack, groups, NX.validate_spawn_group,
                  NX.SPAWN_GROUP_GENERATED_REL, "spawn_group_id",
                  "procedural/reports/npc/spawn_groups", "generate_npc_spawn_groups_report.json",
                  NX.RT_SPAWN_GROUP, FailureCode.NPC_SPAWN_GROUP_SCHEMA_FAILURE, strict=strict)


if __name__ == "__main__":
    main()
