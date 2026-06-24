#!/usr/bin/env python3
"""
provenance.py
Shared provenance stamping for WorldForge manifest generators (MaterialForge,
PlacementForge, and every later forge).

Provenance is recorded honestly (forge_design_decisions D4): git commit, a
dirty flag scoped to the actual inputs, an ISO-8601 UTC timestamp, generator
identity, and a SHA-256 per input. A dirty input tree is flagged, never hidden.

Pure stdlib (no pyyaml) so it is safe to import from any pipeline script.
"""

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(repo_root: Path, *args) -> str:
    """Run a git command at the repo root; return stripped stdout, or '' on failure."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_provenance(
    repo_root: Path,
    input_paths,
    generator_name: str,
    generator_version: str,
) -> dict:
    """Stamp git + timestamp + generator + input-hash provenance.

    'dirty' is scoped to the actual inputs (the given paths) so unrelated
    working-tree churn does not falsely flag an asset's provenance. input_paths
    is an ordered iterable of pathlib.Path; missing paths are skipped.
    """
    existing = [p for p in input_paths if p.exists()]
    # POSIX-normalize repo-relative paths so manifests are identical across OSes
    # (git-friendly, and keeps the inputs-key / source_recipe staleness lookup stable).
    rel_inputs = [p.relative_to(repo_root).as_posix() for p in existing]

    dirty_inputs = git(repo_root, "status", "--porcelain", "--", *rel_inputs) if rel_inputs else ""

    inputs = {p.relative_to(repo_root).as_posix(): sha256(p) for p in existing}

    return {
        "generator_name": generator_name,
        "generator_version": generator_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git(repo_root, "rev-parse", "HEAD") or "unknown",
        "source_tree_dirty": bool(dirty_inputs),
        "inputs": inputs,
    }
