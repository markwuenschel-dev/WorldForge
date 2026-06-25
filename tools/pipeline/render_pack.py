#!/usr/bin/env python3
r"""
render_pack.py -- render a whole biome's preset pack back to back.

    make render-desert-pack
    python tools/pipeline/render_pack.py --biome desert
    python tools/pipeline/render_pack.py --biome desert --no-render   # plumbing test

Orchestration only: for each variant of a biome it invokes

    python tools/pipeline/biome_slice.py --biome <biome> --variant <variant>

one variant at a time. A failing variant does NOT abort the pack -- its return
code is captured and the loop continues -- so one bad preset can't hide the
state of the rest. After the loop it prints a console summary table and exits
non-zero if ANY variant failed.

The variant list is discovered by scanning procedural/slices/<biome>_*.yaml that
actually exist (so it stays in sync with the configs on disk), then ordered by a
sensible canonical sequence with any unknown variants appended alphabetically.

The rich scored report is pack_score.py's job; this script only orchestrates and
prints a quick console summary.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SLICES_DIR = REPO / "procedural" / "slices"
REPORTS_DIR = REPO / "procedural" / "reports" / "slices"
BIOME_SLICE = "tools/pipeline/biome_slice.py"

# Canonical order for known desert presets. Variants found on disk but not listed
# here are appended in alphabetical order so new presets still render.
CANONICAL_ORDER = {
    "desert": ["industrialized", "sandy", "ash", "cracked", "clean", "heavy_industrial"],
}


def discover_variants(biome, include_extras=False):
    """Return the existing <biome>_*.yaml variants in canonical-then-alpha order.

    By default only the canonical pack variants are returned -- this is the pack the
    finish line and pack_score.py are defined against. Pass include_extras=True to
    also render any other <biome>_*.yaml on disk (e.g. legacy state variants) that
    are not part of the canonical pack."""
    prefix = "{}_".format(biome)
    found = sorted(
        p.stem[len(prefix):] for p in SLICES_DIR.glob("{}*.yaml".format(prefix))
    )
    order = CANONICAL_ORDER.get(biome, [])
    ranked = [v for v in order if v in found]
    if not include_extras:
        return ranked
    extras = sorted(v for v in found if v not in order)
    return ranked + extras


def render_variant(biome, variant, no_render):
    """Run biome_slice for one variant; return its return code (never raises)."""
    cmd = [sys.executable, BIOME_SLICE, "--biome", biome, "--variant", variant]
    if no_render:
        cmd.append("--no-render")
    print("\n[render-pack] ===== {}_{} =====".format(biome, variant))
    print("[render-pack] $ {}".format(" ".join(str(c) for c in cmd)))
    proc = subprocess.run(cmd, cwd=str(REPO))
    print("[render-pack] {}_{} exited rc={}".format(biome, variant, proc.returncode))
    return proc.returncode


def load_result(biome, variant):
    """Read a variant's biome_slice_result.json if present, else None."""
    path = REPORTS_DIR / "{}_{}".format(biome, variant) / "biome_slice_result.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def summarize(biome, rows):
    """Print the console summary table. rows: list of (variant, rc, result)."""
    print("\n[render-pack] ==================== pack summary ({}) ====================".format(biome))
    print("[render-pack] {:<20} {:>3}  {:<9} {:<10}".format("variant", "rc", "rendered", "acceptance"))
    print("[render-pack] {}".format("-" * 50))
    for variant, rc, result in rows:
        rendered = "-"
        acceptance = "-"
        if result is not None:
            rendered = "yes" if result.get("rendered") else "no"
            acc = result.get("acceptance")
            if acc is None:
                acceptance = "n/a"  # --no-render: authoring + spec only, not scored
            else:
                acceptance = "PASS" if acc.get("passed") else "FAIL"
        print("[render-pack] {:<20} {:>3}  {:<9} {:<10}".format(variant, rc, rendered, acceptance))
    print("[render-pack] {}".format("-" * 50))


def main():
    ap = argparse.ArgumentParser(description="Render a biome's whole preset pack back to back.")
    ap.add_argument("--biome", default="desert")
    ap.add_argument("--no-render", action="store_true",
                    help="Pass --no-render through to each biome_slice call (plumbing test; no UE).")
    ap.add_argument("--all", action="store_true",
                    help="Also render non-canonical <biome>_*.yaml variants (legacy/extra presets).")
    args = ap.parse_args()

    variants = discover_variants(args.biome, include_extras=args.all)
    if not variants:
        print("[render-pack] no slice configs found for biome '{}' in {}".format(args.biome, SLICES_DIR))
        raise SystemExit(2)

    print("[render-pack] biome '{}' -> {} variant(s): {}".format(
        args.biome, len(variants), ", ".join(variants)))
    if args.no_render:
        print("[render-pack] --no-render: skipping headless UE launch for every variant.")

    rows = []
    failed = []
    for variant in variants:
        rc = render_variant(args.biome, variant, args.no_render)
        result = load_result(args.biome, variant)
        rows.append((variant, rc, result))
        if rc != 0:
            failed.append(variant)

    summarize(args.biome, rows)

    if failed:
        print("[render-pack] {} of {} variant(s) FAILED: {}".format(
            len(failed), len(variants), ", ".join(failed)))
        raise SystemExit(1)
    print("[render-pack] all {} variant(s) OK".format(len(variants)))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
