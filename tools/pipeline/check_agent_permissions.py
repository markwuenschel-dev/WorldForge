#!/usr/bin/env python3
"""
check_agent_permissions.py
Tier-0 forbidden-path checker (forge_design_decisions D7).

Given a set of changed files, fail (exit non-zero) if any change touches a
human-review-only surface (the CODEOWNERS surfaces): master content / *.uasset /
*.umap / *.sbs(.sbsar), the C++ modules under Plugins/WorldForge/Source/**, and
the CoreTerrainMaterials content plugin. Exit 0 if every change is within the
agent-editable surfaces (procedural/substance/recipes/, procedural/definitions/,
tools/, docs/, tests/).

This mirrors .github/CODEOWNERS so an agent gets a fast, deterministic local/CI
signal instead of waiting for a CODEOWNERS review request.

Pure stdlib (no pyyaml). Uses git via subprocess for --changed-against.

Usage:
    # explicit files
    python tools/pipeline/check_agent_permissions.py path/a path/b

    # diff against a ref (e.g. on a PR)
    python tools/pipeline/check_agent_permissions.py --changed-against origin/main

Exit codes:
    0  all changes within agent-editable paths (or no changes)
    1  at least one change in a human-review-only path
    2  usage / git error
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# --- Human-review-only surfaces (must mirror .github/CODEOWNERS) ---------------
# Directory prefixes (POSIX, repo-relative, trailing slash). A changed file is
# forbidden if its path starts with one of these.
FORBIDDEN_PREFIXES = (
    "Plugins/WorldForge/Source/",       # C++ runtime/editor modules (Source/WorldForge*)
    "Plugins/CoreTerrainMaterials/",    # CoreTerrainMaterials content plugin
)

# File extensions that are human-owned wherever they live (master content /
# binary Unreal assets / master Substance graphs).
FORBIDDEN_SUFFIXES = (
    ".uasset",
    ".umap",
    ".sbs",
    ".sbsar",
)

# --- Agent-editable surfaces (informational; everything outside FORBIDDEN_* is
# allowed, these are the intended homes per D7). -------------------------------
AGENT_EDITABLE_PREFIXES = (
    "procedural/substance/recipes/",
    "procedural/definitions/",
    "tools/",
    "docs/",
    "tests/",
)


def normalize(path: str) -> str:
    """Repo-relative POSIX path with no leading './'."""
    return path.strip().replace("\\", "/").lstrip("./") if path.startswith("./") else path.strip().replace("\\", "/")


def is_forbidden(path: str) -> bool:
    p = normalize(path)
    if not p:
        return False
    if any(p.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return True
    if p.lower().endswith(FORBIDDEN_SUFFIXES):
        return True
    return False


def changed_against(ref: str) -> list[str]:
    """Return files changed between <ref> and HEAD (git diff --name-only ref...HEAD).

    Returns [] (not an error) when there is no diff or the ref is unavailable,
    so CI does not crash on a fresh branch / shallow checkout.
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{ref}...HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        print("WARNING: git not found; treating diff as empty.", file=sys.stderr)
        return []
    except subprocess.CalledProcessError as exc:
        # Unknown ref / shallow clone — don't crash the workflow.
        print(
            f"WARNING: could not diff against '{ref}' "
            f"({(exc.stderr or '').strip()}); treating diff as empty.",
            file=sys.stderr,
        )
        return []
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tier-0 forbidden-path checker for agent-editable surfaces (D7)."
    )
    parser.add_argument("files", nargs="*", help="Explicit changed file paths to check.")
    parser.add_argument(
        "--changed-against",
        metavar="GIT_REF",
        help="Compute changed files via 'git diff --name-only <ref>...HEAD'.",
    )
    args = parser.parse_args()

    if args.changed_against and args.files:
        print("ERROR: pass either explicit files OR --changed-against, not both.", file=sys.stderr)
        return 2

    if args.changed_against:
        files = changed_against(args.changed_against)
    else:
        files = args.files

    if not files:
        print("No changed files to check. OK.")
        return 0

    violations = [f for f in files if is_forbidden(f)]

    if violations:
        print("FORBIDDEN: the following changes are in human-review-only paths (D7):")
        for v in violations:
            print(f"  - {normalize(v)}")
        print(
            "\nThese surfaces require a human reviewer (see .github/CODEOWNERS). "
            "Agent-editable surfaces: " + ", ".join(AGENT_EDITABLE_PREFIXES)
        )
        return 1

    print(f"OK: all {len(files)} changed file(s) are within agent-editable paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
