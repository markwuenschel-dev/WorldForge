#!/usr/bin/env python3
"""approve_asset.py — WorldForge v1.5 asset approval gate (library + CLI).

Builds an ``AssetApprovalRecord`` for a discovered candidate, but only after the
dangerous states are refused fail-closed:

  * a paid candidate without a completed manual acquisition action
    (ASSET_PURCHASE_REQUIRED_MANUAL_ACTION);
  * a EULA-gated candidate without a completed manual action
    (ASSET_EULA_REQUIRED_MANUAL_ACTION);
  * an unknown / missing license;
  * a missing source reference or expected hash;
  * a third-party candidate mismarked generated_owned;
  * standalone redistribution requested for third-party content
    (ASSET_STANDALONE_REDISTRIBUTION_FORBIDDEN).

The built record is validated against ``asset_approval_contract`` (which itself
encodes ``INVALID_APPROVAL_RULES``) BEFORE it is written to ``APPROVALS_DIR``.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import asset_approval_contract as AC
import mesh_contract as MC
from failure_codes import FailureCode

_ALLOWED_LICENSES = {
    "cc0", "fab_standard", "fab_professional",
    "project_owned", "generated_owned", "internal_project_license",
}
_THIRD_PARTY_LICENSES = {"cc0", "fab_standard", "fab_professional"}


class ApprovalError(RuntimeError):
    """Raised when a candidate may NOT be approved. Carries a failure code."""

    def __init__(self, code, detail):
        super().__init__("{}: {}".format(code, detail))
        self.code = code
        self.detail = detail


def _find_candidate(candidate_id, candidates_dir=None):
    base = Path(candidates_dir) if candidates_dir else asset_paths.CANDIDATES_DIR
    if not base.is_dir():
        return None
    for p in sorted(base.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rec in (data if isinstance(data, list) else [data]):
            if isinstance(rec, dict) and rec.get("candidate_id") == candidate_id:
                return rec
    return None


def _derive_approval_type(candidate):
    if candidate.get("manual_acquisition_required") or candidate.get("eula_required") \
            or candidate.get("price_class") == "paid":
        return "manual_marketplace_acquisition"
    lf = candidate.get("license_family")
    if lf in ("generated_owned",):
        return "internal_generated"
    if lf in ("project_owned", "internal_project_license"):
        return "project_owned_existing"
    return "direct_download_permissive"


def build_approval(candidate, *, approved_by=None, manual_action_completed=False,
                   eula_accepted_by_user=False, purchase_completed_by_user=False,
                   allowed_usage=None, notes=""):
    """Build + guard an AssetApprovalRecord. Raises ApprovalError fail-closed."""
    candidate = candidate or {}
    cid = candidate.get("candidate_id")
    if not cid:
        raise ApprovalError(FailureCode.ASSET_APPROVAL_STATE_FAILURE,
                            "candidate has no candidate_id")

    # -- license must be present + known ----------------------------------------
    lf = candidate.get("license_family")
    if not lf:
        raise ApprovalError(FailureCode.ASSET_LICENSE_MISSING,
                            "candidate {} has no license_family".format(cid))
    if lf not in _ALLOWED_LICENSES:
        raise ApprovalError(FailureCode.ASSET_UNKNOWN_LICENSE_REJECTED,
                            "candidate {} license_family={!r} not in allowed set".format(cid, lf))

    # -- source + hash present --------------------------------------------------
    if not (candidate.get("source_url") or candidate.get("source_path")):
        raise ApprovalError(FailureCode.ASSET_SOURCE_URL_MISSING,
                            "candidate {} has neither source_url nor source_path".format(cid))
    if not candidate.get("hash_expected"):
        raise ApprovalError(FailureCode.ASSET_HASH_MISSING,
                            "candidate {} has no hash_expected".format(cid))

    approval_type = _derive_approval_type(candidate)
    is_third_party = approval_type in AC.THIRD_PARTY_APPROVAL_TYPES or \
        lf in _THIRD_PARTY_LICENSES

    # -- third-party may never be generated_owned or standalone-redistributable --
    if is_third_party and MC.resolve_ownership_class(candidate) == MC.OWNERSHIP_GENERATED:
        raise ApprovalError(FailureCode.ASSET_OWNERSHIP_FAILURE,
                            "third-party candidate {} mismarked generated_owned".format(cid))

    # -- paid / EULA gate: require a completed manual action --------------------
    if candidate.get("price_class") == "paid" and not manual_action_completed:
        raise ApprovalError(FailureCode.ASSET_PURCHASE_REQUIRED_MANUAL_ACTION,
                            "paid candidate {} requires a completed manual acquisition action".format(cid))
    if candidate.get("eula_required") and not manual_action_completed:
        raise ApprovalError(FailureCode.ASSET_EULA_REQUIRED_MANUAL_ACTION,
                            "EULA-gated candidate {} requires a completed manual action".format(cid))
    if approval_type in AC.MANUAL_ACTION_APPROVAL_TYPES:
        if not (manual_action_completed and approved_by):
            raise ApprovalError(FailureCode.ASSET_MANUAL_APPROVAL_MISSING,
                                "manual acquisition of {} requires manual_action_completed + approved_by".format(cid))
        if not (eula_accepted_by_user and purchase_completed_by_user):
            raise ApprovalError(FailureCode.ASSET_MANUAL_APPROVAL_MISSING,
                                "manual acquisition of {} requires real-user EULA + purchase markers".format(cid))

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "approval_id": "appr_" + cid,
        "candidate_id": cid,
        "asset_need_id": candidate.get("asset_need_id") or "",
        "approved_by": approved_by or "",
        "approval_type": approval_type,
        "approval_scope": "project_incorporated_content_only",
        "allowed_usage": list(allowed_usage or candidate.get("tags") or []),
        # Third-party approvals may NEVER grant standalone redistribution.
        "standalone_redistribution_allowed": False,
        "manual_action_completed": bool(manual_action_completed),
        "eula_accepted_by_user": bool(eula_accepted_by_user),
        "purchase_completed_by_user": bool(purchase_completed_by_user),
        "approved_at": now,
        "notes": notes,
        "schema_version": AC.SCHEMA_VERSION,
    }

    failing = [c for c in AC.validate_record(record, strict=True) if not c[1]]
    if failing:
        name, _ok, detail, code = failing[0]
        raise ApprovalError(code, "approval record invalid ({}): {}".format(name, detail))
    return record


def write_approval(record, approvals_dir=None):
    base = Path(approvals_dir) if approvals_dir else asset_paths.APPROVALS_DIR
    base.mkdir(parents=True, exist_ok=True)
    out = base / (record["approval_id"] + ".json")
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 asset approval gate.")
    ap.add_argument("--candidate", help="candidate_id to approve")
    ap.add_argument("--approved-by")
    ap.add_argument("--manual-action-completed", action="store_true")
    ap.add_argument("--eula-accepted-by-user", action="store_true")
    ap.add_argument("--purchase-completed-by-user", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"

    if not args.candidate:
        # Nothing requested: valid no-op (Wave-1 / empty state).
        print("approve_asset: no --candidate supplied; nothing to approve.")
        return 0

    candidate = _find_candidate(args.candidate)
    if candidate is None:
        sys.stderr.write("candidate not found: {}\n".format(args.candidate))
        return 1
    try:
        rec = build_approval(
            candidate, approved_by=args.approved_by,
            manual_action_completed=args.manual_action_completed,
            eula_accepted_by_user=args.eula_accepted_by_user,
            purchase_completed_by_user=args.purchase_completed_by_user)
    except ApprovalError as exc:
        sys.stderr.write("BLOCKED {}\n".format(exc))
        return 1
    out = write_approval(rec)
    print("approved -> {} ({})".format(rec["approval_id"], out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
