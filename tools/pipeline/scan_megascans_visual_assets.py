#!/usr/bin/env python3
"""scan_megascans_visual_assets.py — WorldForge v1.3.5 Visual Fidelity scanner (Agent 1).

Reclassifies every THIRD-PARTY Megascans record already in the external asset
catalog into a WorldForge *visual asset class* (surface fidelity + dressing) and
writes the classified visual asset catalog the coverage validator consumes.

This is a pure reclassification pass over the v1.2 external catalog — it NEVER
copies, generates, or takes ownership of the Megascans source. Every emitted
record stays third_party_owned / generated_owned=false (brief §3 / visual_contract
ownership rule); only the WorldForge-derived ``visual_class`` is added.

Usage:
    python tools/pipeline/scan_megascans_visual_assets.py --lib megascans
    STRICT=1 python tools/pipeline/scan_megascans_visual_assets.py --lib megascans --strict

Writes:
    procedural/generated/worldforge_visual_asset_catalog.json  (keyed by external_asset_id)
    procedural/reports/visual/scan_megascans_visual_assets/scan_megascans_visual_assets_report.json
"""

import argparse
import datetime
import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import external_asset_contract as EAC
import visual_contract as VC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GENERATOR = "scan_megascans_visual_assets"
GENERATOR_VERSION = "1.3.5.0"


def classify_visual_class(asset_type, asset_category):
    """Map a Megascans (asset_type, asset_category) to a VC.VISUAL_ASSET_CLASSES value.

    rock       -> cliff_surface (cliff/formation) else rock_dressing
    surface    -> ground_surface (materials/ground)
    debris     -> debris_dressing
    vegetation -> vegetation_dressing
    decal      -> decal
    (unknown)  -> ground_surface  (safe surface default; every record is classified)
    """
    t = (asset_type or "").lower()
    cat = (asset_category or "").lower()
    if t == "rock":
        if any(k in cat for k in ("cliff", "formation", "outcrop", "ledge", "wall")):
            return "cliff_surface"
        return "rock_dressing"
    if t == "surface":
        return "ground_surface"
    if t == "debris":
        return "debris_dressing"
    if t == "vegetation":
        return "vegetation_dressing"
    if t == "decal":
        return "decal"
    return "ground_surface"


def _source_ref(rec):
    """A non-absolute reference back to the third-party source (never a WF path)."""
    return (rec.get("descriptor_path") or rec.get("source_path")
            or rec.get("catalog_record") or rec.get("external_asset_id"))


def build_visual_record(ext_id, rec):
    visual_class = classify_visual_class(rec.get("asset_type"), rec.get("asset_category"))
    return {
        "external_asset_id": ext_id,
        "visual_class": visual_class,
        "biome_compatibility": list(rec.get("biome_compatibility") or []),
        "asset_type": rec.get("asset_type"),
        # Ownership stays third-party — the source is licensed, not generated.
        "ownership_class": VC.OWNERSHIP_THIRD_PARTY,
        "generated_owned": False,
        "third_party_owned": True,
        "source_ref": _source_ref(rec),
    }


def save_visual_asset_catalog(catalog, repo_root=REPO_ROOT):
    path = Path(repo_root) / VC.VISUAL_ASSET_CATALOG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(str(tmp), str(path))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reclassify the Megascans external catalog into visual asset classes.")
    ap.add_argument("--lib", default="megascans")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("library", args.lib, strict=strict)
    external = EAC.load_external_catalog(REPO_ROOT).get("assets", {}) or {}

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    visual_assets = {}
    per_biome = Counter()
    per_class = Counter()
    unclassified = []
    ownership_leak = []

    for ext_id in sorted(external.keys()):
        rec = external[ext_id]
        vrec = build_visual_record(ext_id, rec)
        vclass = vrec["visual_class"]
        if vclass not in VC.VISUAL_ASSET_CLASSES:
            unclassified.append(ext_id)
        if vrec["ownership_class"] != VC.OWNERSHIP_THIRD_PARTY or vrec["generated_owned"] is not False:
            ownership_leak.append(ext_id)
        visual_assets[ext_id] = vrec
        per_class[vclass] += 1
        for b in vrec["biome_compatibility"]:
            per_biome[b] += 1

    scanned = len(visual_assets)
    catalog = {
        "schema_version": VC.VISUAL_SCHEMA_VERSION,
        "library_id": args.lib,
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "generated_at_utc": now,
        "source_catalog": EAC.EXTERNAL_CATALOG_REL,
        "assets": visual_assets,
    }
    save_visual_asset_catalog(catalog, REPO_ROOT)

    rep.check("externals_available", scanned > 0,
              "no external assets in {} — run scan_external_asset_library first".format(EAC.EXTERNAL_CATALOG_REL),
              code=FailureCode.MEGASCANS_SCAN_FAILURE)
    rep.check("every_record_classified", not unclassified,
              "unclassified: {}".format(unclassified),
              code=FailureCode.MEGASCANS_SCAN_FAILURE)
    rep.check("ownership_stays_third_party", not ownership_leak,
              "records that lost third-party ownership: {}".format(ownership_leak),
              code=FailureCode.MEGASCANS_SCAN_FAILURE)

    coverage = {
        "scanned": scanned,
        "per_biome": dict(sorted(per_biome.items())),
        "per_visual_class": dict(sorted(per_class.items())),
    }
    rep.finalize()
    rep.set_meta(build_meta(command="scan-megascans-visual-assets", pack=args.lib,
                            strict=strict, status=rep.status, record_count=scanned,
                            extra={"coverage": coverage}))
    report_dir = REPO_ROOT / VC.VISUAL_REPORTS_REL / "scan_megascans_visual_assets"
    rep.write(report_dir, "scan_megascans_visual_assets_report.json")
    rep.print_summary("scan-megascans-visual-assets")
    print("[scan-megascans-visual-assets] {} visual assets classified from '{}'".format(scanned, args.lib))
    print("[scan-megascans-visual-assets] per_visual_class={}".format(coverage["per_visual_class"]))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
