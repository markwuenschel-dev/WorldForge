#!/usr/bin/env python3
"""asset_paths.py — canonical on-disk layout for the v1.5 acquisition chain.

Single source of truth so every stage (gap analysis -> procurement -> candidate
search -> quarantine -> approval -> catalog -> realization) writes and reads the
same directories. The schema-gate validators (validate_asset_*.py) glob these
exact dirs, so generators MUST write here.

Everything is relative to REPO_ROOT; helpers return absolute Paths and ensure the
directory exists on write-intent.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# -- generated record stores (schema validators glob these) ------------------
GEN = REPO_ROOT / "procedural" / "generated"
NEEDS_DIR = GEN / "assets" / "needs"
PROCUREMENT_DIR = GEN / "assets" / "procurement"
CANDIDATES_DIR = GEN / "assets" / "candidates"
APPROVALS_DIR = GEN / "assets" / "approvals"
QUARANTINE_RECORDS_DIR = GEN / "assets" / "quarantine"
CATALOG_DIR = GEN / "assets" / "catalog"
SHOPPING_LISTS_DIR = GEN / "assets" / "shopping_lists"
VISUAL_KITS_DIR = GEN / "visual" / "kits"
COVER_BINDINGS_DIR = GEN / "realization" / "cover_bindings"
OWNED_COVER_DIR = GEN / "realization" / "owned_cover_meshes"

# -- aggregate ledgers (append/upsert) --------------------------------------
ACQUISITION_CATALOG = GEN / "worldforge_asset_acquisition_catalog.json"

# -- quarantine data roots (bytes land here BEFORE any final path) -----------
# Relative anchors so validators can prove a quarantine path is under a root
# without depending on the machine-local absolute cache location.
QUARANTINE_ROOT_ANCHORS = (
    "WorldForgeAssetCache/_Quarantine",
    "Content/WorldForge/_Quarantine",
)
# Absolute on-disk quarantine roots (the first is the external asset-cache drive
# sibling; the second is inside the project content tree).
QUARANTINE_DATA_ROOTS = (
    Path("D:/WorldForgeAssetCache/_Quarantine"),
    REPO_ROOT / "Content" / "WorldForge" / "_Quarantine",
)

# -- report roots (full_shield gate cross-check expects these) ---------------
REPORTS = REPO_ROOT / "procedural" / "reports"
ASSETS_REPORTS = REPORTS / "assets"
REALIZATION_REPORTS = REPORTS / "realization"
VISUAL_REPORTS = REPORTS / "visual"


def ensure(path):
    """Ensure a directory (or a file's parent) exists; return the Path."""
    path = Path(path)
    target = path if path.suffix == "" else path.parent
    target.mkdir(parents=True, exist_ok=True)
    return path


def report_path(report_root, command):
    """procedural/reports/<root>/<command>/<command>_report.json (absolute)."""
    d = REPORTS / report_root / command
    d.mkdir(parents=True, exist_ok=True)
    return d, "{}_report.json".format(command)


def under_quarantine_root(path):
    """True if `path` (str/Path) sits under any quarantine root anchor."""
    s = str(path).replace("\\", "/")
    return any(anchor in s for anchor in QUARANTINE_ROOT_ANCHORS)


if __name__ == "__main__":
    import sys
    for name in ("NEEDS_DIR", "PROCUREMENT_DIR", "CANDIDATES_DIR", "APPROVALS_DIR",
                 "QUARANTINE_RECORDS_DIR", "CATALOG_DIR", "VISUAL_KITS_DIR",
                 "COVER_BINDINGS_DIR", "ACQUISITION_CATALOG"):
        sys.stdout.write("{:24s} {}\n".format(name, globals()[name]))
    assert under_quarantine_root("D:/WorldForgeAssetCache/_Quarantine/foo/bar.uasset")
    assert not under_quarantine_root("/Game/WorldForge/Generated/x")
    sys.stdout.write("asset_paths self-check OK\n")
