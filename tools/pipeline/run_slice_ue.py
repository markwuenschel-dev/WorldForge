#!/usr/bin/env python3
r"""
run_slice_ue.py -- launch a headless UE Python script against a slice spec.

    python tools/pipeline/run_slice_ue.py --script create_slice_map.py --spec <spec.json>
    python tools/pipeline/run_slice_ue.py --script validate_slice.py   --spec <spec.json>

The UE `-ExecutePythonScript` path can't reliably carry an argument path that
contains spaces (this repo lives under "D:/Unreal Projects/..."), so instead of
passing --spec to the in-editor script we stage the chosen spec to a fixed pointer
file the UE scripts read by default:

    procedural/reports/slices/_active_slice_spec.json

Runs in plain WSL Python (PyYAML-free; only the launch matters here) and boots the
Windows editor via WSL interop, mirroring tools/pipeline/biome_slice.py.

Env overrides:
    UE_EDITOR_CMD   path to UnrealEditor-cmd.exe (WSL /mnt/... form)
    WF_UPROJECT     path to the .uproject (WSL form; default repo/WorldForge.uproject)
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
UE_DIR = REPO / "tools" / "unreal"
DEFAULT_EDITOR = "/mnt/c/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-cmd.exe"


def _to_win(path):
    win = subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
    return win.replace("\\", "/")


def main():
    ap = argparse.ArgumentParser(description="Boot headless UE to run a slice script against a spec.")
    ap.add_argument("--script", required=True, help="Script filename under tools/unreal/ (e.g. create_slice_map.py).")
    ap.add_argument("--spec", required=True, help="Path to the generated slice spec JSON.")
    ap.add_argument("--editor", default=os.environ.get("UE_EDITOR_CMD", DEFAULT_EDITOR))
    ap.add_argument("--uproject", default=os.environ.get("WF_UPROJECT", str(REPO / "WorldForge.uproject")))
    args = ap.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = REPO / spec_path
    if not spec_path.is_file():
        raise SystemExit("[run-slice-ue] spec not found: {}".format(spec_path))
    # Validate it parses and stage it to the fixed pointer the UE scripts read.
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    ACTIVE_SPEC.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(spec_path), str(ACTIVE_SPEC))
    print("[run-slice-ue] staged spec '{}' -> {}".format(spec.get("slice_id"), ACTIVE_SPEC))

    script_path = UE_DIR / args.script
    if not script_path.is_file():
        raise SystemExit("[run-slice-ue] script not found: {}".format(script_path))
    if not os.path.isfile(args.editor):
        raise SystemExit("[run-slice-ue] editor not found: {} (set UE_EDITOR_CMD)".format(args.editor))

    cmd = [
        args.editor,
        _to_win(Path(args.uproject)),
        "-ExecutePythonScript={}".format(_to_win(script_path)),
        "-unattended", "-nopause", "-nosplash", "-nosound", "-stdout",
    ]
    print("[run-slice-ue] launching headless UE: {}".format(args.script))
    started = time.time()
    proc = subprocess.run(cmd)
    print("[run-slice-ue] editor exited rc={} after {:.0f}s".format(proc.returncode, time.time() - started))

    # The editor process exits 0 even when the in-editor script's logic fails, so
    # score the report it wrote and propagate a real pass/fail to make.
    rc = proc.returncode
    out_dir = REPO / spec.get("output_dir", "procedural/reports/slices/_unsorted/" + str(spec.get("slice_id")))
    report_name, ok_key = {
        "create_slice_map.py": ("create_map_report.json", "status"),
        "validate_slice.py": ("validate_slice_report.json", "passed"),
    }.get(args.script, (None, None))
    if report_name:
        rpath = out_dir / report_name
        if not rpath.is_file():
            print("[run-slice-ue] FAIL: {} did not write {}".format(args.script, rpath))
            rc = rc or 1
        else:
            rep = json.loads(rpath.read_text(encoding="utf-8"))
            passed = (rep.get("status") == "ok") if ok_key == "status" else bool(rep.get("passed"))
            verdict = "PASS" if passed else "FAIL"
            print("[run-slice-ue] {} report verdict: {}".format(args.script, verdict))
            if not passed:
                for f in rep.get("failures", []) or rep.get("errors", []):
                    print("[run-slice-ue]   - {}".format(f))
                rc = rc or 1
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
