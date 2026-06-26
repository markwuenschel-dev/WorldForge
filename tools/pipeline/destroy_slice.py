#!/usr/bin/env python3
"""destroy_slice.py — WorldForge v0.4 slice lifecycle: destroy one named slice.

Deletes owned generated assets only. Never deletes referenced_assets (shared
materials, placement DAs, PCG graphs owned by other slices or handcrafted).

Usage:
    python tools/pipeline/destroy_slice.py --name Desert_Ash_Outpost_01
"""

import argparse
import shutil
import sys
from pathlib import Path

from registry import load_registry, remove_entry, save_registry

REPO_ROOT = Path(__file__).resolve().parents[2]


def _delete_file(path: Path):
    if path.is_file():
        path.unlink()
        print("  deleted: {}".format(path.relative_to(REPO_ROOT).as_posix()))
    else:
        print("  already gone: {}".format(path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path))


def _delete_dir(path: Path):
    if path.is_dir():
        shutil.rmtree(str(path))
        print("  deleted dir: {}".format(path.relative_to(REPO_ROOT).as_posix()))
    else:
        print("  already gone (dir): {}".format(path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Destroy one named WorldForge slice and its owned generated assets.")
    ap.add_argument("--name", required=True, help="Slice name (e.g. Desert_Ash_Outpost_01)")
    args = ap.parse_args(argv)

    name = args.name
    registry = load_registry(REPO_ROOT)

    if name not in registry:
        print("WARNING: '{}' not in registry — nothing to destroy.".format(name))
        sys.exit(0)

    entry = registry[name]
    biome = entry.get("biome", "")

    print("Destroying slice: {}".format(name))
    print("  pack:   {}".format(entry.get("pack_id", "<unknown>")))
    print("  biome:  {}".format(biome))

    # 1. Delete owned assets (repo-relative paths like Content/WorldForge/Maps/<NAME>.umap).
    print("\nOwned assets:")
    for rel in entry.get("owned_assets", []):
        _delete_file(REPO_ROOT / rel)

    # 2. Delete generated spec.
    print("\nGenerated spec:")
    spec_path = REPO_ROOT / "procedural" / "slices" / biome / "generated" / (name + ".json")
    _delete_file(spec_path)

    # 3. Delete report directory.
    print("\nReport directory:")
    report_dir = REPO_ROOT / "procedural" / "reports" / "slices" / biome / name
    _delete_dir(report_dir)

    # 4. Update registry.
    registry = remove_entry(registry, name)
    save_registry(REPO_ROOT, registry)
    print("\nRegistry updated — '{}' removed.".format(name))


if __name__ == "__main__":
    main()
