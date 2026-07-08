#!/usr/bin/env python3
"""validate_ground_walkability.py — WorldForge v1.6z walkability gate.

Validates every WalkabilityReport against the contract and enforces coverage: one
report per unique map, none with zero surfaces checked, and (under STRICT) every
scenario's map must be spawn->objective walkable so the grounded route substrate
has somewhere to route.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_contracts as GX
import run_ground_runtime_batch as RB
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

WALK_DIR = REPO_ROOT / GX.WALKABILITY_REPORTS_REL


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    maps = sorted({r["map_id"] for r in RB.scenarios()})
    reports = {}
    if WALK_DIR.is_dir():
        for p in sorted(WALK_DIR.glob("*.json")):
            if p.name.startswith(("validate_", "generate_")):
                continue
            reports[p.stem] = json.loads(p.read_text(encoding="utf-8"))

    for sid, r in reports.items():
        for name, ok, detail, code in GX.validate_walkability(r, strict=strict):
            rep.check("{}::{}".format(sid, name), ok, detail, code=code)

    missing = [m for m in maps if m not in reports]
    rep.check("walkability_one_per_map", not missing,
              "{}/{} maps have a walkability report{}".format(
                  len(reports), len(maps), "" if not missing else "; missing {}".format(missing[:3])),
              code=FailureCode.GROUND_WALKABILITY_ANALYSIS_FAILURE, warn_only=(len(reports) < len(maps)))
    walkable_maps = sum(1 for r in reports.values() if r.get("spawn_to_objective_walkable"))
    rep.check("walkability_spawn_to_objective",
              walkable_maps == len(reports) and len(reports) > 0,
              "{}/{} maps are spawn->objective walkable".format(walkable_maps, len(reports)),
              code=FailureCode.GROUND_OBJECTIVE_ACCESS_FAILURE, warn_only=(walkable_maps < len(reports)))

    rep.finalize()
    rep.set_meta(build_meta(command="validate-ground-walkability", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(reports),
                            report_type="wf.ground.walkability_report.v1",
                            extra={"maps": len(reports), "spawn_to_objective_walkable": walkable_maps}))
    rep.write(WALK_DIR, "validate_ground_walkability_report.json")
    rep.print_summary("validate-ground-walkability")
    print("[validate-ground-walkability] {} maps analyzed, {} spawn->objective walkable".format(
        len(reports), walkable_maps))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
