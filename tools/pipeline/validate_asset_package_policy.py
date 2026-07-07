#!/usr/bin/env python3
"""validate_asset_package_policy.py — v1.5 package-policy INTEGRITY gate.

Over every catalog record, enforces the packaging safety rules of the v1.2 addendum
(delegated to ``validate_third_party_package_policy`` logic + ``external_asset_contract``
constants — not reimplemented):

  * no raw third-party redistribution — third-party content is pinned to the
    incorporated-project-content model and never standalone-redistributable
    (ASSET_STANDALONE_REDISTRIBUTION_FORBIDDEN);
  * external license metadata present on third-party records;
  * no absolute/cache-path leaks into packaged UE paths (ue_asset_path /
    ue_dependencies must be /Game refs — never a drive-absolute or quarantine-cache
    path) (ASSET_PACKAGE_POLICY_FAILURE / PACKAGE_ABSOLUTE_PATH_LEAK_FAILURE).

Zero-record policy: INTEGRITY gate — passes clean on zero records; record_count
reflects checks performed (>=1) so report-integrity's zero-record rule is honoured.
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import external_asset_contract as EAC
import mesh_contract as MC
# Delegate the third-party package-policy dict checks to the existing lane.
import validate_third_party_package_policy as _tp_policy
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_asset_package_policy"
REPORT_TYPE = "wf.asset.package_policy_report.v1"

_POLICY = FailureCode.ASSET_PACKAGE_POLICY_FAILURE
_REDIST = FailureCode.ASSET_STANDALONE_REDISTRIBUTION_FORBIDDEN
_LEAK = FailureCode.PACKAGE_ABSOLUTE_PATH_LEAK_FAILURE

_ABS_PATH = re.compile(r"^[a-zA-Z]:[\\/]")  # drive-absolute (D:/, C:\)
_CACHE_ANCHORS = tuple(a for a in asset_paths.QUARANTINE_ROOT_ANCHORS)


def _rel(p):
    return p.relative_to(REPO_ROOT).as_posix()


def _leaks(value):
    s = str(value or "").replace("\\", "/")
    if not s:
        return False
    if _ABS_PATH.match(str(value or "")):
        return True
    return any(anchor in s for anchor in _CACHE_ANCHORS)


def _check_record(rep, tag, rec):
    ok = True
    resolved = MC.resolve_ownership_class(rec)
    is_third_party = resolved == MC.OWNERSHIP_THIRD_PARTY or bool(rec.get("third_party_owned"))
    pp = rec.get("package_policy")

    if is_third_party:
        if isinstance(pp, dict):
            # Delegate the full dict-shaped policy battery to the existing lane.
            _tp_policy.check_external_record(rep, tag, rec)
        else:
            ok = rep.check("{}::package_usage_incorporated".format(tag),
                           pp == EAC.PACKAGE_USAGE_INCORPORATED,
                           "third-party package_policy must be {!r} (incorporated only, "
                           "never standalone), got {!r}".format(EAC.PACKAGE_USAGE_INCORPORATED, pp),
                           code=_REDIST) and ok
        ok = rep.check("{}::external_license_metadata".format(tag),
                       bool(rec.get("license_family")) and bool(
                           rec.get("license_url") or rec.get("license_snapshot")),
                       "third-party record must carry license_family + license_url/snapshot",
                       code=FailureCode.EXTERNAL_LICENSE_METADATA_FAILURE) and ok

    # absolute / cache-path leaks into packaged UE paths.
    leak_targets = [("ue_asset_path", rec.get("ue_asset_path"))]
    for i, d in enumerate(rec.get("ue_dependencies") or []):
        leak_targets.append(("ue_dependencies[{}]".format(i), d))
    leaked = [k for k, v in leak_targets if _leaks(v)]
    ok = rep.check("{}::no_absolute_or_cache_path_leak".format(tag), not leaked,
                   "packaged UE path(s) leak absolute/cache paths: {}".format(leaked),
                   code=_LEAK) and ok
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="v1.5 package-policy integrity gate.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("pack", args.pack or "all", strict=strict)
    records, parse_errors = discover_records([_rel(asset_paths.CATALOG_DIR)])
    for name, detail in parse_errors:
        rep.check("parse::{}".format(name), False, "unparseable catalog record: {}".format(detail),
                  code=_POLICY)

    n_pass = 0
    if not records and not parse_errors:
        rep.check("no_catalog_records_present", True,
                  "no catalog records yet (nothing to validate)")
    else:
        for name, rec in records:
            if _check_record(rep, name, rec if isinstance(rec, dict) else {}):
                n_pass += 1

    rep.finalize()
    rc = len(records) if records else len(rep.checks)
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status, record_count=rc,
        records_total=len(records), records_passed=n_pass,
        records_failed=max(0, len(records) - n_pass)))
    report_dir, filename = asset_paths.report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
