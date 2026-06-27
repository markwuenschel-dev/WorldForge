#!/usr/bin/env python3
"""generate_placement_da.py

Generate a JSON placement DataAsset descriptor for a slice spec.
Pure Python — no UE imports.

Usage:
    python tools/pipeline/generate_placement_da.py --spec procedural/slices/desert/generated/Desert_Ash_Outpost_01.json

Writes: procedural/generated/placement/<slice_id>_da.json
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FALLBACK_PRESET_ID = "reclaimed_desert_foliage"
FALLBACK_CATALOG_ID = "desert_asset_catalog"


def fail(msg):
    sys.stderr.write("ERROR: {}\n".format(msg))
    sys.exit(1)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a JSON placement DA descriptor from a slice spec."
    )
    parser.add_argument("--spec", required=True, help="path to generated slice spec JSON")
    args = parser.parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = REPO_ROOT / spec_path
    if not spec_path.is_file():
        fail("spec not found: {}".format(spec_path))

    with spec_path.open("r", encoding="utf-8") as fh:
        spec = json.load(fh)

    if not isinstance(spec, dict):
        fail("spec did not parse to a JSON object")

    slice_id = spec.get("slice_id", spec_path.stem)
    biome = spec.get("biome", "unknown")
    seed = spec.get("seed", 12345)
    map_path = spec.get("map", "/Game/WorldForge/Maps/{}".format(slice_id))
    state_key = spec.get("state", {}).get("key", "industrial_pressure")

    placement_preset_id = spec.get("placement_preset_id")
    using_fallback = False
    if not placement_preset_id:
        placement_preset_id = FALLBACK_PRESET_ID
        using_fallback = True

    preset_path = "procedural/definitions/placement/{}/{}.yaml".format(biome, placement_preset_id)

    # Try to read catalog_id from the placement preset file if it exists.
    preset_disk = REPO_ROOT / preset_path
    catalog_id = FALLBACK_CATALOG_ID
    if preset_disk.is_file():
        try:
            import yaml
            with preset_disk.open("r", encoding="utf-8") as fh:
                preset_data = yaml.safe_load(fh)
            if isinstance(preset_data, dict):
                catalog_id = preset_data.get("asset_catalog", FALLBACK_CATALOG_ID)
        except Exception:
            pass

    da_id = "DA_Placement_{}".format(slice_id)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    descriptor = {
        "da_id": da_id,
        "slice_id": slice_id,
        "biome": biome,
        "placement_preset_id": placement_preset_id,
        "placement_preset_path": preset_path,
        "asset_catalog_id": catalog_id,
        "state_key": state_key,
        "seed": seed,
        "map_path": map_path,
        "generated_at_utc": now_iso,
    }
    if using_fallback:
        descriptor["using_fallback"] = True

    out_dir = REPO_ROOT / "procedural" / "generated" / "placement"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "{}_da.json".format(slice_id)

    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(descriptor, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    rel = out_path.relative_to(REPO_ROOT).as_posix()
    print(rel)
    print("Generated placement DA descriptor: {} -> {}".format(da_id, rel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
