#!/usr/bin/env python3
"""validate_hazard_combat.py — WorldForge v1.8 CombatForge hazard-damage gate.

Proves that where a combat profile declares a HAZARD damage source, the hazard
actually dealt damage at runtime. For every completion record whose hazard damage
was expected (hazard_damage_result is not 'skipped'), this gate asserts against the
LIVE evidence that at least one DamageEvent with source_type='hazard' and amount>0
landed with internally-consistent accounting (health_after == max(0, health_before -
amount)); otherwise HAZARD_DAMAGE_FAILURE. Every referenced hazard DamageEvent is run
through the frozen DamageEvent contract so a fabricated record cannot pass.

Scenarios that declare NO hazard source (hazard_damage_result == 'skipped') are
'skipped', not failed — hazard combat is a per-profile surface, not universal.

Until the Wave-R UE matrix has emitted evidence the completion dir is empty and this
gate is HONESTLY FAIL-CLOSED (RED); its logic is still proven now by dogfooding a
synthetic VALID hazard record (passes) and a synthetic KNOWN-BAD record (rejected).

Acceptance: `python tools/pipeline/validate_hazard_combat.py --pack encounter_loop_world --strict`.
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
_SKIPPED_RESULTS = (None, "skipped", "not_implemented")
_DEFAULT_COMBAT_ROOT = REPO_ROOT / "procedural" / "reports" / "combat"


def _combat_root(reports_dir):
    """--reports-dir > WF_COMBAT_REPORTS_DIR > committed default."""
    return Path(reports_dir or os.environ.get("WF_COMBAT_REPORTS_DIR") or _DEFAULT_COMBAT_ROOT)


def _hazard_expected(report):
    """A scenario expects hazard damage iff its hazard_damage_result is a real
    (non-skipped) result — i.e. the profile declared a hazard damage source."""
    return report.get("hazard_damage_result") not in _SKIPPED_RESULTS


def _load_damage_events(report):
    """Per LOCKED contract §4 the completion cs_*.json carries a TOP-LEVEL
    ``damage_events`` list — read it directly (NOT from the telemetry stream,
    which carries only an ``events`` list of event-type markers)."""
    evs = report.get("damage_events")
    return evs if isinstance(evs, list) else []


def _check_scenario(report, damage_events, strict):
    """Pure logic for one hazard-expecting scenario."""
    ch = []
    hazard_evs = [de for de in damage_events
                  if isinstance(de, dict) and de.get("source_type") == "hazard"]
    # Each hazard event must be a genuine, accounting-consistent DamageEvent.
    for i, de in enumerate(hazard_evs):
        for name, ok, detail, code in CX.validate_damage_event(de, strict=strict):
            if not ok:
                ch.append(("hz{}::{}".format(i, name), ok, detail, code))
    positive = [de for de in hazard_evs
                if CX.RS.is_number(de.get("amount")) and de.get("amount") > 0]
    ch.append(("hazard_damage_present", len(positive) > 0,
               "profile declared a hazard source but no positive-amount hazard DamageEvent landed",
               FailureCode.HAZARD_DAMAGE_FAILURE))
    ch.append(("hazard_result_pass", report.get("hazard_damage_result") == "pass",
               "hazard_damage_result must be 'pass' for a hazard-source scenario",
               FailureCode.HAZARD_DAMAGE_FAILURE))
    return ch


def _dogfood(rep):
    """Prove logic now with in-memory records."""
    good_report = CX._example_combat_completion(hazard_damage_result="pass")
    good_events = [CX._example_damage_event(source_type="hazard", damage_type="hazard_zone",
                                            source_id="hz_field_0")]
    good_fails = [c for c in _check_scenario(good_report, good_events, strict=True) if not c[1]]
    rep.check("dogfood::valid_passes", not good_fails,
              "synthetic hazard scenario passes ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]),
              code=FailureCode.HAZARD_DAMAGE_FAILURE)
    # KNOWN-BAD: hazard expected, but the only damage event is npc_pressure -> no hazard damage.
    bad_report = CX._example_combat_completion(hazard_damage_result="pass")
    bad_events = [CX._example_damage_event()]  # source_type=npc_pressure
    bad_fails = [c for c in _check_scenario(bad_report, bad_events, strict=True) if not c[1]]
    rep.check("dogfood::known_bad_rejected", len(bad_fails) > 0,
              "synthetic hazard-declared-but-no-hazard-damage scenario is rejected ({} check(s))".format(
                  len(bad_fails)),
              code=FailureCode.HAZARD_DAMAGE_FAILURE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", action="store_true", default=True)
    ap.add_argument("--reports-dir", default=None,
                    help="override combat reports root (points completion/ at a fixture dir)")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    base = _combat_root(args.reports_dir)
    completion_dir = base / "completion"

    _dogfood(rep)

    files = sorted(completion_dir.glob("cs_*.json")) if completion_dir.is_dir() else []
    rep.check("hazard::evidence_present", len(files) > 0,
              "no combat completion evidence in {} (run the Wave-R combat matrix)".format(
                  CX.COMBAT_COMPLETION_REPORTS_REL),
              code=FailureCode.HAZARD_DAMAGE_FAILURE)

    bad = applicable = skipped = 0
    for f in files:
        tag = f.stem
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("hazard::{}::readable".format(tag), False, "unreadable: {}".format(e),
                      code=FailureCode.HAZARD_DAMAGE_FAILURE)
            continue
        if not _hazard_expected(report):
            skipped += 1
            rep.skip("hazard::{}::not_applicable".format(tag), "scenario declares no hazard source")
            continue
        applicable += 1
        for name, ok, detail, code in _check_scenario(report, _load_damage_events(report), strict):
            if not ok:
                bad += 1
                rep.check("hazard::{}::{}".format(tag, name), False, detail, code=code)

    if files:
        rep.check("hazard::all_ok", bad == 0,
                  "{} hazard-damage failure(s) across {} hazard scenario(s)".format(bad, applicable),
                  code=FailureCode.HAZARD_DAMAGE_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-hazard-combat", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type=CX.RT_COMBAT_COMPLETION, records_total=len(files),
                            extra={"applicable": applicable, "skipped": skipped,
                                   "evidence_present": bool(files)}))
    rep.write(completion_dir, "validate_hazard_combat_report.json")
    rep.print_summary("validate-hazard-combat")
    print("[validate-hazard-combat] {} record(s), {} hazard-applicable, {} skipped; evidence_present={}".format(
        len(files), applicable, skipped, bool(files)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
