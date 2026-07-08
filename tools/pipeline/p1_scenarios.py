#!/usr/bin/env python3
"""p1_scenarios.py — WorldForge v1.6 P1 representative-live-runtime selection.

Resolves the 12 P1 scenarios (6 archetypes x 2 pressure profiles) from the
runtime scenario manifest, covering all 5 biomes, all 6 mission archetypes, both
encounter pressure profiles, and both seeds. "Seed" = the two distinct map
variants that exist for each (biome, archetype) pair; sorted, index 0 = seed01,
index 1 = seed02.

This is the single source of the P1 set so the batch runner, the coverage gate,
and the rollup all agree on exactly which 12 scenarios count as P1.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_REL = "procedural/generated/worldforge_runtime_scenario_manifest.json"

LIGHT = "light_pressure"
STD = "standard_pressure"

# (biome, archetype, profile, seed_index) — the operator-approved P1 matrix.
P1_ROWS = [
    ("temperate_forest", "disable_site", LIGHT, 0),
    ("temperate_forest", "recover_resource", STD, 1),
    ("alpine_snow", "survey_landmark", LIGHT, 0),
    ("alpine_snow", "clear_hazard", STD, 1),
    ("volcanic_ashlands", "restore_power", LIGHT, 0),
    ("volcanic_ashlands", "extract_cache", STD, 1),
    ("wetland_mire", "disable_site", STD, 1),
    ("wetland_mire", "survey_landmark", LIGHT, 0),
    ("alien_crystal_badlands", "recover_resource", LIGHT, 0),
    ("alien_crystal_badlands", "clear_hazard", STD, 1),
    ("temperate_forest", "restore_power", STD, 0),
    ("alpine_snow", "extract_cache", LIGHT, 1),
]


def load_manifest():
    return json.loads((REPO_ROOT / MANIFEST_REL).read_text(encoding="utf-8"))["scenarios"]


def resolve(manifest=None):
    """Return the ordered list of 12 P1 records:
    {seq, scenario_id, map_id, biome, archetype, profile, seed_index}."""
    m = manifest or load_manifest()
    # maps per (biome, archetype), sorted → seed index
    maps_by = {}
    for v in m.values():
        maps_by.setdefault((v["biome"], v["mission_archetype"]), set()).add(v["map_id"])
    maps_by = {k: sorted(vs) for k, vs in maps_by.items()}
    # scenario id by (map_id, profile)
    by_map_profile = {(v["map_id"], v["encounter_profile"]): sid for sid, v in m.items()}

    out = []
    for i, (biome, arch, profile, seed) in enumerate(P1_ROWS, 1):
        variants = maps_by.get((biome, arch), [])
        if seed >= len(variants):
            raise SystemExit("P1 row {}: no seed {} for {}/{} (have {})".format(
                i, seed, biome, arch, variants))
        map_id = variants[seed]
        sid = by_map_profile.get((map_id, profile))
        if not sid:
            raise SystemExit("P1 row {}: no scenario for {} / {}".format(i, map_id, profile))
        out.append({"seq": i, "scenario_id": sid, "map_id": map_id, "biome": biome,
                    "archetype": arch, "profile": profile, "seed_index": seed})
    return out


def coverage(records=None):
    """Return a coverage summary dict for the P1 set."""
    recs = records or resolve()
    return {
        "count": len(recs),
        "biomes": sorted({r["biome"] for r in recs}),
        "archetypes": sorted({r["archetype"] for r in recs}),
        "profiles": sorted({r["profile"] for r in recs}),
        "seeds": sorted({r["seed_index"] for r in recs}),
    }


def coverage_ok(records=None):
    c = coverage(records)
    return (c["count"] == 12 and len(c["biomes"]) == 5 and len(c["archetypes"]) == 6
            and len(c["profiles"]) == 2 and len(c["seeds"]) == 2)


if __name__ == "__main__":
    recs = resolve()
    for r in recs:
        print("{seq:02d}  {biome:24s} {archetype:16s} {profile:18s} seed{seed} {sid}".format(
            seq=r["seq"], biome=r["biome"], archetype=r["archetype"], profile=r["profile"],
            seed=r["seed_index"] + 1, sid=r["scenario_id"]))
    c = coverage(recs)
    print("coverage:", c)
    assert coverage_ok(recs), "P1 coverage incomplete: {}".format(c)
    print("OK P1 coverage: 12 scenarios, 5 biomes, 6 archetypes, 2 profiles, 2 seeds")
