#!/usr/bin/env python3
"""validate_generated_factions.py — v2.2 Wave 2 generated-faction authoring gate.

Re-validates every generated FactionDefinition + initial FactionState from disk
against quest_faction_contracts AND performs the cross-record resolution the
schema-only contracts cannot: 3-4 factions, all bounds valid, every relationship
target resolves to the roster, initial values within bounds, and every quest delta
rule targets a real faction (no economy/diplomacy expansion — the caps in the
contract already bound magnitude).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_generated_factions.py --strict
Reports -> procedural/reports/quest_faction/authoring/validate_generated_factions_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

FACTIONS_DIR = REPO_ROOT / "procedural" / "generated" / "factions"
QUESTS_DIR = REPO_ROOT / "procedural" / "generated" / "quests"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "authoring"


def validate(rep):
    def_files = [p for p in sorted(FACTIONS_DIR.glob("*.json"))
                 if p.name not in ("faction_roster.json", "initial_faction_state.json",
                                   "faction_delta_rules.json")]
    faction_ids = {p.stem for p in def_files}
    rep.check("factions::count_in_range",
              QF.MIN_FACTIONS <= len(def_files) <= QF.MAX_FACTIONS,
              "expected {}-{} faction definitions (got {})".format(
                  QF.MIN_FACTIONS, QF.MAX_FACTIONS, len(def_files)),
              code=F.FACTION_CONTRACT_INVALID)

    # 1. definitions
    n = 0
    for dp in def_files:
        d = json.loads(dp.read_text(encoding="utf-8"))
        n += 1
        fid = d.get("faction_id", dp.stem)
        fails = [c for c in QF.validate_faction_definition(d, strict=True) if not c[1]]
        rep.check("fd::{}::contract".format(fid), len(fails) == 0,
                  "faction definition fails contract: {}".format([c[0] for c in fails][:4]),
                  code=F.FACTION_CONTRACT_INVALID)
        rep.check("fd::{}::id_matches_file".format(fid), d.get("faction_id") == dp.stem,
                  "faction_id {} != file name {}".format(d.get("faction_id"), dp.stem),
                  code=F.FACTION_UNKNOWN_ID)

    # 2. initial states
    initp = FACTIONS_DIR / "initial_faction_state.json"
    rep.check("factions::initial_state_present", initp.is_file(),
              "initial_faction_state.json missing", code=F.FACTION_STATE_INVALID)
    if initp.is_file():
        initial = json.loads(initp.read_text(encoding="utf-8"))
        states = initial.get("states", {})
        rep.check("factions::initial_covers_roster",
                  set(states.keys()) == faction_ids,
                  "initial states must cover exactly the roster (got {})".format(
                      sorted(states.keys())),
                  code=F.FACTION_STATE_INVALID)
        for fid, st in states.items():
            sfails = [c for c in QF.validate_faction_state(st, strict=True) if not c[1]]
            rep.check("fs::{}::contract".format(fid), len(sfails) == 0,
                      "initial state fails contract: {}".format([c[0] for c in sfails][:4]),
                      code=F.FACTION_STATE_INVALID)
            # every relationship target resolves to another roster faction
            for other in (st.get("relationships") or {}):
                rep.check("fs::{}::rel_resolves::{}".format(fid, other),
                          other in faction_ids and other != fid,
                          "relationship target {} not a distinct roster faction".format(other),
                          code=F.FACTION_RELATIONSHIP_INVALID)

    # 3. quest delta rules target real factions (no unknown/unbounded targets)
    for qp in sorted(QUESTS_DIR.glob("*.json")):
        if qp.name == "quest_matrix.json":
            continue
        q = json.loads(qp.read_text(encoding="utf-8"))
        for rule in q.get("faction_delta_rules", []):
            tid = rule.get("target_faction_id")
            rep.check("delta::{}::target_resolves::{}".format(q["quest_id"], tid),
                      tid in faction_ids,
                      "quest delta rule targets unknown faction {}".format(tid),
                      code=F.FACTION_UNKNOWN_ID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 generated-faction authoring gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-generated-factions", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.generated_faction_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_generated_factions_report.json")
    rep.print_summary("validate-generated-factions")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
