#!/usr/bin/env python3
r"""
make_placeholder_exports.py
Generate stand-in PNGs for a manifest's texture exports so the UE import lane
(and a real in-engine slice) can be tested WITHOUT a Substance Designer render.

Two modes:
  * procedural (default) - derive five COHERENT maps from the recipe parameters,
    off a single shared procedural height base. A crack that appears in base_color
    also appears in height/normal/AO/roughness, and changing recipe params (or the
    recipe id) produces a visibly distinct, deterministic material. This is the
    "agent-cheap pre-Substance stopgap" from
    docs/substance/terrain_rock_strata_authoring_spec.md section 4.5.
  * solid (--solid) - the original flat-colour-per-channel placeholders, kept so
    the cheapest smoke test path still exists.

Pure stdlib for PNG encoding (zlib + struct); PyYAML is used only to read the
recipe parameters (already a project dependency, see validate_recipe.py).

The contract is unchanged: same five outputs, same export paths, same PNG format.
No recipe / manifest / validator changes are required.

Usage:
    python tools/substance/make_placeholder_exports.py --recipe terrain_rock_desert_01
    python tools/substance/make_placeholder_exports.py --recipe terrain_rock_desert_01 --solid
    python tools/substance/make_placeholder_exports.py --manifest <path> --project-root <root>
"""

import argparse
import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

import yaml

# --- solid-mode fallback (original behaviour) -------------------------------
PLACEHOLDER_COLORS = {
    "base_color": (150, 110, 75),          # neutral desert rock
    "normal": (128, 128, 255),             # flat tangent-space normal
    "roughness": (180, 180, 180),          # fairly rough
    "ambient_occlusion": (255, 255, 255),  # unoccluded
    "height": (128, 128, 128),             # mid height
}
DEFAULT_COLOR = (128, 128, 128)

# Parameter defaults for keys a recipe is allowed to omit (mirrors the allowed
# set in validate_recipe.py). Procedural generation must work for any valid recipe.
PARAM_DEFAULTS = {
    "base_hue": 0.08,
    "saturation": 0.42,
    "value": 0.58,
    "crack_density": 0.5,
    "crack_depth": 0.4,
    "strata_angle": 0.0,
    "erosion_strength": 0.5,
    "sand_overlay": 0.25,
    "normal_intensity": 1.0,
    "height_strength": 1.0,
}


# --- PNG encoding (pure stdlib) ---------------------------------------------
def _png_bytes(width: int, height: int, raw_rows: bytes, color_type: int) -> bytes:
    """raw_rows already includes the per-row filter byte (0). color_type 2 = RGB."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw_rows, 9))
            + chunk(b"IEND", b""))


def write_solid_png(path: Path, width: int, height: int, rgb) -> None:
    row = b"\x00" + bytes(rgb) * width
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes(width, height, row * height, color_type=2))


def write_rgb_png(path: Path, width: int, height: int, rows: list) -> None:
    """rows: list of `height` bytes objects, each width*3 RGB (no filter byte)."""
    raw = b"".join(b"\x00" + r for r in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes(width, height, raw, color_type=2))


# --- value noise / fbm ------------------------------------------------------
def _make_perm(seed: int):
    """Deterministic 256-entry permutation table from a seed."""
    table = list(range(256))
    state = seed & 0xFFFFFFFF
    for i in range(255, 0, -1):
        # xorshift32 for a stable, dependency-free shuffle
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= (state >> 17)
        state ^= (state << 5) & 0xFFFFFFFF
        j = state % (i + 1)
        table[i], table[j] = table[j], table[i]
    return table + table  # doubled to avoid index wrapping


def _smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _value_noise(x: float, y: float, perm) -> float:
    """2D value noise in [0,1] on an integer lattice."""
    xi = int(math.floor(x)) & 255
    yi = int(math.floor(y)) & 255
    xf = x - math.floor(x)
    yf = y - math.floor(y)
    u, v = _smooth(xf), _smooth(yf)

    def lat(a, b):
        return (perm[(perm[a & 255] + b) & 255]) / 255.0

    n00 = lat(xi, yi)
    n10 = lat(xi + 1, yi)
    n01 = lat(xi, yi + 1)
    n11 = lat(xi + 1, yi + 1)
    nx0 = n00 + u * (n10 - n00)
    nx1 = n01 + u * (n11 - n01)
    return nx0 + v * (nx1 - nx0)


def _fbm(x: float, y: float, perm, octaves: int = 4, lac: float = 2.0, gain: float = 0.5) -> float:
    total = 0.0
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for _ in range(octaves):
        total += amp * _value_noise(x * freq, y * freq, perm)
        norm += amp
        amp *= gain
        freq *= lac
    return total / norm


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _hsv_to_rgb(h: float, s: float, v: float):
    h = (h % 1.0) * 6.0
    i = int(h)
    f = h - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i %= 6
    r, g, b = ((v, t, p), (q, v, p), (p, v, t),
               (p, q, v), (t, p, v), (v, p, q))[i]
    return r, g, b


# --- procedural material model ----------------------------------------------
def _seed_for(recipe_id: str, params: dict) -> int:
    """Stable seed so a recipe always renders the same, but variants differ."""
    key = recipe_id + "|" + json.dumps(params, sort_keys=True)
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)


def generate_fields(params: dict, recipe_id: str, work: int):
    """Compute the five maps on a `work`x`work` grid as flat float arrays.

    Returns dict of channel -> list of (work*work) values:
      base_color stored as (r,g,b) tuples in [0,1]; the rest as scalars in [0,1].
    Built off one shared height base so all channels stay physically related.
    """
    p = dict(PARAM_DEFAULTS)
    p.update({k: float(v) for k, v in params.items() if k in PARAM_DEFAULTS})

    perm = _make_perm(_seed_for(recipe_id, p))
    perm_crack = _make_perm(_seed_for(recipe_id + "#crack", p))

    ang = math.radians(p["strata_angle"])
    ca, sa = math.cos(ang), math.sin(ang)

    base_freq = 5.0           # large rock breakup
    strata_freq = 22.0        # banding
    crack_freq = 9.0
    grain_freq = 60.0

    height = [0.0] * (work * work)
    cracks = [0.0] * (work * work)
    sand = [0.0] * (work * work)

    inv = 1.0 / work
    # cracks live in the valleys of ridged noise (ridge near 0). A small,
    # density-driven threshold means higher crack_density -> wider/more cracks.
    crack_thresh = 0.04 + 0.34 * p["crack_density"]

    idx = 0
    for j in range(work):
        v = j * inv
        for i in range(work):
            u = i * inv
            # rotate UV for strata direction
            ru = u * ca - v * sa
            rv = u * sa + v * ca

            base = _fbm(u * base_freq, v * base_freq, perm, octaves=4)
            # strata: rotated banded sine warped by noise
            band = 0.5 + 0.5 * math.sin((rv * strata_freq * math.pi)
                                        + 4.0 * _fbm(ru * 3.0, rv * 3.0, perm, octaves=2))
            grain = _fbm(u * grain_freq, v * grain_freq, perm, octaves=2)

            # erosion: bias downward streaks, strength-controlled smoothing of detail
            eros = p["erosion_strength"]
            streak = _fbm(u * 8.0, v * 30.0, perm, octaves=3)  # vertically stretched
            h = (0.55 * base + 0.30 * band + 0.15 * grain)
            h = h * (1.0 - 0.35 * eros) + 0.35 * eros * streak

            # crack network: ridged noise -> sharp valleys. crack mask = how far
            # the ridge sits below the density-driven threshold, tightened to lines.
            cn = _fbm(u * crack_freq, v * crack_freq, perm_crack, octaves=4)
            ridge = abs(2.0 * cn - 1.0)
            crack = _clamp01((crack_thresh - ridge) / max(crack_thresh, 1e-3)) ** 1.5

            h -= crack * p["crack_depth"] * 0.6
            h = _clamp01(h)

            # sand settles into low areas; more with sand_overlay
            low = _clamp01((0.42 - h) / 0.42)
            sand_amt = _clamp01(low * (0.4 + 1.2 * p["sand_overlay"]) - 0.05)

            height[idx] = h
            cracks[idx] = crack
            sand[idx] = sand_amt
            idx += 1

    return p, height, cracks, sand


def _normal_rgb(height, work, i, j, intensity):
    """Tangent-space normal from height neighbours -> (r,g,b) bytes."""
    def H(a, b):
        return height[(b % work) * work + (a % work)]
    scale = 4.0 * intensity
    dx = (H(i - 1, j) - H(i + 1, j)) * scale
    dy = (H(i, j - 1) - H(i, j + 1)) * scale
    nz = 1.0
    inv = 1.0 / math.sqrt(dx * dx + dy * dy + nz * nz)
    nx, ny, nz = dx * inv, dy * inv, nz * inv
    return (int((nx * 0.5 + 0.5) * 255),
            int((ny * 0.5 + 0.5) * 255),
            int((nz * 0.5 + 0.5) * 255))


def build_channel_rows(channel: str, p, height, cracks, sand, work):
    """Return `work` bytes rows (width*3 RGB) for one channel at work resolution."""
    rows = []
    base_hue, sat, val = p["base_hue"], p["saturation"], p["value"]
    norm_int = p["normal_intensity"]
    sand_rgb = _hsv_to_rgb(0.10, 0.30, 0.78)  # warm dry sand

    for j in range(work):
        row = bytearray(work * 3)
        base = j * work
        for i in range(work):
            idx = base + i
            h = height[idx]
            cr = cracks[idx]
            sd = sand[idx]
            o = i * 3

            if channel == "height":
                b = int(h * 255)
                row[o] = row[o + 1] = row[o + 2] = b

            elif channel == "ambient_occlusion":
                # cavities (cracks) + low areas occlude
                ao = _clamp01(1.0 - 0.85 * cr - 0.15 * _clamp01(0.4 - h))
                b = int(ao * 255)
                row[o] = row[o + 1] = row[o + 2] = b

            elif channel == "roughness":
                # rougher in cracks/cavities, slightly smoother where sand pools,
                # micro-variation from height so it never reads as flat
                rough = 0.62 + 0.25 * cr - 0.12 * sd + 0.08 * (h - 0.5)
                b = int(_clamp01(rough) * 255)
                row[o] = row[o + 1] = row[o + 2] = b

            elif channel == "normal":
                r, g, bb = _normal_rgb(height, work, i, j, norm_int)
                row[o], row[o + 1], row[o + 2] = r, g, bb

            else:  # base_color
                # rock hue, brightened on peaks, darkened (cavity dirt) in cracks
                v_local = val * (0.78 + 0.30 * h)
                s_local = sat * (1.0 - 0.25 * h)
                r, g, bb = _hsv_to_rgb(base_hue, s_local, _clamp01(v_local))
                r *= (1.0 - 0.55 * cr)
                g *= (1.0 - 0.55 * cr)
                bb *= (1.0 - 0.55 * cr)
                # blend toward sand in pooled low areas
                r = r + (sand_rgb[0] - r) * sd
                g = g + (sand_rgb[1] - g) * sd
                bb = bb + (sand_rgb[2] - bb) * sd
                row[o] = int(_clamp01(r) * 255)
                row[o + 1] = int(_clamp01(g) * 255)
                row[o + 2] = int(_clamp01(bb) * 255)
        rows.append(bytes(row))
    return rows


def _upscale_rows(rows: list, work: int, out: int) -> list:
    """Nearest-neighbour upscale of width*3 RGB rows from work -> out (square)."""
    if out == work:
        return rows
    # column map
    col = [(i * work) // out for i in range(out)]
    up = []
    for j in range(out):
        src = rows[(j * work) // out]
        ba = bytearray(out * 3)
        for i in range(out):
            s = col[i] * 3
            d = i * 3
            ba[d] = src[s]
            ba[d + 1] = src[s + 1]
            ba[d + 2] = src[s + 2]
        up.append(bytes(ba))
    return up


# --- recipe loading ---------------------------------------------------------
def _resolve(path_str: str, root: Path) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else root / p


def load_recipe_params(manifest: dict, manifest_path: Path, recipe_arg, root: Path):
    """Return (recipe_id, params dict) using the manifest's source_recipe."""
    src = manifest.get("source_recipe")
    if src:
        recipe_path = _resolve(src, root)
    elif recipe_arg:
        recipe_path = root / "procedural" / "substance" / "recipes" / f"{recipe_arg}.yaml"
    else:
        recipe_path = None

    recipe_id = manifest.get("recipe_id") or recipe_arg or "unknown"
    if recipe_path and recipe_path.exists():
        recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
        return recipe.get("id", recipe_id), recipe.get("parameters", {}) or {}
    return recipe_id, {}


def main():
    parser = argparse.ArgumentParser(description="Generate placeholder texture PNGs from a manifest.")
    parser.add_argument("--manifest")
    parser.add_argument("--recipe", help="Recipe id (derives manifest path if --manifest omitted).")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--size", type=int, default=None,
                        help="Output PNG size. Default: recipe resolution from the manifest.")
    parser.add_argument("--work-size", type=int, default=512,
                        help="Internal compute resolution for procedural maps (upscaled to --size).")
    parser.add_argument("--solid", action="store_true",
                        help="Original flat-colour-per-channel placeholders (no procedural model).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing non-empty files.")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if args.manifest:
        manifest_path = _resolve(args.manifest, root)
    elif args.recipe:
        manifest_path = root / "procedural" / "manifests" / "materials" / f"{args.recipe}.json"
    else:
        parser.error("provide --manifest or --recipe")

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    out_size = args.size or int(manifest.get("resolution", 256))

    # Procedural model is built once and shared across all five channels.
    fields = None
    if not args.solid:
        recipe_id, params = load_recipe_params(manifest, manifest_path, args.recipe, root)
        work = max(16, min(args.work_size, out_size))
        print(f"procedural model: recipe={recipe_id} work={work} out={out_size}")
        p, height, cracks, sand = generate_fields(params, recipe_id, work)
        fields = (p, height, cracks, sand, work)

    written, skipped = 0, 0
    for tex_type, info in manifest["exports"].items():
        out = _resolve(info["source_file"], root)
        if out.exists() and out.stat().st_size > 0 and not args.force:
            print(f"skip (exists): {out.name}")
            skipped += 1
            continue

        if args.solid:
            color = PLACEHOLDER_COLORS.get(tex_type, DEFAULT_COLOR)
            write_solid_png(out, out_size, out_size, color)
            print(f"wrote {out.name}  {out_size}x{out_size} solid rgb{color}")
        else:
            p, height, cracks, sand, work = fields
            rows = build_channel_rows(tex_type, p, height, cracks, sand, work)
            rows = _upscale_rows(rows, work, out_size)
            write_rgb_png(out, out_size, out_size, rows)
            print(f"wrote {out.name}  {out_size}x{out_size} procedural")
        written += 1

    print(f"done: {written} written, {skipped} skipped")


if __name__ == "__main__":
    main()
