#!/usr/bin/env python3
r"""materialize_npc_actors.py — WorldForge v1.7 NPC materialization.

v1.7 realizes the runtime actor set (grounded player pawn + mission objective + NPC
encounter manager) in TWO modes:

  runtime_spawn (default, CANONICAL):
      UWFRuntimeAutoSpawnSubsystem spawns the actor set at world begin-play in
      standalone `-game` when the batch drives a map (WF_NPC_SCENARIO_ID). No editor
      boot, no baked .umap — the whole 120-scenario matrix reproduces from a clean
      checkout. This command emits the materialization manifest by reading the COMMITTED
      behavior-completion evidence: a map is "materialized" iff the engine genuinely
      spawned NPCs on it at runtime (a success completion report with npc_count > 0).
      It cannot be greened without real runtime behavior — the evidence it reads is what
      validate-npc-completion independently proves genuine.

  baked_editor (optional, --bake; editor-preview / v1.7x):
      Boots the UE editor once and bakes the actor set into every map via
      tools/unreal/npc_headless_prepare.py, then records which maps were prepared. This
      is only for in-editor preview; the headless matrix does not require it.

FAIL-CLOSED: any scenario map without genuine runtime realization (or, under --bake, a
map the editor failed to prepare) turns the report FAIL.

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


def run_prepare(maps):
    """--bake path: boot the editor once and bake the actor set into each map."""
    jobs = REPO_ROOT / "procedural/generated/npc/_npc_prepare_maps.json"
    jobs.parent.mkdir(parents=True, exist_ok=True)
    jobs.write_text(json.dumps(maps), encoding="utf-8")
    env = dict(os.environ, WF_PREP_MAPS=str(jobs), MSYS_NO_PATHCONV="1")
    cmd = [UE_CMD, UPROJECT, "-ExecutePythonScript=" + PREPARE_SCRIPT,
           "-unattended", "-nopause", "-nosplash", "-stdout"]
    print("[npc-materialize] --bake: placing NPC encounter manager + grounded pawn + "
          "objective on {} maps (1 editor boot)...".format(len(maps)))
    if not Path(UE_CMD).is_file():
        print("[npc-materialize] UE not found at {} — cannot bake".format(UE_CMD))
        return set()
    subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = REPO_ROOT / "Saved/Logs/WorldForge.log"
    prepared = set()
    if log.is_file():
        for ln in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "WF_NPCPREP OK prepared" in ln:
                try:
                    prepared.add(ln.split("OK prepared", 1)[1].split()[0])
                except Exception:  # noqa: BLE001
                    pass
    return prepared


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.7 NPC materialization.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--bake", action="store_true",
                    help="editor-preview mode: bake the actor set into the .umap files (v1.7x)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    maps = scenario_maps()
    if args.limit:
        maps = maps[:args.limit]

    mode = NX.BAKED_EDITOR_MODE if args.bake else NX.RUNTIME_SPAWN_MODE
    if args.bake:
        prepared = run_prepare(maps) if maps else set()
    else:
        # Canonical runtime_spawn: a map is realized iff genuine runtime evidence exists.
        prepared = NX.runtime_realized_maps(COMPLETION_DIR) & set(maps)

    rep = ValidationReport("pack", args.pack, strict=strict)
    rep.check("materialize::scenarios_exist", len(maps) > 0,
              "no behavior scenarios generated (run generate-npc-behavior-scenarios)",
              code=FailureCode.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE)
    missing = [m for m in maps if m not in prepared]
    detail_verb = "baked" if args.bake else "runtime-realized"
    rep.check("materialize::all_maps_materialized", not missing,
              "{}/{} maps {}; missing: {}".format(len(prepared & set(maps)), len(maps),
                                                  detail_verb, missing[:8]),
              code=FailureCode.NPC_MATERIALIZATION_FAILURE)

    rep.finalize()
    out = {
        "report_type": NX.RT_MATERIALIZATION, "pack": args.pack,
        "materialization_mode": mode,
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
    print("[npc-materialize] mode={} — {}/{} maps materialized".format(
        mode, len(prepared & set(maps)), len(maps)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
