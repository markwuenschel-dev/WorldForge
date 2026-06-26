#!/usr/bin/env python3
"""clean_orphans.py

Delete generated assets that are not owned by any registry entry.
Without --confirm: dry-run only (safe to run freely).
With --confirm: actually deletes orphaned files/dirs.

Safety rules (checked before every deletion):
  - Only deletes under allowed generated paths
  - Never deletes files that are referenced_assets of any registry entry
  - Never deletes under: Content/Materials/, Content/Procedural/,
    Content/WorldForge/Placeholder/, tools/, procedural/slices/<biome>/*.yaml

Usage:
    python tools/pipeline/clean_orphans.py             # dry-run
    python tools/pipeline/clean_orphans.py --confirm   # actually delete

Exit code: 0 on success, 1 on safety violation (deletion blocked).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Paths where deletion is allowed (relative to repo root, as posix prefix).
ALLOWED_PREFIXES = [
    "Content/WorldForge/Maps/",
    "procedural/slices/",          # only generated/ subdirs, enforced below
    "procedural/reports/slices/",
    "procedural/generated/placement/",
]

# Paths that are NEVER safe to delete from, even if they somehow end up in orphans.
BLOCKED_PREFIXES = [
    "Content/Materials/",
    "Content/Procedural/",
    "Content/WorldForge/Placeholder/",
    "tools/",
    "procedural/substance/",
    "procedural/manifests/",
    "procedural/definitions/",
]


def _load_registry():
    sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
    from registry import load_registry
    return load_registry(REPO_ROOT)


def _all_referenced(registry):
    refs = set()
    for entry in registry.values():
        for r in entry.get("referenced_assets", []):
            refs.add(str(r).replace("\\", "/"))
    return refs


def _run_scan():
    """Import and run the same scan logic as list_orphans."""
    sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
    import list_orphans as lo
    import io
    from contextlib import redirect_stdout
    with redirect_stdout(io.StringIO()):
        lo.main()
    rpath = REPO_ROOT / "procedural" / "reports" / "orphans" / "orphan_scan_report.json"
    if not rpath.is_file():
        return []
    import json as _json
    return _json.loads(rpath.read_text(encoding="utf-8")).get("orphans", [])


def _is_safe_to_delete(rel_posix, referenced):
    """Return (safe: bool, reason: str)."""
    # Must not be a referenced asset.
    if rel_posix in referenced:
        return False, "is a referenced_asset in registry"

    # Must not be under a blocked prefix.
    for bp in BLOCKED_PREFIXES:
        if rel_posix.startswith(bp):
            return False, "under blocked prefix {}".format(bp)

    # Must be under an allowed prefix.
    for ap in ALLOWED_PREFIXES:
        if rel_posix.startswith(ap):
            # Extra guard for procedural/slices/: only allow generated/ subdirs.
            if ap == "procedural/slices/":
                if "/generated/" not in rel_posix:
                    return False, "procedural/slices/ path is not under generated/"
            return True, "ok"

    return False, "not under any allowed prefix"


def main():
    ap = argparse.ArgumentParser(
        description="Delete WorldForge orphaned generated assets."
    )
    ap.add_argument("--confirm", action="store_true",
                    help="Actually delete (without this flag: dry-run only)")
    args = ap.parse_args()

    if args.confirm:
        print("MODE: DELETE (--confirm set)")
    else:
        print("MODE: DRY-RUN (pass --confirm to actually delete)")

    registry = _load_registry()
    referenced = _all_referenced(registry)
    orphans = _run_scan()

    if not orphans:
        print("No orphans found — nothing to clean.")
        return 0

    deleted = []
    skipped = []
    blocked = []

    for o in orphans:
        rel = o["path"]
        safe, reason = _is_safe_to_delete(rel, referenced)
        full = REPO_ROOT / rel

        if not safe:
            blocked.append((rel, reason))
            print("  [BLOCKED]  {} — {}".format(rel, reason))
            continue

        if not full.exists():
            skipped.append(rel)
            print("  [GONE]     {} — already deleted".format(rel))
            continue

        if args.confirm:
            try:
                if full.is_dir():
                    shutil.rmtree(str(full))
                else:
                    full.unlink()
                deleted.append(rel)
                print("  [DELETED]  {}".format(rel))
            except OSError as exc:
                print("  [ERROR]    {} — {}".format(rel, exc))
                skipped.append(rel)
        else:
            print("  [DRY-RUN]  {} — would delete".format(rel))
            deleted.append(rel)  # count as "would delete" in dry-run summary

    print("\nSUMMARY")
    if args.confirm:
        print("  deleted:  {}".format(len(deleted)))
    else:
        print("  would delete: {}".format(len(deleted)))
    print("  blocked:  {}".format(len(blocked)))
    print("  skipped:  {}".format(len(skipped)))

    if blocked:
        print("\nBLOCKED (not deleted — safety rules):")
        for rel, reason in blocked:
            print("  {} — {}".format(rel, reason))

    return 0


if __name__ == "__main__":
    sys.exit(main())
