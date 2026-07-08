#!/usr/bin/env python3
"""v1_6_shield.py — WorldForge v1.6 runtime-playability shield.

Runs the v1.6 runtime lane in dependency order and rolls the results up. It is
honest about the offline-editor reality:

  * The AUTHORING SUBSTRATE gates (taxonomy, scenario/route/interaction/pawn
    generation + validation, coverage, completion-report integrity, and the
    always-on no-fake-green detector) are run under STRICT and MUST all pass.
  * The LIVE-RUN completion gate is STAGED: with the UE/NeoStack bridge offline
    every scenario classifies staged_live_run_pending. The shield reports the
    staged count as a prominent banner and does NOT count it as runtime
    completion — but it also does not fake a failure of the authoring substrate.
    With --require-live (or the bridge live), completion becomes mandatory.

Exit 0 == authoring substrate green AND zero fake-green. Exit 1 == a real
authoring/integrity failure, or (with --require-live) scenarios not completed.

Usage:
    python tools/pipeline/v1_6_shield.py --pack encounter_loop_world [--strict] [--require-live]
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPE))

from runtime_bridge import ue_bridge_live, bridge_status_detail  # noqa: E402


def gate(label, script, *args):
    return {"label": label, "script": script, "args": list(args)}


def build_gates(pack, strict):
    s = ["--strict"] if strict else []
    P = ["--pack", pack]
    return [
        gate("taxonomy", "validate_v1_6_taxonomy.py", *s),
        gate("failure-codes", "validate_failure_codes.py", *s),
        gate("scenarios:generate", "generate_runtime_scenarios.py", *P, *s),
        gate("scenarios:validate", "validate_runtime_scenarios.py", *P, *s),
        gate("scenarios:coverage", "validate_runtime_scenario_coverage.py", *P, *s),
        gate("interactions:materialize", "materialize_runtime_interaction_actors.py", *P, *s),
        gate("interactions:validate", "validate_runtime_interactions.py", *P, *s),
        gate("interactions:verbs", "validate_runtime_interaction_verbs.py", *P, *s),
        gate("interactions:completion-bridge", "validate_runtime_mission_completion_bridge.py", *P, *s),
        gate("pawn:generate", "create_runtime_pawn_profile.py", "--profile", "default", *s),
        gate("pawn:validate", "validate_runtime_pawn_profile.py", "--profile", "default", *s),
        gate("routes:generate", "generate_runtime_route_plans.py", *P, *s),
        gate("routes:validate", "validate_runtime_route_plans.py", *P, *s),
        # Gamma runner: staged offline. Run WITHOUT strict here so staging does
        # not fail the authoring substrate; --require-live re-adds the demand.
        gate("gamma:run", "run_playtest_forge_gamma.py", *P, "--scenarios", "all"),
        gate("gamma:completion", "validate_runtime_completion.py", *P),
        # The no-fake-green detector is ALWAYS strict — a fake success must fail
        # the shield no matter what.
        gate("gamma:no-fake-green", "validate_playtest_gamma_no_fake_green.py", *P, "--strict"),
        # Negative harness: known-bad must fail for its owning code (authoring-side).
        gate("negatives", "test_negative_runtime.py", *s),
        # Fuzz: no validator crashes + no corrupted artifact accepted.
        gate("fuzz", "v1_6_fuzz.py", "--cases", "300", "--seed", "1337", *s),
        # Report integrity: audit the report envelopes themselves.
        gate("report-integrity", "runtime_report_integrity.py", *P, *s),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 runtime-playability shield.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", action="store_true",
                    help="fail the shield unless every scenario completed_runtime")
    # accepted-and-ignored knobs so the Makefile can pass the usual shield flags
    for flag in ("--deep", "--torture", "--runtime", "--jobs", "--seeds", "--cases", "--playtest"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _unknown = ap.parse_known_args(argv)

    live = ue_bridge_live()
    # A running editor (runtime.json present) does NOT by itself mean live driver
    # output exists — requiring real completion is an explicit operator choice.
    require_live = args.require_live
    gates = build_gates(args.pack, strict=True if args.strict or True else False)

    print("=" * 70)
    print("WorldForge v1.6 runtime-playability shield — pack={}".format(args.pack))
    print(bridge_status_detail())
    print("=" * 70)

    results = []
    for g in gates:
        cmd = [sys.executable, str(PIPE / g["script"])] + g["args"]
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
        ok = proc.returncode == 0
        results.append((g["label"], ok))
        print("  [{}] {}".format("PASS" if ok else "FAIL", g["label"]))

    failed = [lbl for lbl, ok in results if not ok]

    # Staged live-run status (informational unless --require-live).
    print("-" * 70)
    if require_live:
        for lbl, script in (("gamma:live-completion", "run_playtest_forge_gamma.py"),
                            ("telemetry", "validate_runtime_telemetry.py"),
                            ("save-load", "validate_runtime_save_load.py")):
            extra = ["--scenarios", "all"] if "gamma" in lbl else []
            cmd = [sys.executable, str(PIPE / script), "--pack", args.pack, *extra, "--strict"]
            rc = subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode
            if rc != 0:
                failed.append("{} (require-live)".format(lbl))
            print("  [{}] {} (require-live)".format("PASS" if rc == 0 else "FAIL", lbl))
        # v1.6x full-matrix assertion: all 120 scenarios genuinely completed_runtime
        # via the headless -game batch (crash-isolated, no editor/bridge/navmesh).
        rc = subprocess.run(
            [sys.executable, str(PIPE / "run_headless_runtime_batch.py"), "--gate", "--strict"],
            cwd=str(REPO_ROOT)).returncode
        if rc != 0:
            failed.append("headless:full-matrix-120 (require-live)")
        print("  [{}] headless:full-matrix-120 (require-live)".format("PASS" if rc == 0 else "FAIL"))
    else:
        detail = ("bridge file present but no live driver completions yet"
                  if live else "UE bridge offline")
        print("  LIVE-RUN STAGED: {} — scenarios staged_live_run_pending "
              "(not fake-green). Run the UE driver (runtime_playtest_pack.py) and "
              "rerun with --require-live to convert to real runtime completion."
              .format(detail))

    print("=" * 70)
    verdict = "GREEN" if not failed else "RED"
    print("v1.6 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len([f for f in failed if ":" in f or f in dict(results)]),
        len(results)))
    if failed:
        print("  FAILED: {}".format(failed))
    print("  authoring substrate: {}".format("GREEN" if not failed else "RED"))
    live_state = ("GREEN" if require_live and not failed
                  else "STAGED ({})".format(
                      "no live driver output yet" if live else "editor offline"))
    print("  live runtime completion: {}".format(live_state))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
