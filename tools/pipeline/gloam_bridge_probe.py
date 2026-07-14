#!/usr/bin/env python3
"""gloam_bridge_probe.py — v2.5 Gloamstead bridge DRY probe driver (offline).

Builds a bridge REQUEST targeting a Gloamstead UE 5.8 project, runs the rejecting
dry probe (tools.bridge.dry_probe), and writes a GloamBridgeProbe-shaped report to
procedural/reports/ue5_8/gloam/gloam_bridge_probe_report.json.

v2.5 SCOPE BOUNDARY: this lays the bridge contract only. No live UE process is
launched, no Gloamstead courtyard is authored, no Gloamstead compatibility is
claimed. The report honestly REJECTS (probe_result=rejected_dry_probe) and the
live fixture run is a later, gated wave.

Meta convention (binding): the report's meta block carries
    declared_target_engine="5.8"
    observed_runtime_engine=None
    runtime_execution_required=False
    runtime_executed=False
because a dry probe performs no live run. All evidence paths are project-relative.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/gloam_bridge_probe.py
Report -> procedural/reports/ue5_8/gloam/gloam_bridge_probe_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import bridge  # noqa: E402  (tools/bridge package)
from report_meta import build_meta  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "gloam"
REPORT_NAME = "gloam_bridge_probe_report.json"

# The four binding meta-convention keys for a dry probe (no live run).
BRIDGE_META_EXTRA = {
    "declared_target_engine": bridge.BRIDGE_ENGINE,   # "5.8"
    "observed_runtime_engine": None,
    "runtime_execution_required": False,
    "runtime_executed": False,
}


def build_probe_report(operation_id="op_v2_5_gloam_bridge_0001"):
    """Build the GloamBridgeProbe-shaped report dict (report + meta), offline."""
    request = bridge.build_request(operation_id=operation_id)
    report = bridge.dry_probe(request)
    report["meta"] = build_meta(
        command="gloam-bridge-probe",
        pack="worldforge_vertical_slice",
        strict=False,
        status=report["probe_result"],
        record_count=1,
        records_total=1,
        records_passed=1,
        report_type=report["schema_version"],
        extra=dict(BRIDGE_META_EXTRA),
    )
    return request, report


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 Gloamstead bridge DRY probe (offline).")
    ap.add_argument("--operation-id", default="op_v2_5_gloam_bridge_0001")
    ap.add_argument("--print", action="store_true", help="also print the report to stdout")
    args, _ = ap.parse_known_args(argv)

    request, report = build_probe_report(args.operation_id)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / REPORT_NAME
    with out.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    rel = out.relative_to(REPO_ROOT).as_posix()
    print("[gloam-bridge-probe] DRY PROBE -> {}".format(rel))
    print("[gloam-bridge-probe]   probe_result   = {}".format(report["probe_result"]))
    print("[gloam-bridge-probe]   operation_id   = {}".format(report["operation_id"]))
    print("[gloam-bridge-probe]   target_engine  = {}".format(report["target_engine"]))
    print("[gloam-bridge-probe]   target_project = {}".format(report["target_project"]))
    print("[gloam-bridge-probe]   plugin_present = {} map_present = {}".format(
        report["plugin_present"], report["map_present"]))
    print("[gloam-bridge-probe]   rejection      = {}".format(report["rejection_reason"]))
    print("[gloam-bridge-probe]   runtime_executed = {} (dry probe; no live run)".format(
        report["meta"]["runtime_executed"]))
    if args.print:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
