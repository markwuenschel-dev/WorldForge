#!/usr/bin/env python3
"""v2_3_shield.py — WorldForge v2.3 StreamingForge / WorldScaleForge shield.

FAIL-CLOSED: a gate whose script is missing, or that returns non-zero, turns the
shield RED. Later waves turn unbuilt gates green; the verdict always tracks the real
state — an unbuilt authoring/runtime/operator/hostile gate is honestly RED.

Gate lanes (selected by flags):
  (always)        failure-code registry + makefile refs + streaming contract spine
                  + the negative-fixture suite
  --streaming     region/anchor/route/binding authoring generators + validation
  --streaming+--worldscale together additionally run the full downstream surface:
                  streaming smoke + 24-scenario runtime + lifecycle/save-load/budget
                  validation (Wave 3/4), operator region/tile index + dashboard +
                  smoke (Wave 5), and the hostile suite (negatives/fuzz/torture/
                  report-integrity/hygiene, Wave R)
  --regressions   v2.2/v2.1/v2.0 authoring-shield regressions (opt-in)

Wave 1 state: contract spine + negatives GREEN; the whole downstream surface is
honestly RED until its waves build the scripts.

Acceptance: (canonical command surface — `make` is not installed, run directly)
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_3_shield.py --strict --streaming --worldscale
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def run(label, relpath, *a):
    script_path = REPO_ROOT / relpath
    if not script_path.is_file():
        print("  [FAIL] {}  (gate not yet implemented: {})".format(label, relpath))
        return label, False
    rc = subprocess.run([PY, str(script_path), *[str(x) for x in a]],
                        cwd=str(REPO_ROOT)).returncode
    print("  [{}] {}".format("PASS" if rc == 0 else "FAIL", label))
    return label, rc == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v2.3 StreamingForge shield.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--streaming", action="store_true")
    ap.add_argument("--worldscale", action="store_true")
    ap.add_argument("--regressions", action="store_true")
    ap.add_argument("--scenarios", nargs="?", default="24")
    for flag in ("--deep", "--jobs", "--cases"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []
    PL = "tools/pipeline"
    OP = "tools/operator"
    full = args.streaming and args.worldscale

    print("=" * 72)
    print("WorldForge v2.3 StreamingForge / WorldScaleForge — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) -------------------------------------------
    results.append(run("failure-codes", PL + "/validate_failure_codes.py", *s))
    results.append(run("makefile-refs", PL + "/validate_makefile_refs.py", *s))
    results.append(run("streaming-contracts", PL + "/validate_streaming_contracts.py", *P, *s))
    results.append(run("streaming-negative-fixtures", PL + "/streaming_negatives.py", *s))

    # --- Authoring (--streaming) -------------------------------------------
    if args.streaming:
        results.append(run("generate-streaming-regions", PL + "/generate_streaming_regions.py", *P, *s))
        results.append(run("generate-cross-tile-anchors", PL + "/generate_cross_tile_anchors.py", *P, *s))
        results.append(run("generate-cross-tile-routes", PL + "/generate_cross_tile_routes.py", *P, *s))
        results.append(run("generate-streamed-bindings", PL + "/generate_streamed_bindings.py", *P, *s))
        results.append(run("validate-streaming-authoring", PL + "/validate_streaming_authoring.py", *P, *s))

    # --- Full downstream surface (--streaming AND --worldscale) ------------
    if full:
        # Wave 3 — streaming runtime + lifecycle
        results.append(run("run-streaming-smoke", PL + "/run_streaming_forge_alpha.py", "--smoke", *s))
        results.append(run("run-streaming-runtime", PL + "/run_streaming_forge_alpha.py",
                           "--gate", "--scenarios", args.scenarios, *s))
        results.append(run("validate-streaming-runtime", PL + "/validate_streaming_runtime.py", *P, *s))
        # Wave 4 — cross-tile save/load + budgets
        results.append(run("validate-streaming-save-load", PL + "/validate_streaming_save_load.py", *P, *s))
        results.append(run("validate-streaming-budgets", PL + "/validate_streaming_budgets.py", *P, *s))
        # Wave 5 — OperatorForge region/tile views
        results.append(run("operator-streaming-index", OP + "/build_streaming_index.py", *s))
        results.append(run("operator-streaming-dashboard", OP + "/build_streaming_dashboard.py", *s))
        results.append(run("operator-streaming-smoke", OP + "/streaming_operator_smoke.py", *s))
        # Wave R — hostile suite
        results.append(run("streaming-negative-validators", PL + "/streaming_negative_validators.py", *s))
        results.append(run("streaming-fuzz", PL + "/streaming_fuzz.py", "--cases", "300",
                           "--seed", "1337", *s))
        results.append(run("streaming-torture", PL + "/streaming_torture.py", *s))
        results.append(run("streaming-report-integrity", PL + "/streaming_report_integrity.py", *s))
        results.append(run("streaming-hygiene", PL + "/streaming_hygiene.py", *s))

    # --- Regression lane (opt-in authoring shields) ------------------------
    if args.regressions:
        results.append(run("regress:v2.2", PL + "/v2_2_shield.py", *P, *s, "--quests", "--factions"))
        results.append(run("regress:v2.1", PL + "/v2_1_shield.py", *P, *s, "--operator"))
        results.append(run("regress:v2.0", PL + "/v2_0_shield.py", *P, *s, "--package"))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v2.3 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed — awaiting streaming Waves 2/3/4/5/R): {}".format(failed))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
