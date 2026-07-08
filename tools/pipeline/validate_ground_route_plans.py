#!/usr/bin/env python3
"""validate_ground_route_plan.py — WorldForge v1.6z route-plan gate.

Validates every generated ground route_plan against the frozen contract.
"""
import argparse, json, sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
import ground_contracts as GX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GEN_DIR = REPO_ROOT / getattr(GX, "ROUTE_PLAN_GENERATED_REL")

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)
    items = {}
    if GEN_DIR.is_dir():
        for p in sorted(GEN_DIR.glob("*.json")):
            if p.name.startswith(("generate_", "validate_")):
                continue
            items[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    for sid, obj in items.items():
        for name, ok, detail, c in GX.validate_route_plan(obj, strict=strict):
            rep.check("{}::{}".format(sid, name), ok, detail, code=c)
    rep.check("route_plan_present", len(items) > 0, "{} ground route_plan(s) on disk".format(len(items)),
              code=FailureCode.GROUND_ROUTE_GRAPH_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-ground-route-plan", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(items),
                            report_type="wf.ground.route_plan.v1"))
    rep.write(GEN_DIR, "validate_ground_route_plan_report.json")
    rep.print_summary("validate-ground-route-plan")
    print("[validate-ground-route-plan] {} validated".format(len(items)))
    sys.exit(rep.exit_code)

if __name__ == "__main__":
    main()
