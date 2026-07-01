#!/usr/bin/env python3
"""generate_inspection_metadata.py — WorldForge v1.0 playable-inspection layer.

The smallest thing that makes generated maps inspectable by a human: a per-map
inspection record that states, in one place, what the map IS and whether it is
playable. For every map in a world pack it emits:

    procedural/generated/inspection/<name>.json     (per-map record)
    procedural/reports/inspection/<pack>_inspection.json  (pack index)

Each record carries the human-readable composition (terrain form, material
variant, placement preset, POI type, state preset), the runtime-scenario
compatibility, the in-editor map path, the PlayerStart/NavMesh/POI validity
distilled from the cached validate_slice report, and the overall validation
status. A human (or a thin in-editor reader) can open the index and immediately
identify every map's composition, its primary POI, and whether it passed.

No UE is launched and nothing under Content/** is written — this is the
authoring-side inspection metadata the contract requires for every MVP map.

Modes:
    (default)     generate metadata for every map in the pack
    --validate    do not write; assert metadata exists + is complete for every
                  map (Agent 5's inspection-metadata gate). Exit 1 on any gap.

Usage:
    python tools/pipeline/generate_inspection_metadata.py --pack procedural/world_packs/desert_mvp_world.yaml
    python tools/pipeline/generate_inspection_metadata.py --pack ... --validate [--strict]

Exit 0 = PASS, 1 = FAIL.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode

REQUIRED_RECORD_FIELDS = ("map_name", "map_path", "terrain_form", "material_variant",
                          "placement_preset", "poi_type", "state_preset",
                          "runtime_scenarios", "validation_status")

# Distil these playability signals out of the cached validate_slice report so the
# inspection record answers "is it playable?" without re-reading the UE report.
# Each signal maps to the first cached check name that exists (names vary slightly
# across validator versions; first match wins).
PLAYABILITY_CHECKS = ("player_start", "navmesh", "poi_reachable")
PLAYABILITY_CHECK_CANDIDATES = {
    "player_start": ("player_start", "playerstart"),
    "navmesh": ("nav_bounds", "navmesh", "nav_safe_mask", "terrain_forge_nav_safe_mask_exists"),
    "poi_reachable": ("poi_forge_actor", "poi_forge_anchors_spawned", "poi_reachable"),
}


def _load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _collect_slices(world_pack, default_biome):
    out = []
    for entry in world_pack.get("packs", []):
        rel = entry.get("pack_path", "")
        sp_path = REPO_ROOT / rel if rel else None
        if not sp_path or not sp_path.is_file():
            continue
        sp = _load_yaml(sp_path)
        biome = sp.get("biome", default_biome)
        for sl in sp.get("slices", []):
            out.append((biome, sl))
    return out


def _playability_from_report(biome, name):
    """Return (validation_status, {check: bool/None}, map_path) from the cached
    validate_slice report, or ('unvalidated', {...None}, default_path)."""
    rpt = (REPO_ROOT / "procedural" / "reports" / "slices" / biome / name
           / "validate_slice_report.json")
    signals = {c: None for c in PLAYABILITY_CHECKS}
    map_path = "/Game/WorldForge/Maps/{}".format(name)
    if not rpt.is_file():
        return "unvalidated", signals, map_path
    try:
        d = json.loads(rpt.read_text(encoding="utf-8"))
    except Exception:
        return "unreadable", signals, map_path
    map_path = d.get("map", map_path)
    checks = d.get("checks", {}) or {}
    # Map cached check names onto our coarse playability signals via explicit
    # candidates (first existing check wins).
    for sig in PLAYABILITY_CHECKS:
        for cand in PLAYABILITY_CHECK_CANDIDATES.get(sig, (sig,)):
            if cand in checks:
                signals[sig] = bool(checks[cand].get("ok"))
                break
    return d.get("status", "unknown"), signals, map_path


def _build_record(biome, sl):
    name = sl.get("name")
    status, signals, map_path = _playability_from_report(biome, name)
    return {
        "map_name": name,
        "map_path": map_path,
        "biome": biome,
        "terrain_form": sl.get("terrain"),
        "material_variant": sl.get("variant"),
        "placement_preset": sl.get("placement"),
        "poi_type": sl.get("poi"),
        "primary_poi": sl.get("poi"),
        "state_preset": sl.get("state_preset"),
        "runtime_scenarios": sl.get("scenarios") or [],
        "intent": sl.get("intent", ""),
        "playability": signals,
        "validation_status": status,
        "playable": status in ("ok", "warn"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate/validate per-map inspection metadata for a world pack.")
    ap.add_argument("--pack", required=True, help="Path to world pack YAML")
    ap.add_argument("--validate", action="store_true",
                    help="Validate that complete metadata exists for every map (no write).")
    ap.add_argument("--strict", action="store_true", help="Strict mode; also via STRICT=1.")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    pack_path = Path(args.pack)
    if not pack_path.is_absolute():
        pack_path = REPO_ROOT / pack_path
    if not pack_path.is_file():
        sys.stderr.write("ERROR: world pack not found: {}\n".format(pack_path))
        sys.exit(1)

    world_pack = _load_yaml(pack_path)
    world_pack_id = world_pack.get("world_pack_id", pack_path.stem)
    default_biome = (world_pack.get("global_defaults") or {}).get("biome", "desert")
    slices = _collect_slices(world_pack, default_biome)

    meta_dir = REPO_ROOT / "procedural" / "generated" / "inspection"
    index_dir = REPO_ROOT / "procedural" / "reports" / "inspection"

    if args.validate:
        rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
        rep.check("inspection_has_maps", bool(slices), "{} map(s)".format(len(slices)),
                  code=FailureCode.SPEC_INVALID)
        for biome, sl in slices:
            name = sl.get("name", "<unnamed>")
            rec_path = meta_dir / "{}.json".format(name)
            if not rec_path.is_file():
                rep.check("inspection:{}".format(name), False,
                          "no inspection metadata — run 'make inspect-world-pack PACK={}'".format(world_pack_id),
                          code=FailureCode.SPEC_INVALID)
                continue
            try:
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
            except Exception as exc:
                rep.check("inspection:{}".format(name), False, "unreadable: {}".format(exc),
                          code=FailureCode.SPEC_INVALID)
                continue
            missing = [f for f in REQUIRED_RECORD_FIELDS if rec.get(f) in (None, "")]
            rep.check("inspection:{}".format(name), not missing,
                      "complete" if not missing else "missing fields: {}".format("+".join(missing)),
                      code=FailureCode.SPEC_INVALID)
        rep.finalize()
        rep.write(index_dir, "validate_inspection_report.json", quiet=True)
        rep.print_summary("validate-inspection")
        sys.exit(rep.exit_code)

    # -- generate --------------------------------------------------------------
    meta_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for biome, sl in slices:
        rec = _build_record(biome, sl)
        (meta_dir / "{}.json".format(rec["map_name"])).write_text(
            json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        records.append(rec)

    n_playable = sum(1 for r in records if r["playable"])
    index = {
        "world_pack_id": world_pack_id,
        "map_count": len(records),
        "playable_count": n_playable,
        "maps": [{k: r[k] for k in ("map_name", "map_path", "terrain_form",
                                     "material_variant", "placement_preset", "poi_type",
                                     "state_preset", "runtime_scenarios", "validation_status",
                                     "playable")} for r in records],
    }
    (index_dir / "{}_inspection.json".format(world_pack_id)).write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("[inspect] wrote {} per-map records -> procedural/generated/inspection/".format(len(records)))
    print("[inspect] index -> procedural/reports/inspection/{}_inspection.json ({} playable)".format(
        world_pack_id, n_playable))
    sys.exit(0)


if __name__ == "__main__":
    main()
