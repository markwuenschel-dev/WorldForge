#!/usr/bin/env python3
"""mesh_catalog.py — WorldForge v1.2 generated mesh catalog ledger.

The generated mesh catalog is the SOURCE OF TRUTH for generated mesh assets
(brief §9). It is a JSON ledger keyed by asset_id at
``procedural/generated/worldforge_mesh_catalog.json``. Parallel in spirit to
generated_asset_registry.py, but records the broader v1.2 mesh contract: family,
source type, final path, provenance id, biome/POI/PCG eligibility, material
bindings, collision, bounds, budget class, package + lifecycle status.

Catalog invariants the validators enforce (brief §9):
  * every generated mesh has exactly one catalog record
  * every catalog record points to an existing final asset (descriptor on disk)
  * every final asset has provenance + ownership + package coverage
  * every PCG-eligible asset has placement rules
  * no orphan generated mesh exists outside the catalog
  * no catalog record points to a missing asset

Plain Python (stdlib only). Writers do an atomic replace so a crashed write can
never leave a half-written catalog.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path

from mesh_contract import MESH_CATALOG_REL, MESH_SCHEMA_VERSION

_UNSTABLE_KEYS = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}

# Canonical fields recorded per catalog entry (brief §9).
CATALOG_ENTRY_FIELDS = (
    "asset_id", "mesh_family", "source_type", "final_asset_path",
    "registry_id", "provenance_id", "biome_compatibility", "poi_compatibility",
    "pcg_eligibility", "placement_tags", "material_bindings", "collision_profile",
    "bounds", "budget_class", "package_status", "validation_status",
    "lifecycle_status", "descriptor_path", "input_hash",
)


def catalog_path(repo_root):
    return Path(repo_root) / MESH_CATALOG_REL


def load_mesh_catalog(repo_root):
    """Load the mesh catalog dict (empty if absent/corrupt)."""
    path = catalog_path(repo_root)
    if not path.is_file():
        return {"schema_version": MESH_SCHEMA_VERSION, "assets": {}}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "assets" not in data:
            return {"schema_version": MESH_SCHEMA_VERSION, "assets": {}}
        return data
    except (OSError, json.JSONDecodeError):
        return {"schema_version": MESH_SCHEMA_VERSION, "assets": {}}


def save_mesh_catalog(repo_root, catalog):
    """Atomically write the mesh catalog."""
    path = catalog_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog.setdefault("schema_version", MESH_SCHEMA_VERSION)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(path))


def upsert_catalog_entry(catalog, entry):
    """Insert or update one catalog entry, preserving created_at_utc."""
    assets = catalog.setdefault("assets", {})
    asset_id = entry["asset_id"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if asset_id in assets:
        entry["created_at_utc"] = assets[asset_id].get("created_at_utc", now)
    else:
        entry["created_at_utc"] = now
    entry["updated_at_utc"] = now
    assets[asset_id] = entry
    return catalog


def remove_catalog_entry(catalog, asset_id):
    catalog.get("assets", {}).pop(asset_id, None)
    return catalog


def catalog_entries(catalog):
    """Yield (asset_id, entry) for every entry in the catalog."""
    return sorted((catalog.get("assets") or {}).items())


def compute_catalog_input_hash(entry):
    """Stable hash of the identity-bearing subset of a catalog entry."""
    cleaned = {k: v for k, v in entry.items() if k not in _UNSTABLE_KEYS}
    canonical = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def catalog_content_hash(catalog):
    """Deterministic hash of the whole catalog's stable content (for reports)."""
    assets = catalog.get("assets") or {}
    stable = {
        aid: {k: v for k, v in e.items() if k not in _UNSTABLE_KEYS}
        for aid, e in assets.items()
    }
    canonical = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
