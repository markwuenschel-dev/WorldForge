#!/usr/bin/env python3
"""scan_local_asset_cache.py — v1.5 Wave-2 local third-party cache intake.

Runs the LocalFabMegascansCacheAdapter against the LIVE Fab/Megascans cache
(read-only), COPIES a representative file for each detected asset into a
quarantine root (never moves the original), and emits schema-clean AssetCandidate
records plus QuarantineAssetRecords. Ownership is preserved as third_party_owned.

    PYTHONUTF8=1 STRICT=1 python scan_local_asset_cache.py --source megascans --strict

Exit 0 on a clean scan (candidates found, all records schema-valid, ownership
preserved). Fail-closed if the cache is unconfigured or a record is malformed.
"""

import argparse
import os
import sys

import asset_config
import mesh_contract as MC
from asset_paths import report_path
from asset_source_adapters import get_adapter
from failure_codes import FailureCode
from report_meta import build_meta
from source_adapter_base import (
    persist_candidate,
    persist_quarantine,
    validate_candidate,
    validate_quarantine_record,
)
from validation_report import ValidationReport, strict_from_env

REPORT_TYPE = "wf.asset.local_cache_scan.v1"
COMMAND = "scan_local_asset_cache"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scan a local third-party asset cache into candidates + quarantine.")
    ap.add_argument("--source", default="megascans")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("local_cache_scan", args.source, strict=strict)
    adapter = get_adapter(args.source)

    root = getattr(adapter, "root", None)
    rep.check("cache_configured_and_present", root is not None,
              "library root for {!r} not resolved on this machine (set worldforge_assets.local.json)".format(args.source),
              code=FailureCode.MEGASCANS_LIBRARY_FAILURE)
    rep.check("adapter_cannot_delete_source", adapter.POLICY.may_delete_source is False,
              "adapter policy must forbid source deletion", code=FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK)

    n_candidates = n_quarantined = 0
    if root is not None:
        candidates = adapter.scan_local()
        for cand in candidates:
            cok, cfail = validate_candidate(cand, strict=strict)
            rep.check("candidate::{}".format(cand["candidate_id"]), cok,
                      "; ".join("{}: {}".format(c, d) for c, d, _ in cfail) or "schema ok",
                      code=FailureCode.ASSET_CANDIDATE_SCHEMA_FAILURE)
            # Ownership must stay third_party through intake.
            tp_ok = (cand.get("source_type") == "megascans_library"
                     and cand.get("license_family") == "fab_standard")
            rep.check("candidate_third_party_preserved::{}".format(cand["candidate_id"]), tp_ok,
                      "candidate must remain third-party/fab-licensed",
                      code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)
            if not cok:
                continue
            persist_candidate(cand)
            n_candidates += 1

            qrec = adapter.quarantine(cand["source_path"], cand)
            if isinstance(qrec, dict) and qrec.get("refused"):
                rep.check("quarantine::{}".format(cand["candidate_id"]), False,
                          qrec.get("detail", "quarantine refused"),
                          code=FailureCode.ASSET_QUARANTINE_FAILURE)
                continue
            qok, qfail = validate_quarantine_record(qrec, strict=strict)
            rep.check("quarantine::{}".format(qrec["quarantine_id"]), qok,
                      "; ".join("{}: {}".format(c, d) for c, d, _ in qfail) or "schema ok",
                      code=FailureCode.ASSET_QUARANTINE_SCHEMA_FAILURE)
            own_ok = MC.resolve_ownership_class(qrec) == MC.OWNERSHIP_THIRD_PARTY
            rep.check("quarantine_third_party::{}".format(qrec["quarantine_id"]), own_ok,
                      "quarantine ownership must resolve third_party_owned",
                      code=FailureCode.ASSET_OWNERSHIP_FAILURE)
            if qok:
                persist_quarantine(qrec)
                n_quarantined += 1

    rep.check("candidates_found", n_candidates > 0,
              "no candidates emitted from {!r} cache scan".format(args.source),
              code=FailureCode.MEGASCANS_SCAN_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.source, strict=strict,
        report_type=REPORT_TYPE, record_count=n_candidates,
        records_total=n_candidates, records_passed=n_candidates,
        extra={"quarantined_count": n_quarantined,
               "library_root_alias": asset_config.library_root_alias(args.source)}))
    report_dir, filename = report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    print("[{}] {} candidates, {} quarantined (copy-only) from '{}'".format(
        COMMAND.replace("_", "-"), n_candidates, n_quarantined, args.source))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
