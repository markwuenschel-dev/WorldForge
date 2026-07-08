#!/usr/bin/env python3
"""ground_traversal_report_integrity.py — WorldForge v1.6z report-integrity gate.

Audits the on-disk ground artifacts as ENVELOPES, independent of the generators:
  * no grounded completion may claim success with flight/teleport used or a
    non-grounded actual_traversal_mode,
  * no v1.6x flight report (completion_class=completed_runtime) may live in the
    ground completion dir (stale-report laundering),
  * the ground rollup's grounded count must equal the real number of
    grounded_completed_runtime reports on disk (no partial matrix as full),
  * no walkability report may claim status=pass with zero surfaces checked,
  * every failure report must own a failure code.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_completion_contract as GC
import ground_contracts as GX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F

COMPLETION_DIR = REPO_ROOT / GC.COMPLETION_REPORTS_REL
WALK_DIR = REPO_ROOT / GX.WALKABILITY_REPORTS_REL
SKIP = ("ground_rollup", "run_ground_runtime_batch_gate_report", "validate_")


def _load(d):
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            if any(p.stem.startswith(s) or p.name.startswith(s) for s in SKIP):
                continue
            try:
                out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                out[p.stem] = {"__unreadable__": True}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    comp = _load(COMPLETION_DIR)
    grounded = 0
    for sid, r in comp.items():
        cls = r.get("completion_class")
        rep.check("integ::{}::not_stale_v1_6x".format(sid), cls != "completed_runtime",
                  "v1.6x flight report in ground completion dir", code=F.GROUND_REPORT_STALE)
        if cls == GC.SUCCESS_CLASS or r.get("grounded_success"):
            grounded += 1
            rep.check("integ::{}::no_flight".format(sid), r.get("flight_used") is not True,
                      "grounded success with flight_used", code=F.GROUND_FLIGHT_COUNTED_AS_SUCCESS)
            rep.check("integ::{}::no_teleport".format(sid), r.get("teleport_used") is not True,
                      "grounded success with teleport_used", code=F.GROUND_TELEPORT_COUNTED_AS_SUCCESS)
            rep.check("integ::{}::grounded_mode".format(sid),
                      r.get("actual_traversal_mode") in GC.GROUNDED_SUCCESS_MODES,
                      "grounded success non-grounded mode", code=F.GROUND_TRAVERSAL_MODE_FORBIDDEN)
            rep.check("integ::{}::has_telemetry".format(sid), bool(r.get("telemetry_path")),
                      "grounded success without telemetry", code=F.GROUND_REPORT_MISSING_TELEMETRY)
        elif cls in GC.COMPLETION_CLASSES:
            rep.check("integ::{}::failure_owns_code".format(sid),
                      isinstance(r.get("failure_codes"), list) and len(r["failure_codes"]) > 0,
                      "failure report without a code", code=F.GROUND_REPORT_INTEGRITY_FAILURE)

    # No partial matrix dressed as full.
    roll_p = COMPLETION_DIR / "ground_rollup.json"
    if roll_p.is_file():
        roll = json.loads(roll_p.read_text(encoding="utf-8"))
        claimed = roll.get("grounded_completed_runtime", -1)
        rep.check("integ::rollup_matches_disk", claimed == grounded,
                  "rollup claims {} grounded but {} on disk".format(claimed, grounded),
                  code=F.GROUND_REPORT_PARTIAL_MATRIX)

    walk = _load(WALK_DIR)
    for sid, r in walk.items():
        if r.get("status") == "pass":
            rep.check("integ::walk::{}::nonzero".format(sid),
                      isinstance(r.get("walkable_surfaces"), int) and r["walkable_surfaces"] > 0,
                      "walkability pass with zero walkable", code=F.GROUND_REPORT_ZERO_RECORD_SUCCESS)

    rep.check("integ::audited_something", (len(comp) + len(walk)) > 0,
              "audited {} completion + {} walkability envelopes".format(len(comp), len(walk)),
              code=F.GROUND_REPORT_INTEGRITY_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="ground-traversal-report-integrity", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(comp) + len(walk),
                            report_type="wf.ground.report_integrity.v1",
                            extra={"grounded_on_disk": grounded}))
    rep.write(REPO_ROOT / "procedural/reports/ground/integrity",
              "ground_traversal_report_integrity_report.json")
    rep.print_summary("ground-traversal-report-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
