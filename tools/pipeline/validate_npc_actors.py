#!/usr/bin/env python3
"""validate_npc_actors.py — WorldForge v1.7 Wave R actor-materialization gate.

Validates the materialization report emitted by materialize_npc_actors.py: every
map the behavior matrix drives must have had its runtime actor set (grounded pawn +
objective + encounter manager) placed, with no map left un-materialized. This is the
in-engine counterpart to the schema-layer spawn-placement gate — it proves the
actors were actually realized in UE, not merely that the spawn groups validate on
paper. FAIL-CLOSED: a missing report or any un-prepared map turns the gate RED.

Acceptance: `python tools/pipeline/validate_npc_actors.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

MANIFEST = REPO_ROOT / NX.MATERIALIZATION_REPORTS_REL / "materialization_manifest.json"
SCEN_DIR = REPO_ROOT / NX.BEHAVIOR_SCENARIO_GENERATED_REL


def scenario_maps():
    maps = set()
    if SCEN_DIR.is_dir():
        for f in sorted(SCEN_DIR.glob("*.json")):
            try:
                maps.add(json.loads(f.read_text(encoding="utf-8"))["map_id"])
            except Exception:  # noqa: BLE001
                continue
    return sorted(maps)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    maps = scenario_maps()
    rep.check("actors::scenarios_exist", len(maps) > 0, "no behavior scenarios generated",
              code=FailureCode.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE)

    manifest = None
    if MANIFEST.is_file():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep.check("actors::manifest_readable", False, "unreadable: {}".format(e),
                      code=FailureCode.NPC_MATERIALIZATION_FAILURE)
    rep.check("actors::manifest_exists", manifest is not None,
              "no materialization manifest (run materialize-npc-actors)",
              code=FailureCode.NPC_MATERIALIZATION_FAILURE)

    if manifest is not None:
        rep.check("actors::report_type", manifest.get("report_type") == NX.RT_MATERIALIZATION,
                  "manifest report_type mismatch", code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)
        prepared = set(manifest.get("maps_prepared", []))
        missing = [m for m in maps if m not in prepared]
        rep.check("actors::all_maps_materialized", not missing,
                  "{}/{} maps materialized; missing: {}".format(len(prepared & set(maps)), len(maps),
                                                                missing[:8]),
                  code=FailureCode.NPC_ACTOR_MISSING)
        # No un-manifested maps claimed as prepared (integrity: no phantom green).
        phantom = [m for m in prepared if m not in set(maps)]
        rep.check("actors::no_phantom_maps", not phantom,
                  "manifest lists maps not in the scenario set: {}".format(phantom[:8]),
                  code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-actors", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(maps),
                            report_type=NX.RT_MATERIALIZATION, records_total=len(maps)))
    rep.write(REPO_ROOT / NX.MATERIALIZATION_REPORTS_REL, "validate_npc_actors_report.json")
    rep.print_summary("validate-npc-actors")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
