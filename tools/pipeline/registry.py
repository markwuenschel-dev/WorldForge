#!/usr/bin/env python3
"""registry.py — WorldForge generated-asset registry.

Manages procedural/generated/worldforge_registry.json.
Plain Python, no UE imports.
"""

import hashlib
import json
import os
import datetime
from pathlib import Path

REGISTRY_REL = "procedural/generated/worldforge_registry.json"
_UNSTABLE_KEYS = {"generated_at_utc", "provenance", "output_dir"}


def load_registry(repo_root: Path) -> dict:
    """Load registry or return {} if not found."""
    path = repo_root / REGISTRY_REL
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_registry(repo_root: Path, registry: dict):
    """Atomic write: write to .tmp then rename."""
    path = repo_root / REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(path))


def upsert_entry(registry: dict, entry: dict) -> dict:
    """Insert or update a registry entry. Preserves created_at_utc on update."""
    slice_id = entry["slice_id"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if slice_id in registry:
        entry["created_at_utc"] = registry[slice_id].get("created_at_utc", now)
    else:
        entry["created_at_utc"] = now
    entry["updated_at_utc"] = now
    registry[slice_id] = entry
    return registry


def remove_entry(registry: dict, slice_id: str) -> dict:
    """Remove slice_id from registry. No-op if not present."""
    registry.pop(slice_id, None)
    return registry


def compute_input_hash(spec: dict) -> str:
    """SHA256 of spec JSON excluding unstable fields. Returns 'sha256:<hex>'."""
    cleaned = {k: v for k, v in spec.items() if k not in _UNSTABLE_KEYS}
    canonical = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "sha256:{}".format(digest)
