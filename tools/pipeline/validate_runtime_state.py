#!/usr/bin/env python3
"""validate_runtime_state.py — WorldForge v0.8 Runtime StateForge validator.

Validates the result descriptor produced by run_state_sim.py for a target, and
independently re-derives the scenario's expectations from its YAML so the
descriptor cannot lie to us. Pure Python — no UE imports.

Proves (all data-driven; no key is hard-coded):
  - initial state was read
  - state mutated by the scenario's bounded, clamped deltas
  - post-state is aggregated
  - the MPC render-mirror effect is correctly expected (curated key -> param)
  - POI state evidence updated
  - save/load round-trip restored the persisted state
  - post-scenario map validity (warn_only until UE slice validate is run)
  - the UE bridge applied + read back the state (warn_only until UE run)

Usage:
    python tools/pipeline/validate_runtime_state.py --name Desert_Ash_IndustrialYard_01
    python tools/pipeline/validate_runtime_state.py --name <target> --scenario <id>

Writes:
    procedural/reports/scenarios/<run_id>/validate_runtime_state_report.json

Exit 0 = PASS, 1 = FAIL.

Requires: PyYAML (pip install pyyaml)
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from scenario_registry import load_scenario_registry, make_run_id

CURATED_MPC_PARAMS = {
    "industrial_pressure": "IndustrialPressure",
    "corruption_level": "CorruptionLevel",
    "restoration_level": "RestorationLevel",
    "wetness": "Wetness",
    "ashfall": "Ashfall",
}
_EPS = 1e-6


def _resolve_run_id(name, scenario, registry):
    """Pick a run_id for the target, optionally disambiguated by scenario id."""
    if scenario:
        return make_run_id(name, scenario)
    matches = [rid for rid, e in registry.items() if e.get("target") == name]
    if len(matches) == 1:
        return matches[0]
    return None, matches


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate a WorldForge runtime-state scenario result.")
    ap.add_argument("--name", required=True, help="Target name (slice id / Region context_id)")
    ap.add_argument("--scenario", help="Scenario id (disambiguates when a target has several runs)")
    args = ap.parse_args(argv)

    registry = load_scenario_registry(REPO_ROOT)
    resolved = _resolve_run_id(args.name, args.scenario, registry)
    if isinstance(resolved, tuple):
        run_id, matches = resolved
        sys.stderr.write(
            "ERROR: {} runtime-state runs for target '{}'; pass --scenario. Candidates: {}\n".format(
                len(matches), args.name, ", ".join(matches) or "(none)"))
        sys.exit(1)
    run_id = resolved

    report_dir = REPO_ROOT / "procedural" / "reports" / "scenarios" / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    result = {"run_id": run_id, "target": args.name, "checks": {}, "failures": []}

    def check(name, ok, detail="", warn_only=False):
        result["checks"][name] = {"ok": bool(ok), "detail": str(detail), "warn_only": warn_only}
        if not ok:
            if warn_only:
                result.setdefault("warnings", []).append("{}: {}".format(name, detail or "warn"))
            else:
                result["failures"].append("{}: {}".format(name, detail or "failed"))
        return bool(ok)

    # -- Result descriptor --------------------------------------------------
    desc_path = REPO_ROOT / "procedural" / "generated" / "scenarios" / run_id / "result.json"
    descriptor = None
    if check("result_descriptor_exists", desc_path.is_file(), str(desc_path.relative_to(REPO_ROOT))):
        try:
            with desc_path.open("r", encoding="utf-8") as fh:
                descriptor = json.load(fh)
            check("result_descriptor_parses", True)
        except Exception as exc:
            check("result_descriptor_parses", False, str(exc))

    if descriptor is None:
        result["passed"] = False
        result["status"] = "error"
        _write_report(report_dir, result)
        print("[validate-runtime-state] FAIL — result descriptor missing or unparseable")
        sys.exit(1)

    check("registry_owns_run", run_id in registry, "not found in worldforge_scenario_registry.json")

    scenario_id = descriptor.get("scenario_id", "")
    before = descriptor.get("before_state", {})
    after = descriptor.get("after_state", {})
    deltas = descriptor.get("deltas_applied", {})
    thresholds = descriptor.get("thresholds", {})
    state_min = float(thresholds.get("state_min", 0.0))
    state_max = float(thresholds.get("state_max", 1.0))
    max_delta = float(thresholds.get("max_delta_per_key", 1.0))

    # -- Independently re-derive scenario expectations ----------------------
    scenario_path = REPO_ROOT / "procedural" / "definitions" / "scenarios" / (scenario_id + ".yaml")
    scenario = None
    if check("scenario_definition_exists", scenario_path.is_file(),
             str(scenario_path.relative_to(REPO_ROOT))):
        try:
            with scenario_path.open("r", encoding="utf-8") as fh:
                scenario = yaml.safe_load(fh)
        except Exception as exc:
            check("scenario_definition_parses", False, str(exc))
    scenario = scenario or {}
    declared_deltas = {k: float(v) for k, v in scenario.get("state_deltas", {}).items()}

    # -- Initial state read -------------------------------------------------
    check("initial_state_read", bool(before),
          "before_state empty — no initial state was read")

    # -- State mutation (re-derived from the scenario deltas) ---------------
    mutation_ok = True
    mutation_detail = []
    changed_any = False
    for k, d in declared_deltas.items():
        b = before.get(k)
        a = after.get(k)
        if b is None or a is None:
            mutation_ok = False
            mutation_detail.append("{} missing from before/after".format(k))
            continue
        expected = max(state_min, min(state_max, b + d))
        if abs(a - expected) > _EPS:
            mutation_ok = False
            mutation_detail.append("{}: after={} expected={} (before {} + delta {})".format(
                k, a, expected, b, d))
        if abs(a - b) > _EPS:
            changed_any = True
    check("state_mutation_applied", mutation_ok and bool(declared_deltas),
          "; ".join(mutation_detail) or "after == clamp(before + scenario delta)")
    check("state_actually_changed", changed_any,
          "no state key changed value — scenario had no effect")

    # -- Bounds -------------------------------------------------------------
    oob = [(k, v) for k, v in after.items() if v < state_min - _EPS or v > state_max + _EPS]
    check("state_within_bounds", not oob,
          "out-of-bounds [{},{}]: {}".format(state_min, state_max, oob))
    big = [(k, d) for k, d in deltas.items() if abs(d) > max_delta + _EPS]
    check("deltas_within_budget", not big,
          "deltas exceeding max_delta_per_key={}: {}".format(max_delta, big))

    # -- Aggregation --------------------------------------------------------
    agg = descriptor.get("aggregate", {})
    agg_ok = bool(agg) and agg.get("keys") == descriptor.get("state_keys")
    if agg_ok and after:
        vals = [after[k] for k in agg["keys"] if k in after]
        if vals:
            expect_mean = round(sum(vals) / len(vals), 6)
            agg_ok = abs(float(agg.get("mean", -1)) - expect_mean) < 1e-4
    check("state_aggregated", agg_ok, "aggregate block present and consistent with after_state")

    # -- MPC bridge expectation --------------------------------------------
    expected_mpc = descriptor.get("expected_mpc", {})
    mpc_ok = True
    mpc_detail = []
    for key, param in (scenario.get("expected_mpc", {}) or {}).items():
        curated = CURATED_MPC_PARAMS.get(key)
        if curated is None:
            mpc_ok = False
            mpc_detail.append("{} is not a curated MPC key".format(key))
            continue
        if curated != param:
            mpc_ok = False
            mpc_detail.append("{} mapped to {} but curated param is {}".format(key, param, curated))
        if abs(float(expected_mpc.get(param, -999)) - float(after.get(key, 0.0))) > _EPS:
            mpc_ok = False
            mpc_detail.append("{} expected_mpc={} != after={}".format(
                param, expected_mpc.get(param), after.get(key)))
    check("mpc_bridge_expectation", mpc_ok and bool(expected_mpc),
          "; ".join(mpc_detail) or "curated keys map to MPC params with post-state values")

    # -- POI state evidence -------------------------------------------------
    poi_ev = descriptor.get("poi_evidence", {})
    poi_ok = True
    poi_detail = []
    for poi_type, ev_spec in (scenario.get("expected_poi_evidence", {}) or {}).items():
        ev = poi_ev.get(poi_type)
        if not ev:
            poi_ok = False
            poi_detail.append("missing evidence for {}".format(poi_type))
            continue
        driver = ev_spec.get("driven_by_key")
        if driver and abs(float(ev.get("magnitude", -1)) - float(after.get(driver, 0.0))) > _EPS:
            poi_ok = False
            poi_detail.append("{} magnitude {} != after[{}]={}".format(
                poi_type, ev.get("magnitude"), driver, after.get(driver)))
    check("poi_state_evidence_updated", poi_ok and bool(poi_ev),
          "; ".join(poi_detail) or "POI evidence present and driven by post-state")

    # -- Save / load restoration -------------------------------------------
    sl = descriptor.get("save_load", {})
    save_path = REPO_ROOT / sl.get("save_path", "")
    check("state_save_file_exists", bool(sl.get("save_path")) and save_path.is_file(),
          str(sl.get("save_path", "")))
    restored = sl.get("restored_state", {})
    saved = sl.get("saved_state", {})
    persisted_after = {k: after[k] for k in sl.get("persist_keys", []) if k in after}
    check("save_load_roundtrip", bool(sl.get("roundtrip_ok")) and restored == saved,
          "restored_state must equal saved_state")
    check("save_load_restores_poststate", restored == persisted_after,
          "restored persisted keys must equal post-scenario state")

    # -- Post-scenario map validity (UE; warn_only) -------------------------
    slice_report = (REPO_ROOT / "procedural" / "reports" / "slices" / descriptor.get("biome", "desert")
                    / args.name / "validate_slice_report.json")
    map_ok = False
    if slice_report.is_file():
        try:
            map_ok = bool(json.loads(slice_report.read_text(encoding="utf-8")).get("passed"))
        except Exception:
            map_ok = False
    check("post_scenario_map_valid", map_ok,
          "run 'make validate-slice' for {} (UE) to confirm map validity".format(args.name),
          warn_only=True)

    # -- UE bridge applied + readback (warn_only) ---------------------------
    ue_report = report_dir / "ue_state_scenario_report.json"
    ue_ok = False
    ue_detail = "run 'make apply-state-scenario' (UE) to apply + read back the MPC bridge"
    if ue_report.is_file():
        try:
            ue_rpt = json.loads(ue_report.read_text(encoding="utf-8"))
            ue_ok = bool(ue_rpt.get("passed"))
            ue_detail = "ue readback={}".format(ue_rpt.get("mpc_readback"))
        except Exception:
            ue_ok = False
    check("ue_state_applied", ue_ok, ue_detail, warn_only=True)

    # -- Provenance ---------------------------------------------------------
    check("provenance_exists", bool(descriptor.get("provenance")),
          "provenance block absent from result descriptor")

    # -- Result -------------------------------------------------------------
    result["before_state"] = before
    result["after_state"] = after
    result["mpc_readback_expected"] = expected_mpc
    result["save_load_ok"] = bool(sl.get("roundtrip_ok"))
    result["affected_poi"] = list(poi_ev.keys())
    result["passed"] = len(result["failures"]) == 0
    result["status"] = "ok" if result["passed"] else "fail"
    _write_report(report_dir, result)

    verdict = "PASS" if result["passed"] else "FAIL"
    n_warn = len(result.get("warnings", []))
    print("[validate-runtime-state] {} — {} ({} failure(s), {} warning(s))".format(
        verdict, run_id, len(result["failures"]), n_warn))
    # Legible before/after summary
    for k in descriptor.get("state_keys", []):
        print("[validate-runtime-state]   {}: {} -> {}".format(k, before.get(k), after.get(k)))
    print("[validate-runtime-state]   scenario={} affected_poi={} save_load={}".format(
        scenario_id, result["affected_poi"], "OK" if result["save_load_ok"] else "FAIL"))
    for f in result["failures"]:
        print("[validate-runtime-state]   FAIL: {}".format(f))
    for w in result.get("warnings", []):
        print("[validate-runtime-state]   WARN: {}".format(w))
    sys.exit(0 if result["passed"] else 1)


def _write_report(report_dir: Path, result: dict):
    rpt_path = report_dir / "validate_runtime_state_report.json"
    with rpt_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[validate-runtime-state] report -> {}".format(rpt_path.relative_to(REPO_ROOT)))


if __name__ == "__main__":
    main()
