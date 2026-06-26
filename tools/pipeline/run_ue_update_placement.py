#!/usr/bin/env python3
r"""
run_ue_update_placement.py -- launch headless UE to update placement tags on a slice map.

Reads the slice spec to find the slice_id, loads its placement DA descriptor from
    procedural/generated/placement/<slice_id>_da.json
Stages it to the fixed pointer (no spaces in path):
    procedural/reports/slices/_active_placement_da.json
Then boots UnrealEditor-Cmd with update_slice_placement_tags.py.

Usage:
    python tools/pipeline/run_ue_update_placement.py --spec procedural/slices/desert/generated/Desert_Ash_Outpost_01.json

Env overrides:
    UE_EDITOR_CMD  path to UnrealEditor-Cmd.exe
    WF_UPROJECT    path to the .uproject
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
STAGING = REPO / "procedural" / "reports" / "slices" / "_active_placement_da.json"
UE_SCRIPT = REPO / "tools" / "unreal" / "update_slice_placement_tags.py"

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
    ap = argparse.ArgumentParser(
        description="Update placement preset tags on a slice map via headless UE."
    )
    ap.add_argument("--spec", required=True, help="path to generated slice spec JSON")
    ap.add_argument("--editor", default=os.environ.get("UE_EDITOR_CMD", DEFAULT_EDITOR))
    ap.add_argument("--uproject", default=os.environ.get("WF_UPROJECT", str(REPO / "WorldForge.uproject")))
    args = ap.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = REPO / spec_path
    if not spec_path.is_file():
        raise SystemExit("[run-ue-update-placement] spec not found: {}".format(spec_path))

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    slice_id = spec.get("slice_id", spec_path.stem)
    biome = spec.get("biome", "unknown")

    da_path = REPO / "procedural" / "generated" / "placement" / "{}_da.json".format(slice_id)
    if not da_path.is_file():
        raise SystemExit(
            "[run-ue-update-placement] placement DA not found: {} "
            "(run generate_placement_da.py first)".format(da_path)
        )

    STAGING.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(da_path), str(STAGING))
    print("[run-ue-update-placement] staged DA '{}' -> {}".format(slice_id, STAGING))

    if not os.path.isfile(args.editor):
        raise SystemExit("[run-ue-update-placement] editor not found: {}".format(args.editor))
    if not UE_SCRIPT.is_file():
        raise SystemExit("[run-ue-update-placement] script not found: {}".format(UE_SCRIPT))

    cmd = [
        args.editor,
        _to_win(Path(args.uproject)),
        "-ExecutePythonScript={}".format(_to_win(UE_SCRIPT)),
        "-unattended", "-nopause", "-nosplash", "-nosound", "-stdout",
    ]
    print("[run-ue-update-placement] launching headless UE for slice: {}".format(slice_id))
    started = time.time()
    proc = subprocess.run(cmd)
    elapsed = time.time() - started
    print("[run-ue-update-placement] editor exited rc={} after {:.0f}s".format(proc.returncode, elapsed))

    report_path = (
        REPO / "procedural" / "reports" / "slices" / biome / slice_id
        / "update_placement_tags_report.json"
    )
    rc = proc.returncode
    if not report_path.is_file():
        print("[run-ue-update-placement] FAIL: update_slice_placement_tags.py did not write report")
        rc = rc or 1
    else:
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        passed = bool(rep.get("passed"))
        verdict = "PASS" if passed else "FAIL"
        print("[run-ue-update-placement] report verdict: {}".format(verdict))
        if not passed:
            for w in rep.get("warnings", []):
                print("[run-ue-update-placement]   WARN: {}".format(w))
            for e in rep.get("errors", []):
                print("[run-ue-update-placement]   ERROR: {}".format(e))
        rc = rc or (0 if passed else 1)

    raise SystemExit(rc)


if __name__ == "__main__":
    main()
