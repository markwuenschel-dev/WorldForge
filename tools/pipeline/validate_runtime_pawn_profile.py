#!/usr/bin/env python3
"""validate_runtime_pawn_profile.py — WorldForge v1.6 pawn profile gate (Agent 2B).

Validates every generated runtime pawn profile against the frozen contract:
real capsule dimensions, non-zero walk speed, an interaction component, declared
telemetry channels, and NO objective-teleport capability (a fake-green vector).

Usage:
    python tools/pipeline/validate_runtime_pawn_profile.py --profile default [--strict]
Writes: procedural/reports/runtime/pawns/validate_runtime_pawn_profile_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_pawn_contract as PC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 runtime pawn profile gate.")
    ap.add_argument("--profile", default="default")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pawn_profile", args.profile, strict=strict)
    d = REPO_ROOT / PC.PAWN_GENERATED_REL
    profiles = sorted(d.glob("*.json")) if d.is_dir() else []
    if not profiles:
        rep.error("no pawn profiles — run 'make runtime-pawn-profile' first")

    for p in profiles:
        obj = json.loads(p.read_text(encoding="utf-8"))
        pid = obj.get("pawn_profile_id", p.stem)
        for name, ok, detail, code in PC.validate_pawn_profile(obj, strict=strict):
            rep.check("{}::{}".format(pid, name), ok, detail, code=code)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-pawn-profile", pack=None, strict=strict,
                            status=rep.status, record_count=len(profiles),
                            report_type="wf.runtime.pawn_profile.v1"))
    rep.write(REPO_ROOT / PC.PAWN_REPORTS_REL, "validate_runtime_pawn_profile_report.json")
    rep.print_summary("validate-runtime-pawn-profile")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
