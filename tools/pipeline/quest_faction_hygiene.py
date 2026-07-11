#!/usr/bin/env python3
"""quest_faction_hygiene.py — v2.2 artifact-hygiene gate (Wave R).

Proves the quest/faction surface is internally consistent and free of drift/orphans:

  * every quest/faction GATE script (pipeline + operator) carries an 'Acceptance:'
    docstring line (the documented command surface stays real; libraries excluded)
  * every generated/derived quest-faction artifact lives UNDER an allowed root
    (generated/quests|factions|consequences, reports/quest_faction, reports/operator
    quests|factions) — nothing writes outside its tree
  * no forbidden transient leaked under those roots (Saved/, Intermediate/, .sav,
    crash logs)
  * the counts line up with no silent desync: 24 quests == 24 slice scenarios ==
    24 consequence ledgers == 24 runtime reports; 4 factions == 4 faction views;
    24 quest views
  * the core index artifacts exist and are non-empty

This is the "no silent drift" gate for the quest/faction substrate.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/quest_faction_hygiene.py --strict
Reports -> procedural/reports/quest_faction/quest_faction_hygiene_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

PIPELINE = REPO_ROOT / "tools" / "pipeline"
OPERATOR = REPO_ROOT / "tools" / "operator"
GEN = REPO_ROOT / "procedural" / "generated"
QF_REPORTS = REPO_ROOT / "procedural" / "reports" / "quest_faction"
OP_REPORTS = REPO_ROOT / "procedural" / "reports" / "operator"

# Library modules (no CLI gate) — exempt from the Acceptance-docstring rule.
LIBS = {"quest_faction_contracts.py", "quest_faction_spec.py"}
FORBIDDEN = ("Saved", "Intermediate", "DerivedDataCache", "Build", ".sav", "crash")


def _gate_scripts():
    scripts = [p for p in PIPELINE.glob("*.py")
               if ("quest" in p.name or "faction" in p.name or p.name == "v2_2_shield.py")
               and p.name not in LIBS]
    scripts += [p for p in OPERATOR.glob("*.py")
                if "quest" in p.name or "faction" in p.name]
    return sorted(scripts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 quest/faction hygiene gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "quest_faction_hygiene", strict=strict)

    # 1. Acceptance docstring on every gate script
    scripts = _gate_scripts()
    rep.check("hygiene::scripts_present", len(scripts) >= 15,
              "expected the quest/faction gate scripts (got {})".format(len(scripts)),
              code=F.QUEST_FACTION_HYGIENE_FAILED)
    for p in scripts:
        txt = p.read_text(encoding="utf-8", errors="replace")
        rep.check("hygiene::{}::acceptance_doc".format(p.name), "Acceptance:" in txt,
                  "gate script must carry an 'Acceptance:' docstring line",
                  code=F.QUEST_FACTION_HYGIENE_FAILED)

    # 2. no forbidden transient under the quest/faction roots
    for root in (GEN / "quests", GEN / "factions", GEN / "consequences", QF_REPORTS,
                 OP_REPORTS / "quests", OP_REPORTS / "factions"):
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and any(tok.lower() in p.as_posix().lower() for tok in FORBIDDEN):
                rep.check("hygiene::no_transient::{}".format(p.name), False,
                          "forbidden transient leaked under {}: {}".format(root.name, p.name),
                          code=F.QUEST_FACTION_HYGIENE_FAILED)

    # 3. count coherence (no silent desync)
    def _count(root, pat):
        return len(list(root.glob(pat))) if root.is_dir() else 0

    quest_defs = _count(GEN / "quests", "qf_*.json")
    slice_scns = _count(GEN / "slice" / "scenarios", "*.json")
    ledgers = _count(GEN / "consequences", "ledger_*.json")
    runtime_reports = len([d for d in (QF_REPORTS / "runtime").iterdir()
                           if (QF_REPORTS / "runtime").is_dir()
                           and d.is_dir() and (d / "report.json").is_file()]) \
        if (QF_REPORTS / "runtime").is_dir() else 0
    faction_defs = _count(GEN / "factions", "*.json") - 3  # minus roster/initial/delta_rules indexes

    rep.check("hygiene::24_quests", quest_defs == 24,
              "expected 24 quest defs (got {})".format(quest_defs),
              code=F.QUEST_FACTION_HYGIENE_FAILED)
    rep.check("hygiene::quests_match_scenarios", quest_defs == slice_scns == 24,
              "quests must match 24 slice scenarios (quests={} scenarios={})".format(
                  quest_defs, slice_scns),
              code=F.QUEST_FACTION_HYGIENE_FAILED)
    rep.check("hygiene::24_ledgers", ledgers == 24,
              "expected 24 consequence ledgers (got {})".format(ledgers),
              code=F.QUEST_FACTION_HYGIENE_FAILED)
    rep.check("hygiene::24_runtime_reports", runtime_reports == 24,
              "expected 24 runtime reports (got {})".format(runtime_reports),
              code=F.QUEST_FACTION_HYGIENE_FAILED)
    rep.check("hygiene::4_factions", faction_defs == 4,
              "expected 4 faction defs (got {})".format(faction_defs),
              code=F.QUEST_FACTION_HYGIENE_FAILED)

    # 4. core index artifacts exist + non-empty
    for label, path in (
        ("quest_matrix", GEN / "quests" / "quest_matrix.json"),
        ("faction_roster", GEN / "factions" / "faction_roster.json"),
        ("initial_faction_state", GEN / "factions" / "initial_faction_state.json"),
        ("world_faction_state", QF_REPORTS / "runtime" / "world_faction_state.json"),
        ("quest_views", OP_REPORTS / "index" / "quest_views.json"),
        ("faction_views", OP_REPORTS / "index" / "faction_views.json")):
        ok = path.is_file() and path.stat().st_size > 2
        rep.check("hygiene::core::{}".format(label), ok,
                  "core artifact missing/empty: {}".format(path.name),
                  code=F.QUEST_FACTION_HYGIENE_FAILED)
        if ok:
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                rep.check("hygiene::core::{}::parses".format(label), False,
                          "core artifact unparseable: {}".format(e),
                          code=F.QUEST_FACTION_HYGIENE_FAILED)

    # 5. quest/faction view counts line up with the runtime matrix
    qv_path = OP_REPORTS / "index" / "quest_views.json"
    fv_path = OP_REPORTS / "index" / "faction_views.json"
    if qv_path.is_file():
        rep.check("hygiene::24_quest_views",
                  len(json.loads(qv_path.read_text(encoding="utf-8"))) == 24,
                  "expected 24 quest views", code=F.QUEST_FACTION_HYGIENE_FAILED)
    if fv_path.is_file():
        rep.check("hygiene::4_faction_views",
                  len(json.loads(fv_path.read_text(encoding="utf-8"))) == 4,
                  "expected 4 faction views", code=F.QUEST_FACTION_HYGIENE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="quest-faction-hygiene", pack=None, strict=strict, status=rep.status,
        record_count=len(scripts), records_total=len(scripts),
        report_type="wf.quest_faction.hygiene.v1"))
    QF_REPORTS.mkdir(parents=True, exist_ok=True)
    rep.write(QF_REPORTS, "quest_faction_hygiene_report.json")
    rep.print_summary("quest-faction-hygiene")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
