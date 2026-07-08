#!/usr/bin/env python3
"""validate_runtime_route_plans.py — WorldForge v1.6 route plan + preflight gate (Agent 4D).

Validates every RuntimeRoutePlan against the frozen contract and runs the
authoring-side navmesh/collision PREFLIGHT: navmesh + collision are required, a
goal and >=2 well-formed waypoints exist, and every scenario's route_plan_id
resolves to a real plan on the correct map. This is the static preflight — the
brief's "navmesh exists / spawn reachable / objective reachable / corridor clear"
against LIVE geometry is the Gamma runner's job and fails closed while the editor
is offline (RUNTIME_LIVE_RUN_PENDING).

Usage:
    python tools/pipeline/validate_runtime_route_plans.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/routes/validate_runtime_route_plans_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_route_contract as RC
import runtime_scenario_contract as SC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _load_dir(rel):
    d = REPO_ROOT / rel
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 route plan gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    plans = _load_dir(RC.ROUTE_GENERATED_REL)
    scenarios = _load_dir(SC.SCENARIO_GENERATED_REL)
    if not plans:
        rep.error("no route plans — run 'make runtime-route-plans' first")

    for rpid in sorted(plans):
        plan = plans[rpid]
        for name, ok, detail, code in RC.validate_route_plan(plan, strict=strict):
            rep.check("{}::{}".format(rpid, name), ok, detail, code=code)
        # Preflight: navmesh + collision required on every plan.
        rep.check("{}::navmesh_required".format(rpid), plan.get("navmesh_required") is True,
                  "route plan must require navmesh", code=C.RUNTIME_NAVMESH_MISSING)
        rep.check("{}::collision_required".format(rpid), plan.get("collision_required") is True,
                  "route plan must require collision", code=C.RUNTIME_COLLISION_INVALID)

    # Every scenario's route_plan_id must resolve to a real plan on the same map.
    plans_by_id = {p.get("route_plan_id"): p for p in plans.values()}
    for sid in sorted(scenarios):
        scen = scenarios[sid]
        rpid = scen.get("route_plan_id")
        plan = plans_by_id.get(rpid)
        rep.check("{}::route_resolves".format(sid), plan is not None,
                  "scenario route_plan_id {!r} has no plan".format(rpid),
                  code=C.RUNTIME_ROUTE_PLAN_FAILURE)
        if plan is not None:
            rep.check("{}::route_same_map".format(sid), plan.get("map_id") == scen.get("map_id"),
                      "route plan map {!r} != scenario map {!r}".format(
                          plan.get("map_id"), scen.get("map_id")),
                      code=C.RUNTIME_ROUTE_PLAN_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-route-plans", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(plans),
                            report_type="wf.runtime.route_plan.v1",
                            extra={"routes": len(plans), "scenarios": len(scenarios)}))
    rep.write(REPO_ROOT / RC.ROUTE_REPORTS_REL, "validate_runtime_route_plans_report.json")
    rep.print_summary("validate-runtime-route-plans")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
