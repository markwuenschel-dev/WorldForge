#!/usr/bin/env python3
"""generate_slice_scenarios.py — v2.0 Agent-1 slice authoring generator.

Deterministically emits the vertical-slice definition by binding to REAL existing
encounter_loop_world content (NOT invented ids): it reads the runtime route
catalog as the source of truth for the (biome, archetype, map_id) tuples, then
writes:

    procedural/generated/slice/vertical_slice_contract.json   (the slice matrix)
    procedural/generated/slice/scenarios/vs_*.json            (24 SliceScenario)
    procedural/generated/slice/manifest.json                  (index over the slice)

The 24-scenario matrix (2 x 3 x 2 x 2):
    biomes             : alpine_snow (readable), volcanic_ashlands (stress)
    mission_archetypes : survey_landmark (reach), recover_resource (recover),
                         clear_hazard (survive/clear)
    encounter_profiles : baseline, high   (slice-level PRESSURE profiles applied
                         over the single authored base encounter per map; the
                         authored encounters are all light_pressure, so the "high"
                         profile is a runtime pressure setting + the high reward
                         band, NOT a separately authored encounter — see the v2.0
                         contract doc caveat)
    seeds              : 1, 2  (the two materialized site variants per biome x
                         archetype cell — e.g. GlacialBasin=1, SnowyRidge=2)

Binding per scenario (all resolve to real files, verified by
validate_slice_scenarios.py):
    map_id                    = <the real .umap under Content/WorldForge/Maps>
    mission_id                = mission_<map_id>
    encounter_id              = enc_lp_<map_id>
    expected_route_id         = route_<map_id>__<archetype>
    expected_reward_table_id  = rwt_<archetype>_<baseline|high>
    expected_build_target     = WorldForgeVerticalSlice

Deterministic: sorted iteration, fixed authoring timestamp, no wall-clock / RNG.
Idempotent: rewrites the same bytes for the same catalog.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_slice_scenarios.py \
        --pack encounter_loop_world --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX

SLICE_ID = "worldforge_vertical_slice"
BUILD_TARGET = "WorldForgeVerticalSlice"
BIOMES = ("alpine_snow", "volcanic_ashlands")
ARCHETYPES = ("survey_landmark", "recover_resource", "clear_hazard")
PROFILES = ("baseline", "high")  # slice pressure profile == reward risk band
BIOME_PREFIX = {"Alpine": "alpine_snow", "Ashlands": "volcanic_ashlands"}

ROUTE_CATALOG_REL = "procedural/generated/worldforge_runtime_route_catalog.json"


def _biome_of(map_id):
    for pfx, biome in BIOME_PREFIX.items():
        if map_id.startswith(pfx):
            return biome
    return None


def _load_binding():
    """Return {(biome, archetype): [map_id, ...sorted]} from the real route catalog."""
    cat = json.loads((REPO_ROOT / ROUTE_CATALOG_REL).read_text(encoding="utf-8"))
    routes = cat.get("routes", {})
    cells = {}
    for rid in routes:
        # route_<map_id>__<archetype>
        body = rid[len("route_"):]
        map_id, arch = body.rsplit("__", 1)
        biome = _biome_of(map_id)
        if biome in BIOMES and arch in ARCHETYPES:
            cells.setdefault((biome, arch), []).append(map_id)
    for k in cells:
        cells[k] = sorted(set(cells[k]))
    return cells


def build_records():
    cells = _load_binding()
    scenarios = []
    maps = []
    for biome in BIOMES:
        for arch in ARCHETYPES:
            cell_maps = cells.get((biome, arch), [])
            if len(cell_maps) < 2:
                raise SystemExit(
                    "binding gap: (%s, %s) has %d maps, need >= 2" % (biome, arch, len(cell_maps)))
            for seed, map_id in enumerate(cell_maps[:2], start=1):
                maps.append(map_id)
                for profile in PROFILES:
                    ssid = "vs_{}_{}_{}_s{}".format(biome, arch, profile, seed)
                    scn = SX._example_slice_scenario(
                        slice_scenario_id=ssid,
                        slice_id=SLICE_ID,
                        pack_id="encounter_loop_world",
                        biome=biome,
                        mission_archetype=arch,
                        encounter_profile=profile,
                        seed=seed,
                        map_id=map_id,
                        mission_id="mission_{}".format(map_id),
                        encounter_id="enc_lp_{}".format(map_id),
                        expected_route_id="route_{}__{}".format(map_id, arch),
                        expected_reward_table_id="rwt_{}_{}".format(arch, profile),
                        expected_build_target=BUILD_TARGET,
                    )
                    scenarios.append(scn)

    scenarios.sort(key=lambda s: s["slice_scenario_id"])
    scenario_ids = [s["slice_scenario_id"] for s in scenarios]
    maps = sorted(set(maps))

    contract = SX._example_vertical_slice_contract(
        slice_id=SLICE_ID,
        pack_id="encounter_loop_world",
        biomes=list(BIOMES),
        mission_archetypes=list(ARCHETYPES),
        encounter_profiles=list(PROFILES),
        seeds=[1, 2],
        scenario_count=len(scenarios),
    )
    manifest = SX._example_slice_manifest(
        slice_id=SLICE_ID,
        pack_id="encounter_loop_world",
        scenario_count=len(scenarios),
        scenarios=scenario_ids,
        maps=maps,
        biomes=list(BIOMES),
        mission_archetypes=list(ARCHETYPES),
        encounter_profiles=list(PROFILES),
        seeds=[1, 2],
        build_target=BUILD_TARGET,
    )
    return contract, scenarios, manifest


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice scenario generator.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.parse_known_args(argv)

    contract, scenarios, manifest = build_records()

    _write_json(REPO_ROOT / SX.SLICE_CONTRACT_REL, contract)
    scen_dir = REPO_ROOT / SX.SLICE_SCENARIOS_REL
    # clean stale scenario files so a re-run is authoritative (idempotent set).
    if scen_dir.is_dir():
        for f in scen_dir.glob("vs_*.json"):
            f.unlink()
    for scn in scenarios:
        _write_json(scen_dir / "{}.json".format(scn["slice_scenario_id"]), scn)
    _write_json(REPO_ROOT / SX.SLICE_MANIFEST_REL, manifest)

    print("[generate-slice-scenarios] wrote contract + {} scenarios + manifest -> {}".format(
        len(scenarios), SX.SLICE_GENERATED_REL))
    # fail-closed: the matrix MUST be exactly 24.
    if len(scenarios) != 24:
        print("[generate-slice-scenarios] FAIL: expected 24 scenarios, got {}".format(len(scenarios)))
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
