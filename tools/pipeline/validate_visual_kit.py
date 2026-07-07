#!/usr/bin/env python3
"""validate_visual_kit.py — v1.5 schema gate (generated visual_kit records).

Discovers generated visual_kit records and runs each through
visual_kit_contract.validate_record. Fail-closed: zero records is a blocking failure
(not-yet-generated == not-done), so this gate goes green once Wave 2/3 emits
records. Schema *rejection* of bad records is proven by the negative-fixture
harness, not here.
"""

import argparse
import os
import sys

import visual_kit_contract as C
from failure_codes import FailureCode
from v1_5_schema_gate import run_schema_gate


def main(argv=None):
    ap = argparse.ArgumentParser(description="validate_visual_kit v1.5 schema gate.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    return run_schema_gate(
        "validate_visual_kit", "visual_kit", "wf.visual.kit_schema.v1", C.validate_record,
        ["procedural/generated/visual/kits"], FailureCode.VISUAL_KIT_SCHEMA_FAILURE, pack=args.pack, report_root="visual")


if __name__ == "__main__":
    sys.exit(main())
