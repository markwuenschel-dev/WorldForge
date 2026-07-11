#!/usr/bin/env python3
"""generate_tactical_bindings.py — v2.4 Wave 3 NPC/group binding authoring (Agent 4).

Binds tactical roles + pressure profiles to NPCs across the 24 scenarios, over the real
v2.3 streaming tiles/anchors/routes, v2.2 quests/factions, and v1.7 NPC archetypes. Each
scenario gets a bounded 2-NPC squad + one coordinated group state. Every record is
validated against tactical_contracts before it is written.

Deliverables (handoff §14 Wave 3):
    procedural/generated/tactical/bindings/*.json   (48 NPC bindings)
    procedural/generated/tactical/groups/*.json     (24 group states)
    procedural/reports/tactical/authoring/binding_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_tactical_bindings.py --strict
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

BIND_DIR = REPO_ROOT / "procedural" / "generated" / "tactical" / "bindings"
GROUP_DIR = REPO_ROOT / "procedural" / "generated" / "tactical" / "groups"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "authoring"


def generate(rep):
    BIND_DIR.mkdir(parents=True, exist_ok=True)
    GROUP_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = SP.scenario_plan()
    nb = ng = 0
    for s in scenarios:
        squad = SP.squad_for(s)
        for npc in squad:
            b = SP.npc_binding(s, npc)
            fails = [c for c in TC.validate_tactical_npc_binding(b, strict=True) if not c[1]]
            rep.check("bind::{}::valid".format(b["binding_id"]), len(fails) == 0,
                      "npc binding invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                      code=F.TACTICAL_NPC_BINDING_INVALID)
            (BIND_DIR / (b["binding_id"] + ".json")).write_text(
                json.dumps(b, indent=2, sort_keys=True), encoding="utf-8")
            nb += 1
        g = SP.group_state(s, squad)
        gfails = [c for c in TC.validate_tactical_group_state(g, strict=True) if not c[1]]
        rep.check("group::{}::valid".format(g["group_id"]), len(gfails) == 0,
                  "group state invalid: {}".format([(c[0], c[3]) for c in gfails][:4]),
                  code=F.TACTICAL_GROUP_STATE_INVALID)
        (GROUP_DIR / (g["group_id"] + ".json")).write_text(
            json.dumps(g, indent=2, sort_keys=True), encoding="utf-8")
        ng += 1
    rep.check("count::bindings_48", nb == 48, "must generate 48 NPC bindings (got {})".format(nb),
              code=F.TACTICAL_NPC_BINDING_INVALID)
    rep.check("count::groups_24", ng == 24, "must generate 24 group states (got {})".format(ng),
              code=F.TACTICAL_GROUP_STATE_INVALID)
    return nb + ng


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical NPC/group binding authoring.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_binding_authoring", strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-tactical-bindings", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.binding_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "binding_report.json")
    rep.print_summary("generate-tactical-bindings")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
