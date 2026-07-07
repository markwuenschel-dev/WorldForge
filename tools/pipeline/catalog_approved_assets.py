#!/usr/bin/env python3
"""catalog_approved_assets.py — WorldForge v1.5 catalog promotion (library + CLI).

Promotes APPROVED quarantined assets into durable ``AssetCatalogRecord`` entries.
An asset is promoted only when it has (a) a matching approval record, (b) a license
family, (c) provenance linkage, and (d) a quarantine content hash. Anything short
of that is refused — a catalog entry is a claim of ownership/license/provenance
that must never be fabricated.

Each promoted record is validated with ``asset_catalog_contract.validate_record``
(single-sourced ownership/lifecycle rules) and written both to
``CATALOG_DIR/<asset_id>.json`` and upserted into the ``ACQUISITION_CATALOG``
aggregate. Emits a ``wf.asset.catalog_report.v1`` report.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import asset_catalog_contract as CC
import mesh_contract as MC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
REPORT_TYPE = "wf.asset.catalog_report.v1"
COMMAND = "catalog_approved_assets"


def _rel(p):
    return p.relative_to(REPO_ROOT).as_posix()


def _load_aggregate():
    path = asset_paths.ACQUISITION_CATALOG
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("assets"), dict):
                return data
        except Exception:
            pass
    return {"schema_version": CC.SCHEMA_VERSION, "assets": {}}


def _save_aggregate(agg):
    asset_paths.ensure(asset_paths.ACQUISITION_CATALOG)
    asset_paths.ACQUISITION_CATALOG.write_text(
        json.dumps(agg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _lifecycle_policy_for(ownership):
    protected = ownership in CC.LIFECYCLE_PROTECTED_OWNERSHIP
    return {"repair_allowed": not protected, "destroy_allowed": not protected}


def build_catalog_record(quar, approval):
    """Build an AssetCatalogRecord from a quarantine record + its approval.

    Returns (record, error_str). error_str is non-None (and record None) when the
    asset lacks the license+provenance+content-hash a catalog entry requires.
    """
    q = quar or {}
    cid = q.get("candidate_id") or ""
    content_hash = (q.get("hashes") or {}).get("content_sha256")
    if not content_hash:
        return None, "missing quarantine content hash"
    if not q.get("license_family"):
        return None, "missing license_family"
    if approval is None:
        return None, "no approval record for candidate {}".format(cid)

    ownership = MC.resolve_ownership_class(q)
    if ownership is None:
        return None, "ownership unresolvable"

    # Provenance linkage is SYNTHESIZED from the quarantine record's real source
    # data + the approval (the quarantine_contract deliberately does not carry a
    # separate provenance dict — its constituents live as first-class fields). A
    # catalog entry is still a provenance claim: it is assembled from actual
    # source_adapter/url/hash/candidate/approval, never fabricated. Reject if any
    # constituent is missing.
    prov = q.get("provenance") or {
        "source_adapter": q.get("source_adapter") or "",
        "source_url_or_path": q.get("source_url_or_path") or "",
        "candidate_id": cid,
        "quarantine_id": q.get("quarantine_id") or "",
        "approval_id": approval.get("approval_id") or "",
        "approval_type": approval.get("approval_type") or "",
        "content_sha256": content_hash,
        "license_family": q.get("license_family"),
    }
    prov_id = q.get("provenance_id") or ("prov_" + content_hash[:16])
    _missing = [k for k in ("source_adapter", "source_url_or_path", "candidate_id",
                            "approval_id") if not prov.get(k)]
    if _missing:
        return None, "incomplete provenance linkage: missing {}".format(_missing)

    # Deterministic stamp (no wall-clock): keyed on the content hash so re-runs
    # produce byte-identical catalog records and determinism gates stay green.
    now = "cataloged:" + content_hash[:16]
    # content_hash already carries its "sha256:" prefix from quarantine — do not
    # double-prefix (that breaks the catalog<->quarantine hash cross-check).
    src_hash = (q.get("hashes") or {}).get("source_hash") or content_hash
    record = {
        "asset_id": "cat_" + cid,
        "source_type": q.get("source_adapter") or "manual_acquisition",
        "source_adapter": q.get("source_adapter") or "manual_acquisition",
        "source_url": q.get("source_url_or_path") or "",
        "source_path": q.get("local_quarantine_path") or "",
        "source_hash": src_hash,
        "license_family": q.get("license_family"),
        "license_url": q.get("license_url") or "",
        "license_snapshot": q.get("license_snapshot") or q.get("local_quarantine_path") or "",
        "ownership_class": ownership,
        "external_licensed": bool(q.get("external_licensed")),
        "generated_owned": ownership == MC.OWNERSHIP_GENERATED,
        "third_party_owned": ownership == MC.OWNERSHIP_THIRD_PARTY,
        "human_owned": ownership == MC.OWNERSHIP_HUMAN,
        "project_owned": ownership == MC.OWNERSHIP_PROJECT,
        "publisher": q.get("publisher") or "",
        "author": q.get("author") or "",
        "downloaded_at": q.get("quarantined_at") or q.get("created_at") or now,
        "approved_at": approval.get("approved_at") or now,
        "cataloged_at": now,
        "import_status": "pending_import",
        "ue_asset_path": q.get("ue_import_target") or "",
        "ue_dependencies": [],
        "package_policy": "incorporated_project_content",
        "biome_tags": [],
        "terrain_tags": [],
        "mission_tags": [],
        "encounter_tags": [],
        "usage_tags": list(approval.get("allowed_usage") or []),
        "validation_status": "pending",
        "materialization_status": "not_materialized",
        "lifecycle_policy": _lifecycle_policy_for(ownership),
        "schema_version": CC.SCHEMA_VERSION,
        "provenance_id": prov_id,
        "provenance": prov,
    }
    failing = [c for c in CC.validate_record(record, strict=True) if not c[1]]
    if failing:
        name, _ok, detail, _code = failing[0]
        return None, "catalog record invalid ({}): {}".format(name, detail)
    return record, None


def _index_approvals():
    recs, _errs = discover_records([_rel(asset_paths.APPROVALS_DIR)])
    by_candidate = {}
    for _name, rec in recs:
        if isinstance(rec, dict) and rec.get("candidate_id"):
            by_candidate[rec["candidate_id"]] = rec
    return by_candidate


def promote(strict, pack=None):
    """Promote approved quarantined assets. Returns (rep, promoted, n_quarantine)."""
    rep = ValidationReport("pack", pack or "all", strict=strict)
    quarantined, parse_errors = discover_records([_rel(asset_paths.QUARANTINE_RECORDS_DIR)])
    approvals = _index_approvals()

    for name, detail in parse_errors:
        rep.check("parse::{}".format(name), False,
                  "unparseable quarantine record: {}".format(detail),
                  code=FailureCode.ASSET_CATALOG_FAILURE)

    if not quarantined and not parse_errors:
        rep.check("no_approved_quarantine_records_present", True,
                  "no quarantined records to promote yet (nothing to catalog)")
        return rep, 0, 0

    promoted = 0
    agg = _load_aggregate()
    for name, q in quarantined:
        if not isinstance(q, dict):
            rep.check("promote::{}::record_shape".format(name), False,
                      "quarantine record is not a mapping",
                      code=FailureCode.ASSET_CATALOG_FAILURE)
            continue
        cid = q.get("candidate_id")
        approval = approvals.get(cid)
        # No approval yet => pending, not an error: quarantine is the waystation and
        # an un-approved asset simply stays there. Skip (non-blocking).
        if approval is None:
            rep.skip("promote::{}::pending_approval".format(name),
                     "no approval for candidate {} yet; leaving in quarantine".format(cid))
            continue
        record, err = build_catalog_record(q, approval)
        if record is None:
            # APPROVED but structurally incompletable => a genuine defect (never
            # promote an approved asset lacking license+provenance+content-hash).
            rep.check("promote::{}::approved_asset_complete".format(name), False,
                      err or "approved asset cannot be catalogued",
                      code=FailureCode.ASSET_CATALOG_FAILURE)
            continue
        rep.check("promote::{}::cataloged".format(name), True, "promoted to catalog")
        out = asset_paths.ensure(asset_paths.CATALOG_DIR / (record["asset_id"] + ".json"))
        out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        agg["assets"][record["asset_id"]] = record
        promoted += 1

    if promoted:
        _save_aggregate(agg)
    return rep, promoted, len(quarantined)


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 catalog promotion.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep, promoted, n_quarantine = promote(strict, pack=args.pack)
    rep.finalize()
    rc = n_quarantine if n_quarantine else len(rep.checks)
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=rc, records_total=n_quarantine, records_passed=promoted,
        records_failed=max(0, n_quarantine - promoted)))
    report_dir, filename = asset_paths.report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
