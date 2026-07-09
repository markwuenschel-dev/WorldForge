#!/usr/bin/env python3
"""validate_npc_contracts.py — WorldForge v1.7 NPCForge contract-spine gate.

Dogfoods every NPCForge / EncounterBehaviorForge contract: for each, the
canonical valid example MUST pass under STRICT, and a known-bad example MUST fail.
This proves the schemas actually constrain — a contract that accepts its own
known-bad is a fake-green vector and fails the gate.

Acceptance: ``make npc-contracts STRICT=1``.
Reports -> procedural/reports/npc/contracts/validate_npc_contracts_report.json
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    for name, (validate, good_fn, bad_fn) in NX.CONTRACTS.items():
        good = good_fn()
        bad = bad_fn()
        good_fails = [c for c in validate(good, strict=True) if not c[1]]
        bad_fails = [c for c in validate(bad, strict=True) if not c[1]]
        rep.check("{}::valid_passes".format(name), not good_fails,
                  "valid {} passes strict ({})".format(
                      name, "0 fail" if not good_fails else [c[0] for c in good_fails][:4]),
                  code=FailureCode.NPC_ARCHETYPE_SCHEMA_FAILURE)
        rep.check("{}::known_bad_fails".format(name), len(bad_fails) > 0,
                  "known-bad {} is rejected".format(name),
                  code=FailureCode.NPC_ARCHETYPE_SCHEMA_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-contracts", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(NX.CONTRACTS),
                            report_type="wf.npc.schema_check.v1"))
    out = REPO_ROOT / "procedural/reports/npc/contracts"
    rep.write(out, "validate_npc_contracts_report.json")
    rep.print_summary("validate-npc-contracts")
    print("[validate-npc-contracts] {} contracts dogfooded".format(len(NX.CONTRACTS)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
