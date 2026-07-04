#!/usr/bin/env python3
"""run_playtest_forge.py — WorldForge v1.3 PlaytestForge Alpha harness (Agent 5).

Runs the automated playtest over every generated mission and proves each one is
completable (brief §6). For each mission it runs the five modes (graph, anchor,
state_transition, save_load, budget_safe), writes a per-mission playtest report,
and marks the mission completed only if every mode passes AND the completion
condition resolves. The run FAILS if any mission cannot be completed — a
generator that emits an uncompletable mission is caught here, not by a human.

Usage:
    python tools/pipeline/run_playtest_forge.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/playtest/<mission_id>.json  (per mission)
        procedural/reports/missions/run_playtest_forge/run_playtest_forge_report.json
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
import playtest_contract as PC
from mission_catalog import load_mission_catalog, save_mission_catalog
from report_meta import build_meta, git_sha, strict_from_env, utc_now_iso
from validation_report import ValidationReport
from failure_codes import FailureCode


def playtest_mission(mid, m):
    """Run all declared modes; write the per-mission report; return (completed, results)."""
    modes = (m.get("playtest_contract") or {}).get("modes")
    results, completed = PC.run_modes(m, modes)
    report = {
        "mission_id": mid,
        "mission_archetype": m.get("mission_archetype"),
        "biome_family": m.get("biome_family"),
        "schema_version": "wf.playtest.v1",
        "completed": completed,
        "expected_completion": (m.get("playtest_contract") or {}).get("expected_completion", True),
        "modes": results,
        "final_state": PC.simulate_state(m),
        "git_sha": git_sha(),
        "timestamp": utc_now_iso(),
    }
    out = REPO_ROOT / PC.PLAYTEST_REPORTS_REL / "{}.json".format(mid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return completed, results


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.3 PlaytestForge Alpha harness.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_mission_catalog(REPO_ROOT)
    missions = catalog.get("missions") or {}
    mids = sorted(missions.keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")

    n_completed = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.PLAYTEST_CONTRACT_FAILURE)
            continue
        completed, results = playtest_mission(mid, m)
        expected = (m.get("playtest_contract") or {}).get("expected_completion", True)
        # Every declared mode must pass...
        for mode, r in results.items():
            code = {
                "anchor_playtest": FailureCode.PLAYTEST_ROUTE_FAILURE,
                "state_transition_playtest": FailureCode.PLAYTEST_STATE_TRANSITION_FAILURE,
                "save_load_playtest": FailureCode.PLAYTEST_SAVE_LOAD_FAILURE,
                "budget_safe_playtest": FailureCode.PLAYTEST_ACTION_FAILURE,
            }.get(mode, FailureCode.PLAYTEST_CONTRACT_FAILURE)
            rep.check("{}::{}".format(mid, mode), r["passed"], r["detail"], code=code)
        # ...and the mission must complete as expected.
        rep.check("{}::completed".format(mid), completed == expected,
                  "completed={} expected={}".format(completed, expected),
                  code=FailureCode.PLAYTEST_COMPLETION_FAILURE)
        if completed:
            n_completed += 1
            if mid in missions:
                missions[mid]["playtest_status"] = "completed"

    save_mission_catalog(REPO_ROOT, catalog)
    rep.finalize()
    rep.set_meta(build_meta(command="run-playtest-forge", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(mids),
                            extra={"missions_completed": n_completed, "missions_total": len(mids)}))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "run_playtest_forge",
              "run_playtest_forge_report.json")
    rep.print_summary("run-playtest-forge")
    print("[run-playtest-forge] {}/{} missions completed by the playtest harness".format(
        n_completed, len(mids)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
