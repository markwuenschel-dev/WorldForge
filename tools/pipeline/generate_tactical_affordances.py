#!/usr/bin/env python3
"""generate_tactical_affordances.py — v2.4 Wave 2 affordance authoring (Agent 3).

Generates one TacticalAffordanceMap per scenario over the scenario's objective tile,
built from real v2.3 region/anchor/route evidence + deterministic generated cover markers.
Every record is validated against tactical_contracts before it is written.

Deliverables (handoff §14 Wave 2):
    procedural/generated/tactical/affordances/*.json
    procedural/reports/tactical/affordances/affordance_authoring_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_tactical_affordances.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
import tactical_spec as SP
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

AFF_DIR = REPO_ROOT / "procedural" / "generated" / "tactical" / "affordances"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "affordances"


def generate(rep):
    AFF_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = SP.scenario_plan()
    rep.check("count::scenarios_24", len(scenarios) == SP.EXPECTED_SCENARIO_COUNT,
              "must plan 24 scenarios (got {})".format(len(scenarios)),
              code=F.TACTICAL_AFFORDANCE_MAP_INVALID)
    n = 0
    for s in scenarios:
        am = SP.affordance_for(s)
        fails = [c for c in TC.validate_tactical_affordance_map(am, strict=True) if not c[1]]
        rep.check("aff::{}::valid".format(s["scenario_id"]), len(fails) == 0,
                  "affordance map invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_AFFORDANCE_MAP_INVALID)
        (AFF_DIR / (am["affordance_map_id"] + ".json")).write_text(
            json.dumps(am, indent=2, sort_keys=True), encoding="utf-8")
        n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical affordance authoring.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_affordance_authoring", strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-tactical-affordances", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.affordance_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "affordance_authoring_report.json")
    rep.print_summary("generate-tactical-affordances")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
