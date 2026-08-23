#!/usr/bin/env python3
"""validate_runtime_state.py — WorldForge Runtime StateForge validator.

Validates the result descriptor produced by run_state_sim.py for a target, and
independently re-derives the scenario's expectations from its YAML so the
descriptor cannot lie to us. Pure Python — no UE imports.

Migrated to the v0.9 shared validation contract
(tools/pipeline/validation_report.py + tools/pipeline/failure_codes.py):
  - one canonical report shape (superset of the legacy shape),
  - the verdict vocabulary (PASS/WARN/WARN_ONLY/FAIL/SKIP),
  - opt-in --strict / STRICT=1 that only ever ADDS blocking,
  - stable WFnnn failure codes per check.

Proves (all data-driven; no state key is hard-coded):
  - scenario parses (WF070)
  - target map resolves (WF071)
  - initial state was read
  - state delta is bounded (WF072)
  - each key the scenario mutates moves init -> clamp(init + scenario delta)
    (driven by the scenario's own ``state_deltas`` — never hard-coded)
  - post-state is aggregated
  - the MPC render-mirror effect is correctly expected (curated key -> param),
    expected scalar == simulated post-state (WF073)
  - POI state evidence updated (WF074)
  - save/load round-trip restored the persisted state (WF075)
  - provenance present
  - post-scenario map validity — verified from the per-slice UE validate report
  - the in-editor MPC bridge readback — an optional native-owner cross-check (WF082)

The editor-Python 'make apply-state-scenario' helper cannot acquire a native
write lease, so it records native-authority-required rather than applying state.
No persisted JSON record can currently prove a native leased write and live
readback: every present UE report fails WF082 until a native-only in-process
synchronous emitter/verifier exists. When no report is present the cross-check
is skipped (non-blocking), because the authoring-side scenario validation
already proves the state logic.

Usage:
    python tools/pipeline/validate_runtime_state.py --name Desert_Ash_IndustrialYard_01
    python tools/pipeline/validate_runtime_state.py --name <target> --scenario <id>
    python tools/pipeline/validate_runtime_state.py --name <target> --strict

Writes:
    procedural/reports/scenarios/<run_id>/validate_runtime_state_report.json

Exit 0 = PASS (no blocking failure), 1 = FAIL.

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
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode

CURATED_MPC_PARAMS = {
    "industrial_pressure": "IndustrialPressure",
    "corruption_level": "CorruptionLevel",
    "restoration_level": "RestorationLevel",
    "wetness": "Wetness",
    "ashfall": "Ashfall",
}
_EPS = 1e-6

_NATIVE_AUTHORITY_RECORD_VERSION = 1
_NATIVE_AUTHORITY_RECORD_FIELDS = frozenset((
    "record_version",
    "kind",
    "status",
    "writer",
    "scope",
    "context_id",
    "state_keys",
))


def validate_native_authority_evidence(ue_report, descriptor):
    """Reject untrusted persisted claims while preserving useful failure detail.

    A record can describe an alleged native leased write, but arbitrary Python
    can forge that description. Until a native-only in-process synchronous
    emitter/verifier is tied directly to SetStateValueWithLease and the same
    live MPC readback, no persisted JSON can make ``ue_state_applied`` pass.
    The v1 parsing and descriptor-binding checks below remain only to explain
    why a present report is rejected; they do not authenticate it.
    """
    if not isinstance(ue_report, dict):
        return False, "UE report is not an object"

    authority = ue_report.get("authority")
    if not isinstance(authority, dict):
        return False, "native authority evidence is absent or malformed"
    if authority.get("status") == "native_authority_required":
        return False, "native state-write authority is required"

    fields = set(authority)
    if fields != _NATIVE_AUTHORITY_RECORD_FIELDS:
        missing = sorted(_NATIVE_AUTHORITY_RECORD_FIELDS - fields)
        unexpected = sorted(fields - _NATIVE_AUTHORITY_RECORD_FIELDS)
        detail = "native authority evidence has the wrong v1 field set"
        if missing:
            detail += "; missing={}".format(",".join(missing))
        if unexpected:
            detail += "; unexpected={}".format(",".join(unexpected))
        return False, detail

    if (type(authority["record_version"]) is not int or
            authority["record_version"] != _NATIVE_AUTHORITY_RECORD_VERSION):
        return False, "native authority evidence has an unsupported record version"
    if authority["kind"] != "native_state_write_lease":
        return False, "native authority evidence is not a native write-lease record"
    if authority["status"] != "success":
        return False, "native authority evidence does not record success"
    if authority["writer"] != "native":
        return False, "native authority evidence was not emitted by a native writer"

    expected_run_id = descriptor.get("run_id")
    expected_scope = descriptor.get("scope")
    expected_context_id = descriptor.get("context_id")
    expected_state_keys = descriptor.get("state_keys")
    if (not isinstance(expected_run_id, str) or not expected_run_id or
            not isinstance(expected_scope, str) or not expected_scope or
            not isinstance(expected_context_id, str) or not expected_context_id or
            not isinstance(expected_state_keys, list) or
            not expected_state_keys or
            not all(isinstance(key, str) and key for key in expected_state_keys)):
        return False, "scenario descriptor does not provide a bound state address"
    if ue_report.get("run_id") != expected_run_id:
        return False, "native authority evidence belongs to a different scenario run"
    if authority["scope"] != expected_scope or authority["context_id"] != expected_context_id:
        return False, "native authority evidence is bound to a different state address"
    if authority["state_keys"] != expected_state_keys:
        return False, "native authority evidence does not cover the scenario state keys"

    if ue_report.get("passed") is not True:
        return False, "native authority report did not pass its UE readback"
    if not isinstance(ue_report.get("applied"), dict) or not ue_report["applied"]:
        return False, "native authority report lacks applied-state evidence"
    if not isinstance(ue_report.get("mpc_readback"), dict) or not ue_report["mpc_readback"]:
        return False, "native authority report lacks MPC readback evidence"
    if not isinstance(ue_report.get("checks"), dict) or not ue_report["checks"]:
        return False, "native authority report lacks check evidence"

    return False, (
        "persisted JSON cannot prove a native leased write and live MPC readback; "
        "a future native-only synchronous emitter/verifier tied to "
        "SetStateValueWithLease is required")


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
    ap.add_argument("--strict", action="store_true",
                    help="Strict mode: WARN checks become blocking (optional UE checks stay non-blocking).")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()

    registry = load_scenario_registry(REPO_ROOT)
    resolved = _resolve_run_id(args.name, args.scenario, registry)

    # -- Ambiguous / unresolvable target -----------------------------------
    if isinstance(resolved, tuple):
        _run_id, matches = resolved
        rep = ValidationReport("run_id", "{}__<unresolved>".format(args.name), strict=strict)
        rep.check(
            "target_map_resolved", False,
            "{} runtime-state runs for target '{}'; pass --scenario. Candidates: {}".format(
                len(matches), args.name, ", ".join(matches) or "(none)"),
            code=FailureCode.TARGET_MAP_UNRESOLVED)
        rep.error()
        rep.finalize()
        rep.print_summary("validate-runtime-state")
        sys.stderr.write(
            "ERROR: {} runtime-state runs for target '{}'; pass --scenario.\n".format(
                len(matches), args.name))
        sys.exit(rep.exit_code)
    run_id = resolved

    report_dir = REPO_ROOT / "procedural" / "reports" / "scenarios" / run_id
    rep = ValidationReport("run_id", run_id, strict=strict)

    # -- Result descriptor --------------------------------------------------
    desc_path = REPO_ROOT / "procedural" / "generated" / "scenarios" / run_id / "result.json"
    descriptor = None
    if rep.check("result_descriptor_exists", desc_path.is_file(),
                 str(desc_path.relative_to(REPO_ROOT)),
                 code=FailureCode.DESCRIPTOR_MISSING):
        try:
            with desc_path.open("r", encoding="utf-8") as fh:
                descriptor = json.load(fh)
            rep.check("result_descriptor_parses", True)
        except Exception as exc:
            rep.check("result_descriptor_parses", False, str(exc),
                      code=FailureCode.DESCRIPTOR_UNPARSEABLE)

    if descriptor is None:
        rep.error("result descriptor missing or unparseable")
        rep.finalize()
        rep.write(report_dir, "validate_runtime_state_report.json")
        rep.print_summary("validate-runtime-state")
        print("[validate-runtime-state] FAIL — result descriptor missing or unparseable")
        sys.exit(rep.exit_code)

    rep.check("registry_owns_run", run_id in registry,
              "not found in worldforge_scenario_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

    scenario_id = descriptor.get("scenario_id", "")
    before = descriptor.get("before_state", {})
    after = descriptor.get("after_state", {})
    deltas = descriptor.get("deltas_applied", {})
    thresholds = descriptor.get("thresholds", {})
    state_min = float(thresholds.get("state_min", 0.0))
    state_max = float(thresholds.get("state_max", 1.0))
    max_delta = float(thresholds.get("max_delta_per_key", 1.0))

    # -- Target map resolves ------------------------------------------------
    context_id = descriptor.get("context_id", "")
    rep.check("target_map_resolved", bool(descriptor.get("target")) and bool(context_id),
              "target='{}' context_id='{}'".format(descriptor.get("target"), context_id),
              code=FailureCode.TARGET_MAP_UNRESOLVED)

    # -- Independently re-derive scenario expectations ----------------------
    scenario_path = REPO_ROOT / "procedural" / "definitions" / "scenarios" / (scenario_id + ".yaml")
    scenario = None
    if rep.check("scenario_definition_exists", scenario_path.is_file(),
                 str(scenario_path.relative_to(REPO_ROOT)),
                 code=FailureCode.RECIPE_MISSING):
        try:
            with scenario_path.open("r", encoding="utf-8") as fh:
                scenario = yaml.safe_load(fh)
            rep.check("scenario_definition_parses", True)
        except Exception as exc:
            rep.check("scenario_definition_parses", False, str(exc),
                      code=FailureCode.SCENARIO_UNPARSEABLE)
    scenario = scenario or {}
    declared_deltas = {k: float(v) for k, v in scenario.get("state_deltas", {}).items()}
    mutated_keys = sorted(declared_deltas)

    # -- Initial state read -------------------------------------------------
    rep.check("initial_state_read", bool(before),
              "before_state empty — no initial state was read")

    # -- State mutation (re-derived from the scenario's OWN deltas) ---------
    # Data-driven: the asserted keys ARE whatever the scenario's state_deltas
    # declares. Nothing here is hard-coded to industrial_pressure.
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
        else:
            mutation_detail.append("{}: {} -> {} == clamp({} + {})".format(k, b, a, b, d))
        if abs(a - b) > _EPS:
            changed_any = True
    rep.check("state_mutation_applied", mutation_ok and bool(declared_deltas),
              "scenario keys {}: {}".format(
                  mutated_keys, "; ".join(mutation_detail) or "no state_deltas declared"),
              code=FailureCode.STATE_MUTATION_MISMATCH)
    rep.check("state_actually_changed", changed_any,
              "no state key changed value — scenario had no effect")

    # -- Bounds (state delta is bounded) ------------------------------------
    oob = [(k, v) for k, v in after.items() if v < state_min - _EPS or v > state_max + _EPS]
    rep.check("state_within_bounds", not oob,
              "out-of-bounds [{},{}]: {}".format(state_min, state_max, oob),
              code=FailureCode.STATE_DELTA_UNBOUNDED)
    big = [(k, d) for k, d in deltas.items() if abs(d) > max_delta + _EPS]
    rep.check("deltas_within_budget", not big,
              "deltas exceeding max_delta_per_key={}: {}".format(max_delta, big),
              code=FailureCode.STATE_DELTA_UNBOUNDED)

    # -- Aggregation --------------------------------------------------------
    agg = descriptor.get("aggregate", {})
    agg_ok = bool(agg) and agg.get("keys") == descriptor.get("state_keys")
    if agg_ok and after:
        vals = [after[k] for k in agg["keys"] if k in after]
        if vals:
            expect_mean = round(sum(vals) / len(vals), 6)
            agg_ok = abs(float(agg.get("mean", -1)) - expect_mean) < 1e-4
    rep.check("state_aggregated", agg_ok,
              "aggregate block present and consistent with after_state",
              code=FailureCode.AGGREGATE_INCONSISTENT)

    # -- MPC bridge expectation (expected scalar == simulated post-state) ---
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
    rep.check("mpc_bridge_expectation", mpc_ok and bool(expected_mpc),
              "; ".join(mpc_detail) or "curated keys map to MPC params with post-state values",
              code=FailureCode.MPC_VALUE_MISMATCH)

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
    rep.check("poi_state_evidence_updated", poi_ok and bool(poi_ev),
              "; ".join(poi_detail) or "POI evidence present and driven by post-state",
              code=FailureCode.POI_EVIDENCE_MISSING)

    # -- Save / load restoration -------------------------------------------
    sl = descriptor.get("save_load", {})
    save_path = REPO_ROOT / sl.get("save_path", "")
    rep.check("state_save_file_exists", bool(sl.get("save_path")) and save_path.is_file(),
              str(sl.get("save_path", "")),
              code=FailureCode.SAVE_LOAD_ROUNDTRIP_FAILED)
    restored = sl.get("restored_state", {})
    saved = sl.get("saved_state", {})
    persisted_after = {k: after[k] for k in sl.get("persist_keys", []) if k in after}
    rep.check("save_load_roundtrip", bool(sl.get("roundtrip_ok")) and restored == saved,
              "restored_state must equal saved_state",
              code=FailureCode.SAVE_LOAD_ROUNDTRIP_FAILED)
    rep.check("save_load_restores_poststate", restored == persisted_after,
              "restored persisted keys must equal post-scenario state",
              code=FailureCode.SAVE_LOAD_ROUNDTRIP_FAILED)

    # -- Provenance ---------------------------------------------------------
    rep.check("provenance_exists", bool(descriptor.get("provenance")),
              "provenance block absent from result descriptor",
              code=FailureCode.PROVENANCE_MISSING)

    # -- Post-scenario map validity (verified from the per-slice UE report) --
    # A scenario's own biome may be biome-agnostic ("any"), so the per-slice UE report
    # lives under the SLICE's materialization biome, not the scenario's. Try the
    # scenario-biome path first (desert path unchanged), then fall back to locating the
    # report by slice name across the biome report dirs.
    slices_root = REPO_ROOT / "procedural" / "reports" / "slices"
    slice_report = slices_root / descriptor.get("biome", "desert") / args.name / "validate_slice_report.json"
    if not slice_report.is_file():
        for cand in slices_root.glob("*/{}/validate_slice_report.json".format(args.name)):
            slice_report = cand
            break
    map_ok = False
    if slice_report.is_file():
        try:
            map_ok = bool(json.loads(slice_report.read_text(encoding="utf-8")).get("passed"))
        except Exception:
            map_ok = False
    rep.ue_check("post_scenario_map_valid", map_ok,
              "validate-slice PASS for {}".format(args.name) if map_ok else
              "run 'make validate-slice' for {} to confirm post-scenario map validity".format(
                  args.name),
              code=FailureCode.UE_ARTIFACT_MISSING)

    # -- In-editor MPC bridge readback: an optional native-owner cross-check.
    #    Editor Python reports native-authority-required rather than forging this
    #    mutation. A missing report remains non-blocking because the authoring-side
    #    scenario validation already proves the state logic.
    ue_report = report_dir / "ue_state_scenario_report.json"
    if ue_report.is_file():
        try:
            ue_rpt = json.loads(ue_report.read_text(encoding="utf-8"))
            ue_ok, ue_detail = validate_native_authority_evidence(ue_rpt, descriptor)
        except Exception:
            ue_ok, ue_detail = False, "ue_state_scenario_report.json unreadable"
        rep.ue_check("ue_state_applied", ue_ok, ue_detail,
                  code=FailureCode.UE_STATE_NOT_APPLIED)
    else:
        rep.skip("ue_state_applied",
                 "in-editor MPC bridge readback not run here; a native state owner must produce it")

    # -- Finalize + write ---------------------------------------------------
    rep.finalize()
    rep.write(report_dir, "validate_runtime_state_report.json")
    rep.print_summary("validate-runtime-state")

    # Legible before/after summary (preserves the v0.8 console UX).
    for k in descriptor.get("state_keys", []):
        print("[validate-runtime-state]   {}: {} -> {}".format(k, before.get(k), after.get(k)))
    print("[validate-runtime-state]   scenario={} mutated_keys={} affected_poi={} save_load={}".format(
        scenario_id, mutated_keys, list(poi_ev.keys()),
        "OK" if sl.get("roundtrip_ok") else "FAIL"))

    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
