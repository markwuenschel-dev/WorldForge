#!/usr/bin/env python3
"""streaming_operator_smoke.py — v2.3 Wave 5 operator broken-link/smoke gate.

Proves the OperatorForge streaming surface is coherent and every link resolves:
  * region_views.json + tile_views.json validate against their contracts
  * 2 region views + 6 tile views (full coverage)
  * every region_definition_path / lifecycle_report / ownership path referenced by a
    view resolves on disk (no broken evidence link)
  * every region/tile HTML page the dashboard should have rendered exists
  * every runtime report's operator_trace_paths now resolve to a rendered page
    (closes the loop: the runtime claimed an operator trace; it must exist)
  * a passing tile view links >= 1 real lifecycle report; no out-of-band code

FAIL-CLOSED: absent views/pages -> RED.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/streaming_operator_smoke.py --strict
Reports -> procedural/reports/operator/streaming_operator_smoke_report.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import streaming_contracts as SC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
REGIONS_OUT = REPO_ROOT / "procedural" / "reports" / "operator" / "regions"
TILES_OUT = REPO_ROOT / "procedural" / "reports" / "operator" / "tiles"
RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "runtime"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "operator"
_WF_CODE_RE = re.compile(r"^WF\d{3}_[A-Z0-9_]+$")


def validate(rep):
    rvp, tvp = INDEX_DIR / "region_views.json", INDEX_DIR / "tile_views.json"
    for p in (rvp, tvp):
        rep.check("smoke::{}_present".format(p.name), p.is_file(),
                  "{} missing".format(p.name), code=F.STREAMING_OPERATOR_VIEW_INVALID)
    if not (rvp.is_file() and tvp.is_file()):
        return 0
    region_views = json.loads(rvp.read_text(encoding="utf-8"))
    tile_views = json.loads(tvp.read_text(encoding="utf-8"))
    rep.check("smoke::2_region_views", len(region_views) == SC.EXPECTED_REGION_COUNT,
              "expected 2 region views (got {})".format(len(region_views)),
              code=F.STREAMING_PARTIAL_MATRIX)
    rep.check("smoke::6_tile_views", len(tile_views) == 6,
              "expected 6 tile views (got {})".format(len(tile_views)),
              code=F.STREAMING_OPERATOR_VIEW_INVALID)

    n = 0
    for rv in region_views:
        n += 1
        rid = rv["region_id"]
        fails = [c for c in SC.validate_operator_region_view(rv, strict=True) if not c[1]]
        rep.check("rv::{}::contract".format(rid), len(fails) == 0,
                  "region view invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_OPERATOR_VIEW_INVALID)
        rep.check("rv::{}::def_link".format(rid), (REPO_ROOT / rv["region_definition_path"]).is_file(),
                  "region definition link broken", code=F.STREAMING_OPERATOR_VIEW_INVALID)
        rep.check("rv::{}::page".format(rid), (REGIONS_OUT / "{}.html".format(rid)).is_file(),
                  "region page missing", code=F.STREAMING_OPERATOR_VIEW_INVALID)
        rep.check("rv::{}::codes_well_formed".format(rid),
                  all(_WF_CODE_RE.match(c) for c in rv["failure_codes"]),
                  "region view carries a malformed failure code", code=F.STREAMING_UNKNOWN_FAILURE_CODE)

    for tv in tile_views:
        tid = tv["tile_id"]
        fails = [c for c in SC.validate_operator_tile_view(tv, strict=True) if not c[1]]
        rep.check("tv::{}::contract".format(tid), len(fails) == 0,
                  "tile view invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_OPERATOR_VIEW_INVALID)
        rep.check("tv::{}::page".format(tid), (TILES_OUT / "{}.html".format(tid)).is_file(),
                  "tile page missing", code=F.STREAMING_OPERATOR_VIEW_INVALID)
        for lr in tv["lifecycle_reports"]:
            rep.check("tv::{}::lifecycle_link".format(tid), (REPO_ROOT / lr).is_file(),
                      "lifecycle link broken: {}".format(lr), code=F.STREAMING_TILE_LOAD_MISSING)
        for op in tv["asset_ownership_paths"]:
            rep.check("tv::{}::ownership_link".format(tid), (REPO_ROOT / op).is_file(),
                      "ownership link broken: {}".format(op), code=F.STREAMING_OPERATOR_VIEW_INVALID)
        if tv["runtime_status"] == "pass" and not tv["failure_codes"]:
            rep.check("tv::{}::pass_has_lifecycle".format(tid), len(tv["lifecycle_reports"]) >= 1,
                      "passing tile view must link >= 1 lifecycle report",
                      code=F.STREAMING_TILE_LOAD_MISSING)

    # loop closure: every runtime operator_trace_path resolves to a rendered page.
    for d in sorted(p for p in RUNTIME_DIR.iterdir() if p.is_dir() and (p / "report.json").is_file()):
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        for tp in report.get("operator_trace_paths", []):
            rep.check("trace::{}::resolves".format(d.name), (REPO_ROOT / tp).is_file(),
                      "runtime operator_trace_path does not resolve: {}".format(tp),
                      code=F.STREAMING_OPERATOR_VIEW_INVALID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 operator streaming smoke gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "streaming_operator_smoke", strict=strict)
    n = validate(rep)
    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-streaming-smoke", pack=None, strict=strict, status=rep.status,
        record_count=n, records_total=n, report_type="wf.streaming.operator_smoke.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "streaming_operator_smoke_report.json")
    rep.print_summary("operator-streaming-smoke")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
