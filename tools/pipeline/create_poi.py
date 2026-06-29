#!/usr/bin/env python3
"""create_poi.py — WorldForge v0.7 POIForge Lite artifact generator.

Reads a POI recipe YAML and generates:
  - descriptor.json  (POI descriptor + provenance + registry ownership)

Updates procedural/generated/worldforge_poi_registry.json.

All outputs are deterministic: same recipe always produces identical descriptor.
Rerunning is idempotent (overwrites with the same content).

Usage:
    python tools/pipeline/create_poi.py --type industrial_yard --name POI_IndustrialYard_01
    python tools/pipeline/create_poi.py --type industrial_yard --name POI_IndustrialYard_01 --force

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
GENERATOR_NAME = "create_poi"
GENERATOR_VERSION = "0.7.0"

sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from poi_registry import (
    compute_poi_input_hash,
    load_poi_registry,
    save_poi_registry,
    upsert_poi_entry,
)
from provenance import build_provenance


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate POIForge Lite descriptor from a POI recipe."
    )
    ap.add_argument("--type", required=True, help="POI type / recipe id, e.g. industrial_yard")
    ap.add_argument("--name", required=True, help="Output POI name, e.g. POI_IndustrialYard_01")
    ap.add_argument("--force", action="store_true", help="Regenerate even if descriptor already exists")
    args = ap.parse_args(argv)

    recipe_path = REPO_ROOT / "procedural" / "definitions" / "poi" / (args.type + ".yaml")
    if not recipe_path.is_file():
        sys.stderr.write("ERROR: POI recipe not found: {}\n".format(recipe_path))
        sys.exit(1)

    out_dir = REPO_ROOT / "procedural" / "generated" / "poi" / args.name
    desc_path = out_dir / "descriptor.json"

    if desc_path.is_file() and not args.force:
        print("[create-poi] up-to-date (descriptor exists; use --force to rebuild): {}".format(
            desc_path.relative_to(REPO_ROOT)))
        return 0

    with recipe_path.open("r", encoding="utf-8") as fh:
        recipe = yaml.safe_load(fh)

    out_dir.mkdir(parents=True, exist_ok=True)

    recipe_id = recipe.get("recipe_id", args.type)
    seed = int(recipe.get("seed", 42000))
    footprint = recipe.get("footprint", {})
    width_cm = int(footprint.get("width_cm", 0))
    depth_cm = int(footprint.get("depth_cm", 0))

    print("[create-poi] {} type={} seed={}".format(args.name, recipe_id, seed))

    bounds_recipe = recipe.get("bounds", {})
    bounds = {
        "id": bounds_recipe.get("id", "primary_bounds"),
        "require_non_overlapping": bool(bounds_recipe.get("require_non_overlapping", True)),
        "width_cm": width_cm,
        "depth_cm": depth_cm,
        "area_cm2": width_cm * depth_cm,
    }

    anchors = []
    for a in recipe.get("anchors", []):
        anchors.append({
            "id": a["id"],
            "role": a["role"],
            "offset_cm": list(a.get("offset_cm", [0, 0, 0])),
        })

    markers = []
    for m in recipe.get("markers", []):
        entry = {"id": m["id"], "role": m["role"]}
        if "anchor_ref" in m:
            entry["anchor_ref"] = m["anchor_ref"]
        markers.append(entry)

    budgets = recipe.get("budgets", {})

    prov = build_provenance(REPO_ROOT, [recipe_path], GENERATOR_NAME, GENERATOR_VERSION)

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    desc_rel = desc_path.relative_to(REPO_ROOT).as_posix()

    descriptor = {
        "poi_name": args.name,
        "poi_type": recipe_id,
        "recipe_id": recipe_id,
        "recipe_path": recipe_path.relative_to(REPO_ROOT).as_posix(),
        "seed": seed,
        "footprint": {"width_cm": width_cm, "depth_cm": depth_cm},
        "bounds": bounds,
        "anchors": anchors,
        "markers": markers,
        "budgets": {
            "max_static_mesh_actors": int(budgets.get("max_static_mesh_actors", 0)),
            "max_marker_count": int(budgets.get("max_marker_count", 0)),
            "max_bounds_area_cm2": int(budgets.get("max_bounds_area_cm2", 0)),
        },
        "template_id": recipe.get("template_id", "{}_template_v1".format(recipe_id)),
        "compatible_terrain": list(recipe.get("compatible_terrain", [])),
        "compatible_state": list(recipe.get("compatible_state", [])),
        "compatible_placement": list(recipe.get("compatible_placement", [])),
        "outputs": {
            "descriptor": desc_rel,
        },
        "generated_at_utc": now_iso,
        "provenance": prov,
        "registry_owner": "worldforge_poi_registry",
    }

    with desc_path.open("w", encoding="utf-8") as fh:
        json.dump(descriptor, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[create-poi] descriptor -> {}".format(desc_rel))

    registry = load_poi_registry(REPO_ROOT)
    entry = {
        "poi_name": args.name,
        "poi_type": recipe_id,
        "recipe_id": recipe_id,
        "recipe_path": recipe_path.relative_to(REPO_ROOT).as_posix(),
        "descriptor_path": desc_rel,
        "input_hash": compute_poi_input_hash({
            "poi_name": args.name,
            "recipe_id": recipe_id,
            "seed": seed,
        }),
    }
    registry = upsert_poi_entry(registry, entry)
    save_poi_registry(REPO_ROOT, registry)
    print("[create-poi] registry updated")

    print("[create-poi] DONE: {}".format(args.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
