#!/usr/bin/env python3
"""corrupt_world_pack.py — WorldForge v1.0x lifecycle corruption harness (Agent 7).

Deliberately injects a single, named corruption into a world pack's
GENERATED-OWNED, deterministically-regenerable authoring artifacts so the
lifecycle-torture gate can prove every corruption class is DETECTED, CLASSIFIED,
and (for the safe/regenerable ones) REPAIRED — and that human-owned assets are
never touched.

SAFETY CONTRACT (non-negotiable)
--------------------------------
* Every corruption is applied ONLY to generated-owned artifacts that either
  snapshot+restore byte-for-byte or deterministically regenerate:
    - level-design overlays   procedural/generated/level_design/<slice>.json
    - entity-anchor overlays  procedural/generated/entity_anchors/<slice>.json
    - the slice registry      procedural/generated/worldforge_registry.json
    - generated slice specs   procedural/slices/<biome>/generated/<slice>.json
    - placement DataAssets     procedural/generated/placement/<slice>_da.json
    - per-pack report artifacts procedural/reports/world_packs/<pack>/*.json
    - (profiles are corrupted on a TEMP COPY only — the real definition tree is
      never mutated)
* Before mutating, the harness SNAPSHOTS the exact bytes of every file it will
  touch into a snapshot dir and records the change in ``corruption_manifest.json``.
  ``--restore`` (or restore(manifest)) puts the tree back to the pre-corruption
  bytes and deletes anything that was added.
* ``touch_human_owned_asset`` NEVER mutates a human-owned asset. It only writes a
  marker recording the *intent* plus the target's current hash, so the detector
  can prove the human asset was left byte-identical (a real mutation would be a
  ``REPAIR_TOUCHED_HUMAN_OWNED`` violation).

This module is import-friendly: ``lifecycle_torture`` / ``test_negative_lifecycle``
import ``MODES``, ``apply_corruption``, ``restore``, ``default_target`` and the
per-mode helpers rather than shelling out.

Usage:
    PYTHONUTF8=1 python tools/pipeline/corrupt_world_pack.py --pack desert_mvp_world \
        --mode delete_generated_asset [--target <slice_id>] [--dry-run]
    PYTHONUTF8=1 python tools/pipeline/corrupt_world_pack.py --restore \
        --manifest <path/to/corruption_manifest.json>
"""

import argparse
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode  # noqa: E402
from world_pack_maps import enumerate_maps, generated_spec_path  # noqa: E402

# --- canonical generated-owned locations -------------------------------------
LEVEL_DESIGN_DIR = REPO_ROOT / "procedural" / "generated" / "level_design"
ENTITY_ANCHORS_DIR = REPO_ROOT / "procedural" / "generated" / "entity_anchors"
PLACEMENT_DIR = REPO_ROOT / "procedural" / "generated" / "placement"
REGISTRY_PATH = REPO_ROOT / "procedural" / "generated" / "worldforge_registry.json"
PROFILES_ROOT = REPO_ROOT / "procedural" / "definitions" / "profiles"
REPORTS_DIR = REPO_ROOT / "procedural" / "reports" / "world_packs"

# A human-owned asset the harness must NEVER mutate (marker-only simulation).
# The master terrain material instance is the load-bearing human-owned asset in
# this repo (see MEMORY: master-basecolor-grey-bug).
HUMAN_OWNED_SENTINELS = (
    "Content/Materials/Terrain/MI_Terrain_Rock_Desert_Ash_01.uasset",
    "Content/Materials/Terrain/MI_Terrain_Rock_Desert_01.uasset",
    "procedural/slices/desert_heavy_industrial.yaml",  # human variant template
)

# --- mode taxonomy -----------------------------------------------------------
# Each mode: repairable (a deterministic regenerator/repair can fix it in place)
# vs restore-only (detect + restore from snapshot). ``classify`` is the stable
# failure code the detector SHOULD surface for this corruption class.
MODES = {
    "delete_generated_asset":     {"repairable": True,  "classify": FailureCode.POI_USABILITY_FAILURE},
    "delete_generated_manifest":  {"repairable": False, "classify": FailureCode.REGISTRY_MISSING_ENTRY},
    "truncate_manifest":          {"repairable": False, "classify": FailureCode.REGISTRY_MISSING_ENTRY},
    "duplicate_manifest_record":  {"repairable": False, "classify": FailureCode.REGISTRY_INCONSISTENT},
    "orphan_generated_asset":     {"repairable": False, "classify": FailureCode.REGISTRY_MISSING_ENTRY},
    "move_generated_asset":       {"repairable": True,  "classify": FailureCode.POI_USABILITY_FAILURE},
    "bad_generated_path":         {"repairable": False, "classify": FailureCode.PATH_NOT_OWNED},
    "remove_material_reference":  {"repairable": False, "classify": FailureCode.ASSET_REFERENCE_FAILURE},
    "remove_poi_reference":       {"repairable": False, "classify": FailureCode.ASSET_REFERENCE_FAILURE},
    "remove_environment_profile": {"repairable": False, "classify": FailureCode.ENVIRONMENT_PROFILE_FAILURE},
    "remove_lighting_profile":    {"repairable": False, "classify": FailureCode.LIGHTING_PROFILE_FAILURE},
    "remove_entity_anchor":       {"repairable": True,  "classify": FailureCode.ENTITY_ANCHOR_FAILURE},
    "touch_human_owned_asset":    {"repairable": False, "classify": FailureCode.REPAIR_TOUCHED_HUMAN_OWNED},
    "stale_report":               {"repairable": False, "classify": FailureCode.REPORT_STALE},
    "partial_destroy":            {"repairable": True,  "classify": FailureCode.POI_USABILITY_FAILURE},
    "partial_repair":             {"repairable": True,  "classify": FailureCode.ENTITY_ANCHOR_FAILURE},
}

MANIFEST_FILENAME = "corruption_manifest.json"


# =============================================================================
# helpers
# =============================================================================
def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def default_target(pack):
    """Pick a deterministic, overlay-complete target slice for the pack."""
    world_pack_id, maps = enumerate_maps(pack)
    preferred = "Desert_AshFlats_IndustrialYard_Heavy_01"
    present = [m for m in maps if m.spec_exists and m.slice_id]
    for m in present:
        if m.slice_id == preferred and (LEVEL_DESIGN_DIR / (m.slice_id + ".json")).is_file():
            return m.slice_id
    for m in present:
        if (LEVEL_DESIGN_DIR / (m.slice_id + ".json")).is_file():
            return m.slice_id
    return present[0].slice_id if present else None


def _spec_path_for(target):
    """Resolve the generated spec path for a slice via the registry biome."""
    from registry import load_registry
    reg = load_registry(REPO_ROOT)
    entry = reg.get(target, {})
    biome = entry.get("biome", "desert")
    return generated_spec_path(biome, target)


class Changes:
    """Records the exact-byte snapshot ledger for one corruption so it restores."""

    def __init__(self, snap_dir):
        self.snap_dir = Path(snap_dir)
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        self.records = []      # {path, existed_before, snapshot}
        self.temp_dirs = []    # dirs to rmtree on restore

    def snapshot(self, path):
        """Snapshot a file's current bytes (or record it as absent) before mutation."""
        path = Path(path)
        existed = path.is_file()
        snap = None
        if existed:
            snap = self.snap_dir / "{}__{}".format(len(self.records), path.name)
            shutil.copy2(str(path), str(snap))
        self.records.append({
            "path": str(path),
            "existed_before": existed,
            "snapshot": str(snap) if snap else None,
        })

    def note_added(self, path):
        """Record a file that did not exist before and must be deleted on restore."""
        self.records.append({"path": str(Path(path)), "existed_before": False, "snapshot": None})

    def add_temp_dir(self, path):
        self.temp_dirs.append(str(path))

    def to_manifest(self, mode, pack, target):
        return {
            "schema": "wf.corruption_manifest.v1",
            "mode": mode,
            "pack": pack,
            "target": target,
            "snapshot_dir": str(self.snap_dir),
            "changes": self.records,
            "temp_dirs": self.temp_dirs,
        }


def restore(manifest):
    """Restore the tree to its pre-corruption bytes. Idempotent. Returns count."""
    if isinstance(manifest, (str, Path)):
        manifest = _read_json(manifest)
    restored = 0
    for ch in reversed(manifest.get("changes", [])):
        path = Path(ch["path"])
        snap = ch.get("snapshot")
        if snap and Path(snap).is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snap, str(path))
            restored += 1
        elif not ch.get("existed_before", False) and path.exists():
            # File was added by the corruption — remove it.
            try:
                path.unlink()
                restored += 1
            except OSError:
                pass
    for d in manifest.get("temp_dirs", []):
        shutil.rmtree(d, ignore_errors=True)
    return restored


# =============================================================================
# per-mode corruptions
# =============================================================================
def _corrupt_delete_generated_asset(ch, pack, target):
    p = LEVEL_DESIGN_DIR / (target + ".json")
    ch.snapshot(p)
    if p.is_file():
        p.unlink()
    return "deleted level-design overlay {}".format(p.name)


def _corrupt_delete_generated_manifest(ch, pack, target):
    ch.snapshot(REGISTRY_PATH)
    if REGISTRY_PATH.is_file():
        REGISTRY_PATH.unlink()
    return "removed the slice registry (pack manifest)"


def _corrupt_truncate_manifest(ch, pack, target):
    ch.snapshot(REGISTRY_PATH)
    raw = REGISTRY_PATH.read_text(encoding="utf-8")
    REGISTRY_PATH.write_text(raw[: max(8, len(raw) // 3)], encoding="utf-8")
    return "truncated the slice registry to unparseable JSON"


def _corrupt_duplicate_manifest_record(ch, pack, target):
    ch.snapshot(REGISTRY_PATH)
    reg = _read_json(REGISTRY_PATH)
    if target in reg:
        dup_key = target + "__DUP"
        reg[dup_key] = copy.deepcopy(reg[target])
        reg[dup_key]["slice_id"] = dup_key
        _write_json(REGISTRY_PATH, reg)
        return "injected duplicate/rogue registry record {}".format(dup_key)
    return "target not registered; no duplicate injected"


def _corrupt_orphan_generated_asset(ch, pack, target):
    ch.snapshot(REGISTRY_PATH)
    reg = _read_json(REGISTRY_PATH)
    reg.pop(target, None)
    _write_json(REGISTRY_PATH, reg)
    return "dropped registry record for {} (asset now orphaned on disk)".format(target)


def _corrupt_move_generated_asset(ch, pack, target):
    src = LEVEL_DESIGN_DIR / (target + ".json")
    dst = LEVEL_DESIGN_DIR / (target + "__MOVED.json")
    ch.snapshot(src)
    ch.note_added(dst)
    if src.is_file():
        shutil.move(str(src), str(dst))
    return "moved overlay {} -> {}".format(src.name, dst.name)


def _corrupt_bad_generated_path(ch, pack, target):
    ch.snapshot(REGISTRY_PATH)
    reg = _read_json(REGISTRY_PATH)
    if target in reg:
        reg[target]["map_path"] = "/Game/HoudiniEngine/Temp/BROKEN_UNOWNED_PATH"
        _write_json(REGISTRY_PATH, reg)
        return "set {} map_path to a forbidden/unowned path".format(target)
    return "target not registered; no path corrupted"


def _material_ref_of(spec):
    return ((spec.get("terrain") or {}).get("material_mi")) or None


def _corrupt_remove_material_reference(ch, pack, target):
    ch.snapshot(REGISTRY_PATH)
    reg = _read_json(REGISTRY_PATH)
    entry = reg.get(target)
    if not entry:
        return "target not registered; no material reference removed"
    spec = _read_json(_spec_path_for(target)) if _spec_path_for(target).is_file() else {}
    mat = _material_ref_of(spec)
    refs = entry.get("referenced_assets", []) or []
    # Remove the material reference (and any material-ish ref) so the spec's
    # declared material_mi no longer resolves to the registry's reference set.
    entry["referenced_assets"] = [r for r in refs
                                  if r != mat and "/Materials/" not in str(r)]
    _write_json(REGISTRY_PATH, reg)
    return "removed material reference {} from {}".format(mat, target)


def _corrupt_remove_poi_reference(ch, pack, target):
    sp = _spec_path_for(target)
    ch.snapshot(sp)
    if sp.is_file():
        spec = _read_json(sp)
        spec.pop("poi_forge", None)
        _write_json(sp, spec)
        return "removed poi_forge reference block from {} spec".format(target)
    return "target spec missing; nothing to remove"


def _copy_profiles_tree(ch):
    """Copy the real profiles tree + binding into a temp dir. Returns temp root."""
    tmp = Path(tempfile.mkdtemp(prefix="wf_torture_profiles_"))
    shutil.copytree(str(PROFILES_ROOT), str(tmp / "profiles"))
    ch.add_temp_dir(str(tmp))
    return tmp / "profiles"


def _corrupt_remove_environment_profile(ch, pack, target):
    proot = _copy_profiles_tree(ch)
    # Delete the environment profile bound to the target slice (temp copy only).
    from profiles import load_bindings, environment_for
    world_pack_id, _ = enumerate_maps(pack)
    bindings = load_bindings(world_pack_id, str(proot))
    env_name, _src = environment_for(world_pack_id, target, str(proot), bindings=bindings)
    victim = proot / "environment" / (str(env_name) + ".yaml")
    if victim.is_file():
        victim.unlink()
    return {"profiles_root": str(proot),
            "detail": "deleted environment profile {} (temp copy)".format(env_name)}


def _corrupt_remove_lighting_profile(ch, pack, target):
    proot = _copy_profiles_tree(ch)
    from profiles import load_bindings, environment_for, load_profile
    world_pack_id, _ = enumerate_maps(pack)
    bindings = load_bindings(world_pack_id, str(proot))
    env_name, _src = environment_for(world_pack_id, target, str(proot), bindings=bindings)
    env = load_profile("environment", env_name, str(proot))
    lighting_name = env.get("lighting")
    victim = proot / "lighting" / (str(lighting_name) + ".yaml")
    if victim.is_file():
        victim.unlink()
    return {"profiles_root": str(proot),
            "detail": "deleted lighting profile {} (temp copy)".format(lighting_name)}


def _corrupt_remove_entity_anchor(ch, pack, target):
    p = ENTITY_ANCHORS_DIR / (target + ".json")
    ch.snapshot(p)
    if p.is_file():
        overlay = _read_json(p)
        overlay["anchors"] = []       # remove the entity-anchor substrate
        _write_json(p, overlay)
        return "removed all entity anchors from {} overlay".format(target)
    return "entity-anchor overlay missing; nothing to remove"


def _corrupt_touch_human_owned_asset(ch, pack, target):
    """SIMULATE ONLY. Never mutate a human asset — write a marker recording the
    intent and the target's current hash so the detector can prove it is untouched."""
    from report_meta import hash_file
    human = None
    for cand in HUMAN_OWNED_SENTINELS:
        if (REPO_ROOT / cand).exists():
            human = cand
            break
    if human is None:
        human = HUMAN_OWNED_SENTINELS[0]  # record intent even if absent in checkout
    marker = REPORTS_DIR / pack / ".torture_human_touch_marker.json"
    ch.note_added(marker)
    _write_json(marker, {
        "simulated": True,
        "would_touch": human,
        "pre_hash": hash_file(REPO_ROOT / human),
        "note": "marker only — the human-owned asset was NOT modified",
    })
    return {"human_owned": human, "marker": str(marker),
            "detail": "flagged (marker only) intent to touch human-owned {}".format(human)}


def _corrupt_stale_report(ch, pack, target):
    rpt = REPORTS_DIR / pack / "validate_pois_report.json"
    ch.snapshot(rpt)
    if rpt.is_file():
        data = _read_json(rpt)
    else:
        data = {"world_pack_id": pack, "checks": {}, "failures": []}
    # Fabricate a fake-green, zero-record, back-dated report.
    data["passed"] = True
    data["status"] = "ok"
    data["failures"] = []
    meta = data.get("meta") or {}
    meta["record_count"] = 0
    meta["status"] = "ok"
    meta["timestamp"] = "2000-01-01T00:00:00+00:00"
    meta["git_sha"] = "deadbeefstale"
    data["meta"] = meta
    _write_json(rpt, data)
    return "fabricated stale/zero-record fake-green report {}".format(rpt.name)


def _corrupt_partial_destroy(ch, pack, target):
    # Simulate an interrupted destroy: overlay + placement DA gone, registry/spec left.
    ld = LEVEL_DESIGN_DIR / (target + ".json")
    da = PLACEMENT_DIR / (target + "_da.json")
    for p in (ld, da):
        ch.snapshot(p)
        if p.is_file():
            p.unlink()
    return "half-destroyed {}: removed level-design overlay + placement DA".format(target)


def _corrupt_partial_repair(ch, pack, target):
    # Simulate an interrupted repair: entity-anchor overlay never re-emitted.
    ea = ENTITY_ANCHORS_DIR / (target + ".json")
    ch.snapshot(ea)
    if ea.is_file():
        ea.unlink()
    return "half-repaired {}: entity-anchor overlay left missing".format(target)


_CORRUPTORS = {
    "delete_generated_asset": _corrupt_delete_generated_asset,
    "delete_generated_manifest": _corrupt_delete_generated_manifest,
    "truncate_manifest": _corrupt_truncate_manifest,
    "duplicate_manifest_record": _corrupt_duplicate_manifest_record,
    "orphan_generated_asset": _corrupt_orphan_generated_asset,
    "move_generated_asset": _corrupt_move_generated_asset,
    "bad_generated_path": _corrupt_bad_generated_path,
    "remove_material_reference": _corrupt_remove_material_reference,
    "remove_poi_reference": _corrupt_remove_poi_reference,
    "remove_environment_profile": _corrupt_remove_environment_profile,
    "remove_lighting_profile": _corrupt_remove_lighting_profile,
    "remove_entity_anchor": _corrupt_remove_entity_anchor,
    "touch_human_owned_asset": _corrupt_touch_human_owned_asset,
    "stale_report": _corrupt_stale_report,
    "partial_destroy": _corrupt_partial_destroy,
    "partial_repair": _corrupt_partial_repair,
}


def apply_corruption(mode, pack, target=None, snap_dir=None, dry_run=False):
    """Apply one corruption. Returns a corruption_manifest dict (also written).

    ``dry_run`` reports what WOULD be corrupted without mutating anything.
    """
    if mode not in _CORRUPTORS:
        raise ValueError("unknown corruption mode: {}".format(mode))
    target = target or default_target(pack)
    if snap_dir is None:
        snap_dir = tempfile.mkdtemp(prefix="wf_torture_snap_")
    ch = Changes(snap_dir)

    if dry_run:
        return {"schema": "wf.corruption_manifest.v1", "mode": mode, "pack": pack,
                "target": target, "dry_run": True, "changes": [], "temp_dirs": [],
                "detail": "dry-run: would apply '{}' to {}".format(mode, target)}

    result = _CORRUPTORS[mode](ch, pack, target)
    manifest = ch.to_manifest(mode, pack, target)
    manifest["repairable"] = MODES[mode]["repairable"]
    manifest["expected_code"] = MODES[mode]["classify"]
    if isinstance(result, dict):
        manifest.update(result)
    else:
        manifest["detail"] = result
    return manifest


# =============================================================================
# CLI
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge lifecycle corruption harness (safe, restorable).")
    ap.add_argument("--pack", help="world pack id (e.g. desert_mvp_world)")
    ap.add_argument("--mode", choices=sorted(MODES.keys()), help="corruption mode")
    ap.add_argument("--target", default=None, help="target slice id (default: auto)")
    ap.add_argument("--dry-run", action="store_true", help="report only; mutate nothing")
    ap.add_argument("--restore", action="store_true", help="restore from a manifest")
    ap.add_argument("--manifest", default=None, help="manifest path (for --restore or output)")
    args = ap.parse_args(argv)

    if args.restore:
        mpath = args.manifest
        if not mpath:
            sys.stderr.write("ERROR: --restore requires --manifest\n")
            return 2
        n = restore(mpath)
        print("[corrupt-world-pack] restored {} change(s) from {}".format(n, mpath))
        return 0

    if not args.pack or not args.mode:
        ap.error("--pack and --mode are required (unless --restore)")

    manifest = apply_corruption(args.mode, args.pack, args.target, dry_run=args.dry_run)
    out = args.manifest or str(REPORTS_DIR / args.pack / MANIFEST_FILENAME)
    _write_json(out, manifest)
    tag = "DRY-RUN" if args.dry_run else "APPLIED"
    print("[corrupt-world-pack] {} mode={} target={}".format(tag, args.mode, manifest.get("target")))
    print("[corrupt-world-pack]   {}".format(manifest.get("detail", "")))
    print("[corrupt-world-pack]   manifest -> {}".format(out))
    if not args.dry_run:
        print("[corrupt-world-pack]   restore with: python tools/pipeline/corrupt_world_pack.py "
              "--restore --manifest {}".format(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
