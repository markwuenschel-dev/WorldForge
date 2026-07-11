#!/usr/bin/env python3
"""build_tactical_dashboard.py — v2.4 Wave 6 operator tactical dashboard (Agent 7).

Renders a static, self-contained HTML dashboard over the operator tactical index: the 24
scenarios (region, profile, roles, decision summary, action coverage, save/load + budget
status) and the matrix-wide action-coverage roll-up. Local/static control-plane view only —
no server, no player-facing UI. Reads scenario_views.json + npc_views.json + tactical_index.json.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_tactical_dashboard.py --strict
Reports -> procedural/reports/operator/tactical/build_tactical_dashboard_report.json
"""

import argparse
import html
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


def _load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _row(sv):
    e = html.escape
    cov = ", ".join("{}×{}".format(e(a), n) for a, n in sorted((sv.get("action_coverage") or {}).items()))
    ds = sv.get("decision_summary") or {}
    return (
        "<tr><td>{sid}</td><td>{region}</td><td>{profile}</td><td>{roles}</td>"
        "<td>{total}/{valid}/{invalid}</td><td class='cov'>{cov}</td>"
        "<td>{cover}</td><td>{flank}</td><td>{retreat}</td><td>{obj}</td>"
        "<td>{coord}</td><td>{sl}</td><td>{bud}</td></tr>"
    ).format(
        sid=e(sv.get("scenario_id", "")), region=e(sv.get("region_id", "")),
        profile=e(sv.get("tactical_profile_id", "")),
        roles=e(", ".join(sv.get("roles_present") or [])),
        total=ds.get("total", "-"), valid=ds.get("valid", "-"), invalid=ds.get("invalid", "-"),
        cov=cov, cover=e(sv.get("cover_usage", "")), flank=e(sv.get("flank_usage", "")),
        retreat=e(sv.get("retreat_usage", "")), obj=e(sv.get("objective_pressure", "")),
        coord=e(sv.get("group_coordination", "")), sl=e(sv.get("save_load_status", "")),
        bud=e(sv.get("budget_status", "")))


def build(rep):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svs = _load(OUT_DIR / "scenario_views.json")
    nvs = _load(OUT_DIR / "npc_views.json")
    index = _load(OUT_DIR / "tactical_index.json")
    rep.check("dash::inputs_present", svs is not None and nvs is not None and index is not None,
              "operator tactical index missing (run operator-tactical-index)",
              code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    if svs is None or index is None:
        return 0
    rep.check("dash::scenario_views_24", len(svs) == 24,
              "expected 24 scenario views (got {})".format(len(svs)),
              code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    missing = sorted(set(TC.REQUIRED_COVERAGE_ACTIONS) - set(index.get("action_coverage") or []))
    rep.check("dash::action_coverage_complete", not missing,
              "dashboard action coverage incomplete: {}".format(missing),
              code=F.TACTICAL_ACTION_COVERAGE_MISSING)

    rows = "\n".join(_row(sv) for sv in sorted(svs, key=lambda v: v.get("scenario_id", "")))
    cov = " ".join("<span class='pill'>{}</span>".format(html.escape(a))
                   for a in sorted(index.get("action_coverage") or []))
    doc = """<!doctype html><html><head><meta charset="utf-8">
<title>WorldForge v2.4 TacticalBehaviorForge — Operator Dashboard</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;color:#1a1a1a;background:#fafafa}}
 h1{{font-size:1.4rem}} .sub{{color:#666}}
 table{{border-collapse:collapse;width:100%;margin-top:1rem;background:#fff}}
 th,td{{border:1px solid #ddd;padding:.35rem .5rem;text-align:left;font-size:12px;vertical-align:top}}
 th{{background:#2d3748;color:#fff;position:sticky;top:0}}
 td.cov{{max-width:280px;color:#444}}
 .pill{{display:inline-block;background:#2d3748;color:#fff;border-radius:10px;padding:.1rem .55rem;margin:.1rem;font-size:12px}}
 tr:nth-child(even){{background:#f4f6f8}}
</style></head><body>
<h1>WorldForge v2.4 — AdvancedAIForge / TacticalBehaviorForge</h1>
<p class="sub">Bounded tactical-behavior substrate · {sc} scenarios · {nc} NPCs ·
runtime mode: deterministic_tactical_simulation (alpha, not live UE AI) ·
local/static control-plane view</p>
<p><strong>Matrix action coverage:</strong> {cov}</p>
<table><thead><tr>
<th>Scenario</th><th>Region</th><th>Profile</th><th>Roles</th><th>Dec (t/v/i)</th>
<th>Action coverage</th><th>Cover</th><th>Flank</th><th>Retreat</th><th>Objective</th>
<th>Coord</th><th>Save/Load</th><th>Budget</th>
</tr></thead><tbody>
{rows}
</tbody></table>
</body></html>""".format(sc=index.get("scenario_count", len(svs)),
                         nc=index.get("npc_count", len(nvs or [])), cov=cov, rows=rows)
    (OUT_DIR / "dashboard.html").write_text(doc, encoding="utf-8")
    return len(svs)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 operator tactical dashboard.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_operator_dashboard", strict=strict)
    n = build(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-tactical-dashboard", pack=None, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.operator_dashboard.v1"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(OUT_DIR, "build_tactical_dashboard_report.json")
    rep.print_summary("operator-tactical-dashboard")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
