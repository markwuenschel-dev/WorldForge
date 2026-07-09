#!/usr/bin/env python3
"""validate_combat_completion.py — WorldForge v1.8 CombatForge combat-completion gate.

Validates every combat completion report under ``COMBAT_COMPLETION_REPORTS_REL``
(cs_*.json) against the CombatCompletionReport contract AND the anti-fake-green
honesty invariants baked into validate_combat_completion_report: a
combat_completed_runtime must be status=pass with damage_events_seen>0, health
mutated down (player_min_health < player_max_health), survived
(player_final_health>0), mission_completed=true, save_load_result=pass, a
telemetry_path, the 'survivable' band and no failure codes; a failed class must
own a failure code + owner. It then asserts the set of maps genuinely realized
WITH COMBAT (combat_contracts.runtime_realized_combat_maps — success + real
damage) is non-empty under --require-live, and that every success references a
telemetry file that actually exists on disk (genuine evidence).

ANTI-FAKE-GREEN: the gate DOGFOODS its logic against a synthetic VALID completion
(must pass) and a synthetic KNOWN-BAD success with zero damage / no health
mutation (must be rejected). It is then honestly FAIL-CLOSED: with zero completion
reports (and hence zero realized combat maps) the gate is RED under strict — a
combat realization cannot be greened without real runtime damage evidence.

Acceptance: `python tools/pipeline/validate_combat_completion.py --pack encounter_loop_world --strict`.
Reports -> procedural/reports/combat/completion/validate_combat_completion_report.json
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / CX.COMBAT_COMPLETION_REPORTS_REL
SKIP = {"validate_combat_completion_report.json", "combat_completion_rollup.json",
        "run_combat_runtime_batch_gate_report.json"}
_DEFAULT_COMBAT_ROOT = REPO_ROOT / "procedural" / "reports" / "combat"


def _combat_root(reports_dir):
    """Resolve the combat reports root: --reports-dir > WF_COMBAT_REPORTS_DIR >
    the committed default. Lets the gate be pointed at a throwaway fixture dir so
    the real evidence dir stays untouched (and honestly RED when empty)."""
    return Path(reports_dir or os.environ.get("WF_COMBAT_REPORTS_DIR") or _DEFAULT_COMBAT_ROOT)


def _body(r):
    """Per LOCKED contract §4 the completion cs_*.json carries a TOP-LEVEL
    ``damage_events`` list *alongside* the report fields — but the frozen
    COMBAT_COMPLETION_ALLOWED set does not list it, so under strict the frozen
    validator's no-unknown check would reject a genuine contract-shaped record.
    We validate the report body with damage_events stripped, and check the
    damage_events list separately (see _check_damage_events)."""
    if isinstance(r, dict) and "damage_events" in r:
        r = dict(r)
        r.pop("damage_events")
    return r


def _tp_exists(tp, base):
    """A success's telemetry_path must point at a real file. Resolve repo-relative
    (real evidence), absolute (fixtures), or under the active reports root's
    telemetry/ subdir (fixture dirs pointed via --reports-dir)."""
    if not tp:
        return False
    p = Path(tp)
    if p.is_absolute() and p.is_file():
        return True
    if (REPO_ROOT / tp).is_file():
        return True
    if (base / "telemetry" / p.name).is_file():
        return True
    return False


def _check_damage_events(rep, sid, r, strict):
    """Contract §4: the completion carries a TOP-LEVEL damage_events list, each a
    DamageEvent. A combat_completed_runtime must carry a NON-EMPTY list whose
    length equals damage_events_seen, and every event must pass the frozen
    DamageEvent contract (positive amount, consistent accounting). Returns the
    number of failing checks recorded."""
    bad = 0
    de = r.get("damage_events")
    success = r.get("completion_class") == CX.SUCCESS_COMBAT_CLASS
    if not isinstance(de, list):
        bad += 1
        rep.check("cmp::{}::damage_events_list".format(sid), False,
                  "completion must carry a top-level damage_events list (contract §4)",
                  code=FailureCode.DAMAGE_EVENT_MISSING)
        return bad
    if success and len(de) == 0:
        bad += 1
        rep.check("cmp::{}::damage_events_nonempty".format(sid), False,
                  "combat_completed_runtime requires a non-empty damage_events list",
                  code=FailureCode.COMBAT_NO_DAMAGE_EVENTS)
    csid = r.get("combat_scenario_id")
    for i, ev in enumerate(de):
        for name, ok, detail, code in CX.validate_damage_event(ev, strict=strict):
            if not ok:
                bad += 1
                rep.check("cmp::{}::de{}::{}".format(sid, i, name), False, detail, code=code)
        if isinstance(ev, dict) and ev.get("combat_scenario_id") not in (None, csid):
            bad += 1
            rep.check("cmp::{}::de{}::scenario_ref".format(sid, i), False,
                      "damage_event references {!r} not this scenario {!r}".format(
                          ev.get("combat_scenario_id"), csid),
                      code=FailureCode.DAMAGE_ACCOUNTING_INCONSISTENT)
    dev = r.get("damage_events_seen")
    if success and isinstance(dev, int) and dev != len(de):
        bad += 1
        rep.check("cmp::{}::damage_events_count_matches".format(sid), False,
                  "damage_events_seen ({}) must equal len(damage_events) ({})".format(dev, len(de)),
                  code=FailureCode.DAMAGE_ACCOUNTING_INCONSISTENT)
    return bad


def _dogfood(rep, strict):
    """Prove the gate's logic constrains: a valid completion passes, a known-bad
    success (zero damage / no health mutation) is rejected — independent of any
    real evidence on disk. Also dogfoods the top-level damage_events contract."""
    good = CX._example_combat_completion()
    bad = CX.CONTRACTS["CombatCompletionReport"][2]()  # success with 0 damage / no mutation
    good_fails = [c for c in CX.validate_combat_completion_report(good, strict=True) if not c[1]]
    bad_fails = [c for c in CX.validate_combat_completion_report(bad, strict=True) if not c[1]]
    rep.check("dogfood::valid_completion_passes", not good_fails,
              "valid combat completion passes strict ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]),
              code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)
    rep.check("dogfood::known_bad_rejected", len(bad_fails) > 0,
              "known-bad success (0 damage / no health mutation) is rejected",
              code=FailureCode.COMBAT_FAKE_SUCCESS)
    # Top-level damage_events dogfood: a valid DamageEvent passes, a zero-damage one is rejected.
    good_de = [c for c in CX.validate_damage_event(CX._example_damage_event(), strict=True) if not c[1]]
    bad_de = [c for c in CX.validate_damage_event(
        CX._example_damage_event(amount=0.0, health_after=72.0), strict=True) if not c[1]]
    rep.check("dogfood::damage_event_valid", not good_de,
              "valid top-level DamageEvent passes the frozen contract",
              code=FailureCode.DAMAGE_EVENT_SCHEMA_FAILURE)
    rep.check("dogfood::damage_event_zero_rejected", len(bad_de) > 0,
              "zero-amount DamageEvent is rejected (no fake damage)",
              code=FailureCode.COMBAT_ZERO_DAMAGE_FAKE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", dest="require_live", action="store_true", default=True)
    ap.add_argument("--no-require-live", dest="require_live", action="store_false")
    ap.add_argument("--reports-dir", default=None,
                    help="override combat reports root (points completion/ at a fixture dir)")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    base = _combat_root(args.reports_dir)
    completion_dir = base / "completion"

    # 1) Dogfood the gate logic (green regardless of real evidence).
    _dogfood(rep, strict)

    # 2) Real runtime evidence — fail-closed when absent.
    files = [f for f in sorted(completion_dir.glob("cs_*.json")) if f.name not in SKIP] \
        if completion_dir.is_dir() else []
    rep.check("completion::present", len(files) > 0,
              "no combat completion reports under {} (run the combat runtime batch)".format(
                  CX.COMBAT_COMPLETION_REPORTS_REL),
              code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)

    bad = success = 0
    for f in files:
        sid = f.stem
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("cmp::{}::readable".format(sid), False, "unreadable: {}".format(e),
                      code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)
            continue
        for name, ok, detail, code in CX.validate_combat_completion_report(_body(r), strict=strict):
            if not ok:
                bad += 1
                rep.check("cmp::{}::{}".format(sid, name), False, detail, code=code)
        # Contract §4: validate the top-level damage_events list carried alongside.
        bad += _check_damage_events(rep, sid, r, strict)
        if r.get("completion_class") == CX.SUCCESS_COMBAT_CLASS:
            success += 1
            # A genuine success must point at a telemetry file that actually exists
            # and carry non-empty evidence_paths — no phantom evidence.
            tp = r.get("telemetry_path") or ""
            if not _tp_exists(tp, base):
                bad += 1
                rep.check("cmp::{}::telemetry_on_disk".format(sid), False,
                          "success telemetry_path missing on disk: {}".format(tp),
                          code=FailureCode.COMBAT_DAMAGE_TELEMETRY_MISSING)
            if not (isinstance(r.get("evidence_paths"), list) and r["evidence_paths"]):
                bad += 1
                rep.check("cmp::{}::evidence_present".format(sid), False,
                          "success carries no evidence_paths",
                          code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)

    rep.check("completion::all_valid", bad == 0,
              "{} completion check failure(s) across {} reports".format(bad, len(files)),
              code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)

    # 3) Realized-combat-maps assertion (single source of truth with the batch writer).
    realized = CX.runtime_realized_combat_maps(completion_dir)
    if args.require_live:
        rep.check("completion::realized_maps_nonempty", len(realized) > 0,
                  "no maps realized with real runtime combat damage (require-live)",
                  code=FailureCode.COMBAT_RUNTIME_SPAWN_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-combat-completion", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type=CX.RT_COMBAT_COMPLETION, records_total=len(files),
                            extra={"success": success, "realized_maps": sorted(realized)}))
    rep.write(completion_dir, "validate_combat_completion_report.json")
    rep.print_summary("validate-combat-completion")
    print("[validate-combat-completion] {} completion reports, {} success, {} realized map(s)".format(
        len(files), success, len(realized)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
