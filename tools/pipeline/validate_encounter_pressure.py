#!/usr/bin/env python3
"""validate_encounter_pressure.py — WorldForge v1.4 encounter pressure validator (Lane F).

Proves every generated encounter's pressure math is HONEST against the single
source of truth (encounter_contract): the stored difficulty band must equal the
band recomputed from the deterministic pressure model, the total must fit the
profile's budget, the band must be one the profile is allowed to target, and
per-spawn-group pressure_values must be real (positive, budget-bounded, and in
agreement with the recomputed spawn-pressure component). Fabricated bands,
over-budget encounters, extreme/invalid pressure, and fantasy per-group values
all fail with ENCOUNTER_PRESSURE_FAILURE.

Usage:
    python tools/pipeline/validate_encounter_pressure.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_pressure/validate_encounter_pressure_report.json
"""

import argparse
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

# Stored per-group pressure_values must agree with the recomputed spawn-pressure
# component within this relative tolerance (stored values must not be fantasy).
SPAWN_PRESSURE_TOLERANCE = 0.25


def _num(x):
    """Return float(x) for real numerics (bool excluded), else None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def check_pressure(rep, eid, enc, mission):
    """Recompute the pressure model for one encounter and assert honesty."""
    code = FailureCode.ENCOUNTER_PRESSURE_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(eid, name), ok, detail, code=code)

    comps = EC.pressure_components(enc, mission)
    total = EC.total_pressure(comps)
    band = EC.classify_band(total)
    profile = enc.get("encounter_profile")

    # Every component of the model must be non-negative.
    negative = {k: v for k, v in comps.items() if _num(v) is None or v < 0}
    c("components_nonnegative", not negative,
      "negative/non-numeric pressure components: {}".format(negative))

    # Invalid / extreme pressure is not shippable in v1.4 mission packs.
    c("band_not_invalid", band != "invalid",
      "recomputed pressure {} classifies as 'invalid'".format(total))
    c("band_not_extreme", band != "extreme",
      "recomputed pressure {} classifies as 'extreme' (invalid for v1.4 packs)".format(total))

    # The stored band must be the recomputed band — unclassified or mismatched
    # stored bands mean the generator (or a later edit) lied about difficulty.
    stored_band = enc.get("difficulty_band")
    c("stored_band_matches_recomputed", stored_band == band,
      "stored difficulty_band {!r} != recomputed {!r} (total={})".format(
          stored_band, band, total))

    # Budget must be the canonical per-profile budget, and the total must fit it.
    budget = EC.PROFILE_PRESSURE_BUDGETS.get(profile)
    c("budget_matches_profile", _num(enc.get("pressure_budget")) is not None
      and budget is not None and float(enc.get("pressure_budget")) == budget,
      "pressure_budget {!r} != canonical budget {!r} for profile {!r}".format(
          enc.get("pressure_budget"), budget, profile))
    c("total_within_budget", budget is not None and total <= budget,
      "total pressure {} exceeds budget {} (profile={})".format(total, budget, profile))

    # The recomputed band must be one the profile is allowed to target.
    c("band_allowed_for_profile", band in EC.PROFILE_BAND_TARGETS.get(profile, ()),
      "band {!r} not in allowed targets {} for profile {!r}".format(
          band, EC.PROFILE_BAND_TARGETS.get(profile, ()), profile))

    # Per-group pressure values: positive, budget-bounded, and honest against
    # the recomputed spawn-pressure component.
    groups = enc.get("spawn_groups") or []
    stored_sum = 0.0
    for i, g in enumerate(groups):
        pv = _num(g.get("pressure_value"))
        c("group_{}_pressure_positive".format(i), pv is not None and pv > 0,
          "spawn group {!r} pressure_value {!r} must be > 0".format(
              g.get("spawn_group_id"), g.get("pressure_value")))
        if pv is not None and pv > 0:
            stored_sum += pv
    c("group_pressure_sum_within_budget", budget is not None and stored_sum <= budget,
      "sum of spawn-group pressure_values {} exceeds budget {}".format(
          round(stored_sum, 3), budget))

    recomputed = EC.spawn_pressure(groups)
    if stored_sum > 0:
        honest = abs(recomputed - stored_sum) <= SPAWN_PRESSURE_TOLERANCE * stored_sum
    else:
        honest = recomputed == 0
    c("spawn_pressure_values_honest", honest,
      "recomputed spawn_pressure {} disagrees with stored per-group sum {} "
      "(tolerance {:.0%})".format(recomputed, round(stored_sum, 3),
                                  SPAWN_PRESSURE_TOLERANCE))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter pressure honesty.")
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
                      code=FailureCode.ENCOUNTER_PRESSURE_FAILURE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id"))
        if mission is None:
            rep.check("{}::mission_loads".format(eid), False, merr,
                      code=FailureCode.ENCOUNTER_PRESSURE_FAILURE)
            continue
        check_pressure(rep, eid, enc, mission)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-pressure", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_pressure",
              "validate_encounter_pressure_report.json")
    rep.print_summary("validate-encounter-pressure")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
