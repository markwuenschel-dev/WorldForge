#!/usr/bin/env python3
"""validate_npc_actors.py — WorldForge v1.7 actor-materialization gate.

Proves the NPC runtime actor set (grounded pawn + objective + encounter manager) was
genuinely REALIZED in the engine on every map the behavior matrix drives — not merely
that the spawn groups validate on paper. It accepts the manifest emitted by
materialize_npc_actors.py in either mode:

  runtime_spawn (canonical): the gate does NOT trust the manifest's map list — it
      RE-DERIVES the realized set independently from the committed behavior-completion
      evidence (a success completion with npc_count > 0 == the engine spawned NPCs on
      that map at runtime), requires every scenario map to be covered, and requires the
      manifest to match that evidence-derived set exactly (no map claimed without proof,
      none omitted). So a green here is backed by the same runtime evidence
      validate-npc-completion proves genuine.

  baked_editor (editor-preview / v1.7x): the gate checks the maps the editor prepare
      step actually saved, per the manifest.

FAIL-CLOSED: a missing/unreadable manifest, an unknown mode, any un-realized scenario
map, or any manifest/evidence mismatch turns the gate RED.

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
COMPLETION_DIR = REPO_ROOT / NX.COMPLETION_REPORTS_REL


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
        mode = manifest.get("materialization_mode")
        rep.check("actors::mode_known", mode in NX.MATERIALIZATION_MODES,
                  "unknown materialization_mode: {}".format(mode),
                  code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)
        claimed = set(manifest.get("maps_prepared", []))

        if mode == NX.RUNTIME_SPAWN_MODE:
            # Independently re-derive realization from committed runtime evidence — the
            # manifest is NOT trusted as the source of truth.
            realized = NX.runtime_realized_maps(COMPLETION_DIR)
            missing = [m for m in maps if m not in realized]
            rep.check("actors::all_maps_materialized", not missing,
                      "{}/{} maps runtime-realized; missing: {}".format(
                          len(realized & set(maps)), len(maps), missing[:8]),
                      code=FailureCode.NPC_ACTOR_MISSING)
            # Integrity: the manifest must match the evidence-derived set exactly.
            phantom = sorted(claimed - (realized & set(maps)))
            rep.check("actors::manifest_matches_evidence", not phantom,
                      "manifest claims maps without runtime evidence: {}".format(phantom[:8]),
                      code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)
            omitted = sorted((realized & set(maps)) - claimed)
            rep.check("actors::manifest_complete", not omitted,
                      "manifest omits runtime-realized maps: {}".format(omitted[:8]),
                      code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)
        else:
            # baked_editor: trust the maps the editor prepare step actually saved.
            missing = [m for m in maps if m not in claimed]
            rep.check("actors::all_maps_materialized", not missing,
                      "{}/{} maps baked; missing: {}".format(len(claimed & set(maps)), len(maps),
                                                             missing[:8]),
                      code=FailureCode.NPC_ACTOR_MISSING)
            phantom = [m for m in claimed if m not in set(maps)]
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
