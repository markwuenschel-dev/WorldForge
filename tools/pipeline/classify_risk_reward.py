#!/usr/bin/env python3
"""classify_risk_reward.py — WorldForge v1.9 risk/reward balance rollup + gate.

For every authoring scenario in the reward_forge spine, emits the deterministic
risk/reward classification the reward table produced (value vs budget, risk band)
and rolls it up into ``procedural/reports/rewards/balance/risk_reward_report.json``
with a canonical ``meta`` block (build_meta, report_type
``RX.RT_RISK_REWARD_BALANCE``).

This script both WRITES the balance report and GATES it: it asserts (as
ValidationReport checks) that baseline tables classify ``baseline_reward``, high
tables classify ``high_risk_high_reward``, and NO scenario lands in a blocking
class (``over_rewarded`` / ``exploit_suspected`` / ``invalid``). It exits non-zero
if any classification is blocking or inconsistent — a fabricated green is
impossible because the classes come straight from the spine and are re-checked
here.

Acceptance: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/classify_risk_reward.py --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
import reward_forge as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

REPORT_REL = "procedural/reports/rewards/balance"
C = FailureCode

# Expected class per reward-table risk_band — the balance contract this gate holds.
_EXPECTED_CLASS = {"baseline": "baseline_reward", "high": "high_risk_high_reward"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    scenarios = F.build_authoring_scenarios()
    entries = []

    rep.check("risk-reward::nonzero", len(scenarios) > 0,
              "expected >=1 authoring scenario, got {}".format(len(scenarios)),
              code=C.RISK_REWARD_CLASSIFICATION_INVALID)

    for s in scenarios:
        cl = s["classification"]
        entry = {
            "scenario_id": s["scenario_id"],
            "reward_table_id": cl["reward_table_id"],
            "risk_band": cl["risk_band"],
            "reward_value": cl["reward_value"],
            "budget_min": cl["budget_min"],
            "budget_max": cl["budget_max"],
            "risk_reward_class": cl["risk_reward_class"],
            "exploit_result": cl["exploit_result"],
        }
        entries.append(entry)
        rrc = cl["risk_reward_class"]
        band = cl["risk_band"]

        rep.check("risk-reward::{}::class_known".format(s["scenario_id"]),
                  rrc in RX.RISK_REWARD_CLASSES,
                  "risk_reward_class {!r} not in registry".format(rrc),
                  code=C.RISK_REWARD_CLASSIFICATION_INVALID)
        rep.check("risk-reward::{}::not_blocking".format(s["scenario_id"]),
                  rrc not in RX.BLOCKING_RISK_REWARD_CLASSES,
                  "scenario classifies as blocking class {!r}".format(rrc),
                  code=C.RISK_REWARD_CLASSIFICATION_INVALID)
        rep.check("risk-reward::{}::exploit_clean".format(s["scenario_id"]),
                  cl["exploit_result"] in RX.EXPLOIT_RESULTS and cl["exploit_result"] != "confirmed",
                  "exploit_result {!r} not clean/known".format(cl["exploit_result"]),
                  code=C.REWARD_EXPLOIT_DETECTED)
        if band in _EXPECTED_CLASS:
            rep.check("risk-reward::{}::band_class_match".format(s["scenario_id"]),
                      rrc == _EXPECTED_CLASS[band],
                      "risk_band {!r} expected class {!r}, got {!r}".format(
                          band, _EXPECTED_CLASS[band], rrc),
                      code=C.RISK_REWARD_CLASSIFICATION_INVALID)

    rep.finalize()
    rep.set_meta(build_meta(command="classify-risk-reward", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(entries),
                            report_type=RX.RT_RISK_REWARD_BALANCE,
                            records_total=len(entries)))

    # Write the balance rollup: the ValidationReport shell (meta + checks) PLUS the
    # per-scenario classification entries the validator downstream consumes.
    d = rep.to_dict()
    d["report_type"] = RX.RT_RISK_REWARD_BALANCE
    d["scenarios"] = entries
    out_dir = REPO_ROOT / REPORT_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "risk_reward_report.json").write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rep.print_summary("classify-risk-reward")
    print("[classify-risk-reward] {} scenario(s) classified -> {}/risk_reward_report.json".format(
        len(entries), REPORT_REL))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
