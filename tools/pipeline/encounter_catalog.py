#!/usr/bin/env python3
"""encounter_catalog.py — v1.4 EncounterForge catalog ledger (Agent 1).

JSON ledger of every generated encounter, keyed by encounter_id, at
procedural/generated/worldforge_encounter_catalog.json. Structural clone of
mission_catalog.py — same atomic-write, hashing, and unstable-field rules.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from encounter_contract import ENCOUNTER_CATALOG_REL, ENCOUNTER_SCHEMA_VERSION

_UNSTABLE = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}

CATALOG_ENTRY_FIELDS = (
    "encounter_id",
    "mission_id",
    "pack_id",
    "biome_family",
    "mission_archetype",
    "encounter_archetype",
    "encounter_profile",
    "difficulty_band",
    "encounter_path",
    "ownership_class",
    "input_hash",
    "playtest_beta_status",
    "balance_status",
    "created_at_utc",
    "updated_at_utc",
)


def catalog_path(repo_root):
    return repo_root / ENCOUNTER_CATALOG_REL


def load_encounter_catalog(repo_root):
    p = catalog_path(repo_root)
    if not p.is_file():
        return {"schema_version": ENCOUNTER_SCHEMA_VERSION, "encounters": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def save_encounter_catalog(repo_root, catalog):
    p = catalog_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalog, indent=2, sort_keys=False), encoding="utf-8")
    os.replace(tmp, p)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def upsert_encounter(catalog, entry):
    encounters = catalog.setdefault("encounters", {})
    eid = entry["encounter_id"]
    prev = encounters.get(eid) or {}
    entry = dict(entry)
    entry["created_at_utc"] = prev.get("created_at_utc", _utc_now())
    entry["updated_at_utc"] = _utc_now()
    encounters[eid] = entry
    return catalog


def remove_encounter(catalog, encounter_id):
    (catalog.get("encounters") or {}).pop(encounter_id, None)
    return catalog


def compute_input_hash(entry):
    stable = {k: v for k, v in sorted((entry or {}).items()) if k not in _UNSTABLE}
    blob = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def catalog_content_hash(catalog):
    stable = {}
    for eid, entry in sorted((catalog.get("encounters") or {}).items()):
        stable[eid] = {k: v for k, v in sorted(entry.items()) if k not in _UNSTABLE}
    blob = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
