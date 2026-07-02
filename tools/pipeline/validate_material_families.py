#!/usr/bin/env python3
"""validate_material_families.py — WorldForge v1.1 BiomeForge material-family gate.

Proves that EVERY material family named by EVERY non-desert biome in a BiomeForge
world pack has a real, materially-coherent definition: the file exists under
``procedural/definitions/materials/biomes/<biome>/<family>.yaml``, its family_id
and biome match, the family is compatible with the biome (declared in the
allow-list), it carries the required PBR fields (a non-grey preview_base_color,
roughness, palette_class), the palette_class is one the biome permits, and the
preview colour actually READS as the material it claims — snow bright, basalt/
charred dark, crystal/glowing iridescent or emissive — so a headless preview is
coherent and materially distinct across biomes.

Follows the v1.0x shared build contract: importable ``validate_pack``, one
ValidationReport per pack, one check per (biome, family) pair, meta attached,
record_count == number of (biome, family) pairs, canonical report path.

Core is importable:
    validate_pack(pack, strict, defs_root=None, biomes_root=None) -> ValidationReport
The negative harness injects a broken definition tree through ``defs_root``.
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
from world_pack_maps import resolve_world_pack_path, report_dir_for
import biomes as B

AXIS = "material_family"
CODE = FailureCode.MATERIAL_FAMILY_FAILURE

# Palette classes each biome permits. A material whose palette_class is not in its
# biome's set is materially wrong for that biome (e.g. a snow material in a
# volcanic biome). Keyed by biome id -> allowed palette classes.
BIOME_PALETTES = {
    "temperate_forest":        {"soil", "litter", "rock", "bark", "path"},
    "alpine_snow":             {"snow", "ice", "rock", "scoured", "path"},
    "volcanic_ashlands":       {"basalt", "ash", "charred", "heated", "sulfur"},
    "wetland_mire":            {"mud", "water", "peat", "moss", "stone"},
    "alien_crystal_badlands":  {"iridescent", "crystal", "dark_sand", "glowing", "alien_dust"},
}

# Materiality bands keyed by palette_class so a family cannot claim to be snow but
# render dark, or claim basalt but render bright.
BRIGHT_CLASSES = {"snow", "ice"}          # must read bright
DARK_CLASSES = {"basalt", "charred"}      # must read dark
IRIDESCENT_CLASSES = {"iridescent", "crystal", "glowing"}  # must read colourful/emissive

BRIGHT_LUM_MIN = 0.60
DARK_LUM_MAX = 0.28
IRIDESCENT_CHROMA_MIN = 0.12
GREY_CHROMA_MAX = 0.05            # below this chroma AND mid-luminance == grey
GREY_LUM_LO, GREY_LUM_HI = 0.20, 0.80


def _default_defs_root():
    return REPO_ROOT / "procedural" / "definitions"


def _load_yaml(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _rel(path):
    """Repo-relative string when possible; otherwise the raw path (fixtures)."""
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _pack_biomes(pack, biomes_root):
    wp_path = resolve_world_pack_path(pack)
    wp = _load_yaml(wp_path) or {}
    declared = wp.get("biome_families") or []
    present = set(B.list_biomes(biomes_root))
    return wp.get("world_pack_id", wp_path.stem), [b for b in declared if b in present]


def _luminance(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _chroma(rgb):
    return max(rgb) - min(rgb)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _family_reasons(biome_id, biome, family, path):
    """Return a list of material-family incoherence reasons (empty == coherent)."""
    if not path.is_file():
        return ["definition file missing: {}".format(_rel(path))]
    try:
        data = _load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        return ["definition unparseable: {}".format(exc)]
    if not isinstance(data, dict) or not data:
        return ["definition empty/not-a-mapping"]

    reasons = []
    if data.get("family_id") != family:
        reasons.append("family_id {!r} != family {!r}".format(data.get("family_id"), family))
    if data.get("biome") != biome_id:
        reasons.append("biome {!r} != {!r}".format(data.get("biome"), biome_id))
    if not B.compatible(biome, AXIS, family):
        reasons.append("family {!r} not in biome '{}' allow-list".format(family, biome_id))

    # preview_base_color: required, a 3-list of floats in [0,1].
    color = data.get("preview_base_color")
    valid_color = (isinstance(color, (list, tuple)) and len(color) == 3
                   and all(_num(c) is not None and 0.0 <= _num(c) <= 1.0 for c in color))
    if color is None:
        reasons.append("missing required 'preview_base_color' (would render grey)")
    elif not valid_color:
        reasons.append("preview_base_color must be 3 floats in [0,1], got {!r}".format(color))

    # roughness: required, [0,1].
    rough = _num(data.get("roughness"))
    if rough is None or not (0.0 <= rough <= 1.0):
        reasons.append("roughness must be a float in [0,1], got {!r}".format(data.get("roughness")))
    metallic = data.get("metallic")
    if metallic is not None and (_num(metallic) is None or not (0.0 <= _num(metallic) <= 1.0)):
        reasons.append("metallic must be a float in [0,1], got {!r}".format(metallic))

    # palette_class: required and permitted by the biome.
    pal = data.get("palette_class")
    allowed = BIOME_PALETTES.get(biome_id, set())
    if not pal:
        reasons.append("missing required 'palette_class'")
    elif pal not in allowed:
        reasons.append("palette_class {!r} not permitted in biome '{}' (allowed {})".format(
            pal, biome_id, sorted(allowed)))

    # Materiality: the colour must read as what the palette_class claims.
    if valid_color:
        rgb = [float(c) for c in color]
        lum, chroma = _luminance(rgb), _chroma(rgb)
        emissive = _num(data.get("emissive_intensity")) or 0.0
        if pal in BRIGHT_CLASSES and lum < BRIGHT_LUM_MIN:
            reasons.append("palette_class {!r} must read bright (luminance {:.3f} < {})".format(
                pal, lum, BRIGHT_LUM_MIN))
        if pal in DARK_CLASSES and lum > DARK_LUM_MAX:
            reasons.append("palette_class {!r} must read dark (luminance {:.3f} > {})".format(
                pal, lum, DARK_LUM_MAX))
        if pal in IRIDESCENT_CLASSES and chroma < IRIDESCENT_CHROMA_MIN and emissive <= 0.0:
            reasons.append("palette_class {!r} must read iridescent/emissive "
                           "(chroma {:.3f} < {} and no emissive)".format(
                               pal, chroma, IRIDESCENT_CHROMA_MIN))
        # No material may be a flat mid-grey (would read as an unset/default surface).
        if chroma < GREY_CHROMA_MAX and GREY_LUM_LO < lum < GREY_LUM_HI:
            reasons.append("preview_base_color is a flat mid-grey (chroma {:.3f}, luminance {:.3f}) "
                           "— reads as unset/default".format(chroma, lum))
    return reasons


def validate_pack(pack, strict, defs_root=None, biomes_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    defs_root = Path(defs_root) if defs_root else _default_defs_root()
    world_pack_id, pack_biomes = _pack_biomes(pack, biomes_root)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not pack_biomes:
        rep.check("pack_declares_biomes", False,
                  "world pack declares no resolvable biome_families", code=CODE)

    record_count = 0
    manifest = []
    for biome_id in pack_biomes:
        try:
            biome = B.load_biome(biome_id, biomes_root)
        except B.BiomeError as exc:
            rep.check("biome::{}".format(biome_id), False, str(exc), code=CODE)
            continue
        for family in B.allowed_values(biome, AXIS):
            record_count += 1
            path = defs_root / "materials" / "biomes" / biome_id / (family + ".yaml")
            reasons = _family_reasons(biome_id, biome, family, path)
            tag = "material_family::{}::{}".format(biome_id, family)
            rep.check(tag, not reasons,
                      "; ".join(reasons) if reasons else "material family coherent",
                      code=CODE)
            manifest.append((biome_id, family, not reasons))

    rep.set_meta(build_meta(
        command="validate-material-families", pack=world_pack_id, strict=strict, status=None,
        record_count=record_count, input_spec_hash=hash_obj(sorted(manifest))))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate BiomeForge material families for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--defs-root", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.defs_root)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id), "validate_material_families_report.json")
    rep.print_summary("validate-material-families")
    print("[validate-material-families] records={} (biome x material_family pairs)".format(
        rep.to_dict()["meta"]["record_count"]))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
