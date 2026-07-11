#!/usr/bin/env python3
"""validate_tactical_profiles.py — v2.4 Wave 2 profile/role authoring gate.

Re-validates every generated tactical role + pressure profile from disk against
tactical_contracts AND performs the cross-record checks the schema-only contracts cannot:
the 3 required roles are all present, the 2 pressure profiles are present, each profile's
roles_allowed resolve to real generated roles, and each role's preferred/forbidden action
partition is coherent. Coverage: 3 roles, 2 profiles.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_tactical_profiles.py --strict
Reports -> procedural/reports/tactical/authoring/validate_tactical_profiles_report.json
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

GEN = REPO_ROOT / "procedural" / "generated" / "tactical"
ROLES_DIR = GEN / "roles"
PROFILES_DIR = GEN / "profiles"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "authoring"


def _load_all(d):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))}


def validate(rep):
    roles = _load_all(ROLES_DIR)
    profiles = _load_all(PROFILES_DIR)
    n = 0
    rep.check("count::roles_3", len(roles) == 3,
              "must have exactly 3 tactical roles (got {})".format(len(roles)),
              code=F.TACTICAL_ROLE_INVALID)
    rep.check("count::required_roles_present",
              all(r in roles for r in SP.ROLES),
              "roles must include sentinel/skirmisher/suppressor (got {})".format(sorted(roles)),
              code=F.TACTICAL_ROLE_INVALID)
    rep.check("count::profiles_2", len(profiles) == 2,
              "must have exactly 2 pressure profiles (got {})".format(len(profiles)),
              code=F.TACTICAL_PROFILE_INVALID)

    role_ids = set()
    for name, rec in roles.items():
        n += 1
        fails = [c for c in TC.validate_tactical_role_definition(rec, strict=True) if not c[1]]
        rep.check("role::{}::valid".format(name), len(fails) == 0,
                  "role invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_ROLE_INVALID)
        role_ids.add(rec.get("role_id"))

    for name, rec in profiles.items():
        n += 1
        fails = [c for c in TC.validate_tactical_behavior_profile(rec, strict=True) if not c[1]]
        rep.check("profile::{}::valid".format(name), len(fails) == 0,
                  "profile invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_PROFILE_INVALID)
        # cross-record: every role a profile allows must resolve to a real generated role.
        allowed = rec.get("roles_allowed") or []
        unresolved = [r for r in allowed if r not in role_ids]
        rep.check("profile::{}::roles_resolve".format(name), not unresolved,
                  "profile roles_allowed reference unknown roles: {}".format(unresolved),
                  code=F.TACTICAL_UNKNOWN_ROLE)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical profile/role authoring gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_profiles", strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-tactical-profiles", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.profile_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_tactical_profiles_report.json")
    rep.print_summary("validate-tactical-profiles")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
