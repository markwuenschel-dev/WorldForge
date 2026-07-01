#!/usr/bin/env python3
"""validate_reachability.py — WorldForge v1.0x graph reachability validator.

Builds the reachability graph from each map's overlay and proves a real
traversal guarantee (not a decorative graph):
  * player_start can reach at least one primary POI over reachable/risky edges;
  * danger zones cannot HARD-BLOCK all progression — a reachable-only route
    (never entering a danger zone) still reaches an objective;
  * safe zones are reachable.

All defects are tagged REACHABILITY_FAILURE.

Importable core: ``validate_pack(pack, strict, overlay_dir=None) -> ValidationReport``.
``check_overlay`` accepts an overlay dict so the negative harness can inject
broken overlays.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_reachability.py --pack desert_mvp_world --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta
from world_pack_maps import enumerate_maps, report_dir_for
from generate_level_design import load_overlay, reachable_from, node_ids

CODE = FailureCode.REACHABILITY_FAILURE

PRIMARY_ROLES = ("primary_poi",)
OBJECTIVE_ROLES = ("primary_poi", "secondary_poi")


def check_overlay(rep, slice_id, overlay):
    """Add reachability checks for one overlay. Returns True if all pass."""
    def chk(name, ok, detail=""):
        return rep.check("{}::{}".format(slice_id, name), ok, detail, code=CODE)

    ok_all = True
    ids = node_ids(overlay)

    # graph must have a player_start node to traverse from
    ok_all &= chk("player_start_node_present", "player_start" in ids,
                  "graph has no player_start node")

    # 1. player_start reaches a primary POI over reachable/risky edges
    reach_progress = reachable_from(overlay, "player_start", {"reachable", "risky"})
    reaches_primary = any(r in reach_progress for r in PRIMARY_ROLES)
    ok_all &= chk("primary_reachable_from_spawn", reaches_primary,
                  "player_start cannot reach a primary POI over reachable/risky edges")

    # 2. danger cannot hard-block ALL progression: reachable-only route (which
    #    never enters a danger zone in this schema) still reaches an objective.
    reach_safe = reachable_from(overlay, "player_start", {"reachable"})
    danger_ids = [z.get("id") for z in overlay.get("danger_zones", []) or []]
    objective_via_safe = any(r in reach_safe for r in OBJECTIVE_ROLES)
    danger_free = not any(d in reach_safe for d in danger_ids)
    ok_all &= chk("progress_not_hard_blocked_by_danger",
                  objective_via_safe and danger_free,
                  "no danger-free reachable route to any objective (danger hard-blocks progress)")

    # 3. safe zones reachable
    safe_zones = overlay.get("safe_zones", []) or []
    safe_ok = bool(safe_zones) and all(z.get("id") in reach_safe for z in safe_zones)
    ok_all &= chk("safe_zones_reachable", safe_ok,
                  "every safe zone must be reachable from player_start")

    return ok_all


def validate_pack(pack, strict, overlay_dir=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    for m in maps:
        if not m.spec_exists:
            rep.check("{}::spec_present".format(m.slice_id or "<missing>"), False,
                      m.get("spec_error") or "spec missing", code=CODE)
            continue
        overlay, err = load_overlay(m.slice_id, overlay_dir)
        if overlay is None:
            rep.check("{}::overlay_present".format(m.slice_id), False, err, code=CODE)
            continue
        check_overlay(rep, m.slice_id, overlay)
    rep.set_meta(build_meta(command="validate-reachability", pack=world_pack_id,
                            strict=strict, status=None, record_count=len(maps)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate graph reachability across a world pack.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_pack(args.pack, strict)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_reachability_report.json")
    rep.print_summary("validate-reachability")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
