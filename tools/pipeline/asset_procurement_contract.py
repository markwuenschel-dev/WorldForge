#!/usr/bin/env python3
"""asset_procurement_contract.py — WorldForge v1.5 procurement manifest contract.

The ``AssetProcurementManifest`` is the aggregation of many AssetNeed records
into a single pack-scoped shopping/policy document: what to acquire, under which
source/approval/quarantine/package/manual/download policies, and the validation
requirements every acquired asset must clear. It is pure data — it decides
nothing about a specific candidate; it declares the policy envelope the candidate
pipeline must honour.

Mirrors the houdini_contract ``*_mode_from_env`` convention with
``download_mode_from_env`` so the download policy resolves from a single env flag.
Stdlib only.
"""

from pathlib import Path

from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# --- download automation modes (mirror houdini_contract.houdini_mode_from_env) -
DOWNLOAD_MODE_AUTOMATED = "automated"        # permissive direct downloads allowed
DOWNLOAD_MODE_MANUAL_ONLY = "manual_only"    # every acquisition needs manual action
DOWNLOAD_MODES = (DOWNLOAD_MODE_AUTOMATED, DOWNLOAD_MODE_MANUAL_ONLY)

# --- AssetProcurementManifest contract ----------------------------------------
REQUIRED_FIELDS = (
    "manifest_id",
    "pack",
    "generated_at",
    "asset_needs",
    "source_policy",
    "approval_policy",
    "quarantine_policy",
    "package_policy",
    "manual_acquisition_policy",
    "download_policy",
    "validation_requirements",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "display_name",
    "provenance",
    "provenance_id",
    "notes",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

# Each item inside ``asset_needs`` is a resolved, policy-bound need line.
MANIFEST_ITEM_REQUIRED = (
    "asset_need_id",
    "priority",
    "asset_type",
    "minimum_count",
    "preferred_sources",
    "allowed_license_families",
    "paid_ok",
    "free_ok",
    "manual_acquisition_required",
    "download_automation_allowed",
    "ue_materialization_required",
    "package_policy",
)


def unknown_fields(record):
    return sorted(k for k in (record or {}) if k not in ALLOWED_FIELDS)


def missing_required_fields(record):
    d = record or {}
    return [k for k in REQUIRED_FIELDS if k not in d or d.get(k) in (None, "")]


def download_mode_from_env():
    """Resolve the DOWNLOAD flag: '1'/'auto'/'automated' -> automated downloads;
    'manual'/'manual_only' -> manual-only; anything falsy -> None (unset)."""
    import os
    val = (os.environ.get("DOWNLOAD") or "").strip().lower()
    if val in ("1", "true", "yes", "on", "auto", "automated"):
        return DOWNLOAD_MODE_AUTOMATED
    if val in ("manual", "manual_only", "manualonly"):
        return DOWNLOAD_MODE_MANUAL_ONLY
    return None


def validate_manifest_item(item, strict=False):
    """Validate one line inside ``asset_needs``.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    it = item or {}
    checks = []

    missing = [k for k in MANIFEST_ITEM_REQUIRED if k not in it or it.get(k) in (None, "")]
    checks.append((
        "manifest_item_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all manifest item fields present",
        FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
    ))

    mc = it.get("minimum_count")
    mc_ok = isinstance(mc, int) and not isinstance(mc, bool) and mc >= 0
    checks.append((
        "minimum_count_non_negative_int", mc_ok,
        "minimum_count={!r} must be int >= 0".format(mc),
        FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
    ))

    sources = it.get("preferred_sources")
    checks.append((
        "preferred_sources_is_list", isinstance(sources, list),
        "preferred_sources must be a list, got {!r}".format(type(sources).__name__),
        FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
    ))

    families = it.get("allowed_license_families")
    checks.append((
        "allowed_license_families_is_list", isinstance(families, list),
        "allowed_license_families must be a list, got {!r}".format(type(families).__name__),
        FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
    ))

    # Paid items may never be automation-downloaded without manual acquisition.
    if it.get("paid_ok") and it.get("download_automation_allowed") \
            and not it.get("manual_acquisition_required"):
        checks.append((
            "paid_item_requires_manual_acquisition", False,
            "paid_ok item allows download automation without manual acquisition",
            FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
        ))
    else:
        checks.append((
            "paid_item_requires_manual_acquisition", True,
            "paid/automation policy coherent",
            FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
        ))

    return checks


def validate_record(record, strict=False):
    """Validate an AssetProcurementManifest record (and each nested item).

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    r = record or {}
    checks = []

    missing = missing_required_fields(r)
    checks.append((
        "required_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all required fields present",
        FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
    ))

    if strict:
        unknown = unknown_fields(r)
        checks.append((
            "no_unknown_fields", not unknown,
            "unknown fields: {}".format(unknown) if unknown else "no unknown fields",
            FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
        ))

    needs = r.get("asset_needs")
    checks.append((
        "asset_needs_is_list", isinstance(needs, list),
        "asset_needs must be a list, got {!r}".format(type(needs).__name__),
        FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE,
    ))

    for i, item in enumerate(needs if isinstance(needs, list) else []):
        for name, ok, detail, code in validate_manifest_item(item, strict=strict):
            checks.append(("asset_needs[{}].{}".format(i, name), ok, detail, code))

    return checks


def _example_item():
    return {
        "asset_need_id": "need_desert_cover_low_rock",
        "priority": "P1",
        "asset_type": "3d_mesh",
        "minimum_count": 4,
        "preferred_sources": ["local_fab_megascans_cache"],
        "allowed_license_families": ["cc0", "fab_standard"],
        "paid_ok": False,
        "free_ok": True,
        "manual_acquisition_required": False,
        "download_automation_allowed": True,
        "ue_materialization_required": True,
        "package_policy": "project_incorporated_content_only",
    }


def _example_record():
    return {
        "manifest_id": "manifest_desert_mvp_world",
        "pack": "desert_mvp_world",
        "generated_at": "2026-07-06T00:00:00+00:00",
        "asset_needs": [_example_item()],
        "source_policy": {"adapters": ["local_fab_megascans_cache"]},
        "approval_policy": {"unknown_license": "reject"},
        "quarantine_policy": {"root": "WorldForgeAssetCache/_Quarantine"},
        "package_policy": "project_incorporated_content_only",
        "manual_acquisition_policy": {"paid": "manual_only"},
        "download_policy": {"mode": DOWNLOAD_MODE_AUTOMATED},
        "validation_requirements": ["collision", "bounds", "material_binding"],
    }


if __name__ == "__main__":
    rec = _example_record()
    results = validate_record(rec, strict=True)
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK asset_procurement_contract self-check: {} checks, 0 failing "
          "(REQUIRED_FIELDS={})".format(len(results), len(REQUIRED_FIELDS)))
