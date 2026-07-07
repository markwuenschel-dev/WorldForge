#!/usr/bin/env python3
"""create_procurement_manifest.py — WorldForge v1.5 AssetAcquisitionForge (Wave 2).

Aggregate the pack's generated AssetNeed records into ONE schema-valid
AssetProcurementManifest: the pack-scoped policy envelope every downstream
candidate/quarantine/approval stage must honour. It decides nothing about a
specific candidate — it declares WHAT to acquire and UNDER WHICH policies
(source / approval / quarantine / package / manual-acquisition / download /
validation).

Safety posture baked into the policy blocks:
  * Download automation is permitted ONLY for free + permissive-licensed items;
    every paid / EULA-gated item is manual_acquisition_required with automation
    forbidden (so nothing paid can ever be auto-downloaded).
  * Unknown licenses are rejected; quarantine-first before any final path.

Deterministic: generated_at derives from the git sha (never datetime.now()).
Stdlib only. The manifest is validated before it is written — an invalid
manifest aborts the run.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import asset_paths
import asset_procurement_contract as PC
from failure_codes import FailureCode
from report_meta import build_meta, git_sha
from validation_report import ValidationReport, strict_from_env

REPO_ROOT = Path(__file__).resolve().parents[2]

# License families we treat as permissive/free — the only ones eligible for
# download automation (and then only when the need is free and not paid-only).
PERMISSIVE_LICENSES = {"cc0", "project_owned", "generated_owned"}

VALIDATION_REQUIREMENTS = [
    "license_present", "provenance_present", "quarantine_before_final",
    "collision", "bounds", "material_binding", "ownership_class",
    "package_policy",
]


def _generated_at():
    """Deterministic manifest timestamp — derived from the git sha."""
    sha = git_sha()
    return "generated@{}".format(sha if sha and sha != "unknown" else "unstamped")


def load_pack_needs(pack):
    """Return [need_dict] for every generated AssetNeed belonging to `pack`."""
    out = []
    d = asset_paths.NEEDS_DIR
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(rec, dict) and rec.get("pack") == pack:
            out.append(rec)
    out.sort(key=lambda r: r.get("asset_need_id", ""))
    return out


def _download_allowed(need):
    """A need may be auto-downloaded only if free, not paid-gated, and every one
    of its allowed license families is permissive."""
    if not need.get("free_ok"):
        return False
    if need.get("paid_ok"):
        # Ambiguous (both free and paid acceptable) -> require manual to be safe.
        return False
    if not need.get("download_automation_allowed"):
        return False
    fams = set(need.get("allowed_license_families") or [])
    return bool(fams) and fams.issubset(PERMISSIVE_LICENSES)


def build_manifest_item(need):
    """Derive one policy-bound manifest line from an AssetNeed (12 required fields)."""
    auto = _download_allowed(need)
    # Anything that is not auto-download-eligible (paid/EULA/ambiguous) is manual.
    manual_required = (not auto) or bool(need.get("paid_ok"))
    return {
        "asset_need_id": need["asset_need_id"],
        "priority": need["priority"],
        "asset_type": need["asset_type"],
        "minimum_count": int(need.get("required_count") or 0),
        "preferred_sources": list(need.get("preferred_sources") or []),
        "allowed_license_families": list(need.get("allowed_license_families") or []),
        "paid_ok": bool(need.get("paid_ok")),
        "free_ok": bool(need.get("free_ok")),
        "manual_acquisition_required": bool(manual_required),
        "download_automation_allowed": bool(auto),
        "ue_materialization_required": bool(need.get("ue_materialization_required")),
        "package_policy": need.get("package_policy") or "project_incorporated_content_only",
    }


def build_manifest(pack, needs):
    items = [build_manifest_item(n) for n in needs]
    return {
        "manifest_id": "manifest_{}".format(pack),
        "pack": pack,
        "generated_at": _generated_at(),
        "asset_needs": items,
        "source_policy": {
            "adapters": ["internal_generated", "local_megascans_cache", "polyhaven"],
            "unknown_source": "reject",
            "prefer_order": ["internal_generated", "local_megascans_cache", "polyhaven"],
        },
        "approval_policy": {
            "unknown_license": "reject",
            "requires_manual_approval_for": ["paid", "eula_gated", "third_party"],
            "default": "quarantine_then_review",
        },
        "quarantine_policy": {
            "root": asset_paths.QUARANTINE_ROOT_ANCHORS[0],
            "mode": "quarantine_before_final",
            "hash_required": True,
        },
        "package_policy": "project_incorporated_content_only",
        "manual_acquisition_policy": {
            "paid": "manual_only",
            "eula_gated": "manual_only",
            "free_permissive": "automation_allowed",
        },
        "download_policy": {
            "mode": PC.DOWNLOAD_MODE_MANUAL_ONLY,
            "automation_allowed_for": "free_permissive_only",
            "paid_automation": "forbidden",
        },
        "validation_requirements": list(VALIDATION_REQUIREMENTS),
        # optional / additive
        "schema_version": PC.SCHEMA_VERSION,
        "display_name": "Procurement manifest — {}".format(pack),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aggregate AssetNeeds into an AssetProcurementManifest.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()
    pack = args.pack

    rep = ValidationReport("asset_procurement_manifest", pack, strict=strict)

    needs = load_pack_needs(pack)
    rep.check("needs_present", bool(needs),
              "found {} need(s) for pack {}".format(len(needs), pack),
              code=FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE)

    if not needs:
        rep.set_meta(build_meta(
            "create-procurement-manifest", pack=pack, strict=strict,
            report_type="wf.asset.procurement_manifest.v1", record_count=0,
            records_total=0, records_passed=0, records_failed=1))
        rep.finalize()
        d, fn = asset_paths.report_path("assets", "create_procurement_manifest")
        rep.write(d, fn)
        rep.print_summary("create-procurement-manifest")
        return rep.exit_code

    manifest = build_manifest(pack, needs)

    # Validate the whole manifest (and every nested item) BEFORE writing.
    failing = [c for c in PC.validate_record(manifest, strict=True) if not c[1]]
    if failing:
        for cname, ok, detail, code in failing:
            sys.stderr.write("[create-procurement-manifest] INVALID: {}: {}\n".format(cname, detail))
        sys.stderr.write("[create-procurement-manifest] ABORT — manifest invalid; nothing written.\n")
        return 2

    asset_paths.ensure(asset_paths.PROCUREMENT_DIR)
    path = asset_paths.PROCUREMENT_DIR / "{}.json".format(manifest["manifest_id"])
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    n_items = len(manifest["asset_needs"])
    for it in manifest["asset_needs"]:
        rep.check("item_valid::{}".format(it["asset_need_id"]), True,
                  "manual={} auto_dl={} paid={}".format(
                      it["manual_acquisition_required"],
                      it["download_automation_allowed"], it["paid_ok"]))
    rep.check("manifest_written", True, str(path))

    rep.set_meta(build_meta(
        "create-procurement-manifest", pack=pack, strict=strict,
        report_type="wf.asset.procurement_manifest.v1", record_count=1,
        records_total=1, records_passed=1, records_failed=0,
        extra={"manifest_item_count": n_items}))
    rep.finalize()
    d, fn = asset_paths.report_path("assets", "create_procurement_manifest")
    rep.write(d, fn)
    rep.print_summary("create-procurement-manifest")
    print("[create-procurement-manifest] manifest with {} item(s) -> {}".format(n_items, path))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
