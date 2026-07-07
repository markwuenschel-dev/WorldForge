#!/usr/bin/env python3
"""asset_need_contract.py — WorldForge v1.5 AssetAcquisitionForge need contract.

Single source of truth for the ``AssetNeed`` record: a declared content gap a
source module (biome/terrain/mission/encounter/visual) needs filled before it
can materialize. A need is pure intent — it names what is required, at what
quality, under which license/source/package constraints — and NEVER performs
acquisition. Needs are aggregated into an AssetProcurementManifest downstream.

Dependency-light (stdlib only). Ownership constants and license families are
imported from the v1.2 contracts, never redefined, so the four ownership classes
and the external license taxonomy stay single-sourced across the pipeline.
"""

from pathlib import Path

from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# --- enumerations -------------------------------------------------------------
PRIORITIES = ("P0", "P1", "P2", "P3")
ASSET_TYPES = ("3d_mesh", "material", "texture", "hdri", "decal", "vfx", "audio")
QUALITY_TIERS = ("proxy", "game_ready", "hero")

# Tag fields that must be declared as lists (never a bare string).
TAG_LIST_FIELDS = (
    "biome_tags", "terrain_tags", "mission_tags", "encounter_tags", "usage_tags",
)

# --- AssetNeed contract -------------------------------------------------------
REQUIRED_FIELDS = (
    "asset_need_id",
    "pack",
    "source_module",
    "priority",
    "biome_tags",
    "terrain_tags",
    "mission_tags",
    "encounter_tags",
    "usage_tags",
    "asset_type",
    "required_count",
    "current_count",
    "minimum_quality_tier",
    "physical_requirements",
    "visual_requirements",
    "collision_required",
    "material_required",
    "ue_materialization_required",
    "preferred_sources",
    "allowed_license_families",
    "disallowed_license_families",
    "free_ok",
    "paid_ok",
    "manual_acquisition_allowed",
    "download_automation_allowed",
    "package_policy",
    "validation_requirements",
    "created_by",
    "created_at",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "display_name",
    "rationale",
    "provenance",
    "provenance_id",
    "updated_at",
    "notes",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def unknown_fields(record):
    return sorted(k for k in (record or {}) if k not in ALLOWED_FIELDS)


def missing_required_fields(record):
    d = record or {}
    return [k for k in REQUIRED_FIELDS if k not in d or d.get(k) in (None, "")]


def validate_record(record, strict=False):
    """Validate an AssetNeed record.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples. This is
    intentionally NOT a ValidationReport — the v1.5 validator scripts consume
    these tuples and feed their own report, keeping the contract dependency-light
    and unit-testable.
    """
    r = record or {}
    checks = []

    missing = missing_required_fields(r)
    checks.append((
        "required_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all required fields present",
        FailureCode.ASSET_NEED_SCHEMA_FAILURE,
    ))

    if strict:
        unknown = unknown_fields(r)
        checks.append((
            "no_unknown_fields", not unknown,
            "unknown fields: {}".format(unknown) if unknown else "no unknown fields",
            FailureCode.ASSET_NEED_SCHEMA_FAILURE,
        ))

    priority = r.get("priority")
    checks.append((
        "priority_in_enum", priority in PRIORITIES,
        "priority={!r} not in {}".format(priority, PRIORITIES),
        FailureCode.ASSET_NEED_SCHEMA_FAILURE,
    ))

    asset_type = r.get("asset_type")
    checks.append((
        "asset_type_in_enum", asset_type in ASSET_TYPES,
        "asset_type={!r} not in {}".format(asset_type, ASSET_TYPES),
        FailureCode.ASSET_NEED_SCHEMA_FAILURE,
    ))

    tier = r.get("minimum_quality_tier")
    checks.append((
        "minimum_quality_tier_in_enum", tier in QUALITY_TIERS,
        "minimum_quality_tier={!r} not in {}".format(tier, QUALITY_TIERS),
        FailureCode.ASSET_NEED_SCHEMA_FAILURE,
    ))

    rc = r.get("required_count")
    rc_ok = isinstance(rc, int) and not isinstance(rc, bool) and rc >= 0
    checks.append((
        "required_count_non_negative_int", rc_ok,
        "required_count={!r} must be int >= 0".format(rc),
        FailureCode.ASSET_NEED_SCHEMA_FAILURE,
    ))

    for field in TAG_LIST_FIELDS:
        val = r.get(field)
        checks.append((
            "{}_is_list".format(field), isinstance(val, list),
            "{} must be a list, got {!r}".format(field, type(val).__name__),
            FailureCode.ASSET_NEED_SCHEMA_FAILURE,
        ))

    allowed = set(r.get("allowed_license_families") or [])
    disallowed = set(r.get("disallowed_license_families") or [])
    overlap = sorted(allowed & disallowed)
    checks.append((
        "license_families_disjoint", not overlap,
        "allowed/disallowed license families overlap: {}".format(overlap)
        if overlap else "license family lists disjoint",
        FailureCode.ASSET_NEED_SCHEMA_FAILURE,
    ))

    return checks


def _example_record():
    return {
        "asset_need_id": "need_desert_cover_low_rock",
        "pack": "desert_mvp_world",
        "source_module": "encounter_forge",
        "priority": "P1",
        "biome_tags": ["desert_borderlands"],
        "terrain_tags": ["cover_anchor", "route_edge"],
        "mission_tags": ["guarded_objective"],
        "encounter_tags": ["ambush"],
        "usage_tags": ["encounter_cover", "v1.4x_proxy_replacement"],
        "asset_type": "3d_mesh",
        "required_count": 4,
        "current_count": 0,
        "minimum_quality_tier": "game_ready",
        "physical_requirements": {"max_extent_cm": 600, "collision": "BlockAll"},
        "visual_requirements": {"biome_read": "desert"},
        "collision_required": True,
        "material_required": True,
        "ue_materialization_required": True,
        "preferred_sources": ["local_fab_megascans_cache", "polyhaven_direct_download"],
        "allowed_license_families": ["cc0", "fab_standard"],
        "disallowed_license_families": ["unknown"],
        "free_ok": True,
        "paid_ok": False,
        "manual_acquisition_allowed": True,
        "download_automation_allowed": True,
        "package_policy": "project_incorporated_content_only",
        "validation_requirements": ["collision", "bounds", "material_binding"],
        "created_by": "asset_need_forge",
        "created_at": "2026-07-06T00:00:00+00:00",
    }


if __name__ == "__main__":
    rec = _example_record()
    results = validate_record(rec, strict=True)
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK asset_need_contract self-check: {} checks, 0 failing "
          "(REQUIRED_FIELDS={})".format(len(results), len(REQUIRED_FIELDS)))
