#!/usr/bin/env python3
"""validate_tactical_save_load.py — v2.4 Wave 5 tactical save/load gate (Agent 6).

Builds a TacticalSaveState for every scenario from its runtime decision bundle, proves the
save round-trips (save, reload from the same evidence, compare hashes), validates each
against tactical_contracts, and writes it. A roundtrip_ok save must carry a hash for every
tactical NPC and every active decision — a save/load claim with no tactical hashes cannot
pass. Coverage: 24 save states.

Deliverables:
    procedural/reports/tactical/save_load/*.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_tactical_save_load.py --strict
Reports -> procedural/reports/tactical/save_load/validate_tactical_save_load_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
import tactical_runtime as RT
import tactical_spec as SP
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

DECISIONS_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "decisions"
SAVE_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "save_load"


def validate(rep):
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = {s["scenario_id"]: s for s in SP.scenario_plan()}
    bundles = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(DECISIONS_DIR.glob("*.json")) if not p.stem.startswith("validate_")}
    rep.check("count::bundles_24", len(bundles) == SP.EXPECTED_SCENARIO_COUNT,
              "need 24 decision bundles (run the runtime first); got {}".format(len(bundles)),
              code=F.TACTICAL_SAVE_LOAD_MISSING)
    n = 0
    for sid, bundle in bundles.items():
        scenario = scenarios.get(sid)
        if scenario is None:
            rep.check("sl::{}::known_scenario".format(sid), False,
                      "decision bundle for unknown scenario", code=F.TACTICAL_SAVE_LOAD_FAILED)
            continue
        n += 1
        squad = SP.squad_for(scenario)
        ss = RT.build_save_state(scenario, bundle, squad)
        fails = [c for c in TC.validate_tactical_save_state(ss, strict=True) if not c[1]]
        rep.check("sl::{}::valid".format(sid), len(fails) == 0,
                  "save state invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_SAVE_LOAD_FAILED)
        # genuine roundtrip proof
        rep.check("sl::{}::roundtrip".format(sid),
                  RT.save_state_roundtrip_ok(scenario, bundle, squad),
                  "save/load did not round-trip (hashes differ)", code=F.TACTICAL_SAVE_LOAD_FAILED)
        # every tactical NPC has a state hash
        npc_ids = {npc["npc_id"] for npc in squad}
        have = set(ss.get("npc_state_hashes") or {})
        rep.check("sl::{}::all_npcs_hashed".format(sid), npc_ids <= have,
                  "missing npc state hashes: {}".format(sorted(npc_ids - have)),
                  code=F.TACTICAL_SAVE_LOAD_MISSING)
        (SAVE_DIR / (ss["save_state_id"] + ".json")).write_text(
            json.dumps(ss, indent=2, sort_keys=True), encoding="utf-8")
    rep.check("count::save_states_24", n == SP.EXPECTED_SCENARIO_COUNT,
              "must produce 24 save states (got {})".format(n), code=F.TACTICAL_SAVE_LOAD_MISSING)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical save/load gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_save_load", strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-tactical-save-load", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.save_load.v1"))
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(SAVE_DIR, "validate_tactical_save_load_report.json")
    rep.print_summary("validate-tactical-save-load")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
