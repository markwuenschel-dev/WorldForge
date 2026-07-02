#!/usr/bin/env python3
"""test_negative_terrain_material.py — negative-fixture gate for the BiomeForge
terrain / material / vegetation / placement definition validators.

Builds several KNOWN-BAD definition trees in a temp dir and asserts that the
importable ``validate_pack`` core of the matching validator FAILS with the
correct FailureCode for each. This proves the definition validators actually
reject broken data (degenerate terrain, wrong-biome material, missing fields,
over-budget vegetation) instead of rubber-stamping it — no fake green.

Each fixture starts from a pristine copy of the real biome-definition subtrees
(terrain/materials/vegetation/placement under */biomes), then mutates exactly one
thing. The validator is pointed at the fixture via its ``defs_root`` override, so
the real definitions are never touched. Biome families are always read from the
real tree (the fixtures never corrupt the biome contract itself).

Run:
    PYTHONUTF8=1 python tools/pipeline/test_negative_terrain_material.py
Exits 0 iff every known-bad input failed for the expected reason.
"""

import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import yaml

from failure_codes import FailureCode
from validate_terrain_forms import validate_pack as validate_terrain_forms
from validate_material_families import validate_pack as validate_material_families
from validate_vegetation_profiles import validate_pack as validate_vegetation_profiles
from validate_placement_profiles import validate_pack as validate_placement_profiles

PACK = "biome_expansion_world"
REAL_DEFS = REPO_ROOT / "procedural" / "definitions"
SUBTREES = ("terrain", "materials", "vegetation", "placement")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _copy_defs(dst):
    """Copy the four biome-definition subtrees into a fixture defs_root."""
    for sub in SUBTREES:
        src = REAL_DEFS / sub / "biomes"
        if src.is_dir():
            shutil.copytree(src, Path(dst) / sub / "biomes")
    return dst


def _load(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _dump(path, data):
    with Path(path).open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def _failing_codes(rep):
    """Return the set of codes attached to blocking (failing) checks."""
    codes = set()
    for c in rep.checks.values():
        if not c["ok"] and c.get("blocking") and c.get("code"):
            codes.add(c["code"])
    return codes


# ---------------------------------------------------------------------------
# fixtures — each mutates `root` and returns (name, validate_fn, expected_code)
# ---------------------------------------------------------------------------
def fx_degenerate_terrain_mask(root):
    """Flatten a terrain form so the heightmap relief is zero (degenerate mask)."""
    p = root / "terrain" / "biomes" / "temperate_forest" / "rolling_woodland.yaml"
    data = _load(p)
    data["generation"]["heightmap"]["height_max_cm"] = data["generation"]["heightmap"]["height_min_cm"]
    _dump(p, data)
    return "degenerate_terrain_mask", validate_terrain_forms, FailureCode.TERRAIN_FORM_FAILURE


def fx_snow_material_in_volcanic(root):
    """Repaint a volcanic material as bright snow with a snow palette_class."""
    p = root / "materials" / "biomes" / "volcanic_ashlands" / "black_basalt.yaml"
    data = _load(p)
    data["palette_class"] = "snow"                 # not permitted in a volcanic biome
    data["preview_base_color"] = [0.92, 0.94, 0.98]  # and reads as snow, not basalt
    _dump(p, data)
    return "snow_material_in_volcanic", validate_material_families, FailureCode.MATERIAL_FAMILY_FAILURE


def fx_missing_preview_base_color(root):
    """Strip the preview_base_color from a material (would render grey)."""
    p = root / "materials" / "biomes" / "temperate_forest" / "mossy_soil.yaml"
    data = _load(p)
    data.pop("preview_base_color", None)
    _dump(p, data)
    return "missing_preview_base_color", validate_material_families, FailureCode.MATERIAL_FAMILY_FAILURE


def fx_missing_material_family(root):
    """Delete a material family file the biome requires."""
    p = root / "materials" / "biomes" / "volcanic_ashlands" / "sulfur_stain.yaml"
    p.unlink()
    return "missing_material_family", validate_material_families, FailureCode.MATERIAL_FAMILY_FAILURE


def fx_vegetation_over_budget(root):
    """Push a vegetation density above the biome's vegetation_density cap."""
    p = root / "vegetation" / "biomes" / "temperate_forest" / "sparse_woodland.yaml"
    data = _load(p)
    data["density"] = 0.95            # temperate_forest cap is 0.85
    _dump(p, data)
    return "vegetation_over_budget", validate_vegetation_profiles, FailureCode.VEGETATION_PROFILE_FAILURE


def fx_dense_canopy_over_performance_budget(root):
    """Push dense_canopy's performance_safe density above the perf cap."""
    p = root / "vegetation" / "biomes" / "temperate_forest" / "dense_canopy.yaml"
    data = _load(p)
    data["density_performance_safe"] = 0.60   # perf cap is 0.45
    _dump(p, data)
    return ("dense_canopy_over_performance_budget", validate_vegetation_profiles,
            FailureCode.VEGETATION_PROFILE_FAILURE)


FIXTURES = [
    fx_degenerate_terrain_mask,
    fx_snow_material_in_volcanic,
    fx_missing_preview_base_color,
    fx_missing_material_family,
    fx_vegetation_over_budget,
    fx_dense_canopy_over_performance_budget,
]


def main():
    passed = 0
    failures = []
    for fx in FIXTURES:
        with tempfile.TemporaryDirectory(prefix="wf_neg_terrmat_") as tmp:
            root = _copy_defs(Path(tmp) / "definitions")
            name, validate_fn, expected = fx(root)
            rep = validate_fn(PACK, strict=True, defs_root=str(root))
            rep.finalize()
            codes = _failing_codes(rep)
            if rep.passed:
                failures.append("{}: validator PASSED a known-bad input".format(name))
                print("FAIL  {} — validator accepted broken input".format(name))
            elif expected not in codes:
                failures.append(
                    "{}: failed but without {} (got {})".format(name, expected, sorted(codes)))
                print("FAIL  {} — failed for the wrong reason (got {})".format(name, sorted(codes)))
            else:
                passed += 1
                print("OK    {} — failed as expected with {}".format(name, expected))

    print()
    if failures:
        print("NEGATIVE FAILED: {} fixture(s) did not fail correctly:".format(len(failures)))
        for f in failures:
            print("  - {}".format(f))
        return 1
    print("NEGATIVE OK: {} fixtures failed as expected".format(passed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
