#!/usr/bin/env python3
"""validate_operator_evidence.py — v2.1 operator evidence-view gate (Wave 3).

Proves the browsable cards cannot over-claim their evidence. A scenario card is a
DERIVED roll-up of the evidence graph; this gate re-checks that derivation against
both the graph and the disk, so a card can never show 'pass' where the trace is
not pass, or a report path the filesystem does not have.

FAIL-CLOSED: absent pack_cards.json / scenario_cards.json -> RED.

Checks:
  * every OperatorPackCard / OperatorScenarioCard validates against its contract
  * every card facet status EQUALS the corresponding evidence-graph verdict
    (card over-claim -> WF721 OPERATOR_EVIDENCE_TRACE_INVALID)
  * a card claiming runtime_status=pass carries report_paths + telemetry_paths that
    EXIST on disk (WF714 OPERATOR_REPORT_PATH_MISSING)
  * every scenario in the manifest has exactly one card (no missing/duplicate)

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/validate_operator_evidence.py --strict
Reports -> procedural/reports/operator/index/validate_operator_evidence_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
MANIFEST = REPO_ROOT / "procedural/generated/slice/manifest.json"

# scenario-card facet -> the evidence-graph claim that certifies it.
FACET_CLAIM = {
    "runtime_status": "scenario completed",
    "traversal_status": "grounded traversal succeeded",
    "npc_status": "npc pressure occurred",
    "combat_status": "combat damage occurred",
    "reward_status": "reward granted",
    "save_load_status": "save/load roundtrip passed",
    "package_status": "package includes map",
}


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator evidence-view gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("operator", "evidence_view", strict=strict)

    scn_file = INDEX_DIR / "scenario_cards.json"
    pack_file = INDEX_DIR / "pack_cards.json"
    graph_file = INDEX_DIR / "evidence_graph.json"
    for label, f in (("scenario_cards", scn_file), ("pack_cards", pack_file),
                     ("evidence_graph", graph_file)):
        rep.check("{}_present".format(label), f.is_file(),
                  "{} missing — run operator-dashboard/operator-index-reports".format(f.name),
                  code=F.OPERATOR_MISSING_EVIDENCE)
    if not (scn_file.is_file() and pack_file.is_file() and graph_file.is_file()):
        rep.finalize()
        rep.set_meta(build_meta("operator-evidence-view", pack=None, strict=strict,
                                status=rep.status, record_count=0, records_total=0,
                                report_type="wf.operator.evidence_view.v1"))
        rep.write(INDEX_DIR, "validate_operator_evidence_report.json")
        rep.print_summary("operator-evidence-view")
        sys.exit(rep.exit_code)

    scenario_cards = _load(scn_file)
    pack_cards = _load(pack_file)
    graph = _load(graph_file)
    manifest = _load(MANIFEST) if MANIFEST.is_file() else {"scenarios": []}

    # graph verdicts keyed by (scenario_id, claim)
    verdict = {}
    for t in graph.get("traces", []):
        verdict[(t.get("scenario_id"), t.get("claim"))] = t.get("verdict")

    # pack cards schema
    for pc in pack_cards:
        pfails = [c for c in OX.validate_pack_card(pc, strict=strict) if not c[1]]
        rep.check("pack::{}::schema".format(pc.get("pack_id")), len(pfails) == 0,
                  "pack card schema failures: {}".format([c[0] for c in pfails][:3]),
                  code=F.OPERATOR_PACK_INDEX_INVALID)

    # scenario cards schema + graph agreement + disk
    seen = {}
    for card in scenario_cards:
        ssid = card.get("scenario_id")
        seen[ssid] = seen.get(ssid, 0) + 1
        cfails = [c for c in OX.validate_scenario_card(card, strict=strict) if not c[1]]
        rep.check("scn::{}::schema".format(ssid), len(cfails) == 0,
                  "scenario card schema failures: {}".format([c[0] for c in cfails][:3]),
                  code=F.OPERATOR_SCENARIO_CARD_INVALID)
        # every facet must equal the graph verdict for its claim.
        for facet, claim in FACET_CLAIM.items():
            gv = verdict.get((ssid, claim), "absent")
            cv = card.get(facet)
            rep.check("scn::{}::{}::matches_graph".format(ssid, facet), cv == gv,
                      "card {}={!r} but graph verdict for '{}' is {!r}".format(
                          facet, cv, claim, gv),
                      code=F.OPERATOR_EVIDENCE_TRACE_INVALID)
        # runtime_status=pass must have report + telemetry paths that exist.
        if card.get("runtime_status") == "pass":
            for field in ("report_paths", "telemetry_paths"):
                paths = card.get(field) or []
                rep.check("scn::{}::{}_nonempty".format(ssid, field), len(paths) > 0,
                          "runtime pass card has empty {}".format(field),
                          code=F.OPERATOR_REPORT_PATH_MISSING)
                for p in paths:
                    rep.check("scn::{}::{}::exists".format(ssid, Path(p).name),
                              (REPO_ROOT / p).is_file(),
                              "card references missing path: {}".format(p),
                              code=F.OPERATOR_REPORT_PATH_MISSING)

    # coverage: one card per manifest scenario, no dupes.
    dup = [s for s, n in seen.items() if n > 1]
    rep.check("cards::no_duplicates", not dup,
              "duplicate scenario cards: {}".format(dup[:4]),
              code=F.OPERATOR_DUPLICATE_SCENARIO_CARD)
    missing = [s for s in manifest.get("scenarios", []) if s not in seen]
    rep.check("cards::cover_manifest", not missing,
              "manifest scenarios with no card: {}".format(missing[:4]),
              code=F.OPERATOR_MISSING_EVIDENCE)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-evidence-view", pack=None, strict=strict, status=rep.status,
        record_count=len(scenario_cards), records_total=len(scenario_cards),
        report_type="wf.operator.evidence_view.v1"))
    rep.write(INDEX_DIR, "validate_operator_evidence_report.json")
    rep.print_summary("operator-evidence-view")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
