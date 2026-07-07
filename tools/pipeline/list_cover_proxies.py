#!/usr/bin/env python3
"""list_cover_proxies.py — WorldForge v1.5 Wave-3 cover-proxy inventory.

Inventories every v1.4x WF_ENC cover proxy across a pack: map, mission, encounter,
proxy actor label, cover_anchor_id, height_class, and the route/LOS constraints
that must survive replacement. For each proxy it reports whether a
RealizedCoverBinding exists and whether the live UE swap has happened
(``live_replaced`` from the UE-driver sidecar) — i.e. replaced vs remaining.

Headlessly every proxy is "binding_written but not live_replaced" (proxy-debt),
which is the honest state until the UE swap driver runs. This is a report, not a
gate: it always exits 0 (an empty pack is the only failure).

Usage:
    python tools/pipeline/list_cover_proxies.py --pack encounter_loop_world [--strict]
Report: wf.realization.cover_proxy_inventory.v1
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import realized_cover_contract as RC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "list_cover_proxies"
REPORT_TYPE = "wf.realization.cover_proxy_inventory.v1"
PROXY_LABEL_PREFIX = "WF_ENC_"
# The UE proxy-swap driver writes one sidecar per binding it actually replaces.
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
    """cover_anchor_id -> binding dict."""
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


def live_replaced_ids():
    """binding_ids the UE swap driver has actually replaced (sidecar reports)."""
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


def map_id_of(mission_id):
    return mission_id[len("mission_"):] if mission_id.startswith("mission_") else mission_id


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 cover-proxy inventory.")
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
    live_ids = live_replaced_ids()

    proxies = []
    n_binding, n_live = 0, 0
    for enc in encounters:
        mid = enc.get("mission_id") or ""
        for cov in enc.get("cover_anchors") or []:
            aid = cov["id"]
            b = bindings.get(aid)
            binding_id = b.get("binding_id") if b else None
            is_live = bool(binding_id and binding_id in live_ids)
            if b:
                n_binding += 1
            if is_live:
                n_live += 1
            proxies.append({
                "map_id": map_id_of(mid),
                "mission_id": mid,
                "encounter_id": enc["encounter_id"],
                "proxy_actor_label": PROXY_LABEL_PREFIX + aid,
                "cover_anchor_id": aid,
                "height_class": cov.get("height_class"),
                "collision": cov.get("collision"),
                "route_clearance_result": (b or {}).get("route_clearance_result"),
                "line_of_sight_result": (b or {}).get("line_of_sight_result"),
                "binding_id": binding_id,
                "binding_written": bool(b),
                "live_replaced": is_live,
                "status": "replaced" if is_live else (
                    "binding_written" if b else "remaining_no_binding"),
            })

    total = len(proxies)
    rep.check("every_proxy_has_binding", n_binding == total and total > 0,
              "{}/{} proxies have a RealizedCoverBinding".format(n_binding, total),
              warn_only=True, allow_in_strict=True)

    inv_path = asset_paths.ensure(
        asset_paths.COVER_BINDINGS_DIR.parent / "inventory"
        / "cover_proxy_inventory_{}.json".format(args.pack))
    inv_path.write_text(json.dumps({
        "pack_id": args.pack,
        "report_type": REPORT_TYPE,
        "totals": {"proxies": total, "binding_written": n_binding,
                   "live_replaced": n_live, "remaining": total - n_live},
        "proxies": proxies,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rep.finalize()
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=total, records_total=total,
        records_passed=n_binding, records_failed=total - n_binding,
        extra={"proxies_total": total, "binding_written": n_binding,
               "live_replaced": n_live, "remaining": total - n_live,
               "inventory_path": inv_path.relative_to(REPO_ROOT).as_posix()}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write(
        "[{}] {} proxies | binding_written={} live_replaced={} remaining={}\n".format(
            COMMAND, total, n_binding, n_live, total - n_live))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
