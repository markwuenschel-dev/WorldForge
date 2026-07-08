#!/usr/bin/env python3
"""validate_runtime_scenarios.py — WorldForge v1.6 scenario schema + linkage gate (Agent 4B).

Validates every generated RuntimeScenario against the frozen contract (schema,
no-unknown-fields, no-teleport-recovery) AND proves each scenario's linkage:
its map, mission, and encounter exist in the real catalogs, and its declared
mission_archetype/encounter_profile match the linked records. A scenario that
points at a nonexistent mission or a map that was never realized fails here.

Usage:
    python tools/pipeline/validate_runtime_scenarios.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/scenarios/validate_runtime_scenarios_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_scenario_contract as SC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

MISSION_CATALOG_REL = "procedural/generated/worldforge_mission_catalog.json"
ENCOUNTER_CATALOG_REL = "procedural/generated/worldforge_encounter_catalog.json"


def load_scenarios():
    d = REPO_ROOT / SC.SCENARIO_GENERATED_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                out[p.stem] = {"__parse_error__": str(e)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 runtime scenario validator.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    missions = (json.loads((REPO_ROOT / MISSION_CATALOG_REL).read_text(encoding="utf-8"))
                .get("missions") or {})
    encounters = (json.loads((REPO_ROOT / ENCOUNTER_CATALOG_REL).read_text(encoding="utf-8"))
                  .get("encounters") or {})
    maps = {m.get("source_map") for m in missions.values()}
    scenarios = load_scenarios()
    if not scenarios:
        rep.error("no runtime scenarios — run 'make runtime-scenarios' first")

    for sid in sorted(scenarios):
        scen = scenarios[sid]
        if "__parse_error__" in scen:
            rep.check("{}::parses".format(sid), False, scen["__parse_error__"],
                      code=C.RUNTIME_SCENARIO_SCHEMA_FAILURE)
            continue
        for name, ok, detail, code in SC.validate_scenario(scen, strict=strict):
            rep.check("{}::{}".format(sid, name), ok, detail, code=code)
        # linkage
        mid = scen.get("mission_id")
        eid = scen.get("encounter_id")
        rep.check("{}::mission_exists".format(sid), mid in missions,
                  "mission {!r} missing from catalog".format(mid),
                  code=C.RUNTIME_SCENARIO_GENERATION_FAILURE)
        rep.check("{}::encounter_exists".format(sid), eid in encounters,
                  "encounter {!r} missing from catalog".format(eid),
                  code=C.RUNTIME_SCENARIO_GENERATION_FAILURE)
        rep.check("{}::map_realized".format(sid), scen.get("map_id") in maps,
                  "map {!r} not among realized mission maps".format(scen.get("map_id")),
                  code=C.RUNTIME_MAP_LOAD_FAILURE)
        if eid in encounters:
            enc = encounters[eid]
            rep.check("{}::archetype_matches".format(sid),
                      scen.get("mission_archetype") == enc.get("mission_archetype"),
                      "archetype mismatch vs encounter", code=C.RUNTIME_SCENARIO_SCHEMA_FAILURE)
            rep.check("{}::profile_matches".format(sid),
                      scen.get("encounter_profile") == enc.get("encounter_profile"),
                      "profile mismatch vs encounter", code=C.RUNTIME_SCENARIO_SCHEMA_FAILURE)

    rep.check("all_scenarios_present", len(scenarios) == len(encounters) and len(scenarios) > 0,
              "{}/{} scenarios present".format(len(scenarios), len(encounters)),
              code=C.RUNTIME_SCENARIO_COVERAGE_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-scenarios", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(scenarios),
                            report_type="wf.runtime.scenario_manifest.v1",
                            extra={"scenarios": len(scenarios), "encounters": len(encounters)}))
    rep.write(REPO_ROOT / SC.SCENARIO_REPORTS_REL, "validate_runtime_scenarios_report.json")
    rep.print_summary("validate-runtime-scenarios")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
