#!/usr/bin/env python3
"""pack_score.py -- score the rendered desert variant pack from its outputs.

Reads each variant's biome_slice_result.json + before/after screenshots and
produces a machine report (_pack_result.json) and a human contact-sheet
(_pack_summary.md) under procedural/reports/slices/desert/.

This script is read-only with respect to every input. It ONLY writes the two
report files. It does not edit specs, render scripts, or boot UE.

Color analysis prefers PIL+numpy when available; otherwise it falls back to a
small pure-python PNG decoder (stdlib zlib). If neither can decode an image,
color math for that variant is recorded as unavailable and degrades gracefully.
"""

import datetime
import json
import math
import os
import struct
import zlib

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SLICES_DIR = os.path.join(REPO_ROOT, "procedural", "reports", "slices")
OUT_DIR = os.path.join(SLICES_DIR, "desert")
OUT_JSON = os.path.join(OUT_DIR, "_pack_result.json")
OUT_MD = os.path.join(OUT_DIR, "_pack_summary.md")

# Canonical variant order.
VARIANTS = ["industrialized", "sandy", "ash", "cracked", "clean", "heavy_industrial"]

EXPECTED_WORLD = "Desert_Valley_01"

# Terrain region-of-interest: lower-center band (avoids sky + most foliage).
ROI_ROW_FRAC = (0.60, 0.88)
ROI_COL_FRAC = (0.28, 0.72)

# Thresholds.
DARKEN_FACTOR = 0.92        # after_lum < before_lum * 0.92 == meaningful darkening
TOO_SIMILAR_DIST = 12.0     # pairwise RGB euclidean distance below this == too similar


# ---------------------------------------------------------------------------
# PNG decoding
# ---------------------------------------------------------------------------
try:
    from PIL import Image  # type: ignore
    import numpy as _np     # type: ignore
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _decode_png_pure(path):
    """Minimal PNG decoder for 8-bit grayscale/RGB/RGBA (color types 0,2,6).

    Returns (width, height, channels, bytearray pixels) row-major.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG: %s" % path)
    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length  # skip CRC
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", body[:10])
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
    if bit_depth != 8 or color_type not in (0, 2, 6):
        raise ValueError("unsupported PNG (bd=%s ct=%s)" % (bit_depth, color_type))
    channels = {0: 1, 2: 3, 6: 4}[color_type]
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    bpp = channels
    out = bytearray(stride * height)
    prior = bytearray(stride)
    rp = 0
    op = 0
    for _ in range(height):
        ftype = raw[rp]
        rp += 1
        line = bytearray(raw[rp:rp + stride])
        rp += stride
        if ftype == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prior[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prior[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prior[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, prior[i], c)) & 0xFF
        # ftype 0 == None: nothing to do
        out[op:op + stride] = line
        prior = line
        op += stride
    return width, height, channels, out


def roi_mean_rgb(path):
    """Mean (R,G,B) of the terrain ROI band for an image. Returns (r,g,b) floats."""
    if _HAVE_PIL:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        r0, r1 = int(h * ROI_ROW_FRAC[0]), int(h * ROI_ROW_FRAC[1])
        c0, c1 = int(w * ROI_COL_FRAC[0]), int(w * ROI_COL_FRAC[1])
        arr = _np.asarray(img)[r0:r1, c0:c1, :3].astype("float64")
        m = arr.reshape(-1, 3).mean(axis=0)
        return (float(m[0]), float(m[1]), float(m[2]))
    w, h, ch, px = _decode_png_pure(path)
    r0, r1 = int(h * ROI_ROW_FRAC[0]), int(h * ROI_ROW_FRAC[1])
    c0, c1 = int(w * ROI_COL_FRAC[0]), int(w * ROI_COL_FRAC[1])
    sr = sg = sb = 0
    n = 0
    stride = w * ch
    for row in range(r0, r1):
        base = row * stride
        idx = base + c0 * ch
        for _col in range(c0, c1):
            sr += px[idx]
            sg += px[idx + 1]
            sb += px[idx + 2]
            idx += ch
            n += 1
    if n == 0:
        return (0.0, 0.0, 0.0)
    return (sr / n, sg / n, sb / n)


def luminance(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def rgb_distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def round3(rgb):
    return [round(rgb[0], 2), round(rgb[1], 2), round(rgb[2], 2)]


# ---------------------------------------------------------------------------
# Variant evaluation
# ---------------------------------------------------------------------------
def find_screenshots(slice_dir):
    """Return sorted list of PNG paths in the variant's screenshots dir."""
    ss = os.path.join(slice_dir, "screenshots")
    if not os.path.isdir(ss):
        return []
    pngs = [os.path.join(ss, f) for f in os.listdir(ss) if f.lower().endswith(".png")]
    pngs.sort(key=lambda p: os.path.basename(p))
    return pngs


def rel(path):
    return os.path.relpath(path, REPO_ROOT).replace("\\", "/")


def eval_variant(variant):
    slug = "desert_" + variant
    slice_dir = os.path.join(SLICES_DIR, slug)
    result_json = os.path.join(slice_dir, "biome_slice_result.json")
    pngs = find_screenshots(slice_dir)

    entry = {
        "variant": variant,
        "slug": slug,
        "present": False,
        "mpc_matched": False,
        "terrain_darkens": False,
        "terrain_before_rgb": None,
        "terrain_after_rgb": None,
        "color_analysis": "not_run",
        "foliage": {"grass_decreases": False, "tree_decreases": False, "scrub_increases": False},
        "screenshots_saved": False,
        "correct_world": False,
        "biome_slice_passed": False,
        "before_png": None,
        "after_png": None,
        "verdict": "FAIL",
        "failures": [],
    }

    has_result = os.path.isfile(result_json)
    has_two_shots = len(pngs) >= 2
    entry["present"] = has_result and has_two_shots
    if not entry["present"]:
        reasons = []
        if not has_result:
            reasons.append("no biome_slice_result.json")
        if not has_two_shots:
            reasons.append("fewer than 2 screenshots (found %d)" % len(pngs))
        entry["failures"].append("not present: " + "; ".join(reasons))
        return entry

    # --- biome_slice_result.json fields ---
    with open(result_json, "r", encoding="utf-8") as fh:
        res = json.load(fh)
    acc = res.get("acceptance", {}) or {}

    entry["mpc_matched"] = bool(acc.get("mpc_updates"))
    entry["screenshots_saved"] = bool(acc.get("screenshots_saved"))
    entry["correct_world"] = (acc.get("editor_world") == EXPECTED_WORLD)
    entry["biome_slice_passed"] = bool(acc.get("passed"))

    decreases = acc.get("foliage_decreases", {}) or {}
    increases = acc.get("foliage_increases", {}) or {}
    grass_ok = bool(decreases.get("reclaimed_grass", {}).get("ok"))
    tree_ok = bool(decreases.get("young_tree", {}).get("ok"))
    scrub_ok = bool(increases.get("dead_scrub", {}).get("ok"))
    entry["foliage"] = {
        "grass_decreases": grass_ok,
        "tree_decreases": tree_ok,
        "scrub_increases": scrub_ok,
    }

    # --- screenshots (first=before, last=after) ---
    before_png, after_png = pngs[0], pngs[-1]
    entry["before_png"] = rel(before_png)
    entry["after_png"] = rel(after_png)

    try:
        before_rgb = roi_mean_rgb(before_png)
        after_rgb = roi_mean_rgb(after_png)
        entry["terrain_before_rgb"] = round3(before_rgb)
        entry["terrain_after_rgb"] = round3(after_rgb)
        entry["terrain_darkens"] = luminance(after_rgb) < luminance(before_rgb) * DARKEN_FACTOR
        entry["color_analysis"] = "ok"
        entry["_before_rgb_raw"] = before_rgb  # internal, stripped before write
    except Exception as exc:  # decode failure -> degrade gracefully
        entry["color_analysis"] = "unavailable"
        entry["failures"].append("color analysis unavailable: %s" % exc)

    # --- assemble failure reasons + verdict ---
    f = entry["failures"]
    if not entry["mpc_matched"]:
        f.append("MPC not updated (acceptance.mpc_updates false) -- material params not applied")
    if not grass_ok:
        f.append("reclaimed_grass did not decrease as required")
    if not tree_ok:
        f.append("young_tree did not decrease as required")
    if not scrub_ok:
        f.append("dead_scrub did not increase as required")
    if not entry["screenshots_saved"]:
        f.append("screenshots_saved flag false in acceptance")
    if not entry["correct_world"]:
        f.append("editor_world != %s (wrong/unsaved map: %r)"
                 % (EXPECTED_WORLD, acc.get("editor_world")))
    if entry["color_analysis"] == "ok" and not entry["terrain_darkens"]:
        b = entry["terrain_before_rgb"]
        a = entry["terrain_after_rgb"]
        f.append("terrain did not darken (before lum=%.1f after lum=%.1f; need < %.0f%%) "
                 "-- soot/state not visibly affecting terrain ROI"
                 % (luminance(b), luminance(a), DARKEN_FACTOR * 100))

    verdict_pass = (
        entry["mpc_matched"]
        and grass_ok and tree_ok and scrub_ok
        and entry["screenshots_saved"]
        and entry["correct_world"]
        and entry["terrain_darkens"]
    )
    entry["verdict"] = "PASS" if verdict_pass else "FAIL"
    return entry


# ---------------------------------------------------------------------------
# Cross-variant checks
# ---------------------------------------------------------------------------
def file_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def cross_variant_checks(entries):
    present = [e for e in entries if e["present"]]
    too_similar = []
    min_dist = None

    # Pairwise color distance over BEFORE terrain ROI.
    color_present = [e for e in present if e.get("_before_rgb_raw") is not None]
    for i in range(len(color_present)):
        for j in range(i + 1, len(color_present)):
            a, b = color_present[i], color_present[j]
            d = rgb_distance(a["_before_rgb_raw"], b["_before_rgb_raw"])
            if min_dist is None or d < min_dist:
                min_dist = d
            if d < TOO_SIMILAR_DIST:
                too_similar.append({
                    "a": a["variant"], "b": b["variant"], "distance": round(d, 2),
                })

    # Byte-identical detection over BEFORE PNGs.
    byte_identical = []
    digests = {}
    for e in present:
        if not e["before_png"]:
            continue
        p = os.path.join(REPO_ROOT, e["before_png"])
        try:
            blob = file_bytes(p)
        except OSError:
            continue
        key = (len(blob), zlib.crc32(blob))
        if key in digests:
            # confirm true identity (guard against crc collision)
            other_var, other_blob = digests[key]
            if other_blob == blob:
                byte_identical.append({"a": other_var, "b": e["variant"]})
        else:
            digests[key] = (e["variant"], blob)

    return {
        "min_pair_distance": round(min_dist, 2) if min_dist is not None else None,
        "too_similar_pairs": too_similar,
        "byte_identical_pairs": byte_identical,
        "too_similar_threshold": TOO_SIMILAR_DIST,
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------
def write_markdown(report, entries):
    lines = []
    lines.append("# Desert Variant Pack -- Score Summary")
    lines.append("")
    lines.append("Generated: %s" % report["generated_at_utc"])
    lines.append("")
    lines.append("Pack verdict: **%s**" % report["pack_verdict"])
    lines.append("")
    lines.append("Color analysis backend: %s"
                 % ("PIL+numpy" if _HAVE_PIL else "pure-python PNG decoder"))
    lines.append("")

    # Contact-sheet table.
    lines.append("| variant | verdict | terrain before RGB -> after RGB | darkens? | "
                 "foliage ok (grass/tree/scrub)? | mpc | world | screenshots |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for e in entries:
        if not e["present"]:
            lines.append("| %s | MISSING | - | - | - | - | - | (not rendered) |"
                         % e["variant"])
            continue
        before = e["terrain_before_rgb"]
        after = e["terrain_after_rgb"]
        rgb_cell = ("(%.0f,%.0f,%.0f) -> (%.0f,%.0f,%.0f)"
                    % (before[0], before[1], before[2], after[0], after[1], after[2])
                    if before and after else "unavailable")
        fol = e["foliage"]
        fol_cell = "%s/%s/%s" % (
            "Y" if fol["grass_decreases"] else "N",
            "Y" if fol["tree_decreases"] else "N",
            "Y" if fol["scrub_increases"] else "N",
        )
        ss_cell = "%s , %s" % (e["before_png"], e["after_png"])
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            e["variant"], e["verdict"], rgb_cell,
            "Y" if e["terrain_darkens"] else "N",
            fol_cell,
            "Y" if e["mpc_matched"] else "N",
            "Y" if e["correct_world"] else "N",
            ss_cell,
        ))
    lines.append("")

    # Cross-variant.
    cv = report["cross_variant"]
    lines.append("## Cross-variant checks")
    lines.append("")
    lines.append("- Min pairwise BEFORE-terrain RGB distance: %s (flag threshold < %s)"
                 % (cv["min_pair_distance"], cv["too_similar_threshold"]))
    if cv["too_similar_pairs"]:
        lines.append("- **Too-similar pairs (not visibly distinct):**")
        for p in cv["too_similar_pairs"]:
            lines.append("  - %s <-> %s (distance %s)" % (p["a"], p["b"], p["distance"]))
    else:
        lines.append("- Too-similar pairs: none")
    if cv["byte_identical_pairs"]:
        lines.append("- **Byte-identical BEFORE screenshots (hard fail):**")
        for p in cv["byte_identical_pairs"]:
            lines.append("  - %s == %s" % (p["a"], p["b"]))
    else:
        lines.append("- Byte-identical screenshots: none")
    lines.append("")

    # Missing.
    if report["missing_variants"]:
        lines.append("## Missing variants (not yet rendered)")
        lines.append("")
        for v in report["missing_variants"]:
            lines.append("- %s" % v)
        lines.append("")

    # Failed variants + root cause.
    failed = [e for e in entries if e["present"] and e["verdict"] != "PASS"]
    if failed:
        lines.append("## Failed variants (root cause)")
        lines.append("")
        for e in failed:
            lines.append("### %s" % e["variant"])
            for reason in e["failures"]:
                lines.append("- %s" % reason)
            lines.append("")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    entries = [eval_variant(v) for v in VARIANTS]
    cross = cross_variant_checks(entries)

    missing = [e["variant"] for e in entries if not e["present"]]

    pack_pass = (
        len(missing) == 0
        and all(e["verdict"] == "PASS" for e in entries if e["present"])
        and not cross["too_similar_pairs"]
        and not cross["byte_identical_pairs"]
    )

    report = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "color_backend": "PIL+numpy" if _HAVE_PIL else "pure-python",
        "variants": [],
        "cross_variant": cross,
        "missing_variants": missing,
        "pack_verdict": "PASS" if pack_pass else "FAIL",
    }

    # Strip internal fields before serialising.
    for e in entries:
        clean = {k: v for k, v in e.items() if not k.startswith("_")}
        report["variants"].append(clean)

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")

    write_markdown(report, entries)

    print("pack_verdict:", report["pack_verdict"])
    print("present:", [e["variant"] for e in entries if e["present"]])
    print("missing:", missing)
    print("too_similar:", cross["too_similar_pairs"])
    print("byte_identical:", cross["byte_identical_pairs"])
    print("wrote:", rel(OUT_JSON))
    print("wrote:", rel(OUT_MD))


if __name__ == "__main__":
    main()
