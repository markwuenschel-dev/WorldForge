#!/usr/bin/env python3
"""validate_world_pack.py — WorldForge v0.5 world pack validator.

Runs validate_slice_pack.py for each referenced slice pack, aggregates results.

Usage:
    python tools/pipeline/validate_world_pack.py \
        --pack procedural/world_packs/desert_production_seed.yaml \
        [--deep] [--read-only]

Exit 0 if all packs pass, 1 if any fail.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_PACK_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "validate_slice_pack.py"


def _run_validate_pack(slice_pack_path: Path, deep: bool, read_only: bool) -> tuple:
    """Run validate_slice_pack.py and return (returncode, pass_count, total)."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    cmd = [sys.executable, str(VALIDATE_PACK_SCRIPT), "--pack", str(slice_pack_path)]
    if deep:
        cmd.append("--deep")
    if read_only:
        cmd.append("--read-only")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
    return result.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate all slice packs in a world pack.")
    ap.add_argument("--pack", required=True, help="Path to world pack YAML")
    ap.add_argument("--deep", action="store_true", help="Enable deep per-slice validation")
    ap.add_argument("--read-only", action="store_true", help="Only read existing reports, skip UE runs")
    args = ap.parse_args(argv)

    pack_path = Path(args.pack)
    if not pack_path.is_absolute():
        pack_path = REPO_ROOT / pack_path
    if not pack_path.is_file():
        sys.stderr.write("ERROR: world pack not found: {}\n".format(pack_path))
        sys.exit(1)

    with pack_path.open("r", encoding="utf-8") as fh:
        world_pack = yaml.safe_load(fh)

    world_pack_id = world_pack.get("world_pack_id", pack_path.stem)
    packs = world_pack.get("packs", [])

    print("=== Validate World Pack: {} ({} slice packs) ===".format(world_pack_id, len(packs)))

    pack_results = []
    total_slices = 0
    total_pass = 0
    any_fail = False

    for pack_entry in packs:
        pack_id = pack_entry.get("pack_id", "<unknown>")
        pack_rel = pack_entry.get("pack_path", "")
        slice_pack_path = REPO_ROOT / pack_rel if pack_rel else None

        if not slice_pack_path or not slice_pack_path.is_file():
            print("[{}] ERROR: pack file not found: {}".format(pack_id, pack_rel))
            pack_results.append({"pack_id": pack_id, "status": "error", "pass": 0, "total": 0})
            any_fail = True
            continue

        # Count slices.
        try:
            with slice_pack_path.open("r", encoding="utf-8") as fh:
                sp = yaml.safe_load(fh)
            slice_count = len(sp.get("slices", []))
        except Exception:
            slice_count = 0

        print("\n--- Validating pack: {} ({} slices) ---".format(pack_id, slice_count))
        rc = _run_validate_pack(slice_pack_path, deep=args.deep, read_only=args.read_only)
        passed = rc == 0

        # Read pack validate report if it exists.
        rpt_path = REPO_ROOT / "procedural" / "reports" / "packs" / pack_id / "validate_pack_report.json"
        n_pass = 0
        n_total = slice_count
        if rpt_path.is_file():
            try:
                rpt = json.loads(rpt_path.read_text(encoding="utf-8"))
                n_pass = rpt.get("pass", 0)
                n_total = rpt.get("total", slice_count)
            except Exception:
                pass

        status = "pass" if passed else "fail"
        if not passed:
            any_fail = True
        total_slices += n_total
        total_pass += n_pass
        pack_results.append({"pack_id": pack_id, "status": status, "pass": n_pass, "total": n_total})
        print("[{}] {} ({}/{})".format(pack_id, status.upper(), n_pass, n_total))

    # Summary.
    print("\n=== World Pack '{}': {}/{} total slices PASS ===".format(
        world_pack_id, total_pass, total_slices))

    report_dir = REPO_ROOT / "procedural" / "reports" / "world_packs" / world_pack_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "world_pack_id": world_pack_id,
        "packs": pack_results,
        "total_slices": total_slices,
        "total_pass": total_pass,
        "passed": not any_fail,
        "deep": args.deep,
    }
    out_path = report_dir / "validate_world_pack_report.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print("Report: procedural/reports/world_packs/{}/validate_world_pack_report.json".format(world_pack_id))

    sys.exit(0 if not any_fail else 1)


if __name__ == "__main__":
    main()
