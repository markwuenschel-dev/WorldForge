#!/usr/bin/env python3
"""validate_playtest_contract.py — WorldForge v1.3 PlaytestForge contract validator (Agent 5).

Validates that every generated mission DECLARES a well-formed playtest contract
(brief §6) — the schema gate for PlaytestForge, sibling to validate_mission_contract.py.
It does NOT run the playtest (that is run_playtest_forge.py) nor read the reports
(that is validate_playtest_reports.py); it only proves each mission asks for a
completable playtest of the right shape:

  * playtest_contract present with every MC.PLAYTEST_REQUIRED key
    (modes, expected_completion, max_route_length_cm);
  * modes is non-empty and every declared mode is a known playtest mode
    (PC.PLAYTEST_MODES + PC.OPTIONAL_PLAYTEST_MODES);
  * the five minimum modes (PC.PLAYTEST_MODES) are ALL present — a mission that
    silently drops a required playtest mode is caught here, not by fake green;
  * expected_completion is a bool; max_route_length_cm is a positive number.

Usage:
    python tools/pipeline/validate_playtest_contract.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_playtest_contract/validate_playtest_contract_report.json
"""

import argparse
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

KNOWN_MODES = tuple(PC.PLAYTEST_MODES) + tuple(PC.OPTIONAL_PLAYTEST_MODES)
PTC = FailureCode.PLAYTEST_CONTRACT_FAILURE


def check_mission(rep, mid, m):
    def c(name, ok, detail="", code=PTC):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    pt = m.get("playtest_contract")
    if not isinstance(pt, dict) or not pt:
        c("playtest_contract_present", False, "playtest_contract missing or empty")
        return
    c("playtest_contract_present", True, "present")

    # All required keys present.
    missing = [k for k in MC.PLAYTEST_REQUIRED if k not in pt]
    c("playtest_required_keys", not missing, "missing: {}".format(missing))

    # modes non-empty and each declared mode is a known playtest mode.
    modes = pt.get("modes")
    modes_list = modes if isinstance(modes, (list, tuple)) else []
    c("modes_non_empty", bool(modes_list), "modes={}".format(modes))
    unknown = [x for x in modes_list if x not in KNOWN_MODES]
    c("modes_known", not unknown, "unknown modes: {} (known={})".format(unknown, list(KNOWN_MODES)))

    # The five minimum modes must ALL be declared.
    missing_required = [x for x in PC.PLAYTEST_MODES if x not in modes_list]
    c("required_modes_present", not missing_required,
      "missing required playtest modes: {}".format(missing_required))

    # expected_completion is a bool.
    ec = pt.get("expected_completion")
    c("expected_completion_bool", isinstance(ec, bool), "expected_completion={!r}".format(ec))

    # max_route_length_cm is a positive number (not bool).
    mr = pt.get("max_route_length_cm")
    mr_ok = isinstance(mr, (int, float)) and not isinstance(mr, bool) and mr > 0
    c("max_route_length_positive", mr_ok, "max_route_length_cm={!r}".format(mr))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 PlaytestForge mission contracts.")
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
            rep.check("{}::loads".format(mid), False, err, code=PTC)
            continue
        check_mission(rep, mid, m)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-playtest-contract", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_playtest_contract",
              "validate_playtest_contract_report.json")
    rep.print_summary("validate-playtest-contract")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
