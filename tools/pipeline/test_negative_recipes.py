#!/usr/bin/env python3
"""
test_negative_recipes.py
Negative-fixture gate (forge_design_decisions D7, Tier 1).

For every invalid recipe under tests/fixtures/invalid_recipes/, run
validate_recipe.py against it (via --recipe-path) and assert it is REJECTED
(non-zero exit). The validator earns trust only if it actually catches each
deliberately-broken contract rule.

Runnable as a plain script (no pytest needed in CI); pytest-compatible too
(it exposes test_* functions that pytest will discover).

Usage:
    python tools/pipeline/test_negative_recipes.py
    pytest tools/pipeline/test_negative_recipes.py
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "invalid_recipes"
VALIDATOR = REPO_ROOT / "tools" / "substance" / "validate_recipe.py"


def _fixtures() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.yaml"))


def _run_validator(fixture: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--recipe-path", str(fixture)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_rejected(fixture: Path) -> None:
    """Raise AssertionError if the validator did NOT reject the fixture."""
    result = _run_validator(fixture)
    assert result.returncode != 0, (
        f"Expected REJECTION for invalid fixture '{fixture.name}', "
        f"but validate_recipe.py exited 0 (accepted it).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_all_invalid_recipes_rejected() -> None:
    """pytest entry point: every fixture must be rejected."""
    fixtures = _fixtures()
    assert fixtures, f"No invalid-recipe fixtures found under {FIXTURES_DIR}"
    for fixture in fixtures:
        _assert_rejected(fixture)


def main() -> int:
    if not VALIDATOR.exists():
        print(f"ERROR: validator not found: {VALIDATOR}", file=sys.stderr)
        return 2

    fixtures = _fixtures()
    if not fixtures:
        print(f"ERROR: no invalid-recipe fixtures found under {FIXTURES_DIR}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for fixture in fixtures:
        result = _run_validator(fixture)
        if result.returncode != 0:
            print(f"PASS  rejected: {fixture.name}")
        else:
            print(f"FAIL  ACCEPTED (should have been rejected): {fixture.name}")
            failures.append(fixture.name)

    print()
    if failures:
        print(f"NEGATIVE TEST FAILED: {len(failures)} invalid recipe(s) were accepted:")
        for name in failures:
            print(f"  - {name}")
        return 1

    print(f"NEGATIVE TEST PASSED: all {len(fixtures)} invalid recipe(s) rejected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
