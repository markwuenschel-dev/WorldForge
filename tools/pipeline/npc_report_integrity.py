#!/usr/bin/env python3
"""npc_report_integrity.py — WorldForge v1.7 NPCForge report-integrity gate.

Every NPCForge report must carry a coherent v1.5-shaped meta block and cannot claim
success while empty, stale-typed, or partial. This scans the reports the v1.7
authoring layer emits and asserts:

  * meta block present with all v1.5-required keys, non-empty report_type/report_id;
  * status is a known value and consistent with failure_count;
  * an 'ok' generation/manifest report has records_total > 0 (no zero-record success)
    and records_failed == 0;
  * records_total == records_passed + records_failed + records_skipped.

Acceptance: `make npc-report-integrity PACK=encounter_loop_world STRICT=1`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta, strict_from_env, missing_v1_5_meta_keys
from validation_report import ValidationReport
from failure_codes import FailureCode as F

NPC_REPORTS_ROOT = REPO_ROOT / "procedural" / "reports" / "npc"
# Report types whose 'ok' status implies a non-zero generated/validated record set.
NONZERO_TYPES = {
    "wf.npc.archetype_report.v1", "wf.npc.spawn_group_report.v1",
    "wf.npc.behavior_profile_report.v1", "wf.npc.behavior_scenario_manifest.v1",
    "wf.npc.spawn_placement_report.v1", "wf.npc.route_binding_report.v1",
}
KNOWN_STATUS = {"ok", "warn", "fail", "error"}


def iter_reports():
    if not NPC_REPORTS_ROOT.is_dir():
        return
    for p in sorted(NPC_REPORTS_ROOT.rglob("*.json")):
        try:
            yield p, json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            yield p, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    n = 0
    for path, doc in iter_reports():
        rel = path.relative_to(REPO_ROOT).as_posix()
        n += 1
        if doc is None:
            rep.check("ri::{}::parseable".format(rel), False, "report not parseable",
                      code=F.NPC_REPORT_INTEGRITY_FAILURE)
            continue
        meta = doc.get("meta")
        miss = missing_v1_5_meta_keys(meta)
        rep.check("ri::{}::meta_complete".format(rel), not miss,
                  "missing v1.5 meta keys: {}".format(miss), code=F.NPC_REPORT_INTEGRITY_FAILURE)
        if not isinstance(meta, dict):
            continue
        status = meta.get("status")
        rep.check("ri::{}::status_known".format(rel), status in KNOWN_STATUS,
                  "unknown status {!r}".format(status), code=F.NPC_REPORT_INTEGRITY_FAILURE)
        # status/failure_count coherence.
        fc = meta.get("failure_count", 0)
        if status == "ok":
            rep.check("ri::{}::ok_no_failures".format(rel), fc == 0,
                      "status=ok but failure_count={}".format(fc), code=F.NPC_REPORT_INTEGRITY_FAILURE)
        # records tally coherence.
        tot = meta.get("records_total", 0)
        passed = meta.get("records_passed", 0)
        failed = meta.get("records_failed", 0)
        skipped = meta.get("records_skipped", 0)
        rep.check("ri::{}::records_tally".format(rel), tot == passed + failed + skipped,
                  "records_total {} != passed+failed+skipped".format(tot),
                  code=F.NPC_REPORT_INTEGRITY_FAILURE)
        # no zero-record success for generation/manifest reports.
        if meta.get("report_type") in NONZERO_TYPES and status in ("ok", "warn"):
            rep.check("ri::{}::nonzero_success".format(rel), tot > 0 and failed == 0,
                      "ok {} report with records_total={} failed={}".format(
                          meta.get("report_type"), tot, failed),
                      code=F.NPC_REPORT_INTEGRITY_FAILURE)

    rep.check("integrity::reports_present", n > 0, "no NPC reports found to check",
              code=F.NPC_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="npc-report-integrity", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n, report_type="wf.npc.report_integrity.v1",
                            records_total=n))
    rep.write(REPO_ROOT / "procedural/reports/npc/report_integrity", "npc_report_integrity_report.json")
    rep.print_summary("npc-report-integrity")
    print("[npc-report-integrity] {} NPC reports checked".format(n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
