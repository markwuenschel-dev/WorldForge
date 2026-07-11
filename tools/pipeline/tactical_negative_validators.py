#!/usr/bin/env python3
"""tactical_negative_validators.py — v2.4 aggregate negative-validator gate (Wave R).

The envelope gate that proves the FULL handoff §7/§13 known-bad catalog is rejected — the
contract-fixture negatives (tactical_negatives.cases) AND the evidence-layer fake-proofs
(tactical_torture.modes) together — each for its owning code, with a non-vacuous floor. The
single gate answering "can any known way of faking a green tactical-behavior result slip
through?" — the answer must be no.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/tactical_negative_validators.py --strict
Reports -> procedural/reports/tactical/negatives/tactical_negative_validators_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from tactical_negatives import cases as contract_cases
from tactical_torture import modes as evidence_modes


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 aggregate tactical negative-validator gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "tactical_negative_validators", strict=strict)

    catalog = ([("contract", lbl, val, rec, owning) for lbl, val, rec, owning in contract_cases()]
               + [("evidence", lbl, val, rec, owning) for lbl, val, rec, owning in evidence_modes()])
    rep.check("catalog::non_vacuous", len(catalog) >= 60,
              "aggregate known-bad catalog must carry >= 60 cases (got {})".format(len(catalog)),
              code=F.TACTICAL_NEGATIVE_ACCEPTED)
    for lane, label, validate, rec, owning in catalog:
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("neg::{}::{}::rejected".format(lane, label), len(fails) > 0,
                  "known-bad ACCEPTED (fake green)", code=F.TACTICAL_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::{}::owning_code".format(lane, label), owning in codes,
                  "must be rejected for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]), code=F.TACTICAL_NEGATIVE_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="tactical-negative-validators", pack=None, strict=strict, status=rep.status,
        record_count=len(catalog), records_total=len(catalog),
        report_type="wf.tactical.negative_validators.v1"))
    (REPO_ROOT / "procedural" / "reports" / "tactical" / "negatives").mkdir(parents=True, exist_ok=True)
    rep.write(REPO_ROOT / "procedural" / "reports" / "tactical" / "negatives",
              "tactical_negative_validators_report.json")
    rep.print_summary("tactical-negative-validators")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
