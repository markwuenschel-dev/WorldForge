#!/usr/bin/env python3
"""generate_reward_tables.py — WorldForge v1.9 reward-table generator.

Materializes the deterministic reward tables from the reward_forge spine (one per
mission_archetype x risk_band = 12 tables) to
``procedural/generated/rewards/tables/{reward_table_id}.json``. Every table is
validated against ``RX.validate_reward_table`` under STRICT with zero failures
BEFORE it is written; a table its own contract rejects is a bug, never written.

Report -> ``procedural/reports/rewards/tables/generate_reward_tables_report.json``.

Acceptance: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_reward_tables.py --strict`.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
import reward_forge as F
from npc_gen_common import run_generator
from report_meta import strict_from_env
from failure_codes import FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    tables = F.build_reward_tables()

    run_generator("generate-reward-tables", args.pack, tables,
                  RX.validate_reward_table, RX.REWARD_TABLE_GENERATED_REL, "reward_table_id",
                  "procedural/reports/rewards/tables", "generate_reward_tables_report.json",
                  RX.RT_REWARD_TABLE, FailureCode.REWARD_TABLE_INVALID, strict=strict)


if __name__ == "__main__":
    main()
