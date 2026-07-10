#!/usr/bin/env python3
"""validate_progression_contracts.py — v1.9 progression contract-spine gate.

Dogfoods the InventoryState, ProgressionState, and UnlockState contracts: each
canonical valid example MUST pass under STRICT and its known-bad MUST fail.

Acceptance: ``make progression-contracts STRICT=1``.
Reports -> procedural/reports/progression/contracts/validate_progression_contracts_report.json
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _reward_contract_gate import run_gate
from report_meta import strict_from_env


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    sys.exit(run_gate("progression", "validate-progression-contracts", args.pack, strict,
                      "validate_progression_contracts_report.json"))


if __name__ == "__main__":
    main()
