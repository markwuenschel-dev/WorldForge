#!/usr/bin/env python3
"""test_negative_rendering.py — negative-fixture gate for the rendering/scalability/
ray-tracing/budget lane (Agent 6).

Builds several KNOWN-BAD profile trees in a temp dir and asserts that the correct
importable core FAILS with the expected FailureCode for each. This proves the
Agent-6 validators actually reject broken data instead of rubber-stamping it
(no fake green). Each fixture starts from a pristine copy of the real profiles
tree and mutates exactly one thing; the relevant core is pointed at the fixture
via its profiles_root / bindings_path overrides, so the real data is untouched.

Fixtures:
  1. rendering.ray_tracing==required paired with an env whose ray_tracing.mode==off
        -> validate_rendering_profiles  -> RENDERING_PROFILE_FAILURE
  2. a performance rendering profile with cost_class >= a cinematic profile
        -> validate_rendering_profiles  -> RENDERING_PROFILE_FAILURE
  3. a performance scalability tier bound to a cinematic rendering profile
        -> validate_scalability         -> SCALABILITY_FAILURE
  4. a rendering light_count_budget over the platform cap
        -> validate_performance_budgets -> BUDGET_FAILURE
  5. two name-only-clone rendering profiles
        -> validate_rendering_profiles  -> RENDERING_PROFILE_FAILURE

Run: PYTHONUTF8=1 python tools/pipeline/test_negative_rendering.py
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
import validate_rendering_profiles as VR
import validate_scalability as VS
import validate_performance_budgets as VB

PACK = "desert_mvp_world"
REAL_PROFILES = REPO_ROOT / "procedural" / "definitions" / "profiles"


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
    codes = set()
    for c in rep.checks.values():
        if not c["ok"] and c.get("blocking") and c.get("code"):
            codes.add(c["code"])
    return codes


def _run(core, root):
    bindings = Path(root) / "bindings" / (PACK + ".yaml")
    rep = core.validate_pack(PACK, strict=True, profiles_root=str(root),
                             bindings_path=str(bindings))
    rep.finalize()
    return rep


# ---------------------------------------------------------------------------
# fixtures — each mutates `root` and returns (name, core_module, expected_code)
# ---------------------------------------------------------------------------
def fx_rt_required_but_off(root):
    """cinematic_rt REQUIRES ray tracing; point its env at ray_tracing=off."""
    epath = root / "environment" / "cinematic_desert_high_contrast.yaml"
    env = _load(epath)
    env["ray_tracing"] = "off"
    _dump(epath, env)
    return "rt_required_but_env_off", VR, FailureCode.RENDERING_PROFILE_FAILURE


def fx_performance_not_cheaper(root):
    """Bump the performance profile's cost_class above the cinematic profiles."""
    rpath = root / "rendering" / "performance_baked.yaml"
    r = _load(rpath)
    r["cost_class"] = 99          # >= cinematic cost_class -> ordering violated
    r["light_count_budget"] = 999  # also no longer strictly cheaper on lights
    _dump(rpath, r)
    return "performance_not_cheaper_than_cinematic", VR, FailureCode.RENDERING_PROFILE_FAILURE


def fx_perf_tier_cinematic_render(root):
    """Bind a performance scalability tier under a cinematic rendering profile."""
    epath = root / "environment" / "cinematic_desert_high_contrast.yaml"
    env = _load(epath)
    env["scalability"] = "performance"  # tier low, max_rendering_cost_class 2
    _dump(epath, env)
    return "performance_tier_with_cinematic_rendering", VS, FailureCode.SCALABILITY_FAILURE


def fx_light_over_budget(root):
    """Push a rendering profile's light budget past its platform cap."""
    rpath = root / "rendering" / "performance_baked.yaml"
    r = _load(rpath)
    r["light_count_budget"] = 9999  # console cap is 24
    _dump(rpath, r)
    return "light_count_over_platform_budget", VB, FailureCode.BUDGET_FAILURE


def fx_name_only_clone(root):
    """Add a rendering profile that is a byte-for-byte clone (name only)."""
    src = root / "rendering" / "balanced_lumen.yaml"
    data = _load(src)
    data["name"] = "balanced_lumen_clone"  # only the name differs
    _dump(root / "rendering" / "balanced_lumen_clone.yaml", data)
    return "name_only_clone_rendering", VR, FailureCode.RENDERING_PROFILE_FAILURE


FIXTURES = [
    fx_rt_required_but_off,
    fx_performance_not_cheaper,
    fx_perf_tier_cinematic_render,
    fx_light_over_budget,
    fx_name_only_clone,
]


def main():
    passed = 0
    failures = []
    for fx in FIXTURES:
        with tempfile.TemporaryDirectory(prefix="wf_neg_render_") as tmp:
            root = _copy_tree(Path(tmp) / "profiles")
            name, core, expected = fx(root)
            rep = _run(core, root)
            codes = _failing_codes(rep)
            if rep.passed:
                failures.append("{}: {} PASSED a known-bad input".format(
                    name, core.__name__))
                print("FAIL  {} — {} accepted broken input".format(name, core.__name__))
            elif expected not in codes:
                failures.append("{}: failed without {} (got {})".format(
                    name, expected, sorted(codes)))
                print("FAIL  {} — failed for the wrong reason (got {})".format(
                    name, sorted(codes)))
            else:
                passed += 1
                print("OK    {} — {} failed as expected with {}".format(
                    name, core.__name__, expected))

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
