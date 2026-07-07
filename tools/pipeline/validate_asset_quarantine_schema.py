#!/usr/bin/env python3
"""validate_asset_quarantine_schema.py — v1.5 schema gate (generated quarantine_asset records).

Discovers generated quarantine_asset records and runs each through
quarantine_contract.validate_record. Fail-closed: zero records is a blocking failure
(not-yet-generated == not-done), so this gate goes green once Wave 2/3 emits
records. Schema *rejection* of bad records is proven by the negative-fixture
harness, not here.
"""

import argparse
import os
import sys

import quarantine_contract as C
from failure_codes import FailureCode
from v1_5_schema_gate import run_schema_gate


def main(argv=None):
    ap = argparse.ArgumentParser(description="validate_asset_quarantine_schema v1.5 schema gate.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    return run_schema_gate(
        "validate_asset_quarantine_schema", "quarantine_asset", "wf.asset.quarantine_schema.v1", C.validate_record,
        ["procedural/generated/assets/quarantine"], FailureCode.ASSET_QUARANTINE_SCHEMA_FAILURE, pack=args.pack, report_root="assets")


if __name__ == "__main__":
    sys.exit(main())
