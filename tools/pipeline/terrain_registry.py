#!/usr/bin/env python3
"""terrain_registry.py — WorldForge TerrainForge generated-terrain registry.

Manages procedural/generated/worldforge_terrain_registry.json.
Parallel to registry.py (SliceForge). Plain Python, no UE imports.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path

TERRAIN_REGISTRY_REL = "procedural/generated/worldforge_terrain_registry.json"
_UNSTABLE_KEYS = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}


def load_terrain_registry(repo_root: Path) -> dict:
    path = repo_root / TERRAIN_REGISTRY_REL
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_terrain_registry(repo_root: Path, registry: dict):
    path = repo_root / TERRAIN_REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(path))


def upsert_terrain_entry(registry: dict, entry: dict) -> dict:
    terrain_name = entry["terrain_name"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if terrain_name in registry:
        entry["created_at_utc"] = registry[terrain_name].get("created_at_utc", now)
    else:
        entry["created_at_utc"] = now
    entry["updated_at_utc"] = now
    registry[terrain_name] = entry
    return registry


def remove_terrain_entry(registry: dict, terrain_name: str) -> dict:
    registry.pop(terrain_name, None)
    return registry


def compute_terrain_input_hash(descriptor: dict) -> str:
    cleaned = {k: v for k, v in descriptor.items() if k not in _UNSTABLE_KEYS}
    canonical = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "sha256:{}".format(digest)
