#!/usr/bin/env python3
"""validate_npc_behavior_scenarios.py — WorldForge v1.7 behavior-scenario gate.

Validates the generated behavior scenario matrix as a whole, not just per-record:

  * every scenario passes its strict contract;
  * every referenced spawn group and behavior profile actually exists (no dangling
    references);
  * every scenario's ground_scenario_id resolves to a v1.6z route plan whose status
    is valid and whose traversal_mode is grounded — a scenario may NOT be grounded
    on a flight/teleport plan (NPC traversal truth);
  * the matrix is complete (>= the full 120) and no partial set is reported as full.

Acceptance: `make validate-npc-behavior-scenarios PACK=encounter_loop_world STRICT=1`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
import npc_pack as NP
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GROUNDED_MODES = ("grounded_worldforge_route", "grounded_manual_waypoint")


def _load_ids(rel):
    d = REPO_ROOT / rel
    return {p.stem for p in d.glob("*.json")} if d.is_dir() else set()


def _load_all(rel):
    d = REPO_ROOT / rel
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--expected", type=int, default=120)
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    scenarios = _load_all(NX.BEHAVIOR_SCENARIO_GENERATED_REL)
    spawn_group_ids = _load_ids(NX.SPAWN_GROUP_GENERATED_REL)
    profile_ids = _load_ids(NX.BEHAVIOR_PROFILE_GENERATED_REL)
    plans = NP.load_route_plans()

    rep.check("scenarios::exist", len(scenarios) > 0,
              "no behavior scenarios generated (run generate-npc-behavior-scenarios)",
              code=FailureCode.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE)

    invalid = dangling = ungrounded = 0
    for s in scenarios:
        sid = s.get("behavior_scenario_id", "?")
        if [c for c in NX.validate_behavior_scenario(s, strict=True) if not c[1]]:
            invalid += 1
            continue
        # cross-refs
        for g in s.get("spawn_groups", []):
            if g not in spawn_group_ids:
                dangling += 1
                rep.check("scn::{}::spawn_group".format(sid), False,
                          "spawn group {} not found".format(g),
                          code=FailureCode.NPC_SPAWN_POINT_MISSING)
        for pf in s.get("behavior_profiles", []):
            if pf not in profile_ids:
                dangling += 1
                rep.check("scn::{}::profile".format(sid), False,
                          "behavior profile {} not found".format(pf),
                          code=FailureCode.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE)
        # grounded route-plan binding — no flight/teleport.
        plan = plans.get(s.get("ground_scenario_id"))
        if plan is None:
            ungrounded += 1
            rep.check("scn::{}::ground_ref".format(sid), False,
                      "ground_scenario_id does not resolve to a route plan",
                      code=FailureCode.NPC_ROUTE_GRAPH_MISSING)
        else:
            if plan.get("status") != "valid":
                ungrounded += 1
                rep.check("scn::{}::plan_valid".format(sid), False,
                          "grounded route plan status != valid", code=FailureCode.NPC_ROUTE_BINDING_FAILURE)
            if plan.get("traversal_mode") not in GROUNDED_MODES:
                ungrounded += 1
                rep.check("scn::{}::plan_grounded".format(sid), False,
                          "route plan traversal_mode {} is not grounded".format(plan.get("traversal_mode")),
                          code=FailureCode.NPC_ROUTE_FLIGHT_REQUIRED)

    rep.check("scenarios::all_valid", invalid == 0, "{} invalid scenarios".format(invalid),
              code=FailureCode.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE)
    rep.check("scenarios::no_dangling_refs", dangling == 0, "{} dangling references".format(dangling),
              code=FailureCode.NPC_ROUTE_BINDING_FAILURE)
    rep.check("scenarios::all_grounded_no_flight", ungrounded == 0,
              "{} scenarios not grounded on a valid grounded route plan".format(ungrounded),
              code=FailureCode.NPC_ROUTE_FLIGHT_REQUIRED)
    # Matrix completeness — a partial set must not be reported as the full matrix.
    rep.check("scenarios::matrix_complete", len(scenarios) >= args.expected,
              "matrix has {} scenarios, expected >= {} (no partial-as-full)".format(
                  len(scenarios), args.expected),
              code=FailureCode.GROUND_REPORT_PARTIAL_MATRIX)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-behavior-scenarios", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(scenarios),
                            report_type="wf.npc.behavior_scenario_manifest.v1",
                            records_total=len(scenarios), records_failed=invalid + dangling + ungrounded))
    rep.write(REPO_ROOT / "procedural/reports/npc/behavior_scenarios",
              "validate_npc_behavior_scenarios_report.json")
    rep.print_summary("validate-npc-behavior-scenarios")
    print("[validate-npc-behavior-scenarios] {} scenarios, {} spawn groups, {} profiles".format(
        len(scenarios), len(spawn_group_ids), len(profile_ids)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
