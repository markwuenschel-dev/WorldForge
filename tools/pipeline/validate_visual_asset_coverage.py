#!/usr/bin/env python3
"""validate_visual_asset_coverage.py — WorldForge v1.3.5 Visual Fidelity Pillar-1 gate.

Asserts every biome family (VC.BIOME_FAMILIES) has enough REAL visual assets to be
materialized with fidelity — no biome may be an empty shell. "Real" means:
  * classified third-party Megascans visual assets (from the visual asset catalog
    produced by scan_megascans_visual_assets.py), plus
  * generated mesh assets (the v1.2 generated mesh catalog),
whose biome_compatibility includes the biome.

Per biome it checks (brief §1):
  * total real assets >= VC.MIN_ASSETS_PER_BIOME
  * distinct visual classes / mesh families >= VC.MIN_ASSET_FAMILIES_PER_BIOME
  * NO biome has zero real assets
Biomes that Megascans covers weakly (alien_crystal_badlands has 0 externals) MUST
be carried by generated meshes — asserted explicitly.

Usage:
    python tools/pipeline/validate_visual_asset_coverage.py --pack mission_loop_world [--strict]
Writes:
    procedural/reports/visual/validate_visual_asset_coverage/validate_visual_asset_coverage_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
import mesh_catalog as MCAT
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def load_visual_asset_catalog(repo_root=REPO_ROOT):
    """Load the classified visual asset catalog (empty if absent/corrupt)."""
    path = Path(repo_root) / VC.VISUAL_ASSET_CATALOG_REL
    if not path.is_file():
        return {"assets": {}}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "assets" not in data:
            return {"assets": {}}
        return data
    except (OSError, json.JSONDecodeError):
        return {"assets": {}}


def biome_coverage(biome, visual_assets, mesh_assets):
    """Return a coverage detail dict for one biome family."""
    ext = [v for v in visual_assets.values()
           if biome in (v.get("biome_compatibility") or [])]
    mesh = [m for m in mesh_assets.values()
            if biome in (m.get("biome_compatibility") or [])]
    visual_classes = sorted({v.get("visual_class") for v in ext if v.get("visual_class")})
    mesh_families = sorted({m.get("mesh_family") for m in mesh if m.get("mesh_family")})
    families = sorted(set(visual_classes) | set(mesh_families))
    return {
        "biome": biome,
        "external_visual_assets": len(ext),
        "generated_mesh_assets": len(mesh),
        "total_real_assets": len(ext) + len(mesh),
        "visual_classes": visual_classes,
        "mesh_families": mesh_families,
        "distinct_families": families,
        "distinct_family_count": len(families),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate per-biome real visual asset coverage.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    visual_assets = load_visual_asset_catalog(REPO_ROOT).get("assets", {}) or {}
    mesh_assets = MCAT.load_mesh_catalog(REPO_ROOT).get("assets", {}) or {}

    rep.check("visual_asset_catalog_present", bool(visual_assets),
              "no visual assets — run scan_megascans_visual_assets first",
              code=FailureCode.VISUAL_ASSET_COVERAGE_FAILURE)

    coverage = {}
    for biome in VC.BIOME_FAMILIES:
        cov = biome_coverage(biome, visual_assets, mesh_assets)
        coverage[biome] = cov

        def c(name, ok, detail):
            return rep.check("{}::{}".format(biome, name), ok, detail,
                             code=FailureCode.VISUAL_ASSET_COVERAGE_FAILURE)

        c("has_real_assets", cov["total_real_assets"] > 0,
          "biome has ZERO real visual assets (external+generated)")
        c("min_assets_met",
          cov["total_real_assets"] >= VC.MIN_ASSETS_PER_BIOME,
          "total_real_assets={} < MIN_ASSETS_PER_BIOME={} (ext={}, mesh={})".format(
              cov["total_real_assets"], VC.MIN_ASSETS_PER_BIOME,
              cov["external_visual_assets"], cov["generated_mesh_assets"]))
        c("min_families_met",
          cov["distinct_family_count"] >= VC.MIN_ASSET_FAMILIES_PER_BIOME,
          "distinct_families={} < MIN_ASSET_FAMILIES_PER_BIOME={} ({})".format(
              cov["distinct_family_count"], VC.MIN_ASSET_FAMILIES_PER_BIOME,
              cov["distinct_families"]))

    # Alien badlands is weak in Megascans (0 external) and MUST be carried by the
    # v1.2 generated mesh catalog (crystal/cover/landmark meshes).
    alien = coverage.get("alien_crystal_badlands", {})
    rep.check("alien_covered_by_generated_meshes",
              alien.get("generated_mesh_assets", 0) >= VC.MIN_ASSETS_PER_BIOME,
              "alien_crystal_badlands generated meshes={} (external={}) — must be >= {}".format(
                  alien.get("generated_mesh_assets", 0),
                  alien.get("external_visual_assets", 0), VC.MIN_ASSETS_PER_BIOME),
              code=FailureCode.VISUAL_ASSET_COVERAGE_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-visual-asset-coverage", pack=args.pack,
                            strict=strict, status=rep.status,
                            record_count=len(VC.BIOME_FAMILIES),
                            extra={"coverage": coverage}))
    report_dir = REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_visual_asset_coverage"
    rep.write(report_dir, "validate_visual_asset_coverage_report.json")
    rep.print_summary("validate-visual-asset-coverage")
    for biome in VC.BIOME_FAMILIES:
        cov = coverage[biome]
        print("[validate-visual-asset-coverage] {}: ext={} mesh={} total={} families={}".format(
            biome, cov["external_visual_assets"], cov["generated_mesh_assets"],
            cov["total_real_assets"], cov["distinct_family_count"]))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
