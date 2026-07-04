#!/usr/bin/env python3
"""run_playtest_forge_beta.py — WorldForge v1.4 PlaytestForge Beta harness (Lane E).

Runs the automated beta playtest over every generated encounter (brief §14):
loads the encounter + its linked mission, runs the declared beta modes
(alpha reuse + encounter pressure/resolution/pacing/resource-reward), writes a
per-encounter beta report, and marks the encounter completed only if every
mode passes AND the host mission's alpha playtest still completes. The run
FAILS unless EVERY encounter completes — a generator that emits an unplayable
encounter is caught here, not by a human.

Usage:
    python tools/pipeline/run_playtest_forge_beta.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/playtest_beta/<encounter_id>.json  (per encounter)
        procedural/reports/encounters/run_playtest_forge_beta/run_playtest_forge_beta_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
import encounter_contract as EC
import playtest_beta_contract as PB
from encounter_catalog import load_encounter_catalog, save_encounter_catalog
from report_meta import build_meta, git_sha, strict_from_env, utc_now_iso
from validation_report import ValidationReport
from failure_codes import FailureCode

BETA_SCHEMA_VERSION = "wf.playtest_beta.v1"

# Per-mode failure codes (brief §14).
MODE_FAILURE_CODES = {
    "route_playtest": FailureCode.PLAYTEST_BETA_ROUTE_FAILURE,
    "anchor_playtest": FailureCode.PLAYTEST_BETA_ROUTE_FAILURE,
    "state_transition_playtest": FailureCode.PLAYTEST_BETA_COMPLETION_FAILURE,
    "save_load_playtest": FailureCode.PLAYTEST_BETA_SAVE_LOAD_FAILURE,
    "budget_safe_playtest": FailureCode.PLAYTEST_BETA_PRESSURE_FAILURE,
    "encounter_pressure_playtest": FailureCode.PLAYTEST_BETA_PRESSURE_FAILURE,
    "encounter_resolution_playtest": FailureCode.PLAYTEST_BETA_ENCOUNTER_RESOLUTION_FAILURE,
    "pacing_playtest": FailureCode.PLAYTEST_BETA_PRESSURE_FAILURE,
    "resource_reward_playtest": FailureCode.PLAYTEST_BETA_ENCOUNTER_RESOLUTION_FAILURE,
}


def playtest_encounter(eid, enc, mission):
    """Run all declared beta modes; write the per-encounter report; return
    (completed, results)."""
    results, completed = PB.run_beta_modes(enc, mission)
    comps = EC.pressure_components(enc, mission)
    total = EC.total_pressure(comps)
    report = {
        "encounter_id": eid,
        "mission_id": enc.get("mission_id"),
        "biome_family": enc.get("biome_family"),
        "mission_archetype": enc.get("mission_archetype"),
        "encounter_archetype": enc.get("encounter_archetype"),
        "encounter_profile": enc.get("encounter_profile"),
        "difficulty_band": enc.get("difficulty_band"),
        "schema_version": BETA_SCHEMA_VERSION,
        "completed": completed,
        "expected_completion": (enc.get("playtest_contract") or {}).get("expected_completion", True),
        "modes": results,
        "pressure": {
            "components": comps,
            "total": total,
            "band": EC.classify_band(total),
        },
        "pacing": EC.pacing_metrics(enc, mission),
        "final_state": PB.combined_final_state(enc, mission),
        "git_sha": git_sha(),
        "timestamp": utc_now_iso(),
    }
    out = REPO_ROOT / EC.PLAYTEST_BETA_REPORTS_REL / "{}.json".format(eid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return completed, results


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.4 PlaytestForge Beta harness.")
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

    n_completed = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err,
                      code=FailureCode.PLAYTEST_BETA_CONTRACT_FAILURE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        if mission is None:
            # An encounter without its host mission has no route to playtest.
            rep.check("{}::mission_loads".format(eid), False,
                      "linked mission {!r} missing: {}".format(enc.get("mission_id"), merr),
                      code=FailureCode.PLAYTEST_BETA_ROUTE_FAILURE)
            continue
        completed, results = playtest_encounter(eid, enc, mission)
        expected = (enc.get("playtest_contract") or {}).get("expected_completion", True)
        # Every declared mode must pass...
        for mode, r in results.items():
            code = MODE_FAILURE_CODES.get(mode, FailureCode.PLAYTEST_BETA_CONTRACT_FAILURE)
            rep.check("{}::{}".format(eid, mode), r["passed"], r["detail"], code=code)
        # ...and the encounter must complete as expected.
        rep.check("{}::completed".format(eid), completed == expected,
                  "completed={} expected={}".format(completed, expected),
                  code=FailureCode.PLAYTEST_BETA_COMPLETION_FAILURE)
        if completed:
            n_completed += 1
            if eid in encounters:
                encounters[eid]["playtest_beta_status"] = "completed"

    # The run fails unless EVERY encounter completes.
    rep.check("all_encounters_completed", n_completed == len(eids) and bool(eids),
              "{}/{} encounters completed — every encounter must complete".format(
                  n_completed, len(eids)),
              code=FailureCode.PLAYTEST_BETA_COMPLETION_FAILURE)

    save_encounter_catalog(REPO_ROOT, catalog)
    rep.finalize()
    rep.set_meta(build_meta(command="run-playtest-forge-beta", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(eids),
                            extra={"encounters_completed": n_completed,
                                   "encounters_total": len(eids)}))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "run_playtest_forge_beta",
              "run_playtest_forge_beta_report.json")
    rep.print_summary("run-playtest-forge-beta")
    print("[run-playtest-forge-beta] {}/{} encounters completed by the beta harness".format(
        n_completed, len(eids)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
