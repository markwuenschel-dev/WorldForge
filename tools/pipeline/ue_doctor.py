#!/usr/bin/env python3
"""ue_doctor.py — WorldForge UE execution environment pre-flight check.

Usage:
    python tools/pipeline/ue_doctor.py          # full check including UE boot
    python tools/pipeline/ue_doctor.py --quick  # skip UE boot

Exit 0 if no FAILs (WARNs allowed). Exit 1 if any check FAILs.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_EDITOR_WSL = "/mnt/c/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-cmd.exe"
DEFAULT_EDITOR_WIN = r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"

BOOT_SCRIPT_REL = "procedural/reports/ue_doctor/boot_test.py"
BOOT_REPORT_REL = "procedural/reports/ue_doctor/boot_test_report.json"

BOOT_SCRIPT_CONTENT = """\
import json, os, unreal
root = os.path.normpath(unreal.Paths.project_dir())
out = os.path.join(root, "procedural", "reports", "ue_doctor", "boot_test_report.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    json.dump({"boot": True, "python_ok": True}, f)
unreal.log("[ue-doctor] boot ok")
"""


def _is_wsl():
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


_IN_WSL = _is_wsl()


def _to_win(path):
    if _IN_WSL:
        win = subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
        return win.replace("\\", "/")
    return str(path).replace("\\", "/")


def _default_editor():
    return DEFAULT_EDITOR_WSL if _IN_WSL else DEFAULT_EDITOR_WIN


class Result:
    def __init__(self):
        self.ok = 0
        self.warn = 0
        self.fail = 0
        self.lines = []

    def add(self, level, msg):
        tag = {"OK": "[OK  ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[level]
        self.lines.append(f"  {tag} {msg}")
        if level == "OK":
            self.ok += 1
        elif level == "WARN":
            self.warn += 1
        else:
            self.fail += 1

    def passed(self):
        return self.fail == 0


def check_editor(result):
    editor = os.environ.get("UE_EDITOR_CMD", _default_editor())
    if os.path.isfile(editor):
        result.add("OK", f"UE executable found: {editor}")
    else:
        result.add("FAIL", f"UE executable not found: {editor}  (set UE_EDITOR_CMD to override)")
    return editor


def check_uproject(result):
    uproject = REPO_ROOT / "WorldForge.uproject"
    if uproject.is_file():
        result.add("OK", f"uproject found: {uproject}")
    else:
        result.add("FAIL", f"uproject not found: {uproject}")


def check_utf8(result):
    enc = getattr(sys.stdout, "encoding", "") or ""
    pythonutf8 = os.environ.get("PYTHONUTF8", "0")
    if enc.lower().replace("-", "") == "utf8" or pythonutf8 == "1":
        result.add("OK", "Python UTF-8 forced (PYTHONUTF8=1 or utf-8 stdout)")
    else:
        result.add("WARN", f"PYTHONUTF8 not set (stdout encoding={enc!r}) — emoji output may crash on Windows")


def check_registry(result):
    reg_path = REPO_ROOT / "procedural" / "generated" / "worldforge_registry.json"
    if not reg_path.is_file():
        result.add("WARN", "registry missing — no slices tracked yet")
        return
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        n = len(reg)
        if n == 0:
            result.add("WARN", "registry empty — 0 slices tracked")
        else:
            result.add("OK", f"registry loaded — {n} slices tracked")
    except Exception as exc:
        result.add("WARN", f"registry exists but could not parse: {exc}")


def check_templates(result):
    templates = list((REPO_ROOT / "procedural" / "slices").glob("desert_*.yaml"))
    n = len(templates)
    if n == 0:
        result.add("FAIL", "no slice templates found under procedural/slices/desert_*.yaml")
    else:
        result.add("OK", f"{n} slice templates found")


def check_ue_boot(result, editor):
    boot_script = REPO_ROOT / BOOT_SCRIPT_REL
    boot_report = REPO_ROOT / BOOT_REPORT_REL
    uproject = REPO_ROOT / "WorldForge.uproject"

    boot_script.parent.mkdir(parents=True, exist_ok=True)
    boot_script.write_text(BOOT_SCRIPT_CONTENT, encoding="utf-8")

    # Remove stale report so we can detect failure to write.
    if boot_report.is_file():
        boot_report.unlink()

    if not os.path.isfile(editor):
        result.add("FAIL", "UE boot test skipped — editor not found")
        return

    cmd = [
        editor,
        _to_win(uproject),
        "-ExecutePythonScript={}".format(_to_win(boot_script)),
        "-unattended", "-nopause", "-nosplash", "-nosound", "-stdout",
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    started = time.time()
    proc = subprocess.run(cmd, env=env)
    elapsed = time.time() - started

    if boot_report.is_file():
        try:
            rep = json.loads(boot_report.read_text(encoding="utf-8"))
            if rep.get("boot"):
                result.add("OK", f"UE boot test passed ({elapsed:.0f}s)")
                return
        except Exception:
            pass
    result.add("FAIL", f"UE boot test failed — report not written or boot==false (rc={proc.returncode}, {elapsed:.0f}s)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge UE execution environment pre-flight check.")
    ap.add_argument("--quick", action="store_true", help="skip UE boot test, only check paths")
    args = ap.parse_args(argv)

    print("UE DOCTOR — WorldForge execution environment check")
    result = Result()

    editor = check_editor(result)
    check_uproject(result)
    check_utf8(result)
    check_registry(result)
    check_templates(result)

    if not args.quick:
        check_ue_boot(result, editor)
    else:
        print("  [----] UE boot test skipped (--quick)")

    for line in result.lines:
        print(line)

    verdict = "PASS" if result.passed() else "FAIL"
    print(f"RESULT: {verdict} ({result.ok} OK, {result.warn} WARN, {result.fail} FAIL)")
    sys.exit(0 if result.passed() else 1)


if __name__ == "__main__":
    main()
