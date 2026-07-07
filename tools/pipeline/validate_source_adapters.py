#!/usr/bin/env python3
"""validate_source_adapters.py — v1.5 Wave-2 source-adapter policy gate.

Proves — WITHOUT any network or any candidates on disk — that every source
adapter enforces its fail-closed policy:

  * PolyHaven REFUSES a non-CC0 candidate (license fail-closed).
  * ManualFab REFUSES automated download (ASSET_DOWNLOAD_NOT_ALLOWED).
  * Local Fab/Megascans cache adapter cannot delete/mutate its source.
  * QuarantineFolder classifies an unknown-license drop as REJECT.
  * Every adapter exposes a coherent emit_policy() with a valid ownership_class
    and may_delete_source / may_mutate_source == False (no source is destroyable).

This gate is GREEN when policies are correct even with zero candidates — it tests
enforcement, not inventory.

    PYTHONUTF8=1 STRICT=1 python validate_source_adapters.py --pack <id> --strict
"""

import argparse
import os
import sys

import mesh_contract as MC
from asset_paths import report_path
from asset_source_adapters import (
    ADAPTER_CLASSES,
    LocalFabMegascansCacheAdapter,
    ManualFabAcquisitionAdapter,
    PolyHavenDirectDownloadAdapter,
    QuarantineFolderAdapter,
)
from failure_codes import FailureCode
from report_meta import build_meta
from validation_report import ValidationReport, strict_from_env

REPORT_TYPE = "wf.asset.source_search.v1"
COMMAND = "validate_source_adapters"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prove every source adapter enforces its fail-closed policy.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("source_adapter_policy", args.pack or "all", strict=strict)

    # -- universal invariants over every adapter ----------------------------
    for cls in ADAPTER_CLASSES:
        pol = cls.POLICY
        name = pol.adapter_name
        rep.check("{}::ownership_class_valid".format(name),
                  pol.ownership_class in MC.OWNERSHIP_CLASSES,
                  "ownership_class={!r}".format(pol.ownership_class),
                  code=FailureCode.ASSET_OWNERSHIP_FAILURE)
        rep.check("{}::may_not_delete_source".format(name), pol.may_delete_source is False,
                  "no adapter may delete its source", code=FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK)
        rep.check("{}::may_not_mutate_source".format(name), pol.may_mutate_source is False,
                  "no adapter may mutate its source", code=FailureCode.SOURCE_OWNERSHIP_SEPARATION_FAILURE)
        emitted = cls().emit_policy()
        rep.check("{}::emit_policy_coherent".format(name),
                  emitted.get("adapter_name") == name and "download_automation_allowed" in emitted,
                  "emit_policy() must echo adapter_name + policy flags",
                  code=FailureCode.ASSET_SOURCE_POLICY_FAILURE)
        # A paid-capable adapter must be manual-only (never automate paid content).
        if pol.paid_ok:
            rep.check("{}::paid_is_manual_only".format(name),
                      pol.manual_only and not pol.download_automation_allowed,
                      "paid-capable adapter must be manual-only, no automation",
                      code=FailureCode.ASSET_PURCHASE_REQUIRED_MANUAL_ACTION)
        # A download-automation adapter must be CC0-only + free.
        if pol.download_automation_allowed:
            rep.check("{}::automation_is_cc0_free".format(name),
                      pol.free_ok and not pol.paid_ok and tuple(pol.license_families) == ("cc0",),
                      "automated-download adapter must be free + CC0-only",
                      code=FailureCode.ASSET_SOURCE_POLICY_FAILURE)

    # -- PolyHaven refuses non-CC0 ------------------------------------------
    ph = PolyHavenDirectDownloadAdapter()
    non_cc0 = {"candidate_id": "probe_noncc0", "license_family": "royalty_free",
               "source_url": "https://polyhaven.com/a/probe"}
    ref = ph.download_if_allowed(non_cc0)
    rep.check("polyhaven_refuses_non_cc0",
              bool(ref.get("refused")) and ref.get("failure_code") == FailureCode.ASSET_LICENSE_UNSUPPORTED,
              "expected CC0-only refusal, got {}".format(ref),
              code=FailureCode.ASSET_LICENSE_UNSUPPORTED)
    missing_lic = {"candidate_id": "probe_nolic", "license_family": "",
                   "source_url": "https://polyhaven.com/a/probe"}
    ref2 = ph.download_if_allowed(missing_lic)
    rep.check("polyhaven_refuses_missing_license",
              bool(ref2.get("refused")) and ref2.get("failure_code") == FailureCode.ASSET_LICENSE_MISSING,
              "expected missing-license refusal, got {}".format(ref2),
              code=FailureCode.ASSET_LICENSE_MISSING)

    # -- ManualFab refuses automated download -------------------------------
    mf = ManualFabAcquisitionAdapter()
    ref3 = mf.download_if_allowed({"candidate_id": "probe_manual"})
    rep.check("manual_fab_refuses_download",
              bool(ref3.get("refused")) and ref3.get("failure_code") == FailureCode.ASSET_DOWNLOAD_NOT_ALLOWED,
              "expected download-not-allowed refusal, got {}".format(ref3),
              code=FailureCode.ASSET_DOWNLOAD_NOT_ALLOWED)

    # -- Local cache refuses source deletion --------------------------------
    local = LocalFabMegascansCacheAdapter()
    rep.check("local_cache_may_not_delete_source", local.POLICY.may_delete_source is False,
              "local Fab/Megascans cache adapter must never delete a source file",
              code=FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK)
    rep.check("local_cache_may_not_mutate_source", local.POLICY.may_mutate_source is False,
              "local Fab/Megascans cache adapter must never mutate a source file",
              code=FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK)

    # -- QuarantineFolder fail-closed on unknown ----------------------------
    qf = QuarantineFolderAdapter()
    unknown = qf.classify({"license_family": "mystery_license"})
    rep.check("quarantine_folder_rejects_unknown",
              unknown.get("decision") == "reject" and unknown.get("ownership_class") is None,
              "unknown-license drop must fail closed (reject), got {}".format(unknown),
              code=FailureCode.ASSET_UNKNOWN_LICENSE_REJECTED)
    known = qf.classify({"license_family": "cc0"})
    rep.check("quarantine_folder_accepts_known_license",
              known.get("decision") != "reject" and known.get("license_family") == "cc0",
              "known-license drop should resolve, got {}".format(known),
              code=FailureCode.ASSET_UNKNOWN_LICENSE_REJECTED)

    rep.finalize()
    n_checks = len(rep.checks)
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, record_count=n_checks,
        records_total=n_checks, records_passed=n_checks - len(rep.failures),
        records_failed=len(rep.failures),
        extra={"adapters_checked": [c.POLICY.adapter_name for c in ADAPTER_CLASSES]}))
    report_dir, filename = report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
