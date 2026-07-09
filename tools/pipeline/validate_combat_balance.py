#!/usr/bin/env python3
"""validate_combat_balance.py — WorldForge v1.8 CombatForge Alpha BalanceForge gate.

The survivability gate over the balance reports ``classify_combat_balance`` emits —
the combat analog of v1.7's ``validate_npc_balance.py``. It loads the balance rollup
(and the per-scenario reports) and enforces the honesty-critical guarantee: no
realized combat scenario may land in a BLOCKING_SURVIVABILITY_BAND.

  * unwinnable — player died or the mission could not complete under baseline;
  * no_damage  — zero damage events landed (not real combat).

Both block. The advisory bands (``too_low`` / ``too_soft``) are surfaced as
non-blocking warning counts — a near-unwinnable or toothless encounter is worth
flagging but must not fail the gate.

ANTI-FAKE-GREEN: the gate DOGFOODS its own classifier + blocking logic on synthetic
completion records — one clearly ``survivable``, one ``unwinnable``, one ``no_damage``
— asserting the classifier labels each correctly and that the two bad bands are
blocked while the good one passes. So the gate proves its logic even before any real
runtime evidence exists.

FAIL-CLOSED: no rollup / no balance reports (classifier never run, or nothing
realized at runtime) turns the gate RED — the dogfood stays green, but real
survivability is not claimed without real evidence.

Acceptance: ``python tools/pipeline/validate_combat_balance.py --pack encounter_loop_world --strict``.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CX
from classify_combat_balance import classify, _classify_record
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

BALANCE_DIR = REPO_ROOT / CX.COMBAT_BALANCE_REPORTS_REL
ROLLUP = BALANCE_DIR / "combat_balance_rollup.json"
SKIP = {"combat_balance_rollup.json", "classify_combat_balance_report.json",
        "validate_combat_balance_report.json"}

# Which failure code owns each blocking band.
_BLOCKING_CODE = {
    "unwinnable": FailureCode.COMBAT_UNWINNABLE_BASELINE,
    "no_damage": FailureCode.COMBAT_NO_DAMAGE_EVENTS,
}


def _blocking_band_counts(bands):
    """Return {band: count} for every BLOCKING band with a positive count."""
    return {b: int(bands.get(b, 0)) for b in CX.BLOCKING_SURVIVABILITY_BANDS
            if int(bands.get(b, 0)) > 0}


def _dogfood(rep):
    """Prove the classifier + blocking logic on synthetic records, independent of
    any real evidence. A survivable record must classify clean and pass; an
    unwinnable and a no_damage record must classify into blocking bands and be
    rejected by the gate's blocking logic."""
    survivable = CX._example_combat_completion()  # 100 max, 63 min/final, 9 events, done
    unwinnable = CX._example_combat_completion(
        player_min_health=0.0, player_final_health=0.0, mission_completed=False,
        completion_class="failed_mission_completion", status="fail",
        failure_owner="runtime", failure_codes=["WF625_COMBAT_UNWINNABLE_BASELINE"])
    no_damage = CX._example_combat_completion(
        damage_events_seen=0, player_min_health=100.0, player_final_health=100.0,
        completion_class="failed_damage_application", status="fail",
        failure_owner="runtime", failure_codes=["WF626_COMBAT_NO_DAMAGE_EVENTS"])

    b_ok = _classify_record(survivable)
    b_unwin = _classify_record(unwinnable)
    b_nodmg = _classify_record(no_damage)

    rep.check("dogfood::survivable_labelled", b_ok == "survivable",
              "expected survivable, got {!r}".format(b_ok),
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
    rep.check("dogfood::unwinnable_labelled", b_unwin == "unwinnable",
              "expected unwinnable, got {!r}".format(b_unwin),
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
    rep.check("dogfood::no_damage_labelled", b_nodmg == "no_damage",
              "expected no_damage, got {!r}".format(b_nodmg),
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)

    # A direct sanity check on the pure classifier boundaries.
    rep.check("dogfood::too_soft_boundary", classify(100.0, 98.0, 98.0, 3, True) == "too_soft",
              "barely-scratched player must classify too_soft",
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
    rep.check("dogfood::too_low_boundary", classify(100.0, 6.0, 6.0, 20, True) == "too_low",
              "near-death survivor must classify too_low",
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)

    # The blocking logic must block a rollup carrying the two bad bands and pass a
    # clean one — proving the gate itself is not vacuous.
    bad_rollup = {b_ok: 1, b_unwin: 1, b_nodmg: 1}
    good_rollup = {b_ok: 3}
    bad_hits = _blocking_band_counts(bad_rollup)
    good_hits = _blocking_band_counts(good_rollup)
    rep.check("dogfood::blocks_bad_bands",
              set(bad_hits) == {"unwinnable", "no_damage"},
              "blocking logic must flag unwinnable+no_damage, got {}".format(sorted(bad_hits)),
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
    rep.check("dogfood::passes_good_band", not good_hits,
              "blocking logic must pass an all-survivable rollup, got {}".format(sorted(good_hits)),
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- dogfood the classifier + blocking logic (must be green regardless) -----
    _dogfood(rep)

    # ---- load the real rollup + per-scenario reports (FAIL-CLOSED on absence) ----
    rollup = None
    if ROLLUP.is_file():
        try:
            rollup = json.loads(ROLLUP.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep.check("balance::rollup_readable", False,
                      "balance rollup unreadable: {}".format(e),
                      code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
    rep.check("balance::rollup_present", rollup is not None,
              "no balance rollup (run classify-combat-balance)",
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)

    files = sorted(BALANCE_DIR.glob("cs_*.json")) if BALANCE_DIR.is_dir() else []
    rep.check("balance::reports_present", len(files) > 0,
              "no per-scenario balance reports (nothing realized at runtime yet)",
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)

    # Trust the on-disk band per report, but re-derive from its own numbers so a
    # tampered band label cannot smuggle a blocking scenario past the gate.
    rollup_bands = (rollup or {}).get("bands", {}) if isinstance(rollup, dict) else {}
    counted = {b: 0 for b in CX.SURVIVABILITY_BANDS}
    bad_band = 0
    for f in files:
        sid = f.stem
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad_band += 1
            rep.check("bal::{}::readable".format(sid), False, "unreadable: {}".format(e),
                      code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
            continue
        band = b.get("survivability_band")
        if band not in CX.SURVIVABILITY_BANDS:
            bad_band += 1
            rep.check("bal::{}::band".format(sid), False,
                      "unknown survivability_band {!r}".format(band),
                      code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
            continue
        # Re-derive from the report's own evidence; the stored band must match.
        rederived = _classify_record(b)
        if rederived != band:
            bad_band += 1
            rep.check("bal::{}::band_consistent".format(sid), False,
                      "stored band {!r} != re-derived {!r} (tampered)".format(band, rederived),
                      code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
        counted[rederived] += 1

    # ---- blocking bands: unwinnable / no_damage fail; advisory bands warn --------
    blocking_hits = _blocking_band_counts(counted)
    for band in CX.BLOCKING_SURVIVABILITY_BANDS:
        n = counted.get(band, 0)
        rep.check("balance::no_{}".format(band), n == 0,
                  "{} scenarios in blocking band '{}'".format(n, band),
                  code=_BLOCKING_CODE[band])
    rep.check("balance::bands_consistent", bad_band == 0,
              "{} balance reports with unknown/unreadable/tampered band".format(bad_band),
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)

    # Cross-check: our re-derived counts must agree with the rollup's own tally, so
    # a rollup that under-reports blocking bands cannot hide them.
    if isinstance(rollup_bands, dict) and files:
        mismatch = [b for b in CX.SURVIVABILITY_BANDS
                    if int(rollup_bands.get(b, 0)) != counted.get(b, 0)]
        rep.check("balance::rollup_matches_reports", not mismatch,
                  "rollup band counts disagree with per-scenario reports: {}".format(mismatch),
                  code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)

    # Advisory — reported, never blocking.
    rep.check("balance::advisory_bands", True,
              "advisory: too_low={} too_soft={} (non-blocking)".format(
                  counted.get("too_low", 0), counted.get("too_soft", 0)),
              code=None, warn_only=True)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-combat-balance", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type=CX.RT_COMBAT_BALANCE, records_total=len(files),
                            records_failed=sum(blocking_hits.values()) + bad_band,
                            extra={"bands": counted, "blocking_bands": blocking_hits}))
    rep.write(BALANCE_DIR, "validate_combat_balance_report.json")
    rep.print_summary("validate-combat-balance")
    print("[validate-combat-balance] {} balance reports checked — bands: {} blocking: {}".format(
        len(files), counted, blocking_hits))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
