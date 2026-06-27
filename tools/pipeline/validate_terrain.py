#!/usr/bin/env python3
"""validate_terrain.py — WorldForge v0.6 TerrainForge Lite artifact validator.

Validates all generated terrain artifacts for a given terrain name against
the terrain recipe and descriptor.  Pure Python — no UE imports.

UE-side checks (import_terrain_heightmap.py report) are loaded when present
and treated as warn_only when absent.

Usage:
    python tools/pipeline/validate_terrain.py --name Terrain_AshFlats_01

Writes:
    procedural/reports/terrain/<NAME>/validate_terrain_report.json

Exit 0 = PASS, 1 = FAIL.

Requires: numpy (pip install numpy)
"""

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

try:
    import numpy as np
except ImportError:
    sys.stderr.write("ERROR: numpy required (pip install numpy).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from terrain_registry import load_terrain_registry


# ---------------------------------------------------------------------------
# Minimal PNG readers (stdlib-only fallback; prefers Pillow when available)
# ---------------------------------------------------------------------------

def _read_png_8bit_arr(path: Path) -> "np.ndarray":
    """Return float64 array in [0, 1] from an 8-bit grayscale PNG."""
    try:
        from PIL import Image
        img = Image.open(str(path)).convert("L")
        return np.array(img, dtype=np.float64) / 255.0
    except ImportError:
        pass
    # stdlib fallback
    data = path.read_bytes()
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", chunk[:8])
        elif tag == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = w + 1
    rows = [np.frombuffer(raw[y * stride + 1: y * stride + 1 + w], dtype=np.uint8).astype(np.float64) / 255.0
            for y in range(h)]
    return np.array(rows)


def _read_png_16bit_arr(path: Path) -> "np.ndarray":
    """Return float64 array in [0, 1] from a 16-bit grayscale PNG."""
    try:
        from PIL import Image
        img = Image.open(str(path))
        arr = np.array(img, dtype=np.float64)
        peak = arr.max()
        return arr / peak if peak > 0 else arr
    except ImportError:
        pass
    # stdlib fallback
    data = path.read_bytes()
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", chunk[:8])
        elif tag == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = w * 2 + 1
    rows = [np.frombuffer(raw[y * stride + 1: y * stride + 1 + w * 2], dtype=">u2").astype(np.float64)
            for y in range(h)]
    arr = np.array(rows)
    peak = arr.max()
    return arr / peak if peak > 0 else arr


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate TerrainForge Lite artifacts.")
    ap.add_argument("--name", required=True, help="Terrain name, e.g. Terrain_AshFlats_01")
    args = ap.parse_args(argv)

    terrain_name = args.name
    artifact_dir = REPO_ROOT / "procedural" / "generated" / "terrain" / terrain_name
    report_dir = REPO_ROOT / "procedural" / "reports" / "terrain" / terrain_name
    report_dir.mkdir(parents=True, exist_ok=True)

    result = {"terrain_name": terrain_name, "checks": {}, "failures": []}

    def check(name, ok, detail="", warn_only=False):
        result["checks"][name] = {"ok": bool(ok), "detail": str(detail), "warn_only": warn_only}
        if not ok:
            if warn_only:
                result.setdefault("warnings", []).append("{}: {}".format(name, detail or "warn"))
            else:
                result["failures"].append("{}: {}".format(name, detail or "failed"))
        return bool(ok)

    # -- Descriptor ---------------------------------------------------------
    desc_path = artifact_dir / "descriptor.json"
    descriptor = None
    if check("terrain_descriptor_exists", desc_path.is_file(), str(desc_path.relative_to(REPO_ROOT))):
        try:
            with desc_path.open("r", encoding="utf-8") as fh:
                descriptor = json.load(fh)
            check("terrain_descriptor_parses", True)
        except Exception as exc:
            check("terrain_descriptor_parses", False, str(exc))

    if descriptor is None:
        result["passed"] = False
        result["status"] = "error"
        _write_report(report_dir, result)
        print("[validate-terrain] FAIL — descriptor missing or unparseable")
        sys.exit(1)

    # -- Recipe -------------------------------------------------------------
    recipe_id = descriptor.get("recipe_id", "")
    recipe_path = REPO_ROOT / "procedural" / "definitions" / "terrain" / (recipe_id + ".yaml")
    check("recipe_parses", recipe_path.is_file(),
          "recipe file missing: {}".format(recipe_path.relative_to(REPO_ROOT)))

    # -- Registry -----------------------------------------------------------
    registry = load_terrain_registry(REPO_ROOT)
    check("registry_owns_terrain", terrain_name in registry,
          "not found in worldforge_terrain_registry.json")

    # -- Provenance ---------------------------------------------------------
    prov = descriptor.get("provenance", {})
    check("provenance_exists", bool(prov), "provenance block absent from descriptor")
    prov_complete = bool(
        descriptor.get("recipe_id") and
        descriptor.get("seed") is not None and
        descriptor.get("dimensions") and
        descriptor.get("height_range_cm") and
        descriptor.get("outputs") and
        descriptor.get("hashes") and
        prov.get("generator_name") and
        prov.get("generated_at_utc")
    )
    check("provenance_fields_complete", prov_complete,
          "descriptor must contain recipe_id, seed, dimensions, height_range_cm, "
          "outputs, hashes, provenance.generator_name, provenance.generated_at_utc")

    # -- Output files -------------------------------------------------------
    outputs = descriptor.get("outputs", {})
    hm_path = REPO_ROOT / outputs.get("heightmap", "")
    slope_path = REPO_ROOT / outputs.get("slope_mask", "")
    placement_path = REPO_ROOT / outputs.get("placement_mask", "")
    nav_path = REPO_ROOT / outputs.get("nav_safe_mask", "")

    check("heightmap_exists", hm_path.is_file(), str(outputs.get("heightmap", "")))
    check("slope_mask_exists", slope_path.is_file(), str(outputs.get("slope_mask", "")))
    check("placement_mask_exists", placement_path.is_file(), str(outputs.get("placement_mask", "")))
    check("nav_safe_mask_exists", nav_path.is_file(), str(outputs.get("nav_safe_mask", "")))

    # -- Heightmap content --------------------------------------------------
    dims = descriptor.get("dimensions", [])
    expected_w, expected_h = (int(dims[0]), int(dims[1])) if len(dims) == 2 else (0, 0)

    if hm_path.is_file() and expected_w > 0:
        try:
            hm_arr = _read_png_16bit_arr(hm_path)
            ah, aw = hm_arr.shape
            check("heightmap_dimensions_valid",
                  ah == expected_h and aw == expected_w,
                  "got {}x{} expected {}x{}".format(aw, ah, expected_w, expected_h))

            hrange = descriptor.get("height_range_cm", [0.0, 65535.0])
            check("height_range_within_budget",
                  float(hrange[1]) <= 65535.0 and float(hrange[0]) >= 0.0,
                  "range={}..{}cm; budget=0..65535cm".format(hrange[0], hrange[1]))

            var = float(np.var(hm_arr))
            check("heightmap_variance_nonzero", var > 1e-6,
                  "variance={:.8f} — terrain is completely flat".format(var))
            check("heightmap_variance_bounded", var < 0.25,
                  "variance={:.4f} — terrain is unrealistically spiky".format(var))
        except Exception as exc:
            check("heightmap_dimensions_valid", False, "read error: {}".format(exc))
            check("heightmap_variance_nonzero", False, "skipped (read error)")
            check("heightmap_variance_bounded", False, "skipped (read error)")

    # -- Mask content -------------------------------------------------------
    def _check_mask_nondegenerate(path: Path, label: str):
        if not path.is_file():
            return
        try:
            arr = _read_png_8bit_arr(path)
            mean_val = float(np.mean(arr))
            check("{}_not_degenerate".format(label),
                  0.01 < mean_val < 0.99,
                  "mean={:.4f} — mask is all-black or all-white".format(mean_val))
        except Exception as exc:
            check("{}_not_degenerate".format(label), False, "read error: {}".format(exc))

    _check_mask_nondegenerate(slope_path, "slope_mask")
    _check_mask_nondegenerate(placement_path, "placement_mask")
    _check_mask_nondegenerate(nav_path, "nav_safe_mask")

    # -- UE-side check ------------------------------------------------------
    # Passes if import_terrain_heightmap.py has already been run for this terrain.
    # warn_only=True until Stage C UE bridge is executed.
    ue_report_path = report_dir / "ue_terrain_report.json"
    ue_imported = False
    if ue_report_path.is_file():
        try:
            ue_rpt = json.loads(ue_report_path.read_text(encoding="utf-8"))
            ue_imported = bool(ue_rpt.get("passed"))
        except Exception:
            ue_imported = False
    check("terrain_imported_in_ue", ue_imported,
          "run 'make import-terrain NAME={}' to run UE import".format(terrain_name),
          warn_only=True)

    # -- ue_terrain config present ------------------------------------------
    check("ue_terrain_config_present",
          bool(descriptor.get("ue_terrain")),
          "ue_terrain block missing from descriptor",
          warn_only=True)

    # -- Result -------------------------------------------------------------
    result["passed"] = len(result["failures"]) == 0
    result["status"] = "ok" if result["passed"] else "fail"
    _write_report(report_dir, result)

    verdict = "PASS" if result["passed"] else "FAIL"
    n_warn = len(result.get("warnings", []))
    print("[validate-terrain] {} — {} failure(s), {} warning(s)".format(
        verdict, len(result["failures"]), n_warn))
    for f in result["failures"]:
        print("[validate-terrain]   FAIL: {}".format(f))
    for w in result.get("warnings", []):
        print("[validate-terrain]   WARN: {}".format(w))
    sys.exit(0 if result["passed"] else 1)


def _write_report(report_dir: Path, result: dict):
    rpt_path = report_dir / "validate_terrain_report.json"
    with rpt_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[validate-terrain] report → {}".format(rpt_path))


if __name__ == "__main__":
    main()
