#!/usr/bin/env python3
"""_reward_contract_gate.py — shared dogfood engine for the v1.9 contract gates.

The loadout / reward / progression contract gates all dogfood the same way: for
each contract in their lane, the canonical valid example MUST pass under STRICT,
and the paired known-bad example MUST fail. A contract that accepts its own
known-bad is a fake-green vector and fails the gate. This module holds the one
implementation; the three ``validate_{loadout,reward,progression}_contracts.py``
entry points call it with their lane key.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

# The failure code each lane tags its schema failures with.
_LANE_CODE = {
    "loadout": FailureCode.LOADOUT_CONTRACT_INVALID,
    "reward": FailureCode.REWARD_CONTRACT_INVALID,
    "progression": FailureCode.PROGRESSION_STATE_INVALID,
}
_LANE_REPORT_DIR = {
    "loadout": "procedural/reports/rewards/contracts",
    "reward": "procedural/reports/rewards/contracts",
    "progression": "procedural/reports/progression/contracts",
}
_LANE_REPORT_TYPE = {
    "loadout": "wf.v1_9.loadout_schema_check.v1",
    "reward": "wf.v1_9.reward_schema_check.v1",
    "progression": "wf.v1_9.progression_schema_check.v1",
}


def run_gate(lane, command, pack, strict, report_filename):
    """Dogfood every contract in ``lane`` and write the lane report. Returns exit code."""
    code = _LANE_CODE[lane]
    names = RX.CONTRACT_GROUPS[lane]
    rep = ValidationReport("pack", pack, strict=strict)

    for name in names:
        validate, good_fn, bad_fn = RX.CONTRACTS[name]
        good = good_fn()
        bad = bad_fn()
        good_fails = [c for c in validate(good, strict=True) if not c[1]]
        bad_fails = [c for c in validate(bad, strict=True) if not c[1]]
        rep.check("{}::valid_passes".format(name), not good_fails,
                  "valid {} passes strict ({})".format(
                      name, "0 fail" if not good_fails else [c[0] for c in good_fails][:4]),
                  code=code)
        rep.check("{}::known_bad_fails".format(name), len(bad_fails) > 0,
                  "known-bad {} is rejected".format(name), code=code)

    rep.finalize()
    rep.set_meta(build_meta(command=command, pack=pack, strict=strict, status=rep.status,
                            record_count=len(names), report_type=_LANE_REPORT_TYPE[lane]))
    out = REPO_ROOT / _LANE_REPORT_DIR[lane]
    rep.write(out, report_filename)
    rep.print_summary(command)
    print("[{}] {} contracts dogfooded".format(command, len(names)))
    return rep.exit_code
