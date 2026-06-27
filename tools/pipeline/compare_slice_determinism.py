#!/usr/bin/env python3
"""compare_slice_determinism.py

Verify that a named slice is deterministic: same inputs produce the same
content hash. Compares registry hash → spec hash → re-generated spec hash.

Usage:
    python tools/pipeline/compare_slice_determinism.py --name Desert_Ash_Outpost_01

Exit codes:
    0  deterministic
    1  mismatch or error
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Ensure registry.py is importable.
_PIPELINE = str(REPO_ROOT / "tools" / "pipeline")
if _PIPELINE not in sys.path:
    sys.path.insert(0, _PIPELINE)

from registry import load_registry  # noqa: E402


CREATE_SPEC = REPO_ROOT / "tools" / "pipeline" / "create_slice_spec.py"

# Fields that differ between two slices with different names but otherwise
# identical inputs — exclude before comparing semantic content.
_NAME_DEPENDENT = {"slice_id", "region_id", "map", "output_dir"}
# Fields that are always unstable (timestamps etc.).
_UNSTABLE = {"provenance", "generated_at_utc"}


def _semantic_hash(spec: dict) -> str:
    """SHA-256 of spec with name-dependent and unstable fields stripped."""
    cleaned = {
        k: v for k, v in spec.items()
        if k not in _NAME_DEPENDENT and k not in _UNSTABLE
    }
    # Also strip from nested provenance.
    cleaned.pop("provenance", None)
    raw = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Check that a slice is deterministic (same inputs → same hash)."
    )
    ap.add_argument("--name", required=True, help="slice name, e.g. Desert_Ash_Outpost_01")
    args = ap.parse_args(argv)

    name = args.name

    # 1. Load registry.
    registry = load_registry(REPO_ROOT)
    if name not in registry:
        sys.stderr.write(
            "ERROR: '{}' not found in registry. Run create-slice first.\n".format(name)
        )
        return 1

    entry = registry[name]
    registry_hash = entry.get("input_hash", "")
    biome = entry.get("biome", "desert")
    variant = entry.get("variant", "")
    seed = None  # will read from spec

    # 2. Load generated spec.
    spec_rel = entry.get("spec_path", "")
    spec_path = (REPO_ROOT / spec_rel) if spec_rel else (
        REPO_ROOT / "procedural" / "slices" / biome / "generated" / (name + ".json")
    )
    if not spec_path.is_file():
        sys.stderr.write("ERROR: spec not found: {}\n".format(spec_path))
        return 1

    with spec_path.open("r", encoding="utf-8") as fh:
        spec = json.load(fh)

    seed = spec.get("seed", 12345)
    placement_id = spec.get("placement_preset_id")
    state_preset_id = spec.get("state_preset_id")

    # 3. Compute hash of the on-disk spec (stable fields only).
    spec_hash = _semantic_hash(spec)

    # 4. Re-generate spec using a throwaway name into a temp dir.
    tmp_name = name + "_det_check_tmp"
    tmp_dir = REPO_ROOT / "procedural" / "reports" / "determinism"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(CREATE_SPEC),
        "--biome", biome,
        "--variant", variant,
        "--name", tmp_name,
        "--seed", str(seed),
    ]
    if placement_id:
        cmd += ["--placement", placement_id]
    if state_preset_id:
        cmd += ["--state-preset", state_preset_id]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True
    )

    regen_hash = ""
    regen_spec_path = (
        REPO_ROOT / "procedural" / "slices" / biome / "generated" / (tmp_name + ".json")
    )

    if result.returncode != 0:
        sys.stderr.write("ERROR: create_slice_spec.py failed:\n{}\n".format(result.stderr))
        regen_ok = False
    elif not regen_spec_path.is_file():
        sys.stderr.write("ERROR: re-generated spec not found at {}\n".format(regen_spec_path))
        regen_ok = False
    else:
        with regen_spec_path.open("r", encoding="utf-8") as fh:
            regen_spec = json.load(fh)
        regen_hash = _semantic_hash(regen_spec)
        # Copy to determinism report dir for inspection.
        shutil.copy(str(regen_spec_path), str(tmp_dir / (name + "_regen.json")))
        # Clean up temp spec from generated dir.
        regen_spec_path.unlink(missing_ok=True)
        regen_ok = True

    # 5. Compare.
    registry_matches_spec = (registry_hash == spec_hash)
    regen_matches_original = (regen_hash == spec_hash) if regen_ok else False
    deterministic = registry_matches_spec and regen_matches_original

    def _short(h):
        return h[:28] + "..." if len(h) > 28 else h

    print("DETERMINISM: {}".format(name))
    print("  registry_hash:  {}".format(_short(registry_hash)))
    match_spec = "MATCH" if registry_matches_spec else "MISMATCH"
    print("  spec_hash:      {}  {}".format(_short(spec_hash), match_spec))
    if regen_ok:
        match_regen = "MATCH" if regen_matches_original else "MISMATCH"
        print("  regen_hash:     {}  {}".format(_short(regen_hash), match_regen))
    else:
        print("  regen_hash:     (re-generation failed)")

    verdict = "DETERMINISTIC" if deterministic else "NOT DETERMINISTIC"
    print("RESULT: {}".format(verdict))

    # 6. Write report.
    report = {
        "slice_id": name,
        "biome": biome,
        "variant": variant,
        "seed": seed,
        "placement_preset_id": placement_id,
        "state_preset_id": state_preset_id,
        "registry_hash": registry_hash,
        "spec_hash": spec_hash,
        "regen_hash": regen_hash if regen_ok else None,
        "registry_matches_spec": registry_matches_spec,
        "regen_matches_original": regen_matches_original,
        "deterministic": deterministic,
    }
    report_path = tmp_dir / (name + "_determinism_report.json")
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("Report: {}".format(report_path.relative_to(REPO_ROOT).as_posix()))

    return 0 if deterministic else 1


if __name__ == "__main__":
    sys.exit(main())
