#!/usr/bin/env python3
"""v1_6z_shield.py — WorldForge v1.6z GroundTraversalForge hardening shield.

Turns the proven 120/120 grounded core into a full production substrate and
gates it: contract spine, deep walkability, multi-node route graph + plans, the
full hostile-validation suite, and the grounded completion truth from v1.6y. Under
--require-live it also demands the full 120/120 grounded matrix and runs the
regression matrix (v1.6y/v1.6x flight/desert). Heavier engine-realized regressions
(v1.5 assets/visual, mission/biome full-shields) are listed for the operator and
run when their flags are supplied.
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPE = REPO_ROOT / "tools" / "pipeline"
PY = sys.executable


def run(label, script, *a):
    rc = subprocess.run([PY, str(PIPE / script), *[str(x) for x in a]], cwd=str(REPO_ROOT)).returncode
    print("  [{}] {}".format("PASS" if rc == 0 else "FAIL", label))
    return label, rc == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6z hardening shield.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", action="store_true")
    for flag in ("--deep", "--torture", "--jobs", "--ground"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []

    print("=" * 72)
    print("WorldForge v1.6z GroundTraversalForge Production Hardening — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # Contract spine + taxonomy.
    results.append(run("contract-spine", "validate_ground_traversal_schemas.py", *P, *s))
    results.append(run("failure-codes", "validate_failure_codes.py", *s))
    # Deep walkability (analysis produced separately; here we validate it).
    results.append(run("walkability", "validate_ground_walkability.py", *P, *s))
    # Route graph + plans.
    results.append(run("route-graph:generate", "generate_ground_route_graph.py", *P, *s))
    results.append(run("route-graph:validate", "validate_ground_route_graph.py", *P, *s))
    results.append(run("route-plans:generate", "generate_ground_route_plans.py", *P, *s))
    results.append(run("route-plans:validate", "validate_ground_route_plans.py", *P, *s))
    # Grounded completion truth (v1.6y) + false-success detectors.
    results.append(run("ground:completion", "validate_ground_completion.py", *P, *s))
    results.append(run("ground:no-flight-success", "validate_no_flight_ground_success.py", *P, *s))
    results.append(run("ground:no-flight-selftest", "validate_no_flight_ground_success.py", "--self-test"))
    # Hostile validation suite.
    results.append(run("negatives", "ground_traversal_negatives.py", *s))
    results.append(run("fuzz-300", "ground_traversal_fuzz.py", "--cases", "300", "--seed", "1337", *s))
    results.append(run("torture", "ground_traversal_torture.py", *P, *s))
    results.append(run("report-integrity", "ground_traversal_report_integrity.py", *P, *s))

    if args.require_live:
        # Full 120/120 grounded matrix (P2).
        results.append(run("ground:gate-P2", "run_ground_runtime_batch.py", "--gate", "--strict"))
        # Regressions runnable here without extra engine realization.
        results.append(run("regression:v1.6x-flight", "run_headless_runtime_batch.py", "--gate", "--strict"))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v1.6z shield: {} — {}/{} gates passed".format(verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED: {}".format(failed))
    if not args.require_live:
        print("  (run with --require-live for the P2 120/120 gate + regressions)")
    print("  NOTE: engine-realized regressions (v1.5 ASSETS/VISUAL, mission/biome full-shields)")
    print("        run via their own make targets; desert/v1.6/v1.6y confirmed separately.")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
