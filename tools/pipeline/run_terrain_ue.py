#!/usr/bin/env python3
r"""
run_terrain_ue.py — launch a headless UE Python script against a terrain descriptor.

    python tools/pipeline/run_terrain_ue.py \
        --script import_terrain_heightmap.py --name Terrain_AshFlats_01

Stages the terrain descriptor to a fixed pointer file the UE script reads, then
boots the editor headless.  Mirrors run_slice_ue.py's approach.

Env overrides:
    UE_EDITOR_CMD   path to UnrealEditor-Cmd.exe
    WF_UPROJECT     path to .uproject
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ACTIVE_TERRAIN = REPO / "procedural" / "reports" / "terrain" / "_active_terrain_descriptor.json"
UE_DIR = REPO / "tools" / "unreal"
DEFAULT_EDITOR_WSL = "/mnt/c/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-cmd.exe"
DEFAULT_EDITOR_WIN = r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"


def _is_wsl():
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


_IN_WSL = _is_wsl()
DEFAULT_EDITOR = DEFAULT_EDITOR_WSL if _IN_WSL else DEFAULT_EDITOR_WIN


def _to_win(path):
    if _IN_WSL:
        win = subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
        return win.replace("\\", "/")
    return str(path).replace("\\", "/")


def main():
    ap = argparse.ArgumentParser(description="Boot headless UE to run a terrain script.")
    ap.add_argument("--script", required=True, help="Script filename under tools/unreal/")
    ap.add_argument("--name", required=True, help="Terrain name, e.g. Terrain_AshFlats_01")
    ap.add_argument("--editor", default=os.environ.get("UE_EDITOR_CMD", DEFAULT_EDITOR))
    ap.add_argument("--uproject", default=os.environ.get("WF_UPROJECT", str(REPO / "WorldForge.uproject")))
    args = ap.parse_args()

    desc_path = REPO / "procedural" / "generated" / "terrain" / args.name / "descriptor.json"
    if not desc_path.is_file():
        raise SystemExit("[run-terrain-ue] descriptor not found: {} — run create-terrain first".format(desc_path))

    descriptor = json.loads(desc_path.read_text(encoding="utf-8"))
    ACTIVE_TERRAIN.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(desc_path), str(ACTIVE_TERRAIN))
    print("[run-terrain-ue] staged descriptor '{}' -> {}".format(args.name, ACTIVE_TERRAIN))

    script_path = UE_DIR / args.script
    if not script_path.is_file():
        raise SystemExit("[run-terrain-ue] script not found: {}".format(script_path))
    if not os.path.isfile(args.editor):
        raise SystemExit("[run-terrain-ue] editor not found: {} (set UE_EDITOR_CMD)".format(args.editor))

    cmd = [
        args.editor,
        _to_win(Path(args.uproject)),
        "-ExecutePythonScript={}".format(_to_win(script_path)),
        "-unattended", "-nopause", "-nosplash", "-nosound", "-stdout",
    ]
    print("[run-terrain-ue] launching headless UE: {}".format(args.script))
    started = time.time()
    proc = subprocess.run(cmd)
    print("[run-terrain-ue] editor exited rc={} after {:.0f}s".format(
        proc.returncode, time.time() - started))

    rc = proc.returncode
    report_dir = REPO / "procedural" / "reports" / "terrain" / args.name
    report_name = {
        "import_terrain_heightmap.py": "ue_terrain_report.json",
    }.get(args.script)
    if report_name:
        rpt_path = report_dir / report_name
        if not rpt_path.is_file():
            print("[run-terrain-ue] FAIL: {} did not write {}".format(args.script, rpt_path))
            rc = rc or 1
        else:
            rpt = json.loads(rpt_path.read_text(encoding="utf-8"))
            passed = bool(rpt.get("passed"))
            print("[run-terrain-ue] {} report: {}".format(args.script, "PASS" if passed else "FAIL"))
            if not passed:
                for f in rpt.get("failures", []):
                    print("[run-terrain-ue]   - {}".format(f))
                rc = rc or 1
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
