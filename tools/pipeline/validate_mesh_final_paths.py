#!/usr/bin/env python3
"""validate_mesh_final_paths.py — WorldForge v1.2 mesh final-path ownership validator.

Validates that every generated mesh asset's FINAL asset path is owned, sane, and
free of quarantine/intermediate leakage (brief §6 + §27, final-path side). This
is the ruthless-ownership gate: a mesh may pass through Houdini Temp/Bake, an
Intermediate/ scratch folder, or an external quarantine import path, but its
FINAL asset path must live under a WorldForge-owned generated root and may never
be a Temp/Bake/Intermediate/Saved/DerivedDataCache/plugin/human-owned path.

Temp/Bake/quarantine paths are legitimate ONLY as intermediate/quarantine paths;
this validator asserts the final path is not one of them, and that imported
generated stubs actually declare a quarantine path (in source_metadata) that is
distinct from the final path.

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record) for every asset in the generated mesh catalog.

Usage:
    python tools/pipeline/validate_mesh_final_paths.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_final_paths.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_final_paths/validate_mesh_final_paths_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _load_descriptor(asset_id, repo_root=REPO_ROOT):
    """Load the materialized descriptor for an asset. Returns (record, error)."""
    desc = MC.mesh_descriptor_path(asset_id, repo_root)
    if desc.is_file():
        try:
            return json.loads(desc.read_text(encoding="utf-8")), None
        except Exception as exc:
            return None, "descriptor unparseable: {}".format(exc)
    return None, "descriptor not found: {}".format(desc)


def check_asset(rep, asset_id, record, strict):
    """Run all final-path checks for one asset, prefixing the id."""
    def c(name, ok, detail="", code=FailureCode.MESH_FINAL_PATH_FAILURE):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code)

    final_path = record.get("final_asset_path", "")

    # -- final path present -------------------------------------------------
    c("final_path_present", bool(final_path), "final_asset_path missing/empty")

    # -- final path under an owned WorldForge generated root ----------------
    c("final_path_allowed_root", MC.is_allowed_final_path(final_path),
      "final_asset_path not under an allowed generated root: {}".format(final_path))

    # -- final path is not a forbidden (Temp/Bake/Intermediate/plugin/...) ---
    c("final_path_not_forbidden", not MC.is_forbidden_final_path(final_path),
      "final_asset_path is a forbidden/quarantine path: {}".format(final_path))

    # -- final path must not collide with this asset's own quarantine /
    #    intermediate paths (Temp/Bake may appear THERE, never as final) -----
    quarantine = record.get("quarantine_paths") or []
    intermediate = record.get("intermediate_paths") or []
    c("final_path_not_in_quarantine", final_path not in quarantine,
      "final_asset_path appears in quarantine_paths: {}".format(final_path))
    c("final_path_not_in_intermediate", final_path not in intermediate,
      "final_asset_path appears in intermediate_paths: {}".format(final_path))

    # -- imported generated stubs must declare a distinct quarantine path ----
    if record.get("source_type") == "imported_generated_stub":
        sm = record.get("source_metadata") or {}
        qpath = sm.get("quarantine_path")
        c("stub_quarantine_path_present", bool(qpath),
          "imported_generated_stub missing source_metadata.quarantine_path",
          code=FailureCode.MESH_OWNERSHIP_FAILURE)
        c("stub_quarantine_differs_from_final",
          bool(qpath) and qpath != final_path,
          "imported_generated_stub quarantine_path equals final_asset_path: {}".format(qpath),
          code=FailureCode.MESH_OWNERSHIP_FAILURE)


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}
    asset_ids = sorted(assets.keys())
    if not asset_ids:
        rep.error("no mesh assets in catalog — run 'make create-mesh-assets' first")
        return rep, 0

    n = 0
    for aid in asset_ids:
        record, err = _load_descriptor(aid)
        if record is None:
            rep.check("{}::descriptor_loads".format(aid), False, err or "no descriptor",
                      code=FailureCode.MESH_FINAL_PATH_FAILURE)
            continue
        check_asset(rep, aid, record, strict)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 mesh final-path ownership.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-final-paths", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_final_paths"
    rep.write(report_dir, "validate_mesh_final_paths_report.json")
    rep.print_summary("validate-mesh-final-paths")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
