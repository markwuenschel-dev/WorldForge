#!/usr/bin/env python3
"""validate_asset_dependencies.py — WorldForge v1.5 Wave-3 dependency + leak gate.

Checks the texture/material/map dependency closure across the catalog + the
realized cover bindings, and guards against external-cache / absolute-path leaks:

  * every catalog record's declared ue_dependencies resolve to an approved
    /Game owned root (no quarantine/Temp/Bake/absolute leaks)  (ASSET_DEPENDENCY_FAILURE)
  * every cover binding's ue_asset_path is an approved owned final path, never a
    quarantine/cache path                                       (ASSET_DEPENDENCY_FAILURE)
  * no binding/catalog path leaks an absolute disk or asset-cache location
                                                                (PACKAGE_ABSOLUTE_PATH_LEAK_FAILURE)

This is a schema/plan-level dependency audit (headless-valid now): it does not
require a live UE run — a dependency that points outside the owned tree is a
defect whether or not the asset has been imported yet.

Usage:
    python tools/pipeline/validate_asset_dependencies.py --pack encounter_loop_world [--strict]
Report: wf.realization.asset_dependency_validation.v1
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import mesh_contract as MC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_asset_dependencies"
REPORT_TYPE = "wf.realization.asset_dependency_validation.v1"

# Substrings that must never appear in a shipped dependency/asset path.
ABSOLUTE_LEAK_MARKERS = ("WorldForgeAssetCache", "_Quarantine", ":/", ":\\",
                         "/Users/", "C:", "D:")


def _leaks_absolute(path):
    s = str(path or "")
    return any(m in s for m in ABSOLUTE_LEAK_MARKERS)


def load_catalog_records():
    out = []
    recs, _e = discover_records(
        [asset_paths.CATALOG_DIR.relative_to(REPO_ROOT).as_posix()])
    for name, r in recs:
        if isinstance(r, dict) and r.get("asset_id"):
            out.append((name, r))
    return out


def load_bindings():
    out = []
    base = asset_paths.COVER_BINDINGS_DIR
    if base.is_dir():
        for p in sorted(base.glob("*.json")):
            try:
                b = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            out.append((p.name, b))
    return out


def load_owned_specs():
    out = []
    base = asset_paths.OWNED_COVER_DIR
    if base.is_dir():
        for p in sorted(base.glob("*.json")):
            try:
                out.append((p.name, json.loads(p.read_text(encoding="utf-8"))))
            except Exception:  # noqa: BLE001
                continue
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 asset-dependency gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_catalog_records()
    bindings = load_bindings()
    owned = load_owned_specs()

    rep.check("dependency_surface_present", bool(bindings or owned or catalog),
              "no bindings, owned baselines, or catalog records to audit — run "
              "the Wave-3 generators first",
              code=FailureCode.ASSET_DEPENDENCY_FAILURE)

    n = 0
    # Catalog dependency closure + leak checks.
    for name, rec in catalog:
        aid = rec.get("asset_id")
        for dep in rec.get("ue_dependencies") or []:
            n += 1
            rep.check("catalog_dep_owned[{}::{}]".format(aid, dep),
                      MC.is_allowed_final_path(dep),
                      "catalog '{}' dependency '{}' is not an approved owned "
                      "path".format(aid, dep),
                      code=FailureCode.ASSET_DEPENDENCY_FAILURE)
            rep.check("catalog_dep_no_abs_leak[{}::{}]".format(aid, dep),
                      not _leaks_absolute(dep),
                      "catalog '{}' dependency '{}' leaks an absolute/cache "
                      "path".format(aid, dep),
                      code=FailureCode.PACKAGE_ABSOLUTE_PATH_LEAK_FAILURE)

    # Owned baseline final-path sanity (these are the guaranteed dependencies).
    for name, spec in owned:
        n += 1
        fp = spec.get("final_asset_path")
        rep.check("owned_final_path_owned[{}]".format(spec.get("sm_id") or name),
                  MC.is_allowed_final_path(fp or ""),
                  "owned baseline final_asset_path '{}' not under approved "
                  "root".format(fp),
                  code=FailureCode.ASSET_DEPENDENCY_FAILURE)

    # Binding ue_asset_path dependency + leak checks.
    for name, b in bindings:
        n += 1
        ue_path = b.get("ue_asset_path")
        rep.check("binding_ue_path_owned[{}]".format(b.get("binding_id") or name),
                  MC.is_allowed_final_path(ue_path or ""),
                  "binding '{}' ue_asset_path '{}' is not an approved owned "
                  "path".format(b.get("binding_id"), ue_path),
                  code=FailureCode.ASSET_DEPENDENCY_FAILURE)
        rep.check("binding_no_abs_leak[{}]".format(b.get("binding_id") or name),
                  not _leaks_absolute(ue_path),
                  "binding '{}' ue_asset_path '{}' leaks an absolute/cache "
                  "path".format(b.get("binding_id"), ue_path),
                  code=FailureCode.PACKAGE_ABSOLUTE_PATH_LEAK_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=n, records_total=n,
        records_passed=n if rep.passed else 0,
        records_failed=0 if rep.passed else len(rep.failures),
        extra={"catalog_records": len(catalog), "owned_specs": len(owned),
               "bindings": len(bindings)}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write(
        "[{}] audited catalog={} owned={} bindings={} checks={}\n".format(
            COMMAND, len(catalog), len(owned), len(bindings), n))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
