#!/usr/bin/env python3
"""create_runtime_pawn_profile.py — WorldForge v1.6 pawn profile generator (Agent 2B).

Materializes the canonical, reusable runtime test pawn profile (the stable body
the UE runtime driver spawns and possesses across every map). One profile,
deterministic, validated against the frozen runtime_pawn_contract before write.

Usage:
    python tools/pipeline/create_runtime_pawn_profile.py --profile default [--strict]
Writes: procedural/generated/runtime/pawns/<pawn_profile_id>.json
        procedural/reports/runtime/pawns/create_runtime_pawn_profile_report.json
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
    ap = argparse.ArgumentParser(description="WorldForge v1.6 runtime pawn profile generator.")
    ap.add_argument("--profile", default="default")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pawn_profile", args.profile, strict=strict)
    profile = PC.default_profile()  # only "default" is defined in v1.6
    for name, ok, detail, code in PC.validate_pawn_profile(profile, strict=strict):
        rep.check(name, ok, detail, code=code)

    if rep.status != "fail":
        out = REPO_ROOT / PC.PAWN_GENERATED_REL
        out.mkdir(parents=True, exist_ok=True)
        (out / "{}.json".format(profile["pawn_profile_id"])).write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rep.finalize()
    rep.set_meta(build_meta(command="runtime-pawn-profile", pack=None, strict=strict,
                            status=rep.status, record_count=1,
                            report_type="wf.runtime.pawn_profile.v1",
                            extra={"pawn_profile_id": profile["pawn_profile_id"]}))
    rep.write(REPO_ROOT / PC.PAWN_REPORTS_REL, "create_runtime_pawn_profile_report.json")
    rep.print_summary("runtime-pawn-profile")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
