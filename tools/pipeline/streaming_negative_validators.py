#!/usr/bin/env python3
"""streaming_negative_validators.py — v2.3 aggregate negative-validator gate (Wave R).

The envelope gate that proves the FULL handoff §7/§12 known-bad catalog is rejected —
the contract-fixture negatives (streaming_negatives.cases) AND the evidence-layer
fake-proofs (streaming_torture.modes) together — each for its owning code, with a
non-vacuous floor. The single gate answering "can any known way of faking a green
streamed-region result slip through?" — the answer must be no.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/streaming_negative_validators.py --strict
Reports -> procedural/reports/streaming/negatives/streaming_negative_validators_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from streaming_negatives import cases as contract_cases
from streaming_torture import modes as evidence_modes

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "negatives"


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 aggregate negative-validator gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "streaming_negative_validators", strict=strict)

    catalog = [("contract::" + l, v, r, o) for l, v, r, o in contract_cases()]
    catalog += [("evidence::" + l, v, r, o) for l, v, r, o in evidence_modes()]
    rep.check("catalog::non_vacuous", len(catalog) >= 45,
              "known-bad catalog must carry >= 45 cases (got {})".format(len(catalog)),
              code=F.STREAMING_NEGATIVE_ACCEPTED)
    for label, validate, rec, owning in catalog:
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("nv::{}::rejected".format(label), len(fails) > 0,
                  "known-bad was ACCEPTED (fake green)", code=F.STREAMING_NEGATIVE_ACCEPTED)
        rep.check("nv::{}::owning_code".format(label), owning in codes,
                  "must be rejected for {} (got {})".format(owning, sorted(str(x) for x in codes)[:4]),
                  code=F.STREAMING_NEGATIVE_ACCEPTED)
    for name, (validate, good, _bad) in SC.CONTRACTS.items():
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("reverse::{}::valid_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=F.STREAMING_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="streaming-negative-validators", pack=None, strict=strict, status=rep.status,
        record_count=len(catalog), records_total=len(catalog),
        report_type="wf.streaming.negative_validators.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "streaming_negative_validators_report.json")
    rep.print_summary("streaming-negative-validators")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
