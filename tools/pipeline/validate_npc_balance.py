#!/usr/bin/env python3
"""validate_npc_balance.py — WorldForge v1.7 Wave R BalanceForge gate.

Validates the balance reports classify_npc_pressure emits. The hard, blocking
guarantees on every classified scenario are the honesty-critical ones:

  * baseline_winnable — the mission actually completed under the NPC pressure
    (behavior must never make the baseline unwinnable);
  * pressure_present — a genuine pressure event fired (no zero-pressure "behavior");
  * balance_class is a known band and never `unwinnable` / `no_pressure`.

The too_low / too_high bands are surfaced as advisory counts (non-blocking) — v1.7
alpha pressure is telemetry/state pressure and cannot itself make a run unwinnable.
FAIL-CLOSED: no balance reports (or a missing classifier run) turns the gate RED.

Acceptance: `python tools/pipeline/validate_npc_balance.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

BALANCE_DIR = REPO_ROOT / NX.BALANCE_REPORTS_REL
SKIP = {"balance_rollup.json", "classify_npc_pressure_report.json",
        "validate_npc_balance_report.json"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    files = sorted(BALANCE_DIR.glob("bs_*.json")) if BALANCE_DIR.is_dir() else []
    rep.check("balance::present", len(files) > 0,
              "no balance reports (run classify-npc-pressure)",
              code=FailureCode.NPC_BALANCE_REPORT_FAILURE)

    unwinnable = no_pressure = bad_band = 0
    advisory = {"too_low": 0, "too_high": 0}
    for f in files:
        sid = f.stem
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad_band += 1
            rep.check("bal::{}::readable".format(sid), False, "unreadable: {}".format(e),
                      code=FailureCode.NPC_BALANCE_REPORT_FAILURE)
            continue
        band = b.get("balance_class")
        if band not in NX.BALANCE_CLASSES:
            bad_band += 1
            rep.check("bal::{}::band".format(sid), False,
                      "unknown balance_class {!r}".format(band),
                      code=FailureCode.NPC_BALANCE_REPORT_FAILURE)
        if b.get("baseline_winnable") is not True:
            unwinnable += 1
            rep.check("bal::{}::winnable".format(sid), False,
                      "baseline not winnable under NPC pressure",
                      code=FailureCode.NPC_UNWINNABLE_BASELINE)
        if b.get("pressure_present") is not True or band == "no_pressure":
            no_pressure += 1
            rep.check("bal::{}::pressure".format(sid), False,
                      "no pressure event (not active behavior)",
                      code=FailureCode.NPC_NO_PRESSURE_EVENTS)
        if band in advisory:
            advisory[band] += 1

    rep.check("balance::all_winnable", unwinnable == 0,
              "{} scenarios unwinnable under NPC pressure".format(unwinnable),
              code=FailureCode.NPC_UNWINNABLE_BASELINE)
    rep.check("balance::all_have_pressure", no_pressure == 0,
              "{} scenarios with no pressure".format(no_pressure),
              code=FailureCode.NPC_NO_PRESSURE_EVENTS)
    rep.check("balance::bands_known", bad_band == 0,
              "{} balance reports with unknown/unreadable band".format(bad_band),
              code=FailureCode.NPC_BALANCE_REPORT_FAILURE)
    # Advisory — reported, never blocking.
    rep.check("balance::advisory_bands", True,
              "advisory: too_low={} too_high={} (non-blocking)".format(
                  advisory["too_low"], advisory["too_high"]),
              code=None, warn_only=True)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-balance", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files), report_type=NX.RT_BALANCE,
                            records_total=len(files),
                            records_failed=unwinnable + no_pressure + bad_band))
    rep.write(BALANCE_DIR, "validate_npc_balance_report.json")
    rep.print_summary("validate-npc-balance")
    print("[validate-npc-balance] {} balance reports checked (advisory {})".format(len(files), advisory))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
