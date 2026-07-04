#!/usr/bin/env python3
"""visual_catalog.py — WorldForge v1.3.5 visual catalog ledger.

Source of truth for per-map visual realization (environment rig + surface +
dressing status). JSON ledger keyed by slice_id at
procedural/generated/worldforge_visual_catalog.json. Parallels mesh/mission
catalogs.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path

from visual_contract import VISUAL_CATALOG_REL, VISUAL_SCHEMA_VERSION

_UNSTABLE = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}


def catalog_path(repo_root):
    return Path(repo_root) / VISUAL_CATALOG_REL


def load_visual_catalog(repo_root):
    p = catalog_path(repo_root)
    if not p.is_file():
        return {"schema_version": VISUAL_SCHEMA_VERSION, "maps": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "maps" not in data:
            return {"schema_version": VISUAL_SCHEMA_VERSION, "maps": {}}
        return data
    except (OSError, json.JSONDecodeError):
        return {"schema_version": VISUAL_SCHEMA_VERSION, "maps": {}}


def save_visual_catalog(repo_root, catalog):
    p = catalog_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    catalog.setdefault("schema_version", VISUAL_SCHEMA_VERSION)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(p))


def upsert_map(catalog, entry):
    maps = catalog.setdefault("maps", {})
    sid = entry["slice_id"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry["created_at_utc"] = maps.get(sid, {}).get("created_at_utc", now)
    entry["updated_at_utc"] = now
    maps[sid] = entry
    return catalog


def catalog_content_hash(catalog):
    maps = catalog.get("maps") or {}
    stable = {sid: {k: v for k, v in e.items() if k not in _UNSTABLE} for sid, e in maps.items()}
    return "sha256:" + hashlib.sha256(
        json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
