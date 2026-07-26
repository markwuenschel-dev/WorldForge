#!/usr/bin/env python3
"""v2_6_shield.py — WorldForge v2.6 SceneSurveyForge shield.

FAIL-CLOSED: a gate whose script is missing, or that returns non-zero, turns the
shield RED. Later waves turn unbuilt gates green; the verdict always tracks the real
state — an unbuilt C++/runtime/bridge gate is honestly RED.

Gate lanes (selected by flags):
  (always)          failure-code registry + makefile refs + scene-survey contract
                    spine + the negative-fixture suite
  --scene-survey    the Wave-R hostile suite (fuzz/torture/report-integrity/hygiene)
                    + the runtime survey gates (run_scene_survey_probe smoke + runtime
                    validation) — the latter honestly RED until Waves 3/4 build them
  --regressions     the full v2.5 transition shield (which itself regresses v2.4/2.3/2.2)

Wave 1 state: contract spine + negatives + hostile suite GREEN; the runtime survey
gates are honestly RED until the C++ / boot-harness / live-bridge waves build them.

Acceptance: (canonical command surface — `make` is not installed, run directly)
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_6_shield.py --strict --scene-survey
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
    ap = argparse.ArgumentParser(description="WorldForge v2.6 SceneSurveyForge shield.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--scene-survey", dest="scene_survey", action="store_true")
    ap.add_argument("--regressions", action="store_true")
    for flag in ("--deep", "--jobs", "--cases"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []
    PL = "tools/pipeline"

    print("=" * 72)
    print("WorldForge v2.6 SceneSurveyForge — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) -------------------------------------------
    results.append(run("failure-codes", PL + "/validate_failure_codes.py", *s))
    results.append(run("makefile-refs", PL + "/validate_makefile_refs.py", *s))
    results.append(run("scene-survey-contracts", PL + "/validate_scene_survey_contracts.py", *P, *s))
    results.append(run("scene-survey-negative-fixtures", PL + "/scene_survey_negatives.py", *s))

    # --- Survey lane (--scene-survey) --------------------------------------
    if args.scene_survey:
        # Wave R — hostile suite
        results.append(run("scene-survey-fuzz", PL + "/scene_survey_fuzz.py",
                           "--cases", "300", "--seed", "1337", *s))
        results.append(run("scene-survey-torture", PL + "/scene_survey_torture.py", *s))
        results.append(run("scene-survey-report-integrity", PL + "/scene_survey_report_integrity.py", *s))
        results.append(run("scene-survey-hygiene", PL + "/scene_survey_hygiene.py", *s))
        # Waves 3/4 — runtime survey gates (fail-closed until the C++/boot/bridge
        # waves build them; the verdict honestly reflects the unbuilt state).
        results.append(run("run-scene-survey-smoke", PL + "/run_scene_survey_probe.py", "--smoke", *s))
        results.append(run("validate-scene-survey-runtime", PL + "/validate_scene_survey_runtime.py", *P, *s))

    # --- Regression lane (opt-in — the full v2.5 transition shield) ---------
    if args.regressions:
        results.append(run("regress:v2.5", PL + "/v2_5_shield.py", *P, *s,
                           "--topology", "--conversion", "--plugin", "--capability",
                           "--regression", "--baseline", "--bridge", "--hostile",
                           "--regressions"))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v2.6 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed — awaiting scene-survey Waves 2/3/4): {}".format(failed))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
