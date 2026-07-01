#!/usr/bin/env python3
"""test_negative_environment.py — negative-fixture gate for the environment contract.

Builds several KNOWN-BAD profile/binding trees in a temp dir and asserts that the
importable core ``validate_pack`` FAILS with the correct FailureCode for each.
This proves the environment-contract validator actually rejects broken data
instead of rubber-stamping it (no fake green).

Each fixture starts from a pristine copy of the real profiles tree, then mutates
exactly one thing. The validator is pointed at the fixture via its optional
``profiles_root`` / ``bindings_path`` overrides, so the real profiles are never
touched.

Run:
    PYTHONUTF8=1 python tools/pipeline/test_negative_environment.py
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
import profiles as P
from validate_environment_contract import validate_pack

PACK = "desert_mvp_world"
REAL_PROFILES = REPO_ROOT / "procedural" / "definitions" / "profiles"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _copy_tree(dst):
    shutil.copytree(REAL_PROFILES, dst)
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


def _run(profiles_root):
    """Run the core validator in strict mode against a fixture profiles root."""
    bindings = Path(profiles_root) / "bindings" / (PACK + ".yaml")
    rep = validate_pack(PACK, strict=True, profiles_root=str(profiles_root),
                        bindings_path=str(bindings))
    rep.finalize()
    return rep


# ---------------------------------------------------------------------------
# fixtures — each returns (name, expected_code) after mutating `root`
# ---------------------------------------------------------------------------
def fx_missing_binding(root):
    """Drop one slice from the binding overlay -> falls back to default."""
    bpath = root / "bindings" / (PACK + ".yaml")
    data = _load(bpath)
    victim = "Desert_AshFlats_IndustrialYard_Heavy_01"
    data["bindings"].pop(victim, None)
    _dump(bpath, data)
    return "binding_missing_a_slice", FailureCode.PROFILE_MISSING_BINDING


def fx_bad_child_reference(root):
    """Point an environment at a nonexistent sky profile."""
    epath = root / "environment" / "photoreal_desert_day.yaml"
    env = _load(epath)
    env["sky"] = "sky_that_does_not_exist"
    _dump(epath, env)
    return "environment_references_missing_sky", FailureCode.ENVIRONMENT_PROFILE_FAILURE


def fx_name_only_clone(root):
    """Add a post_process profile that is a byte-for-byte clone (name only)."""
    src = root / "post_process" / "neutral_daylight.yaml"
    data = _load(src)
    data["name"] = "neutral_daylight_clone"  # only the name differs
    _dump(root / "post_process" / "neutral_daylight_clone.yaml", data)
    return "name_only_clone_profile", FailureCode.PROFILE_NOT_MATERIAL


def fx_incompatible_combo(root):
    """Force an env that requires ray tracing to reference ray_tracing=off."""
    epath = root / "environment" / "cinematic_desert_high_contrast.yaml"
    env = _load(epath)
    env["ray_tracing"] = "off"  # rendering cinematic_rt has ray_tracing=required
    _dump(epath, env)
    return "incompatible_ray_tracing_combo", FailureCode.PROFILE_INCOMPATIBLE


def fx_missing_required_field(root):
    """Strip a required field from a referenced fog profile."""
    fpath = root / "fog" / "clear_thin_fog.yaml"
    fog = _load(fpath)
    fog.pop("density", None)
    _dump(fpath, fog)
    return "fog_missing_required_field", FailureCode.FOG_PROFILE_FAILURE


FIXTURES = [
    fx_missing_binding,
    fx_bad_child_reference,
    fx_name_only_clone,
    fx_incompatible_combo,
    fx_missing_required_field,
]


def main():
    passed = 0
    failures = []
    for fx in FIXTURES:
        with tempfile.TemporaryDirectory(prefix="wf_neg_env_") as tmp:
            root = _copy_tree(Path(tmp) / "profiles")
            name, expected = fx(root)
            rep = _run(root)
            codes = _failing_codes(rep)
            if rep.passed:
                failures.append("{}: validator PASSED a known-bad input".format(name))
                print("FAIL  {} — validator accepted broken input".format(name))
            elif expected not in codes:
                failures.append(
                    "{}: failed but without {} (got {})".format(name, expected, sorted(codes)))
                print("FAIL  {} — failed for the wrong reason (got {})".format(
                    name, sorted(codes)))
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
