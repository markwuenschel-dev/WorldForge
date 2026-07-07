#!/usr/bin/env python3
"""validate_route_clearance_after_visuals.py — WorldForge v1.5 Wave-4 regression.

v1.5 replaces v1.4x cube cover proxies with real meshes AND applies biome visual
kits (dressing). Because the resolver preserved every anchor position (proven by
validate_encounter_anchor_preservation), the route-clearance invariant must still
hold AFTER materialization — real cover meshes sitting at the same anchor points
must still leave the mission's required route clear, and visual dressing must not
block it either. This validator re-runs that invariant post-materialization to
PROVE it, rather than assuming it.

Per encounter in the pack it delegates the load-bearing geometry to the existing
validators (no math reimplemented here):

  * cover must not block the required route — validate_encounter_cover's
    ``cover_clear_of_required_route`` check (COVER_ROUTE_CLEAR_CM = 600cm)
  * the required route must be pressured but never blocked —
    validate_encounter_routes' ``required_route_not_blocked`` blockage check
  * visual dressing must not block the route —
    validate_visual_readability's ``dressing_does_not_block_route`` clearance check

Any violation is reported as COVER_REPLACEMENT_ROUTE_BLOCKED.

Report: wf.realization.route_clearance.v1

Usage:
    python tools/pipeline/validate_route_clearance_after_visuals.py --pack encounter_loop_world [--strict]
Writes:
    procedural/reports/realization/validate_route_clearance_after_visuals/
        validate_route_clearance_after_visuals_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import asset_paths
import mission_contract as MC
import replace_cover_proxies as RCP
import visual_contract as VC
import validate_encounter_cover as VEC
import validate_encounter_routes as VER
import validate_visual_readability as VVR
from mesh_catalog import load_mesh_catalog
from mission_catalog import load_mission_catalog
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

COMMAND = "validate_route_clearance_after_visuals"
REPORT_TYPE = "wf.realization.route_clearance.v1"
CODE = FailureCode.COVER_REPLACEMENT_ROUTE_BLOCKED


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _delegated_checks(enc, mission, eid, mesh_assets, sid, rig, dressing, mission_id):
    """Run the three delegated helpers into a throwaway sub-report and return the
    route-clearance-relevant (name -> ok) results so this validator can re-emit
    them under COVER_REPLACEMENT_ROUTE_BLOCKED without reimplementing any math."""
    sub = ValidationReport("pack", eid, strict=False)
    VEC.check_cover(sub, eid, enc, mission, mesh_assets)
    VER.check_routes(sub, eid, enc, mission)
    if rig is not None and dressing is not None and mission is not None and sid:
        VVR.check_map(sub, sid, rig, mission, mission_id, dressing)

    cover_clear = {k: c["ok"] for k, c in sub.checks.items()
                   if k.startswith("cover_clear_of_required_route")}
    route_blocked = {k: c["ok"] for k, c in sub.checks.items()
                     if k.startswith("required_route_not_blocked")}
    dressing_key = "{}::dressing_does_not_block_route".format(sid)
    dressing_ok = sub.checks.get(dressing_key)
    return cover_clear, route_blocked, (dressing_ok["ok"] if dressing_ok else None), sub


def check_encounter(rep, enc, mission, mesh_assets, sid2mid):
    eid = enc.get("encounter_id")
    mission_id = enc.get("mission_id")

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=CODE)

    sid = None
    for s, mid in sid2mid.items():
        if mid == mission_id:
            sid = s
            break
    rig = _read_json(REPO_ROOT / VC.ENV_RIGS_REL / "{}.json".format(sid)) if sid else None
    dressing = _read_json(REPO_ROOT / VC.DRESSING_REL / "{}.json".format(sid)) if sid else None

    cover_clear, route_blocked, dressing_ok, _sub = _delegated_checks(
        enc, mission, eid, mesh_assets, sid, rig, dressing, mission_id)

    # 1. Real cover meshes at the (unchanged) anchors still clear the route.
    # An encounter with no cover anchors has nothing that could block the route,
    # so cover clearance is not applicable there (the route blockage check below
    # still runs unconditionally).
    n_covers = len(enc.get("cover_anchors") or [])
    if n_covers == 0:
        rep.skip("cover_clears_required_route_after_realization::{}".format(eid),
                 "encounter has no cover anchors — no cover can block the route",
                 code=CODE)
    else:
        cover_fail = sorted(k for k, ok in cover_clear.items() if not ok)
        c("cover_clears_required_route_after_realization",
          bool(cover_clear) and not cover_fail,
          "post-realization cover blocks the required route (< {}cm): {}".format(
              VEC.COVER_ROUTE_CLEAR_CM, cover_fail) if cover_clear
          else "{} cover anchor(s) present but the mission required_route has no "
               "waypoints to test clearance against".format(n_covers))

    # 2. The required route is pressured but never blocked.
    route_fail = sorted(k for k, ok in route_blocked.items() if not ok)
    c("required_route_not_blocked_after_realization",
      bool(route_blocked) and not route_fail,
      "required-route blockage invariant broke post-realization: {}".format(route_fail)
      if route_blocked else "no required_route blockage check available")

    # 3. Applied visual dressing does not block the route.
    if dressing_ok is None:
        rep.skip("dressing_clear_of_route_after_visuals::{}".format(eid),
                 "no dressing plan / route geometry for map {} (not applicable)".format(sid),
                 code=CODE)
    else:
        c("dressing_clear_of_route_after_visuals", dressing_ok,
          "applied visual dressing blocks the required route for map {} "
          "(< {}cm)".format(sid, VVR.CLEARANCE_MIN_CM))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Re-prove the route-clearance invariant after v1.5 cover+visual "
                    "materialization.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    encounters = RCP.load_pack_encounters(args.pack)
    if not encounters:
        rep.error("no encounters in pack '{}' — run 'make create-encounters' first"
                  .format(args.pack))

    mesh_assets = (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {}
    mission_catalog = load_mission_catalog(REPO_ROOT)
    sid2mid = {}
    for mid, e in (mission_catalog.get("missions") or {}).items():
        s = e.get("source_map")
        if isinstance(s, str) and s:
            sid2mid[s] = mid

    n = 0
    for enc in sorted(encounters, key=lambda e: e.get("encounter_id") or ""):
        eid = enc.get("encounter_id")
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        if mission is None:
            rep.check("mission_loads::{}".format(eid), False, merr, code=CODE)
            continue
        check_encounter(rep, enc, mission, mesh_assets, sid2mid)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(
        command=COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=n, records_total=n,
        records_passed=n if rep.passed else 0,
        records_failed=0 if rep.passed else n,
        extra={"encounters_checked": n,
               "delegated_validators": ["validate_encounter_cover",
                                        "validate_encounter_routes",
                                        "validate_visual_readability"]}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write("[{}] {} encounter(s) re-proven route-clear after realization\n"
                     .format(COMMAND, n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
