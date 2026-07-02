#!/usr/bin/env python3
"""validate_terrain_forms.py — WorldForge v1.1 BiomeForge terrain-form gate.

Proves that EVERY terrain form named by EVERY non-desert biome in a BiomeForge
world pack has a real, deterministic, non-degenerate terrain-form definition:
the definition file exists under
``procedural/definitions/terrain/biomes/<biome>/<form>.yaml``, its recipe_id and
biome match, the form is compatible with the biome (declared in the biome's
allow-list), the heightmap carries genuine relief, and the slope/placement/nav
masks are parameterised so a non-degenerate mask can be generated (thresholds in
(0, 90) and nav strictly flatter than placement). All data is deterministic
(explicit integer seed, no runtime randomness).

Follows the v1.0x shared build contract: importable ``validate_pack``, one
ValidationReport per pack, one check per (biome, form) pair, meta attached,
record_count == number of (biome, form) pairs, canonical report path.

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

AXIS = "terrain_form"
CODE = FailureCode.TERRAIN_FORM_FAILURE

MIN_RELIEF_CM = 200.0          # a form flatter than this yields a degenerate mask
SLOPE_MIN_DEG = 0.0            # a threshold at/below the horizon is degenerate
SLOPE_MAX_DEG = 90.0          # a threshold at/above vertical is degenerate


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
    """Return the ordered list of non-desert biome ids the pack declares that
    actually resolve to a biome family on disk."""
    wp_path = resolve_world_pack_path(pack)
    wp = _load_yaml(wp_path) or {}
    declared = wp.get("biome_families") or []
    present = set(B.list_biomes(biomes_root))
    return wp.get("world_pack_id", wp_path.stem), [b for b in declared if b in present]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _form_reasons(biome_id, biome, form, path):
    """Return (reasons, ok) for one terrain form. Empty reasons == materially real."""
    if not path.is_file():
        return ["definition file missing: {}".format(_rel(path))]
    try:
        data = _load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        return ["definition unparseable: {}".format(exc)]
    if not isinstance(data, dict) or not data:
        return ["definition empty/not-a-mapping"]

    reasons = []
    if data.get("recipe_id") != form:
        reasons.append("recipe_id {!r} != form {!r}".format(data.get("recipe_id"), form))
    if data.get("biome") != biome_id:
        reasons.append("biome {!r} != {!r}".format(data.get("biome"), biome_id))
    if not B.compatible(biome, AXIS, form):
        reasons.append("form {!r} not in biome '{}' allow-list".format(form, biome_id))

    gen = data.get("generation")
    if not isinstance(gen, dict):
        reasons.append("missing 'generation' block")
        return reasons
    if not isinstance(gen.get("seed"), int):
        reasons.append("generation.seed must be an integer (determinism)")

    hm = gen.get("heightmap")
    if not isinstance(hm, dict):
        reasons.append("missing 'generation.heightmap' block")
        return reasons
    hmin, hmax = _num(hm.get("height_min_cm")), _num(hm.get("height_max_cm"))
    if hmin is None or hmax is None:
        reasons.append("heightmap height_min_cm/height_max_cm non-numeric")
    else:
        relief = hmax - hmin
        if relief < MIN_RELIEF_CM:
            reasons.append("relief {:.1f}cm < {:.0f}cm — heightmap is degenerate/flat".format(
                relief, MIN_RELIEF_CM))
        if hmax > 65535.0 or hmin < 0.0:
            reasons.append("height range {}..{}cm outside UInt16 landscape budget".format(hmin, hmax))

    def _threshold(block, key, label):
        blk = gen.get(block)
        if not isinstance(blk, dict):
            reasons.append("missing '{}' block".format(block))
            return None
        val = _num(blk.get(key))
        if val is None:
            reasons.append("{}.{} non-numeric".format(block, key))
            return None
        if not (SLOPE_MIN_DEG < val < SLOPE_MAX_DEG):
            reasons.append("{} degrees {} not in ({},{}) — degenerate mask".format(
                label, val, SLOPE_MIN_DEG, SLOPE_MAX_DEG))
        return val

    steep = _threshold("slope_mask", "steep_threshold_degrees", "steep")
    place = _threshold("placement_mask", "slope_max_degrees", "placement")
    nav = _threshold("nav_safe_mask", "slope_max_degrees", "nav_safe")
    if place is not None and nav is not None and not (nav <= place):
        reasons.append("nav_safe slope_max {} > placement slope_max {} — nav must be flatter".format(
            nav, place))
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
        forms = B.allowed_values(biome, AXIS)
        for form in forms:
            record_count += 1
            path = defs_root / "terrain" / "biomes" / biome_id / (form + ".yaml")
            reasons = _form_reasons(biome_id, biome, form, path)
            tag = "terrain_form::{}::{}".format(biome_id, form)
            rep.check(tag, not reasons,
                      "; ".join(reasons) if reasons else "terrain form materially real",
                      code=CODE)
            manifest.append((biome_id, form, not reasons))

    rep.set_meta(build_meta(
        command="validate-terrain-forms", pack=world_pack_id, strict=strict, status=None,
        record_count=record_count, input_spec_hash=hash_obj(sorted(manifest))))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate BiomeForge terrain forms for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--defs-root", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.defs_root)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id), "validate_terrain_forms_report.json")
    rep.print_summary("validate-terrain-forms")
    print("[validate-terrain-forms] records={} (biome x terrain_form pairs)".format(
        rep.to_dict()["meta"]["record_count"]))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
