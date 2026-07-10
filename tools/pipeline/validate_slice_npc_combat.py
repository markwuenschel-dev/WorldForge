#!/usr/bin/env python3
"""validate_slice_npc_combat.py — v2.0 Agent-4 NPC + combat runtime gate.

Proves v1.7 NPC behavior and v1.8 combat participate in every slice scenario:
each SliceRuntimeReport has npc_behavior_seen == true, combat_damage_seen == true,
and damage_events > 0 (combat markers must NOT appear only in a report — real
damage must have occurred). NPCs remain v1.7/v1.8 sentry/waypoint pressure, not
tactical AI. Fail-closed RED until Wave R produces the runtime evidence.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_npc_combat.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/runtime/validate_slice_npc_combat_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
import slice_evidence as SE
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / SX.SLICE_RUNTIME_REPORTS_REL


def _facet(doc):
    de = doc.get("damage_events")
    damage_real = isinstance(de, (int, float)) and not isinstance(de, bool) and de > 0
    ok = (doc.get("npc_behavior_seen") is True
          and doc.get("combat_damage_seen") is True and damage_real)
    return ok, "npc_behavior_seen + combat_damage_seen + damage_events>0 required"


def _dogfood(rep):
    rep.check("dogfood::good_passes", _facet(SX._example_slice_runtime_report())[0],
              "reference npc/combat report failed", code=F.SLICE_REPORT_INTEGRITY_FAILED)
    for label, over in (("no_damage", {"combat_damage_seen": False}),
                        ("zero_damage_events", {"damage_events": 0}),
                        ("no_npc", {"npc_behavior_seen": False})):
        bad = SX._example_slice_runtime_report(**over)
        rep.check("dogfood::rejects_{}".format(label), not _facet(bad)[0],
                  "'{}' must fail the npc/combat facet".format(label),
                  code=F.SLICE_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice npc/combat gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)
    passed = SE.facet_gate(rep, _facet, SE.EXPECTED_SCENARIOS,
                           F.SLICE_COMBAT_EVIDENCE_MISSING, F.SLICE_PARTIAL_MATRIX)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-npc-combat", pack=args.pack, strict=strict,
                            status=rep.status, record_count=passed,
                            records_total=SE.EXPECTED_SCENARIOS, records_passed=passed,
                            report_type="wf.slice.npc_combat.v1"))
    rep.write(REPORT_DIR, "validate_slice_npc_combat_report.json")
    rep.print_summary("validate-slice-npc-combat")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
