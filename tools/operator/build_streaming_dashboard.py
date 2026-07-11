#!/usr/bin/env python3
"""build_streaming_dashboard.py — v2.3 Wave 5 operator region/tile dashboard.

Renders the Wave-5 streaming index into a static site under
procedural/reports/operator/regions|tiles:

  regions/index.html          region list (layout / status / scenarios)
  regions/<region_id>.html    tile graph, anchors, cross-tile routes, status panels
  tiles/index.html            tile list (role / neighbors / runtime status)
  tiles/<tile_id>.html        role, neighbors, anchors, lifecycle reports, budget

Derived from the contract-validated views; does not re-assert status. FAIL-CLOSED:
absent region_views.json / tile_views.json -> RED.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_streaming_dashboard.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_view as V
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
REGIONS_OUT = REPO_ROOT / "procedural" / "reports" / "operator" / "regions"
TILES_OUT = REPO_ROOT / "procedural" / "reports" / "operator" / "tiles"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "operator"


def _page(title, body, sha, back=None):
    html = V.page(title, body, subtitle="v2.3 StreamingForge / WorldScaleForge",
                  git_sha=sha, back=back)
    return html.replace("WorldForge v2.1 OperatorForge", "WorldForge v2.3 OperatorForge")


def _write(path, html):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _git_sha():
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _region_page(rv, sha):
    b = V.kv("runtime", V.badge(rv["runtime_status_summary"]))
    b += V.kv("budgets", V.badge(rv["budget_status_summary"]))
    b += V.kv("save/load", V.badge(rv["save_load_status_summary"]))
    b += V.kv("quest/faction", V.badge(rv["quest_faction_status_summary"]))
    b += V.kv("cross-tile routes", ", ".join(rv["cross_tile_routes"]))
    b += "<h2>tiles</h2><table><tr><th>tile</th><th>neighbors</th></tr>"
    for t, nb in rv["tile_graph"].items():
        b += "<tr><td>{}</td><td>{}</td></tr>".format(
            V.link("../tiles/{}.html".format(t), t), V.esc(", ".join(nb)))
    b += "</table>"
    b += "<h2>streaming scenarios ({})</h2><p>{}</p>".format(
        len(rv["streaming_scenarios"]), V.esc(", ".join(rv["streaming_scenarios"])))
    return _page("region {}".format(rv["region_id"]), b, sha, back=("index.html", "regions"))


def _tile_page(tv, sha):
    b = V.kv("region", V.link("../regions/{}.html".format(tv["region_id"]), tv["region_id"]))
    b += V.kv("role", V.badge(tv["tile_role"]))
    b += V.kv("map", V.esc(tv["map_id"]))
    b += V.kv("runtime", V.badge(tv["runtime_status"]))
    b += V.kv("neighbors", ", ".join(tv["neighbors"]))
    b += V.kv("anchors", str(len(tv["anchors"])))
    b += V.kv("budget", ", ".join(tv["budget_reports"]))
    b += "<h2>lifecycle reports ({})</h2><p>{}</p>".format(
        len(tv["lifecycle_reports"]),
        V.esc(", ".join(Path(p).name for p in tv["lifecycle_reports"])) or "(none)")
    return _page("tile {}".format(tv["tile_id"]), b, sha, back=("index.html", "tiles"))


def build(rep, sha):
    rvp, tvp = INDEX_DIR / "region_views.json", INDEX_DIR / "tile_views.json"
    rep.check("dash::region_views_present", rvp.is_file(),
              "region_views.json missing", code=F.STREAMING_OPERATOR_VIEW_INVALID)
    rep.check("dash::tile_views_present", tvp.is_file(),
              "tile_views.json missing", code=F.STREAMING_OPERATOR_VIEW_INVALID)
    if not (rvp.is_file() and tvp.is_file()):
        return 0
    region_views = json.loads(rvp.read_text(encoding="utf-8"))
    tile_views = json.loads(tvp.read_text(encoding="utf-8"))

    rows = ""
    for rv in sorted(region_views, key=lambda v: v["region_id"]):
        rows += "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            V.link("{}.html".format(rv["region_id"]), rv["region_id"]),
            V.badge(rv["runtime_status_summary"]), str(len(rv["streaming_scenarios"])))
    _write(REGIONS_OUT / "index.html", _page(
        "regions ({})".format(len(region_views)),
        "<table><tr><th>region</th><th>runtime</th><th>scenarios</th></tr>{}</table>".format(rows),
        sha, back=("../dashboard/index.html", "dashboard")))
    for rv in region_views:
        _write(REGIONS_OUT / "{}.html".format(rv["region_id"]), _region_page(rv, sha))

    trows = ""
    for tv in sorted(tile_views, key=lambda v: v["tile_id"]):
        trows += "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            V.link("{}.html".format(tv["tile_id"]), tv["tile_id"]),
            V.badge(tv["tile_role"]), V.badge(tv["runtime_status"]))
    _write(TILES_OUT / "index.html", _page(
        "tiles ({})".format(len(tile_views)),
        "<table><tr><th>tile</th><th>role</th><th>runtime</th></tr>{}</table>".format(trows),
        sha, back=("../dashboard/index.html", "dashboard")))
    for tv in tile_views:
        _write(TILES_OUT / "{}.html".format(tv["tile_id"]), _tile_page(tv, sha))

    rep.check("dash::region_pages", all((REGIONS_OUT / "{}.html".format(v["region_id"])).is_file()
                                        for v in region_views),
              "all region pages must be written", code=F.STREAMING_OPERATOR_VIEW_INVALID)
    rep.check("dash::tile_pages", all((TILES_OUT / "{}.html".format(v["tile_id"])).is_file()
                                      for v in tile_views),
              "all tile pages must be written", code=F.STREAMING_OPERATOR_VIEW_INVALID)
    return len(region_views) + len(tile_views)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 operator streaming dashboard.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "streaming_operator_dashboard", strict=strict)
    n = build(rep, _git_sha())
    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-streaming-dashboard", pack=None, strict=strict, status=rep.status,
        record_count=n, records_total=n, report_type="wf.streaming.operator_dashboard.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "build_streaming_dashboard_report.json")
    rep.print_summary("operator-streaming-dashboard")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
