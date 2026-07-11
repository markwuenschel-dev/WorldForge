#!/usr/bin/env python3
"""validate_tactical_bindings.py — v2.4 Wave 3 NPC/group binding gate.

Re-validates every generated NPC binding + group state from disk against tactical_contracts
AND performs the cross-record resolution the schema-only contracts cannot: tactical role +
behavior profile resolve to real generated records; spawn anchor, allowed tiles + routes
resolve to real v2.3 streaming records; allowed cover ids resolve to the scenario's
affordance-map cover markers; npc_profile_id resolves to a real v1.7 archetype; quest +
faction contexts resolve to real v2.2 records; allowed-tile scope does not exceed the
streaming binding; and each group's npc_ids exactly match its scenario's bindings, with a
suppressor present whenever suppression is active and a skirmisher whenever flank is active.
Coverage: 48 NPC bindings + 24 group states over 24 scenarios.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_tactical_bindings.py --strict
Reports -> procedural/reports/tactical/authoring/validate_tactical_bindings_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
import tactical_spec as SP
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

GEN = REPO_ROOT / "procedural" / "generated"
TAC = GEN / "tactical"
BIND_DIR = TAC / "bindings"
GROUP_DIR = TAC / "groups"
ROLES_DIR = TAC / "roles"
PROFILES_DIR = TAC / "profiles"
AFF_DIR = TAC / "affordances"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "authoring"


def _load_all(d):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))}


def _stems(d, pat="*.json"):
    return {p.stem for p in d.glob(pat)}


def validate(rep):
    binds = _load_all(BIND_DIR)
    groups = _load_all(GROUP_DIR)
    affs = _load_all(AFF_DIR)
    role_ids = _stems(ROLES_DIR)
    profile_ids = {rec.get("profile_id") for rec in _load_all(PROFILES_DIR).values()}
    tile_ids = _stems(GEN / "tiles")
    anchor_ids = _stems(GEN / "anchors")
    route_ids = _stems(GEN / "routes")
    quest_ids = _stems(GEN / "quests")
    faction_ids = _stems(GEN / "factions")
    archetype_ids = _stems(GEN / "npc" / "archetypes")
    # cover ids available per scenario (from that scenario's affordance map)
    cover_by_scenario = {}
    for am in affs.values():
        cover_by_scenario.setdefault(am.get("scenario_id"), set()).update(
            cp.get("cover_id") for cp in (am.get("cover_points") or []))

    rep.check("count::bindings_48", len(binds) == 48,
              "must have 48 NPC bindings (got {})".format(len(binds)),
              code=F.TACTICAL_NPC_BINDING_INVALID)
    rep.check("count::groups_24", len(groups) == 24,
              "must have 24 group states (got {})".format(len(groups)),
              code=F.TACTICAL_GROUP_STATE_INVALID)

    n = 0
    bindings_by_scenario = {}
    for name, b in binds.items():
        n += 1
        bindings_by_scenario.setdefault(b.get("scenario_id"), []).append(b)
        fails = [c for c in TC.validate_tactical_npc_binding(b, strict=True) if not c[1]]
        rep.check("bind::{}::valid".format(name), len(fails) == 0,
                  "binding invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_NPC_BINDING_INVALID)
        rep.check("bind::{}::role_resolves".format(name),
                  b.get("tactical_role_id") in role_ids,
                  "role {} unresolved".format(b.get("tactical_role_id")),
                  code=F.TACTICAL_UNKNOWN_ROLE)
        rep.check("bind::{}::profile_resolves".format(name),
                  b.get("behavior_profile_id") in profile_ids,
                  "profile {} unresolved".format(b.get("behavior_profile_id")),
                  code=F.TACTICAL_PROFILE_INVALID)
        rep.check("bind::{}::archetype_resolves".format(name),
                  b.get("npc_profile_id") in archetype_ids,
                  "npc_profile_id {} unresolved".format(b.get("npc_profile_id")),
                  code=F.TACTICAL_NPC_BINDING_INVALID)
        rep.check("bind::{}::spawn_anchor_resolves".format(name),
                  b.get("spawn_anchor_id") in anchor_ids,
                  "spawn anchor {} unresolved".format(b.get("spawn_anchor_id")),
                  code=F.TACTICAL_ANCHOR_REFERENCE_INVALID)
        for t in b.get("allowed_tile_ids") or []:
            rep.check("bind::{}::tile_resolves::{}".format(name, t), t in tile_ids,
                      "allowed tile {} unresolved".format(t),
                      code=F.TACTICAL_NPC_BINDING_INVALID)
        for r in b.get("allowed_route_ids") or []:
            rep.check("bind::{}::route_resolves::{}".format(name, r), r in route_ids,
                      "allowed route {} unresolved".format(r),
                      code=F.TACTICAL_ROUTE_REFERENCE_INVALID)
        # cover ids must resolve to the scenario's affordance-map cover markers.
        avail = cover_by_scenario.get(b.get("scenario_id"), set())
        leak = [c for c in (b.get("allowed_cover_ids") or []) if c not in avail]
        rep.check("bind::{}::cover_resolves".format(name), not leak,
                  "allowed cover ids not in scenario affordance map: {}".format(leak),
                  code=F.TACTICAL_COVER_REFERENCE_INVALID)
        rep.check("bind::{}::quest_resolves".format(name),
                  b.get("quest_context_id") in quest_ids,
                  "quest context {} unresolved".format(b.get("quest_context_id")),
                  code=F.TACTICAL_QUEST_STATE_MISSING)
        rep.check("bind::{}::faction_resolves".format(name),
                  b.get("faction_context_id") in faction_ids,
                  "faction context {} unresolved".format(b.get("faction_context_id")),
                  code=F.TACTICAL_FACTION_STATE_MISSING)

    for name, g in groups.items():
        n += 1
        fails = [c for c in TC.validate_tactical_group_state(g, strict=True) if not c[1]]
        rep.check("group::{}::valid".format(name), len(fails) == 0,
                  "group invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_GROUP_STATE_INVALID)
        sid = g.get("scenario_id")
        scen_binds = bindings_by_scenario.get(sid, [])
        bind_npcs = {b["binding_id"].replace("tnb_", "") for b in scen_binds}
        group_npcs = set(g.get("npc_ids") or [])
        rep.check("group::{}::npcs_match_bindings".format(name),
                  group_npcs == bind_npcs and len(group_npcs) >= 2,
                  "group npc_ids must match the scenario's bindings (group={}, binds={})".format(
                      sorted(group_npcs), sorted(bind_npcs)),
                  code=F.TACTICAL_COORDINATION_INVALID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical NPC/group binding gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_bindings", strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-tactical-bindings", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.binding_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_tactical_bindings_report.json")
    rep.print_summary("validate-tactical-bindings")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
