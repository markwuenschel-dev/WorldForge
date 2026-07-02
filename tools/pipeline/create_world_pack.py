#!/usr/bin/env python3
"""create_world_pack.py — WorldForge v0.5 world pack builder.

Reads a world pack YAML and runs create_slice_pack.py for each referenced
slice pack in sequence.

Usage:
    python tools/pipeline/create_world_pack.py \
        --pack procedural/world_packs/desert_production_seed.yaml \
        [--jobs N] [--force]

Exit 0 if all packs succeeded, 1 if any failed.
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
CREATE_PACK_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "create_slice_pack.py"


def _run(argv, label):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    print("[{}] $ {}".format(label, " ".join(str(a) for a in argv)))
    sys.stdout.flush()
    result = subprocess.run([str(a) for a in argv], cwd=str(REPO_ROOT), env=env)
    return result.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create all slice packs in a world pack spec.")
    ap.add_argument("--pack", required=True, help="Path to world pack YAML")
    ap.add_argument("--jobs", type=int, default=1, help="Parallel jobs for non-UE prep (default: 1)")
    ap.add_argument("--force", action="store_true", help="Force rebuild of all slices")
    ap.add_argument(
        "--specs-only", action="store_true",
        help="Headless: generate slice spec JSONs only, skipping all UE .umap creation "
             "(threads --specs-only through to create_slice_pack.py). Missing sibling "
             "slice packs are reported but do not abort generation of the packs present.")
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

    print("=== World Pack: {} ({} slice packs) ===".format(world_pack_id, len(packs)))

    # Collect all slice names across packs to detect duplicates.
    all_slice_names = []
    pack_slice_names = {}

    results = {}
    for pack_entry in packs:
        pack_id = pack_entry.get("pack_id", "<unknown>")
        pack_rel = pack_entry.get("pack_path", "")
        slice_pack_path = REPO_ROOT / pack_rel if pack_rel else None

        if not slice_pack_path or not slice_pack_path.is_file():
            print("[{}] ERROR: pack file not found: {}".format(pack_id, pack_rel))
            results[pack_id] = "fail"
            continue

        # Collect slice names for duplicate check.
        try:
            with slice_pack_path.open("r", encoding="utf-8") as fh:
                sp = yaml.safe_load(fh)
            names = [s.get("name", "") for s in sp.get("slices", [])]
            pack_slice_names[pack_id] = names
            all_slice_names.extend(names)
        except Exception as exc:
            print("[{}] WARNING: could not read pack for duplicate check: {}".format(pack_id, exc))

        argv_inner = [sys.executable, CREATE_PACK_SCRIPT, "--pack", str(slice_pack_path),
                      "--jobs", str(args.jobs)]
        if args.force:
            argv_inner.append("--force")
        if args.specs_only:
            argv_inner.append("--specs-only")

        print("\n--- Pack: {} ---".format(pack_id))
        rc = _run(argv_inner, pack_id)
        results[pack_id] = "ok" if rc == 0 else "fail"
        print("[{}] {}".format(pack_id, results[pack_id].upper()))

    # Duplicate name check.
    seen = set()
    duplicates = []
    for name in all_slice_names:
        if name in seen:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        print("\nWARNING: duplicate slice names across packs: {}".format(duplicates))

    # Summary.
    n_ok = sum(1 for v in results.values() if v == "ok")
    n_fail = sum(1 for v in results.values() if v == "fail")
    print("\n=== World Pack '{}' done: {}/{} packs OK, {} failed ===".format(
        world_pack_id, n_ok, len(packs), n_fail))

    # Write report.
    report_dir = REPO_ROOT / "procedural" / "reports" / "world_packs" / world_pack_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "world_pack_id": world_pack_id,
        "total_packs": len(packs),
        "packs_ok": n_ok,
        "packs_failed": n_fail,
        "results": results,
        "duplicate_slice_names": duplicates,
        "passed": n_fail == 0,
    }
    with (report_dir / "create_world_pack_report.json").open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print("Report: procedural/reports/world_packs/{}/create_world_pack_report.json".format(world_pack_id))

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
