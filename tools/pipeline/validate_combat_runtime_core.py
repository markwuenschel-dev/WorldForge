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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / CX.COMBAT_COMPLETION_REPORTS_REL


def _check_record(rep, tag, report, strict):
    """Feed the frozen completion contract + telemetry-on-disk check for one record.

    Returns the number of failing checks recorded (0 == clean).
    """
    bad = 0
    for name, ok, detail, code in CX.validate_combat_completion_report(report, strict=strict):
        if not ok:
            bad += 1
            rep.check("core::{}::{}".format(tag, name), False, detail, code=code)
    if report.get("completion_class") == CX.SUCCESS_COMBAT_CLASS:
        tp = report.get("telemetry_path") or ""
        exists = bool(tp) and (REPO_ROOT / tp).is_file()
        if not exists:
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", action="store_true", default=True,
                    help="fail-closed when no runtime evidence is present (default on)")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # (a) dogfood the logic so the constraint is proven even with zero evidence.
    _dogfood(rep, strict)

    # (b) read the real (Wave-R) evidence — fail-closed if absent.
    files = sorted(COMPLETION_DIR.glob("cs_*.json")) if COMPLETION_DIR.is_dir() else []
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
        bad += _check_record(rep, tag, report, strict)
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
    rep.write(COMPLETION_DIR, "validate_combat_runtime_core_report.json")
    rep.print_summary("validate-combat-runtime-core")
    print("[validate-combat-runtime-core] {} completion record(s), {} success; evidence_present={}".format(
        len(files), success, bool(files)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
