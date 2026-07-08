#!/usr/bin/env python3
"""run_live_pie_batch.py — WorldForge v1.6 P1 checkpoint/resume batch controller.

The crash-safe authority for the P1 live-runtime batch. It does NOT drive the
editor (the agent drives PIE via NeoStack per scenario and records each proof with
record_live_playtest.py). Instead it is the resume/checkpoint brain:

  * done-ness is read from disk — a scenario is DONE only when its completion
    report is completed_runtime WITH a telemetry stream AND a verified save/load
    proof. So a PIE/editor crash mid-batch loses nothing: prior proofs on disk
    stay done, and --next returns the first still-incomplete scenario.
  * --status  : per-scenario done/pending + coverage-of-done.
  * --next    : prints "NEXT <sid> <map_id> <archetype>" or "ALL_DONE".
  * --gate    : exit 0 only if all 12 are genuinely done AND coverage is full;
                writes the P1 rollup (12/120 live, 108 staged framing).

Usage:
    python tools/pipeline/run_live_pie_batch.py --status
    python tools/pipeline/run_live_pie_batch.py --next
    python tools/pipeline/run_live_pie_batch.py --gate [--strict]
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import p1_scenarios as P1
import runtime_completion_contract as CC
import runtime_save_load_contract as SL
from report_meta import build_meta, git_sha
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / CC.COMPLETION_REPORTS_REL
SAVELOAD_DIR = REPO_ROOT / SL.SAVE_LOAD_REPORTS_REL
TOTAL_MATRIX = 120


def scenario_done(sid):
    """A scenario is DONE only with a genuine completed_runtime report + telemetry
    + a verified save/load proof on disk. Returns (done, reason)."""
    cpath = COMPLETION_DIR / "{}.json".format(sid)
    if not cpath.is_file():
        return False, "no completion report"
    try:
        rpt = json.loads(cpath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "unreadable completion: {}".format(e)
    if rpt.get("completion_class") != CC.SUCCESS_CLASS:
        return False, "class={}".format(rpt.get("completion_class"))
    if not rpt.get("telemetry_path"):
        return False, "no telemetry"
    spath = SAVELOAD_DIR / "{}.json".format(sid)
    if not spath.is_file():
        return False, "no save/load proof"
    try:
        proof = json.loads(spath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "unreadable proof: {}".format(e)
    if proof.get("status") != SL.VERIFIED:
        return False, "save/load status={}".format(proof.get("status"))
    return True, "completed_runtime + telemetry + verified save/load"


def status():
    recs = P1.resolve()
    done, pending = [], []
    for r in recs:
        ok, reason = scenario_done(r["scenario_id"])
        (done if ok else pending).append((r, reason))
    return recs, done, pending


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 P1 batch controller.")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    recs, done, pending = status()

    if args.next:
        if not pending:
            print("ALL_DONE")
            return
        r = pending[0][0]
        print("NEXT {} {} {}".format(r["scenario_id"], r["map_id"], r["archetype"]))
        return

    if args.gate:
        rep = ValidationReport("pack", "encounter_loop_world", strict=args.strict)
        done_recs = [r for r, _ in done]
        cov = P1.coverage(done_recs)
        rep.check("p1_all_12_complete", len(done) == 12,
                  "{}/12 P1 scenarios genuinely completed_runtime".format(len(done)),
                  code=FailureCode.RUNTIME_LIVE_RUN_PENDING, warn_only=(len(done) < 12))
        rep.check("p1_5_biomes", len(cov["biomes"]) == 5,
                  "biomes: {}".format(cov["biomes"]), code=FailureCode.RUNTIME_SCENARIO_COVERAGE_FAILURE,
                  warn_only=(len(done) < 12))
        rep.check("p1_6_archetypes", len(cov["archetypes"]) == 6,
                  "archetypes: {}".format(cov["archetypes"]),
                  code=FailureCode.RUNTIME_SCENARIO_COVERAGE_FAILURE, warn_only=(len(done) < 12))
        rep.check("p1_2_profiles", len(cov["profiles"]) == 2,
                  "profiles: {}".format(cov["profiles"]),
                  code=FailureCode.RUNTIME_SCENARIO_COVERAGE_FAILURE, warn_only=(len(done) < 12))
        rep.check("p1_2_seeds", len(cov["seeds"]) == 2,
                  "seeds: {}".format(cov["seeds"]),
                  code=FailureCode.RUNTIME_SCENARIO_COVERAGE_FAILURE, warn_only=(len(done) < 12))
        rollup = {
            "report_type": "wf.playtest.p1_rollup.v1",
            "framing": "v1.6 P1 representative live runtime completion",
            "live_completed_runtime": len(done),
            "staged_remaining": TOTAL_MATRIX - len(done),
            "matrix_total": TOTAL_MATRIX,
            "coverage_of_completed": cov,
            "completed_scenarios": [r["scenario_id"] for r in done_recs],
            "pending_scenarios": [r["scenario_id"] for r, _ in pending],
            "git_commit": git_sha(),
        }
        (COMPLETION_DIR / "p1_rollup.json").write_text(
            json.dumps(rollup, indent=2) + "\n", encoding="utf-8")
        rep.finalize()
        rep.set_meta(build_meta(command="p1-gate", pack="encounter_loop_world",
                                strict=args.strict, status=rep.status, record_count=len(recs),
                                report_type="wf.playtest.p1_rollup.v1",
                                extra={"live": len(done), "staged": TOTAL_MATRIX - len(done)}))
        rep.write(COMPLETION_DIR, "run_live_pie_batch_gate_report.json")
        rep.print_summary("p1-gate")
        print("[p1-gate] {}/12 P1 live-complete | {}/120 matrix live, {} staged".format(
            len(done), len(done), TOTAL_MATRIX - len(done)))
        sys.exit(rep.exit_code)

    # default: status
    print("=== v1.6 P1 batch status: {}/12 done ===".format(len(done)))
    for r in recs:
        ok, reason = scenario_done(r["scenario_id"])
        print("  [{}] {:02d} {:22s} {:16s} {:18s} — {}".format(
            "DONE" if ok else "TODO", r["seq"], r["biome"], r["archetype"],
            r["profile"], reason))
    print("--- {}/120 live, {} staged; next: {}".format(
        len(done), TOTAL_MATRIX - len(done),
        pending[0][0]["scenario_id"] if pending else "ALL_DONE"))


if __name__ == "__main__":
    main()
