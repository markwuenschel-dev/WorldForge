#!/usr/bin/env python3
r"""
batch_biome_materialize.py (UE5 Python) -- v1.1 BiomeForge single-session driver.

Reads procedural/reports/slices/_biome_batch.json (written by
prepare_biome_materialization.py) and, in ONE headless editor session:

  1. Creates/updates each biome placement DataAsset (create_placement_data_asset).
  2. For every biome slice: build_map_for_spec (create_slice_map) then
     validate_spec (validate_slice, deep) — writing the per-slice
     create_map_report.json + validate_slice_report.json each downstream gate reads.

Booting the editor once for all 60 slices instead of 120 times is the whole point.
Writes a roll-up to procedural/reports/slices/_biome_batch_result.json.

Run headless:
    UnrealEditor-Cmd <uproject> -ExecutePythonScript=<this> -unattended -nopause -stdout
"""

import json
import os
import sys
import traceback

import unreal

ROOT = os.path.normpath(unreal.Paths.project_dir())
_UE_DIR = os.path.join(ROOT, "tools", "unreal")
if _UE_DIR not in sys.path:
    sys.path.insert(0, _UE_DIR)

import create_slice_map          # noqa: E402
import validate_slice            # noqa: E402
import create_placement_data_asset as cpda  # noqa: E402

BATCH_REL = "procedural/reports/slices/_biome_batch.json"
RESULT_REL = "procedural/reports/slices/_biome_batch_result.json"


def log(m):
    unreal.log("[batch-biome] {}".format(m))


def _load(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    batch = _load(BATCH_REL)
    result = {"placement_das": [], "slices": [], "errors": []}

    # 1) placement DataAssets
    for mrel in batch.get("placement_manifests", []):
        try:
            manifest = _load(mrel)
            res = cpda.create_or_update(manifest)
            result["placement_das"].append({"manifest": mrel, "result": res})
            log("placement DA: {} -> {}".format(manifest["ue"]["data_asset_path"], res.get("status")))
        except Exception as exc:  # noqa: BLE001
            result["errors"].append("placement DA {}: {}".format(mrel, exc))
            log("ERROR placement DA {}: {}".format(mrel, exc))

    # 2) slices — materialize + validate
    specs = batch.get("specs", [])
    n_created = n_valid = 0
    for i, srel in enumerate(specs, 1):
        row = {"spec": srel, "created": None, "validated": None}
        try:
            spec = _load(srel)
            crep = create_slice_map.build_map_for_spec(spec, ROOT)
            row["created"] = crep.get("status")
            if crep.get("status") == "ok":
                n_created += 1
            vrep = validate_slice.validate_spec(spec, ROOT, deep=True)
            row["validated"] = "PASS" if vrep.passed else "FAIL"
            if vrep.passed:
                n_valid += 1
            else:
                row["failures"] = [str(f) for f in vrep.failures]
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)
            row["traceback"] = traceback.format_exc()
            result["errors"].append("slice {}: {}".format(srel, exc))
            log("ERROR slice {}: {}".format(srel, exc))
        result["slices"].append(row)
        log("[{}/{}] {} created={} validated={}".format(
            i, len(specs), srel.rsplit("/", 1)[-1], row["created"], row["validated"]))

    result["summary"] = {
        "specs": len(specs), "created_ok": n_created, "validated_pass": n_valid,
        "placement_das": len(result["placement_das"]),
    }
    with open(os.path.join(ROOT, RESULT_REL), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log("BATCH DONE: {}/{} created, {}/{} validated PASS; DAs={}".format(
        n_created, len(specs), n_valid, len(specs), len(result["placement_das"])))


if __name__ == "__main__":
    main()
