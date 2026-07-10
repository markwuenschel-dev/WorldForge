#!/usr/bin/env python3
"""validate_slice_traversal.py — v2.0 Agent-3 grounded traversal gate.

Proves every slice scenario completed grounded traversal at runtime: each
SliceRuntimeReport has traversal_completed == true with a real telemetry path.
Truth remains grounded_manual_waypoint / grounded_worldforge_route — no native UE
navmesh dependency. Fail-closed RED until Wave R produces the runtime evidence.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_traversal.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/runtime/validate_slice_traversal_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
import slice_evidence as SE
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / SX.SLICE_RUNTIME_REPORTS_REL


def _facet(doc):
    tp = doc.get("telemetry_paths")
    has_tel = isinstance(tp, list) and any(SE.telemetry_path_exists(x) for x in tp)
    ok = doc.get("traversal_completed") is True and doc.get("player_spawned") is True and has_tel
    return ok, "traversal_completed + player_spawned + a real telemetry path required"


def _dogfood(rep):
    good = SX._example_slice_runtime_report(
        telemetry_paths=["procedural/generated/slice/manifest.json"])  # a real file
    rep.check("dogfood::good_passes", _facet(good)[0], "reference traversal report failed",
              code=F.SLICE_REPORT_INTEGRITY_FAILED)
    bad = SX._example_slice_runtime_report(traversal_completed=False)
    rep.check("dogfood::rejects_no_traversal", not _facet(bad)[0],
              "a report with traversal_completed=false must fail", code=F.SLICE_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice traversal gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)
    passed = SE.facet_gate(rep, _facet, SE.EXPECTED_SCENARIOS,
                           F.SLICE_TRAVERSAL_MISSING, F.SLICE_PARTIAL_MATRIX)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-traversal", pack=args.pack, strict=strict,
                            status=rep.status, record_count=passed,
                            records_total=SE.EXPECTED_SCENARIOS, records_passed=passed,
                            report_type="wf.slice.traversal.v1"))
    rep.write(REPORT_DIR, "validate_slice_traversal_report.json")
    rep.print_summary("validate-slice-traversal")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
