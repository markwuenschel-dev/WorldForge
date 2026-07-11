#!/usr/bin/env python3
"""validate_faction_contracts.py — v2.2 faction contract sub-gate (Agent 2).

Dogfoods just the faction side of the spine (FactionDefinition, FactionState,
FactionDelta): every valid example passes, every known-bad is rejected for its
owning code. Runtime-free; GREEN from Wave 1.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_faction_contracts.py --strict
Reports -> procedural/reports/quest_faction/validate_faction_contracts_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from validate_quest_faction_contracts import dogfood

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction"


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 faction contract sub-gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    names = list(QF.CONTRACT_GROUPS["faction"])
    n = dogfood(rep, names)

    rep.finalize()
    rep.set_meta(build_meta(
        command="faction-contracts", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.faction_contract_spine.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_faction_contracts_report.json")
    rep.print_summary("faction-contracts")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
