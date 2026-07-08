#!/usr/bin/env python3
"""validate_playtest_gamma_no_fake_green.py — WorldForge v1.6 false-success detector (Agent 5C).

The load-bearing anti-fake-green gate. It scans every completion report and HARD
FAILS any report that claims completed_runtime without the evidence a real run
must carry:

    * no telemetry stream
    * no objective event seen
    * no state transition seen
    * save/load not passed
    * a non-runtime report_type (a graph-only report laundered as runtime)
    * teleport used for success (any recovery/teleport marker on a success)

Because it only fails on FALSE successes, an all-staged offline run PASSES this
gate (there are zero completed_runtime to be false) — this gate exists to catch a
bad LIVE run, and it is always on. This is the gate the brief's "reject graph-only
/ teleport / no telemetry / empty / stale / partial" list maps to.

Usage:
    python tools/pipeline/validate_playtest_gamma_no_fake_green.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/completion/validate_playtest_gamma_no_fake_green_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_completion_contract as CC
from validate_runtime_completion import load_completion_reports, n_scenarios
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

RUNTIME_REPORT_TYPES = {CC.SCHEMA_VERSION, "wf.runtime.completion_report.v1"}


def fake_green_reasons(rpt):
    """Return a list of reasons this report is a FALSE completed_runtime (empty
    if it is not claiming success, or is a legitimate success)."""
    if rpt.get("completion_class") != CC.SUCCESS_CLASS:
        return []
    reasons = []
    if rpt.get("report_type") not in RUNTIME_REPORT_TYPES:
        reasons.append("non-runtime report_type {!r} (graph-only laundered)".format(
            rpt.get("report_type")))
    if not rpt.get("telemetry_path"):
        reasons.append("no telemetry_path")
    if not (rpt.get("objective_events_seen") or []):
        reasons.append("no objective events seen")
    if not (rpt.get("state_transitions_seen") or []):
        reasons.append("no state transitions seen")
    if rpt.get("save_load_result") != "pass":
        reasons.append("save_load_result={!r} (not pass)".format(rpt.get("save_load_result")))
    if rpt.get("failure_code"):
        reasons.append("success carries failure_code {!r}".format(rpt.get("failure_code")))
    # teleport markers of any kind on a success are forbidden.
    blob = json.dumps(rpt).lower()
    if "teleport" in blob or "noclip" in blob:
        reasons.append("teleport/noclip marker present on a success")
    return reasons


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 Gamma false-success detector.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    reports = load_completion_reports()
    if not reports:
        rep.error("no completion reports — run 'make run-playtest-forge-gamma' first")

    n_success = 0
    for sid in sorted(reports):
        rpt = reports[sid]
        reasons = fake_green_reasons(rpt)
        rep.check("{}::not_fake_green".format(sid), not reasons,
                  "FAKE GREEN: {}".format("; ".join(reasons)) if reasons else "no false success",
                  code=C.PLAYTEST_GAMMA_FALSE_SUCCESS)
        if rpt.get("completion_class") == CC.SUCCESS_CLASS and not reasons:
            n_success += 1

    # A zero-record success set must not be reported as a pass silently — but an
    # all-staged offline batch is legitimately zero successes, so this is only a
    # note, never a fake-green fail.
    rep.check("report_set_non_empty", len(reports) > 0,
              "{} completion reports scanned".format(len(reports)),
              code=C.RUNTIME_REPORT_EMPTY)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-playtest-gamma-no-fake-green", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(reports),
                            report_type="wf.playtest.gamma_rollup.v1",
                            extra={"reports": len(reports), "legit_successes": n_success}))
    rep.write(REPO_ROOT / CC.COMPLETION_REPORTS_REL,
              "validate_playtest_gamma_no_fake_green_report.json")
    rep.print_summary("validate-playtest-gamma-no-fake-green")
    print("[validate-playtest-gamma-no-fake-green] {} reports, {} legit successes, "
          "0 false successes tolerated".format(len(reports), n_success))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
