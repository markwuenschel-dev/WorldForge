#!/usr/bin/env python3
"""validate_npc_spawn_placement.py — WorldForge v1.7 spawn-placement gate.

Proves NPC spawn placement is walkability-driven and safe, against the REAL
encounter anchors the spawn groups bind to:

  * every spawn group resolves to an existing encounter;
  * every spawn_anchor_id resolves to a real anchor in that encounter;
  * every resolved anchor is placeable — has a world position and is NOT flagged
    inside collision / not a valid_spawn=false anchor (proxy for on-walkable,
    outside-collision);
  * count never exceeds the anchor * max_density budget;
  * player_start and objective_interaction are in forbidden_spawn_zones-equivalent
    policy (min distances declared, walkability_required true).

These are the schema-layer + real-data guarantees; the in-engine walkable-surface
trace is the materialization gate (validate-npc-actors). Reported honestly as such.

Acceptance: `make validate-npc-spawn-placement PACK=encounter_loop_world STRICT=1`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
import npc_pack as NP
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    enc_by_id = {eid: enc for eid, enc in NP.iter_encounters(args.pack)}
    groups_dir = REPO_ROOT / NX.SPAWN_GROUP_GENERATED_REL
    groups = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(groups_dir.glob("*.json"))] \
        if groups_dir.is_dir() else []

    rep.check("placement::groups_exist", len(groups) > 0,
              "no spawn groups generated (run generate-npc-spawn-groups)",
              code=FailureCode.NPC_SPAWN_GROUP_SCHEMA_FAILURE)

    missing_enc = dangling_anchor = off_walkable = density_bad = policy_bad = 0
    for g in groups:
        gid = g.get("spawn_group_id", "?")
        enc = enc_by_id.get(g.get("encounter_id"))
        if enc is None:
            missing_enc += 1
            rep.check("pl::{}::encounter".format(gid), False, "encounter not found",
                      code=FailureCode.NPC_SPAWN_POINT_MISSING)
            continue
        idx = NP.encounter_anchor_index(enc)
        for aid in g.get("spawn_anchor_ids", []):
            anchor = idx.get(aid)
            if anchor is None:
                dangling_anchor += 1
                rep.check("pl::{}::anchor::{}".format(gid, aid), False, "spawn anchor not found",
                          code=FailureCode.NPC_SPAWN_POINT_MISSING)
            elif not NP.anchor_is_placeable(anchor):
                off_walkable += 1
                rep.check("pl::{}::placeable::{}".format(gid, aid), False,
                          "spawn anchor not placeable (no position / inside collision)",
                          code=FailureCode.NPC_SPAWN_OFF_WALKABLE_SURFACE)
        # density budget
        n_anchors = len(g.get("spawn_anchor_ids", []))
        if not (isinstance(g.get("count"), int) and g["count"] <= n_anchors * g.get("max_density", 1) + 1e-9):
            density_bad += 1
            rep.check("pl::{}::density".format(gid), False,
                      "count exceeds anchors*max_density", code=FailureCode.NPC_DENSITY_BUDGET_FAILURE)
        # placement policy: walkability required, off-route, min distances declared.
        ok_policy = (g.get("walkability_required") is True
                     and g.get("spawn_zone_policy") in ("walkable_only", "walkable_off_route", "anchor_bound")
                     and g.get("min_distance_from_objective", 0) > 0
                     and g.get("min_distance_from_player_spawn", 0) > 0)
        if not ok_policy:
            policy_bad += 1
            rep.check("pl::{}::policy".format(gid), False,
                      "placement policy not walkability-driven / missing min distances",
                      code=FailureCode.NPC_SPAWN_TOO_CLOSE_TO_OBJECTIVE)

    rep.check("placement::encounters_resolve", missing_enc == 0,
              "{} groups with missing encounter".format(missing_enc), code=FailureCode.NPC_SPAWN_POINT_MISSING)
    rep.check("placement::anchors_resolve", dangling_anchor == 0,
              "{} dangling spawn anchors".format(dangling_anchor), code=FailureCode.NPC_SPAWN_POINT_MISSING)
    rep.check("placement::on_walkable", off_walkable == 0,
              "{} spawn anchors off-walkable / inside collision".format(off_walkable),
              code=FailureCode.NPC_SPAWN_OFF_WALKABLE_SURFACE)
    rep.check("placement::density_budget", density_bad == 0,
              "{} groups exceed density budget".format(density_bad), code=FailureCode.NPC_DENSITY_BUDGET_FAILURE)
    rep.check("placement::policy_walkability_driven", policy_bad == 0,
              "{} groups not walkability-driven".format(policy_bad),
              code=FailureCode.NPC_SPAWN_OFF_WALKABLE_SURFACE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-spawn-placement", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(groups), report_type=NX.RT_SPAWN_PLACEMENT,
                            records_total=len(groups),
                            records_failed=missing_enc + dangling_anchor + off_walkable + density_bad + policy_bad))
    rep.write(REPO_ROOT / NX.SPAWN_PLACEMENT_REPORTS_REL, "validate_npc_spawn_placement_report.json")
    rep.print_summary("validate-npc-spawn-placement")
    print("[validate-npc-spawn-placement] {} spawn groups checked against real encounter anchors".format(
        len(groups)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
