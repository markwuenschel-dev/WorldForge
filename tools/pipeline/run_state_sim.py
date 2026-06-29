#!/usr/bin/env python3
"""run_state_sim.py — WorldForge v0.8 Runtime StateForge scenario simulator.

Runs a data-defined runtime scenario against a target Region and produces a
deterministic result descriptor:

  - reads the initial state (from a resolved slice spec, else scenario baseline)
  - mutates state by the scenario's bounded, clamped deltas
  - aggregates the post-state
  - computes the expected MPC render-mirror effect (curated keys -> MPC params)
  - computes expected POI state evidence
  - persists the post-state and reads it back (a real save/load round-trip)
  - writes result.json + state_save.json and upserts the scenario registry

This is the AUTHORING-SIDE (pure Python) simulation of the scenario. The UE-side
bridge (tools/unreal/run_state_scenario.py) applies the same scenario in-editor
and is validated against this descriptor's expectations.

State keys are read from the scenario data — nothing here is hard-coded to
industrial_pressure (forge_design_decisions: runtime hooks stay data-defined).

Usage:
    python tools/pipeline/run_state_sim.py --name Desert_Ash_IndustrialYard_01 \
        --scenario activate_industrial_forge

Requires: PyYAML (pip install pyyaml)
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_NAME = "run_state_sim"
GENERATOR_VERSION = "0.8.0"

sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from scenario_registry import (
    compute_scenario_input_hash,
    load_scenario_registry,
    make_run_id,
    save_scenario_registry,
    upsert_scenario_entry,
)
from provenance import build_provenance

# Curated state keys mirrored into MPC_WorldState (must match
# WorldStateSubsystem.cpp CuratedParams).
CURATED_MPC_PARAMS = {
    "industrial_pressure": "IndustrialPressure",
    "corruption_level": "CorruptionLevel",
    "restoration_level": "RestorationLevel",
    "wetness": "Wetness",
    "ashfall": "Ashfall",
}


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _resolve_slice_before(name: str, biome: str):
    """Return (context_id, {key: before}) from a slice spec if one exists."""
    spec_path = REPO_ROOT / "procedural" / "slices" / biome / "generated" / (name + ".json")
    if not spec_path.is_file():
        return None, {}, None
    try:
        with spec_path.open("r", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None, {}, None
    state = spec.get("state", {})
    context_id = state.get("context_id") or spec.get("region_id") or name
    before = {}
    if state.get("key") is not None and state.get("before") is not None:
        before[state["key"]] = float(state["before"])
    return context_id, before, spec_path.relative_to(REPO_ROOT).as_posix()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run a WorldForge runtime-state scenario simulation.")
    ap.add_argument("--name", required=True, help="Target name (slice id / Region context_id)")
    ap.add_argument("--scenario", required=True, help="Scenario id (procedural/definitions/scenarios/<id>.yaml)")
    ap.add_argument("--force", action="store_true", help="Rerun even if result.json already exists")
    args = ap.parse_args(argv)

    scenario_path = REPO_ROOT / "procedural" / "definitions" / "scenarios" / (args.scenario + ".yaml")
    if not scenario_path.is_file():
        sys.stderr.write("ERROR: scenario not found: {}\n".format(scenario_path))
        return 1

    with scenario_path.open("r", encoding="utf-8") as fh:
        scenario = yaml.safe_load(fh)

    scenario_id = scenario.get("scenario_id", args.scenario)
    biome = scenario.get("biome", "desert")
    scope = scenario.get("scope", "Region")
    thresholds = scenario.get("validation_thresholds", {})
    state_min = float(thresholds.get("state_min", 0.0))
    state_max = float(thresholds.get("state_max", 1.0))

    run_id = make_run_id(args.name, scenario_id)
    out_dir = REPO_ROOT / "procedural" / "generated" / "scenarios" / run_id
    result_path = out_dir / "result.json"
    save_path = out_dir / "state_save.json"

    if result_path.is_file() and not args.force:
        print("[run-state-sim] up-to-date (result exists; use --force to rerun): {}".format(
            result_path.relative_to(REPO_ROOT)))
        return 0

    # -- Resolve target + baseline -----------------------------------------
    context_id, slice_before, slice_spec_rel = _resolve_slice_before(args.name, biome)
    if context_id is None:
        context_id = args.name
    initial_state = {k: float(v) for k, v in scenario.get("initial_state", {}).items()}
    deltas = {k: float(v) for k, v in scenario.get("state_deltas", {}).items()}

    # Keys touched by the scenario = union of baseline + delta keys.
    keys = sorted(set(initial_state) | set(deltas))

    before_state = {}
    for k in keys:
        if k in slice_before:
            before_state[k] = slice_before[k]
        elif k in initial_state:
            before_state[k] = initial_state[k]
        else:
            before_state[k] = 0.0

    # -- Mutate -------------------------------------------------------------
    after_state = {}
    deltas_applied = {}
    for k in keys:
        d = deltas.get(k, 0.0)
        after_state[k] = _clamp(before_state[k] + d, state_min, state_max)
        deltas_applied[k] = round(after_state[k] - before_state[k], 6)

    print("[run-state-sim] {} scenario={} context={}".format(args.name, scenario_id, context_id))
    for k in keys:
        print("[run-state-sim]   {}: {} -> {} (delta {:+})".format(
            k, before_state[k], after_state[k], deltas_applied[k]))

    # -- Aggregate ----------------------------------------------------------
    values = [after_state[k] for k in keys] or [0.0]
    dominant_key = max(keys, key=lambda k: after_state[k]) if keys else None
    aggregate = {
        "keys": keys,
        "sum": round(sum(values), 6),
        "mean": round(sum(values) / len(values), 6),
        "max": round(max(values), 6),
        "dominant_key": dominant_key,
        "industrialization_index": round(after_state.get("industrial_pressure", 0.0), 6),
    }

    # -- Expected MPC render-mirror effect ---------------------------------
    expected_mpc = {}
    mpc_warnings = []
    for key, param in (scenario.get("expected_mpc", {}) or {}).items():
        # honor the scenario's declared param name, but verify against curated map
        curated = CURATED_MPC_PARAMS.get(key)
        if curated and curated != param:
            mpc_warnings.append("{} declared {} but curated map says {}".format(key, param, curated))
        expected_mpc[param] = round(after_state.get(key, 0.0), 6)
    is_curated = {k: (k in CURATED_MPC_PARAMS) for k in keys}

    # -- POI state evidence -------------------------------------------------
    poi_evidence = {}
    for poi_type, ev in (scenario.get("expected_poi_evidence", {}) or {}).items():
        driver = ev.get("driven_by_key")
        magnitude = round(after_state.get(driver, 0.0), 6) if driver else 0.0
        active = magnitude > before_state.get(driver, 0.0) if driver else False
        evidence = {
            "operational_state": ev.get("operational_state", "active" if active else "idle"),
            "driven_by_key": driver,
            "magnitude": magnitude,
            "changed": bool(active),
        }
        for field in ev.get("evidence_fields", []):
            if field == "activity_level":
                evidence[field] = magnitude
            else:
                evidence[field] = magnitude > 0.0
        poi_evidence[poi_type] = evidence

    # -- Save / load round-trip (real persistence at the data layer) -------
    save_cfg = scenario.get("save_load", {}) or {}
    persist_keys = list(save_cfg.get("persist_keys", keys))
    saved_state = {k: after_state[k] for k in persist_keys if k in after_state}
    save_blob = {
        "run_id": run_id,
        "scope": scope,
        "context_id": context_id,
        "state": saved_state,
        "saved_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with save_path.open("w", encoding="utf-8") as fh:
        json.dump(save_blob, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    with save_path.open("r", encoding="utf-8") as fh:
        reloaded = json.load(fh)
    restored_state = reloaded.get("state", {})
    roundtrip_ok = restored_state == saved_state
    save_load = {
        "save_path": save_path.relative_to(REPO_ROOT).as_posix(),
        "persist_keys": persist_keys,
        "saved_state": saved_state,
        "restored_state": restored_state,
        "roundtrip_ok": roundtrip_ok,
        "expect_roundtrip": bool(save_cfg.get("expect_roundtrip", True)),
    }
    print("[run-state-sim]   save/load roundtrip: {}".format("OK" if roundtrip_ok else "MISMATCH"))

    # -- Result descriptor --------------------------------------------------
    prov = build_provenance(REPO_ROOT, [scenario_path], GENERATOR_NAME, GENERATOR_VERSION)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    descriptor = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "target": args.name,
        "biome": biome,
        "scope": scope,
        "context_id": context_id,
        "slice_spec": slice_spec_rel,
        "state_keys": keys,
        "before_state": before_state,
        "after_state": after_state,
        "deltas_applied": deltas_applied,
        "is_curated_key": is_curated,
        "aggregate": aggregate,
        "expected_mpc": expected_mpc,
        "mpc_warnings": mpc_warnings,
        "poi_evidence": poi_evidence,
        "save_load": save_load,
        "thresholds": {
            "state_min": state_min,
            "state_max": state_max,
            "max_delta_per_key": float(thresholds.get("max_delta_per_key", 1.0)),
        },
        "outputs": {
            "result": result_path.relative_to(REPO_ROOT).as_posix(),
            "state_save": save_path.relative_to(REPO_ROOT).as_posix(),
        },
        "generated_at_utc": now_iso,
        "provenance": prov,
        "registry_owner": "worldforge_scenario_registry",
    }

    with result_path.open("w", encoding="utf-8") as fh:
        json.dump(descriptor, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[run-state-sim] result -> {}".format(result_path.relative_to(REPO_ROOT)))

    registry = load_scenario_registry(REPO_ROOT)
    entry = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "target": args.name,
        "context_id": context_id,
        "result_path": descriptor["outputs"]["result"],
        "input_hash": compute_scenario_input_hash({
            "run_id": run_id,
            "scenario_id": scenario_id,
            "target": args.name,
            "before_state": before_state,
            "after_state": after_state,
        }),
    }
    registry = upsert_scenario_entry(registry, entry)
    save_scenario_registry(REPO_ROOT, registry)
    print("[run-state-sim] registry updated")

    print("[run-state-sim] DONE: {}".format(run_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
