#!/usr/bin/env python3
"""tactical_spec.py — v2.4 shared tactical authoring spec (one source of truth).

Both the profile/role/affordance/binding generators and the authoring validators import
this so they agree on the 3 roles, 2 pressure profiles, the 24-scenario matrix, the
per-tile cover markers, and which real v2.3 anchors/routes each scenario binds to.
Keeping it here (not duplicated per generator) is what stops a binding from referencing
a cover marker no affordance map hosts, or a scenario from flanking a route the region
never defines.

Deterministic + bounded (handoff §3/§6): 2 v2.3 regions × 3 tactical roles × 2 pressure
profiles × 2 seeds = 24 tactical scenarios. Region geometry (tiles, anchors, routes) is
reused verbatim from streaming_spec — v2.4 layers tactical behavior over the real v2.3
streaming substrate, it does not re-invent it. Records are built on the tactical_contracts
_example_* factories with real overrides, so every emitted record is schema-conformant by
construction. No wall-clock, no randomness.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_spec as SS  # noqa: E402
import tactical_contracts as TC  # noqa: E402

ROLES = ("sentinel", "skirmisher", "suppressor")
PROFILE_IDS = ("baseline_tactical", "high_pressure_tactical")
SEEDS = (1, 2)
BUDGET_PROFILE_ID = "tac_budget_standard"

EXPECTED_SCENARIO_COUNT = 24  # 2 regions × 3 roles × 2 profiles × 2 seeds

# --------------------------------------------------------------------------- #
# Role definitions (handoff §6/§8.2) — bounded, per-role action/policy shape.
# --------------------------------------------------------------------------- #
_ROLE_SPECS = {
    "sentinel": {
        "display_key": "tactical.role.sentinel",
        "allowed_actions": ["hold_position", "use_cover", "leave_cover",
                            "protect_objective", "pressure_objective", "advance_to_anchor",
                            "retreat_to_anchor", "call_reinforcement", "disengage"],
        "preferred_actions": ["hold_position", "protect_objective", "use_cover"],
        "forbidden_actions": ["flank_via_route", "pursue_player", "break_pursuit"],
        "min_engagement_distance": 200.0, "max_engagement_distance": 4000.0,
        "cover_usage_policy": "prefer_cover", "retreat_policy": "fighting_withdrawal",
        "objective_policy": "protect", "group_policy": "coordinated_squad",
    },
    "skirmisher": {
        "display_key": "tactical.role.skirmisher",
        "allowed_actions": ["advance_to_anchor", "retreat_to_anchor", "flank_via_route",
                            "use_cover", "leave_cover", "pursue_player", "break_pursuit",
                            "pressure_objective", "disengage"],
        "preferred_actions": ["flank_via_route", "advance_to_anchor", "pursue_player"],
        "forbidden_actions": ["hold_position", "protect_objective", "call_reinforcement"],
        "min_engagement_distance": 400.0, "max_engagement_distance": 6000.0,
        "cover_usage_policy": "opportunistic_cover", "retreat_policy": "fighting_withdrawal",
        "objective_policy": "pressure", "group_policy": "loose_pack",
    },
    "suppressor": {
        "display_key": "tactical.role.suppressor",
        "allowed_actions": ["hold_position", "use_cover", "leave_cover",
                            "pressure_objective", "protect_objective", "advance_to_anchor",
                            "retreat_to_anchor", "call_reinforcement", "disengage"],
        "preferred_actions": ["pressure_objective", "use_cover", "hold_position"],
        "forbidden_actions": ["flank_via_route", "pursue_player", "break_pursuit"],
        "min_engagement_distance": 800.0, "max_engagement_distance": 8000.0,
        "cover_usage_policy": "prefer_cover", "retreat_policy": "retreat_when_low",
        "objective_policy": "pressure", "group_policy": "coordinated_squad",
    },
}

# --------------------------------------------------------------------------- #
# Pressure profiles (handoff §7) — everything bounded.
# --------------------------------------------------------------------------- #
_PROFILE_SPECS = {
    "baseline_tactical": {
        "aggression": 0.45, "cover_preference": 0.6, "flank_preference": 0.35,
        "retreat_health_threshold": 0.3, "objective_pressure_weight": 0.5,
        "reinforcement_threshold": 0.4, "decision_cadence_ms": 750,
        "max_active_tactical_npcs": 8, "max_decisions_per_minute": 80,
    },
    "high_pressure_tactical": {
        "aggression": 0.75, "cover_preference": 0.45, "flank_preference": 0.6,
        "retreat_health_threshold": 0.2, "objective_pressure_weight": 0.75,
        "reinforcement_threshold": 0.6, "decision_cadence_ms": 500,
        "max_active_tactical_npcs": 12, "max_decisions_per_minute": 140,
    },
}


def role_definition(role):
    spec = _ROLE_SPECS[role]
    return TC._example_tactical_role_definition(role_id=role, **spec)


def behavior_profile(profile_id):
    spec = _PROFILE_SPECS[profile_id]
    return TC._example_tactical_behavior_profile(
        profile_id="tac_profile_" + profile_id, tactical_pressure_profile=profile_id,
        roles_allowed=list(ROLES), budget_profile_id=BUDGET_PROFILE_ID, **spec)


def profile_id_for(profile):
    return "tac_profile_" + profile


# --------------------------------------------------------------------------- #
# Geometry helpers (reuse the real v2.3 anchor/route plan).
# --------------------------------------------------------------------------- #
def objective_tile(region):
    return region["mission_path"][1]


def entry_tile(region):
    return region["mission_path"][0]


def anchor_locations(region):
    return {a["anchor_id"]: a["world_location"] for a in SS.anchor_plan(region)}


def region_entry_anchor(region):
    return "anchor_{}_entry".format(region["region_id"])


def objective_anchor(region):
    return "anchor_{}_objective".format(objective_tile(region))


def npc_spawn_anchor(region):
    return "anchor_{}_npc".format(objective_tile(region))


def retreat_transition_anchor(region):
    # transition anchor on the objective tile that leads back toward the entry tile.
    a = entry_tile(region)
    b = objective_tile(region)
    return "anchor_{}_from_{}".format(b, SS._short(a))


def flank_route(region):
    return SS.mission_route_id(region)


def cover_markers(region):
    """Deterministic per-objective-tile cover markers (the source of truth for cover ids).

    Not third-party cover assets — bounded generated cover markers (handoff §8.3), each a
    stable {cover_id, location} the NPC bindings and affordance maps both reference.
    """
    tile = objective_tile(region)
    specs = SS.tile_specs(region)
    c = SS.tile_center(specs[tile]["grid"])
    offsets = [(-1500.0, 800.0), (1200.0, -600.0), (300.0, 1800.0)]
    out = []
    for i, (dx, dy) in enumerate(offsets):
        out.append({"cover_id": "cover_{}_{:02d}".format(tile, i),
                    "location": [c[0] + dx, c[1] + dy, c[2] + 48.0]})
    return out


def cover_ids(region):
    return [cp["cover_id"] for cp in cover_markers(region)]


# --------------------------------------------------------------------------- #
# The 24-scenario matrix.
# --------------------------------------------------------------------------- #
def scenario_plan():
    """2 regions × 3 roles × 2 pressure profiles × 2 seeds = 24 tactical scenarios."""
    out = []
    for region in SS.REGIONS:
        rid = region["region_id"]
        for role in ROLES:
            for profile in PROFILE_IDS:
                for seed in SEEDS:
                    sid = "tac_{}_{}_{}_s{}".format(rid, role, profile, seed)
                    out.append({
                        "scenario_id": sid,
                        "region_id": rid,
                        "role": role,
                        "profile": profile,
                        "profile_id": profile_id_for(profile),
                        "seed": seed,
                        "biome": region["biome"],
                        "streaming_profile": region["streaming_profile"],
                        "objective_tile_id": objective_tile(region),
                        "entry_tile_id": entry_tile(region),
                        "path_tiles": list(region["mission_path"]),
                        "spawn_anchor_id": npc_spawn_anchor(region),
                        "objective_anchor_id": objective_anchor(region),
                        "entry_anchor_id": region_entry_anchor(region),
                        "retreat_anchor_id": retreat_transition_anchor(region),
                        "flank_route_id": flank_route(region),
                        "cover_ids": cover_ids(region),
                    })
    return out


def region_of(scenario):
    return SS.region_by_id(scenario["region_id"])


# --------------------------------------------------------------------------- #
# Affordance map (one per scenario, over the scenario's objective tile).
# --------------------------------------------------------------------------- #
def affordance_for(scenario):
    region = region_of(scenario)
    tile = scenario["objective_tile_id"]
    locs = anchor_locations(region)
    specs = SS.tile_specs(region)
    c = SS.tile_center(specs[tile]["grid"])
    obj_loc = locs.get(scenario["objective_anchor_id"], c)
    route = scenario["flank_route_id"]
    # streaming transition zone from the mission route's boundary midpoint.
    stz = []
    for rp in SS.route_plan(region):
        if rp["route_id"] == route:
            for tp in rp["stream_transition_points"]:
                stz.append({"transition_id": "stz_" + route, "location": tp["location"]})
    return TC._example_tactical_affordance_map(
        affordance_map_id="afm_" + scenario["scenario_id"],
        region_id=scenario["region_id"],
        tile_id=tile,
        scenario_id=scenario["scenario_id"],
        cover_points=cover_markers(region),
        vantage_points=[{"vantage_id": "vp_{}_ridge".format(tile),
                         "location": [c[0], c[1] + 4000.0, c[2] + 512.0]}],
        retreat_anchors=[scenario["retreat_anchor_id"], scenario["entry_anchor_id"]],
        flank_routes=[route],
        objective_pressure_points=[{"point_id": "opp_" + scenario["objective_anchor_id"],
                                    "location": obj_loc}],
        line_of_sight_zones=[{"zone_id": "los_{}_open".format(tile),
                              "location": [c[0], c[1], c[2] + 128.0], "radius": 3000.0}],
        hazard_zones=[{"hazard_id": "hz_{}_field".format(tile),
                       "location": [c[0] - 2000.0, c[1] - 2000.0, c[2]], "radius": 800.0}],
        streaming_transition_zones=stz,
        source_reports=[
            "procedural/generated/regions/{}.json".format(scenario["region_id"]),
            "procedural/generated/tiles/{}.json".format(tile),
            "procedural/generated/routes/{}.json".format(route),
        ],
    )
