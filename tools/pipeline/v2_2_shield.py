#!/usr/bin/env python3
"""v2_2_shield.py — WorldForge v2.2 QuestForge + FactionStateForge shield.

FAIL-CLOSED: a gate whose script is missing, or that returns non-zero, turns the
shield RED. Later waves turn unbuilt gates green; the verdict always tracks the real
state — an unbuilt authoring/runtime/operator/hostile gate is honestly RED, never
fake-green.

Gate lanes (selected by flags):
  (always)        failure-code registry + makefile refs + the quest/faction contract
                  spine (quest / faction / combined dogfood) + the negative suite
  --quests        quest authoring: generate + validate generated quests (Wave 2)
  --factions      faction authoring: generate + validate generated factions (Wave 2)
  --quests+--factions together additionally run the full downstream surface:
                  runtime smoke + 24-scenario runtime + runtime/save-load validation
                  (Wave 3), operator quest/faction index + dashboard + smoke (Wave 4),
                  and the hostile suite (negatives/fuzz/torture/report-integrity/
                  hygiene, Wave R)
  --regressions   v2.1/v2.0 authoring-shield regressions (opt-in; the live-UE
                  regressions run via their own shields with --require-live)

Wave 1 state: contract spine + negatives GREEN; the whole downstream surface is
honestly RED until its waves build the scripts. So a spine-only shield (just
--strict) is GREEN and the full shield (--quests --factions) is honestly RED.

Acceptance: (canonical command surface — `make` is not installed, run directly)
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_2_shield.py --strict --quests --factions
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
    ap = argparse.ArgumentParser(description="WorldForge v2.2 QuestForge/FactionStateForge shield.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--quests", action="store_true")
    ap.add_argument("--factions", action="store_true")
    ap.add_argument("--regressions", action="store_true")
    ap.add_argument("--scenarios", nargs="?", default="24")
    for flag in ("--deep", "--jobs", "--cases"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []
    PL = "tools/pipeline"
    OP = "tools/operator"
    full = args.quests and args.factions

    print("=" * 72)
    print("WorldForge v2.2 QuestForge + FactionStateForge — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) -------------------------------------------
    results.append(run("failure-codes", PL + "/validate_failure_codes.py", *s))
    results.append(run("makefile-refs", PL + "/validate_makefile_refs.py", *s))
    results.append(run("quest-contracts", PL + "/validate_quest_contracts.py", *P, *s))
    results.append(run("faction-contracts", PL + "/validate_faction_contracts.py", *P, *s))
    results.append(run("quest-faction-contracts",
                       PL + "/validate_quest_faction_contracts.py", *P, *s))
    results.append(run("quest-faction-negative-fixtures",
                       PL + "/quest_faction_negatives.py", *s))

    # --- Quest authoring (--quests) ----------------------------------------
    if args.quests:
        results.append(run("generate-quests", PL + "/generate_quests.py", *P, *s))
        results.append(run("validate-generated-quests",
                           PL + "/validate_generated_quests.py", *P, *s))

    # --- Faction authoring (--factions) ------------------------------------
    if args.factions:
        results.append(run("generate-factions", PL + "/generate_factions.py", *P, *s))
        results.append(run("validate-generated-factions",
                           PL + "/validate_generated_factions.py", *P, *s))

    # --- Full downstream surface (--quests AND --factions) -----------------
    if full:
        # Wave 3 — runtime quest/faction proof
        results.append(run("run-quest-faction-smoke",
                           PL + "/run_quest_faction_alpha.py", "--smoke", *s))
        results.append(run("run-quest-faction-runtime",
                           PL + "/run_quest_faction_alpha.py", "--gate",
                           "--scenarios", args.scenarios, *s))
        results.append(run("validate-quest-faction-runtime",
                           PL + "/validate_quest_faction_runtime.py", *P, *s))
        results.append(run("validate-quest-faction-save-load",
                           PL + "/validate_quest_faction_save_load.py", *P, *s))
        # Wave 4 — OperatorForge quest/faction views
        results.append(run("operator-quest-faction-index",
                           OP + "/build_quest_faction_index.py", *s))
        results.append(run("operator-quest-faction-dashboard",
                           OP + "/build_quest_faction_dashboard.py", *s))
        results.append(run("operator-quest-faction-smoke",
                           OP + "/quest_faction_operator_smoke.py", *s))
        # Wave R — hostile suite
        results.append(run("quest-faction-negative-validators",
                           PL + "/quest_faction_negative_validators.py", *s))
        results.append(run("quest-faction-fuzz",
                           PL + "/quest_faction_fuzz.py", "--cases", "300",
                           "--seed", "1337", *s))
        results.append(run("quest-faction-torture",
                           PL + "/quest_faction_torture.py", *s))
        results.append(run("quest-faction-report-integrity",
                           PL + "/quest_faction_report_integrity.py", *s))
        results.append(run("quest-faction-hygiene",
                           PL + "/quest_faction_hygiene.py", *s))

    # --- Regression lane (opt-in authoring shields) ------------------------
    if args.regressions:
        results.append(run("regress:v2.1", PL + "/v2_1_shield.py", *P, *s, "--operator"))
        results.append(run("regress:v2.0", PL + "/v2_0_shield.py", *P, *s, "--package"))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v2.2 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed — awaiting quest/faction Waves 2/3/4/R): {}".format(failed))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
