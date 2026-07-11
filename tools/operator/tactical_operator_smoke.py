#!/usr/bin/env python3
"""tactical_operator_smoke.py — v2.4 Wave 6 operator link-resolution smoke (Agent 7).

Proves the operator tactical views are INSPECTABLE: every scenario view and NPC view
re-validates against its contract, and every linked path it advertises (decision traces,
state deltas, save state, budget report) resolves to a real file on disk. A view that
advertises a broken decision-trace link is a fake-green inspectability vector and turns
this gate RED. Coverage: 24 scenario views + 48 NPC views.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/tactical_operator_smoke.py --strict
Reports -> procedural/reports/operator/tactical/tactical_operator_smoke_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

OUT_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "tactical"


def _load_list(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def smoke(rep):
    sv_list = _load_list(OUT_DIR / "scenario_views.json")
    nv_list = _load_list(OUT_DIR / "npc_views.json")
    rep.check("index::scenario_views_present", sv_list is not None,
              "scenario_views.json missing (run operator-tactical-index)",
              code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    rep.check("index::npc_views_present", nv_list is not None,
              "npc_views.json missing (run operator-tactical-index)",
              code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    sv_list, nv_list = sv_list or [], nv_list or []
    rep.check("count::scenario_views_24", len(sv_list) == 24,
              "expected 24 scenario views (got {})".format(len(sv_list)),
              code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    rep.check("count::npc_views_48", len(nv_list) == 48,
              "expected 48 NPC views (got {})".format(len(nv_list)),
              code=F.TACTICAL_OPERATOR_VIEW_INVALID)

    n = 0
    for sv in sv_list:
        n += 1
        sid = sv.get("scenario_id")
        fails = [c for c in TC.validate_operator_tactical_scenario_view(sv, strict=True) if not c[1]]
        rep.check("sv::{}::valid".format(sid), len(fails) == 0,
                  "scenario view invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_OPERATOR_VIEW_INVALID)
        for link in sv.get("decision_trace_paths") or []:
            rep.check("sv::{}::trace_link_resolves".format(sid), (REPO_ROOT / link).is_file(),
                      "broken decision-trace link: {}".format(link),
                      code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    for nv in nv_list:
        n += 1
        nid = nv.get("npc_id")
        fails = [c for c in TC.validate_operator_tactical_npc_view(nv, strict=True) if not c[1]]
        rep.check("nv::{}::valid".format(nid), len(fails) == 0,
                  "npc view invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_OPERATOR_VIEW_INVALID)
        links = (list(nv.get("decision_trace_paths") or []) + list(nv.get("state_delta_paths") or [])
                 + [nv.get("save_state_path"), nv.get("budget_report_path")])
        for link in links:
            rep.check("nv::{}::link_resolves::{}".format(nid, link),
                      bool(link) and (REPO_ROOT / link).is_file(),
                      "broken operator link: {}".format(link),
                      code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 operator tactical link-resolution smoke.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_operator_smoke", strict=strict)
    n = smoke(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-tactical-smoke", pack=None, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.operator_smoke.v1"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(OUT_DIR, "tactical_operator_smoke_report.json")
    rep.print_summary("operator-tactical-smoke")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
