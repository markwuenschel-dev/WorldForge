#!/usr/bin/env python3
"""register_biome_pack.py — v1.1 BiomeForge registration.

After the biome slices are materialized in-editor, register the pack's owned/
generated surface so package-check (and the lifecycle/ownership gates) resolve it,
exactly as the desert create-world-pack pipeline registers desert:

  * generated assets  — the 5 biome terrain MIs + shared master + 5 placement DAs
                        (worldforge_generated_asset_registry.json)
  * terrain forms     — the 10 definition-only biome terrain forms
                        (worldforge_terrain_registry.json + a class descriptor each)
  * slices            — all 60 biome slices with map/spec/owned/referenced deps
                        (worldforge_registry.json)

Pure Python. Deterministic. Idempotent (upserts).
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "pipeline"))
from provenance import build_provenance  # noqa: E402
from registry import load_registry, save_registry, upsert_entry, compute_input_hash  # noqa: E402
from terrain_registry import (load_terrain_registry, save_terrain_registry,  # noqa: E402
                              upsert_terrain_entry)
from generated_asset_registry import (load_generated_asset_registry,  # noqa: E402
                                      save_generated_asset_registry,
                                      upsert_generated_asset_entry)

SLICES_DIR = REPO / "procedural" / "slices"
SLICE_PACKS = REPO / "procedural" / "slice_packs"
TERRAIN_DEFS = REPO / "procedural" / "definitions" / "terrain" / "biomes"
GEN_TERRAIN_DIR = REPO / "procedural" / "generated" / "terrain"
GEN_ASSET_DIR = REPO / "procedural" / "generated" / "generated_assets"

BIOMES = ["temperate_forest", "alpine_snow", "volcanic_ashlands",
          "wetland_mire", "alien_crystal_badlands"]


def _content_umap(map_path):
    """/Game/WorldForge/Maps/X -> Content/WorldForge/Maps/X.umap"""
    rel = map_path.split("/Game/", 1)[-1]
    return "Content/" + rel + ".umap"


def _asset_id(unreal_path):
    return unreal_path.rsplit("/", 1)[-1].lower()


def register():
    slice_reg = load_registry(REPO)
    terr_reg = load_terrain_registry(REPO)
    gen_reg = load_generated_asset_registry(REPO)

    counts = {"slices": 0, "terrain": 0, "gen_assets": 0}
    seen_gen = set()
    seen_terrain = set()

    for biome in BIOMES:
        pack_id = "biome_expansion_{}".format(biome)
        specs = sorted((SLICES_DIR / biome / "generated").glob("*.json"))
        for sp in specs:
            spec = json.loads(sp.read_text(encoding="utf-8"))
            sid = spec["slice_id"]
            mi = spec["terrain"]["material_mi"]
            pl = spec.get("placement", {}) or {}
            da = pl.get("data_asset")
            pcg = pl.get("pcg_graph")
            tf = spec.get("terrain_forge", {}) or {}
            form = tf.get("recipe_id")

            # -- generated assets: terrain MI (shared per biome) --
            for path, atype in [(mi, "material_instance"), (da, "data_asset")]:
                if not path or path in seen_gen:
                    continue
                seen_gen.add(path)
                aid = _asset_id(path)
                ddir = GEN_ASSET_DIR / aid
                ddir.mkdir(parents=True, exist_ok=True)
                desc = {"asset_id": aid, "unreal_path": path, "source": "worldforge",
                        "asset_type": atype, "biome": [biome], "generated_owned": True,
                        "provenance": build_provenance(REPO, [sp],
                                                       "worldforge-register-biome-pack", "1.1.0")}
                (ddir / "descriptor.json").write_text(
                    json.dumps(desc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                upsert_generated_asset_entry(gen_reg, {
                    "asset_id": aid, "unreal_path": path, "source": "worldforge",
                    "asset_type": atype, "biome": [biome], "pcg_allowed": True,
                    "generated_owned": True,
                    "descriptor_path": "procedural/generated/generated_assets/{}/descriptor.json".format(aid),
                })
                counts["gen_assets"] += 1

            # -- terrain form (definition-only) --
            if form and form not in seen_terrain:
                seen_terrain.add(form)
                tdir = GEN_TERRAIN_DIR / form
                tdir.mkdir(parents=True, exist_ok=True)
                tdesc_src = tf.get("descriptor_path", "")
                tdesc = {"recipe_id": form, "terrain_name": form, "definition_only": True,
                         "biome": biome, "source_definition": tdesc_src,
                         "outputs": {},
                         "provenance": build_provenance(REPO, [sp],
                                                        "worldforge-register-biome-pack", "1.1.0")}
                (tdir / "descriptor.json").write_text(
                    json.dumps(tdesc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                upsert_terrain_entry(terr_reg, {
                    "recipe_id": form, "terrain_name": form, "definition_only": True,
                    "descriptor_path": "procedural/generated/terrain/{}/descriptor.json".format(form),
                    "owned_outputs": [],
                })
                counts["terrain"] += 1

            # -- slice --
            referenced = [p for p in (mi, da, pcg) if p]
            upsert_entry(slice_reg, {
                "slice_id": sid, "pack_id": pack_id, "biome": biome,
                "variant": spec.get("variant", ""),
                "map_path": spec["map"],
                "spec_path": str(sp.relative_to(REPO)).replace("\\", "/"),
                "owned_assets": [_content_umap(spec["map"])],
                "referenced_assets": referenced,
                "input_hash": compute_input_hash(spec),
            })
            counts["slices"] += 1

    save_generated_asset_registry(REPO, gen_reg)
    save_terrain_registry(REPO, terr_reg)
    save_registry(REPO, slice_reg)
    return counts


def main():
    ap = argparse.ArgumentParser(description="Register the biome_expansion pack surface.")
    ap.add_argument("--strict", action="store_true")
    ap.parse_args()
    counts = register()
    print("Registered: {} slices, {} terrain forms, {} generated assets".format(
        counts["slices"], counts["terrain"], counts["gen_assets"]))


if __name__ == "__main__":
    main()
