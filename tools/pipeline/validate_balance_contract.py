#!/usr/bin/env python3
"""validate_balance_contract.py — WorldForge v1.4 balance-contract validator (Lane F).

Proves every encounter carries a complete, correctly-typed balance surface
BEFORE BalanceForge classifies it: pressure_budget / difficulty_band /
pacing_target must be present and typed, the profile must be a known
encounter profile, the stored band must be a real classification (never
'invalid'), the budget must be the canonical per-profile budget, and the
pacing_target must carry every required threshold as a number. Violations
fail with BALANCE_CONTRACT_FAILURE.

Usage:
    python tools/pipeline/validate_balance_contract.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_balance_contract/validate_balance_contract_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _num(x):
    """Return float(x) for real numerics (bool excluded), else None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def check_balance_contract(rep, eid, enc):
    """Assert one encounter's balance surface is complete and typed."""
    code = FailureCode.BALANCE_CONTRACT_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(eid, name), ok, detail, code=code)

    budget = enc.get("pressure_budget")
    band = enc.get("difficulty_band")
    pt = enc.get("pacing_target")
    profile = enc.get("encounter_profile")

    c("pressure_budget_typed", _num(budget) is not None,
      "pressure_budget missing or non-numeric: {!r}".format(budget))
    c("difficulty_band_typed", isinstance(band, str) and bool(band),
      "difficulty_band missing or not a string: {!r}".format(band))
    c("pacing_target_typed", isinstance(pt, dict) and bool(pt),
      "pacing_target missing or not a mapping: {!r}".format(pt))

    c("profile_known", profile in EC.ENCOUNTER_PROFILES,
      "encounter_profile {!r} not in {}".format(profile, EC.ENCOUNTER_PROFILES))

    classifiable = tuple(b for b in EC.DIFFICULTY_BANDS if b != "invalid")
    c("band_classifiable", band in classifiable,
      "difficulty_band {!r} not a real classification {}".format(band, classifiable))

    canonical = EC.PROFILE_PRESSURE_BUDGETS.get(profile)
    c("budget_matches_profile",
      _num(budget) is not None and canonical is not None and float(budget) == canonical,
      "pressure_budget {!r} != canonical {!r} for profile {!r}".format(
          budget, canonical, profile))

    if isinstance(pt, dict):
        missing = [k for k in EC.PACING_TARGET_REQUIRED if k not in pt]
        c("pacing_target_complete", not missing,
          "pacing_target missing required keys: {}".format(missing))
        bad = {k: pt.get(k) for k in EC.PACING_TARGET_REQUIRED
               if k in pt and _num(pt.get(k)) is None}
        c("pacing_target_numeric", not bad,
          "pacing_target has non-numeric thresholds: {}".format(bad))
    else:
        c("pacing_target_complete", False, "pacing_target absent — no thresholds to check")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter balance contract.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err,
                      code=FailureCode.BALANCE_CONTRACT_FAILURE)
            continue
        check_balance_contract(rep, eid, enc)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-balance-contract", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_balance_contract",
              "validate_balance_contract_report.json")
    rep.print_summary("validate-balance-contract")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
