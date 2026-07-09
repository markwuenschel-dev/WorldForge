#!/usr/bin/env python3
"""validate_combat_runtime_core.py — WorldForge v1.8 CombatForge runtime-core gate.

Proves each combat completion report (cs_*.json) is structurally a GENUINE runtime
combat record, not a fabricated green. Every record is validated against the frozen
CombatCompletionReport contract (CX.validate_combat_completion_report), whose success
class already demands damage_events_seen>0, health mutated (player_min<player_max),
mission_completed=true, and save/load pass. On top of that this gate confirms every
success report points at a telemetry file that actually exists on disk.

This is the runtime counterpart to the combat schema-spine gate: it reads the LIVE
evidence the Wave-R UE matrix emits, not authoring data. Until that matrix has run
the evidence dir is empty and this gate is HONESTLY FAIL-CLOSED (RED) — never a
vacuous pass. Its constraint logic is still proven now by dogfooding a synthetic
VALID record (passes) and a synthetic KNOWN-BAD record (rejected).

Acceptance: `python tools/pipeline/validate_combat_runtime_core.py --pack encounter_loop_world --strict`.
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
_DEFAULT_COMBAT_ROOT = REPO_ROOT / "procedural" / "reports" / "combat"


def _combat_root(reports_dir):
    """--reports-dir > WF_COMBAT_REPORTS_DIR > committed default. Lets the gate
    read a throwaway fixture dir while the real evidence dir stays untouched."""
    return Path(reports_dir or os.environ.get("WF_COMBAT_REPORTS_DIR") or _DEFAULT_COMBAT_ROOT)


def _body(r):
    """Strip the top-level ``damage_events`` list (contract §4) before the frozen
    completion body-check, whose no-unknown set doesn't list it; the list itself is
    validated separately in _check_record."""
    if isinstance(r, dict) and "damage_events" in r:
        r = dict(r)
        r.pop("damage_events")
    return r


def _tp_exists(tp, base):
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


def _check_record(rep, tag, report, strict, base):
    """Feed the frozen completion contract (body) + the top-level damage_events
    contract + telemetry-on-disk check for one record.

    Returns the number of failing checks recorded (0 == clean).
    """
    bad = 0
    for name, ok, detail, code in CX.validate_combat_completion_report(_body(report), strict=strict):
        if not ok:
            bad += 1
            rep.check("core::{}::{}".format(tag, name), False, detail, code=code)
    # Contract §4: the completion carries a TOP-LEVEL damage_events list.
    de = report.get("damage_events")
    success = report.get("completion_class") == CX.SUCCESS_COMBAT_CLASS
    if not isinstance(de, list):
        bad += 1
        rep.check("core::{}::damage_events_list".format(tag), False,
                  "completion must carry a top-level damage_events list (contract §4)",
                  code=FailureCode.DAMAGE_EVENT_MISSING)
    else:
        if success and len(de) == 0:
            bad += 1
            rep.check("core::{}::damage_events_nonempty".format(tag), False,
                      "combat_completed_runtime requires a non-empty damage_events list",
                      code=FailureCode.COMBAT_NO_DAMAGE_EVENTS)
        for i, ev in enumerate(de):
            for name, ok, detail, code in CX.validate_damage_event(ev, strict=strict):
                if not ok:
                    bad += 1
                    rep.check("core::{}::de{}::{}".format(tag, i, name), False, detail, code=code)
        dev = report.get("damage_events_seen")
        if success and isinstance(dev, int) and dev != len(de):
            bad += 1
            rep.check("core::{}::damage_events_count_matches".format(tag), False,
                      "damage_events_seen ({}) must equal len(damage_events) ({})".format(dev, len(de)),
                      code=FailureCode.DAMAGE_ACCOUNTING_INCONSISTENT)
    if success:
        tp = report.get("telemetry_path") or ""
        if not _tp_exists(tp, base):
            bad += 1
            rep.check("core::{}::telemetry_on_disk".format(tag), False,
                      "success telemetry_path missing on disk: {!r}".format(tp),
                      code=FailureCode.COMBAT_DAMAGE_TELEMETRY_MISSING)
    return bad


def _dogfood(rep, strict):
    """Prove the constraint logic now: a synthetic VALID record must pass, a
    synthetic KNOWN-BAD record (success class with zero damage events and no
    health mutation) must be rejected. Runs entirely in-memory."""
    valid = CX._example_combat_completion()
    valid_fails = [c for c in CX.validate_combat_completion_report(valid, strict=True) if not c[1]]
    rep.check("dogfood::valid_passes", not valid_fails,
              "synthetic valid completion passes ({})".format(
                  "0 fail" if not valid_fails else [c[0] for c in valid_fails][:4]),
              code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)
    # success class but damage_events_seen=0 and player_min_health==max -> fake green.
    bad = CX._example_combat_completion(damage_events_seen=0, player_min_health=100.0)
    bad_fails = [c for c in CX.validate_combat_completion_report(bad, strict=True) if not c[1]]
    rep.check("dogfood::known_bad_rejected", len(bad_fails) > 0,
              "synthetic zero-damage/no-mutation success is rejected ({} check(s) fired)".format(
                  len(bad_fails)),
              code=FailureCode.COMBAT_FAKE_SUCCESS)
    # Top-level damage_events (contract §4): valid event passes, zero-amount rejected.
    good_de = [c for c in CX.validate_damage_event(CX._example_damage_event(), strict=True) if not c[1]]
    bad_de = [c for c in CX.validate_damage_event(
        CX._example_damage_event(amount=0.0, health_after=72.0), strict=True) if not c[1]]
    rep.check("dogfood::damage_event_valid", not good_de,
              "valid top-level DamageEvent passes the frozen contract",
              code=FailureCode.DAMAGE_EVENT_SCHEMA_FAILURE)
    rep.check("dogfood::damage_event_zero_rejected", len(bad_de) > 0,
              "zero-amount DamageEvent is rejected", code=FailureCode.COMBAT_ZERO_DAMAGE_FAKE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", action="store_true", default=True,
                    help="fail-closed when no runtime evidence is present (default on)")
    ap.add_argument("--reports-dir", default=None,
                    help="override combat reports root (points completion/ at a fixture dir)")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    base = _combat_root(args.reports_dir)
    completion_dir = base / "completion"

    # (a) dogfood the logic so the constraint is proven even with zero evidence.
    _dogfood(rep, strict)

    # (b) read the real (Wave-R) evidence — fail-closed if absent.
    files = sorted(completion_dir.glob("cs_*.json")) if completion_dir.is_dir() else []
    rep.check("runtime_core::evidence_present", len(files) > 0,
              "no combat completion evidence in {} (run the Wave-R combat matrix)".format(
                  CX.COMBAT_COMPLETION_REPORTS_REL),
              code=FailureCode.COMBAT_RUNTIME_SPAWN_FAILURE)

    bad = success = 0
    for f in files:
        tag = f.stem
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("core::{}::readable".format(tag), False, "unreadable: {}".format(e),
                      code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)
            continue
        bad += _check_record(rep, tag, report, strict, base)
        if report.get("completion_class") == CX.SUCCESS_COMBAT_CLASS:
            success += 1

    if files:
        rep.check("runtime_core::all_genuine", bad == 0,
                  "{} runtime-core check failure(s) across {} record(s)".format(bad, len(files)),
                  code=FailureCode.COMBAT_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-combat-runtime-core", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type=CX.RT_COMBAT_COMPLETION, records_total=len(files),
                            extra={"success": success, "evidence_present": bool(files)}))
    rep.write(completion_dir, "validate_combat_runtime_core_report.json")
    rep.print_summary("validate-combat-runtime-core")
    print("[validate-combat-runtime-core] {} completion record(s), {} success; evidence_present={}".format(
        len(files), success, bool(files)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
