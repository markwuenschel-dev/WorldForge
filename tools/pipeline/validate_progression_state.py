#!/usr/bin/env python3
"""validate_progression_state.py — WorldForge v1.9 progression-state contract gate.

Loads every generated ProgressionState under
``procedural/generated/progression/progression/*.json`` and contract-validates
each with reward_contracts.validate_progression_state at strict=True (zero check
failures). This proves every persisted progression state on disk is schema-honest:
level matches the XP curve, progression_hash matches contents, and the save slot
is the dedicated WFProgression_State slot (never a combat/mission/npc slot).

ANTI-FAKE-GREEN: fail-closed. With zero progression states on disk the gate is RED
under strict — progression cannot be greened without real generated state. It also
DOGFOODS the validator against a synthetic known-bad (a progression state whose
hash no longer matches its contents) to prove the schema actually rejects drift.

Acceptance: `python tools/pipeline/validate_progression_state.py --pack encounter_loop_world --strict`.
Reports -> procedural/reports/progression/validate_progression_state_report.json
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

PROGRESSION_DIR = REPO_ROOT / "procedural/generated/progression/progression"
CODE = FailureCode.PROGRESSION_STATE_INVALID


def _dogfood(rep):
    """A valid progression state passes; one with a corrupted hash is rejected."""
    good = RX._example_progression_state()
    bad = RX._example_progression_state()
    bad["progression_hash"] = "prog:deadbeefdeadbeef"  # no longer matches contents
    good_fails = [c for c in RX.validate_progression_state(good, strict=True) if not c[1]]
    bad_fails = [c for c in RX.validate_progression_state(bad, strict=True) if not c[1]]
    rep.check("dogfood::valid_passes", not good_fails,
              "valid progression state passes strict ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]), code=CODE)
    rep.check("dogfood::hash_mismatch_rejected", len(bad_fails) > 0,
              "progression state with mismatched progression_hash is rejected", code=CODE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    files = sorted(PROGRESSION_DIR.glob("*.json")) if PROGRESSION_DIR.is_dir() else []
    rep.check("progression::present", len(files) > 0,
              "no generated progression states found (run generate_progression_state.py)",
              code=CODE)

    invalid = 0
    for f in files:
        try:
            state = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            invalid += 1
            rep.check("progression::{}::readable".format(f.stem), False,
                      "progression state unreadable", code=CODE)
            continue
        fails = [c for c in RX.validate_progression_state(state, strict=True) if not c[1]]
        if fails:
            invalid += 1
            rep.check("progression::{}::valid".format(f.stem), False,
                      "invalid progression state: {}".format([c[0] for c in fails][:4]), code=CODE)

    rep.check("progression::all_valid", invalid == 0,
              "{}/{} progression states invalid".format(invalid, len(files)), code=CODE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-progression-state", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type="wf.reward.progression_state_report.v1",
                            records_total=len(files), records_failed=invalid))
    rep.write(REPO_ROOT / RX.PROGRESSION_REPORTS_REL, "validate_progression_state_report.json")
    rep.print_summary("validate-progression-state")
    print("[validate-progression-state] {} progression state(s), {} invalid".format(
        len(files), invalid))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
