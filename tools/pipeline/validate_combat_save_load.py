#!/usr/bin/env python3
"""validate_combat_save_load.py — WorldForge v1.8 CombatForge combat state save/load gate.

Asserts combat-state PERSISTENCE for every successful combat run: each
combat_completed_runtime completion under ``COMBAT_COMPLETION_REPORTS_REL`` must
carry save_load_result='pass', and the PlayerCombatState the runtime persisted for
that scenario must round-trip coherently — validate_player_combat_state passes on
the persisted state, current_health is within [0, max_health], and is_alive is
consistent with current_health>0 (COMBAT_STATE_SAVE_LOAD_FAILURE). The persisted
state is read from procedural/reports/combat/save_load/<combat_scenario_id>.json,
the round-trip evidence the combat runtime batch writes per success.

ANTI-FAKE-GREEN: the gate DOGFOODS its persistence logic against a synthetic VALID
(success save_load_result=pass + coherent persisted state → passes) and a synthetic
KNOWN-BAD (save_load_result=fail + an incoherent state that claims alive at 0 health
→ rejected). It is then honestly FAIL-CLOSED: with zero success completions / zero
persisted states on disk the gate is RED under strict — persistence cannot be
greened without a real round-tripped combat state.

Acceptance: `python tools/pipeline/validate_combat_save_load.py --pack encounter_loop_world --strict`.
Reports -> procedural/reports/combat/save_load/validate_combat_save_load_report.json
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CX
import runtime_schema as RS
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / CX.COMBAT_COMPLETION_REPORTS_REL
SAVELOAD_DIR = REPO_ROOT / "procedural/reports/combat/save_load"
SL_CODE = FailureCode.COMBAT_STATE_SAVE_LOAD_FAILURE
COMPLETION_SKIP = {"validate_combat_completion_report.json", "combat_completion_rollup.json",
                   "run_combat_runtime_batch_gate_report.json"}


def _persistence_checks(report, state, strict):
    """Return (name, ok, detail, code) tuples asserting one success completion's
    combat state was genuinely persisted and round-trips coherently. Shared by the
    live path and the dogfood so the two can never diverge."""
    ch = []
    ch.append(("save_load_result_pass", report.get("save_load_result") == "pass",
               "success save_load_result must be 'pass' (got {!r})".format(report.get("save_load_result")),
               SL_CODE))
    if not isinstance(state, dict):
        ch.append(("persisted_state_present", False,
                   "no persisted PlayerCombatState round-trip for this success", SL_CODE))
        return ch
    ch.append(("persisted_state_present", True, "persisted PlayerCombatState found", SL_CODE))
    # Full schema round-trip on the persisted state.
    for name, ok, detail, code in CX.validate_player_combat_state(state, strict=strict):
        ch.append(("state::{}".format(name), ok, detail, code))
    # Explicit round-trip coherence (framed as save/load, not just schema).
    chp, mh = state.get("current_health"), state.get("max_health")
    if RS.is_number(chp) and RS.is_number(mh):
        ch.append(("state_health_in_bounds", 0.0 <= chp <= mh,
                   "persisted current_health must be in [0, max_health]", SL_CODE))
        if isinstance(state.get("is_alive"), bool):
            ch.append(("state_is_alive_consistent", state.get("is_alive") == (chp > 0),
                       "persisted is_alive must equal current_health>0", SL_CODE))
    else:
        ch.append(("state_health_numeric", False,
                   "persisted state needs numeric current/max health", SL_CODE))
    return ch


def _dogfood(rep, strict):
    """Prove the persistence logic constrains: a coherent success+state passes, an
    incoherent one (save_load_result=fail, alive at 0 health) is rejected."""
    good_report = CX._example_combat_completion()  # save_load_result='pass'
    good_state = CX._example_player_combat_state()
    bad_report = CX._example_combat_completion(save_load_result="fail")
    bad_state = CX._example_player_combat_state(current_health=0.0, is_alive=True)
    good_fails = [c for c in _persistence_checks(good_report, good_state, True) if not c[1]]
    bad_fails = [c for c in _persistence_checks(bad_report, bad_state, True) if not c[1]]
    rep.check("dogfood::valid_persistence_passes", not good_fails,
              "coherent success + persisted state passes ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]),
              code=SL_CODE)
    rep.check("dogfood::known_bad_rejected", len(bad_fails) > 0,
              "incoherent persistence (save_load=fail / alive at 0 health) is rejected",
              code=SL_CODE)


def _load_persisted_state(combat_scenario_id):
    p = SAVELOAD_DIR / "{}.json".format(combat_scenario_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}  # present-but-unreadable: distinct from absent, still fails schema


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # 1) Dogfood the gate logic (green regardless of real evidence).
    _dogfood(rep, strict)

    # 2) Real runtime evidence — success completions and their persisted states.
    files = [f for f in sorted(COMPLETION_DIR.glob("cs_*.json")) if f.name not in COMPLETION_SKIP] \
        if COMPLETION_DIR.is_dir() else []
    successes = []
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if r.get("completion_class") == CX.SUCCESS_COMBAT_CLASS:
            successes.append((f.stem, r))

    rep.check("save_load::present", len(successes) > 0,
              "no successful combat completions to prove state persistence "
              "(run the combat runtime batch)",
              code=SL_CODE)

    bad = verified = 0
    for sid, r in successes:
        csid = r.get("combat_scenario_id") or sid
        state = _load_persisted_state(csid)
        sub_fails = 0
        for name, ok, detail, code in _persistence_checks(r, state, strict):
            if not ok:
                bad += 1
                sub_fails += 1
                rep.check("sl::{}::{}".format(sid, name), False, detail, code=code)
        if sub_fails == 0:
            verified += 1

    rep.check("save_load::all_verified", bad == 0,
              "{} save/load check failure(s) across {} success completion(s)".format(
                  bad, len(successes)),
              code=SL_CODE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-combat-save-load", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(successes),
                            report_type="wf.combat.save_load_report.v1",
                            records_total=len(successes), extra={"verified": verified}))
    rep.write(SAVELOAD_DIR, "validate_combat_save_load_report.json")
    rep.print_summary("validate-combat-save-load")
    print("[validate-combat-save-load] {} success completion(s), {} persistence-verified".format(
        len(successes), verified))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
