#!/usr/bin/env python3
"""create_terrain.py — WorldForge v0.6 TerrainForge Lite artifact generator.

Reads a terrain recipe YAML and generates:
  - heightmap.png       (16-bit grayscale, values in [0, 65535])
  - slope_mask.png      (8-bit grayscale; 255=steep, 0=flat)
  - placement_mask.png  (8-bit grayscale; 255=placeable, 0=not)
  - nav_safe_mask.png   (8-bit grayscale; 255=nav-safe, 0=not)
  - descriptor.json     (terrain descriptor + provenance + registry ownership)

Updates procedural/generated/worldforge_terrain_registry.json.

All outputs are deterministic: same recipe + seed always produces identical files.
Rerunning is idempotent (overwrites with the same content, same hashes).

Usage:
    python tools/pipeline/create_terrain.py --recipe ash_flats --name Terrain_AshFlats_01
    python tools/pipeline/create_terrain.py --recipe ash_flats --name Terrain_AshFlats_01 --force

Requires: numpy (pip install numpy)
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import struct
import sys
import zlib
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

try:
    import numpy as np
except ImportError:
    sys.stderr.write("ERROR: numpy required (pip install numpy).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_NAME = "create_terrain"
GENERATOR_VERSION = "0.6.0"

sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from terrain_registry import (
    compute_terrain_input_hash,
    load_terrain_registry,
    save_terrain_registry,
    upsert_terrain_entry,
)
from provenance import build_provenance


# ---------------------------------------------------------------------------
# Noise generation
# ---------------------------------------------------------------------------

def _value_noise_2d(rng: "np.random.RandomState", h: int, w: int, scale: float) -> "np.ndarray":
    """Bilinearly-interpolated value noise at the given pixel scale, shape (h, w) in [0,1]."""
    gh = max(2, math.ceil(h / scale) + 2)
    gw = max(2, math.ceil(w / scale) + 2)
    grid = rng.uniform(0.0, 1.0, (gh, gw)).astype(np.float64)

    # Sample positions in grid space, clamped so xi+1 and yi+1 stay in bounds.
    ys = np.linspace(0.0, float(gh - 2), h)
    xs = np.linspace(0.0, float(gw - 2), w)

    yi = np.floor(ys).astype(np.int32)
    xi = np.floor(xs).astype(np.int32)
    yi = np.clip(yi, 0, gh - 2)
    xi = np.clip(xi, 0, gw - 2)

    fy = (ys - yi.astype(np.float64))[:, None]   # (h, 1)
    fx = (xs - xi.astype(np.float64))[None, :]   # (1, w)

    c00 = grid[yi[:, None], xi[None, :]]
    c01 = grid[yi[:, None], (xi + 1)[None, :]]
    c10 = grid[(yi + 1)[:, None], xi[None, :]]
    c11 = grid[(yi + 1)[:, None], (xi + 1)[None, :]]

    return (c00 * (1.0 - fy) * (1.0 - fx) +
            c01 * (1.0 - fy) * fx +
            c10 * fy * (1.0 - fx) +
            c11 * fy * fx)


def generate_fbm_heightmap(
    seed: int,
    width: int,
    height: int,
    octaves: int,
    base_scale_px: float,
    persistence: float,
    lacunarity: float,
    height_min_cm: float,
    height_max_cm: float,
) -> "np.ndarray":
    """
    fBm value-noise heightmap.  Returns float64 (height, width) in [height_min_cm, height_max_cm].
    Fully deterministic for a given set of parameters.
    """
    rng = np.random.RandomState(seed)
    total = np.zeros((height, width), dtype=np.float64)
    amplitude = 1.0
    scale = float(base_scale_px)
    max_value = 0.0

    for _ in range(octaves):
        total += amplitude * _value_noise_2d(rng, height, width, scale)
        max_value += amplitude
        amplitude *= persistence
        scale /= lacunarity

    normalized = total / max_value  # [0, 1]
    return normalized * (height_max_cm - height_min_cm) + height_min_cm


# ---------------------------------------------------------------------------
# Slope / mask computation
# ---------------------------------------------------------------------------

def compute_slope_degrees(heightmap_cm: "np.ndarray", cell_size_cm: float = 100.0) -> "np.ndarray":
    """Slope in degrees at each pixel.  Central differences via np.gradient."""
    dzdx = np.gradient(heightmap_cm, axis=1) / cell_size_cm
    dzdy = np.gradient(heightmap_cm, axis=0) / cell_size_cm
    return np.degrees(np.arctan(np.sqrt(dzdx ** 2 + dzdy ** 2)))


def slope_to_uint8_mask(
    slope_deg: "np.ndarray",
    threshold: float,
    invert: bool = False,
) -> "np.ndarray":
    """
    Binary mask from slope array, returned as uint8 [0, 255].
    invert=False: steep (>= threshold) → 255, flat → 0  (slope_mask)
    invert=True:  flat (<  threshold) → 255, steep → 0  (placement / nav masks)
    """
    steep = slope_deg >= threshold
    if invert:
        steep = ~steep
    return (steep.astype(np.float64) * 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# PNG writers (stdlib-only, no Pillow required)
# ---------------------------------------------------------------------------

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    body = tag + data
    crc = struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return length + body + crc


def save_png_8bit(path: Path, arr: "np.ndarray") -> None:
    """Write a 2D uint8 array as an 8-bit grayscale PNG."""
    assert arr.dtype == np.uint8, "expected uint8 array"
    h, w = arr.shape
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(arr[y]) for y in range(h))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_png_chunk(b"IHDR", ihdr))
        f.write(_png_chunk(b"IDAT", zlib.compress(raw, level=6)))
        f.write(_png_chunk(b"IEND", b""))


def save_png_16bit(path: Path, arr: "np.ndarray") -> None:
    """
    Write a 2D float64 array (any range) as a 16-bit grayscale PNG.
    Normalizes the array to [0, 65535] before writing.
    """
    mn, mx = float(arr.min()), float(arr.max())
    if mx > mn:
        norm = (arr - mn) / (mx - mn)
    else:
        norm = np.zeros_like(arr)
    u16 = (norm * 65535.0).round().astype(np.uint16)
    # PNG is big-endian
    if sys.byteorder == "little":
        u16 = u16.byteswap()
    h, w = u16.shape
    ihdr = struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + u16[y].tobytes() for y in range(h))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_png_chunk(b"IHDR", ihdr))
        f.write(_png_chunk(b"IDAT", zlib.compress(raw, level=6)))
        f.write(_png_chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate TerrainForge Lite artifacts (heightmap + masks) from a terrain recipe."
    )
    ap.add_argument("--recipe", required=True, help="Terrain recipe ID, e.g. ash_flats")
    ap.add_argument("--name", required=True, help="Output terrain name, e.g. Terrain_AshFlats_01")
    ap.add_argument("--force", action="store_true", help="Regenerate even if descriptor already exists")
    args = ap.parse_args(argv)

    recipe_path = REPO_ROOT / "procedural" / "definitions" / "terrain" / (args.recipe + ".yaml")
    if not recipe_path.is_file():
        sys.stderr.write("ERROR: terrain recipe not found: {}\n".format(recipe_path))
        sys.exit(1)

    out_dir = REPO_ROOT / "procedural" / "generated" / "terrain" / args.name
    desc_path = out_dir / "descriptor.json"

    # Skip if already built and not forcing.
    if desc_path.is_file() and not args.force:
        print("[create-terrain] up-to-date (descriptor exists; use --force to rebuild): {}".format(
            desc_path.relative_to(REPO_ROOT)))
        return 0

    with recipe_path.open("r", encoding="utf-8") as fh:
        recipe = yaml.safe_load(fh)

    out_dir.mkdir(parents=True, exist_ok=True)

    gen = recipe.get("generation", {})
    seed = int(gen.get("seed", 12345))
    width = int(gen.get("width", 513))
    height = int(gen.get("height", 513))

    hm_cfg = gen.get("heightmap", {})
    slope_cfg = gen.get("slope_mask", {})
    placement_cfg = gen.get("placement_mask", {})
    nav_cfg = gen.get("nav_safe_mask", {})

    height_min_cm = float(hm_cfg.get("height_min_cm", 0.0))
    height_max_cm = float(hm_cfg.get("height_max_cm", 2000.0))

    print("[create-terrain] {} recipe={} seed={} {}x{}".format(
        args.name, args.recipe, seed, width, height))

    # --- Heightmap ---
    print("[create-terrain] generating heightmap...")
    heightmap_cm = generate_fbm_heightmap(
        seed=seed,
        width=width,
        height=height,
        octaves=int(hm_cfg.get("octaves", 6)),
        base_scale_px=float(hm_cfg.get("base_scale_px", 64)),
        persistence=float(hm_cfg.get("persistence", 0.5)),
        lacunarity=float(hm_cfg.get("lacunarity", 2.0)),
        height_min_cm=height_min_cm,
        height_max_cm=height_max_cm,
    )
    hm_path = out_dir / "heightmap.png"
    save_png_16bit(hm_path, heightmap_cm)
    print("[create-terrain] heightmap → {}".format(hm_path.relative_to(REPO_ROOT)))

    # --- Slope ---
    print("[create-terrain] computing slope...")
    slope_deg = compute_slope_degrees(heightmap_cm, cell_size_cm=100.0)

    steep_thresh = float(slope_cfg.get("steep_threshold_degrees", 12.0))
    slope_arr = slope_to_uint8_mask(slope_deg, threshold=steep_thresh, invert=False)
    slope_path = out_dir / "slope_mask.png"
    save_png_8bit(slope_path, slope_arr)
    print("[create-terrain] slope_mask → {}".format(slope_path.relative_to(REPO_ROOT)))

    # --- Placement mask ---
    print("[create-terrain] computing placement mask...")
    placement_thresh = float(placement_cfg.get("slope_max_degrees", 10.0))
    placement_arr = slope_to_uint8_mask(slope_deg, threshold=placement_thresh, invert=True)
    placement_path = out_dir / "placement_mask.png"
    save_png_8bit(placement_path, placement_arr)
    print("[create-terrain] placement_mask → {}".format(placement_path.relative_to(REPO_ROOT)))

    # --- Nav-safe mask ---
    print("[create-terrain] computing nav-safe mask...")
    nav_thresh = float(nav_cfg.get("slope_max_degrees", 8.0))
    nav_arr = slope_to_uint8_mask(slope_deg, threshold=nav_thresh, invert=True)
    nav_path = out_dir / "nav_safe_mask.png"
    save_png_8bit(nav_path, nav_arr)
    print("[create-terrain] nav_safe_mask → {}".format(nav_path.relative_to(REPO_ROOT)))

    # --- Hashes ---
    hashes = {
        "heightmap": sha256_file(hm_path),
        "slope_mask": sha256_file(slope_path),
        "placement_mask": sha256_file(placement_path),
        "nav_safe_mask": sha256_file(nav_path),
    }

    # --- Provenance ---
    prov = build_provenance(REPO_ROOT, [recipe_path], GENERATOR_NAME, GENERATOR_VERSION)

    # --- Descriptor ---
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    descriptor = {
        "terrain_name": args.name,
        "recipe_id": args.recipe,
        "recipe_path": recipe_path.relative_to(REPO_ROOT).as_posix(),
        "seed": seed,
        "dimensions": [width, height],
        "height_range_cm": [height_min_cm, height_max_cm],
        "outputs": {
            "heightmap": (out_dir / "heightmap.png").relative_to(REPO_ROOT).as_posix(),
            "slope_mask": (out_dir / "slope_mask.png").relative_to(REPO_ROOT).as_posix(),
            "placement_mask": (out_dir / "placement_mask.png").relative_to(REPO_ROOT).as_posix(),
            "nav_safe_mask": (out_dir / "nav_safe_mask.png").relative_to(REPO_ROOT).as_posix(),
        },
        "hashes": hashes,
        "ue_terrain": recipe.get("ue_terrain", {}),
        "generated_at_utc": now_iso,
        "provenance": prov,
        "registry_owner": "worldforge_terrain_registry",
    }

    with desc_path.open("w", encoding="utf-8") as fh:
        json.dump(descriptor, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[create-terrain] descriptor → {}".format(desc_path.relative_to(REPO_ROOT)))

    # --- Registry ---
    registry = load_terrain_registry(REPO_ROOT)
    entry = {
        "terrain_name": args.name,
        "recipe_id": args.recipe,
        "recipe_path": recipe_path.relative_to(REPO_ROOT).as_posix(),
        "descriptor_path": desc_path.relative_to(REPO_ROOT).as_posix(),
        "owned_outputs": list(descriptor["outputs"].values()),
        "input_hash": compute_terrain_input_hash({
            "recipe_id": args.recipe,
            "seed": seed,
            "width": width,
            "height": height,
        }),
    }
    registry = upsert_terrain_entry(registry, entry)
    save_terrain_registry(REPO_ROOT, registry)
    print("[create-terrain] registry updated")

    print("[create-terrain] DONE: {}".format(args.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
