#!/usr/bin/env python3
"""test_negative_slfa.py — WorldForge v1.0x sky/lighting/fog/atmosphere negative harness.

Constructs KNOWN-BAD profile trees by copying the real profiles tree and mutating
exactly one field, then runs the matching validator core against the broken tree
(via the profiles_root override) and asserts it FAILS with the correct
FailureCode. A validator that green-lights a broken tree is itself a defect, so a
bad fixture that "passes" makes this harness exit non-zero.

Fixtures (each a documented, real defect the lane must catch):
  1. sky      — night sky run with daytime exposure     -> SKY_PROFILE_FAILURE
  2. lighting — requires ray tracing while env RT is off -> LIGHTING_PROFILE_FAILURE
  3. fog      — playable fog below the visibility floor  -> VISIBILITY_MINIMUM_VIOLATED
  4. fog      — fog-heavy profile missing low_visibility -> FOG_PROFILE_FAILURE
  5. lighting — exposure outside the lighting window     -> EXPOSURE_OUT_OF_RANGE

Prints `NEGATIVE OK: <n> fixtures failed as expected` and exits 0 iff every
known-bad fixture failed with its expected code.
"""

import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    raise

from failure_codes import FailureCode
import validate_sky
import validate_lighting
import validate_fog
import validate_atmosphere  # noqa: F401  (imported so an import error here fails the harness)

REAL_PROFILES_ROOT = REPO_ROOT / "procedural" / "definitions" / "profiles"
PACK = "desert_mvp_world"


def _copy_tree():
    """Copy the real profiles tree into a fresh temp dir; return its path."""
    tmp = Path(tempfile.mkdtemp(prefix="wf_slfa_neg_"))
    dst = tmp / "profiles"
    shutil.copytree(REAL_PROFILES_ROOT, dst)
    return tmp, dst


def _mutate(root, kind, name, field, value):
    """Set profiles/<kind>/<name>.yaml[field] = value in a copied tree."""
    path = Path(root) / kind / (name + ".yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data[field] = value
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _has_failing_code(rep, code):
    """True if the finalized report is failing AND a failing check carries `code`."""
    rep.finalize()
    if rep.passed:
        return False
    for c in rep.checks.values():
        if not c["ok"] and c.get("code") == code:
            return True
    return False


def _run_fixture(label, validator, mutate, expected_code):
    """Build a broken tree, run the validator core, assert the expected failure."""
    tmp, root = _copy_tree()
    try:
        mutate(root)
        rep = validator.validate_pack(PACK, strict=True, profiles_root=str(root))
        ok = _has_failing_code(rep, expected_code)
        status = "FAILED-AS-EXPECTED" if ok else "!! PASSED (BUG)"
        print("  [{}] {} -> {} (expected {})".format(
            "ok" if ok else "XX", label, status, expected_code))
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    fixtures = [
        (
            "night-sky-daytime-exposure",
            validate_sky,
            lambda root: _mutate(root, "post_process", "horror_desat", "exposure_ev", 0.0),
            FailureCode.SKY_PROFILE_FAILURE,
        ),
        (
            "lighting-requires-rt-env-off",
            validate_lighting,
            lambda root: _mutate(root, "lighting", "moonlit", "requires_ray_tracing", True),
            FailureCode.LIGHTING_PROFILE_FAILURE,
        ),
        (
            "fog-below-visibility-floor-not-lowvis",
            validate_fog,
            lambda root: _mutate(root, "fog", "clear_thin_fog", "visibility_min_cm", 100),
            FailureCode.VISIBILITY_MINIMUM_VIOLATED,
        ),
        (
            "fog-heavy-missing-lowvis-flag",
            validate_fog,
            lambda root: _mutate(root, "fog", "heavy_fog", "low_visibility", False),
            FailureCode.FOG_PROFILE_FAILURE,
        ),
        (
            "exposure-out-of-range",
            validate_lighting,
            lambda root: _mutate(root, "post_process", "neutral_daylight", "exposure_ev", 9.0),
            FailureCode.EXPOSURE_OUT_OF_RANGE,
        ),
    ]

    print("SLFA negative harness — {} known-bad fixtures".format(len(fixtures)))
    results = [_run_fixture(*f) for f in fixtures]
    n_ok = sum(results)
    if n_ok == len(fixtures):
        print("NEGATIVE OK: {} fixtures failed as expected".format(n_ok))
        return 0
    print("NEGATIVE FAIL: {}/{} fixtures failed as expected ({} bad fixture(s) "
          "slipped through)".format(n_ok, len(fixtures), len(fixtures) - n_ok))
    return 1


if __name__ == "__main__":
    sys.exit(main())
