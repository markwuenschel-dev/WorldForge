#!/usr/bin/env python3
"""asset_candidate_contract.py — WorldForge v1.5 asset candidate contract.

An ``AssetCandidate`` is one discovered, ranked, possibly-acquirable source asset
that MIGHT satisfy an AssetNeed. It carries source/license/price provenance plus
quality/fit/risk scores and a lifecycle ``candidate_status``. The load-bearing
safety rule of v1.5: paid or EULA-gated candidates can never be auto-downloaded —
they MUST route through a manual acquisition action first.

Pure data + pure validation helper. Stdlib only.
"""

from pathlib import Path

from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# --- enumerations -------------------------------------------------------------
CANDIDATE_STATUSES = (
    "found",
    "ranked",
    "requires_manual_acquisition",
    "approved_for_download",
    "downloaded_to_quarantine",
    "rejected",
    "approved_for_catalog",
    "cataloged",
    "materialized",
)

PRICE_CLASSES = ("free", "paid", "unknown")

# --- AssetCandidate contract --------------------------------------------------
REQUIRED_FIELDS = (
    "candidate_id",
    "asset_need_id",
    "source_adapter",
    "source_type",
    "source_url",
    "source_path",
    "display_name",
    "publisher",
    "author",
    "license_family",
    "license_url",
    "license_text_snapshot_path",
    "price_class",
    "eula_required",
    "manual_acquisition_required",
    "download_automation_allowed",
    "hash_expected",
    "file_type",
    "asset_type",
    "quality_score",
    "fit_score",
    "risk_score",
    "candidate_status",
    "rejection_reason",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "tags",
    "preview_url",
    "provenance",
    "provenance_id",
    "ranked_at",
    "notes",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def unknown_fields(record):
    return sorted(k for k in (record or {}) if k not in ALLOWED_FIELDS)


def missing_required_fields(record):
    # Key-presence only: source_url / source_path / rejection_reason are legally
    # empty depending on state (one source reference may be blank; a non-rejected
    # candidate has no rejection reason). Value-level rules are checked below.
    d = record or {}
    return [k for k in REQUIRED_FIELDS if k not in d]


def validate_record(record, strict=False):
    """Validate an AssetCandidate record.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    r = record or {}
    checks = []

    missing = missing_required_fields(r)
    checks.append((
        "required_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all required fields present",
        FailureCode.ASSET_CANDIDATE_SCHEMA_FAILURE,
    ))

    if strict:
        unknown = unknown_fields(r)
        checks.append((
            "no_unknown_fields", not unknown,
            "unknown fields: {}".format(unknown) if unknown else "no unknown fields",
            FailureCode.ASSET_CANDIDATE_SCHEMA_FAILURE,
        ))

    status = r.get("candidate_status")
    checks.append((
        "candidate_status_in_enum", status in CANDIDATE_STATUSES,
        "candidate_status={!r} not in {}".format(status, CANDIDATE_STATUSES),
        FailureCode.ASSET_CANDIDATE_SCHEMA_FAILURE,
    ))

    price = r.get("price_class")
    checks.append((
        "price_class_in_enum", price in PRICE_CLASSES,
        "price_class={!r} not in {}".format(price, PRICE_CLASSES),
        FailureCode.ASSET_CANDIDATE_SCHEMA_FAILURE,
    ))

    manual = bool(r.get("manual_acquisition_required"))

    # Paid content must be gated behind a manual acquisition action.
    paid_ok = (price != "paid") or manual
    checks.append((
        "paid_requires_manual_acquisition", paid_ok,
        "price_class=paid requires manual_acquisition_required=True",
        FailureCode.ASSET_PURCHASE_REQUIRED_MANUAL_ACTION,
    ))

    # EULA-gated content must be gated behind a manual acquisition action.
    eula_ok = (not r.get("eula_required")) or manual
    checks.append((
        "eula_requires_manual_acquisition", eula_ok,
        "eula_required requires manual_acquisition_required=True",
        FailureCode.ASSET_EULA_REQUIRED_MANUAL_ACTION,
    ))

    # A candidate must carry at least one usable source reference.
    has_url = bool((r.get("source_url") or "").strip()) if isinstance(
        r.get("source_url"), str) else bool(r.get("source_url"))
    has_path = bool((r.get("source_path") or "").strip()) if isinstance(
        r.get("source_path"), str) else bool(r.get("source_path"))
    checks.append((
        "source_url_or_path_present", has_url or has_path,
        "neither source_url nor source_path present"
        if not (has_url or has_path) else "source reference present",
        FailureCode.ASSET_SOURCE_URL_MISSING if not has_url
        else FailureCode.ASSET_SOURCE_PATH_MISSING,
    ))

    return checks


def _example_record():
    return {
        "candidate_id": "cand_polyhaven_desert_rock_01",
        "asset_need_id": "need_desert_cover_low_rock",
        "source_adapter": "polyhaven_direct_download",
        "source_type": "polyhaven",
        "source_url": "https://polyhaven.com/a/desert_rock_01",
        "source_path": "",
        "display_name": "Desert Rock 01",
        "publisher": "Poly Haven",
        "author": "Poly Haven",
        "license_family": "cc0",
        "license_url": "https://polyhaven.com/license",
        "license_text_snapshot_path": "WorldForgeAssetCache/_Quarantine/cand/license.txt",
        "price_class": "free",
        "eula_required": False,
        "manual_acquisition_required": False,
        "download_automation_allowed": True,
        "hash_expected": "sha256:deadbeef",
        "file_type": "fbx",
        "asset_type": "3d_mesh",
        "quality_score": 0.82,
        "fit_score": 0.9,
        "risk_score": 0.05,
        "candidate_status": "ranked",
        "rejection_reason": "",
    }


if __name__ == "__main__":
    rec = _example_record()
    results = validate_record(rec, strict=True)
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK asset_candidate_contract self-check: {} checks, 0 failing "
          "(REQUIRED_FIELDS={})".format(len(results), len(REQUIRED_FIELDS)))
