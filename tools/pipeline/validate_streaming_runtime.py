#!/usr/bin/env python3
"""validate_streaming_runtime.py — v2.3 Wave 3 runtime + lifecycle gate.

Reads every produced StreamingRuntimeReport + TileLifecycleReport from disk and
proves the runtime matrix is real and complete: 24/24 scenarios, each report
contract-valid with empty failure_codes, crossing >= 2 tiles with >= 1 stream
transition, completing >= 1 cross-tile route + mission, with an honest runtime mode
(never full_ue_streaming). Each visited tile has a valid lifecycle report whose load
completed and whose reload preserved state.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_streaming_runtime.py --strict
Reports -> procedural/reports/streaming/runtime/validate_streaming_runtime_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "runtime"
LIFECYCLE_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "lifecycle"
REPORT_DIR = RUNTIME_DIR


def validate(rep):
    run_dirs = sorted([d for d in RUNTIME_DIR.iterdir()
                       if d.is_dir() and (d / "report.json").is_file()])
    rep.check("runtime::count_24", len(run_dirs) == SC.EXPECTED_SCENARIO_COUNT,
              "expected 24 runtime runs (got {})".format(len(run_dirs)),
              code=F.STREAMING_PARTIAL_MATRIX)
    seen, n = set(), 0
    for d in run_dirs:
        n += 1
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rid = report.get("run_id", d.name)
        fails = [c for c in SC.validate_streaming_runtime_report(report, strict=True) if not c[1]]
        rep.check("rt::{}::report_valid".format(rid), len(fails) == 0,
                  "runtime report invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_RUNTIME_REPORT_INVALID)
        rep.check("rt::{}::no_failure_codes".format(rid), report.get("failure_codes") == [],
                  "clean report must carry empty failure_codes",
                  code=F.STREAMING_MISSION_NOT_COMPLETED)
        seen.add(report.get("scenario_id"))
        # cross-tile + transition + route + mission
        rep.check("rt::{}::crosses_tiles".format(rid),
                  len(report.get("tile_sequence_seen", [])) >= 2,
                  "must cross >= 2 tiles", code=F.STREAMING_MISSION_NOT_COMPLETED)
        rep.check("rt::{}::has_transition".format(rid),
                  report.get("stream_transitions_seen", 0) >= 1,
                  "must have >= 1 stream transition", code=F.STREAMING_REQUIRED_TRANSITION_MISSING)
        rep.check("rt::{}::completes_route".format(rid),
                  len(report.get("routes_completed", [])) >= 1,
                  "must complete >= 1 cross-tile route", code=F.STREAMING_REQUIRED_ROUTE_NOT_COMPLETED)
        rep.check("rt::{}::mission_completed".format(rid),
                  report.get("mission_completed") is True,
                  "mission must complete", code=F.STREAMING_MISSION_NOT_COMPLETED)
        rep.check("rt::{}::honest_runtime_mode".format(rid),
                  report.get("runtime_mode") in ("simulated_streaming_lifecycle",
                                                  "process_isolated_tile_sequence"),
                  "runtime mode must be an honest alpha mode (not full_ue_streaming)",
                  code=F.STREAMING_NAVMESH_OVERCLAIM)
        # lifecycle reports for each visited tile
        for tile_id in report.get("tile_sequence_seen", []):
            lp = LIFECYCLE_DIR / "{}__{}.json".format(rid, tile_id)
            rep.check("rt::{}::lifecycle_exists::{}".format(rid, tile_id), lp.is_file(),
                      "lifecycle report missing for tile {}".format(tile_id),
                      code=F.STREAMING_TILE_LOAD_MISSING)
            if lp.is_file():
                lc = json.loads(lp.read_text(encoding="utf-8"))
                lfails = [c for c in SC.validate_tile_lifecycle_report(lc, strict=True) if not c[1]]
                rep.check("rt::{}::lifecycle_valid::{}".format(rid, tile_id), len(lfails) == 0,
                          "lifecycle invalid: {}".format([c[0] for c in lfails][:4]),
                          code=F.STREAMING_RUNTIME_REPORT_INVALID)
                rep.check("rt::{}::tile_loaded::{}".format(rid, tile_id),
                          lc.get("load_completed") is True,
                          "tile load must complete", code=F.STREAMING_TILE_LOAD_FAILED)
                rep.check("rt::{}::state_preserved::{}".format(rid, tile_id),
                          lc.get("state_preserved") is True,
                          "reload must preserve state", code=F.STREAMING_TILE_STATE_LOST)
    rep.check("runtime::all_24_scenarios", len(seen) == SC.EXPECTED_SCENARIO_COUNT,
              "must cover 24 distinct scenarios (got {})".format(len(seen)),
              code=F.STREAMING_PARTIAL_MATRIX)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 runtime + lifecycle gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)
    n = validate(rep)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-streaming-runtime", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.runtime_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_streaming_runtime_report.json")
    rep.print_summary("validate-streaming-runtime")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
