#!/usr/bin/env python3
"""validate_encounter_resources.py — WorldForge v1.4 encounter resource validator (Lane D).

Proves resource wiring is HONEST end-to-end (brief §12/§27):

  * every resource node has an id; when a world position can be resolved (from
    the encounter node, else the linked mission's matching resource node by
    id), it must NOT lie inside any encounter danger zone bounds
    (MC.point_in_bounds — resource not blocked by the encounter). When neither
    side carries a position the geometric check is recorded as not applicable.
  * every resource node id appears in objective_links (resource reachable/linked)
  * a resource_grant reward hook exists when resource_nodes is non-empty, and
    NO resource_grant hook exists when resource_nodes is empty
  * resource_contest archetype encounters must declare resource_nodes
  * resource nodes come from the linked mission: every encounter resource node
    id must exist among the mission's resource_nodes ids (no invented resources)

Usage:
    python tools/pipeline/validate_encounter_resources.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_resources/validate_encounter_resources_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.ENCOUNTER_REWARD_FAILURE
MISSION_CODE = FailureCode.ENCOUNTER_MISSION_COMPATIBILITY_FAILURE
ARCHETYPE_CODE = FailureCode.ENCOUNTER_ARCHETYPE_FAILURE


def check_resources(rep, eid, enc, mission):
    """Core resource checks for one encounter (namespace '<check>::<eid>')."""
    def c(name, ok, detail="", code=CODE):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=code)

    nodes = enc.get("resource_nodes") or []
    hooks = enc.get("reward_hooks") or []
    has_grant = any((h or {}).get("reward_type") == "resource_grant" for h in hooks)

    # Reward wiring: resource_grant present IFF resource nodes exist.
    if nodes:
        c("resource_grant_hook_present", has_grant,
          "{} resource node(s) but no resource_grant reward hook".format(len(nodes)))
    else:
        c("no_resource_grant_without_nodes", not has_grant,
          "resource_grant reward hook present but resource_nodes is empty")

    # resource_contest must actually contest a resource.
    if enc.get("encounter_archetype") == "resource_contest":
        c("resource_contest_has_nodes", bool(nodes),
          "resource_contest encounter declares no resource_nodes",
          code=ARCHETYPE_CODE)

    if not nodes:
        return

    mission_nodes = {(r or {}).get("id"): (r or {})
                     for r in (mission or {}).get("resource_nodes") or []}
    links = enc.get("objective_links") or []
    danger_bounds = [(dz.get("id"), dz.get("bounds"))
                     for dz in enc.get("danger_zones") or [] if dz.get("bounds")]

    for node in nodes:
        rid = (node or {}).get("id")
        c("resource_node_has_id[{}]".format(rid or "<no-id>"), bool(rid),
          "resource node missing id: {!r}".format(node))
        if not rid:
            continue

        # No invented resources: node must exist on the linked mission.
        c("resource_from_mission[{}]".format(rid), rid in mission_nodes,
          "resource node '{}' not among mission resource_nodes {}".format(
              rid, sorted(k for k in mission_nodes if k)), code=MISSION_CODE)

        # Reachable/linked: node id must appear in objective_links.
        c("resource_linked_to_objectives[{}]".format(rid), rid in links,
          "resource node '{}' absent from objective_links {}".format(rid, links))

        # Not blocked: resolved position must sit outside every danger zone.
        pos = (node or {}).get("world_position") \
            or (mission_nodes.get(rid) or {}).get("world_position")
        if pos:
            blocking = [zid for zid, b in danger_bounds if MC.point_in_bounds(pos, b)]
            c("resource_not_blocked_by_encounter[{}]".format(rid), not blocking,
              "resource node '{}' at {} lies inside danger zone(s) {}".format(
                  rid, pos, blocking))
        else:
            rep.skip("resource_not_blocked_by_encounter[{}]::{}".format(rid, eid),
                     "no world_position on encounter or mission resource node "
                     "'{}' (at_node={!r}) — geometric blockage not applicable".format(
                         rid, (node or {}).get("at_node")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter resource wiring.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted(eid for eid, e in (catalog.get("encounters") or {}).items()
                  if (e or {}).get("pack_id") == args.pack)
    if not eids:
        rep.error("no encounters in pack '{}' — run 'make create-encounters' first".format(args.pack))

    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("loads::{}".format(eid), False, err, code=CODE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        if mission is None:
            rep.check("mission_loads::{}".format(eid), False, merr, code=MISSION_CODE)
            continue
        check_resources(rep, eid, enc, mission)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-resources", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_resources",
              "validate_encounter_resources_report.json")
    rep.print_summary("validate-encounter-resources")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
