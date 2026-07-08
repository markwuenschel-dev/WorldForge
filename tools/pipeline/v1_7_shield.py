#!/usr/bin/env python3
"""v1_7_shield.py — WorldForge v1.7 NPCForge + EncounterBehaviorForge shield.

Aggregates and gates the whole v1.7 behavior substrate: the NPC/behavior contract
spine, generation + materialization, spawn-placement + route-binding, the runtime
behavior matrix, balance classification, and the full hostile-validation suite. It
is FAIL-CLOSED by construction — a gate whose script is missing or that returns
non-zero turns the shield RED. Wave 1 delivers the contract spine + fail-closed
gates; later waves turn the remaining gates green, and the shield's verdict tracks
that honestly (it never reports a green it cannot prove).

Gate lanes (selected by flags):
  (always)     contract spine + failure codes
  --npc        archetypes, spawn groups, behavior profiles, scenarios, and their
               validators; materialization + spawn-placement + route-binding
  --behavior   runtime behavior matrix, telemetry, completion, save/load, balance
  --torture    negatives, fuzz, torture, report integrity
  --require-live  the full 120/120 behavior matrix (P2) instead of the sample

Under --strict every gate is strict. Heavier engine-realized regressions (v1.6z
ground, v1.5 assets/visual, mission/biome/desert full-shields) run via their own
make targets; this shield names them for the operator.
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
    rc = subprocess.run([PY, str(script_path), *[str(x) for x in a]], cwd=str(REPO_ROOT)).returncode
    print("  [{}] {}".format("PASS" if rc == 0 else "FAIL", label))
    return label, rc == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.7 NPCForge behavior shield.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--npc", action="store_true")
    ap.add_argument("--behavior", action="store_true")
    ap.add_argument("--torture", action="store_true")
    ap.add_argument("--require-live", action="store_true")
    ap.add_argument("--scenarios", default="120")
    for flag in ("--deep", "--jobs"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []

    print("=" * 72)
    print("WorldForge v1.7 NPCForge + EncounterBehaviorForge — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) ----------------------------------------
    results.append(run("failure-codes", "validate_failure_codes.py", *s))
    results.append(run("npc-contracts", "validate_npc_contracts.py", *P, *s))

    # --- NPC generation + materialization lane --------------------------
    if args.npc:
        results.append(run("npc:archetypes", "generate_npc_archetypes.py", *P, *s))
        results.append(run("npc:spawn-groups", "generate_npc_spawn_groups.py", *P, *s))
        results.append(run("npc:behavior-profiles", "generate_npc_behavior_profiles.py", *P, *s))
        results.append(run("npc:behavior-scenarios", "generate_npc_behavior_scenarios.py", *P, *s))
        results.append(run("npc:validate-scenarios", "validate_npc_behavior_scenarios.py", *P, *s))
        results.append(run("npc:materialize", "materialize_npc_actors.py", *P, *s))
        results.append(run("npc:validate-actors", "validate_npc_actors.py", *P, *s))
        results.append(run("npc:spawn-placement", "validate_npc_spawn_placement.py", *P, *s))
        results.append(run("npc:route-binding", "validate_npc_route_binding.py", *P, *s))

    # --- Runtime behavior + balance lane --------------------------------
    if args.behavior:
        if args.require_live:
            results.append(run("behavior:matrix-P2", "run_npc_behavior_batch.py",
                               "--gate", "--scenarios", args.scenarios, *s))
        else:
            results.append(run("behavior:sample", "run_npc_behavior_batch.py",
                               "--scenarios", "12", *s))
        results.append(run("behavior:telemetry", "validate_npc_telemetry.py", *P, *s))
        results.append(run("behavior:completion", "validate_npc_completion.py", *P, *s))
        results.append(run("behavior:save-load", "validate_npc_save_load.py", *P, *s))
        results.append(run("behavior:classify-pressure", "classify_npc_pressure.py", *P, *s))
        results.append(run("behavior:balance", "validate_npc_balance.py", *P, *s))

    # --- Hostile validation suite ---------------------------------------
    if args.torture:
        results.append(run("negatives", "npc_behavior_negatives.py", *s))
        results.append(run("fuzz-300", "npc_behavior_fuzz.py", "--cases", "300", "--seed", "1337", *s))
        results.append(run("torture", "npc_behavior_torture.py", *P, *s))
        results.append(run("report-integrity", "npc_report_integrity.py", *P, *s))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v1.7 shield: {} — {}/{} gates passed".format(verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed until built): {}".format(failed))
    print("  NOTE: engine-realized regressions run via their own targets —")
    print("        v1-6z-shield / v1-6x-shield / v1-5-shield / full-shield {mission,biome,desert}.")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
