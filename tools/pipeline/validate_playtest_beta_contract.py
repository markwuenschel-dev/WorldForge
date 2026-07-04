#!/usr/bin/env python3
"""validate_playtest_beta_contract.py — WorldForge v1.4 PlaytestForge Beta contract gate (Lane E).

Validates that every generated encounter DECLARES a well-formed beta playtest
contract (brief §14) — sibling of validate_playtest_contract.py (v1.3). It does
NOT run the playtest (run_playtest_forge_beta.py) nor audit its reports
(validate_playtest_beta_reports.py); it proves each encounter asks for a
playtest that actually exercises the encounter:

  * playtest_contract present with every EC.PLAYTEST_REQUIRED key;
  * modes non-empty, every mode a known beta mode (PB.BETA_MODES);
  * ALL core modes (PB.REQUIRED_BETA_MODES: route/anchor/state_transition/
    save_load/budget_safe/encounter_pressure/encounter_resolution/pacing)
    present — an encounter cannot opt out; a playtest that ignores the
    encounter is a contract failure;
  * resource_reward_playtest declared IFF a resource_grant reward hook exists;
  * expected_completion is exactly True;
  * max_pressure_band in EC.DIFFICULTY_BANDS and pinned per profile
    ("standard" for light_pressure, "hard" for standard_pressure).

Usage:
    python tools/pipeline/validate_playtest_beta_contract.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_playtest_beta_contract/validate_playtest_beta_contract_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import playtest_beta_contract as PB
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

BCON = FailureCode.PLAYTEST_BETA_CONTRACT_FAILURE


def check_beta_contract(rep, eid, enc):
    """Add beta-playtest-contract checks for one encounter to ``rep``. Importable core."""
    def c(name, ok, detail="", code=BCON):
        return rep.check("{}::{}".format(eid, name), ok, detail, code=code)

    pt = enc.get("playtest_contract")
    if not isinstance(pt, dict) or not pt:
        c("playtest_contract_present", False, "playtest_contract missing or empty")
        return
    c("playtest_contract_present", True, "present")

    missing = [k for k in EC.PLAYTEST_REQUIRED if k not in pt]
    c("playtest_required_keys", not missing, "missing: {}".format(missing))

    modes = pt.get("modes")
    modes_list = modes if isinstance(modes, (list, tuple)) else []
    c("modes_non_empty", bool(modes_list), "modes={!r}".format(modes))
    unknown = [x for x in modes_list if x not in PB.BETA_MODES]
    c("modes_known", not unknown,
      "unknown modes: {} (known={})".format(unknown, list(PB.BETA_MODES)))

    # Core modes: the encounter cannot opt out of being playtested.
    missing_core = [x for x in PB.REQUIRED_BETA_MODES if x not in modes_list]
    c("core_modes_present", not missing_core,
      "missing core beta modes (playtest would ignore the encounter): {}".format(missing_core))

    # resource_reward_playtest iff a resource_grant hook exists.
    has_grant = PB.has_resource_grant(enc)
    declared_rr = "resource_reward_playtest" in modes_list
    c("resource_reward_mode_iff_grant", declared_rr == has_grant,
      "resource_grant_hook={} but resource_reward_playtest declared={}".format(
          has_grant, declared_rr))

    ec_val = pt.get("expected_completion")
    c("expected_completion_true", ec_val is True,
      "expected_completion={!r} (must be True)".format(ec_val))

    band = pt.get("max_pressure_band")
    c("max_pressure_band_known", band in EC.DIFFICULTY_BANDS,
      "max_pressure_band={!r} (known={})".format(band, list(EC.DIFFICULTY_BANDS)))
    profile = enc.get("encounter_profile")
    want = PB.PROFILE_MAX_BAND.get(profile)
    c("max_pressure_band_matches_profile", want is not None and band == want,
      "profile={!r} requires max_pressure_band={!r}, got {!r}".format(profile, want, band))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 PlaytestForge Beta encounter contracts.")
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
            rep.check("{}::loads".format(eid), False, err, code=BCON)
            continue
        check_beta_contract(rep, eid, enc)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-playtest-beta-contract", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_playtest_beta_contract",
              "validate_playtest_beta_contract_report.json")
    rep.print_summary("validate-playtest-beta-contract")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
