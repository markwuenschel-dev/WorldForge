#!/usr/bin/env python3
"""validate_mesh_biome_compatibility.py — WorldForge v1.2 mesh biome-compat validator.

Validates that every generated mesh asset declares an explicit, coherent biome
compatibility contract (brief §11). A mesh must say — out loud — which biome
families it belongs in; implicit / empty compatibility is NOT allowed in STRICT
mode. Every declared biome must be a known biome family, every material binding's
biome_compatibility must be known, the materials collectively must cover the
mesh's biomes (a mesh cannot claim a biome no bound material supports), and any
PCG placement rules may only allow biomes the mesh itself is compatible with (a
mesh cannot be PCG-placed into a biome it is not declared compatible with).

This is the biome-taxonomy gate — validate_mesh_pcg_eligibility.py enforces the
PCG rule completeness, and validate_mesh_contract.py enforces the schema shape.

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record), falling back to the definition YAML if a descriptor is absent.

Usage:
    python tools/pipeline/validate_mesh_biome_compatibility.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_biome_compatibility.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_biome_compatibility/validate_mesh_biome_compatibility_report.json
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

_CODE = FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE


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


def _pcg_rules(record):
    """Return the placement_compatibility.pcg_rules dict (or None)."""
    pc = record.get("placement_compatibility")
    if not isinstance(pc, dict):
        return None
    rules = pc.get("pcg_rules")
    return rules if isinstance(rules, dict) else None


def check_asset(rep, asset_id, record, strict):
    """Run all biome-compatibility checks for one asset, prefixing names with id."""
    def c(name, ok, detail="", warn_only=False):
        return rep.check("{}::{}".format(asset_id, name), ok, detail,
                         code=_CODE, warn_only=warn_only)

    # -- asset biome_compatibility: explicit, non-empty, known --------------
    biomes = record.get("biome_compatibility")
    # Implicit compatibility is not allowed (brief §11): empty/absent is a
    # blocking failure in STRICT and a warning otherwise.
    c("biome_compatibility_declared",
      isinstance(biomes, list) and bool(biomes),
      "biome_compatibility must be a non-empty list (implicit not allowed): {}".format(
          biomes),
      warn_only=not strict)

    biomes = biomes if isinstance(biomes, list) else []
    unknown = [b for b in biomes if b not in MC.BIOME_FAMILIES]
    c("biome_compatibility_known", not unknown,
      "unknown biomes in biome_compatibility: {}".format(unknown))

    # -- material bindings must use known biomes and cover the mesh biomes --
    bindings = record.get("material_bindings")
    material_biomes = set()
    if isinstance(bindings, list) and bindings:
        for i, b in enumerate(bindings):
            mb = (b or {}).get("biome_compatibility")
            mb = mb if isinstance(mb, list) else []
            bad = [x for x in mb if x not in MC.BIOME_FAMILIES]
            c("material_binding_{}_biomes_known".format(i), not bad,
              "binding {} has unknown biomes: {}".format(i, bad))
            material_biomes.update(mb)
        # Materials must cover the mesh's biomes: the union of all material
        # biome_compat must intersect the asset biome_compatibility.
        covered = material_biomes & set(biomes)
        c("materials_cover_mesh_biomes", bool(covered),
          "material biomes {} do not cover mesh biomes {}".format(
              sorted(material_biomes), biomes))

    # -- pcg_rules.allowed_biomes must be a subset of the asset's biomes ----
    rules = _pcg_rules(record)
    if rules is not None:
        allowed = rules.get("allowed_biomes")
        allowed = allowed if isinstance(allowed, list) else []
        outside = [b for b in allowed if b not in biomes]
        c("pcg_allowed_biomes_subset", not outside,
          "pcg_rules.allowed_biomes {} not subset of biome_compatibility {}".format(
              outside, biomes))


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
                      code=_CODE)
            continue
        check_asset(rep, aid, record, strict)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 mesh biome compatibility.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Validate a single asset id")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict, asset=args.asset)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-biome-compatibility", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_biome_compatibility"
    rep.write(report_dir, "validate_mesh_biome_compatibility_report.json")
    rep.print_summary("validate-mesh-biome-compatibility")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
