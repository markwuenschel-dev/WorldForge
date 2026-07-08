#!/usr/bin/env python3
"""validate_v1_6_taxonomy.py — WorldForge v1.6 taxonomy integrity gate.

Runs v1_6_taxonomy.validate_taxonomy() and emits the canonical report. Fails if
any runtime registry is empty, has duplicates, or the archetype→verb map is
incoherent. Mirrors validate_failure_codes / the v1.5 taxonomy gate.

Usage:
    python tools/pipeline/validate_v1_6_taxonomy.py [--strict]
Writes: procedural/reports/runtime/taxonomy/validate_v1_6_taxonomy_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import v1_6_taxonomy as TAX
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORTS_REL = "procedural/reports/runtime/taxonomy"


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 taxonomy integrity gate.")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("taxonomy", "v1_6", strict=strict)
    results = TAX.validate_taxonomy()
    for name, ok, detail, code in results:
        rep.check(name, ok, detail, code=code)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-v1-6-taxonomy", pack=None, strict=strict,
                            status=rep.status, record_count=len(TAX.REGISTRIES),
                            report_type="wf.runtime.taxonomy.v1",
                            extra={"registries": len(TAX.REGISTRIES),
                                   "checks": len(results)}))
    rep.write(REPO_ROOT / REPORTS_REL, "validate_v1_6_taxonomy_report.json")
    rep.print_summary("validate-v1-6-taxonomy")
    print("[validate-v1-6-taxonomy] {} registries, {} checks".format(
        len(TAX.REGISTRIES), len(results)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
