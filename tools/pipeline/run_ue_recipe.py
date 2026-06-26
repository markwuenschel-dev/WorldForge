#!/usr/bin/env python3
r"""
run_ue_recipe.py -- launch headless UE to prepare a material recipe.

Stages the manifest to a fixed no-spaces path so -ExecutePythonScript can
find the script without path-parsing issues, then boots UnrealEditor-Cmd.

Usage:
    python tools/pipeline/run_ue_recipe.py --recipe terrain_rock_desert_cracked_01

Env overrides:
    UE_EDITOR_CMD   path to UnrealEditor-Cmd.exe
    WF_UPROJECT     path to the .uproject
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
STAGING = REPO / "procedural" / "reports" / "recipes" / "_active_manifest.json"
UE_SCRIPT = REPO / "tools" / "unreal" / "prepare_recipe_material.py"

DEFAULT_EDITOR_WSL = "/mnt/c/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-cmd.exe"
DEFAULT_EDITOR_WIN = r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"


def _is_wsl():
    try:
        with open("/proc/version") as f:
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
    ap = argparse.ArgumentParser(description="Prepare a material recipe via headless UE.")
    ap.add_argument("--recipe", required=True, help="Recipe id, e.g. terrain_rock_desert_cracked_01")
    ap.add_argument("--editor", default=os.environ.get("UE_EDITOR_CMD", DEFAULT_EDITOR))
    ap.add_argument("--uproject", default=os.environ.get("WF_UPROJECT", str(REPO / "WorldForge.uproject")))
    args = ap.parse_args()

    manifest_path = REPO / "procedural" / "manifests" / "materials" / (args.recipe + ".json")
    if not manifest_path.is_file():
        raise SystemExit("[run-ue-recipe] manifest not found: {}".format(manifest_path))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    STAGING.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(manifest_path), str(STAGING))
    print("[run-ue-recipe] staged manifest '{}' -> {}".format(args.recipe, STAGING))

    if not os.path.isfile(args.editor):
        raise SystemExit("[run-ue-recipe] editor not found: {} (set UE_EDITOR_CMD)".format(args.editor))
    if not UE_SCRIPT.is_file():
        raise SystemExit("[run-ue-recipe] script not found: {}".format(UE_SCRIPT))

    cmd = [
        args.editor,
        _to_win(Path(args.uproject)),
        "-ExecutePythonScript={}".format(_to_win(UE_SCRIPT)),
        "-unattended", "-nopause", "-nosplash", "-nosound", "-stdout",
    ]
    print("[run-ue-recipe] launching headless UE for recipe: {}".format(args.recipe))
    started = time.time()
    proc = subprocess.run(cmd)
    elapsed = time.time() - started
    print("[run-ue-recipe] editor exited rc={} after {:.0f}s".format(proc.returncode, elapsed))

    recipe_id = manifest.get("recipe_id", args.recipe)
    report_path = REPO / "procedural" / "reports" / "recipes" / recipe_id / "prepare_recipe_report.json"
    rc = proc.returncode
    if not report_path.is_file():
        print("[run-ue-recipe] FAIL: prepare_recipe_material.py did not write report")
        rc = rc or 1
    else:
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        passed = bool(rep.get("passed"))
        verdict = "PASS" if passed else "FAIL"
        print("[run-ue-recipe] report verdict: {}".format(verdict))
        if not passed:
            for step, ok in rep.get("steps", {}).items():
                if not ok:
                    print("[run-ue-recipe]   FAIL step: {}".format(step))
        rc = rc or (0 if passed else 1)

    raise SystemExit(rc)


if __name__ == "__main__":
    main()
