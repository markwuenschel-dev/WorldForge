#!/usr/bin/env python3
"""validate_tactical_affordances.py — v2.4 Wave 2 affordance authoring gate.

Re-validates every generated TacticalAffordanceMap from disk against tactical_contracts
AND performs the cross-record resolution the schema-only contract cannot: the tile_id
resolves to a real generated tile, every retreat_anchor resolves to a real anchor, every
flank_route resolves to a real route whose traversal is a PROVED grounded WorldForge mode
(no navmesh overclaim), every source_report exists on disk, cover markers are well-formed,
and the 24-map matrix is complete. Coverage: 24 affordance maps.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_tactical_affordances.py --strict
Reports -> procedural/reports/tactical/affordances/validate_tactical_affordances_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
import tactical_spec as SP
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

GEN = REPO_ROOT / "procedural" / "generated"
AFF_DIR = GEN / "tactical" / "affordances"
TILES_DIR = GEN / "tiles"
ANCHORS_DIR = GEN / "anchors"
ROUTES_DIR = GEN / "routes"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "affordances"

PROVED_MODES = ("grounded_worldforge_route", "grounded_manual_waypoint")


def _load_all(d):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))}


def validate(rep):
    affs = _load_all(AFF_DIR)
    tile_ids = {p.stem for p in TILES_DIR.glob("*.json")}
    anchor_ids = {p.stem for p in ANCHORS_DIR.glob("*.json")}
    routes = _load_all(ROUTES_DIR)

    rep.check("count::affordances_24", len(affs) == SP.EXPECTED_SCENARIO_COUNT,
              "must have 24 affordance maps (got {})".format(len(affs)),
              code=F.TACTICAL_AFFORDANCE_MAP_INVALID)

    n = 0
    for name, am in affs.items():
        n += 1
        fails = [c for c in TC.validate_tactical_affordance_map(am, strict=True) if not c[1]]
        rep.check("aff::{}::valid".format(name), len(fails) == 0,
                  "affordance map invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_AFFORDANCE_MAP_INVALID)
        # tile resolves
        rep.check("aff::{}::tile_resolves".format(name), am.get("tile_id") in tile_ids,
                  "tile_id {} does not resolve to a real tile".format(am.get("tile_id")),
                  code=F.TACTICAL_AFFORDANCE_MAP_INVALID)
        # retreat anchors resolve
        for a in am.get("retreat_anchors") or []:
            rep.check("aff::{}::retreat_anchor_resolves::{}".format(name, a),
                      a in anchor_ids,
                      "retreat_anchor {} does not resolve".format(a),
                      code=F.TACTICAL_ANCHOR_REFERENCE_INVALID)
        # flank routes resolve AND are proved grounded (no navmesh overclaim)
        for rt in am.get("flank_routes") or []:
            rep.check("aff::{}::flank_route_resolves::{}".format(name, rt),
                      rt in routes,
                      "flank_route {} does not resolve".format(rt),
                      code=F.TACTICAL_ROUTE_REFERENCE_INVALID)
            mode = routes.get(rt, {}).get("traversal_mode")
            rep.check("aff::{}::flank_route_proved::{}".format(name, rt),
                      rt not in routes or mode in PROVED_MODES,
                      "flank_route {} traversal {} is not a proved grounded mode "
                      "(navmesh overclaim)".format(rt, mode),
                      code=F.TACTICAL_NAVMESH_OVERCLAIM)
        # source reports exist on disk
        for sr in am.get("source_reports") or []:
            rep.check("aff::{}::source_exists".format(name), (REPO_ROOT / sr).exists(),
                      "source_report {} does not exist".format(sr),
                      code=F.TACTICAL_AFFORDANCE_MAP_INVALID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical affordance authoring gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_affordances", strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-tactical-affordances", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.affordance_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_tactical_affordances_report.json")
    rep.print_summary("validate-tactical-affordances")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
