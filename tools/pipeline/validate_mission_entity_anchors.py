#!/usr/bin/env python3
"""validate_mission_entity_anchors.py — WorldForge v1.3 mission entity-anchor wiring validator (Agent 4).

Proves the mission's navigation graph is WIRED TO THE REAL GENERATED MAP, not
fabricated (brief §5 entity/anchor consumption). Each mission names a source_map
slice; that slice has a generated entity-anchors file
(procedural/generated/entity_anchors/<slice_id>.json) carrying the level-design
reference the map was built from. This validator asserts:

  * the source map's entity_anchors file exists;
  * the mission's start_anchor.world_position matches the entity anchors'
    level_design_ref.player_start_world (within tolerance) — a fabricated mission
    would not sit exactly on the generated player start;
  * the mission's primary_poi.gameplay_anchor sits on the map's
    level_design_ref.poi_origin_world (XY within tolerance — same POI region);
  * the mission references a real POI class.

A mission whose anchors do not correspond to the generated map anchors is a
graph-integrity failure (MISSION_GRAPH_FAILURE): the objective graph would float
free of the level it claims to be layered over.

Usage:
    python tools/pipeline/validate_mission_entity_anchors.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_entity_anchors/validate_mission_entity_anchors_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from generate_level_design import POI_CLASSES
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.MISSION_GRAPH_FAILURE
ENTITY_ANCHORS_REL = "procedural/generated/entity_anchors"
# XY tolerances (cm). The generated data matches to sub-centimetre, so these are
# generous safety margins while still catching a fabricated (off-by-thousands)
# anchor. A false mission would miss by the map's scale (tens of thousands of cm).
START_TOL_CM = 100.0
POI_TOL_CM = 100.0
KNOWN_POI_CLASSES = set(POI_CLASSES)


def _dist2d(a, b):
    return ((float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2) ** 0.5


def check_mission(rep, mid, m):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=CODE)

    slice_id = ((m.get("source_map") or {}).get("slice_id")) or ""
    ea_path = REPO_ROOT / ENTITY_ANCHORS_REL / (slice_id + ".json")
    if not slice_id:
        c("source_slice_named", False, "mission has no source_map.slice_id")
        return
    if not ea_path.is_file():
        c("entity_anchors_exist", False, "entity anchors file missing: {}".format(ea_path))
        return
    c("entity_anchors_exist", True, str(ea_path))

    try:
        ea = json.loads(ea_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        c("entity_anchors_parse", False, "unparseable entity anchors: {}".format(exc))
        return
    ld = ea.get("level_design_ref") or {}

    # start_anchor must sit on the generated player_start.
    ps = ld.get("player_start_world")
    sa = (m.get("start_anchor") or {}).get("world_position")
    if not ps or not sa:
        c("start_anchor_wired", False,
          "missing player_start_world ({}) or start_anchor.world_position ({})".format(ps, sa))
    else:
        d = _dist2d(sa, ps)
        c("start_anchor_wired", d <= START_TOL_CM,
          "start_anchor XY off generated player_start by {:.2f}cm (tol {}) sa={} ps={}".format(
              d, START_TOL_CM, sa, ps))

    # primary_poi.gameplay_anchor must sit in the map's POI region.
    po = ld.get("poi_origin_world")
    ga = (m.get("primary_poi") or {}).get("gameplay_anchor")
    if not po or not ga:
        c("primary_poi_wired", False,
          "missing poi_origin_world ({}) or primary_poi.gameplay_anchor ({})".format(po, ga))
    else:
        d = _dist2d(ga, po)
        c("primary_poi_wired", d <= POI_TOL_CM,
          "primary_poi XY off generated poi_origin by {:.2f}cm (tol {}) ga={} po={}".format(
              d, POI_TOL_CM, ga, po))

    # The mission must reference a real POI class.
    poi_class = (m.get("primary_poi") or {}).get("poi_class")
    c("poi_class_real", poi_class in KNOWN_POI_CLASSES,
      "primary_poi.poi_class '{}' is not a known POI class".format(poi_class))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission entity-anchor wiring.")
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
            rep.check("{}::loads".format(mid), False, err, code=CODE)
            continue
        check_mission(rep, mid, m)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-entity-anchors", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_entity_anchors",
              "validate_mission_entity_anchors_report.json")
    rep.print_summary("validate-mission-entity-anchors")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
