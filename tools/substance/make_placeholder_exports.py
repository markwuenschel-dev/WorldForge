#!/usr/bin/env python3
r"""
make_placeholder_exports.py
Generate valid solid-colour placeholder PNGs for a manifest's texture exports,
so the UE import lane can be tested without a real Substance render.

Pure stdlib (zlib + struct) - no Pillow required. Each channel map gets a
sensible flat value (flat normal, white AO, mid roughness/height, a neutral
base colour). Existing non-empty files are left alone unless --force.

Usage:
    python tools/substance/make_placeholder_exports.py --recipe terrain_rock_desert_01
    python tools/substance/make_placeholder_exports.py --manifest <path> --project-root <root>
"""

import argparse
import json
import struct
import zlib
from pathlib import Path

PLACEHOLDER_COLORS = {
    "base_color": (150, 110, 75),       # neutral desert rock
    "normal": (128, 128, 255),          # flat tangent-space normal
    "roughness": (180, 180, 180),       # fairly rough
    "ambient_occlusion": (255, 255, 255),  # unoccluded
    "height": (128, 128, 128),          # mid height
}
DEFAULT_COLOR = (128, 128, 128)


def write_solid_png(path: Path, width: int, height: int, rgb) -> None:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    row = b"\x00" + bytes(rgb) * width        # filter byte 0 + RGB pixels
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit, colour type 2 (RGB)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def main():
    parser = argparse.ArgumentParser(description="Generate placeholder texture PNGs from a manifest.")
    parser.add_argument("--manifest")
    parser.add_argument("--recipe", help="Recipe id (derives manifest path if --manifest omitted).")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--force", action="store_true", help="Overwrite existing non-empty files.")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
    elif args.recipe:
        manifest_path = root / "procedural" / "manifests" / "materials" / f"{args.recipe}.json"
    else:
        parser.error("provide --manifest or --recipe")

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

    written, skipped = 0, 0
    for tex_type, info in manifest["exports"].items():
        out = Path(info["source_file"])
        if not out.is_absolute():
            out = root / out
        if out.exists() and out.stat().st_size > 0 and not args.force:
            print(f"skip (exists): {out.name}")
            skipped += 1
            continue
        color = PLACEHOLDER_COLORS.get(tex_type, DEFAULT_COLOR)
        write_solid_png(out, args.size, args.size, color)
        print(f"wrote {out.name}  {args.size}x{args.size} rgb{color}")
        written += 1

    print(f"done: {written} written, {skipped} skipped")


if __name__ == "__main__":
    main()
