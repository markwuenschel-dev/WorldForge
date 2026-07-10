#!/usr/bin/env python3
"""validate_unlock_state.py — WorldForge v1.9 unlock-state contract gate.

Loads every generated UnlockState under
``procedural/generated/progression/unlocks/*.json`` and contract-validates each
with reward_contracts.validate_unlock_state at strict=True (zero check failures).
This proves every durable unlock the next-mission generation can consume is
schema-honest: a known unlock_type, an explicit affects_generation boolean, and a
resolved source (source_mission_id + source_reward_event).

ANTI-FAKE-GREEN: fail-closed. With zero unlock states on disk the gate is RED under
strict. It also DOGFOODS the validator against a synthetic known-bad (an unlock
whose affects_generation is not an explicit boolean) to prove the schema rejects it.

Acceptance: `python tools/pipeline/validate_unlock_state.py --pack encounter_loop_world --strict`.
Reports -> procedural/reports/progression/validate_unlock_state_report.json
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

UNLOCKS_DIR = REPO_ROOT / "procedural/generated/progression/unlocks"
CODE = FailureCode.UNLOCK_STATE_INVALID


def _dogfood(rep):
    """A valid unlock passes; one with a non-boolean affects_generation is rejected."""
    good = RX._example_unlock_state()
    bad = RX._example_unlock_state(affects_generation="yes")
    good_fails = [c for c in RX.validate_unlock_state(good, strict=True) if not c[1]]
    bad_fails = [c for c in RX.validate_unlock_state(bad, strict=True) if not c[1]]
    rep.check("dogfood::valid_passes", not good_fails,
              "valid unlock state passes strict ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]), code=CODE)
    rep.check("dogfood::known_bad_rejected", len(bad_fails) > 0,
              "unlock state with non-boolean affects_generation is rejected", code=CODE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    files = sorted(UNLOCKS_DIR.glob("*.json")) if UNLOCKS_DIR.is_dir() else []
    rep.check("unlocks::present", len(files) > 0,
              "no generated unlock states found (run generate_progression_state.py)",
              code=CODE)

    invalid = 0
    for f in files:
        try:
            state = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            invalid += 1
            rep.check("unlocks::{}::readable".format(f.stem), False,
                      "unlock state unreadable", code=CODE)
            continue
        fails = [c for c in RX.validate_unlock_state(state, strict=True) if not c[1]]
        if fails:
            invalid += 1
            rep.check("unlocks::{}::valid".format(f.stem), False,
                      "invalid unlock state: {}".format([c[0] for c in fails][:4]), code=CODE)

    rep.check("unlocks::all_valid", invalid == 0,
              "{}/{} unlock states invalid".format(invalid, len(files)), code=CODE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-unlock-state", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type="wf.reward.unlock_state_report.v1",
                            records_total=len(files), records_failed=invalid))
    rep.write(REPO_ROOT / RX.PROGRESSION_REPORTS_REL, "validate_unlock_state_report.json")
    rep.print_summary("validate-unlock-state")
    print("[validate-unlock-state] {} unlock state(s), {} invalid".format(len(files), invalid))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
