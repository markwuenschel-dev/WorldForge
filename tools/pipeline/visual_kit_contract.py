#!/usr/bin/env python3
"""visual_kit_contract.py — WorldForge v1.5 VisualEnvironmentForge kit contract.

A ``VisualEnvironmentKit`` binds one biome to a complete, readable visual package:
sky/fog/lighting/atmosphere/post-process/terrain-material/decal profiles, dressing
asset sets, and the per-zone visual language (hazard / safe / danger) plus the
route-readability rules that keep gameplay legible under the chosen mood. Density
and performance budgets keep the kit inside frame cost; screenshot/validation
requirements make the kit provable.

Pure data + pure validation helper. Stdlib only.
"""

from pathlib import Path

from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# The six v1.5 biomes a visual kit may target.
BIOMES = (
    "temperate_forest",
    "alpine_snow",
    "volcanic_ashlands",
    "wetland_mire",
    "alien_crystal_badlands",
    "desert_borderlands",
)

# Profile fields that must each be a non-empty string reference.
PROFILE_FIELDS = (
    "sky_profile",
    "fog_profile",
    "lighting_profile",
    "atmosphere_profile",
    "postprocess_profile",
    "terrain_material_profile",
    "decal_profile",
)

# Budget fields that must each be a dict.
BUDGET_FIELDS = ("density_budget", "performance_budget")

# --- VisualEnvironmentKit contract --------------------------------------------
REQUIRED_FIELDS = (
    "visual_kit_id",
    "biome",
    "environment_mode",
    "sky_profile",
    "fog_profile",
    "lighting_profile",
    "atmosphere_profile",
    "postprocess_profile",
    "terrain_material_profile",
    "decal_profile",
    "dressing_asset_sets",
    "hazard_visual_language",
    "safe_zone_visual_language",
    "danger_zone_visual_language",
    "route_readability_rules",
    "density_budget",
    "performance_budget",
    "screenshot_requirements",
    "validation_requirements",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "display_name",
    "mission_tags",
    "encounter_tags",
    "provenance",
    "provenance_id",
    "notes",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def unknown_fields(record):
    return sorted(k for k in (record or {}) if k not in ALLOWED_FIELDS)


def missing_required_fields(record):
    d = record or {}
    return [k for k in REQUIRED_FIELDS if k not in d or d.get(k) in (None, "")]


def validate_record(record, strict=False):
    """Validate a VisualEnvironmentKit record.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    r = record or {}
    checks = []

    missing = missing_required_fields(r)
    checks.append((
        "required_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all required fields present",
        FailureCode.VISUAL_KIT_SCHEMA_FAILURE,
    ))

    if strict:
        unknown = unknown_fields(r)
        checks.append((
            "no_unknown_fields", not unknown,
            "unknown fields: {}".format(unknown) if unknown else "no unknown fields",
            FailureCode.VISUAL_KIT_SCHEMA_FAILURE,
        ))

    biome = r.get("biome")
    checks.append((
        "biome_in_enum", biome in BIOMES,
        "biome={!r} not in {}".format(biome, BIOMES),
        FailureCode.VISUAL_KIT_MISSING_BIOME,
    ))

    for field in PROFILE_FIELDS:
        val = r.get(field)
        ok = isinstance(val, str) and bool(val.strip())
        checks.append((
            "{}_non_empty_string".format(field), ok,
            "{} must be a non-empty string, got {!r}".format(field, val),
            FailureCode.VISUAL_KIT_CONTRACT_FAILURE,
        ))

    for field in BUDGET_FIELDS:
        val = r.get(field)
        checks.append((
            "{}_is_dict".format(field), isinstance(val, dict),
            "{} must be a dict, got {!r}".format(field, type(val).__name__),
            FailureCode.VISUAL_KIT_CONTRACT_FAILURE,
        ))

    return checks


def _example_record():
    return {
        "visual_kit_id": "vk_desert_borderlands_standard",
        "biome": "desert_borderlands",
        "environment_mode": "clear_day",
        "sky_profile": "sky_desert_clear",
        "fog_profile": "fog_desert_haze",
        "lighting_profile": "light_desert_noon",
        "atmosphere_profile": "atmo_desert_dry",
        "postprocess_profile": "pp_desert_warm",
        "terrain_material_profile": "tm_desert_cracked",
        "decal_profile": "decal_desert_tracks",
        "dressing_asset_sets": ["desert_rocks", "desert_debris"],
        "hazard_visual_language": {"marker": "red_pulse"},
        "safe_zone_visual_language": {"marker": "cool_light"},
        "danger_zone_visual_language": {"marker": "warm_haze"},
        "route_readability_rules": {"min_contrast": 0.3},
        "density_budget": {"max_instances": 5000},
        "performance_budget": {"max_draws": 3000},
        "screenshot_requirements": ["overview", "route", "hazard"],
        "validation_requirements": ["readability", "budget"],
    }


if __name__ == "__main__":
    rec = _example_record()
    results = validate_record(rec, strict=True)
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK visual_kit_contract self-check: {} checks, 0 failing "
          "(REQUIRED_FIELDS={})".format(len(results), len(REQUIRED_FIELDS)))
