#!/usr/bin/env python3
"""create_mission_loops.py — WorldForge v1.3 MissionForge generator (Agent 1/4 lane).

Composes biome-aware playable mission loops from the existing v1.1/v1.2 substrate:
each of biome_expansion_world's 60 biome maps supplies a level-design navigation
graph (player_start, primary POI, safe/danger zones — from generate_level_design)
which this generator turns into a mission objective graph, wiring in v1.2 mesh
catalog dependencies (biome-compatible) and a state model with completion,
rewards, and a save/load contract. Deterministic; no UE.

Scale: 5 biome families x 6 archetypes x 2 seeds = 60 mission loops (each of the
60 biome maps hosts exactly one mission; archetypes rotate so every biome runs
all 6). This proves v1.1 (biomes/POIs) + v1.2 (mesh/Megascans) are consumable as
playable purpose, not just plumbing.

Usage:
    python tools/pipeline/create_mission_loops.py --pack mission_loop_world
    STRICT=1 python tools/pipeline/create_mission_loops.py --pack mission_loop_world --strict

Writes procedural/generated/missions/<mission_id>/mission.json + the mission
catalog + a report.
"""

import argparse
import datetime
import glob
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import (
    compute_input_hash, load_mission_catalog, save_mission_catalog, upsert_mission,
)
from mesh_catalog import load_mesh_catalog
from external_asset_contract import load_external_catalog
from report_meta import build_meta, hash_obj, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GENERATOR = "create_mission_loops"
GENERATOR_VERSION = "1.3.0"
LEVEL_DESIGN_DIR = REPO_ROOT / "procedural" / "generated" / "level_design"
SOURCE_PACK = "biome_expansion_world"


def _source_hash(*parts):
    return "sha256:" + hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _load_biome_maps():
    """Return level_design dicts for the biome_expansion_world maps, grouped by biome."""
    by_biome = {}
    for f in sorted(glob.glob(str(LEVEL_DESIGN_DIR / "*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        if d.get("world_pack_id") != SOURCE_PACK:
            continue
        biome = d.get("biome")
        if biome not in MC.BIOME_FAMILIES:
            continue
        by_biome.setdefault(biome, []).append(d)
    return by_biome


def _resolve_mesh_deps(mesh_catalog, families, biome):
    """Biome-compatible mesh assets in the archetype's preferred families; fall
    back to any biome-compatible asset so every mission has a real dependency."""
    assets = mesh_catalog.get("assets") or {}
    preferred = [aid for aid, e in sorted(assets.items())
                 if e.get("mesh_family") in families and biome in (e.get("biome_compatibility") or [])]
    if preferred:
        return preferred[:3]
    fallback = [aid for aid, e in sorted(assets.items())
                if biome in (e.get("biome_compatibility") or [])]
    return fallback[:2]


def _resolve_megascans_dep(ext_catalog, biome):
    """Optional biome-compatible Megascans dressing asset (may be none for some biomes)."""
    for aid, e in sorted((ext_catalog.get("assets") or {}).items()):
        if biome in (e.get("biome_compatibility") or []):
            return aid
    return None


def _build_route(start_pos, obj_pos, hazards, safe_zones):
    """Build required_route start->objective, detouring via a safe zone if the
    straight line crosses a hazard. Returns the route dict."""
    def crosses_any(p0, p1):
        return any(MC.segment_intersects_bounds(p0, p1, h["bounds"]) for h in hazards if h.get("bounds"))

    waypoints = [start_pos, obj_pos]
    avoids = not crosses_any(start_pos, obj_pos)
    if not avoids and safe_zones:
        sp = safe_zones[0].get("world_position", safe_zones[0].get("position"))
        if sp:
            # detour start -> safe -> objective
            if not (crosses_any(start_pos, sp) or crosses_any(sp, obj_pos)):
                waypoints = [start_pos, sp, obj_pos]
                avoids = True
    length = sum(MC.dist2d(waypoints[i], waypoints[i + 1]) for i in range(len(waypoints) - 1))
    return {"from_node": MC.NODE_START, "to_node": MC.NODE_PRIMARY_POI,
            "waypoints": waypoints, "length_cm": round(length, 2),
            "avoids_hazards": avoids}


def build_mission(ld, archetype, arch_spec, seed_variant, mesh_catalog, ext_catalog):
    biome = ld["biome"]
    slice_id = ld["slice_id"]
    mission_id = "mission_{}".format(slice_id)
    ps = ld["player_start"]
    start_pos = ps["world_position"]
    pois = ld.get("pois") or []
    primary = next((p for p in pois if p.get("role") == "primary"), pois[0] if pois else None)
    obj_pos = (primary.get("gameplay_anchor") or primary.get("world_position")) if primary else start_pos
    hazards = ld.get("danger_zones") or []
    safe_zones = ld.get("safe_zones") or []
    bounds = ld.get("terrain_bounds") or {}
    diag = MC.dist2d(bounds.get("min", [0, 0]), bounds.get("max", [0, 0])) if bounds else 100000.0

    state_key = arch_spec["state_key"]
    initial, delta = float(arch_spec["initial"]), float(arch_spec["delta"])
    final = initial + delta
    operator, threshold = arch_spec["operator"], float(arch_spec["threshold"])

    mesh_families = arch_spec.get("mesh_families", [])
    mesh_deps = _resolve_mesh_deps(mesh_catalog, mesh_families, biome)
    megascans_dep = _resolve_megascans_dep(ext_catalog, biome)

    route = _build_route(start_pos, obj_pos, hazards, safe_zones)

    mission = {
        "schema_version": MC.MISSION_SCHEMA_VERSION,
        "mission_id": mission_id,
        "display_name": "{} — {}".format(arch_spec.get("display_name", archetype), biome),
        "mission_archetype": archetype,
        "biome_family": biome,
        "seed": ld.get("seed"),
        "source_map": {"slice_id": slice_id,
                       "world_pack_map": "/Game/WorldForge/Maps/{}".format(slice_id),
                       "world_pack_id": SOURCE_PACK},
        "scenario_id": "mission_state_{}".format(archetype),
        "start_anchor": {"id": MC.NODE_START, "world_position": start_pos,
                         "valid_spawn": MC.point_in_bounds(start_pos, {"min": bounds.get("min"),
                                                                       "max": bounds.get("max")}) if bounds else True},
        "primary_poi": {"id": MC.NODE_PRIMARY_POI,
                        "poi_class": (primary or {}).get("class"),
                        "gameplay_anchor": obj_pos},
        "objective_anchors": [
            {"id": "objective_1", "role": MC.NODE_OBJECTIVE, "world_position": obj_pos,
             "interaction": arch_spec["interaction"], "at_poi": MC.NODE_PRIMARY_POI}],
        "required_route": route,
        "optional_route": None,
        "hazard_zones": [{"id": h.get("id"), "bounds": h.get("bounds")} for h in hazards],
        "safe_zones": [{"id": s.get("id"),
                        "world_position": s.get("world_position", s.get("position"))} for s in safe_zones],
        "encounter_zones": [{"id": h.get("id"), "class": "encounter",
                             "bounds": h.get("bounds")} for h in hazards[:1]],
        "resource_nodes": [{"id": "resource_1", "at_node": MC.NODE_PRIMARY_POI}]
                          if archetype in ("recover_resource", "extract_cache", "restore_power") else [],
        "state_keys": [{"key": state_key, "initial": initial, "delta": delta,
                        "expected_final": final}],
        "completion_conditions": [
            {"condition_id": "complete_1", "state_key": state_key, "operator": operator,
             "threshold": threshold, "at_node": MC.NODE_PRIMARY_POI}],
        "failure_conditions": [
            {"condition_id": "no_state_change", "state_key": state_key,
             "operator": "==", "threshold": initial, "at_node": MC.NODE_COMPLETION}],
        "reward_outputs": [
            {"reward_id": "reward_1", "reward_type": arch_spec["reward_type"],
             "fires_on": "complete_1"}],
        "save_load_contract": {"persist_keys": [state_key], "expect_roundtrip": True},
        "playtest_contract": {
            "modes": ["graph_playtest", "anchor_playtest", "state_transition_playtest",
                      "save_load_playtest", "budget_safe_playtest"],
            "expected_completion": True,
            "max_route_length_cm": round(diag * 1.5, 2)},
        "mesh_dependencies": {
            "required_families": mesh_families,
            "resolved_mesh_assets": mesh_deps,
            "megascans_dressing": megascans_dep},
        "budget_class": ld.get("budget_class", "balanced"),
        "ownership_class": "generated_owned",
    }
    mission["source_hash"] = _source_hash(mission_id, archetype, biome, ld.get("content_hash", ""))
    return mission


def write_mission(mission, repo_root):
    mid = mission["mission_id"]
    out_dir = Path(repo_root) / MC.MISSION_GENERATED_REL / mid
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    mission["provenance"] = {"generator": GENERATOR, "generator_version": GENERATOR_VERSION,
                             "generated_at_utc": now, "source_hash": mission["source_hash"]}
    mission["provenance_id"] = "prov_{}".format(mid)
    mission["registry_id"] = "mission_catalog:{}".format(mid)
    mission["mission_path"] = (out_dir / "mission.json").relative_to(repo_root).as_posix()
    with (out_dir / "mission.json").open("w", encoding="utf-8") as fh:
        json.dump(mission, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    entry = {
        "mission_id": mid, "mission_archetype": mission["mission_archetype"],
        "biome_family": mission["biome_family"], "source_map": mission["source_map"]["slice_id"],
        "scenario_id": mission["scenario_id"],
        "state_keys": [k["key"] for k in mission["state_keys"]],
        "reward_outputs": [r["reward_id"] for r in mission["reward_outputs"]],
        "playtest_status": "pending", "validation_status": "pending",
        "lifecycle_status": "created", "mission_path": mission["mission_path"],
        "source_hash": mission["source_hash"],
    }
    entry["input_hash"] = compute_input_hash(entry)
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.3 MissionForge generator.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    archetypes = MC.load_all_archetypes()
    mesh_catalog = load_mesh_catalog(REPO_ROOT)
    ext_catalog = load_external_catalog(REPO_ROOT)
    by_biome = _load_biome_maps()
    catalog = load_mission_catalog(REPO_ROOT)

    written, biomes_seen, archetypes_seen = [], set(), set()
    for biome in sorted(by_biome):
        maps = by_biome[biome]
        for i, ld in enumerate(maps):
            archetype = MC.MISSION_ARCHETYPES[i % len(MC.MISSION_ARCHETYPES)]
            seed_variant = i // len(MC.MISSION_ARCHETYPES)
            spec = archetypes.get(archetype)
            if not spec:
                continue
            mission = build_mission(ld, archetype, spec, seed_variant, mesh_catalog, ext_catalog)
            entry = write_mission(mission, REPO_ROOT)
            catalog = upsert_mission(catalog, entry)
            written.append(entry["mission_id"])
            biomes_seen.add(biome)
            archetypes_seen.add(archetype)

    save_mission_catalog(REPO_ROOT, catalog)

    rep.check("mission_count_at_least_30", len(written) >= 30,
              "generated {} missions".format(len(written)), code=FailureCode.MISSION_CONTRACT_FAILURE)
    rep.check("biomes_at_least_5", len(biomes_seen) >= 5,
              "biomes: {}".format(sorted(biomes_seen)), code=FailureCode.MISSION_BIOME_COMPATIBILITY_FAILURE)
    rep.check("archetypes_at_least_6", len(archetypes_seen) >= 6,
              "archetypes: {}".format(sorted(archetypes_seen)), code=FailureCode.MISSION_CONTRACT_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="create-mission-loops", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(written),
                            output_manifest_hash=hash_obj(sorted(written)),
                            extra={"biomes": sorted(biomes_seen), "archetypes": sorted(archetypes_seen)}))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "create_mission_loops",
              "create_mission_loops_report.json")
    rep.print_summary("create-mission-loops")
    print("[create-mission-loops] {} missions, {} biomes, {} archetypes".format(
        len(written), len(biomes_seen), len(archetypes_seen)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
