#!/usr/bin/env python3
"""validate_encounter_hazards.py — WorldForge v1.4 encounter hazard validator (Lane D).

Proves hazards are BIOME-TRUE, READABLE and FAIR (brief §12/§27):

  * every hazard zone carries id / hazard_type / bounds / visual_marker; its
    hazard_type is a known EC.HAZARD_TYPES member AND allowed for the biome
    (EC.BIOME_HAZARD_TYPES[biome])
  * every hazard zone is marked visually: visual_marker_requirements contains
    an entry whose target_id equals the hazard zone id
  * bounds are well-formed (min < max on x and y)
  * a route alternative exists: the densified mission required_route is never
    entirely swallowed by a hazard zone, and at least one escape route runs
    entirely outside ALL hazard bounds
  * hazards never contain the mission start position or any mission objective
    position
  * hazard pressure is modeled: the hazard_type has a weight in
    EC.HAZARD_PRESSURE_WEIGHTS
  * archetype rule: hazard_field encounters must declare >= 1 hazard zone
    (other archetypes may legitimately have zero — zone checks only run when
    zones exist)

Usage:
    python tools/pipeline/validate_encounter_hazards.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_hazards/validate_encounter_hazards_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.ENCOUNTER_CONTRACT_FAILURE
BIOME_CODE = FailureCode.ENCOUNTER_BIOME_COMPATIBILITY_FAILURE
ROUTE_CODE = FailureCode.ENCOUNTER_ROUTE_FAILURE
MISSION_CODE = FailureCode.ENCOUNTER_MISSION_COMPATIBILITY_FAILURE
PRESSURE_CODE = FailureCode.ENCOUNTER_PRESSURE_FAILURE
ARCHETYPE_CODE = FailureCode.ENCOUNTER_ARCHETYPE_FAILURE

HAZARD_ZONE_REQUIRED = ("id", "hazard_type", "bounds", "visual_marker")


def _bounds_well_formed(bounds):
    mn, mx = (bounds or {}).get("min"), (bounds or {}).get("max")
    if not mn or not mx or len(mn) < 2 or len(mx) < 2:
        return False
    return mn[0] < mx[0] and mn[1] < mx[1]


def check_hazards(rep, eid, enc, mission):
    """Core hazard checks for one encounter (namespace '<check>::<eid>')."""
    def c(name, ok, detail="", code=CODE):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=code)

    biome = enc.get("biome_family")
    hazard_zones = enc.get("hazard_zones") or []

    # hazard_field is the one archetype REQUIRED to field hazards.
    if enc.get("encounter_archetype") == "hazard_field":
        c("hazard_field_has_hazard_zone", bool(hazard_zones),
          "hazard_field encounter declares no hazard zones", code=ARCHETYPE_CODE)
    if not hazard_zones:
        return

    allowed = EC.BIOME_HAZARD_TYPES.get(biome, ())
    markers = enc.get("visual_marker_requirements") or []
    waypoints = EC.densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))
    start = ((mission or {}).get("start_anchor") or {}).get("world_position")
    objectives = [(oa.get("id"), oa.get("world_position"))
                  for oa in (mission or {}).get("objective_anchors") or []
                  if oa.get("world_position")]

    for hz in hazard_zones:
        hid = hz.get("id") or "<no-id>"
        htype = hz.get("hazard_type")
        bounds = hz.get("bounds") or {}

        missing = [k for k in HAZARD_ZONE_REQUIRED if not hz.get(k)]
        c("hazard_fields_present[{}]".format(hid), not missing,
          "hazard zone '{}' missing required fields {}".format(hid, missing))

        c("hazard_type_known[{}]".format(hid), htype in EC.HAZARD_TYPES,
          "hazard_type {!r} not in EC.HAZARD_TYPES".format(htype))
        c("hazard_type_biome_allowed[{}]".format(hid), htype in allowed,
          "hazard_type {!r} not allowed for biome '{}' ({})".format(
              htype, biome, list(allowed)), code=BIOME_CODE)

        # Hazard must be visually marked for readability.
        c("hazard_visually_marked[{}]".format(hid),
          any(v.get("target_id") == hz.get("id") for v in markers),
          "no visual_marker_requirements entry targets hazard zone '{}'".format(hid))

        c("hazard_bounds_well_formed[{}]".format(hid), _bounds_well_formed(bounds),
          "bounds min/max malformed (need min < max on x and y): {!r}".format(bounds))

        # Route alternative (a): the required route must not be fully swallowed.
        if waypoints:
            c("hazard_leaves_route_alternative[{}]".format(hid),
              not all(MC.point_in_bounds(wp, bounds) for wp in waypoints),
              "every densified required_route waypoint lies inside hazard "
              "zone '{}' — no route alternative".format(hid), code=ROUTE_CODE)

        # Hazards may not contain the mission start or any objective position.
        if start:
            c("hazard_excludes_mission_start[{}]".format(hid),
              not MC.point_in_bounds(start, bounds),
              "mission start position lies inside hazard zone '{}'".format(hid),
              code=MISSION_CODE)
        for oid, opos in objectives:
            c("hazard_excludes_objective[{}][{}]".format(hid, oid),
              not MC.point_in_bounds(opos, bounds),
              "mission objective '{}' lies inside hazard zone '{}'".format(oid, hid),
              code=MISSION_CODE)

        # Hazard pressure must be modeled.
        c("hazard_pressure_modeled[{}]".format(hid),
          htype in EC.HAZARD_PRESSURE_WEIGHTS,
          "hazard_type {!r} has no weight in EC.HAZARD_PRESSURE_WEIGHTS".format(htype),
          code=PRESSURE_CODE)

    # Route alternative (b): at least one escape route entirely outside ALL hazards.
    escape_ok = False
    for er in enc.get("escape_routes") or []:
        ewps = EC.densify_route(er.get("waypoints"))
        if ewps and all(not MC.point_in_bounds(wp, hz.get("bounds") or {})
                        for wp in ewps for hz in hazard_zones):
            escape_ok = True
            break
    c("hazard_escape_route_exists", escape_ok,
      "no escape route runs entirely outside all {} hazard zone(s)".format(
          len(hazard_zones)), code=ROUTE_CODE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter hazard zones.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted(eid for eid, e in (catalog.get("encounters") or {}).items()
                  if (e or {}).get("pack_id") == args.pack)
    if not eids:
        rep.error("no encounters in pack '{}' — run 'make create-encounters' first".format(args.pack))

    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("loads::{}".format(eid), False, err, code=CODE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        if mission is None:
            rep.check("mission_loads::{}".format(eid), False, merr, code=MISSION_CODE)
            continue
        check_hazards(rep, eid, enc, mission)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-hazards", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_hazards",
              "validate_encounter_hazards_report.json")
    rep.print_summary("validate-encounter-hazards")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
