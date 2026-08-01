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

# The operation the runtime gate grades. This is passed EXPLICITLY and never
# discovered: validate_scene_survey_runtime.py refuses to scan the operations
# directory and pick the newest, because "newest on disk" would let an unrelated
# run satisfy this gate. --pack cannot supply it — that flag is a report label,
# not a document reference, and no pack schema in this repository declares a
# bound operation.
#
# Omitting the argument does not produce the intentional caller RED; it produces
# a WIRING DEFECT rail (WF1128) saying the caller never said what to grade. Those
# are different failures and the gate now distinguishes them, so this argument is
# what keeps a missing flag from masquerading as absent caller evidence.
#
# The spelling must be exact: the validator uses parse_known_args, so a typo
# (--operation_id) is silently swallowed and falls through to the wiring rail.
RUNTIME_OPERATION_ID = "op_v2_6_scene_survey_0001"


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
    # Wave 2A — the exported caller-facing contract artifacts must still match a
    # fresh export from the Python spine. Rides the always-on lane: a schema that
    # has silently drifted from its validator misleads the caller lane on every
    # request it authors, which is not something you should be able to opt out of.
    results.append(run("scene-survey-contract-export",
                       PL + "/export_scene_survey_contracts.py", "--check"))

    # --- Survey lane (--scene-survey) --------------------------------------
    if args.scene_survey:
        # Wave R — hostile suite
        results.append(run("scene-survey-fuzz", PL + "/scene_survey_fuzz.py",
                           "--cases", "300", "--seed", "1337", *s))
        results.append(run("scene-survey-torture", PL + "/scene_survey_torture.py", *s))
        # Wave 2F — the mission's hostile scenario list as ON-DISK artifacts, each
        # driven through the real validator and required to fail for its OWN rail.
        results.append(run("scene-survey-known-bads", PL + "/run_v2_6_known_bads.py", *P, *s))
        # Hostile tests for the report ASSEMBLER, which no artifact-level gate reaches.
        # The known-bads drivers all take a finished document, so they stay green even
        # when the assembler sources a "binding" field from the request — the exact
        # vacuity that made three sb:: rails unfailable. These drive _build_report
        # directly with a fabricated far-side document.
        results.append(run("scene-survey-assembler-probes",
                           PL + "/run_v2_6_assembler_probes.py", *P, *s))
        results.append(run("scene-survey-report-integrity", PL + "/scene_survey_report_integrity.py", *s))
        results.append(run("scene-survey-hygiene", PL + "/scene_survey_hygiene.py", *s))
        # Waves 3/4 — runtime survey gates (fail-closed until the C++/boot/bridge
        # waves build them; the verdict honestly reflects the unbuilt state).
        results.append(run("run-scene-survey-smoke", PL + "/run_scene_survey_probe.py", "--smoke", *s))
        results.append(run("validate-scene-survey-runtime", PL + "/validate_scene_survey_runtime.py",
                           *P, *s, "--operation-id", RUNTIME_OPERATION_ID))

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
