#!/usr/bin/env python3
"""generate_npc_archetypes.py — WorldForge v1.7 NPC archetype + model generator.

Emits the canonical NPC archetype roster (5 required + 2 stretch) plus the
perception and pressure models they reference, each validated against its own
strict contract at generation time. Pack-level (encounter-independent).

Acceptance: `make npc-archetypes PACK=encounter_loop_world STRICT=1`.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
import npc_pack as NP
from npc_gen_common import write_records, run_generator
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    archetypes = [NP.build_archetype(r) for r in NX.NPC_ARCHETYPES]
    perceptions = [NP.build_perception(p) for p in NP.PERCEPTION_DEFS]
    pressures = [NP.build_pressure(p) for p in NP.PRESSURE_DEFS]

    rep = ValidationReport("pack", args.pack, strict=strict)
    # Every required archetype must be present.
    have = {a["behavior_role"] for a in archetypes}
    missing = [r for r in NX.REQUIRED_NPC_ARCHETYPES if r not in have]
    rep.check("archetypes::required_present", not missing,
              "missing required archetypes: {}".format(missing),
              code=FailureCode.NPC_ARCHETYPE_SCHEMA_FAILURE)
    # Every perception/pressure model an archetype references must exist.
    perc_ids = {p["perception_model_id"] for p in perceptions}
    prs_ids = {p["pressure_model_id"] for p in pressures}
    ref_perc_ok = all(a["perception_model"] in perc_ids for a in archetypes)
    ref_prs_ok = all("prs_{}".format(a["pressure_model"]) in prs_ids or a["pressure_model"] == "none"
                     for a in archetypes)
    rep.check("archetypes::perception_refs_resolve", ref_perc_ok,
              "an archetype references an unknown perception_model", code=FailureCode.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE)
    rep.check("archetypes::pressure_refs_resolve", ref_prs_ok,
              "an archetype references an unknown pressure_model", code=FailureCode.NPC_PRESSURE_MODEL_SCHEMA_FAILURE)

    invalid = 0
    for rec in archetypes:
        if [c for c in NX.validate_archetype(rec, strict=True) if not c[1]]:
            invalid += 1
    for rec in perceptions:
        if [c for c in NX.validate_perception_model(rec, strict=True) if not c[1]]:
            invalid += 1
    for rec in pressures:
        if [c for c in NX.validate_pressure_model(rec, strict=True) if not c[1]]:
            invalid += 1
    rep.check("archetypes::all_valid", invalid == 0, "{} invalid records".format(invalid),
              code=FailureCode.NPC_ARCHETYPE_SCHEMA_FAILURE)

    total = len(archetypes) + len(perceptions) + len(pressures)
    if rep.passed:
        write_records(archetypes, NX.ARCHETYPE_GENERATED_REL, "npc_archetype_id")
        write_records(perceptions, NX.PERCEPTION_MODEL_GENERATED_REL, "perception_model_id")
        write_records(pressures, NX.PRESSURE_MODEL_GENERATED_REL, "pressure_model_id")

    rep.finalize()
    rep.set_meta(build_meta(command="generate-npc-archetypes", pack=args.pack, strict=strict,
                            status=rep.status, record_count=total, report_type=NX.RT_ARCHETYPE,
                            records_total=total, records_failed=invalid))
    rep.write(REPO_ROOT / "procedural/reports/npc/archetypes", "generate_npc_archetypes_report.json")
    rep.print_summary("generate-npc-archetypes")
    print("[generate-npc-archetypes] {} archetypes, {} perception, {} pressure models".format(
        len(archetypes), len(perceptions), len(pressures)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
