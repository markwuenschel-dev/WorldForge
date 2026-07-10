#!/usr/bin/env python3
"""v2_1_shield.py — WorldForge v2.1 OperatorForge shield.

FAIL-CLOSED: a gate whose script is missing, or that returns non-zero, turns the
shield RED. Later waves turn unbuilt gates green; the verdict always tracks the
real state — an unbuilt index/dashboard/command gate is honestly RED, never
fake-green.

Gate lanes (selected by flags):
  (always)     failure-code registry + operator contract spine + negatives
  --operator   the full operator surface: report index + evidence graph (Wave 2),
               static dashboard + evidence/failure/asset/route views + smoke
               (Wave 3), safe command dry-run + diff + command negatives (Wave 4),
               and the hostile suite (negatives/fuzz/torture/report-integrity/
               hygiene, Wave R)
  --regressions  v2.0/v1.9/v1.8/v1.7/v1.6z authoring-shield regressions (opt-in;
               the live-UE regressions run via their own shields with --require-live)

Wave 1 state: contracts + negatives GREEN; the whole --operator surface is honestly
RED until its waves build the scripts. So a spine-only shield (just --strict) is
GREEN and the full shield (--operator) is honestly RED.

Acceptance (canonical command surface — `make` is not installed, run directly):
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_1_shield.py --strict --operator
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def run(label, relpath, *a):
    """Run a repo-relative script; a missing script is fail-closed RED."""
    script_path = REPO_ROOT / relpath
    if not script_path.is_file():
        print("  [FAIL] {}  (gate not yet implemented: {})".format(label, relpath))
        return label, False
    rc = subprocess.run([PY, str(script_path), *[str(x) for x in a]],
                        cwd=str(REPO_ROOT)).returncode
    print("  [{}] {}".format("PASS" if rc == 0 else "FAIL", label))
    return label, rc == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v2.1 OperatorForge shield.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--operator", action="store_true")
    ap.add_argument("--regressions", action="store_true")
    for flag in ("--deep", "--jobs", "--cases"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []
    OP = "tools/operator"

    print("=" * 72)
    print("WorldForge v2.1 OperatorForge — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) -------------------------------------------
    results.append(run("failure-codes", "tools/pipeline/validate_failure_codes.py", *s))
    results.append(run("makefile-refs", "tools/pipeline/validate_makefile_refs.py", *s))
    results.append(run("operator-contracts", OP + "/validate_operator_contracts.py", *P, *s))
    results.append(run("operator-negative-fixtures", OP + "/operator_negatives.py", *s))

    # --- Full operator surface (--operator) --------------------------------
    if args.operator:
        # Wave 2 — report index + evidence graph
        results.append(run("operator-index-reports", OP + "/index_reports.py", *s))
        results.append(run("validate-operator-index", OP + "/validate_operator_index.py", *s))
        # Wave 3 — static dashboard + per-view builders, THEN smoke last (its
        # broken-link check needs every linked view page to exist first).
        results.append(run("operator-dashboard", OP + "/build_dashboard.py", *s))
        results.append(run("operator-evidence-view", OP + "/validate_operator_evidence.py", *s))
        results.append(run("operator-failure-index", OP + "/build_failure_index.py", *s))
        results.append(run("operator-asset-ownership", OP + "/build_asset_ownership.py", *s))
        results.append(run("operator-route-view", OP + "/build_route_view.py", *s))
        results.append(run("operator-smoke", OP + "/operator_smoke.py", *s))
        # Wave 4 — safe command launcher + diff + command negatives
        results.append(run("operator-command-dry-run", OP + "/operator_command.py",
                           "--dry-run", "--command", "operator-index-reports", *s))
        results.append(run("operator-diff-runs", OP + "/diff_operator_runs.py", *s))
        results.append(run("operator-command-negatives", OP + "/operator_command_negatives.py", *s))
        # Wave R — hostile suite
        results.append(run("operator-negative-validators", OP + "/operator_negatives.py", *s))
        results.append(run("operator-fuzz", OP + "/operator_fuzz.py", "--cases", "300",
                           "--seed", "1337", *s))
        results.append(run("operator-torture", OP + "/operator_torture.py", *s))
        results.append(run("operator-report-integrity", OP + "/operator_report_integrity.py", *s))
        results.append(run("operator-hygiene", OP + "/operator_hygiene.py", *s))

    # --- Regression lane (opt-in authoring shields) ------------------------
    if args.regressions:
        results.append(run("regress:v2.0", "tools/pipeline/v2_0_shield.py", *P, *s))
        results.append(run("regress:v1.9", "tools/pipeline/v1_9_shield.py",
                           "--pack", "encounter_loop_world", *s, "--rewards", "--progression"))
        results.append(run("regress:v1.8", "tools/pipeline/v1_8_shield.py",
                           "--pack", "encounter_loop_world", *s, "--combat", "--behavior"))
        results.append(run("regress:v1.7", "tools/pipeline/v1_7_shield.py",
                           "--pack", "encounter_loop_world", *s, "--npc", "--behavior"))
        results.append(run("regress:v1.6z", "tools/pipeline/v1_6z_shield.py",
                           "--pack", "encounter_loop_world", *s))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v2.1 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed — awaiting operator Waves 2/3/4/R): {}".format(failed))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
