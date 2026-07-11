#!/usr/bin/env python3
"""v2_4_shield.py — WorldForge v2.4 AdvancedAIForge / TacticalBehaviorForge shield.

FAIL-CLOSED: a gate whose script is missing, or that returns non-zero, turns the shield
RED. Later waves turn unbuilt gates green; the verdict always tracks the real state — an
unbuilt authoring/runtime/operator/hostile gate is honestly RED.

Gate lanes (selected by flags):
  (always)          failure-code registry + makefile refs + tactical contract spine
                    + the negative-fixture suite
  --tactical        profile/role/affordance authoring + NPC/group bindings + validation
  --tactical + --advanced-ai together additionally run the full downstream surface:
                    tactical smoke + 24-scenario runtime + decision/state validation
                    (Wave 4), save-load + budget validation (Wave 5), operator scenario/
                    NPC index + dashboard + smoke (Wave 6), and the hostile suite
                    (negatives/fuzz/torture/report-integrity/hygiene, Wave R)
  --regressions     v2.3/v2.2/v2.1/v2.0 authoring-shield regressions (opt-in)

Wave 1 state: contract spine + negatives GREEN; the whole downstream surface is honestly
RED until its waves build the scripts.

Acceptance: (canonical command surface — `make` is not installed, run directly)
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_4_shield.py --strict --tactical --advanced-ai
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
    ap = argparse.ArgumentParser(description="WorldForge v2.4 TacticalBehaviorForge shield.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--tactical", action="store_true")
    ap.add_argument("--advanced-ai", dest="advanced_ai", action="store_true")
    ap.add_argument("--regressions", action="store_true")
    ap.add_argument("--scenarios", nargs="?", default="24")
    for flag in ("--deep", "--jobs", "--cases"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []
    PL = "tools/pipeline"
    OP = "tools/operator"
    full = args.tactical and args.advanced_ai

    print("=" * 72)
    print("WorldForge v2.4 AdvancedAIForge / TacticalBehaviorForge — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) -------------------------------------------
    results.append(run("failure-codes", PL + "/validate_failure_codes.py", *s))
    results.append(run("makefile-refs", PL + "/validate_makefile_refs.py", *s))
    results.append(run("tactical-contracts", PL + "/validate_tactical_contracts.py", *P, *s))
    results.append(run("tactical-negative-fixtures", PL + "/tactical_negatives.py", *s))

    # --- Authoring (--tactical) --------------------------------------------
    if args.tactical:
        results.append(run("generate-tactical-profiles", PL + "/generate_tactical_profiles.py", *P, *s))
        results.append(run("validate-tactical-profiles", PL + "/validate_tactical_profiles.py", *P, *s))
        results.append(run("generate-tactical-affordances", PL + "/generate_tactical_affordances.py", *P, *s))
        results.append(run("validate-tactical-affordances", PL + "/validate_tactical_affordances.py", *P, *s))
        results.append(run("generate-tactical-bindings", PL + "/generate_tactical_bindings.py", *P, *s))
        results.append(run("validate-tactical-bindings", PL + "/validate_tactical_bindings.py", *P, *s))

    # --- Full downstream surface (--tactical AND --advanced-ai) ------------
    if full:
        # Wave 4 — tactical runtime + decision proof
        results.append(run("run-tactical-smoke", PL + "/run_tactical_behavior_alpha.py", "--smoke", *s))
        results.append(run("run-tactical-runtime", PL + "/run_tactical_behavior_alpha.py",
                           "--gate", "--scenarios", args.scenarios, *s))
        results.append(run("validate-tactical-runtime", PL + "/validate_tactical_runtime.py", *P, *s))
        # Wave 5 — save/load + budgets
        results.append(run("validate-tactical-save-load", PL + "/validate_tactical_save_load.py", *P, *s))
        results.append(run("validate-tactical-budgets", PL + "/validate_tactical_budgets.py", *P, *s))
        # Wave 6 — OperatorForge tactical views
        results.append(run("operator-tactical-index", OP + "/build_tactical_index.py", *s))
        results.append(run("operator-tactical-dashboard", OP + "/build_tactical_dashboard.py", *s))
        results.append(run("operator-tactical-smoke", OP + "/tactical_operator_smoke.py", *s))
        # Wave R — hostile suite
        results.append(run("tactical-negative-validators", PL + "/tactical_negative_validators.py", *s))
        results.append(run("tactical-fuzz", PL + "/tactical_fuzz.py", "--cases", "300",
                           "--seed", "1337", *s))
        results.append(run("tactical-torture", PL + "/tactical_torture.py", *s))
        results.append(run("tactical-report-integrity", PL + "/tactical_report_integrity.py", *s))
        results.append(run("tactical-hygiene", PL + "/tactical_hygiene.py", *s))

    # --- Regression lane (opt-in authoring shields) ------------------------
    if args.regressions:
        results.append(run("regress:v2.3", PL + "/v2_3_shield.py", *P, *s, "--streaming", "--worldscale"))
        results.append(run("regress:v2.2", PL + "/v2_2_shield.py", *P, *s, "--quests", "--factions"))
        results.append(run("regress:v2.1", PL + "/v2_1_shield.py", *P, *s, "--operator"))
        results.append(run("regress:v2.0", PL + "/v2_0_shield.py", *P, *s, "--package"))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v2.4 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed — awaiting tactical Waves 2/3/4/5/6/R): {}".format(failed))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
