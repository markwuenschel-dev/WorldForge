#!/usr/bin/env python3
"""
test_negative_generated_asset.py
Negative-fixture gate for the Houdini generated-asset intake sidecar
(forge_design_decisions D7 / Risk 2).

For every invalid definition under tests/fixtures/invalid_generated_assets/, run
register_generated_asset.py (via --definition-path) and assert it is REJECTED
(non-zero exit). The load-bearing case: a forbidden Houdini Temp/Bake path can
never become a final registered path. Mirrors test_negative_placement.py.

Runnable as a plain script (no pytest needed in CI); pytest-compatible too.

Usage:
    python tools/pipeline/test_negative_generated_asset.py
    pytest tools/pipeline/test_negative_generated_asset.py
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "invalid_generated_assets"
REGISTRAR = REPO_ROOT / "tools" / "pipeline" / "register_generated_asset.py"


def _fixtures() -> list:
    return sorted(FIXTURES_DIR.glob("*.yaml"))


def _run_registrar(fixture: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REGISTRAR), "--definition-path", str(fixture)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_rejected(fixture: Path) -> None:
    result = _run_registrar(fixture)
    assert result.returncode != 0, (
        f"Expected REJECTION for invalid fixture '{fixture.name}', "
        f"but register_generated_asset.py exited 0 (accepted it).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_all_invalid_generated_assets_rejected() -> None:
    fixtures = _fixtures()
    assert fixtures, f"No invalid generated-asset fixtures found under {FIXTURES_DIR}"
    for fixture in fixtures:
        _assert_rejected(fixture)


def main() -> int:
    if not REGISTRAR.exists():
        print(f"ERROR: registrar not found: {REGISTRAR}", file=sys.stderr)
        return 2

    fixtures = _fixtures()
    if not fixtures:
        print(f"ERROR: no invalid generated-asset fixtures found under {FIXTURES_DIR}", file=sys.stderr)
        return 2

    failures = []
    for fixture in fixtures:
        result = _run_registrar(fixture)
        if result.returncode != 0:
            print(f"PASS  rejected: {fixture.name}")
        else:
            print(f"FAIL  ACCEPTED (should have been rejected): {fixture.name}")
            failures.append(fixture.name)

    print()
    if failures:
        print(f"NEGATIVE TEST FAILED: {len(failures)} invalid definition(s) were accepted:")
        for name in failures:
            print(f"  - {name}")
        return 1

    print(f"NEGATIVE TEST PASSED: all {len(fixtures)} invalid definition(s) rejected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
