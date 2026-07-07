#!/usr/bin/env python3
"""export_shopping_list.py — WorldForge v1.5 AssetAcquisitionForge (Wave 2).

Produce a MANUAL, human-actionable shopping list for a single source (Fab or
Poly Haven) and a single priority band, derived from the pack's generated
AssetNeed records. For each matching need the list carries: why it is needed,
search terms, license filters, format requirements, a priority score, expected
usage, a manual-action checklist, and post-download import instructions.

CRITICAL SAFETY BOUNDARY: this tool NEVER purchases, logs in, accepts a EULA,
or downloads anything. It only WRITES a list a human follows by hand. All
acquisition is manual by construction — there is no network path in this module.

Deterministic: generated_at derives from the git sha (never datetime.now()).
Stdlib only. The list is written to SHOPPING_LISTS_DIR and a v1.5 report is
emitted.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import asset_paths
from failure_codes import FailureCode
from report_meta import build_meta, git_sha
from validation_report import ValidationReport, strict_from_env

REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCES = ("fab", "polyhaven")
PRIORITIES = ("P0", "P1", "P2", "P3")

# Human-facing source metadata (search UI + license filter hints).
SOURCE_INFO = {
    "fab": {
        "display_name": "Fab (Epic)",
        "url": "https://www.fab.com",
        "license_filter_hint": "Fab Standard / CC0 — exclude editorial-only & noncommercial listings",
        "eula": "Fab EULA acceptance is MANUAL and per-listing",
    },
    "polyhaven": {
        "display_name": "Poly Haven",
        "url": "https://polyhaven.com",
        "license_filter_hint": "CC0 only (Poly Haven is uniformly CC0)",
        "eula": "CC0 — no EULA, attribution optional",
    },
}

# Priority -> numeric score (P0 most urgent).
PRIORITY_SCORE = {"P0": 100, "P1": 80, "P2": 55, "P3": 30}

# Asset type -> format/import requirements per source.
FORMAT_REQUIREMENTS = {
    "3d_mesh": {
        "download_formats": ["fbx", "gltf"],
        "ue_import": "Import as Static Mesh; enable 'Generate Missing Collision' only if none authored; set Nanite per budget.",
        "target_ue_path": "/Game/WorldForge/_Quarantine/<source>/<asset_id>",
    },
    "hdri": {
        "download_formats": ["hdr", "exr"],
        "ue_import": "Import as HDRI Cubemap / Texture; assign to Sky Light + HDRI Backdrop.",
        "target_ue_path": "/Game/WorldForge/_Quarantine/<source>/hdri/<asset_id>",
    },
    "decal": {
        "download_formats": ["png", "tga"],
        "ue_import": "Import as Texture; build a Deferred Decal material; project onto hazard zone.",
        "target_ue_path": "/Game/WorldForge/_Quarantine/<source>/decals/<asset_id>",
    },
    "material": {
        "download_formats": ["png", "tga", "exr"],
        "ue_import": "Import texture set; build Material / MI; bind to target mesh.",
        "target_ue_path": "/Game/WorldForge/_Quarantine/<source>/materials/<asset_id>",
    },
    "texture": {
        "download_formats": ["png", "tga", "exr"],
        "ue_import": "Import as Texture2D; set sRGB per channel role.",
        "target_ue_path": "/Game/WorldForge/_Quarantine/<source>/textures/<asset_id>",
    },
}


def _generated_at():
    sha = git_sha()
    return "generated@{}".format(sha if sha and sha != "unknown" else "unstamped")


def load_pack_needs(pack, priority):
    """Return [need_dict] for the pack, filtered to the requested priority."""
    out = []
    d = asset_paths.NEEDS_DIR
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(rec, dict) and rec.get("pack") == pack \
                and rec.get("priority") == priority:
            out.append(rec)
    out.sort(key=lambda r: r.get("asset_need_id", ""))
    return out


def _search_terms(need, source):
    biome = (need.get("biome_tags") or ["biome"])[0]
    role = (need.get("visual_requirements") or {}).get("role") \
        or (need.get("visual_requirements") or {}).get("cover_family") \
        or "asset"
    words = [biome.replace("_", " "), role.replace("_", " "), need.get("asset_type", "").replace("_", " ")]
    # Add cover family / usage tags for specificity.
    for t in (need.get("usage_tags") or [])[:2]:
        words.append(t.replace("_", " "))
    seen, terms = set(), []
    for w in words:
        w = w.strip()
        if w and w not in seen:
            seen.add(w)
            terms.append(w)
    return terms


def build_line(need, source):
    info = SOURCE_INFO[source]
    fmt = FORMAT_REQUIREMENTS.get(need.get("asset_type"), FORMAT_REQUIREMENTS["3d_mesh"])
    allowed = list(need.get("allowed_license_families") or [])
    disallowed = list(need.get("disallowed_license_families") or [])
    return {
        "asset_need_id": need["asset_need_id"],
        "display_name": need.get("display_name") or need["asset_need_id"],
        "asset_type": need.get("asset_type"),
        "required_count": int(need.get("required_count") or 0),
        "priority": need.get("priority"),
        "priority_score": PRIORITY_SCORE.get(need.get("priority"), 0),
        "reason_needed": need.get("rationale")
            or "Fills declared content gap for pack.",
        "search_terms": _search_terms(need, source),
        "license_filters": {
            "allowed_families": allowed,
            "disallowed_families": disallowed,
            "source_filter_hint": info["license_filter_hint"],
        },
        "format_requirements": {
            "download_formats": fmt["download_formats"],
            "min_quality_tier": need.get("minimum_quality_tier"),
            "collision_required": bool(need.get("collision_required")),
            "material_required": bool(need.get("material_required")),
        },
        "expected_usage": {
            "biome_tags": need.get("biome_tags") or [],
            "terrain_tags": need.get("terrain_tags") or [],
            "usage_tags": need.get("usage_tags") or [],
        },
        "manual_action_checklist": [
            "Open {} ({})".format(info["display_name"], info["url"]),
            "Search using the search_terms above",
            "Filter to allowed license families ({}); reject {}".format(
                ", ".join(allowed) or "n/a", ", ".join(disallowed) or "n/a"),
            "Review license terms manually — {}".format(info["eula"]),
            "Confirm the listing permits project-incorporated redistribution (no standalone resale)",
            "Manually download {} in {}".format(
                need.get("asset_type"), "/".join(fmt["download_formats"])),
            "Record source URL, author, license, and file hash for the provenance record",
        ],
        "post_download_import_instructions": [
            "Place downloaded bytes under quarantine root: {}".format(
                asset_paths.QUARANTINE_ROOT_ANCHORS[0]),
            fmt["ue_import"],
            "Target UE path: {}".format(fmt["target_ue_path"].replace("<source>", source)),
            "Run the candidate/quarantine/approval intake before moving to a final owned path",
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Export a MANUAL shopping list (no purchase/login/download performed).")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--priority", required=True, choices=PRIORITIES)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()
    pack, source, priority = args.pack, args.source, args.priority

    entity_id = "{}_{}_{}".format(pack, source, priority)
    rep = ValidationReport("asset_shopping_list", entity_id, strict=strict)

    needs = load_pack_needs(pack, priority)
    rep.check("needs_present", bool(needs),
              "found {} {} need(s) for pack {}".format(len(needs), priority, pack),
              code=FailureCode.ASSET_SHOPPING_LIST_FAILURE)

    lines = [build_line(n, source) for n in needs]

    shopping_list = {
        "shopping_list_id": entity_id,
        "pack": pack,
        "source": source,
        "source_display_name": SOURCE_INFO[source]["display_name"],
        "source_url": SOURCE_INFO[source]["url"],
        "priority": priority,
        "generated_at": _generated_at(),
        "acquisition_mode": "manual_only",
        "performs_purchase_login_eula_or_download": False,
        "item_count": len(lines),
        "items": lines,
        "operator_notes": [
            "This list is READ-ONLY intent. No purchase, login, EULA acceptance, "
            "or download is performed by this tool.",
            "Every acquisition is a manual human action following each item's "
            "manual_action_checklist.",
            "Quarantine all downloaded bytes before any final owned path.",
        ],
    }

    asset_paths.ensure(asset_paths.SHOPPING_LISTS_DIR)
    path = asset_paths.SHOPPING_LISTS_DIR / "{}.json".format(entity_id)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(shopping_list, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    for ln in lines:
        rep.check("line::{}".format(ln["asset_need_id"]), True,
                  "score={} formats={}".format(
                      ln["priority_score"], ln["format_requirements"]["download_formats"]))
    rep.check("no_acquisition_performed",
              shopping_list["performs_purchase_login_eula_or_download"] is False,
              "manual-only: no purchase/login/EULA/download",
              code=FailureCode.ASSET_SHOPPING_LIST_FAILURE)
    rep.check("list_written", True, str(path))

    rep.set_meta(build_meta(
        "export-shopping-list", pack=pack, strict=strict,
        report_type="wf.asset.shopping_list.v1", record_count=len(lines),
        records_total=len(lines), records_passed=len(lines), records_failed=0,
        extra={"source": source, "priority": priority}))
    rep.finalize()
    d, fn = asset_paths.report_path("assets", "export_shopping_list")
    rep.write(d, fn)
    rep.print_summary("export-shopping-list")
    print("[export-shopping-list] {} item(s) [{}/{}] -> {}".format(
        len(lines), source, priority, path))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
