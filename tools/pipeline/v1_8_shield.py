#!/usr/bin/env python3
"""v1_8_shield.py — WorldForge v1.8 CombatForge Alpha shield.

Aggregates and gates the whole v1.8 combat substrate: the combat contract spine,
combat profiles, the runtime combat matrix (player health mutation, NPC
pressure->damage bridge, hazard damage), survivability/balance classification, and
the full hostile-validation suite. It is FAIL-CLOSED by construction — a gate whose
script is missing or that returns non-zero turns the shield RED. Wave 1 delivers the
contract spine + fail-closed gates; later waves turn the remaining gates green, and
the shield's verdict tracks that honestly (it never reports a green it cannot prove).

Gate lanes (selected by flags):
  (always)     contract spine + failure codes
  --combat     combat profile generation + validators
  --behavior   runtime combat matrix, damage bridges, health mutation, save/load, balance
  --torture    negatives, fuzz, torture, report integrity
  --require-live  the full 120/120 combat matrix (P2) instead of the sample

Under --strict every gate is strict. Heavier engine-realized regressions (v1.7
behavior, v1.6z ground, v1.5 assets/visual) run via their own make targets; this
shield names them for the operator.
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
    ap = argparse.ArgumentParser(description="WorldForge v1.8 CombatForge Alpha shield.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--combat", action="store_true")
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
    print("WorldForge v1.8 CombatForge Alpha — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) ----------------------------------------
    results.append(run("failure-codes", "validate_failure_codes.py", *s))
    results.append(run("combat-contracts", "validate_combat_contracts.py", *P, *s))

    # --- Combat profile generation lane ---------------------------------
    if args.combat:
        results.append(run("combat:profiles", "generate_combat_profiles.py", *P, *s))
        results.append(run("combat:validate-profiles", "validate_combat_profiles.py", *P, *s))

    # --- Runtime combat + balance lane ----------------------------------
    if args.behavior:
        if args.require_live:
            results.append(run("combat:matrix-P2", "run_combat_forge_alpha.py",
                               "--gate", "--scenarios", args.scenarios, *s))
        else:
            results.append(run("combat:sample", "run_combat_forge_alpha.py",
                               "--scenarios", "12", *s))
        results.append(run("combat:runtime-core", "validate_combat_runtime_core.py", *P, *s))
        results.append(run("combat:npc-damage-bridge", "validate_npc_damage_bridge.py", *P, *s))
        results.append(run("combat:hazard-damage", "validate_hazard_combat.py", *P, *s))
        results.append(run("combat:health-mutation", "validate_player_health.py", *P, *s))
        results.append(run("combat:telemetry", "validate_combat_telemetry.py", *P, *s))
        results.append(run("combat:completion", "validate_combat_completion.py", *P, *s))
        results.append(run("combat:save-load", "validate_combat_save_load.py", *P, *s))
        results.append(run("combat:classify-survivability", "classify_combat_balance.py", *P, *s))
        results.append(run("combat:balance", "validate_combat_balance.py", *P, *s))

    # --- Hostile validation suite ---------------------------------------
    if args.torture:
        results.append(run("negatives", "combat_negatives.py", *s))
        results.append(run("fuzz-300", "combat_fuzz.py", "--cases", "300", "--seed", "1337", *s))
        results.append(run("torture", "combat_torture.py", *P, *s))
        results.append(run("report-integrity", "combat_report_integrity.py", *P, *s))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v1.8 shield: {} — {}/{} gates passed".format(verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed until built): {}".format(failed))
    print("  NOTE: engine-realized regressions run via their own targets —")
    print("        v1-7-shield / v1-6z-shield / v1-5-shield.")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
