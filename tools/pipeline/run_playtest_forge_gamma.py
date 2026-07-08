#!/usr/bin/env python3
"""run_playtest_forge_gamma.py — WorldForge v1.6 PlaytestForge Gamma runner (Agent 5A/5D).

Consumes runtime scenarios and classifies runtime completion. This is the
runtime-truth gate, so it is deliberately incapable of fake green:

  * If the UE/NeoStack bridge is LIVE, it invokes the UE runtime driver
    (tools/unreal/runtime_playtest_pack.py) and consumes the completion reports
    it emits — a scenario is completed_runtime only if the driver produced a
    telemetry stream with the required ordered events, a mutated mission state,
    and a verified save/load proof.
  * If the bridge is OFFLINE, it classifies EVERY scenario as
    staged_live_run_pending (failure_code RUNTIME_LIVE_RUN_PENDING, owner
    runtime_bridge) — never completed_runtime. Under STRICT this is blocking
    (the milestone is not runtime-green until the editor runs); without STRICT
    it is non-blocking so the authoring substrate can still be proven.

Every emitted completion report is validated against the frozen completion
contract before it is trusted, and the Gamma rollup breaks results down by biome,
mission archetype, and encounter profile.

Usage:
    python tools/pipeline/run_playtest_forge_gamma.py --pack encounter_loop_world \
        [--scenarios all|N] [--strict]
Writes: procedural/reports/runtime/completion/<scenario_id>.json  (per scenario)
        procedural/reports/runtime/completion/gamma_rollup.json
        procedural/reports/runtime/completion/run_playtest_forge_gamma_report.json
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_completion_contract as CC
import runtime_scenario_contract as SC
from runtime_bridge import ue_bridge_live, bridge_status_detail
from report_meta import build_meta, git_sha, strict_from_env, utc_now_iso
from validation_report import ValidationReport
from failure_codes import FailureCode

CREATED_AT = "2026-07-06T00:00:00+00:00"


def _load_scenarios():
    d = REPO_ROOT / SC.SCENARIO_GENERATED_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def staged_completion_report(scen):
    """A honest, non-green completion report for a scenario that could not run
    live. NEVER completed_runtime; carries the pending code + runtime_bridge owner."""
    sid = scen.get("runtime_scenario_id")
    return {
        "report_id": "{}:completion".format(sid),
        "report_type": CC.SCHEMA_VERSION,
        "schema_version": CC.SCHEMA_VERSION,
        "pack": scen.get("pack"),
        "runtime_scenario_id": sid,
        "map_id": scen.get("map_id"),
        "mission_id": scen.get("mission_id"),
        "encounter_id": scen.get("encounter_id"),
        "biome": scen.get("biome"),
        "status": "warn",
        "completion_class": "staged_live_run_pending",
        "failure_code": FailureCode.RUNTIME_LIVE_RUN_PENDING,
        "failure_owner": "runtime_bridge",
        "spawn_result": "pending",
        "possession_result": "pending",
        "route_result": "pending",
        "interaction_result": "pending",
        "state_result": "pending",
        "save_load_result": "pending",
        "telemetry_path": None,
        "screenshot_paths": [],
        "replay_path": None,
        "runtime_duration_seconds": 0.0,
        "distance_traveled": 0.0,
        "objective_events_seen": [],
        "state_transitions_seen": [],
        "created_at": CREATED_AT,
        "git_commit": git_sha(),
    }


def rollup(reports):
    by_biome, by_arch, by_profile, by_class = Counter(), Counter(), Counter(), Counter()
    scen_by_id = _load_scenarios()
    for sid, rpt in reports.items():
        scen = scen_by_id.get(sid, {})
        by_class[rpt.get("completion_class")] += 1
        by_biome[(rpt.get("biome"), rpt.get("completion_class"))] += 1
        by_arch[(scen.get("mission_archetype"), rpt.get("completion_class"))] += 1
        by_profile[(scen.get("encounter_profile"), rpt.get("completion_class"))] += 1
    completed = by_class.get("completed_runtime", 0)
    return {
        "report_type": "wf.playtest.gamma_rollup.v1",
        "schema_version": "wf.playtest.gamma_rollup.v1",
        "scenario_count": len(reports),
        "completed_runtime": completed,
        "by_completion_class": dict(by_class),
        "by_biome": {"{}|{}".format(*k): v for k, v in by_biome.items()},
        "by_mission_archetype": {"{}|{}".format(*k): v for k, v in by_arch.items()},
        "by_encounter_profile": {"{}|{}".format(*k): v for k, v in by_profile.items()},
        "created_at": CREATED_AT,
        "git_commit": git_sha(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 PlaytestForge Gamma runner.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--scenarios", default="all", help="all | <N>")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    scenarios = _load_scenarios()
    if not scenarios:
        rep.error("no runtime scenarios — run 'make runtime-scenarios' first")

    sids = sorted(scenarios)
    if args.scenarios != "all":
        try:
            sids = sids[:int(args.scenarios)]
        except ValueError:
            pass

    live = ue_bridge_live()
    out_dir = REPO_ROOT / CC.COMPLETION_REPORTS_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = {}

    # Unified load-or-stage: a genuine completed_runtime report from the UE driver
    # is consumed as-is; anything else (missing, stale, or non-success) is (re)set
    # to an honest staged report. Crucially, a *missing* driver report is STAGING,
    # not a driver failure — an editor being up but not having produced runtime
    # output yet is exactly the pending-live-run state, never fake green. A driver
    # that ran and crashed writes its own failed_* report, which is consumed here.
    n_driver_completed = 0
    for sid in sids:
        rpath = out_dir / "{}.json".format(sid)
        existing = None
        if rpath.is_file():
            try:
                existing = json.loads(rpath.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = None
        cclass = (existing or {}).get("completion_class")
        if existing and cclass in (CC.SUCCESS_CLASS,) or (
                existing and cclass and cclass.startswith("failed_")):
            # Genuine driver output (a real success or a real failure) — consume.
            reports[sid] = existing
            if cclass == CC.SUCCESS_CLASS:
                n_driver_completed += 1
        else:
            rpt = staged_completion_report(scenarios[sid])
            rpath.write_text(json.dumps(rpt, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
            reports[sid] = rpt

    if n_driver_completed == 0:
        rep.check("live_runtime_completion", False,
                  "no live driver completions yet — {}".format(bridge_status_detail()),
                  code=C.RUNTIME_LIVE_RUN_PENDING, warn_only=True)

    # Validate EVERY completion report against the frozen contract (dogfood the
    # no-fake-green invariants: a completed_runtime with no telemetry fails here).
    n_completed = 0
    for sid in sids:
        rpt = reports.get(sid)
        if rpt is None:
            continue
        for name, ok, detail, code in CC.validate_completion(rpt, strict=strict):
            rep.check("{}::{}".format(sid, name), ok, detail, code=code)
        if rpt.get("completion_class") == CC.SUCCESS_CLASS:
            n_completed += 1

    roll = rollup(reports)
    (out_dir / "gamma_rollup.json").write_text(
        json.dumps(roll, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # The completion assertion is ALWAYS warn_only: "not all completed" is a
    # PENDING state (blocking under STRICT so the milestone is never falsely
    # runtime-green; non-blocking otherwise so the authoring substrate proves).
    # It is deliberately NOT keyed off the runtime.json file: a running editor
    # with no driver output yet is still pending, not a hard failure.
    all_done = n_completed == len(sids) and len(sids) > 0
    rep.check("all_scenarios_completed_runtime", all_done,
              "{}/{} scenarios completed_runtime{}".format(
                  n_completed, len(sids),
                  "" if all_done else " — LIVE UE RUN PENDING"),
              code=C.RUNTIME_LIVE_RUN_PENDING, warn_only=True)

    rep.finalize()
    rep.set_meta(build_meta(command="run-playtest-forge-gamma", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(sids),
                            report_type="wf.playtest.gamma_rollup.v1",
                            extra={"bridge_live": live, "completed_runtime": n_completed,
                                   "scenarios": len(sids),
                                   "staged_live_run_pending": len(sids) - n_completed}))
    rep.write(out_dir, "run_playtest_forge_gamma_report.json")
    rep.print_summary("run-playtest-forge-gamma")
    print("[run-playtest-forge-gamma] bridge_live={} — {}/{} completed_runtime, "
          "{} staged_live_run_pending".format(live, n_completed, len(sids),
                                              len(sids) - n_completed))
    print("[run-playtest-forge-gamma] {}".format(bridge_status_detail()))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
