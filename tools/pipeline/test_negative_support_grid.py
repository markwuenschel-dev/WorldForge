#!/usr/bin/env python3
"""test_negative_support_grid.py — discovery shim for the support-grid harness.

``test_negative_validators.py`` auto-discovers every sibling ``test_negative_*.py``
and requires each to exit 0 (see its ``discover_sub_harnesses`` /
``run_sub_harness``). This shim exists purely so the v2.6 support-grid conformance
harness is covered by that gate; all the real work — and the JSON report — lives
in ``support_grid_conformance.py``.

Sub-harnesses are invoked with NO arguments, so strictness is taken from the
``STRICT`` environment variable the master harness already sets.

Run directly:
    PYTHONUTF8=1 python tools/pipeline/test_negative_support_grid.py
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "tools" / "pipeline" / "support_grid_conformance.py"


def main():
    if not HARNESS.is_file():
        sys.stderr.write("ERROR: missing {}\n".format(HARNESS))
        return 2
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    cmd = [sys.executable, str(HARNESS)]
    if env.get("STRICT", "") in ("1", "true", "yes", "on"):
        cmd.append("--strict")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
    if proc.returncode == 0:
        print("NEGATIVE OK: support-grid conformance green "
              "(see procedural/reports/scene_survey/support_grid_conformance_report.json)")
    else:
        print("NEGATIVE FAILED: support-grid conformance RED (rc={})".format(
            proc.returncode))
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
