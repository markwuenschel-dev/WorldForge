#!/usr/bin/env python3
r"""materialize_npc_actors.py — WorldForge v1.7 Wave R NPC materialization.

Boots the UE editor ONCE and places the v1.7 runtime actor set — the grounded
player pawn (AWFGroundedRuntimePawn), the mission objective (AWFRuntimeObjective)
and the NPC encounter manager (AWFEncounterManager) — on every map the behavior
matrix drives, via tools/unreal/npc_headless_prepare.py. Writes a materialization
report (wf.npc.materialization_report.v1) recording which maps were prepared. It is
FAIL-CLOSED: if the editor cannot be launched or a map is not prepared, the map is
recorded as failed and the report status is FAIL.

The per-scenario NPC spec is supplied at RUN time (env), so a map is materialized
once and drives both pressure profiles. Maps are restored clean afterwards by the
batch (prepare is a required idempotent step); the reports are the committed
evidence.

Acceptance: `python tools/pipeline/materialize_npc_actors.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _fs(p):
    return str(p).replace("\\", "/")


PREPARE_SCRIPT = _fs(REPO_ROOT / "tools/unreal/npc_headless_prepare.py")
UPROJECT = _fs(REPO_ROOT / "WorldForge.uproject")
UE_CMD = os.environ.get(
    "WF_UE_CMD",
    r"C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe")
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


def run_prepare(maps):
    jobs = REPO_ROOT / "procedural/generated/npc/_npc_prepare_maps.json"
    jobs.parent.mkdir(parents=True, exist_ok=True)
    jobs.write_text(json.dumps(maps), encoding="utf-8")
    env = dict(os.environ, WF_PREP_MAPS=str(jobs), MSYS_NO_PATHCONV="1")
    cmd = [UE_CMD, UPROJECT, "-ExecutePythonScript=" + PREPARE_SCRIPT,
           "-unattended", "-nopause", "-nosplash", "-stdout"]
    print("[npc-materialize] placing NPC encounter manager + grounded pawn + objective "
          "on {} maps (1 editor boot)...".format(len(maps)))
    if not Path(UE_CMD).is_file():
        print("[npc-materialize] UE not found at {} — cannot materialize".format(UE_CMD))
        return set()
    subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = REPO_ROOT / "Saved/Logs/WorldForge.log"
    prepared = set()
    if log.is_file():
        for ln in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "WF_NPCPREP OK prepared" in ln:
                # "... OK prepared <map_id> start=..."
                try:
                    prepared.add(ln.split("OK prepared", 1)[1].split()[0])
                except Exception:  # noqa: BLE001
                    pass
    return prepared


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.7 NPC materialization.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    maps = scenario_maps()
    if args.limit:
        maps = maps[:args.limit]
    prepared = run_prepare(maps) if maps else set()

    rep = ValidationReport("pack", args.pack, strict=strict)
    rep.check("materialize::scenarios_exist", len(maps) > 0,
              "no behavior scenarios generated (run generate-npc-behavior-scenarios)",
              code=FailureCode.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE)
    missing = [m for m in maps if m not in prepared]
    rep.check("materialize::all_maps_prepared", not missing,
              "{}/{} maps materialized; missing: {}".format(len(prepared & set(maps)), len(maps),
                                                            missing[:8]),
              code=FailureCode.NPC_MATERIALIZATION_FAILURE)
    for m in maps:
        rep.check("materialize::{}".format(m), m in prepared,
                  "encounter manager + pawn + objective placed", code=FailureCode.NPC_ACTOR_MISSING)

    rep.finalize()
    out = {
        "report_type": NX.RT_MATERIALIZATION, "pack": args.pack,
        "maps_total": len(maps), "maps_prepared": sorted(prepared & set(maps)),
        "maps_missing": missing,
        "meta": build_meta(command="materialize-npc-actors", pack=args.pack, strict=strict,
                           status="ok" if not missing else "fail", record_count=len(maps),
                           report_type=NX.RT_MATERIALIZATION, report_id="npc_materialization_manifest",
                           records_total=len(maps), records_failed=len(missing),
                           records_passed=len(maps) - len(missing)),
    }
    rep.set_meta(build_meta(command="materialize-npc-actors", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(maps),
                            report_type=NX.RT_MATERIALIZATION,
                            records_total=len(maps), records_failed=len(missing),
                            extra=out))
    outdir = REPO_ROOT / NX.MATERIALIZATION_REPORTS_REL
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "materialization_manifest.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    rep.write(outdir, "materialize_npc_actors_report.json")
    rep.print_summary("materialize-npc-actors")
    print("[npc-materialize] {}/{} maps materialized".format(len(prepared & set(maps)), len(maps)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
