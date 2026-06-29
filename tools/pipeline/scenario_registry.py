#!/usr/bin/env python3
"""scenario_registry.py — WorldForge v0.8 Runtime StateForge scenario-run registry.

Manages procedural/generated/worldforge_scenario_registry.json.
Parallel to terrain_registry.py / poi_registry.py. Plain Python, no UE imports.

Each entry is one runtime-scenario run, keyed by run_id ("<target>__<scenario_id>").
"""

import datetime
import hashlib
import json
import os
from pathlib import Path

SCENARIO_REGISTRY_REL = "procedural/generated/worldforge_scenario_registry.json"
_UNSTABLE_KEYS = {"generated_at_utc", "provenance", "updated_at_utc", "created_at_utc"}


def make_run_id(target: str, scenario_id: str) -> str:
    return "{}__{}".format(target, scenario_id)


def load_scenario_registry(repo_root: Path) -> dict:
    path = repo_root / SCENARIO_REGISTRY_REL
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_scenario_registry(repo_root: Path, registry: dict):
    path = repo_root / SCENARIO_REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(path))


def upsert_scenario_entry(registry: dict, entry: dict) -> dict:
    run_id = entry["run_id"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if run_id in registry:
        entry["created_at_utc"] = registry[run_id].get("created_at_utc", now)
    else:
        entry["created_at_utc"] = now
    entry["updated_at_utc"] = now
    registry[run_id] = entry
    return registry


def remove_scenario_entry(registry: dict, run_id: str) -> dict:
    registry.pop(run_id, None)
    return registry


def compute_scenario_input_hash(descriptor: dict) -> str:
    cleaned = {k: v for k, v in descriptor.items() if k not in _UNSTABLE_KEYS}
    canonical = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "sha256:{}".format(digest)
