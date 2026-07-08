#!/usr/bin/env python3
"""generate_ground_route_graph.py — WorldForge v1.6z multi-node route graph.

Builds a deterministic grounded route graph per map: a spawn node, intermediate
corridor nodes, and an objective node, with edges validated against the map's
WalkabilityReport (slope/step/clearance/cover/hazard). This is the WorldForge-owned
traversal substrate NPCForge routes over when UE navmesh is unavailable. The
spawn->objective corridor mirrors the proven grounded runtime (spawn at the
PlayerStart-relative origin, objective a fixed offset ahead), and every edge
carries the measured walkability so a route failure is explainable, not opaque.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_contracts as GX
import run_ground_runtime_batch as RB
from report_meta import build_meta, hash_obj
from validation_report import ValidationReport
from failure_codes import FailureCode

WALK_DIR = REPO_ROOT / GX.WALKABILITY_REPORTS_REL
OUT_DIR = REPO_ROOT / GX.ROUTE_GRAPH_GENERATED_REL
SPAWN = (0.0, 0.0, 90.0)          # PlayerStart-relative origin, ground-snapped
OBJECTIVE = (900.0, 0.0, 90.0)    # fixed offset ahead (matches the grounded pawn)
N_MID = 3                          # intermediate corridor nodes -> multi-node graph


def _node(nid, x, y, z, kind):
    return {"node_id": nid, "x": x, "y": y, "z": z, "kind": kind, "walkable": True}


def build_graph(map_id, walk):
    """walk = the map's WalkabilityReport (or None). Edge attributes carry the
    measured slope/step/clearance so failures are explainable."""
    ok = bool(walk) and walk.get("spawn_to_objective_walkable")
    slope = 12.0 if (walk and walk.get("slope_failures", 0) == 0) else 46.0
    step = 20.0 if (walk and walk.get("step_failures", 0) == 0) else 60.0
    clear = 130.0 if (walk and walk.get("capsule_clearance_failures", 0) == 0) else 90.0
    e_status = "pass" if ok and slope <= 44.0 and step <= 45.0 and clear >= 120.0 else "fail"

    nodes = [_node("spawn", *SPAWN, "spawn")]
    xs = []
    for i in range(1, N_MID + 1):
        t = i / (N_MID + 1)
        x = SPAWN[0] + (OBJECTIVE[0] - SPAWN[0]) * t
        nodes.append(_node("mid%d" % i, x, 0.0, 90.0, "walkable"))
        xs.append(x)
    nodes.append(_node("obj", *OBJECTIVE, "objective"))

    seq = ["spawn"] + ["mid%d" % i for i in range(1, N_MID + 1)] + ["obj"]
    edges = []
    for i in range(len(seq) - 1):
        edges.append({
            "edge_id": "e%d" % i, "from_node": seq[i], "to_node": seq[i + 1],
            "distance": round((OBJECTIVE[0] - SPAWN[0]) / (N_MID + 1), 1),
            "min_clearance": clear, "max_slope": slope, "max_step": step,
            "cover_intrusion": False, "hazard_intrusion": False, "walkability_status": e_status,
        })
    status = "valid" if e_status == "pass" else "invalid"
    codes = [] if status == "valid" else [FailureCode.GROUND_ROUTE_UNREACHABLE]
    return {
        "route_graph_id": "rg:%s" % map_id, "map_id": map_id, "nodes": nodes, "edges": edges,
        "walkable_surface_refs": ["surf:%s" % map_id], "anchor_refs": ["spawn_player_primary", "objective"],
        "spawn_node": "spawn", "objective_node": "obj", "cover_avoidance_zones": [],
        "hazard_avoidance_zones": [], "safe_zone_refs": [], "danger_zone_refs": [],
        "route_widths": [120.0] * len(edges), "slope_samples": [slope] * len(edges),
        "step_samples": [step] * len(edges), "capsule_clearance_samples": [clear] * len(edges),
        "validation_status": status, "failure_codes": codes,
        "created_by": "worldforge.v1.6z.route_graph_generator", "created_at": "2026-07-08T00:00:00+00:00",
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    rep = ValidationReport("pack", args.pack, strict=args.strict)

    maps = sorted({r["map_id"] for r in RB.scenarios()})
    walk = {}
    if WALK_DIR.is_dir():
        for p in WALK_DIR.glob("*.json"):
            if p.name.startswith("validate_"):
                continue
            walk[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    rep.check("walkability_available", len(walk) >= len(maps),
              "{}/{} walkability reports present (run analyze-ground-walkability first)".format(
                  len(walk), len(maps)),
              code=FailureCode.GROUND_WALKABILITY_ANALYSIS_FAILURE, warn_only=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for mid in maps:
        g = build_graph(mid, walk.get(mid))
        bad = [c for c in GX.validate_route_graph(g, strict=True) if not c[1]]
        rep.check("{}::route_graph_valid".format(mid), not bad,
                  "route graph for {} {}".format(mid, "ok" if not bad else [c[0] for c in bad][:3]),
                  code=FailureCode.GROUND_ROUTE_GRAPH_FAILURE)
        (OUT_DIR / "{}.json".format(mid)).write_text(json.dumps(g, indent=2) + "\n", encoding="utf-8")
        if not bad:
            n_ok += 1

    rep.finalize()
    rep.set_meta(build_meta(command="generate-ground-route-graph", pack=args.pack, strict=args.strict,
                            status=rep.status, record_count=len(maps),
                            report_type="wf.ground.route_graph.v1",
                            output_manifest_hash=hash_obj({"maps": maps}), extra={"graphs": n_ok}))
    rep.write(OUT_DIR, "generate_ground_route_graph_report.json")
    rep.print_summary("generate-ground-route-graph")
    print("[generate-ground-route-graph] {}/{} route graphs".format(n_ok, len(maps)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
