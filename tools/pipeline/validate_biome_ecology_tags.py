#!/usr/bin/env python3
"""validate_biome_ecology_tags.py — WorldForge v1.1 BiomeForge ecology gate.

Proves every biome family in a world pack declares a non-empty ``ecology_tags``
list drawn ONLY from the BiomeForge ecology vocabulary, and a non-empty
``entity_anchor_types`` list. Ecology tags are the encounter-substrate contract:
a biome that names an unknown ecology role (a typo, or a role no system knows how
to populate) is a BIOME_ECOLOGY_FAILURE — the vocabulary is closed.

This lane is pure contract data (no generated specs required), so it passes for
every declared biome family whose ecology data is honest.

record_count == number of biome families checked.

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

CODE = FailureCode.BIOME_ECOLOGY_FAILURE

# The closed BiomeForge ecology vocabulary. Every ecology_tag a biome declares
# MUST be one of these roles — an unknown tag is a contract failure, not a
# free-text label. Per-biome hostile/worker roles for the five non-desert
# families, the two shared placeholders, plus the desert_borderlands regression
# roles (present for completeness so the locked baseline validates too).
ECOLOGY_VOCAB = frozenset({
    "forest_scavenger", "forest_guard",
    "alpine_survivor", "alpine_drone",
    "ashland_raider", "ashland_worker",
    "wetland_stalker", "wetland_worker",
    "alien_crystal_sentinel", "alien_fungal_ambient",
    "neutral_trader_placeholder", "ambient_creature_placeholder",
    "desert_scavenger", "desert_raider",
})


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
    seen, out = set(), []
    for m in maps:
        b = m.get("biome")
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out


def _ecology_reasons(biome):
    """Return human-readable ecology/anchor problems (empty == OK)."""
    reasons = []

    tags = biome.get("ecology_tags")
    if not isinstance(tags, list) or not tags:
        reasons.append("ecology_tags missing or empty")
    else:
        unknown = [t for t in tags if t not in ECOLOGY_VOCAB]
        if unknown:
            reasons.append("unknown ecology tag(s) not in BiomeForge vocabulary: {}".format(unknown))

    anchors = biome.get("entity_anchor_types")
    if not isinstance(anchors, list) or not anchors:
        reasons.append("entity_anchor_types missing or empty")

    return reasons


def validate_pack(pack, strict, biomes_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    biome_families = _pack_biomes(pack, maps)
    if not biome_families:
        rep.check("pack_declares_biomes", False,
                  "world pack declares no biome_families and no maps resolve a biome", code=CODE)

    for biome_id in biome_families:
        tag = "biome_ecology::{}".format(biome_id)
        try:
            biome = B.load_biome(biome_id, biomes_root)
        except B.BiomeError as exc:
            rep.check(tag, False, "biome '{}' does not load: {}".format(biome_id, exc), code=CODE)
            continue
        reasons = _ecology_reasons(biome)
        rep.check(
            tag, not reasons,
            "biome '{}' ecology invalid: {}".format(biome_id, "; ".join(reasons))
            if reasons else "biome '{}' ecology_tags + entity_anchor_types valid".format(biome_id),
            code=CODE,
        )

    rep.set_meta(build_meta(
        command="validate-biome-ecology-tags", pack=world_pack_id, strict=strict,
        status=None, record_count=len(biome_families),
        input_spec_hash=hash_obj(sorted(biome_families)),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate biome ecology tags + entity anchors for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--biomes-root", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.biomes_root)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_biome_ecology_tags_report.json")
    rep.print_summary("validate-biome-ecology-tags")
    _, maps = enumerate_maps(args.pack)
    fams = _pack_biomes(args.pack, maps)
    print("[validate-biome-ecology-tags] records={} (biome families)".format(len(fams)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
