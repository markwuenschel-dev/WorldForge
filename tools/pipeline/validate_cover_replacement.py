#!/usr/bin/env python3
"""validate_cover_replacement.py — WorldForge v1.5 Wave-3 cover-replacement gate.

Proves the cube->mesh cover swap is real, catalog/owned-backed, and semantics-
preserving for EVERY cover anchor in a pack:

  * every cover anchor has a RealizedCoverBinding            (COVER_PROXY_REPLACEMENT_FAILURE)
  * replacement resolves to a catalog OR owned-cover asset   (COVER_REPLACEMENT_NOT_CATALOG_BACKED)
  * collision profile is BlockAll                            (COVER_REPLACEMENT_COLLISION_INVALID)
  * height_class unchanged vs the encounter anchor           (COVER_REPLACEMENT_HEIGHT_CLASS_MISMATCH)
  * anchor id/position unchanged (recomputed route clearance
    matches the binding's stored clearance)                  (COVER_REPLACEMENT_ANCHOR_MUTATED)
  * route_clearance_result.passed                            (COVER_REPLACEMENT_ROUTE_BLOCKED)

FAIL-CLOSED on live: a binding whose UE swap has NOT happened (no
``live_replaced`` sidecar) is honest proxy-debt. Under STRICT that is a BLOCKING
COVER_PROXY_REPLACEMENT_FAILURE naming the binding — so this gate is correctly RED
until the separate UE swap driver flips live_replaced True. That RED is the point:
it never reports a swap that has not happened.

Usage:
    python tools/pipeline/validate_cover_replacement.py --pack encounter_loop_world [--strict]
Report: wf.realization.cover_replacement_validation.v1
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import encounter_contract as EC
import mission_contract as MC
import realized_cover_contract as RC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_cover_replacement"
REPORT_TYPE = "wf.realization.cover_replacement_validation.v1"
COVER_ROUTE_CLEAR_CM = 600.0
CLEARANCE_EPS_CM = 1.0
LIVE_REPLACE_DIR = REPO_ROOT / "procedural" / "reports" / "realization" / "ue_replace"


def load_pack_encounters(pack):
    base = REPO_ROOT / "procedural" / "generated" / "encounters"
    out = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        p = d / "encounter.json"
        if not p.is_file():
            continue
        try:
            enc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if enc.get("pack_id") == pack:
            out.append(enc)
    return out


def load_bindings():
    out = {}
    base = asset_paths.COVER_BINDINGS_DIR
    if base.is_dir():
        for p in sorted(base.glob("*.json")):
            try:
                b = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if b.get("cover_anchor_id"):
                out[b["cover_anchor_id"]] = b
    return out


def load_backed_ids():
    """(owned_ids, catalog_ids) usable to back a replacement_asset_id."""
    owned = set()
    base = asset_paths.OWNED_COVER_DIR
    if base.is_dir():
        for p in sorted(base.glob("*.json")):
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if s.get("sm_id"):
                owned.add(s["sm_id"])
            if s.get("final_asset_path"):
                owned.add(s["final_asset_path"])
    catalog = set()
    recs, _e = discover_records(
        [asset_paths.CATALOG_DIR.relative_to(REPO_ROOT).as_posix()])
    for _n, r in recs:
        if isinstance(r, dict) and r.get("asset_id"):
            catalog.add(r["asset_id"])
    agg = asset_paths.ACQUISITION_CATALOG
    if agg.is_file():
        try:
            data = json.loads(agg.read_text(encoding="utf-8"))
            catalog.update((data.get("assets") or {}).keys())
        except Exception:  # noqa: BLE001
            pass
    return owned, catalog


def live_replaced_ids():
    out = set()
    if LIVE_REPLACE_DIR.is_dir():
        for p in sorted(LIVE_REPLACE_DIR.glob("*.json")):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if r.get("live_replaced") is True and r.get("binding_id"):
                out.add(r["binding_id"])
    return out


def recompute_clearance(anchor_pos, mission):
    waypoints = EC.densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))
    if not waypoints:
        return None
    return round(min(MC.dist2d(anchor_pos, wp) for wp in waypoints), 3)


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 cover-replacement gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    encounters = load_pack_encounters(args.pack)
    rep.check("pack_has_encounters", bool(encounters),
              "no encounters in pack '{}'".format(args.pack),
              code=FailureCode.COVER_PROXY_REPLACEMENT_FAILURE)

    bindings = load_bindings()
    owned_ids, catalog_ids = load_backed_ids()
    live_ids = live_replaced_ids()

    n_anchor, n_binding, n_live, n_debt = 0, 0, 0, 0
    mission_cache = {}
    for enc in encounters:
        mid = enc.get("mission_id") or ""
        if mid not in mission_cache:
            mission_cache[mid] = MC.load_mission(mid)[0]
        mission = mission_cache[mid]
        for cov in enc.get("cover_anchors") or []:
            n_anchor += 1
            aid = cov["id"]
            b = bindings.get(aid)
            if b is None:
                rep.check("has_binding[{}]".format(aid), False,
                          "cover anchor '{}' has no RealizedCoverBinding".format(aid),
                          code=FailureCode.COVER_PROXY_REPLACEMENT_FAILURE)
                continue
            n_binding += 1
            bid = b.get("binding_id")

            rid = b.get("replacement_asset_id")
            rep.check("catalog_or_owned_backed[{}]".format(bid),
                      rid in owned_ids or rid in catalog_ids,
                      "replacement_asset_id '{}' backs neither a catalog record "
                      "nor an owned-cover baseline".format(rid),
                      code=FailureCode.COVER_REPLACEMENT_NOT_CATALOG_BACKED)

            rep.check("collision_block_all[{}]".format(bid),
                      b.get("collision_profile") == RC.REQUIRED_COLLISION_PROFILE,
                      "collision_profile={!r} must be BlockAll".format(
                          b.get("collision_profile")),
                      code=FailureCode.COVER_REPLACEMENT_COLLISION_INVALID)

            rep.check("height_class_unchanged[{}]".format(bid),
                      b.get("height_class") == cov.get("height_class"),
                      "binding height_class {!r} != anchor height_class {!r}".format(
                          b.get("height_class"), cov.get("height_class")),
                      code=FailureCode.COVER_REPLACEMENT_HEIGHT_CLASS_MISMATCH)

            # Anchor id present + position unchanged: the binding's stored route
            # clearance must equal the clearance recomputed from the CURRENT anchor
            # position. If the anchor moved, the two diverge.
            recomputed = recompute_clearance(cov.get("world_position"), mission)
            stored = (b.get("route_clearance_result") or {}).get("min_clearance_cm")
            pos_ok = (b.get("cover_anchor_id") == aid) and (
                (recomputed is None and stored is None)
                or (recomputed is not None and stored is not None
                    and abs(recomputed - stored) <= CLEARANCE_EPS_CM))
            rep.check("anchor_not_mutated[{}]".format(bid), pos_ok,
                      "anchor '{}' appears mutated: recomputed clearance {} != "
                      "binding-stored {}".format(aid, recomputed, stored),
                      code=FailureCode.COVER_REPLACEMENT_ANCHOR_MUTATED)

            rcr = b.get("route_clearance_result") or {}
            rep.check("route_not_blocked[{}]".format(bid),
                      rcr.get("passed") is True,
                      "route_clearance_result.passed is not True "
                      "(min_clearance_cm={}, threshold {}cm)".format(
                          rcr.get("min_clearance_cm"), COVER_ROUTE_CLEAR_CM),
                      code=FailureCode.COVER_REPLACEMENT_ROUTE_BLOCKED)

            # FAIL-CLOSED live gate: no live swap yet == proxy-debt. WARN so it is
            # non-blocking in normal mode but BLOCKING under strict — the honest
            # RED-until-UE-run state, naming the exact binding/asset in debt.
            is_live = bool(bid and bid in live_ids)
            if is_live:
                n_live += 1
            else:
                n_debt += 1
            rep.check("live_replaced[{}]".format(bid), is_live,
                      "proxy-debt: binding '{}' (asset_need '{}') not yet live-"
                      "replaced in UE — run the UE cover-swap driver".format(
                          bid, rid),
                      warn_only=True, code=FailureCode.COVER_PROXY_REPLACEMENT_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=n_anchor, records_total=n_anchor,
        records_passed=n_live, records_failed=n_anchor - n_live,
        extra={"anchors": n_anchor, "bindings": n_binding,
               "live_replaced": n_live, "proxy_debt": n_debt}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write(
        "[{}] anchors={} bindings={} live_replaced={} proxy_debt={} (strict={})\n".format(
            COMMAND, n_anchor, n_binding, n_live, n_debt, "on" if strict else "off"))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
