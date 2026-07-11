#!/usr/bin/env python3
"""streaming_spec.py — v2.3 shared streaming authoring spec (one source of truth).

Both the region/anchor/route/binding generators and the authoring validators import
this so they agree on the 2 region layouts, the tile graph, the anchor plan, the
cross-tile route plan, and the 24-scenario matrix. Keeping it here (not duplicated
per generator) is what stops a route from crossing a tile the region never defines,
or a binding from requiring an anchor no tile hosts.

Deterministic + bounded (handoff §7): 2 regions (hub_spoke + linear_chain), 3 tiles
each, no wall-clock, no randomness. Region A = 1 hub + 2 objective spokes; Region B
= entry -> objective -> exit linear chain. Both give a 2-tile mission crossing with
exactly one stream transition — expressible under either streaming profile.
"""

TILE_SIZE = [25600.0, 25600.0, 8192.0]

# Region plans. Each tile: (tile_id, role, map_id, [source_scenario_ids], grid[x,y]).
REGIONS = [
    {
        "region_id": "region_alpine_hub",
        "region_name": "Alpine Glacial Hub",
        "layout": "hub_spoke",
        "biome": "alpine_snow",
        "streaming_profile": "hub_to_spoke_transition",
        "seed": 1,
        "tiles": [
            ("tile_alpine_hub_entry", "hub", "Alpine_GlacialBasin_Debris_Photoreal_01",
             ["vs_alpine_snow_survey_landmark_baseline_s1"], [0, 0], True, False),
            ("tile_alpine_objective_a", "objective", "Alpine_GlacialBasin_Scatter_Perf_01",
             ["vs_alpine_snow_recover_resource_baseline_s1"], [1, 0], False, False),
            ("tile_alpine_objective_b", "objective", "Alpine_SnowyRidge_Debris_Photoreal_01",
             ["vs_alpine_snow_clear_hazard_baseline_s1"], [0, 1], False, True),
        ],
        # hub_spoke: hub connects to both spokes.
        "adjacencies": [("tile_alpine_hub_entry", "tile_alpine_objective_a"),
                        ("tile_alpine_hub_entry", "tile_alpine_objective_b")],
        # entry -> first objective is the canonical 2-tile mission path.
        "mission_path": ("tile_alpine_hub_entry", "tile_alpine_objective_a"),
    },
    {
        "region_id": "region_volcanic_chain",
        "region_name": "Ashlands Basalt Chain",
        "layout": "linear_chain",
        "biome": "volcanic_ashlands",
        "streaming_profile": "adjacent_tile_crossing",
        "seed": 2,
        "tiles": [
            ("tile_volcanic_entry", "entry", "Ashlands_AshRavine_Debris_Photoreal_01",
             ["vs_volcanic_ashlands_survey_landmark_baseline_s1"], [0, 0], True, False),
            ("tile_volcanic_objective", "objective", "Ashlands_BasaltFlats_Debris_Photoreal_01",
             ["vs_volcanic_ashlands_recover_resource_baseline_s1"], [1, 0], False, False),
            ("tile_volcanic_exit", "exit", "Ashlands_AshRavine_Scar_Perf_01",
             ["vs_volcanic_ashlands_clear_hazard_baseline_s1"], [2, 0], False, True),
        ],
        "adjacencies": [("tile_volcanic_entry", "tile_volcanic_objective"),
                        ("tile_volcanic_objective", "tile_volcanic_exit")],
        "mission_path": ("tile_volcanic_entry", "tile_volcanic_objective"),
    },
]

MISSION_ARCHETYPES = ("survey_landmark", "recover_resource", "clear_hazard")
STREAMING_PROFILES = ("adjacent_tile_crossing", "hub_to_spoke_transition")
SEEDS = (1, 2)
BUDGET_PROFILE_ID = "budget_standard"


def tile_center(grid):
    return [grid[0] * TILE_SIZE[0] + TILE_SIZE[0] / 2,
            grid[1] * TILE_SIZE[1] + TILE_SIZE[1] / 2, 512.0]


def tile_origin(grid):
    return [grid[0] * TILE_SIZE[0], grid[1] * TILE_SIZE[1], 0.0]


def _short(tile_id):
    return tile_id.rsplit("_", 1)[-1]


def region_by_id(region_id):
    for r in REGIONS:
        if r["region_id"] == region_id:
            return r
    return None


def tile_specs(region):
    """Return {tile_id: dict(role,map_id,source_scenarios,grid,is_entry,is_exit)}."""
    out = {}
    for tid, role, map_id, srcs, grid, is_entry, is_exit in region["tiles"]:
        out[tid] = {"role": role, "map_id": map_id, "source_scenarios": srcs,
                    "grid": grid, "is_entry": is_entry, "is_exit": is_exit}
    return out


def neighbors(region):
    """Reciprocal neighbor map derived from adjacencies."""
    nb = {t[0]: [] for t in region["tiles"]}
    for a, b in region["adjacencies"]:
        nb[a].append(b)
        nb[b].append(a)
    return nb


def anchor_plan(region):
    """Deterministic per-region anchor specs (list of dicts)."""
    specs = tile_specs(region)
    plan = []

    def add(anchor_id, tile_id, atype, loc, linked, route_role="none",
            mission_role="none", npc_role="none"):
        plan.append({
            "anchor_id": anchor_id, "region_id": region["region_id"], "tile_id": tile_id,
            "anchor_type": atype, "tile_role": specs[tile_id]["role"],
            "world_location": [float(x) for x in loc], "linked_anchor_ids": list(linked),
            "route_role": route_role, "mission_role": mission_role, "npc_role": npc_role,
            "save_load_key": "sl_" + anchor_id})

    for tid, sp in specs.items():
        c = tile_center(sp["grid"])
        if sp["is_entry"]:
            add("anchor_{}_entry".format(region["region_id"]), tid, "entry",
                [c[0] - 4000, c[1], c[2]], [], route_role="region_entry")
        # npc_spawn only on tiles whose role permits it (exit-role tiles do not).
        if sp["role"] in ("entry", "hub", "route", "objective", "hazard"):
            add("anchor_{}_npc".format(tid), tid, "npc_spawn",
                [c[0] + 2000, c[1] + 2000, c[2]], [], npc_role="spawn")
        add("anchor_{}_save".format(tid), tid, "save_checkpoint",
            [c[0], c[1] - 3000, c[2]], [])
        if sp["role"] in ("hub", "objective"):
            add("anchor_{}_objective".format(tid), tid, "mission_objective",
                [c[0], c[1], c[2]], [], mission_role="objective")
        # exit-type anchor only on tiles whose role hosts it (exit/hub roles).
        if sp["is_exit"] and sp["role"] in ("exit", "hub"):
            add("anchor_{}_exit".format(tid), tid, "exit",
                [c[0] + 4000, c[1], c[2]], [], route_role="region_exit")

    # transition anchor pairs (reciprocal) at each boundary.
    for a, b in region["adjacencies"]:
        ca, cb = tile_center(specs[a]["grid"]), tile_center(specs[b]["grid"])
        mid = [(ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2, (ca[2] + cb[2]) / 2]
        a_anchor = "anchor_{}_to_{}".format(a, _short(b))
        b_anchor = "anchor_{}_from_{}".format(b, _short(a))
        add(a_anchor, a, "transition", mid, [b_anchor], route_role="transition_out")
        add(b_anchor, b, "transition", mid, [a_anchor], route_role="transition_in")
    return plan


def route_plan(region):
    """Deterministic per-region cross-tile route specs (list of dicts)."""
    specs = tile_specs(region)
    plan = []
    for a, b in region["adjacencies"]:
        ca, cb = tile_center(specs[a]["grid"]), tile_center(specs[b]["grid"])
        mid = [(ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2, (ca[2] + cb[2]) / 2]
        length = abs(cb[0] - ca[0]) + abs(cb[1] - ca[1])
        a_anchor = "anchor_{}_to_{}".format(a, _short(b))
        b_anchor = "anchor_{}_from_{}".format(b, _short(a))
        plan.append({
            "route_id": "route_{}_to_{}".format(_short(a), _short(b)),
            "region_id": region["region_id"], "source_anchor_id": a_anchor,
            "target_anchor_id": b_anchor, "tile_sequence": [a, b],
            "route_segments": [{"from": a_anchor, "to": b_anchor, "length": length}],
            "stream_transition_points": [{"at_tile_boundary": [a, b], "location": mid}],
        })
    return plan


def mission_route_id(region):
    a, b = region["mission_path"]
    return "route_{}_to_{}".format(_short(a), _short(b))


def scenario_plan():
    """The 24-scenario matrix: 2 regions × 3 archetypes × 2 profiles × 2 seeds."""
    out = []
    for region in REGIONS:
        rid = region["region_id"]
        a, b = region["mission_path"]
        for archetype in MISSION_ARCHETYPES:
            for profile in STREAMING_PROFILES:
                for seed in SEEDS:
                    sid = "st_{}_{}_{}_s{}".format(rid, archetype, profile, seed)
                    out.append({
                        "scenario_id": sid, "region_id": rid, "mission_archetype": archetype,
                        "streaming_profile": profile, "seed": seed,
                        "path_tiles": [a, b], "route_id": mission_route_id(region),
                        "start_anchor_id": ("anchor_{}_entry".format(rid)
                                            if region["tiles"][0][5] else "anchor_{}_objective".format(a)),
                        "objective_anchor_id": "anchor_{}_objective".format(b),
                        "npc_spawn_anchor_id": "anchor_{}_npc".format(b),
                        "biome": region["biome"],
                    })
    return out
