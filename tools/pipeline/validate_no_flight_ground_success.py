#!/usr/bin/env python3
"""validate_no_flight_ground_success.py — WorldForge v1.6y false-success detector.

The always-on guarantee that flight and teleport can never launder into grounded
success. It scans every grounded completion report (plus any stale v1.6x flight
report that leaked into the ground dir) and FAILS if any report claims grounded
success while:
  * flight_used is true, or
  * teleport_used is true, or
  * actual_traversal_mode is continuous_flight / teleport_diagnostic / failed, or
  * the report is a v1.6x flight completion (completion_class=completed_runtime)
    masquerading in the ground results.

--self-test injects a flight-as-grounded-success report and proves this validator
rejects it (exit 1), so the detector itself is verified.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_completion_contract as GC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

SKIP = {"ground_rollup.json", "run_ground_runtime_batch_gate_report.json",
        "validate_ground_completion_report.json", "validate_no_flight_ground_success_report.json"}


def load_reports():
    d = REPO_ROOT / GC.COMPLETION_REPORTS_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            if p.name not in SKIP:
                out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def audit(sid, r, rep):
    C = FailureCode
    claims_success = (r.get("completion_class") == GC.SUCCESS_CLASS) or bool(r.get("grounded_success"))
    # A v1.6x flight report (completed_runtime) has no business claiming grounded.
    if r.get("completion_class") == "completed_runtime":
        rep.check("{}::not_v1_6x_flight_report".format(sid), False,
                  "v1.6x flight completion report present in ground results",
                  code=C.GROUND_REPORT_STALE)
        return
    if not claims_success:
        return
    rep.check("{}::no_flight_used".format(sid), r.get("flight_used") is not True,
              "grounded success with flight_used=true", code=C.GROUND_FLIGHT_COUNTED_AS_SUCCESS)
    rep.check("{}::no_teleport_used".format(sid), r.get("teleport_used") is not True,
              "grounded success with teleport_used=true", code=C.GROUND_TELEPORT_COUNTED_AS_SUCCESS)
    rep.check("{}::mode_is_grounded".format(sid),
              r.get("actual_traversal_mode") in GC.GROUNDED_SUCCESS_MODES,
              "grounded success actual_traversal_mode={!r}".format(r.get("actual_traversal_mode")),
              code=C.GROUND_TRAVERSAL_MODE_FORBIDDEN)


def run(strict, pack, extra_reports=None):
    rep = ValidationReport("pack", pack, strict=strict)
    reports = dict(load_reports())
    if extra_reports:
        reports.update(extra_reports)
    for sid, r in reports.items():
        audit(sid, r, rep)
    rep.check("no_flight_detector_ran", True,
              "audited {} grounded reports for flight/teleport false-success".format(len(reports)),
              code=FailureCode.GROUND_FLIGHT_COUNTED_AS_SUCCESS)
    rep.finalize()
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--self-test", action="store_true",
                    help="inject a flight-as-grounded-success report; expect rejection")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    if args.self_test:
        bad = {"_inj_flight": {
            "completion_class": GC.SUCCESS_CLASS, "grounded_success": True, "flight_used": True,
            "teleport_used": False, "actual_traversal_mode": "continuous_flight"}}
        rep = run(True, args.pack, extra_reports=bad)
        if rep.exit_code == 0:
            print("[no-flight-ground-success][self-test] FAIL: injected flight success NOT rejected")
            sys.exit(1)
        print("[no-flight-ground-success][self-test] OK: injected flight-as-grounded-success rejected")
        sys.exit(0)

    rep = run(strict, args.pack)
    rep.set_meta(build_meta(command="validate-no-flight-ground-success", pack=args.pack,
                            strict=strict, status=rep.status, record_count=0,
                            report_type="wf.ground.completion_report.v1"))
    rep.write(REPO_ROOT / GC.COMPLETION_REPORTS_REL, "validate_no_flight_ground_success_report.json")
    rep.print_summary("validate-no-flight-ground-success")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
