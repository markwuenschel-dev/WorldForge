#!/usr/bin/env python3
"""asset_catalog_contract.py — WorldForge v1.5 acquired-asset catalog contract.

An ``AssetCatalogRecord`` is the durable, approved, provenance-proven inventory
entry an acquired asset earns after it clears quarantine. It is the v1.5 sibling
of the v1.2 external asset catalog and the generated mesh catalog: it carries the
ownership class, license family/snapshot, UE realization state, tag taxonomy, and
— critically — a ``lifecycle_policy`` that keeps third-party / human-owned source
content repair/destroy PROTECTED.

License families are imported from ``external_asset_contract`` and ownership
resolution from ``mesh_contract`` — never redefined here. Stdlib only.
"""

from pathlib import Path

import mesh_contract as MC
from external_asset_contract import LICENSE_FAMILIES as EXTERNAL_LICENSE_FAMILIES
from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# Ownership classes whose SOURCE content lifecycle may never touch (mirrors the
# v1.2 addendum protection rule). Repair/destroy must be denied in lifecycle_policy.
LIFECYCLE_PROTECTED_OWNERSHIP = MC.OWNERSHIP_LIFECYCLE_PROTECTED
LIFECYCLE_POLICY_KEYS = ("repair_allowed", "destroy_allowed")

# --- AssetCatalogRecord contract ----------------------------------------------
REQUIRED_FIELDS = (
    "asset_id",
    "source_type",
    "source_adapter",
    "source_url",
    "source_path",
    "source_hash",
    "license_family",
    "license_url",
    "license_snapshot",
    "ownership_class",
    "external_licensed",
    "generated_owned",
    "third_party_owned",
    "human_owned",
    "project_owned",
    "publisher",
    "author",
    "downloaded_at",
    "approved_at",
    "cataloged_at",
    "import_status",
    "ue_asset_path",
    "ue_dependencies",
    "package_policy",
    "biome_tags",
    "terrain_tags",
    "mission_tags",
    "encounter_tags",
    "usage_tags",
    "validation_status",
    "materialization_status",
    "lifecycle_policy",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "display_name",
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
    return [k for k in REQUIRED_FIELDS if k not in d]


def is_lifecycle_protected(lifecycle_policy):
    """True if a lifecycle_policy dict denies both repair and destroy."""
    lp = lifecycle_policy
    if not isinstance(lp, dict):
        return False
    return not lp.get("repair_allowed") and not lp.get("destroy_allowed")


def validate_record(record, strict=False):
    """Validate an AssetCatalogRecord for ownership/license/lifecycle coherence.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    r = record or {}
    checks = []

    missing = missing_required_fields(r)
    checks.append((
        "required_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all required fields present",
        FailureCode.ASSET_CATALOG_FAILURE,
    ))

    if strict:
        unknown = unknown_fields(r)
        checks.append((
            "no_unknown_fields", not unknown,
            "unknown fields: {}".format(unknown) if unknown else "no unknown fields",
            FailureCode.ASSET_CATALOG_FAILURE,
        ))

    ownership = MC.resolve_ownership_class(r)
    checks.append((
        "ownership_class_resolves", ownership is not None,
        "ownership ambiguous/unresolvable" if ownership is None
        else "ownership resolves to {}".format(ownership),
        FailureCode.ASSET_OWNERSHIP_FAILURE,
    ))

    # Third-party owned content must be externally licensed.
    if r.get("third_party_owned"):
        checks.append((
            "third_party_external_licensed", bool(r.get("external_licensed")),
            "third_party_owned asset must have external_licensed=True",
            FailureCode.ASSET_OWNERSHIP_FAILURE,
        ))

    # Protected ownership classes must be repair/destroy protected.
    if ownership in LIFECYCLE_PROTECTED_OWNERSHIP:
        checks.append((
            "protected_lifecycle_policy", is_lifecycle_protected(r.get("lifecycle_policy")),
            "ownership={} requires lifecycle_policy denying repair+destroy".format(ownership),
            FailureCode.ASSET_OWNERSHIP_FAILURE,
        ))

    return checks


def _example_record():
    return {
        "asset_id": "cat_fab_rock_pack_01",
        "source_type": "megascans_library",
        "source_adapter": "manual_fab_acquisition",
        "source_url": "https://fab.com/listings/rock_pack_01",
        "source_path": "WorldForgeAssetCache/_Quarantine/fab_rock_pack_01",
        "source_hash": "sha256:deadbeef",
        "license_family": EXTERNAL_LICENSE_FAMILIES[0],
        "license_url": "https://fab.com/eula",
        "license_snapshot": "WorldForgeAssetCache/_Quarantine/fab_rock_pack_01/license.txt",
        "ownership_class": MC.OWNERSHIP_THIRD_PARTY,
        "external_licensed": True,
        "generated_owned": False,
        "third_party_owned": True,
        "human_owned": False,
        "project_owned": False,
        "publisher": "SomeVendor",
        "author": "SomeVendor",
        "downloaded_at": "2026-07-06T00:00:00+00:00",
        "approved_at": "2026-07-06T00:00:00+00:00",
        "cataloged_at": "2026-07-06T00:00:00+00:00",
        "import_status": "imported",
        "ue_asset_path": "/Game/WorldForge/ThirdParty/Meshes/Rock01",
        "ue_dependencies": ["/Game/WorldForge/ThirdParty/Materials/MI_Rock01"],
        "package_policy": "incorporated_project_content",
        "biome_tags": ["desert_borderlands"],
        "terrain_tags": ["cover_anchor"],
        "mission_tags": ["guarded_objective"],
        "encounter_tags": ["ambush"],
        "usage_tags": ["encounter_cover"],
        "validation_status": "passed",
        "materialization_status": "materialized",
        "lifecycle_policy": {"repair_allowed": False, "destroy_allowed": False},
    }


if __name__ == "__main__":
    rec = _example_record()
    results = validate_record(rec, strict=True)
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK asset_catalog_contract self-check: {} checks, 0 failing "
          "(REQUIRED_FIELDS={})".format(len(results), len(REQUIRED_FIELDS)))
