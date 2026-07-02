#!/usr/bin/env python3
"""prepare_biome_materialization.py — v1.1 BiomeForge (pipeline-side prep).

Prepares everything the single-session UE batch driver (batch_biome_materialize.py)
needs to materialize + validate the biome_expansion_world 60-map matrix:

  1. Generates the per-slice placement DA descriptor (_da.json) for every biome slice
     via generate_placement_da.py (pure Python).
  2. Builds one create_placement_data_asset-compatible manifest per biome placement
     DataAsset (derived from the biome placement definitions' `categories` schema),
     written to procedural/manifests/placement/<da>.json.
  3. Writes the batch manifest procedural/reports/slices/_biome_batch.json listing the
     placement-DA manifests + the ordered spec paths for the UE driver.

Pure Python (pyyaml on the pipeline side). No UE. Deterministic.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "pipeline"))
from provenance import build_provenance  # noqa: E402

SLICES_DIR = REPO / "procedural" / "slices"
PLACEMENT_DEFS = REPO / "procedural" / "definitions" / "placement" / "biomes"
MANIFEST_DIR = REPO / "procedural" / "manifests" / "placement"
BATCH_PATH = REPO / "procedural" / "reports" / "slices" / "_biome_batch.json"
GEN_DA = REPO / "tools" / "pipeline" / "generate_placement_da.py"

BIOMES = ["temperate_forest", "alpine_snow", "volcanic_ashlands",
          "wetland_mire", "alien_crystal_badlands"]

PLACEHOLDER_MESH = "/Engine/BasicShapes/Cube.Cube"


def _biome_specs(biome):
    d = SLICES_DIR / biome / "generated"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _species_from_categories(defs):
    """Merge the `categories` blocks of a biome's placement defs into species rules."""
    merged = {}
    state_key = "none"
    for dpath in defs:
        data = yaml.safe_load(dpath.read_text(encoding="utf-8")) or {}
        state_key = data.get("state_key", state_key)
        for cat, vals in (data.get("categories") or {}).items():
            if cat not in merged:
                merged[cat] = {
                    "id": cat,
                    "mesh": PLACEHOLDER_MESH,
                    "base_density": float(vals.get("density_at_0", 1.0)),
                    "scale_min": 0.8,
                    "scale_max": 1.2,
                    "state_scope": "Region",
                    "state_key": state_key,
                    "density_at_state_zero": float(vals.get("density_at_0", 1.0)),
                    "density_at_state_one": float(vals.get("density_at_1", 1.0)),
                }
    return list(merged.values()), state_key


def _da_path_for_biome(specs):
    """The (shared) placement DataAsset + pcg graph the biome's slices reference."""
    for sp in specs:
        pl = (json.loads(sp.read_text(encoding="utf-8")).get("placement") or {})
        if pl.get("data_asset"):
            return pl.get("data_asset"), pl.get("pcg_graph", "")
    return None, ""


def main():
    ap = argparse.ArgumentParser(description="Prepare biome materialization inputs.")
    ap.add_argument("--strict", action="store_true")
    ap.parse_args()

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    BATCH_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_specs = []
    manifests = []
    da_summary = []
    for biome in BIOMES:
        specs = _biome_specs(biome)
        if not specs:
            print("WARN: no specs for biome {}".format(biome))
            continue
        # 1) per-slice placement _da.json
        for sp in specs:
            rc = subprocess.run([sys.executable, str(GEN_DA), "--spec", str(sp)],
                                cwd=str(REPO), capture_output=True, text=True)
            if rc.returncode != 0:
                print("FAIL generate_placement_da {}: {}".format(sp.name, rc.stderr.strip()[:200]))
                sys.exit(1)
            all_specs.append(str(sp.relative_to(REPO)).replace("\\", "/"))

        # 2) biome placement-DA manifest
        da_path, pcg = _da_path_for_biome(specs)
        defs = sorted((PLACEMENT_DEFS / biome).glob("*.yaml"))
        species, state_key = _species_from_categories(defs)
        definition_id = da_path.rsplit("/", 1)[-1]  # e.g. DA_Woodland_Foliage
        manifest = {
            "definition_id": definition_id,
            "schema_version": "1.1",
            "biome": biome,
            "source_definition": "procedural/definitions/placement/biomes/{}".format(biome),
            "pcg_graph": pcg,
            "ue": {
                "data_asset_path": da_path,
                "data_asset_class": "PlacementRulesDataAsset",
                "generate_data_asset": True,
            },
            "species": species,
            "provenance": build_provenance(
                REPO, defs,
                "worldforge-prepare-biome-materialization", "1.1.0"),
        }
        mpath = MANIFEST_DIR / "{}.json".format(definition_id)
        mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        manifests.append(str(mpath.relative_to(REPO)).replace("\\", "/"))
        da_summary.append({"biome": biome, "data_asset": da_path,
                           "species": len(species), "state_key": state_key})
        print("[{}] DA={} species={} slices={}".format(biome, da_path, len(species), len(specs)))

    batch = {"placement_manifests": manifests, "specs": all_specs,
             "das": da_summary, "spec_count": len(all_specs)}
    BATCH_PATH.write_text(json.dumps(batch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nBatch manifest: {} ({} specs, {} placement DAs)".format(
        BATCH_PATH.relative_to(REPO), len(all_specs), len(manifests)))


if __name__ == "__main__":
    main()
