#!/usr/bin/env python3
"""validate_mesh_material_bindings.py — WorldForge v1.2 mesh material-binding lane.

Validates the material-binding block of every generated mesh asset against the
v1.2 mesh contract (brief §12/§28). The sibling schema gate
(validate_mesh_contract.py) only proves the binding block is structurally
present with the required keys; this lane goes deeper and proves each binding is
SEMANTICALLY sound:

  * material_bindings is a non-empty list
  * every binding carries all MC.MATERIAL_BINDING_REQUIRED keys
  * slot_name is non-empty
  * material_asset_path is non-empty AND under the owned generated Materials root
    (an allowed final root — never a Temp/Bake/quarantine leak)
  * material_family is non-empty
  * binding.biome_compatibility is a non-empty list of known biomes that
    INTERSECTS the asset's top-level biome_compatibility (a material must be
    compatible with the mesh's biomes — brief "material incompatible with biome
    fails")
  * fallback_allowed must be False unless a fallback_reason is also declared
    (brief §12 "fallback material fails unless explicitly declared")

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record), falling back to the definition YAML if a descriptor is absent. A single
--asset scopes to one asset; default validates the whole catalog.

Usage:
    python tools/pipeline/validate_mesh_material_bindings.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_material_bindings.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_material_bindings/validate_mesh_material_bindings_report.json
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

# The single owned generated Materials root a binding path must live under
# (brief §12; it is an allowed final root in MC.ALLOWED_FINAL_ROOTS).
MATERIALS_ROOT = "/Game/WorldForge/Generated/Materials/"


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


def check_asset(rep, asset_id, record, strict):
    """Run all material-binding checks for one asset, prefixing check names."""
    def c(name, ok, detail="", code=FailureCode.MESH_MATERIAL_BINDING_FAILURE):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code)

    # Asset-level biomes the materials must be compatible with.
    asset_biomes = record.get("biome_compatibility")
    asset_biome_set = set(asset_biomes) if isinstance(asset_biomes, list) else set()

    bindings = record.get("material_bindings")
    if not (isinstance(bindings, list) and bindings):
        c("material_bindings_present", False,
          "material_bindings absent or empty")
        return
    c("material_bindings_present", True,
      "{} binding(s)".format(len(bindings)))

    for i, b in enumerate(bindings):
        b = b or {}
        pfx = "material_binding_{}".format(i)

        # -- all required keys present --------------------------------------
        miss = [k for k in MC.MATERIAL_BINDING_REQUIRED if k not in b]
        c("{}_required_keys".format(pfx), not miss,
          "binding {} missing keys: {}".format(i, miss))

        # -- slot_name non-empty --------------------------------------------
        slot = b.get("slot_name")
        c("{}_slot_name".format(pfx), bool(slot),
          "binding {} slot_name empty".format(i))

        # -- material_asset_path non-empty AND under owned Materials root ----
        mpath = (b.get("material_asset_path") or "").strip()
        c("{}_material_path_present".format(pfx), bool(mpath),
          "binding {} material_asset_path empty".format(i))
        under_owned = (bool(mpath) and mpath.startswith(MATERIALS_ROOT)
                       and not MC.is_forbidden_final_path(mpath))
        c("{}_material_path_owned".format(pfx), under_owned,
          "binding {} material_asset_path not under {}: {}".format(
              i, MATERIALS_ROOT, mpath))

        # -- material_family non-empty --------------------------------------
        fam = b.get("material_family")
        c("{}_material_family".format(pfx), bool(fam),
          "binding {} material_family empty".format(i))

        # -- biome_compatibility: non-empty, known, intersects asset biomes -
        b_biomes = b.get("biome_compatibility")
        b_biome_list = b_biomes if isinstance(b_biomes, list) else []
        c("{}_biome_list".format(pfx), bool(b_biome_list),
          "binding {} biome_compatibility absent or empty".format(i))
        bad = [x for x in b_biome_list if x not in MC.BIOME_FAMILIES]
        c("{}_biome_known".format(pfx), not bad,
          "binding {} unknown biomes: {}".format(i, bad))
        intersects = bool(set(b_biome_list) & asset_biome_set)
        c("{}_biome_compatible".format(pfx), intersects,
          "binding {} material biomes {} incompatible with asset biomes {}".format(
              i, b_biome_list, sorted(asset_biome_set)))

        # -- fallback: only allowed with an explicit fallback_reason --------
        fallback_allowed = b.get("fallback_allowed", False)
        fallback_ok = (fallback_allowed is not True) or bool(b.get("fallback_reason"))
        c("{}_fallback_declared".format(pfx), fallback_ok,
          "binding {} fallback_allowed=True without a fallback_reason".format(i))


def validate(pack, strict, asset=None):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    asset_ids = [asset] if asset else [aid for aid, _ in
                                       sorted((catalog.get("assets") or {}).items())]
    if not asset_ids:
        rep.error("no mesh assets found — run 'make create-mesh-assets' first")
        return rep, 0

    n = 0
    for aid in asset_ids:
        record, err = _load_record(aid)
        if record is None:
            rep.check("{}::record_loads".format(aid), False, err or "no record",
                      code=FailureCode.MESH_MATERIAL_BINDING_FAILURE)
            continue
        check_asset(rep, aid, record, strict)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 mesh material bindings.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Validate a single asset id")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict, asset=args.asset)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-material-bindings", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_material_bindings"
    rep.write(report_dir, "validate_mesh_material_bindings_report.json")
    rep.print_summary("validate-mesh-material-bindings")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
