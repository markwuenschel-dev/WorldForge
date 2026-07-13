#!/usr/bin/env python3
"""v2_5_shield.py — WorldForge v2.5 UE 5.7→5.8 Transition shield.

FAIL-CLOSED: a gate whose script is missing, or that returns non-zero, turns the shield
RED. Later waves turn unbuilt gates green; the verdict always tracks the real state — an
unbuilt topology/conversion/plugin/capability/regression/baseline/bridge/hostile gate is
honestly RED.

This is the Wave-0 SKELETON. Only the always-on transition contract spine has a real
script (Lane 4). Every flag-gated lane below points at a script a later wave must create;
until then each such gate reports "(gate not yet implemented)" and the shield is RED by
design. Do NOT stub the missing gates green.

Gate lanes:
  (always)         transition contract spine   → validate_transition_contracts.py --strict
  --topology       transition topology         → validate_transition_topology.py
  --conversion     conversion manifest         → validate_conversion_manifest.py
  --plugin         plugin build                → validate_plugin_build.py
  --capability     capability manifest         → validate_capability_manifest.py
  --regression     transition regression       → transition_regression.py --strict
  --baseline       transition baseline         → validate_transition_baseline.py --strict
  --bridge         Gloamstead bridge           → validate_gloam_bridge.py --strict
  --hostile        hostile suite               → transition_negatives.py
                                               + transition_fuzz.py --strict
                                               + transition_report_integrity.py
                                                   procedural/reports/ue5_8 --strict
                                               + transition_hygiene.py
  --regressions    prior authoring shields (opt-in): v2.4/v2.3/v2.2

Honors a global --strict, threaded to gate scripts that accept it, exactly as
v2_4_shield.py threads its flags. Uses argparse with parse_known_args.

Acceptance: (canonical command surface — `make` is not installed, run directly)
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_5_shield.py --strict \
        --topology --conversion --plugin --capability --regression --baseline --bridge --hostile
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
    ap = argparse.ArgumentParser(description="WorldForge v2.5 UE 5.7->5.8 Transition shield.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--topology", action="store_true")
    ap.add_argument("--conversion", action="store_true")
    ap.add_argument("--plugin", action="store_true")
    ap.add_argument("--capability", action="store_true")
    ap.add_argument("--regression", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--bridge", action="store_true")
    ap.add_argument("--hostile", action="store_true")
    ap.add_argument("--regressions", action="store_true")
    for flag in ("--deep", "--jobs", "--cases"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []
    PL = "tools/pipeline"

    print("=" * 72)
    print("WorldForge v2.5 UE 5.7->5.8 Transition — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Transition contract spine (always) --------------------------------
    results.append(run("transition-contracts", PL + "/validate_transition_contracts.py", "--strict"))

    # --- Topology (--topology) ---------------------------------------------
    if args.topology:
        results.append(run("transition-topology", PL + "/validate_transition_topology.py", *s))

    # --- Conversion manifest (--conversion) --------------------------------
    if args.conversion:
        results.append(run("conversion-manifest", PL + "/validate_conversion_manifest.py", *s))

    # --- Plugin build (--plugin) -------------------------------------------
    if args.plugin:
        results.append(run("plugin-build", PL + "/validate_plugin_build.py", *s))

    # --- Capability manifest (--capability) --------------------------------
    if args.capability:
        results.append(run("capability-manifest", PL + "/validate_capability_manifest.py", *s))

    # --- Regression (--regression) -----------------------------------------
    if args.regression:
        results.append(run("transition-regression", PL + "/transition_regression.py", "--strict"))

    # --- Baseline (--baseline) ---------------------------------------------
    if args.baseline:
        results.append(run("transition-baseline", PL + "/validate_transition_baseline.py", "--strict"))

    # --- Gloamstead bridge (--bridge) --------------------------------------
    if args.bridge:
        results.append(run("gloam-bridge", PL + "/validate_gloam_bridge.py", "--strict"))

    # --- Hostile suite (--hostile) -----------------------------------------
    if args.hostile:
        results.append(run("transition-negatives", PL + "/transition_negatives.py", *s))
        results.append(run("transition-fuzz", PL + "/transition_fuzz.py", "--strict"))
        results.append(run("transition-report-integrity", PL + "/transition_report_integrity.py",
                           "procedural/reports/ue5_8", "--strict"))
        results.append(run("transition-hygiene", PL + "/transition_hygiene.py", *s))

    # --- Regression lane (opt-in prior authoring shields) ------------------
    if args.regressions:
        results.append(run("regress:v2.4", PL + "/v2_4_shield.py", *P, *s, "--tactical"))
        results.append(run("regress:v2.3", PL + "/v2_3_shield.py", *P, *s, "--streaming", "--worldscale"))
        results.append(run("regress:v2.2", PL + "/v2_2_shield.py", *P, *s, "--quests", "--factions"))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v2.5 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed — awaiting v2.5 transition waves): {}".format(failed))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
