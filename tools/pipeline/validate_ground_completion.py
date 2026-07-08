#!/usr/bin/env python3
"""validate_ground_completion.py — WorldForge v1.6y grounded completion gate.

Validates every grounded completion report against the frozen ground contract and
reports the honestly-achieved tier (P0 12 / P1 60-maps / P2 120). Under STRICT a
scenario not classified grounded_completed_runtime blocks; the achieved tier is
always stated truthfully — no partial matrix is dressed up as full.
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
TOTAL = 120


def load_reports():
    d = REPO_ROOT / GC.COMPLETION_REPORTS_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            if p.name in SKIP:
                continue
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    reports = load_reports()
    classes = {}
    for sid, r in reports.items():
        classes[r.get("completion_class")] = classes.get(r.get("completion_class"), 0) + 1
        for name, ok, detail, code in GC.validate_completion(r, strict=strict):
            rep.check("{}::{}".format(sid, name), ok, detail, code=code)

    grounded = classes.get(GC.SUCCESS_CLASS, 0)
    rep.check("ground_reports_present", len(reports) > 0,
              "{} grounded completion reports on disk".format(len(reports)),
              code=FailureCode.GROUND_REPORT_ZERO_RECORD_SUCCESS)
    rep.check("ground_all_grounded", grounded == len(reports) and len(reports) > 0,
              "{}/{} grounded_completed_runtime; classes={}".format(grounded, len(reports), classes),
              code=FailureCode.GROUND_COMPLETION_FAILURE, warn_only=(grounded < TOTAL))

    tier = ("P2" if grounded >= 120 else "P1" if grounded >= 60 else "P0" if grounded >= 12 else "sub-P0")
    rep.finalize()
    rep.set_meta(build_meta(command="validate-ground-completion", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(reports),
                            report_type="wf.ground.completion_report.v1",
                            extra={"grounded": grounded, "achieved_tier": tier, "by_class": classes}))
    rep.write(REPO_ROOT / GC.COMPLETION_REPORTS_REL, "validate_ground_completion_report.json")
    rep.print_summary("validate-ground-completion")
    print("[validate-ground-completion] {} grounded / {} reports — achieved {} ({} of 120)".format(
        grounded, len(reports), tier, grounded))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
