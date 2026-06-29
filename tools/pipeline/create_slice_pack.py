#!/usr/bin/env python3
"""create_slice_pack.py — WorldForge v0.4 batch slice factory.

Reads a pack YAML spec and creates/updates all named slices in it.

Usage:
    python tools/pipeline/create_slice_pack.py \
        --pack procedural/slice_packs/desert_foundation.yaml \
        [--jobs N] [--force]

Algorithm:
  Phase 1 (parallelisable, up to --jobs workers):
    For each slice that needs building:
      - emit generated spec (create_slice_spec.py)
      - prepare assets    (prepare_slice.py)
  Phase 2 (serialised — one headless UE boot at a time):
      - create_slice_map.py (via run_slice_ue.py)
  After each successful map build: upsert registry entry.
  Write procedural/reports/packs/<pack_id>/create_pack_report.json.

Exit 0 if all slices succeeded, 1 if any failed.
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

from registry import (
    compute_input_hash,
    load_registry,
    remove_entry,
    save_registry,
    upsert_entry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CREATE_SPEC_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "create_slice_spec.py"
PREPARE_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "prepare_slice.py"
RUN_UE_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "run_slice_ue.py"
GEN_DA_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "generate_placement_da.py"


def _run(argv, label):
    """Run a subprocess, stream its output, return exit code."""
    print("[{}] $ {}".format(label, " ".join(str(a) for a in argv)))
    sys.stdout.flush()
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    result = subprocess.run([str(a) for a in argv], cwd=str(REPO_ROOT), env=env)
    return result.returncode


def _spec_path(biome, name):
    return REPO_ROOT / "procedural" / "slices" / biome / "generated" / (name + ".json")


def _load_spec(path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _preview_hash(pack_biome, variant, name, seed, defaults, placement=None, state_preset=None,
                  terrain=None, poi=None):
    """Compute expected hash without actually running create_slice_spec.
    We do this by loading the variant template and building a minimal
    representative dict that matches the stable spec fields."""
    template_path = REPO_ROOT / "procedural" / "slices" / "{}_{}".format(pack_biome, variant) + ".yaml"
    if not template_path.is_file():
        return None
    try:
        with template_path.open("r", encoding="utf-8") as fh:
            tmpl = yaml.safe_load(fh)
        proxy = {
            "slice_id": name,
            "biome": pack_biome,
            "variant": variant,
            "region_id": name,
            "seed": seed,
            "map": "/Game/WorldForge/Maps/{}".format(name),
            "placement_preset_id": placement or "",
            "state_preset_id": state_preset or "",
            "terrain_recipe_id": terrain or "",
            "poi_type": poi or "",
        }
        return compute_input_hash(proxy)
    except Exception:
        return None


def _phase1_slice(biome, name, variant, seed, placement=None, state_preset=None,
                  terrain=None, poi=None):
    """Emit spec + prepare. Returns (name, ok, spec_path_or_None)."""
    spec_out = _spec_path(biome, name)
    cmd = [sys.executable, CREATE_SPEC_SCRIPT,
           "--biome", biome, "--variant", variant, "--name", name, "--seed", str(seed)]
    if placement:
        cmd += ["--placement", placement]
    if state_preset:
        cmd += ["--state-preset", state_preset]
    if terrain:
        cmd += ["--terrain", terrain]
    if poi:
        cmd += ["--poi", poi]
    rc_spec = _run(cmd, name)
    if rc_spec != 0:
        print("[{}] FAIL: create_slice_spec exited {}".format(name, rc_spec))
        return name, False, None
    rc_prep = _run(
        [sys.executable, PREPARE_SCRIPT, "--spec", str(spec_out)],
        name,
    )
    if rc_prep != 0:
        print("[{}] FAIL: prepare_slice exited {}".format(name, rc_prep))
        return name, False, spec_out
    return name, True, spec_out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Batch-create all slices in a pack spec.")
    ap.add_argument("--pack", required=True, help="Path to pack YAML (e.g. procedural/slice_packs/desert_foundation.yaml)")
    ap.add_argument("--jobs", type=int, default=1, help="Parallel workers for non-UE prep phase (default: 1)")
    ap.add_argument("--force", action="store_true", help="Rebuild even if slice is up-to-date")
    args = ap.parse_args(argv)

    pack_path = Path(args.pack)
    if not pack_path.is_absolute():
        pack_path = REPO_ROOT / pack_path
    if not pack_path.is_file():
        sys.stderr.write("ERROR: pack not found: {}\n".format(pack_path))
        sys.exit(1)

    with pack_path.open("r", encoding="utf-8") as fh:
        pack = yaml.safe_load(fh)

    pack_id = pack["pack_id"]
    biome = pack["biome"]
    defaults = pack.get("defaults", {})
    slices = pack.get("slices", [])

    if not slices:
        print("Pack '{}' has no slices defined.".format(pack_id))
        sys.exit(0)

    registry = load_registry(REPO_ROOT)

    # Determine which slices need building.
    to_build = []
    skipped = []
    for sl in slices:
        name = sl["name"]
        variant = sl["variant"]
        seed = sl.get("seed", 12345)
        placement = sl.get("placement")
        state_preset = sl.get("state_preset")
        terrain = sl.get("terrain")
        poi = sl.get("poi")
        if not args.force and name in registry:
            existing = registry[name]
            spec_p = _spec_path(biome, name)
            if spec_p.is_file():
                try:
                    spec = _load_spec(spec_p)
                    h = compute_input_hash(spec)
                    if h == existing.get("input_hash"):
                        print("[{}] up_to_date (hash match) — skipping".format(name))
                        skipped.append(name)
                        continue
                except Exception:
                    pass
        to_build.append((name, variant, seed, placement, state_preset, terrain, poi))

    print("\nPack: {} | biome: {} | {} slices ({} to build, {} skipped)".format(
        pack_id, biome, len(slices), len(to_build), len(skipped)))

    results = {}  # name -> "ok" | "fail" | "up_to_date"
    for name in skipped:
        results[name] = "up_to_date"

    if not to_build:
        print("All slices up-to-date.")
    else:
        # Phase 1: parallel spec + prepare.
        phase1_results = {}  # name -> (ok, spec_path)
        jobs = max(1, args.jobs)
        print("\n--- Phase 1: spec + prepare ({} workers) ---".format(jobs))
        if jobs == 1:
            for name, variant, seed, placement, state_preset, terrain, poi in to_build:
                _, ok, sp = _phase1_slice(biome, name, variant, seed, placement, state_preset,
                                          terrain=terrain, poi=poi)
                phase1_results[name] = (ok, sp)
        else:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = {
                    pool.submit(_phase1_slice, biome, name, variant, seed, placement, state_preset,
                                terrain, poi): name
                    for name, variant, seed, placement, state_preset, terrain, poi in to_build
                }
                for fut in as_completed(futures):
                    nm, ok, sp = fut.result()
                    phase1_results[nm] = (ok, sp)

        # Phase 2: serialised UE map creation.
        print("\n--- Phase 2: UE map creation (serialised) ---")
        for name, variant, seed, placement, state_preset, terrain, poi in to_build:
            ok, spec_p = phase1_results.get(name, (False, None))
            if not ok or spec_p is None:
                results[name] = "fail"
                continue
            rc_ue = _run(
                [sys.executable, RUN_UE_SCRIPT,
                 "--script", "create_slice_map.py", "--spec", str(spec_p)],
                name,
            )
            if rc_ue != 0:
                print("[{}] FAIL: create_slice_map exited {}".format(name, rc_ue))
                results[name] = "fail"
                continue
            # Upsert registry.
            try:
                spec = _load_spec(spec_p)
                placement = spec.get("placement", {})
                ref_assets = [
                    x for x in [
                        spec.get("terrain", {}).get("material_mi"),
                        placement.get("data_asset"),
                        placement.get("pcg_graph"),
                    ] if x
                ]
                entry = {
                    "slice_id": name,
                    "pack_id": pack_id,
                    "biome": biome,
                    "variant": variant,
                    "placement_preset_id": spec.get("placement_preset_id"),
                    "state_preset_id": spec.get("state_preset_id"),
                    "terrain_recipe_id": spec.get("terrain_forge", {}).get("recipe_id"),
                    "poi_type": spec.get("poi_forge", {}).get("poi_type"),
                    "map_path": spec["map"],
                    "spec_path": spec_p.relative_to(REPO_ROOT).as_posix(),
                    "owned_assets": ["Content/WorldForge/Maps/{}.umap".format(name)],
                    "referenced_assets": ref_assets,
                    "input_hash": compute_input_hash(spec),
                }
                registry = upsert_entry(registry, entry)
                save_registry(REPO_ROOT, registry)
            except Exception as exc:
                print("[{}] WARNING: registry update failed: {}".format(name, exc))
            # Generate placement DA descriptor (pure Python, no UE).
            rc_da = _run([sys.executable, GEN_DA_SCRIPT, "--spec", str(spec_p)], name)
            if rc_da != 0:
                print("[{}] WARNING: generate_placement_da failed (non-fatal)".format(name))

            results[name] = "ok"
            print("[{}] OK".format(name))

    # Summary.
    n_ok = sum(1 for v in results.values() if v == "ok")
    n_skip = sum(1 for v in results.values() if v == "up_to_date")
    n_fail = sum(1 for v in results.values() if v == "fail")
    print("\n=== Pack '{}' done: {}/{} built, {} up-to-date, {} failed ===".format(
        pack_id, n_ok, len(slices), n_skip, n_fail))

    # Write pack report.
    report_dir = REPO_ROOT / "procedural" / "reports" / "packs" / pack_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "pack_id": pack_id,
        "biome": biome,
        "total": len(slices),
        "built": n_ok,
        "up_to_date": n_skip,
        "failed": n_fail,
        "results": results,
        "passed": n_fail == 0,
    }
    with (report_dir / "create_pack_report.json").open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print("Report: procedural/reports/packs/{}/create_pack_report.json".format(pack_id))

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
