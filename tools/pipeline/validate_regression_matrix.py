#!/usr/bin/env python3
"""validate_regression_matrix.py — WorldForge v1.0x regression gate (Agent 7).

Re-validates the known-good regression packs and asserts they STILL pass, so a
v1.0x hardening change can never silently regress a previously-green pack. The
MVP report cites ``desert_poi_lite_seed`` at 6/6 and ``desert_production_seed`` at
30/30; this gate re-runs the canonical pack validator on each and asserts:

  * the pack enumerates its full declared map set (no coverage shortfall), and
  * ``validate_world_pack.py`` returns green.

Any regression is tagged ``FailureCode.REGRESSION_FAILURE``.

Report: ``validate_regression_matrix_report.json`` (written under each pack's
report dir; the parent gate is keyed on the matrix).

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_regression_matrix.py --strict
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta  # noqa: E402
from world_pack_maps import enumerate_maps, report_dir_for  # noqa: E402

PY = sys.executable
REG = FailureCode.REGRESSION_FAILURE

# Known-good regression packs and their expected declared map counts.
REGRESSION_PACKS = (
    ("desert_poi_lite_seed", 6),
    ("desert_production_seed", 30),
)


def _run(script, extra):
    path = PIPELINE / script
    if not path.is_file():
        return None, "validator missing: {}".format(script)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run([PY, str(path)] + extra, cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-1:])[:200]
    return proc.returncode, tail


def validate_matrix(strict):
    rep = ValidationReport("regression_matrix", "regression_matrix", strict=strict)
    for pack, expected in REGRESSION_PACKS:
        yaml_arg = "procedural/world_packs/{}.yaml".format(pack)

        # coverage: pack still enumerates its full declared map set.
        try:
            _wid, maps = enumerate_maps(pack)
            present = sum(1 for m in maps if m.spec_exists)
            total = len(maps)
            rep.check("{}::coverage".format(pack),
                      total == expected and present == total and total > 0,
                      "{} maps present/{} declared (expected {})".format(present, total, expected),
                      code=REG)
        except Exception as exc:  # noqa: BLE001
            rep.check("{}::coverage".format(pack), False,
                      "enumeration raised: {}".format(exc), code=REG)

        # canonical pack validator must still be green.
        rc, tail = _run("validate_world_pack.py",
                        ["--pack", yaml_arg] + (["--strict"] if strict else []))
        rep.check("{}::validate_world_pack".format(pack), rc == 0,
                  "validate-world-pack rc={} ({})".format(rc, tail), code=REG)

    rep.set_meta(build_meta(command="validate-regression-matrix", pack="regression_matrix",
                            strict=strict, status=None, record_count=len(REGRESSION_PACKS),
                            extra={"packs": [p for p, _ in REGRESSION_PACKS]}))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Re-validate known-good regression packs.")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_matrix(strict)
    rep.finalize()
    # Write under the mvp world-pack report dir root (matrix is cross-pack).
    out = REPO_ROOT / "procedural" / "reports" / "world_packs"
    out.mkdir(parents=True, exist_ok=True)
    rep.write(out, "validate_regression_matrix_report.json")
    rep.print_summary("validate-regression-matrix")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
