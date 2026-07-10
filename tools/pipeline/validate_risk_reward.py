#!/usr/bin/env python3
"""validate_risk_reward.py — WorldForge v1.9 risk/reward balance report gate.

Loads the balance rollup ``procedural/reports/rewards/balance/risk_reward_report.json``
(written by classify_risk_reward.py) and independently re-gates it as an artifact:
it must exist and be non-empty; every per-scenario entry must carry a
``risk_reward_class`` in ``RX.RISK_REWARD_CLASSES`` and an ``exploit_result`` in
``RX.EXPLOIT_RESULTS``; NO entry may be in a blocking class; and the report's meta
block must carry a ``git_sha`` and ``report_type`` (report-integrity — a balance
report with no provenance is not trustworthy).

Report -> ``procedural/reports/rewards/balance/validate_risk_reward_report.json``.

Acceptance: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_risk_reward.py --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

REPORT_REL = "procedural/reports/rewards/balance"
BALANCE_REPORT = "procedural/reports/rewards/balance/risk_reward_report.json"
C = FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    path = REPO_ROOT / BALANCE_REPORT
    doc = None
    if not path.is_file():
        rep.check("risk-reward-report::exists", False,
                  "balance report missing at {} (run classify_risk_reward.py)".format(BALANCE_REPORT),
                  code=C.RISK_REWARD_CLASSIFICATION_INVALID)
    else:
        rep.check("risk-reward-report::exists", True, str(path))
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            rep.check("risk-reward-report::parseable", False,
                      "could not parse balance report: {}".format(exc),
                      code=C.RISK_REWARD_CLASSIFICATION_INVALID)

    entries = doc.get("scenarios") if isinstance(doc, dict) else None
    rep.check("risk-reward-report::nonempty",
              isinstance(entries, list) and len(entries) > 0,
              "balance report must carry a non-empty scenarios list",
              code=C.RISK_REWARD_CLASSIFICATION_INVALID)

    if isinstance(entries, list):
        for i, e in enumerate(entries):
            sid = e.get("scenario_id", i) if isinstance(e, dict) else i
            rrc = e.get("risk_reward_class") if isinstance(e, dict) else None
            expl = e.get("exploit_result") if isinstance(e, dict) else None
            rep.check("risk-reward-report::{}::class_known".format(sid),
                      rrc in RX.RISK_REWARD_CLASSES,
                      "risk_reward_class {!r} not in registry".format(rrc),
                      code=C.RISK_REWARD_CLASSIFICATION_INVALID)
            rep.check("risk-reward-report::{}::exploit_known".format(sid),
                      expl in RX.EXPLOIT_RESULTS,
                      "exploit_result {!r} not in registry".format(expl),
                      code=C.REWARD_EXPLOIT_DETECTED)
            rep.check("risk-reward-report::{}::not_blocking".format(sid),
                      rrc not in RX.BLOCKING_RISK_REWARD_CLASSES,
                      "entry classifies as blocking class {!r}".format(rrc),
                      code=C.RISK_REWARD_CLASSIFICATION_INVALID)

    meta = doc.get("meta") if isinstance(doc, dict) else None
    rep.check("risk-reward-report::meta_present", isinstance(meta, dict),
              "balance report must carry a meta block", code=C.REWARD_REPORT_INTEGRITY_FAILED)
    if isinstance(meta, dict):
        rep.check("risk-reward-report::meta_git_sha",
                  isinstance(meta.get("git_sha"), str) and len(meta.get("git_sha")) > 0,
                  "meta.git_sha must be present", code=C.REWARD_REPORT_INTEGRITY_FAILED)
        rep.check("risk-reward-report::meta_report_type",
                  meta.get("report_type") == RX.RT_RISK_REWARD_BALANCE,
                  "meta.report_type must be {!r} (got {!r})".format(
                      RX.RT_RISK_REWARD_BALANCE, meta.get("report_type")),
                  code=C.REWARD_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-risk-reward", pack=args.pack, strict=strict,
                            status=rep.status,
                            record_count=len(entries) if isinstance(entries, list) else 0,
                            report_type="wf.reward.risk_reward_check.v1",
                            records_total=len(entries) if isinstance(entries, list) else 0))
    rep.write(REPO_ROOT / REPORT_REL, "validate_risk_reward_report.json")
    rep.print_summary("validate-risk-reward")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
