#!/usr/bin/env python3
"""poi_registry.py — WorldForge POIForge generated-POI registry.

Manages procedural/generated/worldforge_poi_registry.json.
Parallel to terrain_registry.py. Plain Python, no UE imports.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path

POI_REGISTRY_REL = "procedural/generated/worldforge_poi_registry.json"
_UNSTABLE_KEYS = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}


def load_poi_registry(repo_root: Path) -> dict:
    path = repo_root / POI_REGISTRY_REL
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_poi_registry(repo_root: Path, registry: dict):
    path = repo_root / POI_REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(path))


def upsert_poi_entry(registry: dict, entry: dict) -> dict:
    poi_name = entry["poi_name"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if poi_name in registry:
        entry["created_at_utc"] = registry[poi_name].get("created_at_utc", now)
    else:
        entry["created_at_utc"] = now
    entry["updated_at_utc"] = now
    registry[poi_name] = entry
    return registry


def remove_poi_entry(registry: dict, poi_name: str) -> dict:
    registry.pop(poi_name, None)
    return registry


def compute_poi_input_hash(descriptor: dict) -> str:
    cleaned = {k: v for k, v in descriptor.items() if k not in _UNSTABLE_KEYS}
    canonical = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "sha256:{}".format(digest)
