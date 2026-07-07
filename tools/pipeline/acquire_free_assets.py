#!/usr/bin/env python3
"""acquire_free_assets.py — v1.5 Wave-2 live CC0 free-asset acquisition.

Runs the PolyHavenDirectDownloadAdapter LIVE: searches api.polyhaven.com for a
small CC0 set, downloads the actual file bytes into a quarantine root FIRST,
computes a real content sha256, snapshots the CC0 license, and emits schema-clean
AssetCandidate + QuarantineAssetRecord records.

    PYTHONUTF8=1 STRICT=1 python acquire_free_assets.py --source polyhaven --approved-free-only --strict

Honest degrade: if the network is unavailable the run STILL exits 0, but emits
candidates with status ``requires_manual_acquisition`` and a report field
``live_download=false`` — it never fabricates a hash or claims a phantom
download. Fail-closed on any non-CC0 / missing-license candidate.
"""

import argparse
import os
import sys

from asset_paths import report_path
from asset_source_adapters import PolyHavenDirectDownloadAdapter, get_adapter
from failure_codes import FailureCode
from report_meta import build_meta
from source_adapter_base import (
    persist_candidate,
    persist_quarantine,
    validate_candidate,
    validate_quarantine_record,
)
from validation_report import ValidationReport, strict_from_env

REPORT_TYPE = "wf.asset.download_report.v1"
COMMAND = "acquire_free_assets"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Acquire free CC0 assets into quarantine (live).")
    ap.add_argument("--source", default="polyhaven")
    ap.add_argument("--approved-free-only", action="store_true", default=False)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("free_acquisition", args.source, strict=strict)
    adapter = get_adapter(args.source)

    # This driver only ever runs a free-approved source.
    rep.check("source_is_free_approved", adapter.POLICY.free_ok and not adapter.POLICY.paid_ok,
              "acquire_free_assets only runs free-approved (non-paid) sources",
              code=FailureCode.ASSET_SOURCE_POLICY_FAILURE)
    rep.check("cc0_only", tuple(adapter.POLICY.license_families) == ("cc0",),
              "free-download source must be CC0-only", code=FailureCode.ASSET_SOURCE_POLICY_FAILURE)
    rep.check("adapter_cannot_delete_source", adapter.POLICY.may_delete_source is False,
              "adapter must not delete its source", code=FailureCode.ASSET_SOURCE_POLICY_FAILURE)

    candidates = adapter.search([])   # no bound needs here -> default desert-biased CC0 set
    live_download = False
    downloaded = 0
    quarantined = 0
    manual_fallback = 0
    total_bytes = 0
    notes = []

    for cand in candidates:
        result = adapter.download_if_allowed(cand)
        if isinstance(result, dict) and result.get("refused"):
            # A policy refusal here means a non-CC0 slipped through — that is a
            # blocking fault (fail closed), not a silent skip.
            rep.check("download_not_refused::{}".format(cand["candidate_id"]), False,
                      result.get("detail", "download refused"), code=result.get("failure_code"))
            continue

        final_cand = result.get("candidate", cand)
        cok, cfail = validate_candidate(final_cand, strict=strict)
        rep.check("candidate::{}".format(final_cand["candidate_id"]), cok,
                  "; ".join("{}: {}".format(c, d) for c, d, _ in cfail) or "schema ok",
                  code=FailureCode.ASSET_CANDIDATE_SCHEMA_FAILURE)
        if cok:
            persist_candidate(final_cand)

        if result.get("live_download"):
            live_download = True
            downloaded += 1
            total_bytes += int(result.get("bytes", 0) or 0)
            qrec = result.get("quarantine_record")
            qok, qfail = validate_quarantine_record(qrec, strict=strict)
            rep.check("quarantine::{}".format((qrec or {}).get("quarantine_id", cand["candidate_id"])), qok,
                      "; ".join("{}: {}".format(c, d) for c, d, _ in qfail) or "schema ok",
                      code=FailureCode.ASSET_QUARANTINE_SCHEMA_FAILURE)
            # Downloaded record MUST carry a real content hash — no fake green.
            has_hash = bool((qrec or {}).get("hashes", {}).get("content_sha256")) and bool(final_cand.get("hash_expected"))
            rep.check("real_content_hash::{}".format(final_cand["candidate_id"]), has_hash,
                      "downloaded asset must carry a real content sha256",
                      code=FailureCode.ASSET_HASH_MISSING)
            if qok:
                persist_quarantine(qrec)
                quarantined += 1
        else:
            # Honest degrade — not a failure. Candidate is requires_manual_acquisition.
            manual_fallback += 1
            notes.append(result.get("note", "degraded to manual"))

    # At least one candidate must be produced (search yielded a set, or degrade).
    produced = downloaded + manual_fallback
    rep.check("acquisition_attempted", produced > 0 or adapter.network_ok is False,
              "no candidates produced and network state unknown",
              code=FailureCode.ASSET_SOURCE_ADAPTER_FAILURE)

    net_note = ("live network OK" if adapter.network_ok
                else "network unavailable: {}".format(getattr(adapter, "last_error", "unknown")))

    rep.finalize()
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.source, strict=strict,
        report_type=REPORT_TYPE, record_count=produced,
        records_total=produced, records_passed=produced,
        extra={
            "live_download": bool(live_download),
            "network_ok": bool(adapter.network_ok),
            "network_note": net_note,
            "downloaded_count": downloaded,
            "quarantined_count": quarantined,
            "manual_fallback_count": manual_fallback,
            "total_bytes": total_bytes,
            "notes": notes[:8],
        }))
    report_dir, filename = report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    print("[{}] live_download={} downloaded={} quarantined={} manual_fallback={} bytes={} ({})".format(
        COMMAND.replace("_", "-"), bool(live_download), downloaded, quarantined,
        manual_fallback, total_bytes, net_note))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
