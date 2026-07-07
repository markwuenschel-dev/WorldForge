#!/usr/bin/env python3
"""validate_asset_candidate.py — v1.5 schema gate (generated asset_candidate records).

Discovers generated asset_candidate records and runs each through
asset_candidate_contract.validate_record. Fail-closed: zero records is a blocking failure
(not-yet-generated == not-done), so this gate goes green once Wave 2/3 emits
records. Schema *rejection* of bad records is proven by the negative-fixture
harness, not here.
"""

import argparse
import os
import sys

import asset_candidate_contract as C
from failure_codes import FailureCode
from v1_5_schema_gate import run_schema_gate


def main(argv=None):
    ap = argparse.ArgumentParser(description="validate_asset_candidate v1.5 schema gate.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    return run_schema_gate(
        "validate_asset_candidate", "asset_candidate", "wf.asset.candidate_schema.v1", C.validate_record,
        ["procedural/generated/assets/candidates"], FailureCode.ASSET_CANDIDATE_SCHEMA_FAILURE, pack=args.pack, report_root="assets")


if __name__ == "__main__":
    sys.exit(main())
