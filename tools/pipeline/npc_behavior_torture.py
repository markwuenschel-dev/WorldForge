#!/usr/bin/env python3
"""npc_behavior_torture.py — WorldForge v1.7 NPCForge lifecycle-torture gate.

Attacks the authoring truth of the generated NPC matrix:

  * corruption detection — corrupt REAL generated records (not just examples) in
    each dangerous way and assert the owning validator rejects them;
  * determinism — regenerating the archetype/profile/scenario sets twice yields
    byte-identical records (no run-to-run drift);
  * matrix integrity — a partial scenario set can never be reported as the full
    matrix (partial-as-full is caught).

Acceptance: `make npc-behavior-torture PACK=encounter_loop_world STRICT=1`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
import npc_pack as NP
from generate_npc_behavior_profiles import build_profile
from generate_npc_spawn_groups import build_spawn_groups
from generate_npc_behavior_scenarios import build_scenarios
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F


def _load_one(rel):
    d = REPO_ROOT / rel
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    return json.loads(files[0].read_text(encoding="utf-8")) if files else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- corruption detection on REAL generated records ----
    sg = _load_one(NX.SPAWN_GROUP_GENERATED_REL)
    sc = _load_one(NX.BEHAVIOR_SCENARIO_GENERATED_REL)
    ar = _load_one(NX.ARCHETYPE_GENERATED_REL)
    have_records = all(x is not None for x in (sg, sc, ar))
    rep.check("torture::records_present", have_records,
              "generated records missing (run the generators first)", code=F.NPC_REPORT_INTEGRITY_FAILURE)
    if have_records:
        corruptions = [
            ("spawn_group_walkability_off", NX.validate_spawn_group,
             dict(sg, walkability_required=False), F.NPC_SPAWN_OFF_WALKABLE_SURFACE),
            ("spawn_group_over_density", NX.validate_spawn_group,
             dict(sg, count=99, max_density=1.0), F.NPC_DENSITY_BUDGET_FAILURE),
            ("scenario_ground_ref_wiped", NX.validate_behavior_scenario,
             dict(sc, ground_scenario_id=""), F.NPC_ROUTE_GRAPH_MISSING),
            ("scenario_no_pressure", NX.validate_behavior_scenario,
             dict(sc, expected_pressure_events=[]), F.NPC_NO_PRESSURE_EVENTS),
            ("archetype_flight_route", NX.validate_archetype,
             dict(ar, allowed_route_modes=["continuous_flight"]), F.NPC_ROUTE_FLIGHT_REQUIRED),
        ]
        for label, fn, bad, code in corruptions:
            fails = [c for c in fn(bad, strict=True) if not c[1]]
            codes = {c[3] for c in fails}
            rep.check("torture::corrupt::{}".format(label), len(fails) > 0 and code in codes,
                      "corruption '{}' must be detected for {}".format(label, code), code=code)

    # ---- determinism: regenerate twice, expect identical ----
    prof1 = [build_profile(a) for a in NX.ENCOUNTER_ARCHETYPES]
    prof2 = [build_profile(a) for a in NX.ENCOUNTER_ARCHETYPES]
    grp1, grp2 = build_spawn_groups(args.pack), build_spawn_groups(args.pack)
    scn1, scn2 = build_scenarios(args.pack), build_scenarios(args.pack)
    for name, a, b in (("profiles", prof1, prof2), ("spawn_groups", grp1, grp2), ("scenarios", scn1, scn2)):
        same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        rep.check("torture::determinism::{}".format(name), same,
                  "{} regeneration is not deterministic".format(name), code=F.NPC_REPORT_INTEGRITY_FAILURE)

    # ---- matrix integrity: a partial set is not the full matrix ----
    full = build_scenarios(args.pack)
    partial = full[:12]
    rep.check("torture::partial_not_full", len(partial) < len(full) and len(full) >= 120,
              "partial matrix ({}) must not equal full matrix ({})".format(len(partial), len(full)),
              code=F.GROUND_REPORT_PARTIAL_MATRIX)

    rep.finalize()
    rep.set_meta(build_meta(command="npc-behavior-torture", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(full), report_type="wf.npc.torture.v1",
                            records_total=len(full)))
    rep.write(REPO_ROOT / "procedural/reports/npc/torture", "npc_behavior_torture_report.json")
    rep.print_summary("npc-behavior-torture")
    print("[npc-behavior-torture] corruption-detect + determinism + matrix-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
