#!/usr/bin/env python3
"""validate_houdini_generated_assets.py — WorldForge v1.2 Houdini output-guarantee gate.

Validates the OUTPUT guarantees of every ``houdini_generated`` mesh asset
(addendum §5 output guarantees). The baked/imported StaticMesh WorldForge
produces from an HDA is a first-class generated-owned asset and must satisfy the
same output invariants as any other generated mesh: it is generated_owned (not
human/third-party), its final path is a catalogued owned root (never Temp/Bake),
it carries a registry_id and provenance, its material bindings all live under the
generated Materials root (package dependency present), and its bounds are real.

Usage:
    PYTHONUTF8=1 STRICT=1 HOUDINI=metadata_only \
        python tools/pipeline/validate_houdini_generated_assets.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_houdini_generated_assets/validate_houdini_generated_assets_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import houdini_contract as HC
import mesh_contract as MC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

MATERIALS_ROOT = "/Game/WorldForge/Generated/Materials/"


def _load_descriptor(asset_id):
    path = MC.mesh_descriptor_path(asset_id, REPO_ROOT)
    if not path.is_file():
        return None, "descriptor not found: {}".format(path)
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover
        return None, "descriptor unparseable: {}".format(exc)


def check_asset(rep, asset_id, entry, descriptor):
    def c(name, ok, detail="", code=FailureCode.HOUDINI_OUTPUT_REGISTRY_FAILURE):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code)

    # -- output ownership: generated_owned, not human, class == generated ---
    c("output_generated_owned", descriptor.get("generated_owned") is True,
      "generated_owned={}".format(descriptor.get("generated_owned")),
      code=FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE)
    c("output_not_human_owned", descriptor.get("human_owned") is False,
      "human_owned={}".format(descriptor.get("human_owned")),
      code=FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE)
    c("output_ownership_class_generated",
      MC.resolve_ownership_class(descriptor) == MC.OWNERSHIP_GENERATED,
      "ownership_class resolved to {}".format(MC.resolve_ownership_class(descriptor)),
      code=FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE)

    # -- final path: catalogued, allowed owned root, never Temp/Bake --------
    d_final = descriptor.get("final_asset_path", "")
    e_final = entry.get("final_asset_path", "")
    c("final_path_in_catalog", bool(e_final) and e_final == d_final,
      "catalog final_asset_path={} descriptor={}".format(e_final, d_final),
      code=FailureCode.HOUDINI_OUTPUT_REGISTRY_FAILURE)
    c("final_path_not_temp_bake", not MC.is_forbidden_final_path(d_final),
      "final_asset_path is a Temp/Bake/quarantine leak: {}".format(d_final),
      code=FailureCode.HOUDINI_IMPORT_FAILURE)
    c("final_path_allowed", MC.is_allowed_final_path(d_final),
      "final_asset_path not under an owned generated root: {}".format(d_final),
      code=FailureCode.HOUDINI_IMPORT_FAILURE)

    # -- registry + provenance ----------------------------------------------
    c("registry_id_present", bool(entry.get("registry_id")),
      "catalog entry has no registry_id",
      code=FailureCode.HOUDINI_OUTPUT_REGISTRY_FAILURE)
    c("provenance_present",
      bool(descriptor.get("provenance")) and bool(descriptor.get("provenance_id")),
      "descriptor missing provenance/provenance_id",
      code=FailureCode.HOUDINI_OUTPUT_PROVENANCE_FAILURE)

    # -- material bindings under the generated Materials root ---------------
    bindings = descriptor.get("material_bindings")
    if isinstance(bindings, list) and bindings:
        for i, b in enumerate(bindings):
            mpath = (b or {}).get("material_asset_path", "")
            c("material_binding_{}_package".format(i),
              bool(mpath) and mpath.startswith(MATERIALS_ROOT),
              "material_asset_path not under {}: {}".format(MATERIALS_ROOT, mpath),
              code=FailureCode.HOUDINI_OUTPUT_PACKAGE_FAILURE)
    else:
        c("material_bindings_present", False,
          "material_bindings absent or empty",
          code=FailureCode.HOUDINI_OUTPUT_PACKAGE_FAILURE)

    # -- bounds non-zero -----------------------------------------------------
    bounds = descriptor.get("bounds") or {}
    dims = [bounds.get(k) for k in MC.BOUNDS_REQUIRED]
    nonzero = all(isinstance(v, (int, float)) and v > 0 for v in dims)
    c("bounds_non_zero", nonzero, "bounds dims={}".format(dims),
      code=FailureCode.HOUDINI_OUTPUT_PACKAGE_FAILURE)


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    n = 0
    for aid, entry in HC.iter_houdini_assets(catalog):
        descriptor, err = _load_descriptor(aid)
        if descriptor is None:
            rep.check("{}::descriptor_loads".format(aid), False, err or "no descriptor",
                      code=FailureCode.HOUDINI_OUTPUT_REGISTRY_FAILURE)
            continue
        check_asset(rep, aid, entry, descriptor)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate WorldForge v1.2 Houdini generated-asset guarantees.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-houdini-generated-assets", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_houdini_generated_assets"
    rep.write(report_dir, "validate_houdini_generated_assets_report.json")
    rep.print_summary("validate-houdini-generated-assets")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
