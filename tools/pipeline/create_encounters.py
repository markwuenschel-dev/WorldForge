#!/usr/bin/env python3
"""create_encounters.py — v1.4 EncounterForge generator.

Generates the 120 encounter-enabled mission loops of encounter_loop_world:
60 v1.3 missions x 2 encounter profiles, across 8 encounter archetypes.
Every encounter is bound to one mission's routes/anchors/zones, carries a
full spawn/state/reward/save-load/playtest contract, and is fitted to its
profile's pressure budget and difficulty-band target at generation time —
no silent fallback: an encounter that cannot fit its band is a hard failure.

Deterministic: rng is seeded from the mission seed + profile index only.
"""

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import (compute_input_hash, load_encounter_catalog,
                               save_encounter_catalog, upsert_encounter)
from failure_codes import FailureCode
from mesh_catalog import load_mesh_catalog
from mission_catalog import load_mission_catalog
from report_meta import build_meta, hash_obj, strict_from_env
from validation_report import ValidationReport

GENERATOR = "create_encounters"
GENERATOR_VERSION = "1.4.0"

# (mission_archetype, profile) -> encounter_archetype. Covers all 8 archetypes;
# resource_contest only binds to missions that carry resource nodes.
PAIRING = {
    ("disable_site", "light_pressure"): "guarded_objective",
    ("disable_site", "standard_pressure"): "defensive_holdout",
    ("recover_resource", "light_pressure"): "resource_contest",
    ("recover_resource", "standard_pressure"): "extraction_pressure",
    ("survey_landmark", "light_pressure"): "patrol_route",
    ("survey_landmark", "standard_pressure"): "roaming_threat",
    ("clear_hazard", "light_pressure"): "hazard_field",
    ("clear_hazard", "standard_pressure"): "ambush_choke",
    ("restore_power", "light_pressure"): "guarded_objective",
    ("restore_power", "standard_pressure"): "defensive_holdout",
    ("extract_cache", "light_pressure"): "ambush_choke",
    ("extract_cache", "standard_pressure"): "extraction_pressure",
}

PROFILE_SHORT = {"light_pressure": "lp", "standard_pressure": "sp"}
PLAYTEST_BETA_MODES = (
    "route_playtest", "anchor_playtest", "state_transition_playtest",
    "save_load_playtest", "budget_safe_playtest", "encounter_pressure_playtest",
    "encounter_resolution_playtest", "pacing_playtest",
)
MAX_BAND_FOR_PROFILE = {"light_pressure": "standard", "standard_pressure": "hard"}


def _lerp(a, b, t):
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 0.0]


def _perp(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return (-dy / n, dx / n)


def _offset(pt, perp, dist):
    return [pt[0] + perp[0] * dist, pt[1] + perp[1] * dist, 0.0]


def _bounds_around(points, pad):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {"min": [min(xs) - pad, min(ys) - pad, 0.0],
            "max": [max(xs) + pad, max(ys) + pad, 1200.0]}


def _route_entry(rid, kind, waypoints):
    length = sum(MC.dist2d(waypoints[i - 1], waypoints[i])
                 for i in range(1, len(waypoints)))
    return {"route_id": rid, "kind": kind,
            "waypoints": [list(w) for w in waypoints],
            "length_cm": round(length, 2)}


def _source_hash(*parts):
    return "sha256:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def build_encounter(mission, profile, arch_spec, mesh_assets, rng):
    mid = mission["mission_id"]
    biome = mission["biome_family"]
    m_arch = mission["mission_archetype"]
    e_arch = PAIRING[(m_arch, profile)]
    eid = "enc_{}_{}".format(PROFILE_SHORT[profile], mid[len("mission_"):])

    start = mission["start_anchor"]["world_position"]
    objective_anchor = mission["objective_anchors"][0]
    objective = objective_anchor["world_position"]
    route_wp = mission["required_route"]["waypoints"]
    a, b = route_wp[0], route_wp[-1]
    perp = _perp(a, b)

    n_groups = arch_spec["spawn_groups"][profile]
    cmin, cmax = arch_spec["count_range"][profile]

    # pressure-point placement along the route corridor, biased per archetype
    if e_arch == "extraction_pressure":
        t_values = [0.72, 0.6][:n_groups]
    elif e_arch == "defensive_holdout":
        t_values = [0.88, 0.82, 0.78][:n_groups]
    else:
        t_values = [0.45, 0.62, 0.55][:n_groups]

    spawn_anchors, spawn_groups = [], []
    for gi, t in enumerate(t_values):
        side = 1 if gi % 2 == 0 else -1
        off = rng.uniform(900.0, 1700.0) * side
        pos = _offset(_lerp(a, b, t), perp, off)
        anchor_id = "{}_spawn_{}".format(eid, gi)
        spawn_anchors.append({"id": anchor_id, "kind": "spawn",
                              "world_position": pos, "valid_spawn": True})
        roles = list(arch_spec["roles"])
        diff = rng.uniform(1.0, 1.3) if profile == "light_pressure" \
            else rng.uniform(1.4, 1.8)
        group = {
            "spawn_group_id": "{}_group_{}".format(eid, gi),
            "encounter_id": eid,
            "archetype_tag": e_arch,
            "faction_tag": "hostile_wildlife" if biome == "alien_crystal_badlands"
                           else "scavenger_band",
            "role_tags": roles,
            "count_min": cmin,
            "count_max": cmax,
            "pressure_value": 0.0,   # filled after band fitting
            "difficulty_value": round(diff, 3),
            "spawn_policy": arch_spec["spawn_policy"],
            "spawn_anchor_ids": [anchor_id],
            "allowed_spawn_zones": ["{}_danger_{}".format(eid, gi)],
            "forbidden_spawn_zones": ["player_start", "objective_interaction"],
            "activation_condition": "{}_activate".format(eid),
            "state_keys": ["{}_resolved".format(eid)],
            "budget_class": mission.get("budget_class", "light"),
        }
        spawn_groups.append(group)

    cover_anchors = []
    if arch_spec.get("cover_required"):
        # cover sits on the FAR side of each spawn cluster (away from the
        # required route) so it never encroaches on the route corridor.
        for gi, sa in enumerate(spawn_anchors):
            away = 1 if gi % 2 == 0 else -1
            for ci in range(2):
                cover_pos = _offset(sa["world_position"], perp,
                                    300.0 * (ci + 1) * away)
                cover_anchors.append({
                    "id": "{}_cover_{}_{}".format(eid, gi, ci), "kind": "cover",
                    "world_position": cover_pos, "height_class": "half_height",
                    "collision": True})

    patrol_anchors = []
    if e_arch in ("patrol_route", "roaming_threat"):
        for pi, t in enumerate((0.35, 0.5, 0.65, 0.8)):
            side = 1 if pi % 2 == 0 else -1
            patrol_anchors.append({
                "id": "{}_patrol_{}".format(eid, pi), "kind": "patrol",
                "world_position": _offset(_lerp(a, b, t), perp, 1200.0 * side)})

    ambush_anchors = []
    if e_arch == "ambush_choke":
        for ai, side in enumerate((1, -1)):
            ambush_anchors.append({
                "id": "{}_ambush_{}".format(eid, ai), "kind": "ambush",
                "world_position": _offset(_lerp(a, b, 0.55), perp, 1100.0 * side)})

    hazard_zones = []
    if e_arch == "hazard_field" or arch_spec.get("requires_hazard"):
        htype = EC.BIOME_HAZARD_TYPES[biome][0]
        center = _offset(_lerp(a, b, 0.5), perp, 2200.0)
        hazard_zones.append({
            "id": "{}_hazard_0".format(eid), "hazard_type": htype,
            "bounds": _bounds_around([center], 1600.0),
            "visual_marker": "hazard_marker_{}".format(htype)})

    spawn_positions = [sa["world_position"] for sa in spawn_anchors]
    danger_zones = [{"id": "{}_danger_{}".format(eid, gi),
                     "bounds": _bounds_around([pos], 1200.0)}
                    for gi, pos in enumerate(spawn_positions)]

    mission_safe = mission["safe_zones"][0]
    safe_zones = [
        {"id": "{}_safe_start".format(eid),
         "world_position": [start[0] - 800.0, start[1] - 800.0, 0.0]},
        {"id": "{}_safe_mission".format(eid),
         "world_position": list(mission_safe["world_position"])},
    ]

    cluster_mid = _lerp(a, b, sum(t_values) / len(t_values))
    approach_routes = [_route_entry("{}_approach".format(eid), "approach",
                                    [start, _lerp(a, b, max(t_values[0] - 0.15, 0.1)),
                                     cluster_mid])]
    escape_routes = [_route_entry("{}_escape".format(eid), "escape",
                                  [cluster_mid, safe_zones[1]["world_position"]])]

    resolved_key = "{}_resolved".format(eid)
    mission_state_key = mission["state_keys"][0]["key"]
    completion_threshold = mission["completion_conditions"][0]["threshold"]

    if e_arch == "extraction_pressure":
        activation = [{"condition_id": "{}_activate".format(eid),
                       "state_key": mission_state_key, "operator": ">=",
                       "threshold": completion_threshold,
                       "trigger": "post_objective"}]
    else:
        activation = [{"condition_id": "{}_activate".format(eid),
                       "state_key": mission_state_key, "operator": ">=",
                       "threshold": 0, "trigger": "mission_start"}]

    state_keys = [{"key": resolved_key, "initial": 0, "delta": 1,
                   "expected_final": 1}]
    completion_conditions = [{"condition_id": "{}_complete".format(eid),
                              "state_key": resolved_key, "operator": ">=",
                              "threshold": 1, "at_node": danger_zones[0]["id"]}]
    failure_conditions = [{"condition_id": "{}_fail".format(eid),
                           "state_key": resolved_key, "operator": "<",
                           "threshold": 0, "at_node": danger_zones[0]["id"]}]

    resource_nodes = []
    objective_links = [objective_anchor["id"]]
    reward_type = "state_flag"
    if e_arch == "resource_contest":
        node = dict(mission["resource_nodes"][0])
        # v1.3 resource nodes are positionless references (at_node); realize the
        # position from the referenced mission anchor so geometric blockage
        # checks run instead of skipping.
        if not node.get("world_position") and node.get("at_node") == "primary_poi":
            node["world_position"] = list(mission["primary_poi"]["gameplay_anchor"])
        resource_nodes = [node]
        objective_links.append(node.get("id", "resource_node_0"))
        reward_type = "resource_grant"
    reward_hooks = [{"reward_id": "{}_reward".format(eid),
                     "reward_type": reward_type,
                     "fires_on": "encounter_resolved"}]

    persist = [resolved_key] + list(
        mission["save_load_contract"].get("persist_keys") or [])
    save_load_contract = {"persist_keys": persist, "expect_roundtrip": True}

    modes = list(PLAYTEST_BETA_MODES)
    if reward_type == "resource_grant":
        modes.append("resource_reward_playtest")
    playtest_contract = {"modes": modes, "expected_completion": True,
                         "max_pressure_band": MAX_BAND_FOR_PROFILE[profile]}

    pacing_target = {
        "min_first_pressure_cm": EC.SAFE_START_CLEARANCE_CM,
        "max_route_blockage_ratio": 0.6,
        "min_cover_per_pressure_point": 0.5 if arch_spec.get("cover_required") else 0.0,
    }

    families = list(EC.BIOME_COVER_FAMILIES[biome]) if arch_spec.get("cover_required") else []
    resolved = []
    for aid, asset in sorted(mesh_assets.items()):
        if asset.get("mesh_family") in families and \
                biome in (asset.get("biome_compatibility") or []):
            resolved.append(aid)
    mesh_dependencies = {"required_families": families,
                         "resolved_mesh_assets": resolved[:6]}
    # v1.3 missions carry megascans_dressing as a scalar id (or null); v1.4
    # normalizes to a list of ids — never iterate a scalar string.
    _dressing = (mission.get("mesh_dependencies") or {}).get("megascans_dressing")
    if isinstance(_dressing, str):
        megascans_dependencies = [_dressing]
    elif isinstance(_dressing, list):
        megascans_dependencies = [d for d in _dressing if isinstance(d, str)]
    else:
        megascans_dependencies = []

    visual_markers = [{"target_id": hz["id"], "marker_class": hz["visual_marker"]}
                      for hz in hazard_zones]
    if e_arch == "ambush_choke":
        visual_markers.append({"target_id": ambush_anchors[0]["id"],
                               "marker_class": "readability_cue_choke"})

    encounter = {
        "schema_version": EC.ENCOUNTER_SCHEMA_VERSION,
        "encounter_id": eid,
        "display_name": "{} — {}".format(
            arch_spec.get("display_name", e_arch), biome),
        "mission_id": mid,
        "pack_id": "encounter_loop_world",
        "biome_family": biome,
        "mission_archetype": m_arch,
        "encounter_archetype": e_arch,
        "encounter_profile": profile,
        "difficulty_band": "invalid",   # set by band fitting below
        "pressure_budget": EC.PROFILE_PRESSURE_BUDGETS[profile],
        "pacing_target": pacing_target,
        "seed": mission.get("seed"),
        "spawn_groups": spawn_groups,
        "spawn_anchors": spawn_anchors,
        "patrol_anchors": patrol_anchors,
        "idle_anchors": [],
        "ambush_anchors": ambush_anchors,
        "cover_anchors": cover_anchors,
        "hazard_zones": hazard_zones,
        "resource_nodes": resource_nodes,
        "safe_zones": safe_zones,
        "danger_zones": danger_zones,
        "approach_routes": approach_routes,
        "escape_routes": escape_routes,
        "objective_links": objective_links,
        "state_keys": state_keys,
        "activation_conditions": activation,
        "completion_conditions": completion_conditions,
        "failure_conditions": failure_conditions,
        "reward_hooks": reward_hooks,
        "save_load_contract": save_load_contract,
        "playtest_contract": playtest_contract,
        "mesh_dependencies": mesh_dependencies,
        "megascans_dependencies": megascans_dependencies,
        "visual_marker_requirements": visual_markers,
        "bypass_allowed": bool(arch_spec.get("bypass_allowed")),
        "budget_class": mission.get("budget_class", "light"),
        "ownership_class": "generated_owned",
    }
    return encounter


def fit_band(encounter, mission, profile):
    """Deterministically fit the encounter into its profile band + budget.

    Adjusts spawn difficulty/count in bounded steps. Returns (band, components)
    or raises ValueError if the encounter cannot fit — hard failure, no
    silent fallback.
    """
    targets = EC.PROFILE_BAND_TARGETS[profile]
    budget = EC.PROFILE_PRESSURE_BUDGETS[profile]
    floor = min(EC.BAND_THRESHOLDS[[b for b, _ in EC.BAND_THRESHOLDS].index(targets[0])][1]
                for _ in (0,))
    for _ in range(40):
        comps = EC.pressure_components(encounter, mission)
        total = EC.total_pressure(comps)
        band = EC.classify_band(total)
        if band in targets and total <= budget:
            for g in encounter["spawn_groups"]:
                roles = g["role_tags"]
                w = max(EC.ROLE_PRESSURE_WEIGHTS.get(r, 0.0) for r in roles)
                avg = (g["count_min"] + g["count_max"]) / 2.0
                g["pressure_value"] = round(avg * w * g["difficulty_value"], 3)
            encounter["difficulty_band"] = band
            return band, comps
        if total > budget or band not in targets and total > floor:
            for g in encounter["spawn_groups"]:
                if g["difficulty_value"] > 0.8:
                    g["difficulty_value"] = round(g["difficulty_value"] * 0.92, 3)
                elif g["count_max"] > g["count_min"]:
                    g["count_max"] -= 1
        else:
            for g in encounter["spawn_groups"]:
                g["difficulty_value"] = round(g["difficulty_value"] * 1.08, 3)
    raise ValueError("cannot fit {} into band {} within budget {}".format(
        encounter["encounter_id"], targets, budget))


def write_encounter(encounter, repo_root=REPO_ROOT):
    eid = encounter["encounter_id"]
    encounter["source_hash"] = _source_hash(
        encounter["mission_id"], encounter["encounter_profile"],
        encounter["encounter_archetype"], GENERATOR_VERSION)
    encounter["provenance"] = {
        "generator": GENERATOR, "generator_version": GENERATOR_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_hash": encounter["source_hash"]}
    encounter["provenance_id"] = "prov_{}".format(eid)
    encounter["registry_id"] = "encounter_catalog:{}".format(eid)
    p = EC.encounter_path(eid, repo_root)
    encounter["encounter_path"] = p.relative_to(repo_root).as_posix()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(encounter, indent=2), encoding="utf-8")
    return p


def main(argv=None):
    import random

    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mission_catalog = load_mission_catalog(REPO_ROOT)
    missions = mission_catalog.get("missions") or {}
    if len(missions) != 60:
        rep.error("mission catalog has {} missions — run create-mission-loops"
                  .format(len(missions)))
        rep.finalize()
        rep.set_meta(build_meta(command="create-encounters", pack=args.pack,
                                strict=strict, status=rep.status))
        rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "create_encounters",
                  "create_encounters_report.json")
        rep.print_summary("create-encounters")
        sys.exit(rep.exit_code)

    archetypes = EC.load_all_archetypes()
    mesh_assets = (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {}
    catalog = load_encounter_catalog(REPO_ROOT)

    written, bands, e_archs, biomes, m_archs = [], {}, set(), set(), set()
    for mid in sorted(missions):
        mission, err = MC.load_mission(mid)
        if mission is None:
            rep.check("load::{}".format(mid), False, err,
                      code=FailureCode.ENCOUNTER_CONTRACT_FAILURE)
            continue
        for pi, profile in enumerate(EC.ENCOUNTER_PROFILES):
            e_arch = PAIRING[(mission["mission_archetype"], profile)]
            spec = archetypes.get(e_arch)
            if spec is None:
                rep.check("archetype::{}".format(e_arch), False,
                          "archetype spec missing",
                          code=FailureCode.ENCOUNTER_ARCHETYPE_FAILURE)
                continue
            rng = random.Random((mission.get("seed") or 0) * 1000 + pi)
            enc = build_encounter(mission, profile, spec, mesh_assets, rng)
            try:
                band, comps = fit_band(enc, mission, profile)
            except ValueError as exc:
                rep.check("band_fit::{}".format(enc["encounter_id"]), False,
                          str(exc), code=FailureCode.ENCOUNTER_PRESSURE_FAILURE)
                continue
            p = write_encounter(enc)
            written.append(enc["encounter_id"])
            bands[band] = bands.get(band, 0) + 1
            e_archs.add(enc["encounter_archetype"])
            biomes.add(enc["biome_family"])
            m_archs.add(enc["mission_archetype"])
            entry = {
                "encounter_id": enc["encounter_id"],
                "mission_id": mid,
                "pack_id": args.pack,
                "biome_family": enc["biome_family"],
                "mission_archetype": enc["mission_archetype"],
                "encounter_archetype": enc["encounter_archetype"],
                "encounter_profile": profile,
                "difficulty_band": band,
                "encounter_path": enc["encounter_path"],
                "ownership_class": "generated_owned",
                "playtest_beta_status": "pending",
                "balance_status": "pending",
            }
            entry["input_hash"] = compute_input_hash(entry)
            upsert_encounter(catalog, entry)

    save_encounter_catalog(REPO_ROOT, catalog)

    rep.check("encounter_count", len(written) == 120,
              "{} encounters generated (expected 120)".format(len(written)),
              code=FailureCode.ENCOUNTER_CONTRACT_FAILURE)
    rep.check("biome_coverage", len(biomes) == 5,
              "biomes: {}".format(sorted(biomes)),
              code=FailureCode.ENCOUNTER_BIOME_COMPATIBILITY_FAILURE)
    rep.check("mission_archetype_coverage", len(m_archs) == 6,
              "mission archetypes: {}".format(sorted(m_archs)),
              code=FailureCode.ENCOUNTER_MISSION_COMPATIBILITY_FAILURE)
    rep.check("encounter_archetype_coverage", len(e_archs) == 8,
              "encounter archetypes: {}".format(sorted(e_archs)),
              code=FailureCode.ENCOUNTER_ARCHETYPE_FAILURE)
    rep.check("no_invalid_bands", "invalid" not in bands and "extreme" not in bands,
              "band distribution: {}".format(bands),
              code=FailureCode.ENCOUNTER_PRESSURE_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(
        command="create-encounters", pack=args.pack, strict=strict,
        output_manifest_hash=hash_obj(sorted(written)), status=rep.status,
        record_count=len(written),
        extra={"bands": bands, "encounter_archetypes": sorted(e_archs),
               "biomes": sorted(biomes)}))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "create_encounters",
              "create_encounters_report.json")
    rep.print_summary("create-encounters")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
