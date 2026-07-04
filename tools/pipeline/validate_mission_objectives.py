#!/usr/bin/env python3
"""validate_mission_objectives.py — WorldForge v1.3 mission objective validator (Agent 1).

Proves every mission's objectives are actionable and consistent with its
archetype (brief §1/§2): each objective anchor has a position + an interaction,
the interaction matches the archetype's declared interaction, objectives are
attached to a real POI node, and every completion condition targets a declared
objective/primary node. Complements validate_mission_graph (structural) and the
PlaytestForge harness (does it complete).

Writes: procedural/reports/missions/validate_mission_objectives/validate_mission_objectives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def check_objectives(rep, mid, m, archetypes):
    def c(name, ok, detail="", code=FailureCode.MISSION_OBJECTIVE_FAILURE):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    objectives = m.get("objective_anchors") or []
    c("has_objective", bool(objectives), "no objective anchors")

    archetype = m.get("mission_archetype")
    spec = archetypes.get(archetype) or {}
    expected_interaction = spec.get("interaction")

    node_ids = {MC.NODE_START, MC.NODE_PRIMARY_POI, MC.NODE_COMPLETION}
    node_ids |= {o.get("id") for o in objectives}

    for i, o in enumerate(objectives):
        c("obj_{}_position".format(i), bool(o.get("world_position")),
          "objective {} missing world_position".format(i))
        c("obj_{}_interaction".format(i), bool(o.get("interaction")),
          "objective {} missing interaction".format(i))
        # interaction must match the archetype's declared interaction
        if expected_interaction:
            c("obj_{}_interaction_matches_archetype".format(i),
              o.get("interaction") == expected_interaction,
              "interaction={} expected={}".format(o.get("interaction"), expected_interaction))
        # objective attaches to a real POI node
        c("obj_{}_attached".format(i), o.get("at_poi") in node_ids or o.get("at_poi") is None,
          "at_poi={} not a graph node".format(o.get("at_poi")))

    # every completion condition targets a declared node (objective/primary/completion)
    for i, comp in enumerate(m.get("completion_conditions") or []):
        c("completion_{}_targets_objective".format(i), comp.get("at_node") in node_ids,
          "at_node={} not an objective/graph node".format(comp.get("at_node")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission objectives.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    archetypes = MC.load_all_archetypes()
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions found")
    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.MISSION_OBJECTIVE_FAILURE)
            continue
        check_objectives(rep, mid, m, archetypes)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-objectives", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_objectives",
              "validate_mission_objectives_report.json")
    rep.print_summary("validate-mission-objectives")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
