#!/usr/bin/env python3
"""quest_faction_operator_smoke.py — v2.2 Wave 4 operator broken-link/smoke gate.

Proves the OperatorForge quest/faction surface is coherent and every link resolves:
  * quest_views.json + faction_views.json validate against their contracts
  * 24 quest views + 4 faction views (full coverage)
  * every consequence_ledger_path / definition_path / state_path referenced by a
    view resolves on disk (no broken evidence link)
  * every quest/faction HTML page the dashboard should have rendered exists
  * every runtime report's operator_trace_paths now resolve to a real rendered page
    (closes the loop: the runtime claimed an operator trace; it must exist)
  * a passing quest view (roundtrip_ok, no failure codes) links a real ledger and a
    real save/load proof, and each faction delta it cites is in that ledger
  * no view carries an out-of-band failure code

FAIL-CLOSED: absent views/pages -> RED.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/quest_faction_operator_smoke.py --strict
Reports -> procedural/reports/operator/quest_faction_operator_smoke_report.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import quest_faction_contracts as QF
import quest_faction_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
QUESTS_OUT = REPO_ROOT / "procedural" / "reports" / "operator" / "quests"
FACTIONS_OUT = REPO_ROOT / "procedural" / "reports" / "operator" / "factions"
RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "runtime"
SAVELOAD_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "save_load"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "operator"

_WF_CODE_RE = re.compile(r"^WF\d{3}_[A-Z0-9_]+$")


def validate(rep):
    qv_path = INDEX_DIR / "quest_views.json"
    fv_path = INDEX_DIR / "faction_views.json"
    for p, code in ((qv_path, F.QUEST_FACTION_OPERATOR_VIEW_INVALID),
                    (fv_path, F.QUEST_FACTION_OPERATOR_VIEW_INVALID)):
        rep.check("smoke::{}_present".format(p.name), p.is_file(),
                  "{} missing".format(p.name), code=code)
    if not (qv_path.is_file() and fv_path.is_file()):
        return 0
    quest_views = json.loads(qv_path.read_text(encoding="utf-8"))
    faction_views = json.loads(fv_path.read_text(encoding="utf-8"))

    rep.check("smoke::24_quest_views", len(quest_views) == QF.EXPECTED_SCENARIO_COUNT,
              "expected 24 quest views (got {})".format(len(quest_views)),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)
    rep.check("smoke::4_faction_views", len(faction_views) == len(SPEC.FACTION_IDS),
              "expected {} faction views (got {})".format(len(SPEC.FACTION_IDS), len(faction_views)),
              code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)

    n = 0
    for qv in quest_views:
        n += 1
        qid = qv["quest_id"]
        fails = [c for c in QF.validate_operator_quest_view(qv, strict=True) if not c[1]]
        rep.check("qv::{}::contract".format(qid), len(fails) == 0,
                  "quest view invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
        # HTML page exists
        rep.check("qv::{}::page".format(qid), (QUESTS_OUT / "{}.html".format(qid)).is_file(),
                  "quest page missing: {}.html".format(qid), code=F.OPERATOR_LINK_BROKEN)
        # ledger link resolves; deltas cited are in the ledger
        for lp in qv["consequence_ledger_paths"]:
            lpath = REPO_ROOT / lp
            rep.check("qv::{}::ledger_link".format(qid), lpath.is_file(),
                      "ledger link broken: {}".format(lp), code=F.CONSEQUENCE_LEDGER_MISSING)
            if lpath.is_file():
                led = json.loads(lpath.read_text(encoding="utf-8"))
                for d in qv["faction_deltas"]:
                    rep.check("qv::{}::delta_in_ledger::{}".format(qid, d),
                              d in led.get("applied_deltas", []),
                              "faction delta {} not in linked ledger".format(d),
                              code=F.FACTION_DELTA_INVALID)
        # runtime report link resolves (quest outcome must have a runtime report)
        run_id = "qfrun_" + qid[len("qf_"):]
        rep.check("qv::{}::runtime_report".format(qid),
                  (RUNTIME_DIR / run_id / "report.json").is_file(),
                  "quest outcome lacks a runtime report link", code=F.OPERATOR_LINK_BROKEN)
        # a passing view must have a real save/load proof
        if qv["save_load_status"] == "roundtrip_ok" and not qv["failure_codes"]:
            rep.check("qv::{}::save_load_proof".format(qid),
                      (SAVELOAD_DIR / (run_id + ".json")).is_file(),
                      "passing view claims roundtrip_ok but save/load proof missing",
                      code=F.QUEST_FACTION_SAVE_LOAD_MISSING)
        # no out-of-band failure code
        rep.check("qv::{}::codes_well_formed".format(qid),
                  all(_WF_CODE_RE.match(c) for c in qv["failure_codes"]),
                  "quest view carries a malformed failure code",
                  code=F.QUEST_FACTION_UNKNOWN_FAILURE_CODE)

    for fv in faction_views:
        fid = fv["faction_id"]
        fails = [c for c in QF.validate_operator_faction_view(fv, strict=True) if not c[1]]
        rep.check("fv::{}::contract".format(fid), len(fails) == 0,
                  "faction view invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
        rep.check("fv::{}::page".format(fid), (FACTIONS_OUT / "{}.html".format(fid)).is_file(),
                  "faction page missing: {}.html".format(fid), code=F.OPERATOR_LINK_BROKEN)
        # definition + state paths resolve
        rep.check("fv::{}::def_link".format(fid), (REPO_ROOT / fv["definition_path"]).is_file(),
                  "faction definition link broken: {}".format(fv["definition_path"]),
                  code=F.OPERATOR_LINK_BROKEN)
        for sp in fv["state_paths"]:
            rep.check("fv::{}::state_link".format(fid), (REPO_ROOT / sp).is_file(),
                      "faction state link broken: {}".format(sp), code=F.OPERATOR_LINK_BROKEN)

    # closes the loop: every runtime report's operator_trace_paths now resolve.
    for d in sorted(p for p in RUNTIME_DIR.iterdir()
                    if p.is_dir() and (p / "report.json").is_file()):
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        for tp in report.get("operator_trace_paths", []):
            rep.check("trace::{}::resolves".format(d.name), (REPO_ROOT / tp).is_file(),
                      "runtime operator_trace_path does not resolve: {}".format(tp),
                      code=F.OPERATOR_LINK_BROKEN)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 operator quest/faction smoke gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "quest_faction_operator_smoke", strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-quest-faction-smoke", pack=None, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.operator_smoke.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "quest_faction_operator_smoke_report.json")
    rep.print_summary("operator-quest-faction-smoke")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
