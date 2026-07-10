#!/usr/bin/env python3
"""validate_slice_scenarios.py — v2.0 Agent-1 slice authoring gate.

Proves the generated 24-scenario matrix is real: schema-valid, matrix-complete,
and every binding RESOLVES to real encounter_loop_world content on disk. This is
the gate the contract dogfood cannot cover — it checks that map_id/mission_id/
encounter_id/route_id/reward_table_id name artifacts that actually exist, that the
2x3x2x2 matrix is exactly covered with no duplicate cell, and (hostile dogfood)
that a scenario with an unknown dimension or a duplicate cell is rejected.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_scenarios.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/validate_slice_scenarios_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "slice"
MAPS_DIR = REPO_ROOT / "Content" / "WorldForge" / "Maps"
MISSIONS_DIR = REPO_ROOT / "procedural" / "generated" / "missions"
ENCOUNTERS_DIR = REPO_ROOT / "procedural" / "generated" / "encounters"
REWARD_TABLES_DIR = REPO_ROOT / "procedural" / "generated" / "rewards" / "tables"
ROUTE_CATALOG = REPO_ROOT / "procedural" / "generated" / "worldforge_runtime_route_catalog.json"


def _load_ctx():
    cat = json.loads(ROUTE_CATALOG.read_text(encoding="utf-8"))
    return {
        "route_ids": set(cat.get("routes", {}).keys()),
        "reward_tables": {p.stem for p in REWARD_TABLES_DIR.glob("*.json")},
    }


def resolve_scenario(scn, ctx, contract):
    """Cross-record resolution: every id must name a real artifact + a legal dim.

    Returns a list of (name, ok, detail, code) tuples (the ValidationReport shape).
    Kept pure so the hostile dogfood can exercise it on synthetic records.
    """
    sid = scn.get("slice_scenario_id", "?")
    p = "res::{}::".format(sid)
    ch = []
    # dimension membership against the contract
    ch.append((p + "biome_in_contract", scn.get("biome") in (contract.get("biomes") or []),
               "biome {!r} not in contract biomes".format(scn.get("biome")), F.SLICE_SCENARIO_INVALID))
    ch.append((p + "archetype_in_contract",
               scn.get("mission_archetype") in (contract.get("mission_archetypes") or []),
               "archetype {!r} not in contract".format(scn.get("mission_archetype")),
               F.SLICE_SCENARIO_INVALID))
    ch.append((p + "profile_in_contract",
               scn.get("encounter_profile") in (contract.get("encounter_profiles") or []),
               "profile {!r} not in contract".format(scn.get("encounter_profile")),
               F.SLICE_SCENARIO_INVALID))
    ch.append((p + "seed_in_contract", scn.get("seed") in (contract.get("seeds") or []),
               "seed {!r} not in contract seeds".format(scn.get("seed")), F.SLICE_SCENARIO_INVALID))
    # artifact resolution on disk
    mid = scn.get("map_id") or ""
    ch.append((p + "umap_exists", bool(mid) and (MAPS_DIR / (mid + ".umap")).is_file(),
               "map .umap missing for {!r}".format(mid), F.SLICE_ENVIRONMENT_INVALID))
    ch.append((p + "mission_exists", (MISSIONS_DIR / "mission_{}".format(mid)).is_dir(),
               "mission dir missing for {!r}".format(mid), F.SLICE_SCENARIO_INVALID))
    ch.append((p + "encounter_exists", (ENCOUNTERS_DIR / "enc_lp_{}".format(mid)).is_dir(),
               "encounter dir missing for {!r}".format(mid), F.SLICE_SCENARIO_INVALID))
    ch.append((p + "route_resolves", scn.get("expected_route_id") in ctx["route_ids"],
               "route {!r} not in route catalog".format(scn.get("expected_route_id")),
               F.SLICE_ROUTE_BINDING_INVALID))
    ch.append((p + "reward_table_resolves",
               scn.get("expected_reward_table_id") in ctx["reward_tables"],
               "reward table {!r} not found".format(scn.get("expected_reward_table_id")),
               F.SLICE_REWARD_TABLE_BINDING_INVALID))
    # id-consistency: derived ids must match the map
    ch.append((p + "mission_id_matches_map", scn.get("mission_id") == "mission_{}".format(mid),
               "mission_id must be mission_<map_id>", F.SLICE_SCENARIO_INVALID))
    ch.append((p + "encounter_id_matches_map", scn.get("encounter_id") == "enc_lp_{}".format(mid),
               "encounter_id must be enc_lp_<map_id>", F.SLICE_SCENARIO_INVALID))
    # reward band must match the pressure profile (baseline/high)
    prof = scn.get("encounter_profile")
    ch.append((p + "reward_band_matches_profile",
               str(scn.get("expected_reward_table_id", "")).endswith("_" + str(prof)),
               "reward table band must match profile {!r}".format(prof),
               F.SLICE_REWARD_TABLE_BINDING_INVALID))
    return ch


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice scenario authoring gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    contract_path = REPO_ROOT / SX.SLICE_CONTRACT_REL
    manifest_path = REPO_ROOT / SX.SLICE_MANIFEST_REL
    scen_dir = REPO_ROOT / SX.SLICE_SCENARIOS_REL

    # fail-closed: the generated artifacts must exist.
    rep.check("contract_present", contract_path.is_file(),
              "run generate_slice_scenarios.py first", code=F.SLICE_CONTRACT_INVALID)
    rep.check("manifest_present", manifest_path.is_file(),
              "manifest.json missing", code=F.SLICE_MANIFEST_INVALID)
    if not (contract_path.is_file() and scen_dir.is_dir()):
        rep.error("slice authoring artifacts absent")
        rep.finalize()
        rep.set_meta(build_meta(command="validate-slice-scenarios", pack=args.pack,
                                strict=strict, status=rep.status, record_count=0,
                                report_type="wf.slice.scenarios.v1"))
        rep.write(REPORT_DIR, "validate_slice_scenarios_report.json")
        rep.print_summary("validate-slice-scenarios")
        sys.exit(rep.exit_code)

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    ctx = _load_ctx()

    scen_files = sorted(scen_dir.glob("vs_*.json"))
    scenarios = [json.loads(f.read_text(encoding="utf-8")) for f in scen_files]

    # 1. exactly 24, matching contract scenario_count
    rep.check("scenario_count_is_24", len(scenarios) == 24,
              "expected 24 scenarios, got {}".format(len(scenarios)), code=F.SLICE_PARTIAL_MATRIX)
    rep.check("count_matches_contract", contract.get("scenario_count") == len(scenarios),
              "contract scenario_count != file count", code=F.SLICE_SCENARIO_SET_INVALID)

    # 2. each scenario schema-valid + resolves
    for scn in scenarios:
        sfails = [c for c in SX.validate_slice_scenario(scn, strict=True) if not c[1]]
        rep.check("schema::{}".format(scn.get("slice_scenario_id", "?")), len(sfails) == 0,
                  "schema failures: {}".format([c[0] for c in sfails][:4]),
                  code=F.SLICE_SCENARIO_INVALID)
        for name, ok, detail, code in resolve_scenario(scn, ctx, contract):
            rep.check(name, ok, detail, code=code)

    # 3. matrix completeness: every (biome,archetype,profile,seed) cell exactly once
    cells = [(s.get("biome"), s.get("mission_archetype"), s.get("encounter_profile"),
              s.get("seed")) for s in scenarios]
    expected = set()
    for b in contract.get("biomes", []):
        for a in contract.get("mission_archetypes", []):
            for p in contract.get("encounter_profiles", []):
                for sd in contract.get("seeds", []):
                    expected.add((b, a, p, sd))
    rep.check("matrix_no_duplicate_cell", len(cells) == len(set(cells)),
              "duplicate scenario dimension tuple present", code=F.SLICE_DUPLICATE_SCENARIO_REPORT)
    rep.check("matrix_fully_covered", set(cells) == expected,
              "matrix cells {} != expected {}".format(len(set(cells)), len(expected)),
              code=F.SLICE_PARTIAL_MATRIX)
    rep.check("scenario_ids_unique",
              len({s.get("slice_scenario_id") for s in scenarios}) == len(scenarios),
              "duplicate slice_scenario_id", code=F.SLICE_DUPLICATE_SCENARIO_REPORT)

    # 4. hostile dogfood: resolution MUST reject bad scenarios. The good fixture is
    #    a REAL current scenario (not a hardcoded literal), so this schema self-test
    #    cannot rot when the generator renames maps/routes/tables.
    if scenarios:
      good = dict(scenarios[0])
      gfails = [c for c in resolve_scenario(good, ctx, contract) if not c[1]]
      rep.check("dogfood::good_scenario_resolves", len(gfails) == 0,
                "reference scenario failed resolution: {}".format([c[0] for c in gfails][:4]),
                code=F.SLICE_REPORT_INTEGRITY_FAILED)
      # flip to the opposite pressure band so the reward-table binding mismatches.
      other_profile = "high" if good.get("encounter_profile") == "baseline" else "baseline"
      for label, override in (
        ("unknown_biome", {"biome": "mars"}),
        ("unknown_archetype", {"mission_archetype": "hack_terminal"}),
        ("unknown_profile", {"encounter_profile": "extreme"}),
        ("unresolvable_map", {"map_id": "Nonexistent_Map_99"}),
        ("wrong_reward_band", {"encounter_profile": other_profile}),  # band no longer matches
      ):
        bad = dict(good)
        bad.update(override)
        bfails = [c for c in resolve_scenario(bad, ctx, contract) if not c[1]]
        rep.check("dogfood::{}_rejected".format(label), len(bfails) > 0,
                  "bad scenario '{}' must be rejected by resolution".format(label),
                  code=F.SLICE_NEGATIVE_ACCEPTED)

    n = len(scenarios)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-scenarios", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n, records_total=n,
                            report_type="wf.slice.scenarios.v1"))
    rep.write(REPORT_DIR, "validate_slice_scenarios_report.json")
    rep.print_summary("validate-slice-scenarios")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
