#!/usr/bin/env python3
"""validate_transition_integrity.py — v2.5 hostile/integrity umbrella (Lane 7).

Runs the six hostile/integrity sub-gates as subprocesses and rolls their verdicts into a
single integrity report. Mirrors the shield's run() helper: a missing sub-gate script is a
hard FAIL ("gate not yet implemented"), never a silent skip; a sub-gate exiting non-zero is a
FAIL. GREEN only when every sub-gate passes.

Sub-gates:
  transition-negatives        transition_negatives.py
  transition-fuzz             transition_fuzz.py
  transition-report-integrity transition_report_integrity.py  procedural/reports/ue5_8
  transition-hygiene          transition_hygiene.py
  transition-known-bads       run_transition_known_bads.py
  transition-torture          run_transition_torture.py

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_transition_integrity.py --strict
Reports -> procedural/reports/ue5_8/hostile/validate_transition_integrity_report.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

PL = "tools/pipeline"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "hostile"
PY = sys.executable


def run(label, relpath, *args):
    script = REPO_ROOT / relpath
    if not script.exists():
        return (label, False, "gate not yet implemented: {}".format(relpath))
    rc = subprocess.run([PY, str(script), *[str(a) for a in args]],
                        cwd=str(REPO_ROOT)).returncode
    return (label, rc == 0, "exit {}".format(rc))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 hostile/integrity umbrella.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    s = ["--strict"] if strict else []

    gates = [
        run("transition-negatives", PL + "/transition_negatives.py", *s),
        run("transition-fuzz", PL + "/transition_fuzz.py", *s),
        run("transition-report-integrity", PL + "/transition_report_integrity.py",
            "procedural/reports/ue5_8", *s),
        run("transition-hygiene", PL + "/transition_hygiene.py", *s),
        run("transition-known-bads", PL + "/run_transition_known_bads.py", *s),
        run("transition-torture", PL + "/run_transition_torture.py", *s),
    ]

    rep = ValidationReport("suite", "transition_integrity", strict=strict)
    for label, ok, detail in gates:
        rep.check("integrity::" + label, ok, detail)
    rep.finalize()
    rep.set_meta(build_meta(
        command="transition-integrity", pack=None, strict=strict, status=rep.status,
        record_count=len(gates), records_total=len(gates),
        report_type="wf.transition.integrity_umbrella.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_transition_integrity_report.json")
    rep.print_summary("transition-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
