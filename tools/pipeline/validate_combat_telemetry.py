#!/usr/bin/env python3
"""validate_combat_telemetry.py — WorldForge v1.8 CombatForge combat-telemetry gate.

Validates the live combat telemetry the runtime batch emits under
``DAMAGE_TELEMETRY_REPORTS_REL`` (cs_*.json): every telemetry report must carry a
non-empty events list of known COMBAT_EVENT_TYPES and — as runtime evidence of a
genuine combat_completed_runtime — must contain the full
COMPLETION_REQUIRED_COMBAT_EVENTS set INCLUDING ``combat.player.damage.taken``
(real damage landed). A telemetry stream that loaded a map with an NPC on it but
shows no player-damage / no completion is NOT combat and fails here
(COMBAT_DAMAGE_TELEMETRY_MISSING / COMBAT_NO_DAMAGE_EVENTS).

ANTI-FAKE-GREEN: the gate first DOGFOODS its own logic against a synthetic VALID
telemetry stream (must pass) and a synthetic KNOWN-BAD stream missing the
player-damage event (must be rejected), so the gate proves it constrains even
when no runtime evidence exists yet. It is then honestly FAIL-CLOSED: with no
real cs_*.json telemetry on disk the gate is RED under strict — there is nothing
to prove combat happened.

Acceptance: `python tools/pipeline/validate_combat_telemetry.py --pack encounter_loop_world --strict`.
Reports -> procedural/reports/combat/telemetry/validate_combat_telemetry_report.json
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

TELEMETRY_DIR = REPO_ROOT / CX.DAMAGE_TELEMETRY_REPORTS_REL
SKIP = {"validate_combat_telemetry_report.json"}
_DEFAULT_COMBAT_ROOT = REPO_ROOT / "procedural" / "reports" / "combat"


def _telemetry_dir(reports_dir):
    """--reports-dir > WF_COMBAT_REPORTS_DIR > committed default; returns the
    telemetry/ subdir so the gate can be pointed at a throwaway fixture dir."""
    base = Path(reports_dir or os.environ.get("WF_COMBAT_REPORTS_DIR") or _DEFAULT_COMBAT_ROOT)
    return base / "telemetry"


def _dogfood(rep, strict):
    """Prove the gate's logic constrains: valid telemetry passes, known-bad is
    rejected. Runs with no dependency on real evidence so the gate is honest even
    while the runtime evidence dir is empty."""
    good = CX._example_combat_telemetry()
    bad = CX.CONTRACTS["CombatTelemetry"][2]()  # completion telemetry missing the damage event
    good_fails = [c for c in CX.validate_combat_telemetry(good, strict=True, require_completion=True)
                  if not c[1]]
    bad_fails = [c for c in CX.validate_combat_telemetry(bad, strict=True, require_completion=True)
                 if not c[1]]
    rep.check("dogfood::valid_telemetry_passes", not good_fails,
              "valid combat telemetry passes strict/require_completion ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]),
              code=FailureCode.COMBAT_TELEMETRY_SCHEMA_FAILURE)
    rep.check("dogfood::known_bad_rejected", len(bad_fails) > 0,
              "known-bad telemetry (no player.damage.taken) is rejected",
              code=FailureCode.COMBAT_NO_DAMAGE_EVENTS)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--reports-dir", default=None,
                    help="override combat reports root (points telemetry/ at a fixture dir)")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    telemetry_dir = _telemetry_dir(args.reports_dir)

    # 1) Dogfood the gate logic (green regardless of real evidence).
    _dogfood(rep, strict)

    # 2) Real runtime evidence — fail-closed when absent.
    files = [f for f in sorted(telemetry_dir.glob("cs_*.json")) if f.name not in SKIP] \
        if telemetry_dir.is_dir() else []
    rep.check("telemetry::present", len(files) > 0,
              "no combat telemetry emitted under {} (run the combat runtime batch)".format(
                  CX.DAMAGE_TELEMETRY_REPORTS_REL),
              code=FailureCode.COMBAT_DAMAGE_TELEMETRY_MISSING)

    bad = 0
    for f in files:
        sid = f.stem
        try:
            tel = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("tel::{}::readable".format(sid), False, "unreadable: {}".format(e),
                      code=FailureCode.COMBAT_TELEMETRY_SCHEMA_FAILURE)
            continue
        for name, ok, detail, code in CX.validate_combat_telemetry(
                tel, strict=strict, require_completion=True):
            if not ok:
                bad += 1
                rep.check("tel::{}::{}".format(sid, name), False, detail, code=code)

    rep.check("telemetry::all_valid", bad == 0,
              "{} telemetry check failure(s) across {} reports".format(bad, len(files)),
              code=FailureCode.COMBAT_DAMAGE_TELEMETRY_MISSING)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-combat-telemetry", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type=CX.RT_COMBAT_TELEMETRY, records_total=len(files)))
    rep.write(telemetry_dir, "validate_combat_telemetry_report.json")
    rep.print_summary("validate-combat-telemetry")
    print("[validate-combat-telemetry] {} telemetry reports checked".format(len(files)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
