#!/usr/bin/env python3
"""create_encounter_pack.py — v1.4 gate: validate/register encounter_loop_world.

Proves the encounter pack spec is coherent before generation: encounterforge
marker present, source pack is the missionforge pack with 60 missions, contract
enums match the spec lists, and all 8 archetype specs parse. Pure validation +
report; generation itself lives in create_encounters.py.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from failure_codes import FailureCode
from mission_catalog import load_mission_catalog
from report_meta import build_meta, hash_file, strict_from_env
from validation_report import ValidationReport
from world_pack_maps import resolve_world_pack_path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    code = FailureCode.ENCOUNTER_CONTRACT_FAILURE

    spec_path = resolve_world_pack_path(args.pack)
    rep.check("pack_spec_exists", spec_path is not None and Path(spec_path).is_file(),
              "world pack yaml for {}".format(args.pack), code=code)
    data = {}
    if spec_path and Path(spec_path).is_file():
        import yaml
        data = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8")) or {}

    rep.check("encounterforge_marker", bool(data.get("encounterforge")),
              "encounterforge: true required", code=code)
    rep.check("source_pack_is_missionforge",
              data.get("source_pack") == "mission_loop_world",
              "source_pack={}".format(data.get("source_pack")), code=code)

    rep.check("biome_families_match",
              tuple(data.get("biome_families") or ()) == MC.BIOME_FAMILIES,
              "pack biome_families must equal contract BIOME_FAMILIES", code=code)
    rep.check("mission_archetypes_match",
              tuple(data.get("mission_archetypes") or ()) == MC.MISSION_ARCHETYPES,
              "pack mission_archetypes must equal contract", code=code)
    rep.check("encounter_archetypes_match",
              tuple(data.get("encounter_archetypes") or ()) == EC.ENCOUNTER_ARCHETYPES,
              "pack encounter_archetypes must equal contract", code=code)
    rep.check("encounter_profiles_match",
              tuple(data.get("encounter_profiles") or ()) == EC.ENCOUNTER_PROFILES,
              "pack encounter_profiles must equal contract", code=code)

    archetypes = EC.load_all_archetypes()
    for a in EC.ENCOUNTER_ARCHETYPES:
        spec = archetypes.get(a)
        rep.check("archetype_spec::{}".format(a),
                  spec is not None and spec.get("encounter_archetype") == a,
                  "definitions/encounters/archetypes/{}.yaml".format(a),
                  code=FailureCode.ENCOUNTER_ARCHETYPE_FAILURE)

    catalog = load_mission_catalog(REPO_ROOT)
    missions = catalog.get("missions") or {}
    rep.check("source_missions_present", len(missions) == 60,
              "mission catalog has {} missions (expected 60)".format(len(missions)),
              code=code)

    rep.finalize()
    rep.set_meta(build_meta(
        command="create-encounter-pack", pack=args.pack, strict=strict,
        input_spec_hash=hash_file(spec_path) if spec_path and Path(spec_path).is_file() else None,
        status=rep.status, failure_count=len(rep.failures),
        warning_count=len(rep.warnings), record_count=len(missions)))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "create_encounter_pack",
              "create_encounter_pack_report.json")
    rep.print_summary("create-encounter-pack")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
