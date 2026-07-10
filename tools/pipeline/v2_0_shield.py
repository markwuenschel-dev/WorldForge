#!/usr/bin/env python3
"""v2_0_shield.py — WorldForge v2.0 VerticalSliceForge shield.

FAIL-CLOSED: a gate whose script is missing, or that returns non-zero, turns the
shield RED. Later waves turn unbuilt gates green; the verdict always tracks the
real state — an unbuilt runtime/package gate is honestly RED, never fake-green.

Gate lanes (selected by flags):
  (always)        failure-code registry + vertical-slice contract spine
  --slices        slice scenario generation + authoring/environment/asset validators
  --require-live  UE-realized 24-scenario runtime slice matrix + per-system evidence
                  + evidence index (traversal/NPC/combat/reward/save-load)
  --package       build/package artifact proof + package integrity
  --torture       slice negatives + fuzz-300 + torture + report integrity + hygiene
  --regressions   v1.9/v1.8/v1.7/v1.6z authoring-shield regressions (opt-in; the
                  live-UE regressions run via their own shields with --require-live)

Wave 1 state: contracts + negatives GREEN; runtime/package/authoring/integrity
gates RED until their waves build them. So a contracts-only shield is GREEN and
the full shield (--slices --require-live --package --torture) is honestly RED.

Acceptance (canonical command surface — `make` is not installed, run directly):
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_0_shield.py \
        --pack encounter_loop_world --strict --slices --require-live --package --torture
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPE = REPO_ROOT / "tools" / "pipeline"
PY = sys.executable


def run(label, script, *a):
    script_path = PIPE / script
    if not script_path.is_file():
        # Fail-closed: a gate we have not built yet is RED, never silently green.
        print("  [FAIL] {}  (gate not yet implemented: {})".format(label, script))
        return label, False
    rc = subprocess.run([PY, str(script_path), *[str(x) for x in a]],
                        cwd=str(REPO_ROOT)).returncode
    print("  [{}] {}".format("PASS" if rc == 0 else "FAIL", label))
    return label, rc == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v2.0 Vertical Slice shield.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--slices", action="store_true")
    ap.add_argument("--require-live", action="store_true")
    ap.add_argument("--package", action="store_true")
    ap.add_argument("--torture", action="store_true")
    ap.add_argument("--regressions", action="store_true")
    ap.add_argument("--scenarios", default="24")
    for flag in ("--deep", "--jobs"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []

    print("=" * 72)
    print("WorldForge v2.0 VerticalSliceForge — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) -------------------------------------------
    results.append(run("failure-codes", "validate_failure_codes.py", *s))
    results.append(run("slice-contracts", "validate_vertical_slice_contracts.py", *P, *s))

    # --- Slice authoring lane ----------------------------------------------
    if args.slices:
        results.append(run("slice:generate", "generate_slice_scenarios.py", *P, *s))
        results.append(run("slice:validate-scenarios", "validate_slice_scenarios.py", *P, *s))
        results.append(run("slice:environment", "validate_slice_environment.py", *P, *s))
        results.append(run("slice:assets", "validate_slice_assets.py", *P, *s))

    # --- Runtime slice matrix (--require-live) -----------------------------
    if args.require_live:
        results.append(run("slice:runtime-matrix", "run_slice_forge_alpha.py",
                           "--gate", "--pack", args.pack, "--scenarios", args.scenarios, *s))
        results.append(run("slice:traversal", "validate_slice_traversal.py", *P, *s))
        results.append(run("slice:npc-combat", "validate_slice_npc_combat.py", *P, *s))
        results.append(run("slice:rewards", "validate_slice_rewards.py", *P, *s))
        results.append(run("slice:save-load", "validate_slice_save_load.py", *P, *s))
        results.append(run("slice:evidence-index", "validate_slice_evidence_index.py", *P, *s))

    # --- Package proof (--package) -----------------------------------------
    if args.package:
        results.append(run("slice:package", "validate_slice_package.py", *P, *s))

    # --- Hostile validation suite (--torture) ------------------------------
    if args.torture:
        results.append(run("negatives", "slice_negatives.py", *s))
        results.append(run("fuzz-300", "slice_fuzz.py", "--cases", "300", "--seed", "1337", *s))
        results.append(run("torture", "slice_torture.py", *P, *s))
        results.append(run("report-integrity", "slice_report_integrity.py", *P, *s))
        results.append(run("hygiene", "slice_hygiene.py", *s))

    # --- Regression lane (opt-in authoring shields) ------------------------
    if args.regressions:
        results.append(run("regress:v1.9", "v1_9_shield.py", *P, *s, "--rewards", "--progression"))
        results.append(run("regress:v1.8", "v1_8_shield.py", *P, *s, "--combat", "--behavior"))
        results.append(run("regress:v1.7", "v1_7_shield.py", *P, *s, "--npc", "--behavior"))
        results.append(run("regress:v1.6z", "v1_6z_shield.py", *P, *s))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v2.0 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed — awaiting UE runtime/package evidence, Waves R/P): {}"
              .format(failed))
    print("  NOTE: engine-realized regressions also run via their own shields —")
    print("        v1_9_shield.py / v1_8_shield.py / v1_7_shield.py / v1_6z_shield.py")
    print("        (with --require-live) for the full runtime regression.")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
