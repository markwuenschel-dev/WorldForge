#!/usr/bin/env python3
"""validate_runtime_scenario_coverage.py — WorldForge v1.6 coverage gate (Agent 4E).

Proves the generated runtime scenario set covers the full matrix the brief
requires: all 5 biomes, all 6 mission archetypes, both pressure profiles, and 60
distinct realized maps — with 120 scenario records present. Silent
under-coverage (a missing biome, only one profile, 118 of 120) is exactly the
partial-success-as-success smell this gate exists to catch.

Usage:
    python tools/pipeline/validate_runtime_scenario_coverage.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/scenarios/validate_runtime_scenario_coverage_report.json
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

EXPECTED_BIOMES = ("temperate_forest", "alpine_snow", "volcanic_ashlands",
                   "wetland_mire", "alien_crystal_badlands")
EXPECTED_ARCHETYPES = SC.MISSION_ARCHETYPES
EXPECTED_PROFILES = SC.ENCOUNTER_PROFILES
EXPECTED_MAPS = 60
EXPECTED_SCENARIOS = 120


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 scenario coverage gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    man_path = REPO_ROOT / SC.SCENARIO_MANIFEST_REL
    if not man_path.is_file():
        rep.error("no scenario manifest — run 'make runtime-scenarios' first")
        rep.finalize()
        rep.set_meta(build_meta(command="validate-runtime-scenario-coverage", pack=args.pack,
                                strict=strict, status=rep.status, record_count=0,
                                report_type="wf.runtime.scenario_manifest.v1"))
        rep.write(REPO_ROOT / SC.SCENARIO_REPORTS_REL,
                  "validate_runtime_scenario_coverage_report.json")
        rep.print_summary("validate-runtime-scenario-coverage")
        sys.exit(rep.exit_code)

    scen = (json.loads(man_path.read_text(encoding="utf-8")).get("scenarios") or {})
    biomes = {v.get("biome") for v in scen.values()}
    archs = {v.get("mission_archetype") for v in scen.values()}
    profiles = {v.get("encounter_profile") for v in scen.values()}
    maps = {v.get("map_id") for v in scen.values()}

    rep.check("scenario_count", len(scen) == EXPECTED_SCENARIOS,
              "{} scenarios (expected {})".format(len(scen), EXPECTED_SCENARIOS),
              code=C.RUNTIME_SCENARIO_COVERAGE_FAILURE)
    rep.check("distinct_maps", len(maps) == EXPECTED_MAPS,
              "{} distinct maps (expected {})".format(len(maps), EXPECTED_MAPS),
              code=C.RUNTIME_SCENARIO_COVERAGE_FAILURE)
    rep.check("all_biomes_covered", set(EXPECTED_BIOMES) <= biomes,
              "missing biomes: {}".format(sorted(set(EXPECTED_BIOMES) - biomes)),
              code=C.RUNTIME_SCENARIO_COVERAGE_FAILURE)
    rep.check("all_archetypes_covered", set(EXPECTED_ARCHETYPES) <= archs,
              "missing archetypes: {}".format(sorted(set(EXPECTED_ARCHETYPES) - archs)),
              code=C.RUNTIME_SCENARIO_COVERAGE_FAILURE)
    rep.check("both_profiles_covered", set(EXPECTED_PROFILES) <= profiles,
              "missing profiles: {}".format(sorted(set(EXPECTED_PROFILES) - profiles)),
              code=C.RUNTIME_SCENARIO_COVERAGE_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-scenario-coverage", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(scen),
                            report_type="wf.runtime.scenario_manifest.v1",
                            extra={"biomes": sorted(biomes), "archetypes": sorted(archs),
                                   "profiles": sorted(profiles), "distinct_maps": len(maps)}))
    rep.write(REPO_ROOT / SC.SCENARIO_REPORTS_REL,
              "validate_runtime_scenario_coverage_report.json")
    rep.print_summary("validate-runtime-scenario-coverage")
    print("[validate-runtime-scenario-coverage] {} scenarios, {} maps, {} biomes, "
          "{} archetypes, {} profiles".format(len(scen), len(maps), len(biomes),
                                              len(archs), len(profiles)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
