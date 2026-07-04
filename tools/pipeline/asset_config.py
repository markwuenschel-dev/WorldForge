#!/usr/bin/env python3
"""asset_config.py — WorldForge v1.2 addendum external-asset library config loader.

Resolves the machine-local external-asset library configuration (Megascans/Fab
cache roots and their ownership metadata). Absolute machine paths live ONLY in
the gitignored ``procedural/config/worldforge_assets.local.json``; the committed
``worldforge_assets.example.json`` is a template. This loader reads the local
file if present, else falls back to the example, so validators never hardcode an
absolute Windows path.

The load-bearing invariant (addendum §1/§3): a Megascans library root is an
external asset CACHE — third_party_owned, external_licensed, repair/destroy
protected. It is never a generated-owned output root, never a lifecycle target.
"""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "procedural" / "config"
LOCAL_CONFIG = CONFIG_DIR / "worldforge_assets.local.json"
EXAMPLE_CONFIG = CONFIG_DIR / "worldforge_assets.example.json"


def load_asset_config():
    """Return (config_dict, source_path). Local wins over example."""
    for path in (LOCAL_CONFIG, EXAMPLE_CONFIG):
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    return json.load(fh), path
            except (OSError, json.JSONDecodeError):
                continue
    return {"external_asset_libraries": {}}, None


def external_library(lib_id="megascans"):
    """Return the config block for one external library, or {} if undefined."""
    cfg, _ = load_asset_config()
    return (cfg.get("external_asset_libraries") or {}).get(lib_id, {})


def library_root(lib_id="megascans"):
    """Resolved filesystem root of an external library, or None if not configured
    or the path does not exist on this machine."""
    block = external_library(lib_id)
    root = block.get("library_root")
    if not root:
        return None
    p = Path(root)
    return p if p.is_dir() else None


def library_root_alias(lib_id="megascans"):
    """A stable, machine-independent alias for the library root (for provenance /
    committed records). Never leaks the absolute path."""
    return "{}:library_root".format(lib_id)


def is_within_external_library(path, lib_id="megascans"):
    """True if a filesystem path lives inside an external (protected) library.

    Used by repair/destroy guards: a path under an external library root can
    never be a lifecycle/destroy target. Compares resolved, normalized paths so
    a Temp/relative sneak-in still resolves correctly.
    """
    block = external_library(lib_id)
    root = block.get("library_root")
    if not root or not path:
        return False
    try:
        root_n = os.path.normcase(os.path.abspath(str(root)))
        path_n = os.path.normcase(os.path.abspath(str(path)))
    except Exception:
        return False
    return path_n == root_n or path_n.startswith(root_n + os.sep)


def is_repair_destroy_protected(lib_id="megascans"):
    block = external_library(lib_id)
    # Default to PROTECTED when unspecified — fail safe, never fail open.
    return bool(block.get("repair_destroy_protected", True))
