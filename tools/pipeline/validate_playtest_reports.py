#!/usr/bin/env python3
"""validate_playtest_reports.py — WorldForge v1.3 PlaytestForge no-fake-green gate (Agent 5).

The report-integrity gate for PlaytestForge (brief §6 + the v1.0x "reports are
artifacts" spirit): it does NOT trust the harness's exit code — it audits the
per-mission playtest reports on disk and proves none of them is fake green. For
EVERY mission in the catalog it demands a real, honest, consistent report:

  * a per-mission report EXISTS at procedural/reports/missions/playtest/<mid>.json
    (missing -> PLAYTEST_REPORT_FAILURE);
  * it parses and carries schema_version "wf.playtest.v1", a modes{} block, and
    bool completed / expected_completion;
  * EVERY mode the mission DECLARES appears in the report's modes with a bool
    "passed" (a report that skips a required mode -> PLAYTEST_REPORT_FAILURE);
  * completed == expected_completion (a report claiming success without completing
    the objective -> PLAYTEST_COMPLETION_FAILURE);
  * internal consistency: if completed is True then EVERY mode passed (completed
    True with a failing mode is contradictory -> PLAYTEST_REPORT_FAILURE);
  * the report is not stale relative to the mission.json (mtime compare).

Usage:
    python tools/pipeline/validate_playtest_reports.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_playtest_reports/validate_playtest_reports_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
import playtest_contract as PC
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

REPORT = FailureCode.PLAYTEST_REPORT_FAILURE
COMPLETION = FailureCode.PLAYTEST_COMPLETION_FAILURE


def report_path(mid):
    return REPO_ROOT / PC.PLAYTEST_REPORTS_REL / "{}.json".format(mid)


def check_mission(rep, mid, m):
    def c(name, ok, detail="", code=REPORT):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    rp = report_path(mid)
    if not rp.is_file():
        c("report_exists", False, "no playtest report at {} — run run_playtest_forge.py".format(rp))
        return
    c("report_exists", True, str(rp))

    try:
        report = json.loads(rp.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover
        c("report_parses", False, "unparseable: {}".format(exc))
        return
    if not isinstance(report, dict):
        c("report_parses", False, "report is not an object")
        return
    c("report_parses", True, "parsed")

    c("schema_version", report.get("schema_version") == "wf.playtest.v1",
      "schema_version={!r}".format(report.get("schema_version")))

    modes = report.get("modes")
    modes_ok = isinstance(modes, dict) and bool(modes)
    c("has_modes_block", modes_ok, "modes={!r}".format(modes))
    modes = modes if isinstance(modes, dict) else {}

    completed = report.get("completed")
    c("completed_bool", isinstance(completed, bool), "completed={!r}".format(completed))
    expected = report.get("expected_completion")
    c("expected_completion_bool", isinstance(expected, bool),
      "expected_completion={!r}".format(expected))

    # Every DECLARED mode must appear in the report with a bool "passed".
    declared = (m.get("playtest_contract") or {}).get("modes") or []
    declared = declared if isinstance(declared, (list, tuple)) else []
    missing_modes = [x for x in declared if x not in modes]
    c("all_declared_modes_reported", not missing_modes,
      "report skips declared modes: {}".format(missing_modes))
    bad_passed = [x for x in declared
                  if x in modes and not isinstance((modes.get(x) or {}).get("passed"), bool)]
    c("declared_modes_have_passed_bool", not bad_passed,
      "modes lacking bool passed: {}".format(bad_passed))

    # completed == expected_completion — no success claim without completing.
    if isinstance(completed, bool) and isinstance(expected, bool):
        c("completed_matches_expected", completed == expected,
          "playtest reports success without completing objective"
          if (completed is False and expected is True)
          else "completed={} expected={}".format(completed, expected),
          code=COMPLETION)

    # Internal consistency: completed True => every mode passed.
    all_passed = all(isinstance(v, dict) and v.get("passed") is True for v in modes.values()) \
        and bool(modes)
    if completed is True:
        c("completed_implies_all_modes_pass", all_passed,
          "completed=True but a mode failed (contradictory report): {}".format(
              [k for k, v in modes.items()
               if not (isinstance(v, dict) and v.get("passed") is True)]))

    # Staleness: report must not predate its mission.json.
    mp = MC.mission_path(mid)
    if mp.is_file():
        stale = rp.stat().st_mtime < mp.stat().st_mtime
        c("report_not_stale", not stale,
          "playtest report older than mission.json — re-run run_playtest_forge.py")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 PlaytestForge reports (no-fake-green gate).")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")

    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=REPORT)
            continue
        check_mission(rep, mid, m)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-playtest-reports", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_playtest_reports",
              "validate_playtest_reports_report.json")
    rep.print_summary("validate-playtest-reports")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
