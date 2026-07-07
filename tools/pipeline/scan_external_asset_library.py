#!/usr/bin/env python3
"""scan_external_asset_library.py — WorldForge v1.2 addendum Megascans scanner.

Performs a REAL scan of the local Megascans/Fab cache (path resolved from the
gitignored machine-local config, never hardcoded) and normalizes every asset into
the third-party external asset catalog. Each record is classified
(asset_type/category, biome compatibility, PCG eligibility) and stamped with
third_party_owned / external_licensed / repair_destroy_protected — the source
cache is an intake source, NEVER a generated output or lifecycle target
(addendum §2/§6).

No absolute machine path is written into the committed catalog: records store a
relative ``source_path`` plus the ``library_root_alias`` that resolves via config.

Usage:
    python tools/pipeline/scan_external_asset_library.py --lib megascans
    STRICT=1 python tools/pipeline/scan_external_asset_library.py --lib megascans --strict

Writes: worldforge_external_asset_catalog.json + per-asset descriptors under
procedural/generated/external_assets/<id>/descriptor.json, and a report.
"""

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import asset_config
import external_asset_contract as EAC
import mesh_contract as MC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GENERATOR = "scan_external_asset_library"
GENERATOR_VERSION = "1.2.0"
EXTERNAL_GENERATED_REL = "procedural/generated/external_assets"

# asset_type -> POI compatibility + PCG eligibility policy.
POI_BY_TYPE = {
    "rock": ["landmark", "dressing"],
    "debris": ["outpost", "ruin", "dressing"],
    "vegetation": ["dressing", "resource"],
    "surface": ["ground"],
    "decal": ["ground", "dressing"],
}
PCG_BY_TYPE = {
    "rock": MC.PCG_CONDITIONAL,
    "debris": MC.PCG_CONDITIONAL,
    "vegetation": MC.PCG_CONDITIONAL,
    "surface": MC.PCG_DISALLOWED,   # surfaces are materials, not scatter meshes
    "decal": MC.PCG_DISALLOWED,
}


def _hash(*parts):
    return "sha256:" + hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def representative_source_file(asset_dir):
    """Return the most representative real source file for content hashing.

    Prefers the actual gltf mesh (small, canonical), then the Fab metadata JSON,
    then the first texture/binary present. Returns a Path or None. Read-only —
    NEVER mutates the cache.
    """
    asset_dir = Path(asset_dir)
    for f in sorted(asset_dir.glob("gltf/high/**/*.gltf")):
        if f.is_file():
            return f
    meta = asset_dir / "gltf" / "high" / "metadata"
    if meta.is_file():
        return meta
    for f in sorted(asset_dir.glob("gltf/high/**/*")):
        if f.is_file():
            return f
    return None


def content_sha256(asset_dir):
    """Real sha256 of a representative source file's bytes as ``sha256:<hex>``.

    This is the ADDITIVE content hash (v1.5): unlike ``source_path_hash`` (which
    hashes only path|uid), this hashes the ACTUAL gltf/texture bytes on disk so a
    quarantine/provenance record can prove file identity, not just path identity.
    Returns None when no readable source file exists.
    """
    f = representative_source_file(asset_dir)
    if f is None:
        return None
    h = hashlib.sha256()
    try:
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return "sha256:" + h.hexdigest()


def _read_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _parse_asset_dir(asset_dir):
    """Extract (name, uid, tags, categories, listing_type, has_mesh) from a
    Megascans asset directory. Reads gltf/high/metadata (Fab listing) + qlEtl.json."""
    meta = _read_json(asset_dir / "gltf" / "high" / "metadata") or {}
    listing = meta.get("listing", {}) if isinstance(meta, dict) else {}
    name = listing.get("title") or asset_dir.name.rsplit("-", 1)[0].replace("_", " ")
    uid = listing.get("uid") or asset_dir.name.rsplit("-", 1)[-1]
    listing_type = listing.get("listingType", "")
    tags = [t.get("slug") or t.get("name") for t in listing.get("tags", []) if isinstance(t, dict)]

    categories = []
    # qlEtl.json lives a few levels down; find the first one.
    for ql in asset_dir.glob("gltf/high/*/qlEtl.json"):
        q = _read_json(ql) or {}
        categories = q.get("categories", []) or []
        break
    has_mesh = any(asset_dir.glob("gltf/high/**/*.gltf"))
    return name, uid, tags, categories, listing_type, has_mesh


def build_external_record(asset_dir, lib_block, library_root):
    name, uid, tags, categories, listing_type, has_mesh = _parse_asset_dir(asset_dir)
    rel_path = asset_dir.name  # relative to library root — no absolute leak
    ext_id = "megascans_{}_{}".format(EAC.slugify(name), str(uid)[:8])
    asset_type = EAC.derive_asset_type(name, tags, categories, listing_type)
    biomes = EAC.derive_biomes(name, tags, categories)
    pcg = PCG_BY_TYPE.get(asset_type, MC.PCG_DISALLOWED)
    budget = "cinematic" if asset_type in ("rock",) else "balanced"

    record = {
        "external_asset_id": ext_id,
        "source_type": "megascans_library",
        "library_id": "megascans",
        "library_root_alias": asset_config.library_root_alias("megascans"),
        "source_path": rel_path,
        "source_path_hash": _hash(rel_path, uid),
        # v1.5 ADDITIVE: real content hash of the actual gltf/texture bytes.
        # Existing source_path_hash (path|uid) is unchanged; this is a new field.
        "source_content_hash": content_sha256(asset_dir),
        "source_content_file": (
            representative_source_file(asset_dir).relative_to(asset_dir).as_posix()
            if representative_source_file(asset_dir) is not None else None),
        "asset_name": name,
        "asset_category": (categories[0] if categories else asset_type),
        "asset_type": asset_type,
        "ownership_class": MC.OWNERSHIP_THIRD_PARTY,
        "external_licensed": True,
        "license_family": lib_block.get("license_family", "fab_standard_license"),
        "generated_owned": False,
        "third_party_owned": True,
        "repair_destroy_protected": True,
        "raw_asset_destroy_allowed": False,
        "import_status": "cataloged_reference",   # referenced, not copied into gen tree
        "material_bindings": [{
            "slot_name": "MI_External",
            "material_asset_path": None,  # external source material; not a WF-owned path
            "material_family": "megascans_pbr",
            "texture_set": ["B", "N", "ORM", "H"],
            "biome_compatibility": biomes,
            "external_source": True,
        }],
        "texture_set": ["B", "N", "ORM", "H"],
        "mesh_lods": ["high"],
        "collision_status": "source_default",
        "bounds": {"x_cm": None, "y_cm": None, "z_cm": None, "source_reported": True},
        "scale_policy": "uniform",
        "pcg_eligibility": pcg,
        "biome_compatibility": biomes,
        "poi_compatibility": POI_BY_TYPE.get(asset_type, ["dressing"]),
        "budget_class": budget,
        "package_policy": {
            "package_usage": EAC.PACKAGE_USAGE_INCORPORATED,
            "standalone_redistribution_allowed": False,
            "raw_asset_export_allowed": False,
            "collaborator_share_allowed": True,
            "requires_project_context": True,
        },
        "has_mesh": has_mesh,
    }
    # PCG placement rules for allowed/conditional external assets.
    if pcg in (MC.PCG_ALLOWED, MC.PCG_CONDITIONAL):
        record["pcg_rules"] = {
            "allowed_biomes": biomes,
            "allowed_poi_classes": record["poi_compatibility"],
            "allowed_placement_profiles": ["scatter_default", "scatter_sparse"],
            "slope_limits": {"min_deg": 0, "max_deg": 30},
            "height_limits": {"min_cm": -50000, "max_cm": 50000},
            "density_class": "sparse",
            "collision_policy": "source_default",
            "avoid_critical_routes": True,
            "avoid_player_start": True,
            "conditions": ["requires_import_into_project_path"],
        }
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scan an external asset library into the external catalog.")
    ap.add_argument("--lib", default="megascans")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("library", args.lib, strict=strict)
    lib_block = asset_config.external_library(args.lib)
    root = asset_config.library_root(args.lib)

    rep.check("library_configured", bool(lib_block),
              "no config block for '{}' (add procedural/config/worldforge_assets.local.json)".format(args.lib),
              code=FailureCode.MEGASCANS_LIBRARY_FAILURE)
    rep.check("library_root_exists", root is not None,
              "library root ({}) {}".format(asset_config.library_root_alias(args.lib),
                                             "resolved" if root else "not found on this machine"),
              code=FailureCode.MEGASCANS_LIBRARY_FAILURE)
    rep.check("library_ownership_is_third_party",
              lib_block.get("ownership_class") == MC.OWNERSHIP_THIRD_PARTY,
              "ownership_class={}".format(lib_block.get("ownership_class")),
              code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)
    rep.check("library_not_generated_owned", lib_block.get("generated_owned") is False,
              "generated_owned must be false for an external library",
              code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)

    if root is None:
        rep.finalize()
        rep.set_meta(build_meta(command="scan-external-asset-library", pack=args.lib,
                                strict=strict, status=rep.status, record_count=0))
        report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "scan_external_asset_library"
        rep.write(report_dir, "scan_external_asset_library_report.json")
        rep.print_summary("scan-external-asset-library")
        sys.exit(rep.exit_code)

    catalog = EAC.load_external_catalog(REPO_ROOT)
    catalog["library_id"] = args.lib
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    asset_dirs = sorted([d for d in root.iterdir() if d.is_dir()])
    scanned = 0
    for d in asset_dirs:
        record = build_external_record(d, lib_block, root)
        record["provenance_record"] = "prov_{}".format(record["external_asset_id"])
        record["catalog_record"] = "external_catalog:{}".format(record["external_asset_id"])
        record["provenance"] = {
            "generator": GENERATOR, "generator_version": GENERATOR_VERSION,
            "scanned_at_utc": now, "source_path_hash": record["source_path_hash"],
            "library_root_alias": record["library_root_alias"],
        }
        # Per-asset descriptor (mirrors mesh_assets layout).
        out_dir = REPO_ROOT / EXTERNAL_GENERATED_REL / record["external_asset_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "descriptor.json").open("w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        record["descriptor_path"] = (out_dir / "descriptor.json").relative_to(REPO_ROOT).as_posix()
        catalog = EAC.upsert_external_entry(catalog, record)
        scanned += 1

    EAC.save_external_catalog(catalog, REPO_ROOT)

    rep.check("assets_scanned", scanned > 0, "scanned {} external assets".format(scanned),
              code=FailureCode.MEGASCANS_SCAN_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="scan-external-asset-library", pack=args.lib,
                            strict=strict, status=rep.status, record_count=scanned,
                            output_manifest_hash=EAC.external_catalog_content_hash(catalog)))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "scan_external_asset_library"
    rep.write(report_dir, "scan_external_asset_library_report.json")
    rep.print_summary("scan-external-asset-library")
    print("[scan-external-asset-library] {} assets cataloged from '{}'".format(scanned, args.lib))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
