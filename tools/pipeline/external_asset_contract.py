#!/usr/bin/env python3
"""external_asset_contract.py — WorldForge v1.2 addendum external-asset contract.

Defines the THIRD-PARTY external asset catalog (Megascans/Fab) — kept deliberately
SEPARATE from the generated mesh catalog so ownership models never merge (addendum
§6/§7). The generated mesh catalog is generated_owned + lifecycle-touchable; this
external catalog is third_party_owned, external_licensed, and repair/destroy
PROTECTED. The two may be linked by reference, never collapsed.

Ledger: procedural/generated/worldforge_external_asset_catalog.json (keyed by
external_asset_id). Plain stdlib.
"""

import datetime
import hashlib
import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_CATALOG_REL = "procedural/generated/worldforge_external_asset_catalog.json"
EXTERNAL_SCHEMA_VERSION = "1.2"

# Recognised external libraries and their license families.
LICENSE_FAMILIES = ("fab_standard_license", "fab_professional_license", "unknown_license")

# Required external-asset record fields (addendum §6). third_party ownership +
# license + destroy-protection are load-bearing.
EXTERNAL_REQUIRED_FIELDS = (
    "external_asset_id", "source_type", "library_id", "library_root_alias",
    "source_path", "source_path_hash", "asset_name", "asset_category",
    "asset_type", "ownership_class", "external_licensed", "license_family",
    "generated_owned", "repair_destroy_protected", "raw_asset_destroy_allowed",
    "pcg_eligibility", "biome_compatibility", "poi_compatibility",
    "budget_class", "package_policy", "provenance_record", "catalog_record",
)

# Package policy fields (addendum §8). Megascans may only be packaged as
# incorporated project content — never a standalone redistributable raw pack.
PACKAGE_POLICY_REQUIRED = (
    "package_usage", "standalone_redistribution_allowed", "raw_asset_export_allowed",
    "collaborator_share_allowed", "requires_project_context",
)
PACKAGE_USAGE_INCORPORATED = "incorporated_project_content"

# Megascans -> v1.1 biome family derivation. Ordered; first matching keyword wins
# per biome bucket, but an asset may match several biomes (union). Keyword sets
# are lowercase substrings tested against name + tags + categories.
BIOME_KEYWORDS = {
    "desert": ("desert", "arid", "sandstone", "sand", "dune", "western", "canyon",
               "gravel", "rocky", "rock", "cliff", "quarry", "limestone", "slate",
               "boulder", "ledge", "outcrop", "terrain"),
    "volcanic_ashlands": ("lava", "basalt", "volcanic", "icelandic", "ash", "scoria",
                          "obsidian"),
    "temperate_forest": ("tree", "stump", "wood", "leaf", "leaves", "forest", "moss",
                         "shrub", "branch", "bark", "grass", "wheat", "foliage"),
    "alpine_snow": ("snow", "ice", "glacier", "frost", "alpine"),
    "wetland_mire": ("mud", "marsh", "swamp", "wet", "moist", "bog", "reed", "silt"),
    "alien_crystal_badlands": ("crystal", "alien", "resonance", "geode"),
}

# Megascans category/listingType -> WorldForge asset_type bucket.
ASSET_TYPE_KEYWORDS = {
    "surface": ("ground", "gravel", "sand", "soil", "mud", "material", "surface",
                "3d-plants-surface", "patch"),
    "rock": ("rock", "cliff", "boulder", "stone", "outcrop", "ledge", "slab",
             "formation", "sandstone", "limestone", "quarry"),
    "debris": ("debris", "rubble", "scatter", "pile", "cluster"),
    "vegetation": ("tree", "stump", "shrub", "grass", "wheat", "leaf", "leaves",
                   "plant", "foliage"),
    "decal": ("decal", "tracks", "tire"),
}


def external_catalog_path(repo_root=REPO_ROOT):
    return Path(repo_root) / EXTERNAL_CATALOG_REL


def load_external_catalog(repo_root=REPO_ROOT):
    path = external_catalog_path(repo_root)
    if not path.is_file():
        return {"schema_version": EXTERNAL_SCHEMA_VERSION, "library_id": "megascans", "assets": {}}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "assets" not in data:
            return {"schema_version": EXTERNAL_SCHEMA_VERSION, "library_id": "megascans", "assets": {}}
        return data
    except (OSError, json.JSONDecodeError):
        return {"schema_version": EXTERNAL_SCHEMA_VERSION, "library_id": "megascans", "assets": {}}


def save_external_catalog(catalog, repo_root=REPO_ROOT):
    path = external_catalog_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog.setdefault("schema_version", EXTERNAL_SCHEMA_VERSION)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(path))


def upsert_external_entry(catalog, entry):
    assets = catalog.setdefault("assets", {})
    aid = entry["external_asset_id"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if aid in assets:
        entry["created_at_utc"] = assets[aid].get("created_at_utc", now)
    else:
        entry["created_at_utc"] = now
    entry["updated_at_utc"] = now
    assets[aid] = entry
    return catalog


def external_catalog_content_hash(catalog):
    unstable = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}
    assets = catalog.get("assets") or {}
    stable = {aid: {k: v for k, v in e.items() if k not in unstable}
              for aid, e in assets.items()}
    canonical = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _haystack(name, tags, categories):
    parts = [name or ""]
    parts += [str(t) for t in (tags or [])]
    parts += [str(c) for c in (categories or [])]
    return " ".join(parts).lower()


def derive_biomes(name, tags, categories):
    """Union of biome families an external asset is compatible with. Never empty —
    a desert-library asset with no obvious keyword defaults to desert."""
    hay = _haystack(name, tags, categories)
    hits = []
    for biome, keywords in BIOME_KEYWORDS.items():
        if any(k in hay for k in keywords):
            hits.append(biome)
    return hits or ["desert"]


def derive_asset_type(name, tags, categories, listing_type=None):
    hay = _haystack(name, tags, categories) + " " + (listing_type or "").lower()
    for atype, keywords in ASSET_TYPE_KEYWORDS.items():
        if any(k in hay for k in keywords):
            return atype
    return "surface"


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "asset"
