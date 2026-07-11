#!/usr/bin/env python3
"""generate_streamed_bindings.py — v2.3 Wave 2 streamed mission/NPC bindings (Agent 4).

Emits one StreamedMissionBinding + one StreamedNPCBinding for each of the 24
streaming scenarios (scenario_plan). Missions cross exactly 2 tiles with 1 stream
transition and bind to their v2.2 quest (quest/faction hook). NPC bindings spawn at
the target tile and keep perception/pressure/combat scope INSIDE their allowed tiles
(no pressure in an unloaded tile). Deterministic; every record validated before write.

Deliverables (handoff §12 Agent 4):
    procedural/generated/streaming/mission_bindings/*.json
    procedural/generated/streaming/npc_bindings/*.json
    procedural/reports/streaming/authoring/binding_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_streamed_bindings.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
import streaming_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

MISSION_DIR = REPO_ROOT / "procedural" / "generated" / "streaming" / "mission_bindings"
NPC_DIR = REPO_ROOT / "procedural" / "generated" / "streaming" / "npc_bindings"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "authoring"


def _quest_id(scn):
    # bind to the v2.2 baseline quest for this biome/archetype/seed.
    return "qf_{}_{}_baseline_s{}".format(scn["biome"], scn["mission_archetype"], scn["seed"])


def generate(rep):
    MISSION_DIR.mkdir(parents=True, exist_ok=True)
    NPC_DIR.mkdir(parents=True, exist_ok=True)
    scns = SPEC.scenario_plan()
    rep.check("scenarios::count_24", len(scns) == SC.EXPECTED_SCENARIO_COUNT,
              "expected 24 scenarios (got {})".format(len(scns)),
              code=F.STREAMING_PARTIAL_MATRIX)

    n = 0
    for scn in scns:
        sid = scn["scenario_id"]
        target_tile = scn["path_tiles"][1]
        mission = SC._example_streamed_mission_binding(
            binding_id="smb_" + sid, region_id=scn["region_id"], scenario_id=sid,
            quest_id=_quest_id(scn), mission_archetype=scn["mission_archetype"],
            required_tile_ids=list(scn["path_tiles"]),
            start_anchor_id=scn["start_anchor_id"],
            objective_anchor_ids=[scn["objective_anchor_id"]],
            completion_anchor_id=scn["objective_anchor_id"],
            required_cross_tile_routes=[scn["route_id"]],
            streaming_requirements={"min_transitions": 1,
                                    "streaming_profile": scn["streaming_profile"]},
            runtime_claims_required=[
                {"claim": "transition", "op": ">=", "value": 1},
                {"claim": "route", "op": "==", "value": "completed"},
                {"claim": "mission", "op": "==", "value": "completed"},
                {"claim": "save_load", "op": "==", "value": "roundtrip_ok"},
            ],
            streaming_profile=scn["streaming_profile"], seed=scn["seed"])
        mfails = [c for c in SC.validate_streamed_mission_binding(mission, strict=True) if not c[1]]
        rep.check("mission::{}::valid".format(sid), len(mfails) == 0,
                  "mission binding invalid: {}".format([c[0] for c in mfails][:4]),
                  code=F.STREAMING_MISSION_BINDING_INVALID)
        (MISSION_DIR / ("smb_" + sid + ".json")).write_text(
            json.dumps(mission, indent=2, sort_keys=True), encoding="utf-8")

        npc = SC._example_streamed_npc_binding(
            binding_id="snb_" + sid, region_id=scn["region_id"], scenario_id=sid,
            npc_profile_id="npc_sentry_baseline", spawn_anchor_id=scn["npc_spawn_anchor_id"],
            allowed_tile_ids=list(scn["path_tiles"]),
            perception_tile_scope=[target_tile], pressure_tile_scope=[target_tile],
            combat_tile_scope=[target_tile], stream_in_policy="spawn_on_tile_load",
            stream_out_policy="despawn_on_tile_unload", save_load_key="sl_npc_" + sid)
        nfails = [c for c in SC.validate_streamed_npc_binding(npc, strict=True) if not c[1]]
        rep.check("npc::{}::valid".format(sid), len(nfails) == 0,
                  "npc binding invalid: {}".format([c[0] for c in nfails][:4]),
                  code=F.STREAMING_NPC_BINDING_INVALID)
        (NPC_DIR / ("snb_" + sid + ".json")).write_text(
            json.dumps(npc, indent=2, sort_keys=True), encoding="utf-8")
        n += 1

    rep.check("bindings::24_each", n == SC.EXPECTED_SCENARIO_COUNT,
              "expected 24 mission+npc bindings (got {})".format(n),
              code=F.STREAMING_PARTIAL_MATRIX)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 streamed mission/NPC binding generator.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-streamed-bindings", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.binding_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "binding_report.json")
    rep.print_summary("generate-streamed-bindings")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
