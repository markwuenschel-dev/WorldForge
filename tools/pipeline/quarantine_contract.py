#!/usr/bin/env python3
"""quarantine_contract.py — WorldForge v1.5 quarantine record contract.

A ``QuarantineAssetRecord`` describes an acquired asset that has landed in the
quarantine holding area but has NOT yet been catalogued or materialized. Nothing
leaves quarantine without a content hash, a resolvable ownership class, and a
path that is genuinely under a quarantine root — the three guards that stop a
raw third-party download from masquerading as owned, catalogued content.

Ownership resolution is delegated to ``mesh_contract.resolve_ownership_class`` so
the four ownership classes are single-sourced. Stdlib only.
"""

from pathlib import Path

import mesh_contract as MC
from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.5"

# Relative anchors a quarantine path must sit under. Never a final/owned root.
QUARANTINE_ROOTS = (
    "WorldForgeAssetCache/_Quarantine",
    "Content/WorldForge/_Quarantine",
)

# The hash key every quarantined file manifest must carry.
CONTENT_HASH_KEY = "content_sha256"

# --- QuarantineAssetRecord contract -------------------------------------------
REQUIRED_FIELDS = (
    "quarantine_id",
    "candidate_id",
    "source_adapter",
    "source_url_or_path",
    "local_quarantine_path",
    "file_manifest",
    "hashes",
    "license_family",
    "ownership_class",
    "external_licensed",
    "generated_owned",
    "third_party_owned",
    "human_owned",
    "project_owned",
    "publisher",
    "author",
    "import_intent",
    "ue_import_target",
    "validation_status",
    "validation_errors",
    "created_at",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "provenance",
    "provenance_id",
    "quarantined_at",
    "notes",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def unknown_fields(record):
    return sorted(k for k in (record or {}) if k not in ALLOWED_FIELDS)


def missing_required_fields(record):
    d = record or {}
    return [k for k in REQUIRED_FIELDS if k not in d]


def _norm(path):
    return (path or "").replace("\\", "/").strip()


def is_under_quarantine_root(path):
    """True if ``path`` sits under one of the declared quarantine roots."""
    p = _norm(path)
    if not p:
        return False
    for root in QUARANTINE_ROOTS:
        r = root.replace("\\", "/").strip("/")
        if p == r or p.startswith(r + "/") or ("/" + r + "/") in ("/" + p + "/"):
            return True
    return False


def validate_record(record, strict=False):
    """Validate a QuarantineAssetRecord.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    r = record or {}
    checks = []

    missing = missing_required_fields(r)
    checks.append((
        "required_fields_present", not missing,
        "missing: {}".format(missing) if missing else "all required fields present",
        FailureCode.ASSET_QUARANTINE_SCHEMA_FAILURE,
    ))

    if strict:
        unknown = unknown_fields(r)
        checks.append((
            "no_unknown_fields", not unknown,
            "unknown fields: {}".format(unknown) if unknown else "no unknown fields",
            FailureCode.ASSET_QUARANTINE_SCHEMA_FAILURE,
        ))

    hashes = r.get("hashes")
    hashes_ok = isinstance(hashes, dict) and bool(hashes) \
        and bool(hashes.get(CONTENT_HASH_KEY))
    checks.append((
        "hashes_include_content_sha256", hashes_ok,
        "hashes must be a non-empty dict including {!r}".format(CONTENT_HASH_KEY),
        FailureCode.ASSET_HASH_MISSING,
    ))

    path = r.get("local_quarantine_path")
    path_ok = is_under_quarantine_root(path)
    checks.append((
        "local_quarantine_path_under_root", path_ok,
        "local_quarantine_path={!r} not under a quarantine root {}".format(
            path, QUARANTINE_ROOTS),
        FailureCode.ASSET_QUARANTINE_FAILURE,
    ))

    ownership = MC.resolve_ownership_class(r)
    checks.append((
        "ownership_class_resolves", ownership is not None,
        "ownership ambiguous/unresolvable (ownership_class + flags disagree)"
        if ownership is None else "ownership resolves to {}".format(ownership),
        FailureCode.ASSET_OWNERSHIP_FAILURE,
    ))

    return checks


def _example_record():
    return {
        "quarantine_id": "q_fab_rock_pack_01",
        "candidate_id": "cand_fab_rock_pack_01",
        "source_adapter": "manual_fab_acquisition",
        "source_url_or_path": "https://fab.com/listings/rock_pack_01",
        "local_quarantine_path": "WorldForgeAssetCache/_Quarantine/fab_rock_pack_01",
        "file_manifest": ["rock_01.fbx", "rock_01_bc.png"],
        "hashes": {"content_sha256": "deadbeefcafe"},
        "license_family": "fab_standard",
        "ownership_class": MC.OWNERSHIP_THIRD_PARTY,
        "external_licensed": True,
        "generated_owned": False,
        "third_party_owned": True,
        "human_owned": False,
        "project_owned": False,
        "publisher": "SomeVendor",
        "author": "SomeVendor",
        "import_intent": "encounter_cover",
        "ue_import_target": "/Game/WorldForge/ThirdParty/Meshes/",
        "validation_status": "pending",
        "validation_errors": [],
        "created_at": "2026-07-06T00:00:00+00:00",
    }


if __name__ == "__main__":
    rec = _example_record()
    results = validate_record(rec, strict=True)
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK quarantine_contract self-check: {} checks, 0 failing "
          "(REQUIRED_FIELDS={})".format(len(results), len(REQUIRED_FIELDS)))
