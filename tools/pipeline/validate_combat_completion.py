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


def _dogfood(rep, strict):
    """Prove the gate's logic constrains: a valid completion passes, a known-bad
    success (zero damage / no health mutation) is rejected — independent of any
    real evidence on disk."""
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", dest="require_live", action="store_true", default=True)
    ap.add_argument("--no-require-live", dest="require_live", action="store_false")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # 1) Dogfood the gate logic (green regardless of real evidence).
    _dogfood(rep, strict)

    # 2) Real runtime evidence — fail-closed when absent.
    files = [f for f in sorted(COMPLETION_DIR.glob("cs_*.json")) if f.name not in SKIP] \
        if COMPLETION_DIR.is_dir() else []
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
        for name, ok, detail, code in CX.validate_combat_completion_report(r, strict=strict):
            if not ok:
                bad += 1
                rep.check("cmp::{}::{}".format(sid, name), False, detail, code=code)
        if r.get("completion_class") == CX.SUCCESS_COMBAT_CLASS:
            success += 1
            # A genuine success must point at a telemetry file that actually exists
            # and carry non-empty evidence_paths — no phantom evidence.
            tp = r.get("telemetry_path") or ""
            if not (tp and (REPO_ROOT / tp).is_file()):
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
    realized = CX.runtime_realized_combat_maps(COMPLETION_DIR)
    if args.require_live:
        rep.check("completion::realized_maps_nonempty", len(realized) > 0,
                  "no maps realized with real runtime combat damage (require-live)",
                  code=FailureCode.COMBAT_RUNTIME_SPAWN_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-combat-completion", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type=CX.RT_COMBAT_COMPLETION, records_total=len(files),
                            extra={"success": success, "realized_maps": sorted(realized)}))
    rep.write(COMPLETION_DIR, "validate_combat_completion_report.json")
    rep.print_summary("validate-combat-completion")
    print("[validate-combat-completion] {} completion reports, {} success, {} realized map(s)".format(
        len(files), success, len(realized)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
