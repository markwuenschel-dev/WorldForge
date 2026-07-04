#!/usr/bin/env python3
"""validate_balance_reports.py — WorldForge v1.4 balance-report validator (Lane F).

Proves BalanceForge's output is real, fresh, and honest for every encounter:
a balance report must exist and parse, carry the right schema and encounter,
classify a genuine difficulty band that agrees with BOTH the catalog and the
encounter file, score pressure/pacing/completion, never mark an invalid
encounter valid (cross-checked by recomputing the canonical pressure model),
not be stale against the encounter it describes, and the catalog must be
stamped "classified". Violations fail with BALANCE_REPORT_FAILURE.

Usage:
    python tools/pipeline/validate_balance_reports.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_balance_reports/validate_balance_reports_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

BALANCE_SCHEMA_VERSION = "wf.balance.v1"


def _num(x):
    """Return float(x) for real numerics (bool excluded), else None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def balance_report_path(eid):
    return REPO_ROOT / EC.BALANCE_REPORTS_REL / "{}.json".format(eid)


def load_balance_report(eid):
    """Return (report_or_None, err_or_None)."""
    p = balance_report_path(eid)
    if not p.is_file():
        return None, "balance report missing: {}".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, "balance report unparseable: {}".format(exc)


def check_balance_report(rep, eid, enc, report, entry=None):
    """Assert one encounter's balance report is present, honest, and fresh."""
    code = FailureCode.BALANCE_REPORT_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(eid, name), ok, detail, code=code)

    p = balance_report_path(eid)
    exists = c("report_exists", isinstance(report, dict),
               "balance report {} — run 'run_balance_forge' first".format(
                   "exists but is unparseable/not a mapping" if p.is_file() else "missing")
               + ": {}".format(p))
    if not exists:
        return

    c("schema_version_ok", report.get("schema_version") == BALANCE_SCHEMA_VERSION,
      "schema_version {!r} != {!r}".format(report.get("schema_version"),
                                           BALANCE_SCHEMA_VERSION))
    c("encounter_id_matches", report.get("encounter_id") == eid,
      "report encounter_id {!r} != {!r}".format(report.get("encounter_id"), eid))

    # Classified, scored, and completable.
    band = report.get("difficulty_band")
    c("band_classified", isinstance(band, str) and band in EC.DIFFICULTY_BANDS
      and band not in ("invalid",) and band != "unclassified",
      "difficulty_band {!r} is missing/unclassified/invalid".format(band))
    c("pressure_score_numeric", _num(report.get("pressure_score")) is not None,
      "pressure_score missing or non-numeric: {!r}".format(report.get("pressure_score")))
    c("pacing_score_present", _num(report.get("pacing_score")) is not None,
      "pacing_score missing or non-numeric: {!r}".format(report.get("pacing_score")))
    conf = _num(report.get("completion_confidence"))
    c("completion_confidence_positive", conf is not None and conf > 0.0,
      "completion_confidence {!r} — must be present and > 0".format(
          report.get("completion_confidence")))

    c("invalid_reason_null", report.get("invalid_reason") is None,
      "report carries invalid_reason {!r} — invalid encounters cannot ship".format(
          report.get("invalid_reason")))

    # Cross-check: recompute the canonical model; a report may never mark an
    # invalid encounter valid (balance classifies, validators decide).
    mission, merr = MC.load_mission(enc.get("mission_id"))
    if mission is None:
        c("recompute_cross_check", False, "mission unavailable for recompute: {}".format(merr))
    else:
        comps = EC.pressure_components(enc, mission)
        total = EC.total_pressure(comps)
        recomputed = EC.classify_band(total)
        profile = enc.get("encounter_profile")
        budget = EC.PROFILE_PRESSURE_BUDGETS.get(profile)
        honest = (recomputed == band
                  and recomputed not in ("invalid", "extreme")
                  and budget is not None and total <= budget
                  and recomputed in EC.PROFILE_BAND_TARGETS.get(profile, ()))
        c("recompute_cross_check", honest,
          "report band {!r} vs recomputed {!r} (total={} budget={} profile={!r}) — "
          "report marks an invalid/mismatched encounter valid".format(
              band, recomputed, total, budget, profile))

    # Three-way band agreement: report == catalog entry == encounter file.
    entry_band = (entry or {}).get("difficulty_band")
    enc_band = enc.get("difficulty_band")
    c("band_agreement", band == entry_band == enc_band,
      "band disagreement: report {!r} / catalog {!r} / encounter {!r}".format(
          band, entry_band, enc_band))

    # Freshness: the report must be at least as new as the encounter it scores.
    enc_path = EC.encounter_path(eid)
    fresh = (p.is_file() and enc_path.is_file()
             and p.stat().st_mtime >= enc_path.stat().st_mtime)
    c("report_not_stale", fresh,
      "balance report older than encounter.json — rerun run_balance_forge")

    c("catalog_status_classified", (entry or {}).get("balance_status") == "classified",
      "catalog balance_status {!r} != 'classified'".format(
          (entry or {}).get("balance_status")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 BalanceForge reports.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    encounters = catalog.get("encounters") or {}
    eids = sorted(encounters.keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err,
                      code=FailureCode.BALANCE_REPORT_FAILURE)
            continue
        report, _rerr = load_balance_report(eid)
        check_balance_report(rep, eid, enc, report, entry=encounters.get(eid))
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-balance-reports", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_balance_reports",
              "validate_balance_reports_report.json")
    rep.print_summary("validate-balance-reports")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
