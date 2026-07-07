#!/usr/bin/env python3
"""v1_5_taxonomy.py — WorldForge v1.5 central taxonomy registry (single source).

One module every v1.5 tool consults for the shared vocabularies: asset types,
usage/biome/terrain/mission/encounter tags, license families, source adapters,
ownership classes, package policies, visual profile types, and cover height
classes. Where another contract already owns an enum, this module IMPORTS it
rather than restating it, so the taxonomy can never drift from the contracts that
enforce it.

``validate_taxonomy`` is the integrity self-check: no registry may be empty and
no registry may contain duplicate values. Stdlib only.
"""

from pathlib import Path

import mesh_contract as MC
import mission_contract as MISSION
from asset_need_contract import ASSET_TYPES as _ASSET_TYPES
from failure_codes import FailureCode
from realized_cover_contract import HEIGHT_CLASSES as _HEIGHT_CLASSES
from visual_kit_contract import BIOMES as _BIOMES

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# --- imported registries (owned elsewhere) ------------------------------------
ASSET_TYPES = _ASSET_TYPES                      # asset_need_contract
BIOME_TAGS = _BIOMES                            # visual_kit_contract
OWNERSHIP_CLASSES = MC.OWNERSHIP_CLASSES        # mesh_contract
MISSION_TAGS = MISSION.MISSION_ARCHETYPES       # mission_contract
COVER_HEIGHT_CLASSES = _HEIGHT_CLASSES          # realized_cover_contract

# --- registries owned here ----------------------------------------------------
USAGE_TAGS = (
    "encounter_cover",
    "route_pressure",
    "v1.4x_proxy_replacement",
    "surface_dressing",
    "poi_dressing",
    "hazard_marker",
    "sky_hdri",
    "decal",
)

TERRAIN_TAGS = (
    "route_edge",
    "cover_anchor",
    "ridge",
    "basin",
    "flats",
)

ENCOUNTER_TAGS = (
    "ambush",
    "patrol",
    "hazard_pressure",
    "guarded_objective",
    "resource_contest",
    "defensive_holdout",
    "roaming_threat",
    "extraction_pressure",
)

LICENSE_FAMILIES = (
    "cc0",
    "fab_standard",
    "fab_professional",
    "project_owned",
    "generated_owned",
    "internal_project_license",
)

SOURCE_ADAPTERS = (
    "local_fab_megascans_cache",
    "polyhaven_direct_download",
    "manual_fab_acquisition",
    "houdini_generated",
    "internal_generated",
    "quarantine_folder",
    "existing_project_asset",
)

PACKAGE_POLICIES = (
    "project_incorporated_content_only",
    "incorporated_project_content",
    "generated_redistributable",
)

VISUAL_PROFILE_TYPES = (
    "sky",
    "fog",
    "lighting",
    "atmosphere",
    "post_process",
    "terrain_material",
    "decal",
)

# Registry-name -> tuple. The single lookup surface for is_known / validate.
REGISTRIES = {
    "ASSET_TYPES": ASSET_TYPES,
    "USAGE_TAGS": USAGE_TAGS,
    "BIOME_TAGS": BIOME_TAGS,
    "TERRAIN_TAGS": TERRAIN_TAGS,
    "MISSION_TAGS": MISSION_TAGS,
    "ENCOUNTER_TAGS": ENCOUNTER_TAGS,
    "LICENSE_FAMILIES": LICENSE_FAMILIES,
    "SOURCE_ADAPTERS": SOURCE_ADAPTERS,
    "OWNERSHIP_CLASSES": OWNERSHIP_CLASSES,
    "PACKAGE_POLICIES": PACKAGE_POLICIES,
    "VISUAL_PROFILE_TYPES": VISUAL_PROFILE_TYPES,
    "COVER_HEIGHT_CLASSES": COVER_HEIGHT_CLASSES,
}


def is_known(registry_name, value):
    """True if ``value`` is a member of the named registry (False for unknowns)."""
    return value in REGISTRIES.get(registry_name, ())


def validate_taxonomy():
    """Integrity self-check over every registry.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples: one
    non-empty check and one no-duplicates check per registry.
    """
    checks = []
    for name, values in REGISTRIES.items():
        checks.append((
            "{}_non_empty".format(name), bool(values),
            "registry {} is empty".format(name) if not values
            else "{} has {} entries".format(name, len(values)),
            FailureCode.V1_5_TAXONOMY_FAILURE,
        ))
        seen = set()
        dupes = sorted({v for v in values if v in seen or seen.add(v)})
        checks.append((
            "{}_no_duplicates".format(name), not dupes,
            "registry {} has duplicate values: {}".format(name, dupes) if dupes
            else "{} has no duplicates".format(name),
            FailureCode.V1_5_TAXONOMY_FAILURE,
        ))
    return checks


if __name__ == "__main__":
    results = validate_taxonomy()
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK v1_5_taxonomy self-check: {} checks, 0 failing "
          "({} registries)".format(len(results), len(REGISTRIES)))
