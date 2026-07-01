#!/usr/bin/env python3
"""run_world_state_scenario.py — WorldForge v1.0 pack-level runtime scenario runner.

Runs a Runtime StateForge scenario across every *compatible* map in a world pack,
not just one hand-picked slice. Compatibility is resolved from data:

  1. primary  — slices whose matrix ``scenarios:`` metadata lists the scenario_id
  2. fallback — slices whose ``poi`` is in the scenario's ``compatible_poi`` list

For each compatible slice it runs the proven v0.8 pair as subprocesses:

    run_state_sim.py        (mutate -> aggregate -> MPC -> POI evidence -> save/load)
    validate_runtime_state.py (re-derives + validates that result, --strict aware)

then aggregates a pack-level scenario report (per-slice roundtrip + POI evidence +
validation verdict). No new simulation framework is introduced and no UE is
launched here — the post-scenario map-validity check stays D7-gated inside
validate_runtime_state.

Usage:
    python tools/pipeline/run_world_state_scenario.py \
        --pack procedural/world_packs/desert_mvp_world.yaml \
        --scenario industrial_takeover [--strict] [--force] [--limit N]

Exit 0 = PASS, 1 = FAIL.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode

RUN_SIM = REPO_ROOT / "tools" / "pipeline" / "run_state_sim.py"
VALIDATE = REPO_ROOT / "tools" / "pipeline" / "validate_runtime_state.py"


def _py(argv):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable] + [str(a) for a in argv],
                          cwd=str(REPO_ROOT), env=env).returncode


def _load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _collect_slices(world_pack):
    """Yield (name, slice_dict) across every referenced slice pack."""
    out = []
    for entry in world_pack.get("packs", []):
        rel = entry.get("pack_path", "")
        sp_path = REPO_ROOT / rel if rel else None
        if not sp_path or not sp_path.is_file():
            continue
        sp = _load_yaml(sp_path)
        for sl in sp.get("slices", []):
            out.append(sl)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run a runtime-state scenario across a world pack's compatible maps.")
    ap.add_argument("--pack", required=True, help="Path to world pack YAML")
    ap.add_argument("--scenario", required=True, help="Scenario id (procedural/definitions/scenarios/<id>.yaml)")
    ap.add_argument("--strict", action="store_true", help="Thread --strict into per-slice validation; also via STRICT=1.")
    ap.add_argument("--force", action="store_true", help="Rerun sims even if a result already exists.")
    ap.add_argument("--limit", type=int, default=0, help="Cap number of compatible slices run (0 = all).")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()

    pack_path = Path(args.pack)
    if not pack_path.is_absolute():
        pack_path = REPO_ROOT / pack_path
    scenario_path = REPO_ROOT / "procedural" / "definitions" / "scenarios" / (args.scenario + ".yaml")

    world_pack_id = pack_path.stem
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not pack_path.is_file():
        rep.error("world pack not found: {}".format(pack_path))
    elif not scenario_path.is_file():
        rep.error("scenario not found: {}".format(scenario_path))
    if rep._status == "error":
        rep.finalize()
        rep.print_summary("run-world-state-scenario")
        sys.exit(rep.exit_code)

    world_pack = _load_yaml(pack_path)
    world_pack_id = world_pack.get("world_pack_id", world_pack_id)
    rep.entity_id = world_pack_id
    scenario = _load_yaml(scenario_path)
    scenario_id = scenario.get("scenario_id", args.scenario)
    compatible_poi = set(scenario.get("compatible_poi", []) or [])

    # -- Resolve compatible slices (data-driven) --------------------------------
    compatible = []
    for sl in _collect_slices(world_pack):
        name = sl.get("name")
        if not name:
            continue
        tagged = scenario_id in (sl.get("scenarios") or [])
        poi_match = sl.get("poi") in compatible_poi
        if tagged or poi_match:
            compatible.append((name, "tag" if tagged else "poi"))

    print("=== Run World State Scenario: {} on {} (strict={}) ===".format(
        scenario_id, world_pack_id, "on" if strict else "off"))
    print("Compatible maps: {}".format(len(compatible)))

    rep.check("scenario_has_compatible_maps", bool(compatible),
              "{} compatible map(s)".format(len(compatible)) if compatible
              else "no compatible maps for scenario '{}'".format(scenario_id),
              code=FailureCode.SPEC_INVALID)

    if args.limit and args.limit > 0:
        compatible = compatible[:args.limit]
        print("Limited to first {} map(s).".format(len(compatible)))

    # -- Run sim + validate per compatible map ----------------------------------
    rows = []
    for name, why in compatible:
        sim_argv = [RUN_SIM, "--name", name, "--scenario", scenario_id]
        if args.force:
            sim_argv.append("--force")
        rc_sim = _py(sim_argv)

        val_argv = [VALIDATE, "--name", name, "--scenario", scenario_id]
        if strict:
            val_argv.append("--strict")
        rc_val = _py(val_argv) if rc_sim == 0 else 1

        # Read back the sim result for roundtrip + POI evidence aggregation.
        run_id = "{}__{}".format(name, scenario_id)
        result_path = REPO_ROOT / "procedural" / "generated" / "scenarios" / run_id / "result.json"
        roundtrip_ok, poi_types = None, []
        if result_path.is_file():
            try:
                res = json.loads(result_path.read_text(encoding="utf-8"))
                roundtrip_ok = bool((res.get("save_load") or {}).get("roundtrip_ok"))
                poi_types = sorted((res.get("poi_evidence") or {}).keys())
            except Exception:
                pass

        ok = (rc_sim == 0 and rc_val == 0)
        key = "scenario:{}".format(name)
        detail = "via {} | sim_rc={} val_rc={} roundtrip={} poi={}".format(
            why, rc_sim, rc_val, roundtrip_ok, ",".join(poi_types) or "-")
        rep.check(key, ok, detail, code=FailureCode.CHILD_VALIDATION_FAILED)
        rows.append({"name": name, "match": why, "sim_rc": rc_sim, "val_rc": rc_val,
                     "roundtrip_ok": roundtrip_ok, "poi_evidence": poi_types, "passed": ok})

    n_pass = sum(1 for r in rows if r["passed"])
    print("\n=== Scenario '{}': {}/{} compatible maps PASS ===".format(
        scenario_id, n_pass, len(rows)))

    rep.finalize()

    out_dir = REPO_ROOT / "procedural" / "reports" / "world_packs" / world_pack_id
    rep.write(out_dir, "run_world_state_scenario_report.json", quiet=True)
    out = rep.to_dict()
    out.update({"scenario_id": scenario_id, "compatible_count": len(compatible),
                "maps": rows, "maps_pass": n_pass})
    (out_dir / "run_world_state_scenario_report.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Report: procedural/reports/world_packs/{}/run_world_state_scenario_report.json".format(world_pack_id))

    rep.print_summary("run-world-state-scenario")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
