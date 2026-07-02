#!/usr/bin/env python3
"""test_negative_biome_poi_ecology.py — negative-fixture gate for the BiomeForge
POI / traversal / ecology validators.

Builds several KNOWN-BAD biome trees in a temp dir and asserts the importable
cores FAIL with the correct FailureCode for each. This proves the three
validators actually reject broken biome contracts instead of rubber-stamping
them (no fake green).

Each fixture starts from a pristine copy of the real biomes tree, then mutates
exactly one thing in ONE biome (temperate_forest — the only family whose slice
pack currently exists, so its maps are real). The validator is pointed at the
fixture via its ``biomes_root`` override, so the real biome definitions are never
touched. Because the pack also has coverage-shortfall failures (4 biomes have no
slice pack yet), each fixture asserts a SPECIFIC check — the one the injected
defect targets — flipped from PASS to FAIL with the expected code, rather than
merely that the code appears somewhere.

Run:
    PYTHONUTF8=1 python tools/pipeline/test_negative_biome_poi_ecology.py
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
from validate_biome_poi_compatibility import validate_pack as poi_validate
from validate_biome_traversal import validate_pack as traversal_validate
from validate_biome_ecology_tags import validate_pack as ecology_validate

PACK = "biome_expansion_world"
REAL_BIOMES = REPO_ROOT / "procedural" / "definitions" / "biomes"
TARGET_BIOME = "temperate_forest"
# A temperate_forest map that is legal in the pristine tree (poi navigation_landmark,
# terrain rolling_woodland) — the POI fixture makes exactly this map illegal.
TARGET_MAP = "Forest_RollingWoodland_Scatter_Photoreal_01"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _copy_tree(dst):
    shutil.copytree(REAL_BIOMES, dst)
    return dst


def _load(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _dump(path, data):
    with Path(path).open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def _specific_fail(rep, tag_substr, expected):
    """True iff some blocking, failing check whose name contains tag_substr
    carries the expected code. Robust against unrelated coverage-shortfall noise."""
    for name, c in rep.checks.items():
        if tag_substr in name and not c["ok"] and c.get("blocking") and c.get("code") == expected:
            return True
    return False


# ---------------------------------------------------------------------------
# fixtures — each mutates `root`, runs a validator, returns
# (name, rep, expected_code, tag_substr)
# ---------------------------------------------------------------------------
def fx_poi_not_in_biome_list(root):
    """Remove a POI class that a temperate_forest map requests from the biome's
    poi_compatibility allow-list -> that map becomes POI-incompatible."""
    bpath = root / (TARGET_BIOME + ".yaml")
    biome = _load(bpath)
    biome["poi_compatibility"] = [p for p in biome["poi_compatibility"]
                                  if p != "navigation_landmark"]
    _dump(bpath, biome)
    rep = poi_validate(PACK, strict=True, biomes_root=str(root))
    rep.finalize()
    return ("poi_class_not_in_biome_list", rep,
            FailureCode.BIOME_POI_COMPATIBILITY_FAILURE, TARGET_MAP)


def fx_traversal_missing_safe_route(root):
    """Strip safe_route_required AND set danger_blocks_all_progression=true on a
    biome's traversal_rules -> traversal contract is incoherent."""
    bpath = root / (TARGET_BIOME + ".yaml")
    biome = _load(bpath)
    tr = biome["traversal_rules"]
    tr.pop("safe_route_required", None)
    tr["danger_blocks_all_progression"] = True
    _dump(bpath, biome)
    rep = traversal_validate(PACK, strict=True, biomes_root=str(root))
    rep.finalize()
    return ("traversal_missing_safe_route_and_danger_blocks_all", rep,
            FailureCode.BIOME_TRAVERSAL_FAILURE, "biome_traversal::" + TARGET_BIOME)


def fx_ecology_unknown_tag(root):
    """Inject an ecology tag outside the BiomeForge vocabulary."""
    bpath = root / (TARGET_BIOME + ".yaml")
    biome = _load(bpath)
    biome["ecology_tags"] = list(biome["ecology_tags"]) + ["totally_bogus_role"]
    _dump(bpath, biome)
    rep = ecology_validate(PACK, strict=True, biomes_root=str(root))
    rep.finalize()
    return ("ecology_unknown_tag", rep,
            FailureCode.BIOME_ECOLOGY_FAILURE, "biome_ecology::" + TARGET_BIOME)


FIXTURES = [
    fx_poi_not_in_biome_list,
    fx_traversal_missing_safe_route,
    fx_ecology_unknown_tag,
]


def main():
    passed = 0
    failures = []
    for fx in FIXTURES:
        with tempfile.TemporaryDirectory(prefix="wf_neg_biome_") as tmp:
            root = _copy_tree(Path(tmp) / "biomes")
            name, rep, expected, tag_substr = fx(root)
            if rep.passed:
                failures.append("{}: validator PASSED a known-bad input".format(name))
                print("FAIL  {} — validator accepted broken input".format(name))
            elif not _specific_fail(rep, tag_substr, expected):
                failures.append(
                    "{}: failed but not the targeted check '{}' with {}".format(
                        name, tag_substr, expected))
                print("FAIL  {} — targeted check '{}' did not fail with {}".format(
                    name, tag_substr, expected))
            else:
                passed += 1
                print("OK    {} — targeted check '{}' failed as expected with {}".format(
                    name, tag_substr, expected))

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
