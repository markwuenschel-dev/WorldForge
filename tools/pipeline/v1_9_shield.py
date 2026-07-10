#!/usr/bin/env python3
"""v1_9_shield.py — WorldForge v1.9 Reward + Progression Alpha shield.

Aggregates and gates the whole v1.9 player-consequence substrate: the reward /
loadout / progression contract spine, deterministic reward-table + catalog
generation, the runtime reward bridge (reward grants that mutate inventory /
progression), independent save/load proof, the next-mission state handoff,
risk/reward classification, and the full hostile-validation suite.

It is FAIL-CLOSED by construction — a gate whose script is missing, or that
returns non-zero, turns the shield RED. Wave 1 delivers the contract spine +
fail-closed gates: the contract lanes go GREEN, but every runtime / authoring /
hostile gate that has not been built yet reports ``[FAIL] (gate not yet
implemented)`` so the shield's verdict tracks the real state of the milestone and
never reports a green it cannot prove. Later waves turn those gates green.

Gate lanes (selected by flags):
  (always)        failure-code registry + loadout/reward/progression contracts
  --rewards       reward-table + equipment/unlock catalog gen & validators,
                  risk/reward classification (Wave 2/3)
  --progression   inventory/progression/unlock state, save/load proof,
                  next-mission handoff (Wave 2/R)
  --torture       reward negatives, fuzz-300, torture, report integrity (Wave 7)
  --require-live  the runtime reward matrix + reward bridge (Wave R)

Under --strict every gate is strict. Heavier engine-realized regressions
(v1.8 combat, v1.7 npc, v1.6z ground) run via their own shields; this shield
names them for the operator.
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
    ap = argparse.ArgumentParser(description="WorldForge v1.9 Reward + Progression Alpha shield.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--rewards", action="store_true")
    ap.add_argument("--progression", action="store_true")
    ap.add_argument("--torture", action="store_true")
    ap.add_argument("--require-live", action="store_true")
    ap.add_argument("--scenarios", default="120")
    for flag in ("--deep", "--jobs"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []

    print("=" * 72)
    print("WorldForge v1.9 Reward + Progression Alpha — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Contract spine (always) ----------------------------------------
    results.append(run("failure-codes", "validate_failure_codes.py", *s))
    results.append(run("loadout-contracts", "validate_loadout_contracts.py", *P, *s))
    results.append(run("reward-contracts", "validate_reward_contracts.py", *P, *s))
    results.append(run("progression-contracts", "validate_progression_contracts.py", *P, *s))

    # --- Reward-table / catalog authoring + classification lane ---------
    # Generators FIRST (catalogs + tables), then validators — validate_reward_tables
    # cross-refs the equipment/unlock catalogs, so they must exist first.
    if args.rewards:
        results.append(run("reward:equipment-catalog", "generate_equipment_catalog.py", *P, *s))
        results.append(run("reward:unlock-catalog", "generate_unlock_catalog.py", *P, *s))
        results.append(run("reward:tables", "generate_reward_tables.py", *P, *s))
        results.append(run("reward:validate-tables", "validate_reward_tables.py", *P, *s))
        results.append(run("reward:classify-risk-reward", "classify_risk_reward.py", *P, *s))
        results.append(run("reward:validate-risk-reward", "validate_risk_reward.py", *P, *s))

    # --- Progression / inventory / unlock state + persistence lane ------
    # generate_progression_state writes the full authoring scenario evidence
    # (grant events, inventory/progression/unlock states, completion, telemetry)
    # that every validator below consumes, so it runs first.
    if args.progression:
        results.append(run("progression:state", "generate_progression_state.py", *P, *s))
        results.append(run("progression:validate-state", "validate_progression_state.py", *P, *s))
        results.append(run("progression:validate-unlock-state", "validate_unlock_state.py", *P, *s))
        results.append(run("progression:inventory-save-load", "validate_inventory_save_load.py", *P, *s))
        results.append(run("progression:progression-save-load", "validate_progression_save_load.py", *P, *s))
        results.append(run("progression:next-mission-state", "validate_next_mission_state.py", *P, *s))

    # --- Runtime reward bridge (P2, Wave R) — UE-realized, --require-live only.
    # Wave 2 proves the authoring substrate WITHOUT the engine; the runtime matrix
    # is a separate, explicitly-gated lane so Wave 2 green never implies runtime.
    if args.require_live:
        results.append(run("reward:matrix-P2", "run_reward_forge_alpha.py",
                           "--gate", "--scenarios", args.scenarios, *s))
        results.append(run("reward:validate-bridge", "validate_reward_bridge.py", *P, *s))

    # --- Hostile validation suite ---------------------------------------
    if args.torture:
        results.append(run("negatives", "reward_negatives.py", *s))
        results.append(run("fuzz-300", "reward_fuzz.py", "--cases", "300", "--seed", "1337", *s))
        results.append(run("torture", "reward_torture.py", *P, *s))
        results.append(run("report-integrity", "reward_report_integrity.py", *P, *s))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v1.9 shield: {} — {}/{} gates passed".format(verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed until built): {}".format(failed))
    print("  NOTE: engine-realized regressions run via their own shields —")
    print("        v1_8_shield.py / v1_7_shield.py / v1_6z_shield.py.")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
