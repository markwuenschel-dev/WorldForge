#!/usr/bin/env python3
"""list_orphans.py — WorldForge v0.9 hardened orphan detector (read-only).

Scans every WorldForge generated-content surface and reports any artifact that
is NOT owned by a live registry entry — i.e. a slice spec / placement DataAsset /
slice map / per-slice report directory that exists on disk but whose owning
slice_id is absent from ``worldforge_registry.json``.

This is the read-only companion to ``clean_orphans.py`` (which removes them under
``--confirm``) and to ``destroy_world_pack.py`` (which removes a whole world
pack's *registered* assets). It NEVER mutates project ``Content/**`` or any
registry; it only writes its own contract report under
``procedural/reports/orphans/``.

Ownership model (load-bearing — keep in lockstep with clean_orphans.py):
  * a generated artifact belongs to exactly one ``slice_id``;
  * an artifact is OWNED iff that slice_id is a key in the slice registry, OR the
    path itself appears in some entry's ``owned_assets`` / ``referenced_assets``;
  * everything else under a generated-owned tree is an ORPHAN.

The per-orphan finding is a WARN (non-blocking in normal mode, so a plain
``make list-orphans`` still exits 0 like the legacy tool) that becomes BLOCKING
under ``STRICT=1`` — a hardened/production build should carry no orphans.

Usage:
    python tools/pipeline/list_orphans.py            # scan (exit 0 unless STRICT)
    python tools/pipeline/list_orphans.py --strict   # orphans block (exit 1)
"""

import argparse
import json
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from registry import load_registry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

REPORT_DIR_REL = "procedural/reports/orphans"
REPORT_FILENAME = "list_orphans_report.json"

# Generated-content surfaces this scanner sweeps. Each tuple is
# (kind, base-dir relative to repo root, glob, is_dir_entry).
SLICES_SPEC_BASE = "procedural/slices"          # <biome>/generated/*.json
PLACEMENT_BASE = "procedural/generated/placement"  # *_da.json
MAPS_BASE = "Content/WorldForge/Maps"           # *.umap
REPORTS_SLICES_BASE = "procedural/reports/slices"  # <biome>/<slice>/


def _posix(p):
    return str(p).replace("\\", "/")


def _registry_paths(registry):
    """Every repo-relative path a registry entry claims (owned + referenced).

    Used as a defensive guard so a path explicitly tracked by ANY entry is never
    treated as an orphan, even if surface heuristics would otherwise flag it.
    """
    claimed = set()
    for entry in registry.values():
        for a in entry.get("owned_assets", []) or []:
            claimed.add(_posix(Path(a)))
        for r in entry.get("referenced_assets", []) or []:
            claimed.add(_posix(r))
        sp = entry.get("spec_path")
        if sp:
            claimed.add(_posix(Path(sp)))
    return claimed


def _da_slice_id(path):
    """Resolve the owning slice_id of a placement DA (json ``slice_id`` field,
    falling back to the filename minus the ``_da`` suffix)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        sid = data.get("slice_id")
        if sid:
            return sid
    except Exception:  # noqa: BLE001
        pass
    stem = path.stem
    return stem[:-3] if stem.endswith("_da") else stem


def scan_orphans(repo_root=REPO_ROOT, registry=None):
    """Return a list of orphan dicts. PURE: no writes, no prints.

    Each dict: ``{path, kind, slice_id, is_dir, exists}`` where ``path`` is the
    repo-relative POSIX path of the orphaned artifact.
    """
    repo_root = Path(repo_root)
    if registry is None:
        registry = load_registry(repo_root)
    owned_ids = set(registry.keys())
    claimed = _registry_paths(registry)

    orphans = []

    def _consider(path, kind, slice_id, is_dir=False):
        rel = _posix(path.relative_to(repo_root))
        if slice_id in owned_ids:
            return
        if rel in claimed:
            return
        orphans.append({
            "path": rel,
            "kind": kind,
            "slice_id": slice_id,
            "is_dir": is_dir,
            "exists": path.exists(),
        })

    # Real biomes are exactly those with a generated-spec tree on disk. Per-slice
    # report dirs mirror these; anything else under reports/slices/ (e.g. the
    # render-pack's variant-named screenshots buckets) is NOT a per-slice report.
    valid_biomes = set()
    spec_root = repo_root / SLICES_SPEC_BASE
    if spec_root.is_dir():
        for biome_dir in sorted(spec_root.iterdir()):
            if (biome_dir / "generated").is_dir():
                valid_biomes.add(biome_dir.name)

    # 1. Generated slice specs: procedural/slices/<biome>/generated/*.json
    if spec_root.is_dir():
        for biome_dir in sorted(spec_root.iterdir()):
            gen = biome_dir / "generated"
            if not gen.is_dir():
                continue
            for f in sorted(gen.glob("*.json")):
                _consider(f, "spec_json", f.stem)

    # 2. Placement DataAssets: procedural/generated/placement/*_da.json
    placement_root = repo_root / PLACEMENT_BASE
    if placement_root.is_dir():
        for f in sorted(placement_root.glob("*_da.json")):
            _consider(f, "placement_da", _da_slice_id(f))

    # 3. Slice maps: Content/WorldForge/Maps/*.umap
    maps_root = repo_root / MAPS_BASE
    if maps_root.is_dir():
        for f in sorted(maps_root.glob("*.umap")):
            _consider(f, "slice_map", f.stem)

    # 4. Per-slice report directories: procedural/reports/slices/<biome>/<slice>/
    reports_root = repo_root / REPORTS_SLICES_BASE
    if reports_root.is_dir():
        for biome_dir in sorted(reports_root.iterdir()):
            if not biome_dir.is_dir():
                continue
            if biome_dir.name not in valid_biomes:
                continue  # not a real biome (render-pack buckets, staging, etc.)
            for slice_dir in sorted(biome_dir.iterdir()):
                if not slice_dir.is_dir():
                    continue
                if slice_dir.name.startswith("_"):
                    continue  # staging dirs (e.g. _active_slice_spec)
                _consider(slice_dir, "report_dir", slice_dir.name, is_dir=True)

    return orphans


def _is_removable(rel_posix, registry):
    """Thin reuse of clean_orphans' ownership guard, so list and clean agree on
    what is generated-owned (and therefore safely removable)."""
    import clean_orphans
    return clean_orphans.is_safe_to_delete(rel_posix, registry)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="List WorldForge orphaned generated content (read-only).")
    ap.add_argument("--strict", action="store_true",
                    help="strict: orphan findings become blocking (exit 1)")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    registry = load_registry(REPO_ROOT)
    orphans = scan_orphans(REPO_ROOT, registry)

    rep = ValidationReport("orphan_scan", "generated_content", strict=strict)

    # group by slice_id for a readable console summary
    by_slice = {}
    for o in orphans:
        by_slice.setdefault(o["slice_id"], []).append(o)

    print("ORPHAN SCAN (strict={})".format("on" if strict else "off"))
    if not orphans:
        print("  (no orphaned generated content found)")
        rep.check("no_orphaned_generated_content", True,
                  "every generated artifact resolves to a registry-owned slice")
    else:
        for sid in sorted(by_slice):
            print("  unregistered slice '{}':".format(sid))
            for o in by_slice[sid]:
                removable, reason = _is_removable(o["path"], registry)
                tag = "removable" if removable else "RETAINED (ownership unresolved)"
                print("    [{}]  {}  ({})".format(o["kind"], o["path"], tag))
                name = "orphan:{}".format(o["path"])
                if removable:
                    rep.check(
                        name, False,
                        "unregistered {} owned by no registry slice "
                        "(slice_id={}) — removable via clean-orphans --confirm".format(
                            o["kind"], sid),
                        warn_only=True, code=FailureCode.REGISTRY_MISSING_ENTRY)
                else:
                    rep.check(
                        name, False,
                        "unregistered {} (slice_id={}) NOT under a generated-owned "
                        "tree: {} — will NOT be auto-removed".format(
                            o["kind"], sid, reason),
                        warn_only=True, code=FailureCode.OWNER_UNRESOLVABLE)

    rep.finalize()
    print("RESULT: {} orphan artifact(s) across {} unregistered slice(s)".format(
        len(orphans), len(by_slice)))

    rep.write(REPO_ROOT / REPORT_DIR_REL, REPORT_FILENAME)
    rep.print_summary("list-orphans")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
