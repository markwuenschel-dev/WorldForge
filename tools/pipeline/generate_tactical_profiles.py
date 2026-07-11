#!/usr/bin/env python3
"""generate_tactical_profiles.py — v2.4 Wave 2 profile/role authoring (Agent 2).

Generates the 3 bounded tactical roles (sentinel / skirmisher / suppressor) and the 2
tactical pressure profiles (baseline_tactical / high_pressure_tactical) from tactical_spec.
Deterministic; every record is validated against tactical_contracts before it is written —
generation never emits a record its own contract would reject.

Deliverables (handoff §14 Wave 2):
    procedural/generated/tactical/roles/*.json
    procedural/generated/tactical/profiles/*.json
    procedural/reports/tactical/authoring/profile_authoring_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_tactical_profiles.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
import tactical_spec as SP
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

ROLES_DIR = REPO_ROOT / "procedural" / "generated" / "tactical" / "roles"
PROFILES_DIR = REPO_ROOT / "procedural" / "generated" / "tactical" / "profiles"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "authoring"


def _write(d, name, obj):
    d.mkdir(parents=True, exist_ok=True)
    (d / (name + ".json")).write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def generate(rep):
    n = 0
    for role in SP.ROLES:
        rec = SP.role_definition(role)
        fails = [c for c in TC.validate_tactical_role_definition(rec, strict=True) if not c[1]]
        rep.check("role::{}::valid".format(role), len(fails) == 0,
                  "role invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_ROLE_INVALID)
        _write(ROLES_DIR, role, rec)
        n += 1
    for profile in SP.PROFILE_IDS:
        rec = SP.behavior_profile(profile)
        fails = [c for c in TC.validate_tactical_behavior_profile(rec, strict=True) if not c[1]]
        rep.check("profile::{}::valid".format(profile), len(fails) == 0,
                  "profile invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_PROFILE_INVALID)
        _write(PROFILES_DIR, rec["profile_id"], rec)
        n += 1
    rep.check("count::roles_3", len(SP.ROLES) == 3, "must generate 3 tactical roles",
              code=F.TACTICAL_ROLE_INVALID)
    rep.check("count::profiles_2", len(SP.PROFILE_IDS) == 2,
              "must generate 2 tactical pressure profiles", code=F.TACTICAL_PROFILE_INVALID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical profile/role authoring.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_profile_authoring", strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-tactical-profiles", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.profile_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "profile_authoring_report.json")
    rep.print_summary("generate-tactical-profiles")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
