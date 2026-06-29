#!/usr/bin/env python3
"""generated_asset_registry.py — WorldForge generated-asset registry.

Canonical home for provenance + role metadata of WorldForge-OWNED generated
assets (e.g. a Houdini-baked StaticMesh that has been relocated into the
WorldForge content tree). Manages
procedural/generated/worldforge_generated_asset_registry.json.

Parallel to terrain_registry.py / poi_registry.py. Plain Python, no UE imports.
Each entry is one generated asset, keyed by asset_id.

This is NOT MeshForge and NOT a generic asset framework — it is the single
intake ledger that lets a generated asset earn WorldForge ownership, provenance,
and PCG eligibility. Forbidden Houdini source folders (Temp / Bake) must never
appear as an entry's final unreal_path; enforce that at registration time.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path

GENERATED_ASSET_REGISTRY_REL = "procedural/generated/worldforge_generated_asset_registry.json"
_UNSTABLE_KEYS = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}

# Final registered paths that are never allowed — a generated asset must be
# relocated into the WorldForge-owned tree before it can be registered.
FORBIDDEN_PATH_PREFIXES = (
    "/Game/HoudiniEngine/Temp",
    "/Game/HoudiniEngine/Bake",
)


def load_generated_asset_registry(repo_root: Path) -> dict:
    path = repo_root / GENERATED_ASSET_REGISTRY_REL
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_generated_asset_registry(repo_root: Path, registry: dict):
    path = repo_root / GENERATED_ASSET_REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(path))


def upsert_generated_asset_entry(registry: dict, entry: dict) -> dict:
    asset_id = entry["asset_id"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if asset_id in registry:
        entry["created_at_utc"] = registry[asset_id].get("created_at_utc", now)
    else:
        entry["created_at_utc"] = now
    entry["updated_at_utc"] = now
    registry[asset_id] = entry
    return registry


def remove_generated_asset_entry(registry: dict, asset_id: str) -> dict:
    registry.pop(asset_id, None)
    return registry


def is_forbidden_path(unreal_path: str) -> bool:
    p = (unreal_path or "").rstrip("/")
    return any(p == pre or p.startswith(pre + "/") for pre in FORBIDDEN_PATH_PREFIXES)


def compute_generated_asset_input_hash(descriptor: dict) -> str:
    cleaned = {k: v for k, v in descriptor.items() if k not in _UNSTABLE_KEYS}
    canonical = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "sha256:{}".format(digest)
