#!/usr/bin/env python3
"""test_negative_biome_contract.py — negative-fixture gate for the BiomeForge lane.

Builds a KNOWN-BAD biome / binding tree in a temp dir for EACH of the five
BiomeForge validators and asserts the importable ``validate_pack`` core FAILS with
the expected FailureCode. This proves the biome validators actually reject broken
data instead of rubber-stamping it (no fake green).

Each fixture starts from a pristine copy of the real biomes tree (or the real
binding overlay), mutates exactly one thing, and points the validator at the
fixture through its injectable ``biomes_root`` / ``bindings_path`` / ``profiles_root``
overrides, so the real data is never touched.

Run:
    PYTHONUTF8=1 python tools/pipeline/test_negative_biome_contract.py
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
import validate_biome_contract as VC
import validate_biome_matrix as VM
import validate_biome_inspection as VI
import validate_biome_profile_bindings as VB
import validate_biome_environment_compatibility as VE

PACK = "biome_expansion_world"
REAL_BIOMES = REPO_ROOT / "procedural" / "definitions" / "biomes"
REAL_BINDINGS = (REPO_ROOT / "procedural" / "definitions" / "profiles"
                 / "bindings" / (PACK + ".yaml"))
VICTIM_BIOME = "temperate_forest"
VICTIM_SLICE = "Forest_RollingWoodland_Scatter_Photoreal_01"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _copy_biomes(dst):
    shutil.copytree(REAL_BIOMES, dst)
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
# fixtures — each returns (name, expected_code, finalized_rep)
# ---------------------------------------------------------------------------
def case_contract_missing_required_field():
    """Strip a required axis list from a biome -> BIOME_CONTRACT_FAILURE."""
    with tempfile.TemporaryDirectory(prefix="wf_neg_biome_") as tmp:
        root = _copy_biomes(Path(tmp) / "biomes")
        p = root / (VICTIM_BIOME + ".yaml")
        data = _load(p)
        data.pop("terrain_forms", None)
        _dump(p, data)
        rep = VC.validate_pack(PACK, strict=True, biomes_root=str(root))
        rep.finalize()
        return ("contract_missing_required_field",
                FailureCode.BIOME_CONTRACT_FAILURE, rep)


def case_contract_unknown_field():
    """Add an unknown top-level field to a biome -> contract lane rejects it."""
    with tempfile.TemporaryDirectory(prefix="wf_neg_biome_") as tmp:
        root = _copy_biomes(Path(tmp) / "biomes")
        p = root / (VICTIM_BIOME + ".yaml")
        data = _load(p)
        data["totally_unexpected_field"] = "surprise"
        _dump(p, data)
        rep = VC.validate_pack(PACK, strict=True, biomes_root=str(root))
        rep.finalize()
        return ("contract_unknown_field",
                FailureCode.BIOME_CONTRACT_FAILURE, rep)


def case_matrix_missing_axis_allowlist():
    """Remove a compatibility-axis allow-list -> BIOME_MATRIX_FAILURE."""
    with tempfile.TemporaryDirectory(prefix="wf_neg_biome_") as tmp:
        root = _copy_biomes(Path(tmp) / "biomes")
        p = root / (VICTIM_BIOME + ".yaml")
        data = _load(p)
        data.pop("raytracing_profiles", None)
        _dump(p, data)
        rep = VM.validate_pack(PACK, strict=True, biomes_root=str(root))
        rep.finalize()
        return ("matrix_missing_axis_allowlist",
                FailureCode.BIOME_MATRIX_FAILURE, rep)


def case_inspection_blank_description():
    """Blank a biome's description -> inspection completeness rejects it."""
    with tempfile.TemporaryDirectory(prefix="wf_neg_biome_") as tmp:
        root = _copy_biomes(Path(tmp) / "biomes")
        p = root / (VICTIM_BIOME + ".yaml")
        data = _load(p)
        data["description"] = "   "
        _dump(p, data)
        rep = VI.validate_pack(PACK, strict=True, biomes_root=str(root))
        rep.finalize()
        return ("inspection_blank_description",
                FailureCode.BIOME_CONTRACT_FAILURE, rep)


def case_bindings_env_not_declared_by_biome():
    """Bind a slice to an env the biome does not allow -> BIOME_PROFILE_BINDING_FAILURE."""
    with tempfile.TemporaryDirectory(prefix="wf_neg_biome_") as tmp:
        bpath = Path(tmp) / (PACK + ".yaml")
        overlay = _load(REAL_BINDINGS)
        overlay.setdefault("bindings", {})[VICTIM_SLICE] = "unlisted_env_not_in_allowlist"
        _dump(bpath, overlay)
        rep = VB.validate_pack(PACK, strict=True, biomes_root=None,
                               profiles_root=None, bindings_path=str(bpath))
        rep.finalize()
        return ("bindings_env_not_declared_by_biome",
                FailureCode.BIOME_PROFILE_BINDING_FAILURE, rep)


def case_env_compat_unresolvable_reference():
    """Add a bogus referenced profile to a biome -> BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE."""
    with tempfile.TemporaryDirectory(prefix="wf_neg_biome_") as tmp:
        root = _copy_biomes(Path(tmp) / "biomes")
        p = root / (VICTIM_BIOME + ".yaml")
        data = _load(p)
        data["sky_profiles"] = list(data.get("sky_profiles", [])) + ["__definitely_missing_sky__"]
        _dump(p, data)
        # Point profiles_root at the REAL profiles tree; the bogus sky cannot resolve.
        rep = VE.validate_pack(PACK, strict=True, biomes_root=str(root), profiles_root=None)
        rep.finalize()
        return ("env_compat_unresolvable_reference",
                FailureCode.BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE, rep)


CASES = [
    case_contract_missing_required_field,
    case_contract_unknown_field,
    case_matrix_missing_axis_allowlist,
    case_inspection_blank_description,
    case_bindings_env_not_declared_by_biome,
    case_env_compat_unresolvable_reference,
]


def main():
    passed = 0
    failures = []
    for case in CASES:
        name, expected, rep = case()
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
        print("NEGATIVE FAILED: {} case(s) did not fail correctly:".format(len(failures)))
        for f in failures:
            print("  - {}".format(f))
        return 1
    print("NEGATIVE OK: {} cases failed as expected".format(passed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
