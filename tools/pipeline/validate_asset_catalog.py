#!/usr/bin/env python3
"""validate_asset_catalog.py — v1.5 catalog INTEGRITY gate (+ legacy YAML mode).

Primary (v1.5) mode: ``--pack <id> [--strict]`` runs an integrity gate over every
generated ``AssetCatalogRecord``:

  * schema-valid via ``asset_catalog_contract.validate_record`` (ownership/license/
    lifecycle coherence, single-sourced — third_party => external_licensed True and
    repair/destroy PROTECTED);
  * ownership resolves (delegated to ``mesh_contract.resolve_ownership_class``, the
    same resolver ``validate_external_asset_ownership`` uses — not reimplemented);
  * ``ue_dependencies`` resolvable (each a /Game or /Script reference), no orphan.

Legacy mode: ``--catalog <path.yaml>`` preserves the pre-v1.5 asset-catalog YAML
validator so existing Makefile targets keep working unchanged.

Zero-record policy: INTEGRITY gate — passes clean on zero records; record_count
reflects checks performed (>=1) so report-integrity's zero-record rule is honoured.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import asset_catalog_contract as CC
import mesh_contract as MC
# Imported to delegate ownership semantics to the same module the external-asset
# ownership lane uses (kept as the single source of ownership truth).
import validate_external_asset_ownership as _ext_ownership_lane  # noqa: F401
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_asset_catalog"
REPORT_TYPE = "wf.asset.catalog_report.v1"


def _rel(p):
    return p.relative_to(REPO_ROOT).as_posix()


def _dep_resolvable(dep):
    return isinstance(dep, str) and (dep.startswith("/Game/") or dep.startswith("/Script/"))


def _check_record(rep, tag, rec):
    ok = True
    for cname, cok, detail, code in CC.validate_record(rec, strict=True):
        ok = rep.check("{}::{}".format(tag, cname), cok, detail, code=code) and ok
    # ownership resolves (delegated resolver).
    resolved = MC.resolve_ownership_class(rec)
    ok = rep.check("{}::ownership_resolves".format(tag), resolved is not None,
                   "ownership unresolvable/ambiguous",
                   code=FailureCode.ASSET_OWNERSHIP_FAILURE) and ok
    # ue_dependencies resolvable, no orphan references.
    deps = rec.get("ue_dependencies")
    if deps:
        bad = [d for d in deps if not _dep_resolvable(d)]
        ok = rep.check("{}::ue_dependencies_resolvable".format(tag), not bad,
                       "unresolvable ue_dependencies (orphan refs): {}".format(bad),
                       code=FailureCode.ASSET_DEPENDENCY_FAILURE) and ok
    return ok


def _run_v1_5(pack, strict):
    rep = ValidationReport("pack", pack or "all", strict=strict)
    records, parse_errors = discover_records([_rel(asset_paths.CATALOG_DIR)])
    for name, detail in parse_errors:
        rep.check("parse::{}".format(name), False, "unparseable catalog record: {}".format(detail),
                  code=FailureCode.ASSET_CATALOG_FAILURE)

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
        COMMAND.replace("_", "-"), pack=pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status, record_count=rc,
        records_total=len(records), records_passed=n_pass,
        records_failed=max(0, len(records) - n_pass)))
    report_dir, filename = asset_paths.report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    return rep.exit_code


def _run_legacy_yaml(catalog_arg):
    """Preserve the pre-v1.5 asset-catalog YAML validator (Makefile back-compat)."""
    try:
        import yaml
    except ImportError:
        sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
        return 2
    catalog_path = Path(catalog_arg)
    if not catalog_path.is_absolute():
        catalog_path = REPO_ROOT / catalog_path
    if not catalog_path.is_file():
        print("ERROR: catalog not found: {}".format(catalog_path))
        return 1
    try:
        with catalog_path.open("r", encoding="utf-8") as fh:
            catalog = yaml.safe_load(fh)
    except Exception as exc:
        print("ERROR: failed to parse YAML: {}".format(exc))
        return 1
    if not isinstance(catalog, dict):
        print("ERROR: catalog did not parse to a mapping")
        return 1

    categories = catalog.get("categories", {})
    failures = []
    print("CATALOG: {}".format(catalog.get("catalog_id", "<missing>")))
    if not catalog.get("catalog_id"):
        failures.append("missing catalog_id")
    if not catalog.get("biome"):
        failures.append("missing biome")
    empty_cats = [k for k, v in categories.items() if isinstance(v, dict) and not v.get("assets")]
    if empty_cats:
        failures.append("empty categories: {}".format(empty_cats))
    seen = {}
    for cat_name, cat_data in categories.items():
        if not isinstance(cat_data, dict):
            continue
        for asset in cat_data.get("assets", []):
            if asset in seen:
                failures.append("duplicate asset {} in {} and {}".format(asset, seen[asset], cat_name))
            seen[asset] = cat_name
    bad_paths = [a for a in seen if not a.startswith("/Game/")]
    if bad_paths:
        failures.append("bad asset paths: {}".format(bad_paths))
    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print("  - {}".format(f))
        return 1
    print("RESULT: PASS")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="v1.5 asset catalog integrity gate (+ legacy YAML mode).")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--catalog", default=None, help="legacy: path to a v0.x catalog YAML")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    if args.catalog and not args.pack:
        return _run_legacy_yaml(args.catalog)
    return _run_v1_5(args.pack, strict_from_env())


if __name__ == "__main__":
    sys.exit(main())
