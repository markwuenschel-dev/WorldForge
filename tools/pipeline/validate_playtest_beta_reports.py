#!/usr/bin/env python3
"""validate_playtest_beta_reports.py — WorldForge v1.4 Beta no-fake-green gate (Lane E).

Report-integrity gate for PlaytestForge Beta (sibling of
validate_playtest_reports.py): it does NOT trust the harness exit code — it
audits the per-encounter beta reports on disk and proves none is fake green.
For EVERY encounter in the catalog it demands a real, honest, consistent report:

  * a per-encounter report EXISTS at procedural/reports/encounters/playtest_beta/<eid>.json;
  * it parses, carries schema_version "wf.playtest_beta.v1", and its
    encounter_id / mission_id match the encounter;
  * completed is True and expected_completion is True;
  * the report's modes cover the encounter's declared playtest_contract.modes
    EXACTLY (no skipped mode, no phantom mode) and EVERY listed mode passed;
  * pressure.band is a known band inside the profile's band targets;
  * final_state carries every encounter state key at its expected_final value;
  * the report is not stale (report mtime >= encounter.json mtime);
  * the catalog entry is stamped playtest_beta_status == "completed".

Usage:
    python tools/pipeline/validate_playtest_beta_reports.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_playtest_beta_reports/validate_playtest_beta_reports_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

BREP = FailureCode.PLAYTEST_BETA_REPORT_FAILURE
BETA_SCHEMA_VERSION = "wf.playtest_beta.v1"


def report_path(eid):
    return REPO_ROOT / EC.PLAYTEST_BETA_REPORTS_REL / "{}.json".format(eid)


def check_beta_report(rep, eid, enc, report):
    """Content checks against a parsed beta report dict (None = missing/unparseable).
    Importable core — mutation probes call this directly."""
    def c(name, ok, detail="", code=BREP):
        return rep.check("{}::{}".format(eid, name), ok, detail, code=code)

    if not isinstance(report, dict):
        c("report_present", False,
          "no parseable beta report — run run_playtest_forge_beta.py")
        return
    c("report_present", True, "parsed")

    c("schema_version", report.get("schema_version") == BETA_SCHEMA_VERSION,
      "schema_version={!r} (want {!r})".format(report.get("schema_version"), BETA_SCHEMA_VERSION))

    c("encounter_id_matches", report.get("encounter_id") == eid,
      "report encounter_id={!r} != {!r}".format(report.get("encounter_id"), eid))
    c("mission_id_matches", report.get("mission_id") == enc.get("mission_id"),
      "report mission_id={!r} != encounter mission_id={!r}".format(
          report.get("mission_id"), enc.get("mission_id")))

    completed = report.get("completed")
    c("completed_true", completed is True, "completed={!r} (must be True)".format(completed))
    expected = report.get("expected_completion")
    c("expected_completion_true", expected is True,
      "expected_completion={!r} (must be True)".format(expected))

    # Modes must cover the declared contract EXACTLY.
    declared = (enc.get("playtest_contract") or {}).get("modes") or []
    declared = list(declared) if isinstance(declared, (list, tuple)) else []
    modes = report.get("modes")
    modes = modes if isinstance(modes, dict) else {}
    missing = [x for x in declared if x not in modes]
    extra = [x for x in modes if x not in declared]
    c("modes_cover_contract_exactly", not missing and not extra and bool(modes),
      "report modes != declared modes (missing={} phantom={})".format(missing, extra))

    failed = [x for x in modes
              if not (isinstance(modes.get(x), dict) and modes[x].get("passed") is True)]
    c("all_listed_modes_passed", not failed and bool(modes),
      "modes without passed=True: {}".format(failed))
    # completed True with a failed mode is a contradictory (doctored) report.
    if completed is True:
        c("completed_implies_all_modes_pass", not failed,
          "completed=True but modes failed (contradictory report): {}".format(failed))

    # Pressure band: known and inside the profile's targets.
    band = (report.get("pressure") or {}).get("band")
    profile = enc.get("encounter_profile")
    c("pressure_band_known", band in EC.DIFFICULTY_BANDS,
      "pressure.band={!r} (known={})".format(band, list(EC.DIFFICULTY_BANDS)))
    c("pressure_band_in_profile_targets", EC.band_allowed_for_profile(band, profile),
      "pressure.band={!r} outside targets {} for profile {!r}".format(
          band, list(EC.PROFILE_BAND_TARGETS.get(profile, ())), profile))

    # final_state must carry every encounter state key at expected_final.
    final = report.get("final_state")
    final = final if isinstance(final, dict) else {}
    bad_keys = []
    for s in enc.get("state_keys") or []:
        key = (s or {}).get("key")
        try:
            want = float(s.get("expected_final"))
            got = float(final[key])
            ok = got == want
        except (TypeError, ValueError, KeyError):
            ok = False
            got = final.get(key) if key in final else "<absent>"
            want = s.get("expected_final")
        if not ok:
            bad_keys.append("{}={!r} (want {!r})".format(key, got, want))
    c("final_state_at_expected_final", not bad_keys,
      "encounter state keys not at expected_final: {}".format(bad_keys))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 PlaytestForge Beta reports (no-fake-green gate).")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    entries = catalog.get("encounters") or {}
    eids = sorted(entries.keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")

    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err, code=BREP)
            continue
        rp = report_path(eid)
        if not rp.is_file():
            rep.check("{}::report_exists".format(eid), False,
                      "no beta report at {} — run run_playtest_forge_beta.py".format(rp),
                      code=BREP)
            n += 1
            continue
        rep.check("{}::report_exists".format(eid), True, str(rp), code=BREP)
        try:
            report = json.loads(rp.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            report = None
            rep.check("{}::report_parses".format(eid), False,
                      "unparseable: {}".format(exc), code=BREP)
        check_beta_report(rep, eid, enc, report if isinstance(report, dict) else None)

        # Staleness: the report must not predate its encounter.json.
        ep = EC.encounter_path(eid)
        if ep.is_file():
            stale = rp.stat().st_mtime < ep.stat().st_mtime
            rep.check("{}::report_not_stale".format(eid), not stale,
                      "beta report older than encounter.json — re-run run_playtest_forge_beta.py",
                      code=BREP)

        # Catalog stamp must say completed.
        status = (entries.get(eid) or {}).get("playtest_beta_status")
        rep.check("{}::catalog_status_completed".format(eid), status == "completed",
                  "catalog playtest_beta_status={!r} (want 'completed')".format(status),
                  code=BREP)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-playtest-beta-reports", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_playtest_beta_reports",
              "validate_playtest_beta_reports_report.json")
    rep.print_summary("validate-playtest-beta-reports")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
