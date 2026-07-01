#!/usr/bin/env python3
"""validate_npc_spawns.py — WorldForge v1.0x NPC/enemy/neutral spawn-zone validator.

Focuses on the spawn-zone slice of the entity-anchor substrate (npc_spawn_zone,
enemy_spawn_zone, neutral_spawn_zone). It proves the spawn zones a future
NPCForge would consume are placeable and safe:

  * every map declares at least one spawn zone;
  * every spawn zone is reachable (recomputed graph) and collision-safe;
  * no spawn zone overlaps player_start;
  * enemy zones are not inside a safe zone unless explicitly allowed; friendly
    npc/neutral zones are reachable staging (not floating/buried);
  * per-zone capacity and total spawn density stay within the map budget;
  * spawn-zone faction and archetype tags are valid;
  * every spawn zone is generated-owned (provenance) with a valid budget_class.

Blocking failures are tagged ``FailureCode.NPC_SPAWN_FAILURE`` (density overruns
use ``FailureCode.ENTITY_DENSITY_EXCEEDED``). Writes one parent report per pack;
record_count == maps.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_npc_spawns.py --pack desert_mvp_world --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta
from world_pack_maps import enumerate_maps, report_dir_for
import generate_entity_anchors as G

NPC = FailureCode.NPC_SPAWN_FAILURE
DENS = FailureCode.ENTITY_DENSITY_EXCEEDED


def _fmt(items, n=6):
    items = list(items)
    shown = ", ".join(str(x) for x in items[:n])
    return shown + (" …(+{})".format(len(items) - n) if len(items) > n else "")


def check_map(rep, map_id, overlay, strict):
    """Add all spawn-zone checks for one map's overlay to ``rep``. Importable core."""
    p = "{}: ".format(map_id)

    if not isinstance(overlay, dict):
        rep.check(p + "overlay_present", False,
                  "no entity-anchor overlay for map (run generate-entity-anchors)", code=NPC)
        return
    anchors = overlay.get("anchors")
    wm = overlay.get("world_model")
    if not isinstance(anchors, list) or not isinstance(wm, dict) or "player_start" not in wm:
        rep.check(p + "overlay_wellformed", False,
                  "overlay missing anchors or world_model.player_start", code=NPC)
        return
    rep.check(p + "overlay_wellformed", True)

    player_start = wm["player_start"]
    ps_radius = wm.get("player_start_radius_cm", G.PLAYER_START_RADIUS_CM)
    max_slope = wm.get("max_slope_deg", G.MAX_SLOPE_DEG)
    float_tol = wm.get("float_tolerance_cm", G.GROUND_FLOAT_TOL_CM)
    bury_tol = wm.get("bury_tolerance_cm", G.GROUND_BURY_TOL_CM)
    edge_max = wm.get("edge_max_dist_cm", G.EDGE_MAX_DIST_CM)
    safe_zones = wm.get("safe_zones", [])
    blocking = wm.get("blocking_volumes", [])

    spawns = [a for a in anchors if isinstance(a, dict) and a.get("type") in G.SPAWN_ZONE_TYPES]
    rep.check(p + "has_spawn_zones", len(spawns) > 0,
              "map declares no spawn zones", code=NPC)
    if not spawns:
        return

    # -- reachability recomputed across ALL anchors ------------------------
    positions = [a["position"] for a in anchors if isinstance(a, dict) and "position" in a]
    reachable_idx = G.compute_reachable_indices(player_start, positions, edge_max)
    reach = {}
    j = 0
    for a in anchors:
        if isinstance(a, dict) and "position" in a:
            reach[id(a)] = (j + 1) in reachable_idx
            j += 1

    unreachable, collide, in_ps = [], [], []
    for a in spawns:
        pos = a.get("position")
        if not reach.get(id(a), False):
            unreachable.append(a.get("id"))
        gz = a.get("ground_z", wm.get("ground_z", 0))
        floating = pos[2] > gz + float_tol
        buried = pos[2] < gz - bury_tol
        bad_slope = a.get("slope_deg", 0) > max_slope
        inside = any(G.point_in_box(pos, b) for b in blocking)
        if floating or buried or bad_slope or inside:
            collide.append(a.get("id"))
        if G.dist_xy(pos, player_start) <= ps_radius:
            in_ps.append(a.get("id"))
    rep.check(p + "spawn_zones_reachable", not unreachable,
              "spawn zones not reachable: " + _fmt(unreachable), code=NPC)
    rep.check(p + "spawn_zones_collision_safe", not collide,
              "spawn zones floating/buried/steep/in-geometry: " + _fmt(collide), code=NPC)
    rep.check(p + "spawn_not_overlapping_player_start", not in_ps,
              "spawn zones overlapping player_start: " + _fmt(in_ps), code=NPC)

    # -- placement rules by zone kind -------------------------------------
    enemy_in_safe, friendly_unreachable = [], []
    for a in spawns:
        t = a.get("type")
        if t == "enemy_spawn_zone" and not a.get("allow_in_safe_zone"):
            for sz in safe_zones:
                if G.dist_xy(a["position"], sz["center"]) <= sz["radius_cm"]:
                    enemy_in_safe.append(a.get("id"))
                    break
        if t in ("npc_spawn_zone", "neutral_spawn_zone") and not reach.get(id(a), False):
            friendly_unreachable.append(a.get("id"))
    rep.check(p + "enemy_zone_not_in_safe_zone", not enemy_in_safe,
              "enemy spawn zones inside a safe zone: " + _fmt(enemy_in_safe), code=NPC)
    rep.check(p + "friendly_zones_reachable", not friendly_unreachable,
              "npc/neutral zones not reachable staging: " + _fmt(friendly_unreachable), code=NPC)

    # -- tags / provenance / budget_class ---------------------------------
    bad_fac, bad_arch, bad_prov, bad_budget = [], [], [], []
    for a in spawns:
        if a.get("faction_tag") is not None and a["faction_tag"] not in G.VALID_FACTIONS:
            bad_fac.append("{}={}".format(a.get("id"), a.get("faction_tag")))
        arche = a.get("archetypes")
        if arche is None or not arche or not set(arche).issubset(G.ARCHETYPES):
            bad_arch.append(a.get("id"))
        prov = a.get("provenance") or {}
        if not (prov.get("generator") and prov.get("owned_by") == "generated"):
            bad_prov.append(a.get("id"))
        if a.get("budget_class") not in G.BUDGET_CLASSES:
            bad_budget.append(a.get("id"))
    rep.check(p + "spawn_faction_tags_valid", not bad_fac,
              "invalid spawn faction tags: " + _fmt(bad_fac), code=NPC)
    rep.check(p + "spawn_archetypes_valid", not bad_arch,
              "spawn zones with missing/invalid archetypes: " + _fmt(bad_arch), code=NPC)
    rep.check(p + "spawn_provenance_owned", not bad_prov,
              "spawn zones without generated-owned provenance: " + _fmt(bad_prov), code=NPC)
    rep.check(p + "spawn_budget_class_valid", not bad_budget,
              "spawn zones with invalid budget_class: " + _fmt(bad_budget), code=NPC)

    # -- density per zone + total -----------------------------------------
    db = overlay.get("density_budget") or G.DENSITY_BUDGET
    enemy = [a for a in spawns if a.get("type") == "enemy_spawn_zone"]
    total_cap = sum(int(a.get("capacity", 0)) for a in spawns)
    over_zone = ["{}={}".format(a.get("id"), a.get("capacity"))
                 for a in spawns if int(a.get("capacity", 0)) > db["max_capacity_per_zone"]]
    zero_cap = [a.get("id") for a in spawns if int(a.get("capacity", 0)) <= 0]
    rep.check(p + "spawn_capacity_positive", not zero_cap,
              "spawn zones with non-positive capacity: " + _fmt(zero_cap), code=NPC)
    density_ok = (
        len(spawns) <= db["max_spawn_zones_per_map"] and
        len(enemy) <= db["max_enemy_spawn_zones_per_map"] and
        total_cap <= db["max_total_spawn_capacity"] and
        not over_zone
    )
    rep.check(p + "spawn_density_within_budget", density_ok,
              "spawn density over budget: zones={}/{} enemy_zones={}/{} total_capacity={}/{} "
              "over_zone=[{}]".format(
                  len(spawns), db["max_spawn_zones_per_map"],
                  len(enemy), db["max_enemy_spawn_zones_per_map"],
                  total_cap, db["max_total_spawn_capacity"], _fmt(over_zone)),
              code=DENS)


def validate_pack(pack, strict, overlay_dir=None, overlays=None):
    """Core entrypoint: parent report for the pack. Importable."""
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    if not maps:
        rep.error("world pack enumerated zero maps")
        rep.set_meta(build_meta(command="validate-npc-spawns", pack=world_pack_id,
                                strict=strict, status=None, record_count=0))
        return rep
    for m in maps:
        map_id = m.slice_id or "<unknown>"
        if not m.spec_exists:
            rep.check("{}: spec_present".format(map_id), False,
                      m.get("spec_error") or "generated spec missing", code=NPC)
            continue
        overlay = overlays.get(map_id) if overlays is not None else G.load_overlay(map_id, overlay_dir)
        check_map(rep, map_id, overlay, strict)
    rep.set_meta(build_meta(command="validate-npc-spawns", pack=world_pack_id,
                            strict=strict, status=None, record_count=len(maps)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate NPC/enemy/neutral spawn zones for a world pack.")
    ap.add_argument("--pack", default="desert_mvp_world", help="World pack id.")
    ap.add_argument("--strict", action="store_true", help="Treat warnings as blocking (STRICT=1).")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_pack(args.pack, strict)
    rep.finalize()
    report_dir = report_dir_for(rep.entity_id)
    rep.write(report_dir, "validate_npc_spawns_report.json")
    rep.print_summary("validate-npc-spawns")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
