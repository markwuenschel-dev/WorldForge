#!/usr/bin/env python3
"""run_balance_forge.py — WorldForge v1.4 BalanceForge Alpha harness (Lane F).

Classifies every generated encounter against the canonical pressure/pacing
model (brief §15): recomputes the pressure components and difficulty band from
encounter_contract, scores pacing against the SAME thresholds as
validate_encounter_pacing, derives risk/hazard/cover/reward scores, and writes
one balance report per encounter plus a run-level report.

Balance never overrides validators — it CLASSIFIES. Any disagreement (band
invalid/extreme, over budget, band/profile mismatch, stored band that lies, or
an encounter no resolution path can complete) fails the run loudly with
ENCOUNTER_BALANCE_FAILURE. Valid encounters are stamped balance_status
"classified" in the encounter catalog.

completion_confidence: 1.0 when a beta playtest report proves completion,
0.5 when the abstract state simulation resolves (beta not yet run), else 0.0.

Usage:
    python tools/pipeline/run_balance_forge.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/balance/<encounter_id>.json  (per encounter)
        procedural/reports/encounters/run_balance_forge/run_balance_forge_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog, save_encounter_catalog
from report_meta import build_meta, git_sha, strict_from_env, utc_now_iso
from validation_report import ValidationReport
from failure_codes import FailureCode
from validate_encounter_pacing import pacing_check_results

BALANCE_SCHEMA_VERSION = "wf.balance.v1"


def _state_math():
    """Prefer playtest_beta_contract's state math when present; fall back to the
    canonical v1.3 playtest_contract simple initial+delta resolution."""
    try:
        import playtest_beta_contract as PBC
        if all(hasattr(PBC, f) for f in ("simulate_state", "completion_resolves",
                                         "failure_fires")):
            return PBC
    except ImportError:
        pass
    import playtest_contract as PC
    return PC


STATE = _state_math()


def _clamp01(x):
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def state_resolution_completes(enc):
    """True iff applying every state key's delta resolves completion without
    tripping a failure condition (the 0.5-confidence path)."""
    final = STATE.simulate_state(enc)
    return STATE.completion_resolves(enc, final) and not STATE.failure_fires(enc, final)


def completion_confidence(eid, enc):
    """1.0 = beta playtest proved completion; 0.5 = state simulation resolves;
    0.0 = nothing can complete this encounter."""
    beta_path = REPO_ROOT / EC.PLAYTEST_BETA_REPORTS_REL / "{}.json".format(eid)
    if beta_path.is_file():
        try:
            beta = json.loads(beta_path.read_text(encoding="utf-8"))
            if beta.get("completed") is True:
                return 1.0
        except Exception:  # noqa: BLE001 — unparseable beta report is not proof
            pass
    if state_resolution_completes(enc):
        return 0.5
    return 0.0


def resource_reward_score(enc):
    """1.0 iff reward hooks are well-formed AND the encounter's declared state
    keys are persisted through the save/load contract; else 0.0."""
    hooks = enc.get("reward_hooks") or []
    hooks_ok = bool(hooks) and all(
        isinstance(h, dict) and all(k in h for k in EC.REWARD_HOOK_REQUIRED)
        for h in hooks)
    slc = enc.get("save_load_contract") or {}
    persist = slc.get("persist_keys") or []
    declared = [s.get("key") for s in enc.get("state_keys") or [] if isinstance(s, dict)]
    persisted = (slc.get("expect_roundtrip") is True and bool(declared)
                 and all(k in persist for k in declared))
    return 1.0 if (hooks_ok and persisted) else 0.0


def balance_encounter(eid, enc, mission):
    """Compute one encounter's balance classification. Pure — no I/O."""
    comps = EC.pressure_components(enc, mission)
    total = EC.total_pressure(comps)
    band = EC.classify_band(total)
    profile = enc.get("encounter_profile")
    budget = EC.PROFILE_PRESSURE_BUDGETS.get(profile)

    invalid_reason = None
    if band == "invalid":
        invalid_reason = "pressure_band_invalid: total {} outside [0, {}]".format(
            total, EC.INVALID_PRESSURE_ABOVE)
    elif band == "extreme":
        invalid_reason = "pressure_band_extreme: total {} classifies extreme".format(total)
    elif budget is None or total > budget:
        invalid_reason = "over_pressure_budget: total {} > budget {} (profile {!r})".format(
            total, budget, profile)
    elif band not in EC.PROFILE_BAND_TARGETS.get(profile, ()):
        invalid_reason = "band_profile_mismatch: band {!r} not in {} for profile {!r}".format(
            band, EC.PROFILE_BAND_TARGETS.get(profile, ()), profile)

    pacing = pacing_check_results(enc, mission)
    pacing_score = round(sum(1 for _, ok, _ in pacing if ok) / len(pacing), 4) \
        if pacing else 0.0
    metrics = EC.pacing_metrics(enc, mission)

    report = {
        "encounter_id": eid,
        "mission_id": enc.get("mission_id"),
        "biome_family": enc.get("biome_family"),
        "encounter_archetype": enc.get("encounter_archetype"),
        "encounter_profile": profile,
        "schema_version": BALANCE_SCHEMA_VERSION,
        "difficulty_band": "invalid" if invalid_reason else band,
        "pressure_score": total,
        "pressure_components": comps,
        "pacing_score": pacing_score,
        "route_risk_score": round(_clamp01(comps.get("route_pressure", 0.0) / 10.0), 4),
        "hazard_score": round(_clamp01(comps.get("hazard_pressure", 0.0) / 10.0), 4),
        "cover_score": round(_clamp01(metrics.get("cover_density_near_pressure") or 0.0), 4),
        "resource_reward_score": resource_reward_score(enc),
        "completion_confidence": completion_confidence(eid, enc),
        "invalid_reason": invalid_reason,
        "git_sha": git_sha(),
        "timestamp": utc_now_iso(),
    }
    return report, band


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.4 BalanceForge Alpha harness.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    encounters = catalog.get("encounters") or {}
    eids = sorted(encounters.keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")

    code = FailureCode.ENCOUNTER_BALANCE_FAILURE
    out_dir = REPO_ROOT / EC.BALANCE_REPORTS_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    n_classified = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err, code=code)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id"))
        if mission is None:
            rep.check("{}::mission_loads".format(eid), False, merr, code=code)
            continue

        report, recomputed_band = balance_encounter(eid, enc, mission)
        out = out_dir / "{}.json".format(eid)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

        # Balance classifies; it never overrides. Disagreements fail loudly.
        valid = rep.check("{}::classified_valid".format(eid),
                          report["invalid_reason"] is None,
                          "invalid: {}".format(report["invalid_reason"]), code=code)
        agrees = rep.check("{}::stored_band_agrees".format(eid),
                           recomputed_band == enc.get("difficulty_band"),
                           "recomputed band {!r} != stored difficulty_band {!r}".format(
                               recomputed_band, enc.get("difficulty_band")), code=code)
        confident = rep.check("{}::completable".format(eid),
                              report["completion_confidence"] > 0.0,
                              "completion_confidence 0.0 — no resolution path completes",
                              code=code)
        if valid and agrees and confident:
            n_classified += 1
            if eid in encounters:
                encounters[eid]["balance_status"] = "classified"

    save_encounter_catalog(REPO_ROOT, catalog)
    rep.finalize()
    rep.set_meta(build_meta(command="run-balance-forge", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(eids),
                            extra={"encounters_classified": n_classified,
                                   "encounters_total": len(eids)}))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "run_balance_forge",
              "run_balance_forge_report.json")
    rep.print_summary("run-balance-forge")
    print("[run-balance-forge] {}/{} encounters classified by BalanceForge".format(
        n_classified, len(eids)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
