#!/usr/bin/env python3
"""build_conversion_manifest.py — v2.5 Lane 3 pre-conversion inventory (read-only).

Walks the repo's committed content roots and emits a DETERMINISTIC pre-conversion
inventory of every asset the authoritative UE 5.7 -> 5.8 conversion will touch. This
is INVENTORY ONLY: it opens no editor, resaves no asset, and writes no .uasset/.umap.
It is the honest "before" snapshot the commander's serial conversion window diffs its
output against (see audit_conversion_diff.py).

What it can and cannot know
---------------------------
* CAN, read-only: repo-relative path, byte size, streamed sha256 content hash, and a
  path/extension/redirector-byte classification (map / blueprint / material /
  data_asset / texture / redirector / other).
* CANNOT, without the editor: per-map actor counts. UMAP actor accounting requires a
  loaded UWorld. This tool therefore records ``actors_before = null`` with an explicit
  ``actors_note = "unknown_without_editor"`` and NEVER fabricates a count. The
  authoritative ConversionManifest (commander's job) fills real actor counts from a
  live 5.8 editor.

Determinism: assets are sorted by repo-relative POSIX path; hashing is a streamed
sha256 of file bytes. Two runs on an unchanged tree produce byte-identical output
(modulo the runtime meta fields git_sha/timestamp, which report_meta marks runtime-only).

Usage:
    PYTHONUTF8=1 python tools/pipeline/build_conversion_manifest.py
Emits -> procedural/manifests/ue5_8_conversion/pre_conversion_manifest.json
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta  # noqa: E402

# Content roots the conversion will touch (repo-relative). Read-only walk.
CONTENT_ROOTS = ("Content", "Plugins/WorldForge/Content")

# Output — MACHINE-GENERATED ONLY. Never hand-edit.
MANIFEST_DIR = REPO_ROOT / "procedural" / "manifests" / "ue5_8_conversion"
MANIFEST_NAME = "pre_conversion_manifest.json"

SOURCE_ENGINE = "5.7"
TARGET_ENGINE = "5.8"

# Classification taxonomy (bounded — mirrors the conversion audit vocabulary).
ASSET_TYPES = ("map", "blueprint", "material", "data_asset", "texture",
               "redirector", "other")

# A redirector's class name appears verbatim in a .uasset name table; a cheap,
# read-only byte scan flags it without loading the editor.
_REDIRECTOR_MARKER = b"ObjectRedirector"


def _sha256_and_size(path):
    """Stream a file's bytes -> (sha256 hex, size, first_chunk_bytes)."""
    h = hashlib.sha256()
    size = 0
    first_chunk = b""
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            if not first_chunk:
                first_chunk = chunk
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size, first_chunk


def classify(rel_posix, first_chunk):
    """Classify an asset by extension / path / redirector-marker (read-only)."""
    lower = rel_posix.lower()
    if lower.endswith(".umap"):
        return "map"
    if lower.endswith(".uasset"):
        # A redirector is detectable from its class-name marker in the header.
        if _REDIRECTOR_MARKER in first_chunk:
            return "redirector"
        base = rel_posix.rsplit("/", 1)[-1]
        if base.startswith("T_"):
            return "texture"
        if base.startswith(("M_", "MI_")):
            return "material"
        if base.startswith("DA_"):
            return "data_asset"
        if base.startswith(("BP_", "ABP_", "WBP_")):
            return "blueprint"
        # SM_/PCG_/etc. are real assets but outside the named taxonomy.
        return "other"
    # .hda, .gitkeep, and anything else are recorded (never silently dropped).
    return "other"


def build_inventory():
    """Walk the content roots and return a deterministic inventory dict."""
    assets = []
    roots_present = []
    for root_rel in CONTENT_ROOTS:
        root = REPO_ROOT / root_rel
        roots_present.append({"root": root_rel, "exists": root.is_dir()})
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel_posix = path.relative_to(REPO_ROOT).as_posix()
            sha, size, first_chunk = _sha256_and_size(path)
            atype = classify(rel_posix, first_chunk)
            entry = {
                "path": rel_posix,
                "type": atype,
                "size_bytes": size,
                "sha256": sha,
            }
            if atype == "map":
                # Actor counts are NOT extractable without a loaded UWorld.
                entry["actors_before"] = None
                entry["actors_note"] = "unknown_without_editor"
            assets.append(entry)

    assets.sort(key=lambda e: e["path"])

    counts_by_type = {t: 0 for t in ASSET_TYPES}
    for e in assets:
        counts_by_type[e["type"]] = counts_by_type.get(e["type"], 0) + 1
    total_bytes = sum(e["size_bytes"] for e in assets)

    return {
        "conversion_status": "pre_conversion_inventory",
        "source_engine": SOURCE_ENGINE,
        "target_engine": TARGET_ENGINE,
        "generated_by": "tools/pipeline/build_conversion_manifest.py",
        "content_roots": roots_present,
        "asset_count": len(assets),
        "map_count": counts_by_type.get("map", 0),
        "total_bytes": total_bytes,
        "counts_by_type": counts_by_type,
        "actor_accounting": "unknown_without_editor",
        "assets": assets,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 Lane 3 pre-conversion inventory.")
    ap.add_argument("--out", default=str(MANIFEST_DIR / MANIFEST_NAME))
    args, _ = ap.parse_known_args(argv)

    inv = build_inventory()

    # Deterministic content hash of the asset list (excludes runtime meta).
    inv_hash = hashlib.sha256(
        json.dumps(inv["assets"], sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()

    inv["meta"] = build_meta(
        command="build-conversion-manifest",
        pack="worldforge_vertical_slice",
        status="ok",
        record_count=inv["asset_count"],
        records_total=inv["asset_count"],
        records_passed=inv["asset_count"],
        output_manifest_hash=inv_hash,
        report_type="wf.transition.pre_conversion_inventory.v1",
        extra={
            "declared_target_engine": "5.8",
            "observed_runtime_engine": None,
            "runtime_execution_required": False,
            "runtime_executed": False,
        })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(inv, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    try:
        shown = out_path.relative_to(Path.cwd())
    except ValueError:
        shown = out_path
    print("[pre-conversion-inventory] {} assets, {} maps, {} bytes -> {}".format(
        inv["asset_count"], inv["map_count"], inv["total_bytes"], shown))
    print("[pre-conversion-inventory] counts_by_type: {}".format(
        json.dumps(inv["counts_by_type"], sort_keys=True)))
    print("[pre-conversion-inventory] conversion_status = {} (actor counts "
          "deferred: {})".format(inv["conversion_status"], inv["actor_accounting"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
