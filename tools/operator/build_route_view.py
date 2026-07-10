#!/usr/bin/env python3
"""build_route_view.py — v2.1 OperatorForge route/walkability viewer (Wave 3).

Makes traversal/walkability evidence drillable per scenario, from the REAL v1.6z
walkability reports (procedural/reports/ground/walkability/<map>.json).

Truth boundary (handoff §7.7): grounded_manual_waypoint / grounded_worldforge_route
are valid PROVED traversal; grounded_navmesh must NOT be claimed proved — headless
UE navmesh remains an honest path_missing limit. So every view uses the proved
grounded_worldforge_route mode and the navmesh_probe_path is an explicit
'unavailable_headless' sentinel, never a fabricated proof. The RouteWalkabilityView
contract enforces that a proved objective_access is grounded-WorldForge, never
navmesh/flight/teleport — a view that violates it turns this builder RED.

Deliverables:
  index/route_walkability_views.json     (list[RouteWalkabilityView])
  dashboard/routes/index.html            (per-scenario route/walkability table)

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_route_view.py --strict
Reports -> procedural/reports/operator/index/build_route_view_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
import operator_view as V
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
MANIFEST = REPO_ROOT / "procedural/generated/slice/manifest.json"
WALK_DIR = REPO_ROOT / "procedural/reports/ground/walkability"
WALK_DIR_REL = "procedural/reports/ground/walkability"
ROUTE_CATALOG_REL = "procedural/generated/worldforge_runtime_route_catalog.json"
# Honest headless limit: no per-map navmesh probe exists (path_missing).
NAVMESH_SENTINEL = "ground/navmesh:unavailable_headless_path_missing"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _cnt(v):
    return len(v) if isinstance(v, list) else (int(v) if isinstance(v, (int, float)) else 0)


def _status(n):
    return "pass" if n == 0 else "fail"


def build_views(manifest):
    views, notes = [], []
    for ssid in sorted(manifest.get("scenarios", [])):
        rrel = "procedural/reports/slice/runtime/slice_runtime_{}.json".format(ssid)
        runtime = _load(REPO_ROOT / rrel) if (REPO_ROOT / rrel).is_file() else {}
        map_id = runtime.get("map_id", "unknown")
        walk_rel = "{}/{}.json".format(WALK_DIR_REL, map_id)
        walk = _load(REPO_ROOT / walk_rel) if (REPO_ROOT / walk_rel).is_file() else None

        if walk is None:
            slope = step = capsule = cover = 1  # unknown -> treat as failing/blocked
            walkable = 0
            walk_path = walk_rel  # recorded even if absent (validator/HTML surfaces it)
        else:
            slope = _cnt(walk.get("slope_failures"))
            step = _cnt(walk.get("step_failures"))
            capsule = _cnt(walk.get("capsule_clearance_failures"))
            cover = _cnt(walk.get("cover_intrusions"))
            walkable = _cnt(walk.get("walkable_surfaces"))
            walk_path = walk_rel

        clean = (slope == 0 and step == 0 and capsule == 0 and cover == 0 and walkable > 0)
        view = OX._example_route_walkability_view(
            map_id=map_id,
            scenario_id=ssid,
            traversal_mode="grounded_worldforge_route",   # proved mode, never navmesh
            walkability_report_path=walk_path,
            route_plan_path=ROUTE_CATALOG_REL,
            navmesh_probe_path=NAVMESH_SENTINEL,
            objective_access_status="pass" if clean else "blocked",
            cover_intrusion_status=_status(cover),
            capsule_clearance_status=_status(capsule),
            slope_status=_status(slope),
            step_status=_status(step),
            failure_codes=[] if clean else ["WF679_SLICE_TRAVERSAL_MISSING"],
        )
        views.append(view)
        if walk is None:
            notes.append(ssid)
    return views, notes


def _render(views, sha):
    body = '<h2>Route / walkability ({} scenarios)</h2>'.format(len(views))
    body += '<p class="muted">traversal_mode = grounded_worldforge_route (proved). '\
            'navmesh = honest headless limit (path_missing), never claimed proved.</p>'
    body += '<div class="scroll"><table><tr><th>scenario</th><th>map</th><th>mode</th>'\
            '<th>objective</th><th>slope</th><th>step</th><th>capsule</th><th>cover</th></tr>'
    for v in views:
        body += ("<tr><td>{}</td><td><code>{}</code></td><td>{}</td><td>{}</td>"
                 "<td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>").format(
            V.esc(v["scenario_id"]), V.esc(v["map_id"]), V.esc(v["traversal_mode"]),
            V.badge(v["objective_access_status"]), V.badge(v["slope_status"]),
            V.badge(v["step_status"]), V.badge(v["capsule_clearance_status"]),
            V.badge(v["cover_intrusion_status"]))
    body += "</table></div>"
    return V.page("Route / walkability viewer", body,
                  subtitle="v1.6z grounded traversal evidence · headless navmesh is an honest limit",
                  git_sha=sha, back=("../index.html", "dashboard"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator route/walkability viewer.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("operator", "route_view", strict=strict)

    if not MANIFEST.is_file():
        rep.check("manifest_present", False, "slice manifest missing",
                  code=F.OPERATOR_ROUTE_VIEW_INVALID)
        rep.finalize()
        rep.write(INDEX_DIR, "build_route_view_report.json")
        rep.print_summary("operator-route-view")
        sys.exit(rep.exit_code)

    manifest = _load(MANIFEST)
    views, missing = build_views(manifest)

    rep.check("route_views_nonempty", len(views) == len(manifest.get("scenarios", [])),
              "expected one route view per scenario ({}, got {})".format(
                  len(manifest.get("scenarios", [])), len(views)),
              code=F.OPERATOR_ROUTE_VIEW_INVALID)
    rep.check("walkability_present", not missing,
              "scenarios with no walkability report: {}".format(missing[:4]),
              code=F.OPERATOR_ROUTE_VIEW_INVALID)
    for v in views:
        fails = [c for c in OX.validate_route_walkability_view(v, strict=strict) if not c[1]]
        rep.check("route::{}::schema".format(v["scenario_id"]), len(fails) == 0,
                  "route view schema failures: {}".format([c[0] for c in fails][:3]),
                  code=F.OPERATOR_ROUTE_VIEW_INVALID)
        # a PASS objective_access walkability report path must exist on disk.
        if v["objective_access_status"] == "pass":
            rep.check("route::{}::walk_exists".format(v["scenario_id"]),
                      (REPO_ROOT / v["walkability_report_path"]).is_file(),
                      "proved route references missing walkability report: {}".format(
                          v["walkability_report_path"]),
                      code=F.OPERATOR_ROUTE_VIEW_INVALID)

    if rep.passed:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        (INDEX_DIR / "route_walkability_views.json").write_text(
            json.dumps(views, indent=2, sort_keys=True), encoding="utf-8")
        sha = ""
        idx = INDEX_DIR / "operator_report_index.json"
        if idx.is_file():
            sha = json.loads(idx.read_text(encoding="utf-8")).get("git_sha", "")
        V.write_page("routes/index.html", _render(views, sha))

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-route-view", pack=None, strict=strict, status=rep.status,
        record_count=len(views), records_total=len(views),
        report_type="wf.operator.route_view.v1"))
    rep.write(INDEX_DIR, "build_route_view_report.json")
    rep.print_summary("operator-route-view")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
