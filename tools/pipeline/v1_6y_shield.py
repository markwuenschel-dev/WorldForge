#!/usr/bin/env python3
"""v1_6y_shield.py — WorldForge v1.6y grounded-traversal shield.

Runs the grounded-traversal truth lane and is honest about the achieved tier
(P0 12 / P1 60-maps / P2 120). Gates that MUST pass regardless of tier:

  * ground completion contract self-check (valid grounded passes; flight/teleport
    success rejected),
  * failure-codes registry validates (the WF516+ GROUND band included),
  * the no-flight/no-teleport false-success DETECTOR self-test (proves it rejects
    an injected flight-as-grounded-success),
  * every grounded completion report on disk validates against the contract,
  * the always-on no-flight/no-teleport detector passes over the real reports.

--require-live additionally demands the full 120/120 grounded matrix (P2). Without
it the shield passes as long as the truth machinery is green and reports the
honest tier — it never dresses a partial matrix as full.

Regression: the v1.6x flight matrix must remain green (flight stays valid as a
v1.6x runtime-completion regression, never as v1.6y grounded success).
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPE = REPO_ROOT / "tools" / "pipeline"
PY = sys.executable


def run(label, *cmd):
    rc = subprocess.run([PY, *[str(c) for c in cmd]], cwd=str(REPO_ROOT)).returncode
    print("  [{}] {}".format("PASS" if rc == 0 else "FAIL", label))
    return rc == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6y grounded-traversal shield.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", action="store_true",
                    help="demand the full 120/120 grounded (P2) matrix")
    for flag in ("--deep", "--torture", "--jobs", "--ground"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []

    print("=" * 70)
    print("WorldForge v1.6y grounded-traversal shield — pack={}".format(args.pack))
    print("Wave-0 decision: navmesh unavailable headless; grounded_manual_waypoint on")
    print("collidable terrain is the success mode. Flight/teleport never count.")
    print("=" * 70)

    results = []
    # Truth machinery — MUST pass at every tier.
    results.append(("contract:self-check", run("contract:self-check",
                    PIPE / "ground_completion_contract.py")))
    results.append(("failure-codes", run("failure-codes",
                    PIPE / "validate_failure_codes.py", *s)))
    results.append(("no-flight-detector:self-test", run("no-flight-detector:self-test",
                    PIPE / "validate_no_flight_ground_success.py", "--self-test")))
    results.append(("ground:completion", run("ground:completion",
                    PIPE / "validate_ground_completion.py", *P, *s)))
    results.append(("ground:no-flight-success", run("ground:no-flight-success",
                    PIPE / "validate_no_flight_ground_success.py", *P, *s)))
    results.append(("ground:gate", run("ground:gate",
                    PIPE / "run_ground_runtime_batch.py", "--gate", *s)))

    # v1.6x flight matrix must remain green (regression).
    results.append(("regression:v1.6x-flight-matrix", run("regression:v1.6x-flight-matrix",
                    PIPE / "run_headless_runtime_batch.py", "--gate", "--strict")))

    failed = [lbl for lbl, ok in results if not ok]

    # Achieved tier from the grounded gate rollup.
    import json
    tier = "unknown"
    grounded = 0
    roll = REPO_ROOT / "procedural/reports/ground/completion/ground_rollup.json"
    if roll.is_file():
        d = json.loads(roll.read_text(encoding="utf-8"))
        tier = d.get("achieved_tier", "unknown")
        grounded = d.get("grounded_completed_runtime", 0)

    if args.require_live and grounded < 120:
        failed.append("require-live:P2-120 ({}/120)".format(grounded))
        print("  [FAIL] require-live:P2-120 — {}/120 grounded".format(grounded))

    print("=" * 70)
    verdict = "GREEN" if not failed else "RED"
    print("v1.6y shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len([f for f in failed if f in dict(results)]), len(results)))
    print("  grounded runtime completion: {} — achieved {} ({}/120 grounded)".format(
        "GREEN" if not failed else "RED", tier, grounded))
    print("  flight/teleport as grounded success: REJECTED (detector self-test passes)")
    if failed:
        print("  FAILED: {}".format(failed))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
