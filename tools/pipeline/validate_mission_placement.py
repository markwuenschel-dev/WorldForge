#!/usr/bin/env python3
"""validate_mission_placement.py — WorldForge v1.3 biome-aware placement validator (Agent 2).

Proves each mission's anchors sit where a player can actually reach and act on them
(brief §4 biome-aware placement): the start_anchor and primary_poi anchor both lie
inside the source map's terrain bounds, every objective anchor is in-bounds, the
start is a valid spawn, and each biome's placement rule (from
MC.BIOME_PLACEMENT_RULES) holds — wetland routes must detour around water hazards,
volcanic hazards may pressure but must not fully block a completable route, and
open biomes must not present a degenerate (start == objective) objective. Geometry
only (no UE) — pairs with validate_mission_routes for the hazard-avoidance proof.

Usage:
    python tools/pipeline/validate_mission_placement.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_placement/validate_mission_placement_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

LEVEL_DESIGN_REL = "procedural/generated/level_design"
# Tolerance (cm) for "same position" comparisons.
POS_TOL_CM = 1.0


def load_level_design(slice_id):
    """Load the source map's level-design descriptor. Returns (data, error)."""
    p = REPO_ROOT / LEVEL_DESIGN_REL / (str(slice_id) + ".json")
    if not p.is_file():
        return None, "level_design not found: {}".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover
        return None, "level_design unparseable: {}".format(exc)


def terrain_bounds_of(ld):
    """Return {min,max} usable by MC.point_in_bounds, or None."""
    tb = (ld or {}).get("terrain_bounds") or {}
    mn, mx = tb.get("min"), tb.get("max")
    if not mn or not mx:
        return None
    return {"min": mn, "max": mx}


def check_placement(rep, mid, m):
    def c(name, ok, detail="", code=FailureCode.MISSION_PLACEMENT_FAILURE):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    biome = m.get("biome_family")
    source_map = m.get("source_map") or {}
    slice_id = source_map.get("slice_id")

    ld, err = load_level_design(slice_id)
    if ld is None:
        c("level_design_loads", False, err)
        return
    bounds = terrain_bounds_of(ld)
    if not bounds:
        c("terrain_bounds_present", False, "no terrain_bounds for slice {}".format(slice_id))
        return

    start = m.get("start_anchor") or {}
    primary = m.get("primary_poi") or {}
    start_pos = start.get("world_position")
    poi_pos = primary.get("gameplay_anchor")

    c("start_in_bounds", bool(start_pos) and MC.point_in_bounds(start_pos, bounds),
      "start={} bounds={}".format(start_pos, bounds))
    c("primary_poi_in_bounds", bool(poi_pos) and MC.point_in_bounds(poi_pos, bounds),
      "poi={} bounds={}".format(poi_pos, bounds))

    objectives = m.get("objective_anchors") or []
    for i, o in enumerate(objectives):
        op = o.get("world_position")
        c("objective_{}_in_bounds".format(i), bool(op) and MC.point_in_bounds(op, bounds),
          "objective {} pos={}".format(i, op))

    c("start_valid_spawn", start.get("valid_spawn") is True,
      "valid_spawn={}".format(start.get("valid_spawn")))

    # Biome-aware placement rules (brief §4).
    rules = MC.BIOME_PLACEMENT_RULES.get(biome, {})
    route = m.get("required_route") or {}
    hazards = m.get("hazard_zones") or []

    if rules.get("requires_route_when_water"):  # wetland_mire
        # If the direct start->objective route crosses a hazard, the mission's
        # required_route must detour (avoids_hazards True) so a path exists.
        crosses = bool(start_pos) and bool(poi_pos) and any(
            MC.segment_intersects_bounds(start_pos, poi_pos, h.get("bounds") or {})
            for h in hazards)
        c("wetland_water_route_detours", (not crosses) or bool(route.get("avoids_hazards")),
          "direct route crosses water hazard but required_route.avoids_hazards={}".format(
              route.get("avoids_hazards")))

    if rules.get("hazard_may_pressure_not_block"):  # volcanic_ashlands
        # Hazards may pressure the player but must not make the mission
        # uncompletable — a completable (hazard-avoiding) route must exist.
        c("volcanic_route_completable", bool(route.get("avoids_hazards")),
          "no completable route: required_route.avoids_hazards={}".format(
              route.get("avoids_hazards")))

    if biome in ("alpine_snow", "temperate_forest", "alien_crystal_badlands"):
        # Open/readable biomes: objective must not be degenerate (coincident
        # with the start), which would make the mission trivially/empty.
        for i, o in enumerate(objectives):
            op = o.get("world_position")
            degenerate = bool(start_pos) and bool(op) and MC.dist2d(start_pos, op) < POS_TOL_CM
            c("objective_{}_not_degenerate".format(i), not degenerate,
              "objective {} coincides with start".format(i))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 biome-aware mission placement.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")
    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.MISSION_PLACEMENT_FAILURE)
            continue
        check_placement(rep, mid, m)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-placement", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_placement",
              "validate_mission_placement_report.json")
    rep.print_summary("validate-mission-placement")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
