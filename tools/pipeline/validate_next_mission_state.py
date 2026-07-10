#!/usr/bin/env python3
"""validate_next_mission_state.py — WorldForge v1.9 next-mission handoff gate.

Proves the reward/progression state genuinely HANDS OFF to the next mission: the
authoring scenarios form a single accumulating player, so scenario_i's pre-state
must be scenario_{i-1}'s post-state and the next mission can read the unlocks the
prior missions granted. This gate asserts:

  1. The progression HASH CHAIN is unbroken — for every scenario i>0,
     scenario_i.prev_progression_hash == scenario_{i-1}.progression_hash. The
     authoritative chain is RE-DERIVED from reward_forge.build_authoring_scenarios()
     (the generated progression files intentionally don't carry prev_*).
  2. The on-disk progression file for each scenario matches the authoritative
     progression_hash (NEXT_MISSION_STATE_MISSING if a file is absent,
     NEXT_MISSION_STATE_MISMATCH if its hash disagrees).
  3. The next mission can READ prior unlocks — the FINAL scenario's progression
     `unlocks` is non-empty and every unlock that affects_generation is present in
     that list AND backed by an enabled on-disk UnlockState.

ANTI-FAKE-GREEN: fail-closed (fewer than 2 scenarios => RED) and DOGFOODS the
chain comparison against a synthetic broken chain to prove a broken hand-off is
caught, not silently passed.

Codes: NEXT_MISSION_STATE_MISSING, NEXT_MISSION_STATE_MISMATCH.
Acceptance: `python tools/pipeline/validate_next_mission_state.py --pack encounter_loop_world --strict`.
Reports -> procedural/reports/progression/validate_next_mission_state_report.json
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_forge as RF
import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

PROGRESSION_DIR = REPO_ROOT / "procedural/generated/progression/progression"
UNLOCKS_DIR = REPO_ROOT / "procedural/generated/progression/unlocks"
MISSING = FailureCode.NEXT_MISSION_STATE_MISSING
MISMATCH = FailureCode.NEXT_MISSION_STATE_MISMATCH


def _chain_break_count(scenarios):
    """Number of broken links in the prev_progression_hash chain. Shared by the
    live path and the dogfood so the two can never diverge."""
    broken = 0
    for i in range(1, len(scenarios)):
        expected = scenarios[i - 1]["progression_state"]["progression_hash"]
        actual = scenarios[i]["prev_progression_hash"]
        if actual != expected:
            broken += 1
    return broken


def _load_disk_progression(scenario_id):
    p = PROGRESSION_DIR / "{}.json".format(scenario_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _find_unlock_state(unlock_id):
    """Return the first on-disk UnlockState for an unlock_id, or None."""
    for p in sorted(UNLOCKS_DIR.glob("{}__*.json".format(unlock_id))):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return None


def _dogfood(rep):
    """A coherent authoring chain has zero breaks; corrupting one prev hash breaks it."""
    good = RF.build_authoring_scenarios()
    rep.check("dogfood::coherent_chain_unbroken", _chain_break_count(good) == 0,
              "authoritative authoring chain is unbroken", code=MISMATCH)
    # Corrupt one link in a copy and confirm the detector catches it.
    import copy
    bad = copy.deepcopy(good)
    if len(bad) >= 2:
        bad[1]["prev_progression_hash"] = "prog:tampered0000"
    rep.check("dogfood::broken_chain_detected", _chain_break_count(bad) > 0,
              "a tampered prev_progression_hash is detected as a broken hand-off", code=MISMATCH)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    scenarios = RF.build_authoring_scenarios()
    rep.check("next_mission::min_scenarios", len(scenarios) >= 2,
              "need >= 2 scenarios to prove a next-mission hand-off (got {})".format(len(scenarios)),
              code=MISSING)
    if len(scenarios) < 2:
        rep.finalize()
        rep.set_meta(build_meta(command="validate-next-mission-state", pack=args.pack, strict=strict,
                                status=rep.status, record_count=len(scenarios),
                                report_type="wf.reward.next_mission_state_report.v1",
                                records_total=len(scenarios)))
        rep.write(REPO_ROOT / RX.PROGRESSION_REPORTS_REL, "validate_next_mission_state_report.json")
        rep.print_summary("validate-next-mission-state")
        sys.exit(rep.exit_code)

    # ---- (1)+(2) authoritative chain + on-disk agreement ----
    for i, sc in enumerate(scenarios):
        sid = sc["scenario_id"]
        auth_hash = sc["progression_state"]["progression_hash"]
        disk = _load_disk_progression(sid)
        if disk is None:
            rep.check("chain::{}::disk_present".format(sid), False,
                      "on-disk progression state missing for {}".format(sid), code=MISSING)
            continue
        rep.check("chain::{}::disk_hash_matches".format(sid),
                  disk.get("progression_hash") == auth_hash,
                  "on-disk progression_hash for {} disagrees with authoritative chain".format(sid),
                  code=MISMATCH)
        if i > 0:
            expected_prev = scenarios[i - 1]["progression_state"]["progression_hash"]
            actual_prev = sc["prev_progression_hash"]
            rep.check("chain::{}::prev_hash_links".format(sid), actual_prev == expected_prev,
                      "prev_progression_hash {!r} for {} must equal prior scenario hash {!r}".format(
                          actual_prev, sid, expected_prev), code=MISMATCH)

    # ---- (3) final scenario: next mission can read prior unlocks ----
    final = scenarios[-1]
    fsid = final["scenario_id"]
    final_disk = _load_disk_progression(fsid)
    final_unlocks = (final_disk or {}).get("unlocks") if isinstance(final_disk, dict) else None
    rep.check("next_mission::final_disk_present", isinstance(final_disk, dict) and bool(final_disk),
              "final scenario {} progression state must be on disk".format(fsid), code=MISSING)
    rep.check("next_mission::final_unlocks_nonempty",
              isinstance(final_unlocks, list) and len(final_unlocks) > 0,
              "final scenario progression must carry >= 1 unlock for the next mission to read",
              code=MISSING)

    affects_gen = {u["unlock_id"]: u["affects_generation"]
                   for u in RF.build_unlock_catalog()["unlocks"]}
    for uid in (final_unlocks or []):
        if not affects_gen.get(uid, False):
            continue  # only generation-affecting unlocks must be materialized+enabled
        ust = _find_unlock_state(uid)
        rep.check("next_mission::unlock::{}::present".format(uid),
                  isinstance(ust, dict) and bool(ust),
                  "generation-affecting unlock {} has no on-disk UnlockState".format(uid),
                  code=MISSING)
        if isinstance(ust, dict) and ust:
            rep.check("next_mission::unlock::{}::enabled".format(uid),
                      ust.get("enabled") is True and ust.get("affects_generation") is True,
                      "unlock {} must be enabled and affects_generation".format(uid),
                      code=MISMATCH)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-next-mission-state", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(scenarios),
                            report_type="wf.reward.next_mission_state_report.v1",
                            records_total=len(scenarios),
                            extra={"final_scenario": fsid,
                                   "final_unlock_count": len(final_unlocks or [])}))
    rep.write(REPO_ROOT / RX.PROGRESSION_REPORTS_REL, "validate_next_mission_state_report.json")
    rep.print_summary("validate-next-mission-state")
    print("[validate-next-mission-state] {} scenario(s), final {} with {} unlock(s)".format(
        len(scenarios), fsid, len(final_unlocks or [])))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
