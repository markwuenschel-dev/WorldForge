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


# ---------------------------------------------------------------------------
# v1.5 Wave-2 additions — free-download sources + quarantine roots.
# ---------------------------------------------------------------------------
# Safe fallbacks used when the config file omits a block. These NEVER include a
# machine-absolute path; they are anchor-relative so they cannot leak a cache
# path into a committed record.
_DEFAULT_POLYHAVEN = {
    "api_base": "https://api.polyhaven.com",
    "enabled": True,
    "license_family": "cc0",
    "license_url": "https://polyhaven.com/license",
    "publisher": "Poly Haven",
    "approved_free_only": True,
    # Only CC0 is ever eligible for automated download from this source.
    "allowed_license_families": ["cc0"],
    "max_assets_per_run": 3,
    # Smallest maps/resolutions first — keep automated downloads tiny.
    "preferred_resolutions": ["1k", "2k"],
    "preferred_formats": ["jpg", "png"],
}

_DEFAULT_QUARANTINE_ROOTS = [
    "WorldForgeAssetCache/_Quarantine",
    "Content/WorldForge/_Quarantine",
]


def download_source(source_id="polyhaven"):
    """Return the config block for a free-download source, merged over defaults.

    The config file's ``download_sources.<id>`` (if present) overrides the safe
    defaults key-by-key, so a partial config never drops a required knob.
    """
    cfg, _ = load_asset_config()
    block = (cfg.get("download_sources") or {}).get(source_id, {})
    if source_id == "polyhaven":
        merged = dict(_DEFAULT_POLYHAVEN)
        merged.update(block or {})
        return merged
    return dict(block or {})


def polyhaven_config():
    """Convenience accessor for the Poly Haven CC0 download source config."""
    return download_source("polyhaven")


def quarantine_roots():
    """Return the anchor-relative quarantine roots (config override or defaults)."""
    cfg, _ = load_asset_config()
    roots = cfg.get("quarantine_roots")
    if isinstance(roots, list) and roots:
        return [str(r).replace("\\", "/") for r in roots]
    return list(_DEFAULT_QUARANTINE_ROOTS)


if __name__ == "__main__":
    import sys

    cfg, src = load_asset_config()
    ph = polyhaven_config()
    roots = quarantine_roots()
    # Extensions must not break the existing megascans resolution.
    mega = external_library("megascans")
    assert mega.get("ownership_class") in (None, "third_party_owned"), mega
    assert ph.get("license_family") == "cc0", ph
    assert ph.get("allowed_license_families") == ["cc0"], ph
    assert roots and all("_Quarantine" in r for r in roots), roots
    sys.stdout.write("asset_config self-check OK\n")
    sys.stdout.write("  config_source     : {}\n".format(src.name if src else "<none>"))
    sys.stdout.write("  megascans_root    : {}\n".format(
        "resolved" if library_root("megascans") else "not on this machine"))
    sys.stdout.write("  polyhaven_api     : {}\n".format(ph.get("api_base")))
    sys.stdout.write("  quarantine_roots  : {}\n".format(", ".join(roots)))
