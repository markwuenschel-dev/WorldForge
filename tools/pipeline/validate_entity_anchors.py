#!/usr/bin/env python3
"""validate_entity_anchors.py — WorldForge v1.0x entity-anchor substrate validator.

Strictly validates the entity-anchor overlays emitted by
``generate_entity_anchors.py`` for every map in a world pack. This proves the
substrate a future NPCForge / EncounterForge would consume is self-consistent
and geometry-safe WITHOUT that downstream system re-deriving anything.

Per map / per anchor it checks:
  * every anchor carries all required fields, a known type, provenance
    (generated-owned), and a valid budget_class;
  * spawn zones are reachable (recomputed from the world model, not trusted);
  * anchors are not floating, buried, on an invalid slope, or inside geometry;
  * no anchor (other than the safe-zone marker) sits inside player_start;
  * enemy spawns are not inside a safe zone unless explicitly allowed;
  * patrol anchors are connected, interaction anchors accessible, idle anchors
    do not block the critical route;
  * faction / encounter / difficulty / archetype tags are valid;
  * entity density stays within the map's declared budget.

Blocking failures are tagged ``FailureCode.ENTITY_ANCHOR_FAILURE`` (density
overruns use ``FailureCode.ENTITY_DENSITY_EXCEEDED``). One parent report is
written for the pack with one-or-more checks per map; record_count == maps.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_entity_anchors.py --pack desert_mvp_world --strict
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

EA = FailureCode.ENTITY_ANCHOR_FAILURE
DENS = FailureCode.ENTITY_DENSITY_EXCEEDED


def _fmt(items, n=6):
    items = list(items)
    shown = ", ".join(str(x) for x in items[:n])
    return shown + (" …(+{})".format(len(items) - n) if len(items) > n else "")


def check_map(rep, map_id, overlay, strict):
    """Add all entity-anchor checks for one map's overlay to ``rep``.

    Importable core: the negative harness constructs a fresh report, calls this
    with a known-bad overlay, and asserts the right FailureCode blocks.
    """
    p = "{}: ".format(map_id)

    if not isinstance(overlay, dict):
        rep.check(p + "overlay_present", False,
                  "no entity-anchor overlay for map (run generate-entity-anchors)",
                  code=EA)
        return
    rep.check(p + "overlay_present", True)

    anchors = overlay.get("anchors")
    wm = overlay.get("world_model")
    if not isinstance(anchors, list) or not anchors:
        rep.check(p + "anchors_nonempty", False, "overlay has no anchors", code=EA)
        return
    rep.check(p + "anchors_nonempty", True, "{} anchors".format(len(anchors)))

    if not isinstance(wm, dict) or "player_start" not in wm:
        rep.check(p + "world_model_present", False,
                  "world_model missing player_start / geometry model", code=EA)
        return
    rep.check(p + "world_model_present", True)

    player_start = wm["player_start"]
    ps_radius = wm.get("player_start_radius_cm", G.PLAYER_START_RADIUS_CM)
    max_slope = wm.get("max_slope_deg", G.MAX_SLOPE_DEG)
    float_tol = wm.get("float_tolerance_cm", G.GROUND_FLOAT_TOL_CM)
    bury_tol = wm.get("bury_tolerance_cm", G.GROUND_BURY_TOL_CM)
    edge_max = wm.get("edge_max_dist_cm", G.EDGE_MAX_DIST_CM)
    corridor = wm.get("route_corridor_radius_cm", G.ROUTE_CORRIDOR_RADIUS_CM)
    route = wm.get("critical_route", [player_start, player_start])
    safe_zones = wm.get("safe_zones", [])
    blocking = wm.get("blocking_volumes", [])

    # -- required fields / known type / provenance / budget_class ----------
    missing_fields, bad_type, bad_prov, bad_budget = [], [], [], []
    for a in anchors:
        if not isinstance(a, dict):
            bad_type.append("<non-dict>")
            continue
        aid = a.get("id", "<no-id>")
        if any(f not in a for f in G.REQUIRED_ANCHOR_FIELDS):
            missing_fields.append(aid)
        if a.get("type") not in G.ANCHOR_TYPES:
            bad_type.append("{}={}".format(aid, a.get("type")))
        prov = a.get("provenance") or {}
        if not (prov.get("generator") and prov.get("owned_by") == "generated"):
            bad_prov.append(aid)
        if a.get("budget_class") not in G.BUDGET_CLASSES:
            bad_budget.append("{}={}".format(aid, a.get("budget_class")))
    rep.check(p + "anchor_fields_complete", not missing_fields,
              "anchors missing required fields: " + _fmt(missing_fields), code=EA)
    rep.check(p + "anchor_types_known", not bad_type,
              "unknown anchor types: " + _fmt(bad_type), code=EA)
    rep.check(p + "anchor_provenance_owned", not bad_prov,
              "anchors without generated-owned provenance: " + _fmt(bad_prov), code=EA)
    rep.check(p + "anchor_budget_class_valid", not bad_budget,
              "invalid budget_class: " + _fmt(bad_budget), code=EA)

    # -- collision safety: floating / buried / slope / inside geometry -----
    floating, buried, bad_slope, inside_geo = [], [], [], []
    for a in anchors:
        if not isinstance(a, dict) or "position" not in a:
            continue
        pos = a["position"]
        gz = a.get("ground_z", wm.get("ground_z", 0))
        if pos[2] > gz + float_tol:
            floating.append(a.get("id"))
        if pos[2] < gz - bury_tol:
            buried.append(a.get("id"))
        if a.get("slope_deg", 0) > max_slope:
            bad_slope.append("{}={}".format(a.get("id"), a.get("slope_deg")))
        if any(G.point_in_box(pos, b) for b in blocking):
            inside_geo.append(a.get("id"))
    rep.check(p + "no_floating_anchors", not floating,
              "floating anchors (z above ground+tol): " + _fmt(floating), code=EA)
    rep.check(p + "no_buried_anchors", not buried,
              "buried anchors (z below ground-tol): " + _fmt(buried), code=EA)
    rep.check(p + "no_invalid_slope", not bad_slope,
              "anchors on invalid slope (> {} deg): {}".format(max_slope, _fmt(bad_slope)),
              code=EA)
    rep.check(p + "no_anchor_inside_geometry", not inside_geo,
              "anchors inside blocking geometry: " + _fmt(inside_geo), code=EA)

    # -- reachability recomputed from the graph (do not trust stored flag) --
    positions = [a["position"] for a in anchors if isinstance(a, dict) and "position" in a]
    reachable_idx = G.compute_reachable_indices(player_start, positions, edge_max)
    computed = {}
    j = 0
    for a in anchors:
        if isinstance(a, dict) and "position" in a:
            computed[id(a)] = (j + 1) in reachable_idx
            j += 1

    spawn_unreachable, stale_flags = [], []
    for a in anchors:
        if not isinstance(a, dict):
            continue
        comp = computed.get(id(a), False)
        if a.get("reachable") is not comp:
            stale_flags.append(a.get("id"))
        if a.get("type") in G.SPAWN_ZONE_TYPES and not comp:
            spawn_unreachable.append(a.get("id"))
    rep.check(p + "spawn_zones_reachable", not spawn_unreachable,
              "spawn zones not reachable from player_start: " + _fmt(spawn_unreachable),
              code=EA)
    rep.check(p + "reachable_flags_honest", not stale_flags,
              "stored reachable flag disagrees with recomputed graph: " + _fmt(stale_flags),
              code=EA)

    # -- player_start containment (safe-zone marker is exempt) -------------
    in_ps = []
    for a in anchors:
        if not isinstance(a, dict) or a.get("type") == "safe_zone_anchor":
            continue
        if G.dist_xy(a["position"], player_start) <= ps_radius:
            in_ps.append(a.get("id"))
    rep.check(p + "no_anchor_in_player_start", not in_ps,
              "anchors inside player_start radius: " + _fmt(in_ps), code=EA)

    # -- enemy spawn not inside safe zone unless allowed -------------------
    enemy_in_safe = []
    for a in anchors:
        if not isinstance(a, dict) or a.get("type") != "enemy_spawn_zone":
            continue
        if a.get("allow_in_safe_zone"):
            continue
        for sz in safe_zones:
            if G.dist_xy(a["position"], sz["center"]) <= sz["radius_cm"]:
                enemy_in_safe.append(a.get("id"))
                break
    rep.check(p + "enemy_not_in_safe_zone", not enemy_in_safe,
              "enemy spawn zones inside a safe zone (not allowed): " + _fmt(enemy_in_safe),
              code=EA)

    # -- patrol connected / interaction accessible / idle not blocking -----
    patrol_isolated = []
    for a in anchors:
        if not isinstance(a, dict) or a.get("type") != "patrol_anchor":
            continue
        if not computed.get(id(a), False):
            patrol_isolated.append(a.get("id"))
            continue
        has_neighbor = any(
            b is not a and isinstance(b, dict) and "position" in b
            and G.dist3(a["position"], b["position"]) <= edge_max
            for b in anchors)
        if not has_neighbor:
            patrol_isolated.append(a.get("id"))
    rep.check(p + "patrol_anchors_connected", not patrol_isolated,
              "patrol anchors isolated / unreachable: " + _fmt(patrol_isolated), code=EA)

    inter_inaccessible = [a.get("id") for a in anchors
                          if isinstance(a, dict) and a.get("type") == "interaction_anchor"
                          and not computed.get(id(a), False)]
    rep.check(p + "interaction_anchors_accessible", not inter_inaccessible,
              "interaction anchors not reachable: " + _fmt(inter_inaccessible), code=EA)

    idle_blocking = [a.get("id") for a in anchors
                     if isinstance(a, dict) and a.get("type") == "idle_anchor"
                     and G.point_seg_dist_xy(a["position"], route[0], route[1]) <= corridor]
    rep.check(p + "idle_not_blocking_route", not idle_blocking,
              "idle anchors blocking the critical route: " + _fmt(idle_blocking), code=EA)

    # -- tag validity ------------------------------------------------------
    bad_fac, bad_enc, bad_diff, bad_arch = [], [], [], []
    for a in anchors:
        if not isinstance(a, dict):
            continue
        if "faction_tag" in a and a["faction_tag"] not in G.VALID_FACTIONS:
            bad_fac.append("{}={}".format(a.get("id"), a["faction_tag"]))
        if "encounter_tag" in a and a["encounter_tag"] not in G.VALID_ENCOUNTER_TAGS:
            bad_enc.append("{}={}".format(a.get("id"), a["encounter_tag"]))
        if "difficulty_tag" in a and a["difficulty_tag"] not in G.VALID_DIFFICULTY_TAGS:
            bad_diff.append("{}={}".format(a.get("id"), a["difficulty_tag"]))
        if "archetypes" in a and not set(a["archetypes"]).issubset(G.ARCHETYPES):
            bad_arch.append(a.get("id"))
    rep.check(p + "faction_tags_valid", not bad_fac,
              "invalid faction tags: " + _fmt(bad_fac), code=EA)
    rep.check(p + "encounter_tags_valid", not bad_enc,
              "invalid encounter tags: " + _fmt(bad_enc), code=EA)
    rep.check(p + "difficulty_tags_valid", not bad_diff,
              "invalid difficulty tags: " + _fmt(bad_diff), code=EA)
    rep.check(p + "archetype_tags_valid", not bad_arch,
              "anchors with archetypes outside the allowed set: " + _fmt(bad_arch), code=EA)

    # -- density budget ----------------------------------------------------
    db = overlay.get("density_budget") or G.DENSITY_BUDGET
    spawn = [a for a in anchors if isinstance(a, dict) and a.get("type") in G.SPAWN_ZONE_TYPES]
    enemy = [a for a in spawn if a.get("type") == "enemy_spawn_zone"]
    total_cap = sum(int(a.get("capacity", 0)) for a in spawn)
    over_zone = ["{}={}".format(a.get("id"), a.get("capacity"))
                 for a in spawn if int(a.get("capacity", 0)) > db["max_capacity_per_zone"]]
    density_ok = (
        len(anchors) <= db["max_anchors_per_map"] and
        len(spawn) <= db["max_spawn_zones_per_map"] and
        len(enemy) <= db["max_enemy_spawn_zones_per_map"] and
        total_cap <= db["max_total_spawn_capacity"] and
        not over_zone
    )
    rep.check(p + "entity_density_within_budget", density_ok,
              "density over budget: anchors={}/{} spawn_zones={}/{} enemy_zones={}/{} "
              "total_capacity={}/{} over_zone=[{}]".format(
                  len(anchors), db["max_anchors_per_map"],
                  len(spawn), db["max_spawn_zones_per_map"],
                  len(enemy), db["max_enemy_spawn_zones_per_map"],
                  total_cap, db["max_total_spawn_capacity"], _fmt(over_zone)),
              code=DENS)


def validate_pack(pack, strict, overlay_dir=None, overlays=None):
    """Core entrypoint: build the parent report for the pack. Importable.

    ``overlays`` (dict slice_id->overlay) or ``overlay_dir`` override the on-disk
    overlay location for injection / negative testing.
    """
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not maps:
        rep.error("world pack enumerated zero maps")
        rep.set_meta(build_meta(command="validate-entity-anchors", pack=world_pack_id,
                                strict=strict, status=None, record_count=0))
        return rep

    for m in maps:
        map_id = m.slice_id or "<unknown>"
        if not m.spec_exists:
            rep.check("{}: spec_present".format(map_id), False,
                      m.get("spec_error") or "generated spec missing", code=EA)
            continue
        if overlays is not None:
            overlay = overlays.get(map_id)
        else:
            overlay = G.load_overlay(map_id, overlay_dir)
        check_map(rep, map_id, overlay, strict)

    rep.set_meta(build_meta(command="validate-entity-anchors", pack=world_pack_id,
                            strict=strict, status=None, record_count=len(maps)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate entity-anchor overlays for a world pack.")
    ap.add_argument("--pack", default="desert_mvp_world", help="World pack id.")
    ap.add_argument("--strict", action="store_true", help="Treat warnings as blocking (STRICT=1).")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_pack(args.pack, strict)
    rep.finalize()
    world_pack_id = rep.entity_id
    report_dir = report_dir_for(world_pack_id)
    rep.write(report_dir, "validate_entity_anchors_report.json")
    rep.print_summary("validate-entity-anchors")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
