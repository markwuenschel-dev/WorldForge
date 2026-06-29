#!/usr/bin/env python3
"""register_generated_asset.py — WorldForge generated-asset intake registrar.

Registers ONE WorldForge-owned generated asset (e.g. a Houdini-baked rock
StaticMesh) into the generated-asset registry and writes its descriptor. This is
the narrow asset-intake sidecar — NOT MeshForge.

Refuses to register an asset whose final unreal_path is a Houdini Temp/Bake path
(Risk 2): a generated asset must be relocated into the WorldForge-owned tree
(/Game/WorldForge/Generated/...) first. When pcg_allowed is set, also asserts the
asset is listed in its declared asset-catalog category so PCG can actually
scatter it.

Usage:
    python tools/pipeline/register_generated_asset.py --asset rock_generator_desert_01
    python tools/pipeline/register_generated_asset.py --asset rock_generator_desert_01 --force

Requires: PyYAML (pip install pyyaml)
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_NAME = "register_generated_asset"
GENERATOR_VERSION = "0.8.0"

ALLOWED_ROOT = "/Game/WorldForge/Generated/"

sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from generated_asset_registry import (
    compute_generated_asset_input_hash,
    is_forbidden_path,
    load_generated_asset_registry,
    save_generated_asset_registry,
    upsert_generated_asset_entry,
)
from provenance import build_provenance


def _catalog_contains(catalog_id: str, category: str, unreal_path: str):
    """(found, detail) — is unreal_path listed under category in the catalog?"""
    cat_path = REPO_ROOT / "procedural" / "definitions" / "assets" / (catalog_id + ".yaml")
    if not cat_path.is_file():
        return False, "catalog not found: {}".format(cat_path.relative_to(REPO_ROOT))
    try:
        with cat_path.open("r", encoding="utf-8") as fh:
            catalog = yaml.safe_load(fh) or {}
    except Exception as exc:
        return False, "catalog parse error: {}".format(exc)
    assets = (catalog.get("categories", {}).get(category, {}) or {}).get("assets", [])
    if unreal_path in assets:
        return True, "{} in {}.{}".format(unreal_path, catalog_id, category)
    return False, "{} not listed in {}.{} — add it before registering".format(
        unreal_path, catalog_id, category)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Register a WorldForge-owned generated asset.")
    ap.add_argument("--asset", required=True, help="Asset id (procedural/definitions/generated_assets/<id>.yaml)")
    ap.add_argument("--force", action="store_true", help="Re-register even if descriptor exists")
    args = ap.parse_args(argv)

    def_path = REPO_ROOT / "procedural" / "definitions" / "generated_assets" / (args.asset + ".yaml")
    if not def_path.is_file():
        sys.stderr.write("ERROR: generated-asset definition not found: {}\n".format(def_path))
        return 1

    with def_path.open("r", encoding="utf-8") as fh:
        d = yaml.safe_load(fh) or {}

    asset_id = d.get("asset_id", args.asset)
    unreal_path = d.get("unreal_path", "")
    pcg_allowed = bool(d.get("pcg_allowed", False))
    catalog_id = d.get("asset_catalog", "")
    category = d.get("placement_category", "")

    # -- Hard refusals (fail before writing anything) -----------------------
    if not unreal_path:
        sys.stderr.write("ERROR: {} has no unreal_path\n".format(asset_id))
        return 1
    if is_forbidden_path(unreal_path):
        sys.stderr.write(
            "ERROR: refusing to register a forbidden path (relocate out of Houdini Temp/Bake first): {}\n".format(
                unreal_path))
        return 1
    if not unreal_path.startswith(ALLOWED_ROOT):
        sys.stderr.write(
            "ERROR: final path must live under {} (WorldForge-owned): got {}\n".format(
                ALLOWED_ROOT, unreal_path))
        return 1
    if pcg_allowed:
        found, detail = _catalog_contains(catalog_id, category, unreal_path)
        if not found:
            sys.stderr.write("ERROR: pcg_allowed but catalog membership missing — {}\n".format(detail))
            return 1
        print("[register-generated-asset] catalog OK: {}".format(detail))

    out_dir = REPO_ROOT / "procedural" / "generated" / "generated_assets" / asset_id
    desc_path = out_dir / "descriptor.json"
    if desc_path.is_file() and not args.force:
        print("[register-generated-asset] up-to-date (descriptor exists; use --force): {}".format(
            desc_path.relative_to(REPO_ROOT)))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    prov = build_provenance(REPO_ROOT, [def_path], GENERATOR_NAME, GENERATOR_VERSION)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    desc_rel = desc_path.relative_to(REPO_ROOT).as_posix()

    descriptor = {
        "asset_id": asset_id,
        "display_name": d.get("display_name", asset_id),
        "unreal_path": unreal_path,
        "source": d.get("source", "unknown"),
        "hda_name": d.get("hda_name"),
        "source_bake_path": d.get("source_bake_path"),
        "asset_type": d.get("asset_type", "static_mesh"),
        "role": list(d.get("role", [])),
        "biome": list(d.get("biome", [])),
        "pcg_allowed": pcg_allowed,
        "placement_category": category,
        "asset_catalog": catalog_id,
        "generated_owned": bool(d.get("generated_owned", True)),
        "temporary": bool(d.get("temporary", False)),
        "definition_path": def_path.relative_to(REPO_ROOT).as_posix(),
        "outputs": {"descriptor": desc_rel},
        "generated_at_utc": now_iso,
        "provenance": prov,
        "registry_owner": "worldforge_generated_asset_registry",
    }

    with desc_path.open("w", encoding="utf-8") as fh:
        json.dump(descriptor, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[register-generated-asset] descriptor -> {}".format(desc_rel))

    registry = load_generated_asset_registry(REPO_ROOT)
    entry = {
        "asset_id": asset_id,
        "unreal_path": unreal_path,
        "source": d.get("source", "unknown"),
        "asset_type": d.get("asset_type", "static_mesh"),
        "biome": list(d.get("biome", [])),
        "pcg_allowed": pcg_allowed,
        "generated_owned": bool(d.get("generated_owned", True)),
        "descriptor_path": desc_rel,
        "input_hash": compute_generated_asset_input_hash({
            "asset_id": asset_id,
            "unreal_path": unreal_path,
            "source": d.get("source", "unknown"),
            "asset_type": d.get("asset_type", "static_mesh"),
        }),
    }
    registry = upsert_generated_asset_entry(registry, entry)
    save_generated_asset_registry(REPO_ROOT, registry)
    print("[register-generated-asset] registry updated")

    print("[register-generated-asset] DONE: {} -> {}".format(asset_id, unreal_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
