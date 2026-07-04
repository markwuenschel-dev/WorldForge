#!/usr/bin/env python3
"""validate_encounter_routes.py — WorldForge v1.4 encounter route validator (Lane B).

Proves every encounter's route layer keeps the linked mission playable (brief
§7/§25): approach and escape routes exist, are well-formed, and their declared
lengths are recomputed rather than trusted; the escape vector actually leads to
safety (final waypoint at a declared safe zone) and does not dead-end back in
the ambush; THE core v1.4 rule — the encounter may pressure but must never
block the mission's required route (densified-corridor blockage ratio must stay
within the encounter's own pacing target, and strictly below 1.0); the
encounter's hazard zones must leave at least one route (mission required route
or an escape route) completely hazard-free and must never swallow the mission
objective's interaction anchor; and the approach route really departs from the
mission start.

Usage:
    python tools/pipeline/validate_encounter_routes.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_routes/validate_encounter_routes_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

# Tolerances / clearances (cm unless noted).
LENGTH_TOL_FRAC = 0.05            # declared length within 5% of recomputed sum
ESCAPE_SAFE_CM = 1500.0           # escape must terminate at a safe zone
ESCAPE_SPAWN_CLEARANCE_CM = 3000.0  # escape must not dead-end in the ambush
APPROACH_START_CM = 1200.0        # approach must depart from the mission start


def _fmt(items, n=4):
    items = list(items)
    shown = ", ".join(str(x) for x in items[:n])
    return shown + (" …(+{})".format(len(items) - n) if len(items) > n else "")


def _is_coord(w):
    return (isinstance(w, (list, tuple)) and len(w) >= 2
            and all(isinstance(v, (int, float)) for v in w[:2]))


def _route_ok(r):
    wps = (r or {}).get("waypoints") or []
    return bool(r.get("route_id")) and bool(r.get("kind")) and len(wps) >= 2 \
        and all(_is_coord(w) for w in wps) \
        and isinstance(r.get("length_cm"), (int, float)) and r["length_cm"] > 0


def check_routes(rep, eid, enc, mission):
    """Core route checks for one encounter + its linked mission (importable)."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(name, eid), ok, detail,
                         code=FailureCode.ENCOUNTER_ROUTE_FAILURE)

    approaches = enc.get("approach_routes") or []
    escapes = enc.get("escape_routes") or []

    # 1/2. Both route families must exist.
    c("approach_routes_present", len(approaches) >= 1,
      "approach_routes={}".format(len(approaches)))
    c("escape_routes_present", len(escapes) >= 1,
      "escape_routes={}".format(len(escapes)))

    # 3. Every route is well-formed (route_id/kind/waypoints>=2/length_cm).
    bad = [r.get("route_id") for r in approaches + escapes if not _route_ok(r)]
    c("route_fields_valid", not bad,
      "malformed routes (route_id/kind/waypoints/length_cm): {}".format(_fmt(bad)))

    routes = [r for r in approaches + escapes if _route_ok(r)]

    # 4. Declared length is not fabricated: recomputed within 5%.
    fudged = []
    for r in routes:
        wps = r["waypoints"]
        rec = sum(MC.dist2d(wps[i - 1], wps[i]) for i in range(1, len(wps)))
        if rec <= 0 or abs(r["length_cm"] - rec) > LENGTH_TOL_FRAC * rec:
            fudged.append((r["route_id"], r["length_cm"], round(rec, 2)))
    c("route_length_matches_geometry", not fudged,
      "declared length_cm off recomputed by >{:.0%}: {}".format(
          LENGTH_TOL_FRAC, _fmt(fudged)))

    good_escapes = [r for r in escapes if _route_ok(r)]
    safes = [z.get("world_position") for z in enc.get("safe_zones") or []
             if _is_coord(z.get("world_position"))]
    spawn_pos = [a.get("world_position") for a in enc.get("spawn_anchors") or []
                 if _is_coord(a.get("world_position"))]

    # 5. Escape vector leads to safety: final waypoint at a declared safe zone.
    stranded = []
    for r in good_escapes:
        final = r["waypoints"][-1]
        d = min((MC.dist2d(final, z) for z in safes), default=None)
        if d is None or d > ESCAPE_SAFE_CM:
            stranded.append((r["route_id"], None if d is None else round(d, 1)))
    c("escape_reaches_safe_zone", bool(good_escapes) and not stranded,
      "escape routes ending >{}cm from every safe zone: {}".format(
          ESCAPE_SAFE_CM, _fmt(stranded)) if good_escapes
      else "no well-formed escape route")

    # 6. Escape does not dead-end in the ambush.
    dead_ends = []
    for r in good_escapes:
        final = r["waypoints"][-1]
        d = min((MC.dist2d(final, s) for s in spawn_pos), default=None)
        if d is not None and d < ESCAPE_SPAWN_CLEARANCE_CM:
            dead_ends.append((r["route_id"], round(d, 1)))
    c("escape_clear_of_spawns", not dead_ends,
      "escape routes ending within {}cm of a spawn anchor: {}".format(
          ESCAPE_SPAWN_CLEARANCE_CM, _fmt(dead_ends)))

    # 7. THE core v1.4 rule: the required route is pressured, never blocked.
    corridor = EC.densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))
    max_ratio = (enc.get("pacing_target") or {}).get("max_route_blockage_ratio")
    if not corridor:
        c("required_route_not_blocked", False,
          "mission required_route has no waypoints to densify")
        blockage = None
    else:
        contested = sum(
            1 for wp in corridor
            if any(MC.dist2d(wp, s) <= EC.PRESSURE_RADIUS_CM for s in spawn_pos))
        blockage = round(contested / len(corridor), 3)
        c("required_route_not_blocked",
          max_ratio is not None and blockage <= max_ratio and blockage < 1.0,
          "blockage_ratio={} max_route_blockage_ratio={} (must be <=max and <1.0)"
          .format(blockage, max_ratio))

    # 8. Encounter hazards must leave at least one hazard-free route.
    hz = [(h.get("id"), h.get("bounds") or {})
          for h in enc.get("hazard_zones") or []]

    def hazard_free(poly):
        return all(not MC.point_in_bounds(wp, b) for wp in poly for _, b in hz)

    escape_polys = [EC.densify_route(r["waypoints"]) for r in good_escapes]
    open_route = hazard_free(corridor) if corridor else False
    open_route = open_route or any(hazard_free(p) for p in escape_polys)
    c("hazards_leave_open_route", not hz or open_route,
      "every route (required route + {} escape route(s)) crosses an encounter "
      "hazard zone".format(len(escape_polys)) if hz else "no encounter hazard zones")

    # 9. No encounter hazard zone swallows a mission objective interaction anchor.
    covered = [(hid, o.get("id"))
               for o in (mission or {}).get("objective_anchors") or []
               if _is_coord(o.get("world_position"))
               for hid, b in hz
               if MC.point_in_bounds(o["world_position"], b)]
    c("hazard_clear_of_objective", not covered,
      "encounter hazard zones containing mission objective anchors: {}".format(
          _fmt(covered)))

    # 10. Approach route departs from the mission start.
    start = ((mission or {}).get("start_anchor") or {}).get("world_position")
    astray = []
    for r in approaches:
        if not _route_ok(r):
            continue
        d = MC.dist2d(r["waypoints"][0], start) if _is_coord(start) else None
        if d is None or d > APPROACH_START_CM:
            astray.append((r["route_id"], None if d is None else round(d, 1)))
    c("approach_starts_at_mission_start", _is_coord(start) and not astray,
      "approach routes starting >{}cm from mission start: {}".format(
          APPROACH_START_CM, _fmt(astray))
      if _is_coord(start) else "mission start_anchor position missing")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter routes.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("loads::{}".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_ROUTE_FAILURE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        if mission is None:
            rep.check("mission_loads::{}".format(eid), False, merr,
                      code=FailureCode.ENCOUNTER_ROUTE_FAILURE)
            continue
        check_routes(rep, eid, enc, mission)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-routes", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_routes",
              "validate_encounter_routes_report.json")
    rep.print_summary("validate-encounter-routes")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
