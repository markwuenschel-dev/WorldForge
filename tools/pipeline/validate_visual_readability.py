#!/usr/bin/env python3
"""validate_visual_readability.py — WorldForge v1.3.5 visual readability gate (Pillar 6).

Fidelity must never break playability. Every one of the 60 mission maps already
has a passing PlaytestForge run; this gate proves the MATERIALIZED visuals
(environment rig + dressing) do not invalidate that proven playtest. It is the
load-bearing "fidelity is not allowed to hide the objective" check (brief Pillar
6).

Per map it joins three artifacts — the resolved environment rig
(procedural/generated/visual/environment_rigs/<slice_id>.json), the dressing plan
(procedural/generated/visual/dressing/<slice_id>.json) and the mission this map
carries (via the mission catalog) — and checks:

  * FOG does not hide the mission route. The ExponentialHeightFog readable
    distance (the clear near-field start_distance_cm plus the fog-penetration
    visibility_min_cm) must be at least VC.MIN_FOG_VISIBILITY_FRACTION_OF_ROUTE of
    the mission's required-route length, so the objective stays visible through
    the fog. A fog that would occlude the route is a VISUAL_READABILITY_FAILURE
    ("fog hides mission route"). Only evaluated when the fog is enabled and
    carries a bound visibility_min_cm (a low-visibility / volumetric fog);
    otherwise not applicable.
  * EXPOSURE is in the readable EV window [VC.EXPOSURE_EV_MIN, VC.EXPOSURE_EV_MAX]
    so the objective is neither black-framed nor blown out.
  * DRESSING does not block the route: no dressing asset lands within
    CLEARANCE_MIN_CM of any required-route waypoint or the player start
    (re-affirming the world-dressing readability rule against the rig's mission).
  * The mission's existing PLAYTEST still completes: the per-mission PlaytestForge
    report (procedural/reports/missions/playtest/<mission_id>.json) records
    completed=True. A map whose visuals would invalidate the playtest fails.

Code: VISUAL_READABILITY_FAILURE.

Usage:
    python tools/pipeline/validate_visual_readability.py --pack mission_loop_world [--strict]
Writes:
    procedural/reports/visual/validate_visual_readability/validate_visual_readability_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_rig_common import components_by_type, is_number
from visual_catalog import load_visual_catalog
from mission_catalog import load_mission_catalog
import mission_contract as MC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.VISUAL_READABILITY_FAILURE

# Dressing must clear every route waypoint + player start by more than this
# (mirrors validate_world_dressing.CLEARANCE_MIN_CM — one readability floor).
CLEARANCE_MIN_CM = 200.0


def _dist2d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _slice_to_mission(mission_catalog):
    """source_map slice_id -> mission_id, from the mission catalog."""
    out = {}
    for mid, e in (mission_catalog.get("missions") or {}).items():
        sid = e.get("source_map")
        if sid:
            out[sid] = mid
    return out


def _playtest_report_path(mission_id):
    return REPO_ROOT / MC.MISSION_REPORTS_REL / "playtest" / (mission_id + ".json")


def check_map(rep, sid, rig, mission, mission_id, dressing):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=CODE)

    route = mission.get("required_route") or {}
    route_len = route.get("length_cm")
    start = (mission.get("start_anchor") or {}).get("world_position")
    poi = (mission.get("primary_poi") or {}).get("gameplay_anchor")
    waypoints = route.get("waypoints") or ([start, poi] if start and poi else [])

    # -- FOG must not hide the route ---------------------------------------
    fog = components_by_type(rig).get(VC.COMP_HEIGHT_FOG)
    params = (fog or {}).get("params") or {}
    vis = params.get("visibility_min_cm")
    if fog and fog.get("enabled") and is_number(vis):
        if is_number(route_len) and route_len > 0:
            start_dist = params.get("start_distance_cm")
            near_clear = start_dist if is_number(start_dist) else 0.0
            # Readable distance = clear near-field + fog penetration.
            readable = near_clear + vis
            threshold = VC.MIN_FOG_VISIBILITY_FRACTION_OF_ROUTE * route_len
            c("fog_does_not_hide_route", readable >= threshold,
              "fog hides mission route: readable {:.0f}cm (start {:.0f} + visibility "
              "{:.0f}) < {:.0%} of route {:.0f}cm = {:.0f}cm".format(
                  readable, near_clear, vis, VC.MIN_FOG_VISIBILITY_FRACTION_OF_ROUTE,
                  route_len, threshold))
        else:
            c("route_length_present", False,
              "cannot evaluate fog readability: required_route.length_cm={}".format(route_len))

    # -- EXPOSURE in the readable window -----------------------------------
    exposure = rig.get("exposure_ev")
    c("exposure_in_readable_range",
      is_number(exposure) and VC.EXPOSURE_EV_MIN <= exposure <= VC.EXPOSURE_EV_MAX,
      "exposure_ev={} not in [{}, {}] (would black-frame/blow out objective)".format(
          exposure, VC.EXPOSURE_EV_MIN, VC.EXPOSURE_EV_MAX))

    # -- DRESSING must not block the route/start ---------------------------
    if dressing is None:
        c("dressing_plan_present", False, "no dressing plan for map")
    else:
        clearance_pts = list(waypoints) + ([start] if start else [])
        if not clearance_pts:
            c("route_geometry_present", False, "no waypoints/start to test dressing against")
        else:
            blocking = []
            for d in (dressing.get("dressing_assets") or []):
                pos = d.get("world_position")
                if not (isinstance(pos, (list, tuple)) and len(pos) >= 2):
                    continue
                clr = min(_dist2d(pos, p) for p in clearance_pts)
                if clr <= CLEARANCE_MIN_CM:
                    blocking.append("{} @ {:.0f}cm".format(d.get("asset_id"), clr))
            c("dressing_does_not_block_route", not blocking,
              "dressing blocks route/start (< {}cm): {}".format(CLEARANCE_MIN_CM, blocking))

    # -- The mission's existing PLAYTEST must still complete ---------------
    pr_path = _playtest_report_path(mission_id)
    report, perr = _read_json(pr_path) if pr_path.is_file() else (None, "missing")
    if report is None:
        c("playtest_report_present", False,
          "no playtest report at {} ({}) — cannot confirm playability".format(pr_path, perr))
    else:
        c("playtest_completes", report.get("completed") is True,
          "playtest report completed={!r} (visuals must not invalidate the playtest)".format(
              report.get("completed")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 visual readability (Pillar 6).")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_visual_catalog(REPO_ROOT)
    maps = catalog.get("maps") or {}
    mission_catalog = load_mission_catalog(REPO_ROOT)
    sid2mid = _slice_to_mission(mission_catalog)

    if not maps:
        rep.error("no visual maps — run 'make materialize-environment-rigs' + "
                  "'make create-visual-dressing' first")

    n = 0
    for sid in sorted(maps):
        entry = maps.get(sid) or {}
        rig_rel = entry.get("rig_path") or "{}/{}.json".format(VC.ENV_RIGS_REL, sid)
        rig, rerr = _read_json(REPO_ROOT / rig_rel)
        if rig is None:
            rep.check("{}::rig_loads".format(sid), False, rerr or rig_rel, code=CODE)
            continue

        mission_id = sid2mid.get(sid)
        if not mission_id:
            rep.check("{}::mission_bound".format(sid), False,
                      "no mission in catalog carries source_map={}".format(sid), code=CODE)
            continue
        mission, merr = MC.load_mission(mission_id, REPO_ROOT)
        if mission is None:
            rep.check("{}::mission_loads".format(sid), False, merr, code=CODE)
            continue

        dress_rel = entry.get("dressing_path") or "{}/{}.json".format(VC.DRESSING_REL, sid)
        dressing, _ = _read_json(REPO_ROOT / dress_rel)

        check_map(rep, sid, rig, mission, mission_id, dressing)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-visual-readability", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_visual_readability",
              "validate_visual_readability_report.json")
    rep.print_summary("validate-visual-readability")
    print("[validate-visual-readability] {} maps checked".format(n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
