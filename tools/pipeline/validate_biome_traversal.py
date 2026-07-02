#!/usr/bin/env python3
"""validate_biome_traversal.py — WorldForge v1.1 BiomeForge traversal gate.

Proves every biome family in a world pack declares a coherent ``traversal_rules``
block and that every map's terrain form is one its biome permits. Traversal is
where a biome earns "you can actually play here": a safe route must be required,
danger must never block ALL progression, and each biome must declare the
biome-specific traversal rule its hazard model needs (wetland deep-water tagging,
alpine ice/slope handling, ashlands lava-adjacent-does-not-block-all).

Two record classes:
  * per biome family (from the pack's ``biome_families``) — traversal_rules
    present and internally consistent.
  * per map — the map's terrain form is in its biome's ``terrain_forms``
    allow-list. Maps whose slice pack is missing are honest coverage-shortfall
    failures.

Failures carry BIOME_TRAVERSAL_FAILURE. record_count == biomes + maps checked.

Importable core:
    validate_pack(pack, strict, biomes_root=None) -> ValidationReport
The negative harness injects a broken biomes tree through ``biomes_root``.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    raise

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj
from world_pack_maps import enumerate_maps, report_dir_for, resolve_world_pack_path

import biomes as B

CODE = FailureCode.BIOME_TRAVERSAL_FAILURE


def _pack_biomes(pack, maps):
    """Return the pack's declared biome_families (fallback: distinct map biomes)."""
    wp_path = resolve_world_pack_path(pack)
    fams = []
    if wp_path.is_file():
        try:
            with wp_path.open("r", encoding="utf-8") as fh:
                wp = yaml.safe_load(fh) or {}
            fams = list(wp.get("biome_families") or [])
        except Exception:  # noqa: BLE001
            fams = []
    if fams:
        return fams
    # Honest fallback: whatever biomes the enumerated maps actually resolve to.
    seen, out = set(), []
    for m in maps:
        b = m.get("biome")
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out


def _traversal_reasons(biome_id, tr):
    """Return human-readable traversal inconsistencies (empty == coherent)."""
    if not isinstance(tr, dict) or not tr:
        return ["traversal_rules missing or not a non-empty mapping"]

    reasons = []

    # Universal invariants: a safe route is required, and danger never blocks all
    # progression. Both must be explicitly declared (no implicit default).
    if "safe_route_required" not in tr:
        reasons.append("traversal_rules missing 'safe_route_required'")
    elif tr.get("safe_route_required") is not True:
        reasons.append("'safe_route_required' must be true (got {!r})".format(
            tr.get("safe_route_required")))

    if "danger_blocks_all_progression" not in tr:
        reasons.append("traversal_rules missing 'danger_blocks_all_progression'")
    elif tr.get("danger_blocks_all_progression") is not False:
        reasons.append("'danger_blocks_all_progression' must be false (got {!r})".format(
            tr.get("danger_blocks_all_progression")))

    # Biome-specific traversal rule each hazard model must declare.
    if biome_id == "wetland_mire":
        v = tr.get("deep_water_requires_tag")
        if not isinstance(v, list) or not v:
            reasons.append("wetland_mire must declare a non-empty 'deep_water_requires_tag'")
    elif biome_id == "alpine_snow":
        if tr.get("ice_hazard_tag_required") is None and not tr.get("steep_slope_rule"):
            reasons.append("alpine_snow must declare an ice/slope traversal rule "
                           "('ice_hazard_tag_required' or 'steep_slope_rule')")
    elif biome_id == "volcanic_ashlands":
        if "lava_adjacent_blocks_all_progression" not in tr:
            reasons.append("volcanic_ashlands must declare 'lava_adjacent_blocks_all_progression'")
        elif tr.get("lava_adjacent_blocks_all_progression") is not False:
            reasons.append("volcanic_ashlands 'lava_adjacent_blocks_all_progression' must be false "
                           "(got {!r})".format(tr.get("lava_adjacent_blocks_all_progression")))

    return reasons


def validate_pack(pack, strict, biomes_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    biome_families = _pack_biomes(pack, maps)
    if not biome_families:
        rep.check("pack_declares_biomes", False,
                  "world pack declares no biome_families and no maps resolve a biome", code=CODE)

    # --- per-biome traversal-contract checks --------------------------------
    for biome_id in biome_families:
        tag = "biome_traversal::{}".format(biome_id)
        try:
            biome = B.load_biome(biome_id, biomes_root)
        except B.BiomeError as exc:
            rep.check(tag, False, "biome '{}' does not load: {}".format(biome_id, exc), code=CODE)
            continue
        reasons = _traversal_reasons(biome_id, biome.get("traversal_rules"))
        rep.check(
            tag, not reasons,
            "biome '{}' traversal_rules incoherent: {}".format(biome_id, "; ".join(reasons))
            if reasons else "biome '{}' traversal_rules coherent".format(biome_id),
            code=CODE,
        )

    # --- per-map terrain-form sanity ----------------------------------------
    for i, m in enumerate(maps):
        tag = "biome_traversal_map::{:02d}::{}".format(
            i, m.slice_id or m.get("pack_id") or "<unknown>")
        biome_id = m.get("biome")
        terrain = m.get("row", {}).get("terrain") if isinstance(m.get("row"), dict) else None

        if not m.slice_id or not biome_id:
            rep.check(tag, False,
                      "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id/biome"),
                      code=CODE)
            continue
        try:
            biome = B.load_biome(biome_id, biomes_root)
        except B.BiomeError as exc:
            rep.check(tag, False, "biome '{}' does not load: {}".format(biome_id, exc), code=CODE)
            continue
        if not isinstance(terrain, str) or not terrain.strip():
            rep.check(tag, False, "map declares no terrain form (row.terrain missing)", code=CODE)
            continue
        ok = B.compatible(biome, "terrain_form", terrain)
        rep.check(
            tag, ok,
            "terrain '{}' not in biome '{}' terrain_forms {}".format(
                terrain, biome_id, B.allowed_values(biome, "terrain_form"))
            if not ok else "terrain '{}' permitted by biome '{}'".format(terrain, biome_id),
            code=CODE,
        )

    record_count = len(biome_families) + len(maps)
    rep.set_meta(build_meta(
        command="validate-biome-traversal", pack=world_pack_id, strict=strict,
        status=None, record_count=record_count,
        input_spec_hash=hash_obj(sorted(biome_families)),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate biome traversal rules + terrain forms for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--biomes-root", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.biomes_root)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_biome_traversal_report.json")
    rep.print_summary("validate-biome-traversal")
    _, maps = enumerate_maps(args.pack)
    fams = _pack_biomes(args.pack, maps)
    print("[validate-biome-traversal] records={} ({} biomes + {} maps)".format(
        len(fams) + len(maps), len(fams), len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
