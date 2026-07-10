#!/usr/bin/env python3
"""generate_equipment_catalog.py — WorldForge v1.9 reward equipment + loadout gen.

Materializes the deterministic EquipmentItem catalog and the LoadoutProfile set
from the reward_forge spine. Every record is validated against its own contract
(``RX.validate_equipment_item`` / ``RX.validate_loadout_profile``) under STRICT
with ZERO failures BEFORE anything is written — a generator that emits a record
its own contract rejects is a bug, never a written artifact.

Equipment items are written via run_generator to
``procedural/generated/rewards/equipment/{item_id}.json``; loadout profiles are
written to ``procedural/generated/loadouts/{loadout_profile_id}.json``. The single
report -> ``procedural/reports/rewards/catalog/generate_equipment_catalog_report.json``.

Acceptance: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_equipment_catalog.py --strict`.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
import reward_forge as F
from npc_gen_common import run_generator, write_records
from report_meta import strict_from_env
from failure_codes import FailureCode

EQUIPMENT_GENERATED_REL = "procedural/generated/rewards/equipment"
REPORT_REL = "procedural/reports/rewards/catalog"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    equipment = F.build_equipment_catalog()
    loadouts = F.build_loadout_profiles()

    # Pre-validate both sets under strict. Loadouts are written here (run_generator
    # only writes the records it is handed); equipment is written by run_generator.
    # Neither set is written unless BOTH are fully valid — no partial catalog.
    eq_fails = sum(1 for e in equipment
                   if any(not c[1] for c in RX.validate_equipment_item(e, strict=True)))
    lo_bad = []
    for p in loadouts:
        f = [c[0] for c in RX.validate_loadout_profile(p, strict=True) if not c[1]]
        if f:
            lo_bad.append((p.get("loadout_profile_id", "?"), f[:4]))

    if eq_fails == 0 and not lo_bad and len(loadouts) > 0:
        write_records(loadouts, RX.LOADOUT_GENERATED_REL, "loadout_profile_id")

    extra = [
        ("equipment-catalog::loadouts_nonzero", len(loadouts) > 0,
         "expected >=1 loadout profile, got {}".format(len(loadouts)),
         FailureCode.LOADOUT_CONTRACT_INVALID),
        ("equipment-catalog::loadouts_valid", not lo_bad,
         "loadout profiles failed their own contract: {}".format(lo_bad),
         FailureCode.LOADOUT_CONTRACT_INVALID),
    ]

    run_generator("generate-equipment-catalog", args.pack, equipment,
                  RX.validate_equipment_item, EQUIPMENT_GENERATED_REL, "item_id",
                  REPORT_REL, "generate_equipment_catalog_report.json",
                  RX.RT_EQUIPMENT_ITEM, FailureCode.EQUIPMENT_ITEM_INVALID,
                  strict=strict, extra_checks=extra)


if __name__ == "__main__":
    main()
