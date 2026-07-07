#!/usr/bin/env python3
"""validate_v1_5_taxonomy.py — v1.5 taxonomy registry gate.

Validates the static v1.5 registries (asset types, usage/biome/terrain/encounter
tags, license families, source adapters, package policies, visual profile types,
ownership + cover-height classes): no registry empty, no duplicate values. Unlike
the record-schema gates this needs no generated data, so it is green as soon as
the taxonomy is coherent.
"""

import argparse
import os
import sys
from pathlib import Path

import v1_5_taxonomy as T
from report_meta import build_meta
from validation_report import ValidationReport, strict_from_env

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "assets" / "validate_v1_5_taxonomy"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.5 taxonomy registries.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("registry", "v1_5_taxonomy", strict=strict)
    for cname, ok, detail, code in T.validate_taxonomy():
        rep.check(cname, ok, detail, code=code)

    n = len(getattr(T, "REGISTRIES", {}))
    rep.set_meta(build_meta(
        "validate-v1-5-taxonomy", pack=args.pack, strict=strict,
        report_type="wf.v1_5.taxonomy.v1", record_count=n, records_total=n,
        records_passed=n))
    rep.finalize()
    rep.write(REPORT_DIR, "validate_v1_5_taxonomy_report.json")
    rep.print_summary("validate-v1-5-taxonomy")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
