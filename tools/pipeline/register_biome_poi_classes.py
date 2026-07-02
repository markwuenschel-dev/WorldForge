#!/usr/bin/env python3
"""register_biome_poi_classes.py — v1.1 BiomeForge.

The biome slice packs reference POI *compatibility classes* (safe_zone, danger_zone,
traversal_choke, vista_point, navigation_landmark, resource_site, ruin_cluster,
abandoned_outpost, encounter_ready_anchor, objective_ready_anchor) rather than
concrete POIForge recipes. These classes are authoritative in each biome contract's
`poi_compatibility` / anchor lists and are validated by validate-biome-poi-compatibility.

package-check resolves every slice `poi:` value against the POI registry. This script
registers each referenced biome POI class as a first-class registry entry (kind=class)
backed by a real, provenance-stamped class descriptor generated from the biome
contracts — so package-check resolves them without fabricating geometry. Classes that
are already concrete POIForge recipes (e.g. industrial_yard) are left untouched.

Pure Python. Deterministic. Idempotent.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "pipeline"))
from provenance import build_provenance  # noqa: E402
from poi_registry import load_poi_registry, save_poi_registry, upsert_poi_entry  # noqa: E402

SLICE_PACKS = REPO / "procedural" / "slice_packs"
BIOME_DEFS = REPO / "procedural" / "definitions" / "biomes"
POI_GEN_DIR = REPO / "procedural" / "generated" / "poi"


def _referenced_poi_classes():
    """Every distinct `poi:` value across the biome_expansion slice packs."""
    classes = set()
    for sp in sorted(SLICE_PACKS.glob("biome_expansion_*.yaml")):
        data = yaml.safe_load(sp.read_text(encoding="utf-8")) or {}
        for s in data.get("slices", []) or []:
            if s.get("poi"):
                classes.add(s["poi"])
    return classes


def _biomes_declaring(cls):
    """Which biome contracts list this class in poi_compatibility / anchor types."""
    out = []
    for bp in sorted(BIOME_DEFS.glob("*.yaml")):
        data = yaml.safe_load(bp.read_text(encoding="utf-8")) or {}
        pool = set(data.get("poi_compatibility") or [])
        pool |= set(data.get("entity_anchor_types") or [])
        if cls in pool:
            out.append(data.get("id", bp.stem))
    return out


def main():
    ap = argparse.ArgumentParser(description="Register biome POI compatibility classes.")
    ap.add_argument("--strict", action="store_true")
    ap.parse_args()

    registry = load_poi_registry(REPO)
    existing_recipes = {e.get("recipe_id") for e in registry.values()}

    referenced = _referenced_poi_classes()
    biome_contracts = sorted(BIOME_DEFS.glob("*.yaml"))
    registered, skipped = [], []
    for cls in sorted(referenced):
        if cls in existing_recipes:
            skipped.append(cls)  # already a concrete POIForge recipe
            continue
        biomes = _biomes_declaring(cls)
        desc_dir = POI_GEN_DIR / cls
        desc_dir.mkdir(parents=True, exist_ok=True)
        descriptor = {
            "poi_name": cls,
            "poi_type": "class",
            "kind": "class",
            "recipe_id": cls,
            "class_of": "biome_poi_compatibility",
            "compatible_biomes": biomes,
            "outputs": {},
            "provenance": build_provenance(
                REPO, biome_contracts,
                "worldforge-register-biome-poi-classes", "1.1.0"),
        }
        (desc_dir / "descriptor.json").write_text(
            json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        upsert_poi_entry(registry, {
            "poi_name": cls,
            "poi_type": "class",
            "kind": "class",
            "recipe_id": cls,
            "descriptor_path": "procedural/generated/poi/{}/descriptor.json".format(cls),
            "compatible_biomes": biomes,
            "owned_outputs": [],
        })
        registered.append(cls)

    save_poi_registry(REPO, registry)
    print("Registered {} biome POI class(es): {}".format(len(registered), ", ".join(registered)))
    if skipped:
        print("Skipped (already POIForge recipes): {}".format(", ".join(skipped)))


if __name__ == "__main__":
    main()
