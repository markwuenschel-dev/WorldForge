#!/usr/bin/env python3
"""mission_catalog.py — WorldForge v1.3 mission catalog ledger.

Source of truth for generated mission loops. JSON ledger keyed by mission_id at
procedural/generated/worldforge_mission_catalog.json. Parallels mesh_catalog.py.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path

from mission_contract import MISSION_CATALOG_REL, MISSION_SCHEMA_VERSION

_UNSTABLE = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}

CATALOG_ENTRY_FIELDS = (
    "mission_id", "mission_archetype", "biome_family", "source_map",
    "scenario_id", "state_keys", "reward_outputs", "playtest_status",
    "validation_status", "lifecycle_status", "mission_path", "input_hash",
)


def catalog_path(repo_root):
    return Path(repo_root) / MISSION_CATALOG_REL


def load_mission_catalog(repo_root):
    p = catalog_path(repo_root)
    if not p.is_file():
        return {"schema_version": MISSION_SCHEMA_VERSION, "missions": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "missions" not in data:
            return {"schema_version": MISSION_SCHEMA_VERSION, "missions": {}}
        return data
    except (OSError, json.JSONDecodeError):
        return {"schema_version": MISSION_SCHEMA_VERSION, "missions": {}}


def save_mission_catalog(repo_root, catalog):
    p = catalog_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    catalog.setdefault("schema_version", MISSION_SCHEMA_VERSION)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(p))


def upsert_mission(catalog, entry):
    missions = catalog.setdefault("missions", {})
    mid = entry["mission_id"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry["created_at_utc"] = missions.get(mid, {}).get("created_at_utc", now)
    entry["updated_at_utc"] = now
    missions[mid] = entry
    return catalog


def remove_mission(catalog, mission_id):
    catalog.get("missions", {}).pop(mission_id, None)
    return catalog


def compute_input_hash(entry):
    cleaned = {k: v for k, v in entry.items() if k not in _UNSTABLE}
    return "sha256:" + hashlib.sha256(
        json.dumps(cleaned, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def catalog_content_hash(catalog):
    missions = catalog.get("missions") or {}
    stable = {mid: {k: v for k, v in e.items() if k not in _UNSTABLE}
              for mid, e in missions.items()}
    return "sha256:" + hashlib.sha256(
        json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
