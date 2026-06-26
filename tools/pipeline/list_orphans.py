#!/usr/bin/env python3
"""list_orphans.py

Scans WorldForge generated asset locations and reports any file not owned
by a registry entry. Safe read-only operation — writes a scan report only.

Usage:
    python tools/pipeline/list_orphans.py

Exit code: always 0 (listing never fails).
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories to scan for generated assets.
SCAN_PATTERNS = [
    ("Content/WorldForge/Maps", "*.umap"),
    ("procedural/generated/placement", "*_da.json"),
]

# Directories for generated spec JSONs (biome/generated/*.json).
SPEC_GLOB_BASE = REPO_ROOT / "procedural" / "slices"

# Directories for per-slice report dirs.
REPORTS_BASE = REPO_ROOT / "procedural" / "reports" / "slices"


def _load_registry():
    sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
    from registry import load_registry
    return load_registry(REPO_ROOT)


def _owned_assets(registry):
    owned = set()
    for entry in registry.values():
        for asset in entry.get("owned_assets", []):
            owned.add(str(Path(asset)).replace("\\", "/"))
    return owned


def _owned_specs(registry):
    specs = set()
    for entry in registry.values():
        sp = entry.get("spec_path")
        if sp:
            specs.add(str(Path(sp)).replace("\\", "/"))
    return specs


def _owned_slice_ids(registry):
    return set(registry.keys())


def main():
    registry = _load_registry()
    owned_assets = _owned_assets(registry)
    owned_specs  = _owned_specs(registry)
    owned_ids    = _owned_slice_ids(registry)

    orphans = []

    # Scan fixed-pattern directories.
    for rel_dir, pattern in SCAN_PATTERNS:
        scan_dir = REPO_ROOT / rel_dir
        if not scan_dir.is_dir():
            continue
        for f in scan_dir.glob(pattern):
            rel = f.relative_to(REPO_ROOT).as_posix()
            if rel not in owned_assets:
                orphans.append({"path": rel, "kind": "owned_asset"})

    # Scan generated spec JSONs.
    if SPEC_GLOB_BASE.is_dir():
        for biome_dir in SPEC_GLOB_BASE.iterdir():
            gen_dir = biome_dir / "generated"
            if not gen_dir.is_dir():
                continue
            for f in gen_dir.glob("*.json"):
                rel = f.relative_to(REPO_ROOT).as_posix()
                if rel not in owned_specs:
                    orphans.append({"path": rel, "kind": "spec_json"})

    # Scan per-slice report dirs.
    if REPORTS_BASE.is_dir():
        for biome_dir in REPORTS_BASE.iterdir():
            if not biome_dir.is_dir():
                continue
            for slice_dir in biome_dir.iterdir():
                if not slice_dir.is_dir():
                    continue
                slice_name = slice_dir.name
                if slice_name.startswith("_"):
                    continue  # staging dirs
                if slice_name not in owned_ids:
                    rel = slice_dir.relative_to(REPO_ROOT).as_posix()
                    orphans.append({"path": rel, "kind": "report_dir"})

    print("ORPHAN SCAN")
    if not orphans:
        print("  (none found)")
    for o in orphans:
        print("  {}  [ORPHAN - {}]".format(o["path"], o["kind"]))
    print("RESULT: {} orphan(s) found".format(len(orphans)))

    out_dir = REPO_ROOT / "procedural" / "reports" / "orphans"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "total_orphans": len(orphans),
        "orphans": orphans,
        "registry_slice_count": len(registry),
    }
    out_path = out_dir / "orphan_scan_report.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("Report: {}".format(out_path.relative_to(REPO_ROOT).as_posix()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
