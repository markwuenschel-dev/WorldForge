#!/usr/bin/env python3
"""asset_approval_contract.py — WorldForge v1.5 asset approval contract.

An ``AssetApprovalRecord`` is the human/gate decision that a candidate may proceed
to download/quarantine/catalog. It is the audit trail for the two most dangerous
actions v1.5 guards: accepting a EULA and completing a purchase. Those can only
be recorded by a real user marker (``eula_accepted_by_user`` /
``purchase_completed_by_user``) — the pipeline can never self-approve them.

Third-party approvals may NEVER grant standalone redistribution rights; that is a
project_owned / generated_owned privilege only. Pure data + pure validation
helper, stdlib only.
"""

from pathlib import Path

from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# --- enumerations -------------------------------------------------------------
APPROVAL_TYPES = (
    "direct_download_permissive",
    "manual_marketplace_acquisition",
    "local_cache_detected",
    "internal_generated",
    "project_owned_existing",
)

# Approval types that acquire externally-owned content. These may never grant
# standalone redistribution — only the owned types below may.
THIRD_PARTY_APPROVAL_TYPES = (
    "direct_download_permissive",
    "manual_marketplace_acquisition",
    "local_cache_detected",
)
OWNED_APPROVAL_TYPES = (
    "internal_generated",
    "project_owned_existing",
)

# Approval types that require a completed manual acquisition action + approver.
MANUAL_ACTION_APPROVAL_TYPES = ("manual_marketplace_acquisition",)

# --- AssetApprovalRecord contract ---------------------------------------------
REQUIRED_FIELDS = (
    "approval_id",
    "candidate_id",
    "asset_need_id",
    "approved_by",
    "approval_type",
    "approval_scope",
    "allowed_usage",
    "standalone_redistribution_allowed",
    "manual_action_completed",
    "eula_accepted_by_user",
    "purchase_completed_by_user",
    "approved_at",
    "notes",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "provenance",
    "provenance_id",
    "expires_at",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

# Declarative catalogue of invalid approval states (for validators + fixtures).
# Each rule: which approval types it applies to, and the code emitted when the
# invalid state is detected.
INVALID_APPROVAL_RULES = (
    {
        "rule_id": "third_party_standalone_redistribution",
        "approval_types": THIRD_PARTY_APPROVAL_TYPES,
        "failure_code": FailureCode.ASSET_STANDALONE_REDISTRIBUTION_FORBIDDEN,
        "detail": "third-party approval must not allow standalone redistribution",
    },
    {
        "rule_id": "manual_marketplace_missing_action",
        "approval_types": MANUAL_ACTION_APPROVAL_TYPES,
        "failure_code": FailureCode.ASSET_MANUAL_APPROVAL_MISSING,
        "detail": "manual_marketplace_acquisition requires manual_action_completed + approved_by",
    },
    {
        "rule_id": "manual_marketplace_user_markers",
        "approval_types": MANUAL_ACTION_APPROVAL_TYPES,
        "failure_code": FailureCode.ASSET_MANUAL_APPROVAL_MISSING,
        "detail": "manual_marketplace_acquisition requires eula_accepted_by_user "
                  "and purchase_completed_by_user markers set by a real user",
    },
)


def unknown_fields(record):
    return sorted(k for k in (record or {}) if k not in ALLOWED_FIELDS)


def missing_required_fields(record):
    # Key-presence only: notes / scope may be empty; boolean markers may be False.
    d = record or {}
    return [k for k in REQUIRED_FIELDS if k not in d]


def validate_record(record, strict=False):
    """Validate an AssetApprovalRecord.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    r = record or {}
    checks = []

    missing = missing_required_fields(r)
    checks.append((
        "required_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all required fields present",
        FailureCode.ASSET_APPROVAL_STATE_FAILURE,
    ))

    if strict:
        unknown = unknown_fields(r)
        checks.append((
            "no_unknown_fields", not unknown,
            "unknown fields: {}".format(unknown) if unknown else "no unknown fields",
            FailureCode.ASSET_APPROVAL_STATE_FAILURE,
        ))

    approval_type = r.get("approval_type")
    checks.append((
        "approval_type_in_enum", approval_type in APPROVAL_TYPES,
        "approval_type={!r} not in {}".format(approval_type, APPROVAL_TYPES),
        FailureCode.ASSET_APPROVAL_STATE_FAILURE,
    ))

    # Third-party approvals may never allow standalone redistribution.
    if approval_type in THIRD_PARTY_APPROVAL_TYPES:
        redistrib_ok = not r.get("standalone_redistribution_allowed")
        checks.append((
            "third_party_no_standalone_redistribution", redistrib_ok,
            "third-party approval_type={!r} must not allow standalone redistribution"
            .format(approval_type),
            FailureCode.ASSET_STANDALONE_REDISTRIBUTION_FORBIDDEN,
        ))

    # Manual marketplace acquisition requires completed action + a named approver.
    if approval_type in MANUAL_ACTION_APPROVAL_TYPES:
        action_ok = bool(r.get("manual_action_completed")) and bool(r.get("approved_by"))
        checks.append((
            "manual_marketplace_action_completed", action_ok,
            "manual_marketplace_acquisition requires manual_action_completed=True and approved_by set",
            FailureCode.ASSET_MANUAL_APPROVAL_MISSING,
        ))
        # A marketplace acquisition claims purchase + EULA completion; the
        # matching real-user markers must both be set.
        markers_ok = bool(r.get("eula_accepted_by_user")) and \
            bool(r.get("purchase_completed_by_user"))
        checks.append((
            "manual_marketplace_user_markers", markers_ok,
            "manual_marketplace_acquisition requires eula_accepted_by_user and "
            "purchase_completed_by_user markers True",
            FailureCode.ASSET_MANUAL_APPROVAL_MISSING,
        ))

    return checks


def _example_record():
    return {
        "approval_id": "appr_fab_rock_pack_01",
        "candidate_id": "cand_fab_rock_pack_01",
        "asset_need_id": "need_desert_cover_low_rock",
        "approved_by": "maw271190",
        "approval_type": "manual_marketplace_acquisition",
        "approval_scope": "project_incorporated_content_only",
        "allowed_usage": ["encounter_cover", "surface_dressing"],
        "standalone_redistribution_allowed": False,
        "manual_action_completed": True,
        "eula_accepted_by_user": True,
        "purchase_completed_by_user": True,
        "approved_at": "2026-07-06T00:00:00+00:00",
        "notes": "acquired via Fab, incorporated content only",
    }


if __name__ == "__main__":
    rec = _example_record()
    results = validate_record(rec, strict=True)
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK asset_approval_contract self-check: {} checks, 0 failing "
          "(REQUIRED_FIELDS={})".format(len(results), len(REQUIRED_FIELDS)))
