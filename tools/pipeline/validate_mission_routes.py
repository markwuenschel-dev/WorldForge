#!/usr/bin/env python3
"""validate_mission_routes.py — WorldForge v1.3 mission route validator (Agent 2).

Proves each mission's required_route is a real, honest, hazard-aware path (brief
§2/§6): it runs from the start_anchor to the primary_poi, has at least two
waypoints, its declared length_cm is not fabricated (it equals — within 1% — the
recomputed sum of 2D segment distances between consecutive waypoints), the route
actually terminates at the start and primary-POI world positions, and its
avoids_hazards claim is verified rather than trusted — no route segment may pass
through a blocking hazard zone. A route that claims avoids_hazards=True while
crossing a hazard is a MISSION_ROUTE_FAILURE.

Usage:
    python tools/pipeline/validate_mission_routes.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_routes/validate_mission_routes_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

# Tolerances.
LENGTH_TOL_FRAC = 0.01   # declared length must be within 1% of recomputed sum.
CONNECT_TOL_CM = 1.0     # route endpoints must coincide with anchors.


def _is_coord(w):
    return isinstance(w, (list, tuple)) and len(w) >= 2 and all(
        isinstance(v, (int, float)) for v in w[:2])


def check_route(rep, mid, m):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(mid, name), ok, detail,
                         code=FailureCode.MISSION_ROUTE_FAILURE)

    route = m.get("required_route") or {}
    start = m.get("start_anchor") or {}
    primary = m.get("primary_poi") or {}
    start_pos = start.get("world_position")
    poi_pos = primary.get("gameplay_anchor")

    c("route_from_start", route.get("from_node") == MC.NODE_START,
      "from_node={}".format(route.get("from_node")))
    c("route_to_primary", route.get("to_node") == MC.NODE_PRIMARY_POI,
      "to_node={}".format(route.get("to_node")))

    wps = route.get("waypoints") or []
    c("route_has_waypoints", len(wps) >= 2, "waypoints={}".format(len(wps)))
    coords_ok = len(wps) >= 2 and all(_is_coord(w) for w in wps)
    c("route_waypoints_are_coords", coords_ok, "waypoints not all coordinate lists")
    if not coords_ok:
        return

    # Length is not fabricated: declared length == recomputed segment sum (±1%).
    length = route.get("length_cm") or 0
    c("route_length_positive", length > 0, "length_cm={}".format(length))
    recomputed = sum(MC.dist2d(wps[i], wps[i + 1]) for i in range(len(wps) - 1))
    within = recomputed > 0 and abs(length - recomputed) <= LENGTH_TOL_FRAC * recomputed
    c("route_length_matches_geometry", within,
      "declared={} recomputed={}".format(length, round(recomputed, 2)))

    # Route actually connects the start anchor to the primary-POI anchor.
    if start_pos is not None:
        c("route_starts_at_start_anchor", MC.dist2d(wps[0], start_pos) <= CONNECT_TOL_CM,
          "first waypoint={} start={}".format(wps[0], start_pos))
    if poi_pos is not None:
        c("route_ends_at_primary_poi", MC.dist2d(wps[-1], poi_pos) <= CONNECT_TOL_CM,
          "last waypoint={} poi={}".format(wps[-1], poi_pos))

    # avoids_hazards must be True AND actually verified.
    avoids = route.get("avoids_hazards")
    c("route_claims_avoids_hazards", avoids is True, "avoids_hazards={}".format(avoids))
    hazards = m.get("hazard_zones") or []
    crossing = None
    for i in range(len(wps) - 1):
        for h in hazards:
            if MC.segment_intersects_bounds(wps[i], wps[i + 1], h.get("bounds") or {}):
                crossing = h.get("id")
                break
        if crossing:
            break
    # If it claims to avoid hazards, prove it: no segment may cross a hazard.
    c("route_avoids_hazards_verified", not (avoids and crossing),
      "route claims avoids_hazards but crosses hazard {}".format(crossing))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission required routes.")
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
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.MISSION_ROUTE_FAILURE)
            continue
        check_route(rep, mid, m)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-routes", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_routes",
              "validate_mission_routes_report.json")
    rep.print_summary("validate-mission-routes")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
