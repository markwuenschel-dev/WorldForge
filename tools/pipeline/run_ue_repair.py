#!/usr/bin/env python3
r"""
run_ue_repair.py -- launch headless UE to repair a named slice.

Usage:
    python tools/pipeline/run_ue_repair.py --name Desert_Ash_Outpost_01

Looks up the slice in the registry, stages its spec, runs repair_slice.py,
reads the repair report, and exits 0/1.

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
ACTIVE_SPEC = REPO / "procedural" / "reports" / "slices" / "_active_slice_spec.json"
UE_SCRIPT   = REPO / "tools" / "unreal" / "repair_slice.py"

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
    ap = argparse.ArgumentParser(description="Repair a WorldForge slice via headless UE.")
    ap.add_argument("--name", required=True, help="Slice name, e.g. Desert_Ash_Outpost_01")
    ap.add_argument("--editor",   default=os.environ.get("UE_EDITOR_CMD", DEFAULT_EDITOR))
    ap.add_argument("--uproject", default=os.environ.get("WF_UPROJECT", str(REPO / "WorldForge.uproject")))
    args = ap.parse_args()

    # Load registry.
    sys.path.insert(0, str(REPO / "tools" / "pipeline"))
    from registry import load_registry
    registry = load_registry(REPO)

    if args.name not in registry:
        raise SystemExit("[run-ue-repair] slice '{}' not in registry — cannot repair".format(args.name))

    entry = registry[args.name]
    biome = entry.get("biome", "unknown")
    spec_rel = entry.get("spec_path")
    if not spec_rel:
        raise SystemExit("[run-ue-repair] registry entry for '{}' has no spec_path".format(args.name))

    spec_path = REPO / spec_rel
    if not spec_path.is_file():
        raise SystemExit("[run-ue-repair] spec not found: {}".format(spec_path))

    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    ACTIVE_SPEC.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(spec_path), str(ACTIVE_SPEC))
    print("[run-ue-repair] staged spec '{}' -> {}".format(args.name, ACTIVE_SPEC))

    if not os.path.isfile(args.editor):
        raise SystemExit("[run-ue-repair] editor not found: {} (set UE_EDITOR_CMD)".format(args.editor))
    if not UE_SCRIPT.is_file():
        raise SystemExit("[run-ue-repair] script not found: {}".format(UE_SCRIPT))

    cmd = [
        args.editor,
        _to_win(Path(args.uproject)),
        "-ExecutePythonScript={}".format(_to_win(UE_SCRIPT)),
        "-unattended", "-nopause", "-nosplash", "-nosound", "-stdout",
    ]
    print("[run-ue-repair] launching headless UE for repair: {}".format(args.name))
    started = time.time()
    proc = subprocess.run(cmd)
    print("[run-ue-repair] editor exited rc={} after {:.0f}s".format(proc.returncode, time.time() - started))

    out_dir_rel = spec.get("output_dir",
        "procedural/reports/slices/{}/{}".format(biome, args.name))
    report_path = REPO / out_dir_rel / "repair_slice_report.json"
    rc = proc.returncode

    if not report_path.is_file():
        print("[run-ue-repair] FAIL: repair_slice.py did not write report at {}".format(report_path))
        rc = rc or 1
    else:
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        passed = bool(rep.get("passed"))
        verdict = "PASS" if passed else "FAIL"
        print("[run-ue-repair] repair verdict: {}".format(verdict))
        repairs = rep.get("repairs", [])
        no_change = rep.get("no_change_needed", [])
        errors = rep.get("errors", [])
        if repairs:
            for r in repairs:
                print("[run-ue-repair]   repaired: {}".format(r))
        if no_change:
            print("[run-ue-repair]   no_change_needed: {}".format(", ".join(no_change)))
        for e in errors:
            print("[run-ue-repair]   error: {}".format(e))
        rc = rc or (0 if passed else 1)

    raise SystemExit(rc)


if __name__ == "__main__":
    main()
