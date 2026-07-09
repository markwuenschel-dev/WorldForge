#!/usr/bin/env python3
"""classify_combat_balance.py — WorldForge v1.8 CombatForge Alpha BalanceForge classifier.

The BalanceForge / survivability analog of v1.7's ``classify_npc_pressure.py``, but
grounded on REAL runtime *combat* damage rather than telemetry-only pressure. Reads
every combat completion report (``cs_*.json``) from the combat completion reports dir
and classifies each into a SURVIVABILITY_BAND from the GENUINE observed evidence —
``player_min_health`` / ``player_final_health`` / ``damage_events_seen`` measured
against ``player_max_health`` and whether the mission actually completed under
baseline:

  * no_damage   — zero damage events landed (not real combat; blocking downstream).
  * unwinnable  — player died (final health <= 0) or the mission did not complete
                  under baseline (blocking downstream).
  * too_low     — survived, but limped out at very low final health (near-unwinnable;
                  advisory band).
  * too_soft    — health barely dropped, so the encounter posed no real threat
                  (advisory band).
  * survivable  — took real damage, stayed above the low-water line, and completed.

Only ``unwinnable`` / ``no_damage`` (BLOCKING_SURVIVABILITY_BANDS) are hard integrity
failures for the downstream gate; ``too_low`` / ``too_soft`` are advisory. Emits one
balance report per scenario plus a rollup with band counts.

FAIL-CLOSED: with no committed combat completion evidence this writes an honest,
empty-but-real rollup and turns the gate RED (nothing has been realized at runtime
yet) — it never fabricates a vacuous green.

Acceptance: ``python tools/pipeline/classify_combat_balance.py --pack encounter_loop_world --strict``.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CX
from report_meta import build_meta, git_sha, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / CX.COMBAT_COMPLETION_REPORTS_REL
BALANCE_DIR = REPO_ROOT / CX.COMBAT_BALANCE_REPORTS_REL

# Survivability thresholds (fractions of player_max_health). Advisory bands only.
TOO_SOFT_DROP_FRAC = 0.05   # max health dropped by < 5% -> no real threat (too_soft)
TOO_LOW_FINAL_FRAC = 0.10   # survived but final health <= 10% of max -> near-unwinnable


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def classify(player_max_health, player_min_health, player_final_health,
             damage_events_seen, mission_completed):
    """Classify one combat completion record into a SURVIVABILITY_BAND.

    Pure function of the observed runtime evidence so it can be dogfooded directly.
    Order matters: no_damage and unwinnable (blocking) are decided first, then the
    advisory soft/low bands, then survivable as the residual.
    """
    dev = damage_events_seen if isinstance(damage_events_seen, int) else 0
    if dev <= 0:
        return "no_damage"
    # Died, or the mission could not be completed under baseline pressure.
    if not _num(player_final_health) or player_final_health <= 0 or mission_completed is not True:
        return "unwinnable"
    pmax = player_max_health if _num(player_max_health) else 0.0
    pmin = player_min_health if _num(player_min_health) else pmax
    pfin = player_final_health
    if pmax <= 0:
        # No sane max health to normalise against — cannot claim a real threat.
        return "too_soft"
    drop_frac = (pmax - pmin) / pmax
    if drop_frac < TOO_SOFT_DROP_FRAC:
        return "too_soft"
    if (pfin / pmax) <= TOO_LOW_FINAL_FRAC:
        return "too_low"
    return "survivable"


def _classify_record(r):
    """Extract fields from a completion record and classify it. Returns the band."""
    return classify(
        r.get("player_max_health"), r.get("player_min_health"), r.get("player_final_health"),
        r.get("damage_events_seen"), r.get("mission_completed"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    files = sorted(COMPLETION_DIR.glob("cs_*.json")) if COMPLETION_DIR.is_dir() else []
    # FAIL-CLOSED: real evidence absent -> RED, never a vacuous pass.
    rep.check("classify::completions_present", len(files) > 0,
              "no combat completion reports to classify (run the combat runtime batch)",
              code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)

    BALANCE_DIR.mkdir(parents=True, exist_ok=True)
    bands = {b: 0 for b in CX.SURVIVABILITY_BANDS}
    emitted = 0
    unreadable = 0
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            unreadable += 1
            rep.check("classify::{}::readable".format(f.stem), False,
                      "unreadable completion report: {}".format(e),
                      code=FailureCode.COMBAT_BALANCE_REPORT_FAILURE)
            continue
        sid = r.get("combat_scenario_id") or f.stem
        band = _classify_record(r)
        bands[band] += 1
        pmax = r.get("player_max_health")
        pmin = r.get("player_min_health")
        pfin = r.get("player_final_health")
        dev = r.get("damage_events_seen")
        out = {
            "report_type": CX.RT_COMBAT_BALANCE, "combat_scenario_id": sid,
            "behavior_scenario_id": r.get("behavior_scenario_id"),
            "runtime_scenario_id": r.get("runtime_scenario_id"), "map_id": r.get("map_id"),
            "biome": r.get("biome"), "mission_archetype": r.get("mission_archetype"),
            "pressure_profile": r.get("pressure_profile"), "seed": r.get("seed"),
            "completion_class": r.get("completion_class"),
            "player_max_health": pmax, "player_min_health": pmin, "player_final_health": pfin,
            "damage_events_seen": dev, "mission_completed": r.get("mission_completed") is True,
            "survivability_band": band,
            "baseline_winnable": band not in CX.BLOCKING_SURVIVABILITY_BANDS,
            "damage_present": isinstance(dev, int) and dev > 0,
            "advisory": band in ("too_low", "too_soft"),
            "blocking": band in CX.BLOCKING_SURVIVABILITY_BANDS,
            "created_at": "live", "git_commit": git_sha(),
            "meta": build_meta(command="classify-combat-balance", pack=args.pack, strict=strict,
                               status="ok", record_count=1, report_type=CX.RT_COMBAT_BALANCE,
                               report_id="combat_balance:{}".format(sid),
                               records_total=1, records_passed=1),
        }
        (BALANCE_DIR / "{}.json".format(sid)).write_text(
            json.dumps(out, indent=2) + "\n", encoding="utf-8")
        emitted += 1

    rollup = {
        "report_type": "wf.combat.balance_rollup.v1", "pack": args.pack,
        "scenarios_classified": emitted, "unreadable": unreadable, "bands": bands,
        "blocking_bands": {b: bands[b] for b in CX.BLOCKING_SURVIVABILITY_BANDS},
        "git_commit": git_sha(),
        "meta": build_meta(command="classify-combat-balance", pack=args.pack, strict=strict,
                           status="ok", record_count=emitted,
                           report_type="wf.combat.balance_rollup.v1",
                           report_id="combat_balance_rollup", records_total=emitted,
                           records_passed=emitted),
    }
    (BALANCE_DIR / "combat_balance_rollup.json").write_text(
        json.dumps(rollup, indent=2) + "\n", encoding="utf-8")

    # Blocking-band integrity: unwinnable / no_damage are hard downstream failures.
    rep.check("classify::no_no_damage", bands["no_damage"] == 0,
              "{} scenarios with zero damage events (not real combat)".format(bands["no_damage"]),
              code=FailureCode.COMBAT_NO_DAMAGE_EVENTS)
    rep.check("classify::no_unwinnable", bands["unwinnable"] == 0,
              "{} scenarios unwinnable under combat baseline".format(bands["unwinnable"]),
              code=FailureCode.COMBAT_UNWINNABLE_BASELINE)
    # Advisory bands — surfaced, never blocking.
    rep.check("classify::advisory_bands", True,
              "advisory: too_low={} too_soft={} (non-blocking)".format(
                  bands["too_low"], bands["too_soft"]),
              code=None, warn_only=True)

    rep.finalize()
    rep.set_meta(build_meta(command="classify-combat-balance", pack=args.pack, strict=strict,
                            status=rep.status, record_count=emitted,
                            report_type=CX.RT_COMBAT_BALANCE, records_total=emitted,
                            extra={"bands": bands}))
    rep.write(BALANCE_DIR, "classify_combat_balance_report.json")
    rep.print_summary("classify-combat-balance")
    print("[classify-combat-balance] {} classified — bands: {}".format(emitted, bands))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
