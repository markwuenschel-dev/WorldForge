#!/usr/bin/env python3
"""analyze_asset_gaps.py — WorldForge v1.5 AssetAcquisitionForge (Wave 2).

Turn a generated encounter pack into CONCRETE, schema-valid AssetNeed records: a
declared inventory of content gaps that must be filled before the pack's cover
proxies and biome dressing can be replaced with real, licensed, owned assets.

This stage is pure intent — it NEVER downloads, purchases, or logs in anywhere.
It reads the read-only encounter records, aggregates the gaps, and emits one
AssetNeed per gap under asset_paths.NEEDS_DIR, then a gap report. Every emitted
need must pass asset_need_contract.validate_record(strict=True) with zero failing
tuples; an invalid need aborts the run rather than being written.

Gaps aggregated:
  * Cover replacement needs — grouped by (biome x cover_family x height_class),
    one P1 3d_mesh need per group, required_count = distinct cover anchors.
  * Visual / dressing needs per biome — sky HDRI + surface dressing + hazard
    marker, P2, derived from the biomes actually present in the pack.

Stdlib + PyYAML only. Deterministic: timestamps derive from the git sha, never
datetime.now()/random.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import asset_need_contract as NC
import asset_paths
import encounter_contract as EC
from failure_codes import FailureCode
from report_meta import build_meta, git_sha
from validation_report import ValidationReport, strict_from_env

REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_MODULE = "encounter_forge"
CREATED_BY = "analyze_asset_gaps"

# License envelope shared by every gap this stage declares (project-incorporated,
# never standalone redistribution). Kept disjoint per the contract.
ALLOWED_LICENSES = ["cc0", "fab_standard", "project_owned", "generated_owned"]
DISALLOWED_LICENSES = ["unknown", "editorial_only", "noncommercial_only"]
PACKAGE_POLICY = "project_incorporated_content_only"

# Rough max extent per height class (cm) for the physical_requirements hint.
HEIGHT_MAX_EXTENT_CM = {"low": 250, "half_height": 600, "full_height": 1200}


def _stamp():
    """Deterministic created_at — derived from the git sha, never wall-clock."""
    sha = git_sha(short=True)
    return "generated@{}".format(sha if sha and sha != "unknown" else "unstamped")


def load_pack_encounters(pack):
    """Return [(encounter_id, encounter_dict)] for every encounter in `pack`.

    Prefers the catalog (authoritative pack membership); falls back to globbing
    the generated encounters dir when the catalog is absent.
    """
    out = []
    seen = set()
    cat_path = REPO_ROOT / EC.ENCOUNTER_CATALOG_REL
    if cat_path.is_file():
        catalog = json.loads(cat_path.read_text(encoding="utf-8"))
        for eid, entry in (catalog.get("encounters") or {}).items():
            if entry.get("pack_id") != pack:
                continue
            enc, err = EC.load_encounter(eid, REPO_ROOT)
            if enc is not None:
                out.append((eid, enc))
                seen.add(eid)
    # Fallback / union: glob the encounters dir and match pack_id.
    gen_dir = REPO_ROOT / EC.ENCOUNTER_GENERATED_REL
    if gen_dir.is_dir():
        for p in sorted(gen_dir.glob("*/encounter.json")):
            eid = p.parent.name
            if eid in seen:
                continue
            try:
                enc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if enc.get("pack_id") == pack:
                out.append((eid, enc))
                seen.add(eid)
    out.sort(key=lambda t: t[0])
    return out


def _base_need(need_id, priority, asset_type, biome_tags, terrain_tags,
               encounter_tags, usage_tags, required_count, collision, material,
               preferred_sources, physical_req, visual_req, display_name,
               rationale, stamp):
    """Assemble a fully-populated AssetNeed record (all 29 required fields)."""
    return {
        "asset_need_id": need_id,
        "pack": None,  # filled by caller (kept explicit at call site)
        "source_module": SOURCE_MODULE,
        "priority": priority,
        "biome_tags": list(biome_tags),
        "terrain_tags": list(terrain_tags),
        "mission_tags": [],
        "encounter_tags": list(encounter_tags),
        "usage_tags": list(usage_tags),
        "asset_type": asset_type,
        "required_count": int(required_count),
        "current_count": 0,
        "minimum_quality_tier": "game_ready",
        "physical_requirements": dict(physical_req),
        "visual_requirements": dict(visual_req),
        "collision_required": bool(collision),
        "material_required": bool(material),
        "ue_materialization_required": True,
        "preferred_sources": list(preferred_sources),
        "allowed_license_families": list(ALLOWED_LICENSES),
        "disallowed_license_families": list(DISALLOWED_LICENSES),
        "free_ok": True,
        "paid_ok": True,
        "manual_acquisition_allowed": True,
        "download_automation_allowed": False,
        "package_policy": PACKAGE_POLICY,
        "validation_requirements": ["collision", "bounds", "material_binding"],
        "created_by": CREATED_BY,
        "created_at": stamp,
        # optional, additive
        "schema_version": NC.SCHEMA_VERSION,
        "display_name": display_name,
        "rationale": rationale,
    }


def build_cover_needs(pack, encounters, stamp):
    """One P1 3d_mesh need per (biome x cover_family x height_class) group."""
    groups = defaultdict(set)  # (biome, family, hc) -> {anchor_id}
    for eid, enc in encounters:
        biome = enc.get("biome_family")
        families = EC.BIOME_COVER_FAMILIES.get(biome, ())
        for ca in enc.get("cover_anchors") or []:
            hc = ca.get("height_class") or "half_height"
            aid = ca.get("id") or "{}:{}".format(eid, ca.get("world_position"))
            for fam in families:
                groups[(biome, fam, hc)].add(aid)

    needs = []
    for (biome, fam, hc) in sorted(groups):
        count = len(groups[(biome, fam, hc)])
        need_id = "need_{}_cover_{}_{}_{}".format(pack, biome, fam, hc)
        rec = _base_need(
            need_id=need_id,
            priority="P1",
            asset_type="3d_mesh",
            biome_tags=[biome],
            terrain_tags=["cover_anchor", "route_edge"],
            encounter_tags=["cover_replacement", fam],
            usage_tags=["encounter_cover", "v1.4x_proxy_replacement"],
            required_count=count,
            collision=True,
            material=True,
            preferred_sources=["internal_generated", "local_megascans_cache", "polyhaven"],
            physical_req={
                "height_class": hc,
                "collision": "BlockAll",
                "max_extent_cm": HEIGHT_MAX_EXTENT_CM.get(hc, 600),
            },
            visual_req={"biome_read": biome, "cover_family": fam},
            display_name="Cover mesh — {} / {} / {}".format(biome, fam, hc),
            rationale=("Replace {} v1.4x proxy cover anchors ({} / {}) in biome {} "
                       "with catalog-backed, collision-bearing meshes."
                       .format(count, fam, hc, biome)),
            stamp=stamp,
        )
        rec["pack"] = pack
        needs.append(rec)
    return needs


def build_visual_needs(pack, encounters, stamp):
    """Per-biome P2 visual/dressing needs: sky HDRI, surface dressing, hazard markers."""
    biomes = sorted({enc.get("biome_family") for _, enc in encounters
                     if enc.get("biome_family")})
    hazard_counts = defaultdict(int)
    for _, enc in encounters:
        if enc.get("hazard_zones"):
            hazard_counts[enc.get("biome_family")] += len(enc.get("hazard_zones") or [])

    needs = []
    for biome in biomes:
        # Sky HDRI — one dome per biome, no collision/material.
        hdri = _base_need(
            need_id="need_{}_hdri_{}".format(pack, biome),
            priority="P2",
            asset_type="hdri",
            biome_tags=[biome],
            terrain_tags=[],
            encounter_tags=[],
            usage_tags=["sky_dome", "biome_lighting", "environment_visual"],
            required_count=1,
            collision=False,
            material=False,
            preferred_sources=["polyhaven", "local_megascans_cache", "internal_generated"],
            physical_req={"projection": "equirectangular", "min_resolution": "4k"},
            visual_req={"biome_read": biome, "role": "sky_dome"},
            display_name="Sky HDRI — {}".format(biome),
            rationale="Biome sky/lighting dome for {} readability.".format(biome),
            stamp=stamp,
        )
        hdri["pack"] = pack
        needs.append(hdri)

        # Surface dressing — scatter meshes (no collision, material required).
        dressing = _base_need(
            need_id="need_{}_dressing_{}".format(pack, biome),
            priority="P2",
            asset_type="3d_mesh",
            biome_tags=[biome],
            terrain_tags=["ground_scatter", "route_edge"],
            encounter_tags=[],
            usage_tags=["surface_dressing", "biome_scatter", "environment_visual"],
            required_count=4,
            collision=False,
            material=True,
            preferred_sources=["internal_generated", "local_megascans_cache", "polyhaven"],
            physical_req={"placement": "scatter", "collision": "NoCollision"},
            visual_req={"biome_read": biome, "role": "surface_dressing"},
            display_name="Surface dressing set — {}".format(biome),
            rationale="Biome-appropriate ground/scatter dressing for {}.".format(biome),
            stamp=stamp,
        )
        dressing["pack"] = pack
        needs.append(dressing)

        # Hazard marker decals — count driven by hazard-zone-bearing encounters.
        marker_count = max(hazard_counts.get(biome, 0), 1)
        marker = _base_need(
            need_id="need_{}_hazard_marker_{}".format(pack, biome),
            priority="P2",
            asset_type="decal",
            biome_tags=[biome],
            terrain_tags=["hazard_zone"],
            encounter_tags=["hazard_field"],
            usage_tags=["hazard_marker", "readability", "environment_visual"],
            required_count=marker_count,
            collision=False,
            material=True,
            preferred_sources=["internal_generated", "local_megascans_cache", "polyhaven"],
            physical_req={"projection": "decal", "collision": "NoCollision"},
            visual_req={"biome_read": biome, "role": "hazard_marker"},
            display_name="Hazard marker decals — {}".format(biome),
            rationale=("Readability decals for {} hazard zones ({} marker(s))."
                       .format(biome, marker_count)),
            stamp=stamp,
        )
        marker["pack"] = pack
        needs.append(marker)
    return needs


def _clear_pack_needs(pack):
    """Remove previously-generated needs for this pack so re-runs are idempotent."""
    d = asset_paths.NEEDS_DIR
    if not d.is_dir():
        return
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(rec, dict) and rec.get("pack") == pack \
                and rec.get("created_by") == CREATED_BY:
            p.unlink()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aggregate encounter-pack asset gaps into AssetNeed records.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()
    pack = args.pack

    rep = ValidationReport("asset_gap_report", pack, strict=strict)

    encounters = load_pack_encounters(pack)
    rep.check("encounters_present", bool(encounters),
              "found {} encounter(s) for pack {}".format(len(encounters), pack),
              code=FailureCode.ASSET_NEED_ANALYSIS_FAILURE)
    if not encounters:
        rep.set_meta(build_meta(
            "analyze-asset-gaps", pack=pack, strict=strict,
            report_type="wf.asset.gap_report.v1", record_count=0,
            records_total=0, records_passed=0, records_failed=0))
        rep.finalize()
        d, fn = asset_paths.report_path("assets", "analyze_asset_gaps")
        rep.write(d, fn)
        rep.print_summary("analyze-asset-gaps")
        return rep.exit_code

    stamp = _stamp()
    needs = build_cover_needs(pack, encounters, stamp) \
        + build_visual_needs(pack, encounters, stamp)

    # Validate every need BEFORE writing anything — never emit an invalid record.
    invalid = []
    for rec in needs:
        failing = [c for c in NC.validate_record(rec, strict=True) if not c[1]]
        if failing:
            invalid.append((rec.get("asset_need_id"), failing))
    if invalid:
        for nid, failing in invalid:
            sys.stderr.write("[analyze-asset-gaps] INVALID need {}: {}\n".format(
                nid, [(c[0], c[2]) for c in failing]))
        sys.stderr.write("[analyze-asset-gaps] ABORT — {} invalid need(s); nothing written.\n"
                         .format(len(invalid)))
        return 2

    # All valid — write them.
    _clear_pack_needs(pack)
    asset_paths.ensure(asset_paths.NEEDS_DIR)
    written = []
    for rec in needs:
        path = asset_paths.NEEDS_DIR / "{}.json".format(rec["asset_need_id"])
        with path.open("w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        written.append(path)
        rep.check("need_valid::{}".format(rec["asset_need_id"]), True,
                  "asset_type={} priority={} required_count={}".format(
                      rec["asset_type"], rec["priority"], rec["required_count"]))

    rep.check("needs_produced", bool(written),
              "wrote {} AssetNeed record(s)".format(len(written)),
              code=FailureCode.ASSET_NEED_ANALYSIS_FAILURE)

    rep.set_meta(build_meta(
        "analyze-asset-gaps", pack=pack, strict=strict,
        report_type="wf.asset.gap_report.v1", record_count=len(written),
        records_total=len(written), records_passed=len(written), records_failed=0))
    rep.finalize()
    d, fn = asset_paths.report_path("assets", "analyze_asset_gaps")
    rep.write(d, fn)
    rep.print_summary("analyze-asset-gaps")
    print("[analyze-asset-gaps] {} need(s) -> {}".format(len(written), asset_paths.NEEDS_DIR))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
