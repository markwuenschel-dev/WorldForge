#!/usr/bin/env python3
"""validate_player_health.py — WorldForge v1.8 CombatForge player-health mutation gate.

Proves the player's health genuinely MUTATED at runtime — the core anti-fake-green
invariant of combat. For every completion record that either succeeded or saw damage
(damage_events_seen>0), this gate asserts against the LIVE evidence that:

  * health actually dropped: player_min_health < player_max_health
    (else PLAYER_HEALTH_NO_MUTATION — a "combat" run where health never moved is fake), and
  * damage accounting is internally consistent: player_min <= player_final <= player_max
    (else DAMAGE_ACCOUNTING_INCONSISTENT), and
  * the player was NOT invulnerable — no invulnerable flag, and health did not stay
    pinned at max while damage events were claimed
    (else COMBAT_INVULNERABILITY_ABUSE — invulnerability is the classic zero-risk cheat).

Until the Wave-R UE matrix has emitted evidence the completion dir is empty and this
gate is HONESTLY FAIL-CLOSED (RED); its logic is still proven now by dogfooding a
synthetic VALID record (passes) and synthetic KNOWN-BAD records (rejected).

Acceptance: `python tools/pipeline/validate_player_health.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / CX.COMBAT_COMPLETION_REPORTS_REL
_isnum = CX.RS.is_number


def _saw_damage(report):
    dev = report.get("damage_events_seen")
    return isinstance(dev, int) and dev > 0


def _check_scenario(report, strict):
    """Pure logic for one record. Returns (name, ok, detail, code) tuples."""
    ch = []
    success = report.get("completion_class") == CX.SUCCESS_COMBAT_CLASS
    pmax = report.get("player_max_health")
    pmin = report.get("player_min_health")
    pfin = report.get("player_final_health")

    # Mutation is required whenever the run succeeded or claims to have taken damage.
    require_mutation = success or _saw_damage(report)
    if require_mutation:
        mutated = _isnum(pmax) and _isnum(pmin) and pmin < pmax
        ch.append(("health_mutated", mutated,
                   "player_min_health ({}) must be < player_max_health ({}) — health never mutated".format(
                       pmin, pmax),
                   FailureCode.PLAYER_HEALTH_NO_MUTATION))

    # Accounting: the trough must sit below the final, and the final at/below the cap.
    if all(_isnum(x) for x in (pmin, pfin, pmax)):
        consistent = pmin <= pfin <= pmax
        ch.append(("accounting_consistent", consistent,
                   "require player_min <= player_final <= player_max (got {} / {} / {})".format(
                       pmin, pfin, pmax),
                   FailureCode.DAMAGE_ACCOUNTING_INCONSISTENT))

    # Invulnerability abuse: an explicit flag, or damage claimed while health stayed pinned at max.
    flag = report.get("invulnerable") is True
    pcs = report.get("player_combat_state")
    pcs_invuln = isinstance(pcs, dict) and pcs.get("invulnerable") is True
    pinned_at_max = _saw_damage(report) and _isnum(pmin) and _isnum(pmax) and pmin >= pmax
    abuse = flag or pcs_invuln or pinned_at_max
    ch.append(("not_invulnerable", not abuse,
               "invulnerable-player evidence rejected (flag={}, pcs_invuln={}, pinned_at_max={})".format(
                   flag, pcs_invuln, pinned_at_max),
               FailureCode.COMBAT_INVULNERABILITY_ABUSE))
    return ch


def _dogfood(rep):
    """Prove logic now with in-memory records."""
    # VALID: min 63 < max 100, final 63 in range, 9 damage events, not invulnerable.
    good = CX._example_combat_completion()
    good_fails = [c for c in _check_scenario(good, strict=True) if not c[1]]
    rep.check("dogfood::valid_passes", not good_fails,
              "synthetic mutated-health record passes ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]),
              code=FailureCode.PLAYER_HEALTH_NO_MUTATION)
    # KNOWN-BAD 1: damage claimed but health pinned at max -> no mutation + invuln abuse.
    bad_nomut = CX._example_combat_completion(player_min_health=100.0, player_final_health=100.0,
                                              damage_events_seen=9)
    bad_nomut_fails = [c for c in _check_scenario(bad_nomut, strict=True) if not c[1]]
    rep.check("dogfood::no_mutation_rejected", len(bad_nomut_fails) > 0,
              "synthetic no-mutation record is rejected ({} check(s))".format(len(bad_nomut_fails)),
              code=FailureCode.PLAYER_HEALTH_NO_MUTATION)
    # KNOWN-BAD 2: invulnerable flag set even though health moved -> abuse rejected.
    bad_invuln = CX._example_combat_completion(invulnerable=True)
    bad_invuln_fails = [c for c in _check_scenario(bad_invuln, strict=True)
                        if not c[1] and c[3] == FailureCode.COMBAT_INVULNERABILITY_ABUSE]
    rep.check("dogfood::invulnerable_flag_rejected", len(bad_invuln_fails) > 0,
              "synthetic invulnerable-flagged record is rejected on the abuse check",
              code=FailureCode.COMBAT_INVULNERABILITY_ABUSE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", action="store_true", default=True)
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    files = sorted(COMPLETION_DIR.glob("cs_*.json")) if COMPLETION_DIR.is_dir() else []
    rep.check("player_health::evidence_present", len(files) > 0,
              "no combat completion evidence in {} (run the Wave-R combat matrix)".format(
                  CX.COMBAT_COMPLETION_REPORTS_REL),
              code=FailureCode.PLAYER_HEALTH_NO_MUTATION)

    bad = checked = 0
    for f in files:
        tag = f.stem
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("ph::{}::readable".format(tag), False, "unreadable: {}".format(e),
                      code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)
            continue
        checked += 1
        for name, ok, detail, code in _check_scenario(report, strict):
            if not ok:
                bad += 1
                rep.check("ph::{}::{}".format(tag, name), False, detail, code=code)

    if files:
        rep.check("player_health::all_mutated", bad == 0,
                  "{} player-health failure(s) across {} record(s)".format(bad, checked),
                  code=FailureCode.PLAYER_HEALTH_NO_MUTATION)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-player-health", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type=CX.RT_COMBAT_COMPLETION, records_total=len(files),
                            extra={"checked": checked, "evidence_present": bool(files)}))
    rep.write(COMPLETION_DIR, "validate_player_health_report.json")
    rep.print_summary("validate-player-health")
    print("[validate-player-health] {} record(s) checked; evidence_present={}".format(
        checked, bool(files)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
