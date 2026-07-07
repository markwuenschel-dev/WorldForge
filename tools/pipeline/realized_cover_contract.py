#!/usr/bin/env python3
"""realized_cover_contract.py — WorldForge v1.5 realized cover binding contract.

A ``RealizedCoverBinding`` records the replacement of a v1.4x cube cover proxy
with a real catalog-backed mesh at a fixed cover anchor. The binding proves the
swap kept cover semantics intact: the anchor did not move, the mesh blocks
(collision BlockAll), routes stayed clear, line-of-sight still works, and the
material + package policy checks passed. This is the audit record the cover
proxy-replacement validator consumes.

Ownership classes are imported from ``mesh_contract``. Height classes align with
the v1.5 cover taxonomy. Stdlib only.
"""

from pathlib import Path

import mesh_contract as MC
from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# Cover height classes (v1.5 cover taxonomy). Distinct from the mesh_contract
# geometry vocabulary ("low"/"half"/"full"); realized cover uses the explicit
# gameplay-facing names.
HEIGHT_CLASSES = ("low", "half_height", "full_height")

# The only collision profile a realized cover mesh may carry — it must block.
REQUIRED_COLLISION_PROFILE = "BlockAll"

# Result sub-dicts that must be truthy dicts carrying a boolean "passed".
RESULT_FIELDS = ("route_clearance_result", "line_of_sight_result")

# --- RealizedCoverBinding contract --------------------------------------------
REQUIRED_FIELDS = (
    "binding_id",
    "encounter_id",
    "mission_id",
    "map_id",
    "original_proxy_actor_label",
    "cover_anchor_id",
    "replacement_asset_id",
    "ue_asset_path",
    "ownership_class",
    "collision_profile",
    "bounds",
    "height_class",
    "route_clearance_result",
    "line_of_sight_result",
    "material_result",
    "package_policy_result",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "provenance",
    "provenance_id",
    "realized_at",
    "notes",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def unknown_fields(record):
    return sorted(k for k in (record or {}) if k not in ALLOWED_FIELDS)


def missing_required_fields(record):
    d = record or {}
    return [k for k in REQUIRED_FIELDS if k not in d or d.get(k) in (None, "")]


def _result_ok(result):
    return isinstance(result, dict) and bool(result) \
        and isinstance(result.get("passed"), bool)


def validate_record(record, strict=False):
    """Validate a RealizedCoverBinding record.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    r = record or {}
    checks = []

    missing = missing_required_fields(r)
    checks.append((
        "required_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all required fields present",
        FailureCode.COVER_BINDING_SCHEMA_FAILURE,
    ))

    if strict:
        unknown = unknown_fields(r)
        checks.append((
            "no_unknown_fields", not unknown,
            "unknown fields: {}".format(unknown) if unknown else "no unknown fields",
            FailureCode.COVER_BINDING_SCHEMA_FAILURE,
        ))

    ownership = r.get("ownership_class")
    checks.append((
        "ownership_class_in_enum", ownership in MC.OWNERSHIP_CLASSES,
        "ownership_class={!r} not in {}".format(ownership, MC.OWNERSHIP_CLASSES),
        FailureCode.ASSET_OWNERSHIP_FAILURE,
    ))

    collision = r.get("collision_profile")
    checks.append((
        "collision_profile_block_all", collision == REQUIRED_COLLISION_PROFILE,
        "collision_profile={!r} must be {!r}".format(collision, REQUIRED_COLLISION_PROFILE),
        FailureCode.COVER_REPLACEMENT_COLLISION_INVALID,
    ))

    height = r.get("height_class")
    checks.append((
        "height_class_in_enum", height in HEIGHT_CLASSES,
        "height_class={!r} not in {}".format(height, HEIGHT_CLASSES),
        FailureCode.COVER_REPLACEMENT_HEIGHT_CLASS_MISMATCH,
    ))

    for field in RESULT_FIELDS:
        checks.append((
            "{}_passed_boolean".format(field), _result_ok(r.get(field)),
            "{} must be a non-empty dict with a boolean 'passed'".format(field),
            FailureCode.REALIZED_COVER_BINDING_FAILURE,
        ))

    return checks


def _example_record():
    return {
        "binding_id": "rcb_enc001_cover_03",
        "encounter_id": "enc_desert_guarded_objective_s1",
        "mission_id": "mis_desert_guarded_objective_s1",
        "map_id": "_wf_test_lvl",
        "original_proxy_actor_label": "WF_CoverProxy_03",
        "cover_anchor_id": "cover_anchor_03",
        "replacement_asset_id": "cat_low_rock_cover_01",
        "ue_asset_path": "/Game/WorldForge/Generated/Meshes/LowRockCover01",
        "ownership_class": MC.OWNERSHIP_GENERATED,
        "collision_profile": "BlockAll",
        "bounds": {"x_cm": 120.0, "y_cm": 90.0, "z_cm": 80.0},
        "height_class": "half_height",
        "route_clearance_result": {"passed": True, "min_clearance_cm": 620.0},
        "line_of_sight_result": {"passed": True, "blocked_pct": 0.4},
        "material_result": {"passed": True},
        "package_policy_result": {"passed": True},
    }


if __name__ == "__main__":
    rec = _example_record()
    results = validate_record(rec, strict=True)
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK realized_cover_contract self-check: {} checks, 0 failing "
          "(REQUIRED_FIELDS={})".format(len(results), len(REQUIRED_FIELDS)))
