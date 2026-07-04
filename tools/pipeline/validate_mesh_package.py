#!/usr/bin/env python3
"""validate_mesh_package.py — WorldForge v1.2 mesh package-coverage lane.

Validates that every generated mesh asset is package-safe (brief §14 package side /
§30): its final asset path is present and NOT a forbidden quarantine/intermediate
leak, its package rules opt in to bundling material dependencies, every material
dependency it names is an owned generated path (so packaging the mesh pulls the
material with it rather than dangling), and its rendering budget declares a
package size class. Finally it asserts the whole dependency set — every material
path across every asset — contains no forbidden path.

This is the packaging gate for MeshForge Intake: it does NOT re-check the whole
contract (that is validate_mesh_contract.py) — it focuses on "will this asset
package cleanly, pulling exactly its owned generated dependencies and nothing from
Temp/Bake/plugins/human-authored trees."

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record), falling back to the definition YAML if a descriptor is absent.

Usage:
    python tools/pipeline/validate_mesh_package.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_package.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_package/validate_mesh_package_report.json
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

_CODE = FailureCode.MESH_PACKAGE_FAILURE

# Owned generated materials root — a mesh's material dependencies must live here
# for packaging to pull them with the mesh.
_MATERIALS_ROOT = "/Game/WorldForge/Generated/Materials/"


def _load_record(asset_id, repo_root=REPO_ROOT):
    """Prefer the descriptor; fall back to the raw definition YAML."""
    desc = MC.mesh_descriptor_path(asset_id, repo_root)
    if desc.is_file():
        try:
            return json.loads(desc.read_text(encoding="utf-8")), None
        except Exception as exc:
            return None, "descriptor unparseable: {}".format(exc)
    data, err = MC.load_mesh_definition(MC.mesh_definition_path(asset_id, repo_root))
    return data, err


def _is_owned_material_path(path):
    """A non-empty, non-forbidden material path under the owned Materials root."""
    p = (path or "").strip()
    if not p or MC.is_forbidden_final_path(p):
        return False
    return p.startswith(_MATERIALS_ROOT)


def check_asset(rep, asset_id, record, strict):
    """Run all package-coverage checks for one asset. Returns collected material
    dependency paths so the caller can assert the aggregate dependency set."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=_CODE)

    # -- final path present and not a forbidden quarantine/intermediate leak -
    final_path = record.get("final_asset_path", "")
    c("final_path_present", bool(final_path), "final_asset_path missing")
    c("final_path_not_forbidden",
      not MC.is_forbidden_final_path(final_path),
      "final_asset_path is a forbidden quarantine/intermediate path: {}".format(
          final_path))

    # -- package rules opt in to material dependency bundling ----------------
    rules = record.get("package_rules")
    if isinstance(rules, dict):
        c("package_rules_present", True, "")
        c("include_material_dependencies_true",
          rules.get("include_material_dependencies") is True,
          "include_material_dependencies={}".format(
              rules.get("include_material_dependencies")))
    else:
        c("package_rules_present", False, "package_rules absent")

    # -- every material dependency is an owned generated path ----------------
    dep_paths = []
    bindings = record.get("material_bindings")
    if isinstance(bindings, list) and bindings:
        for i, b in enumerate(bindings):
            mpath = (b or {}).get("material_asset_path")
            dep_paths.append(mpath)
            c("material_dependency_{}_owned".format(i),
              _is_owned_material_path(mpath),
              "binding {} material_asset_path is not a non-empty owned generated "
              "path under {}: {}".format(i, _MATERIALS_ROOT, mpath))
    else:
        c("material_bindings_present", False,
          "material_bindings absent or empty — package would exclude generated "
          "mesh material dependencies")

    # -- rendering budget declares a package size class ----------------------
    rb = record.get("rendering_budget")
    size_class = rb.get("package_size_class") if isinstance(rb, dict) else None
    c("package_size_class_present",
      size_class not in (None, ""),
      "rendering_budget.package_size_class missing: {}".format(size_class))

    return dep_paths


def validate(pack, strict, asset=None):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    asset_ids = [asset] if asset else [aid for aid, _ in
                                       sorted((catalog.get("assets") or {}).items())]
    if not asset_ids:
        rep.error("no mesh assets found — run 'make create-mesh-assets' first")
        return rep, 0

    n = 0
    all_deps = []
    for aid in asset_ids:
        record, err = _load_record(aid)
        if record is None:
            rep.check("{}::record_loads".format(aid), False, err or "no record",
                      code=_CODE)
            continue
        all_deps.extend(check_asset(rep, aid, record, strict))
        n += 1

    # -- aggregate dependency set contains no forbidden path -----------------
    forbidden = sorted({p for p in all_deps if MC.is_forbidden_final_path(p)})
    rep.check("dependency_set::no_forbidden_path", not forbidden,
              "forbidden paths in aggregate material dependency set: {}".format(
                  forbidden), code=_CODE)
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 mesh package coverage.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Validate a single asset id")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict, asset=args.asset)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-package", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_package"
    rep.write(report_dir, "validate_mesh_package_report.json")
    rep.print_summary("validate-mesh-package")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
