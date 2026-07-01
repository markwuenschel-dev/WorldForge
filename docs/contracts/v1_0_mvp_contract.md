# WorldForge v1.0 MVP Contract — `desert_mvp_world`

Status: **Pass 1 complete** (spec + matrix + coverage gate green). Owner: Agent 0 (Integration Captain).

## Mission

Prove the WorldForge factory can generate **a small playable adaptive world pack from data**. The target pack is `desert_mvp_world`. v1.0 builds the MVP pack only — it does not start v1.1 and does not open a new Forge system.

## Target pack

- World pack: `procedural/world_packs/desert_mvp_world.yaml`
- Slice matrix: `procedural/slice_packs/desert_mvp_world.yaml` (25 maps)
- Biome: `desert`

## Coverage contract (MVP minimums → actuals)

Enforced by `validate-world-pack-spec` (WARN, blocking under `STRICT=1`):

| Category | Minimum | `desert_mvp_world` | Source of truth |
|---|---|---|---|
| Maps | 25 | **25** | slice matrix |
| Terrain forms | 3 | **3** — ash_flats, cracked_ridge, sandy_basin | `procedural/definitions/terrain/` |
| Material variants | 8 | **8** — ash, clean, cracked, heavy_industrial, industrialized, light_industrial, ruined_industrial, sandy | `procedural/slices/desert_<variant>.yaml` |
| Placement presets | 6 | **6** — clean_scrub, dead_scrub, industrial_debris, mixed_ruins, reclaimed_scrub, rocky_basin | `procedural/definitions/placement/desert/` |
| POI templates | 5–6 | **6** — abandoned_mining_camp, ash_shrine_ruin, cracked_ridge_lookout, debris_checkpoint, industrial_yard, scrubland_resource_node | `procedural/definitions/poi/` |
| State presets | 2+ | **4** — clean, light_industrial, industrialized, ruined_industrial | `procedural/definitions/state/desert/` |
| Runtime scenario paths | 2 | **3** — industrial_takeover, clean_preserve, resource_survey | per-slice `scenarios:` metadata |

New in v1.0 (smallest gap-fill only, per the non-negotiable rules): terrain forms `cracked_ridge` + `sandy_basin`, placement preset `reclaimed_scrub`. Nothing else was invented; everything else reuses proven v0.5–v0.9 surfaces.

Coverage report (machine-readable): `procedural/reports/coverage/desert_mvp_world_coverage.json`.

## Matrix design rule

Every row earns its place by **contrast** (terrain / material / placement / POI / state / scenario), never by seed-noise duplication. Rows are grouped into three scenario paths:

- `industrial_takeover` — high industrial pressure (industrialized / ruined_industrial states, industrial POIs).
- `clean_preserve` — clean / low-impact (clean state, scrub & shrine POIs, reclaimed scrub).
- `resource_survey` — resource-oriented (scrubland_resource_node, mining camps, dead scrub).

## Command surface (canonical = Makefile targets)

```bash
make worldforge-doctor
make validate-world-pack-spec PACK=desert_mvp_world            # v1.0, Pass-1 gate
make create-world-pack       PACK=desert_mvp_world JOBS=6
make validate-world-pack     PACK=desert_mvp_world DEEP=1 STRICT=1
make run-world-state-scenario PACK=desert_mvp_world SCENARIO=industrial_takeover   # Pass 4 (to build)
make package-check           PACK=desert_mvp_world
make repair-world-pack       PACK=desert_mvp_world
make destroy-world-pack      PACK=desert_mvp_world CONFIRM=1
```

`make` is the documented surface; each target is a thin wrapper over a `tools/pipeline/*.py` entrypoint, so any step can also be run directly with `PYTHONUTF8=1 python tools/pipeline/<script>.py ...` (required on Windows — see memory `windows-utf8-validators`).

## Merge / integration order

```
Pass 0  freeze v0.9 ............................. DONE (tag v0.9-production-hardening)
Pass 1  contract + matrix + spec gate ........... DONE (validate-world-pack-spec PASS, strict)
Pass 2  10-map smoke (orchestration + validate) . headless prep proves path; UE map gen is D7-gated
Pass 3  25-map MVP + DEEP STRICT validate
Pass 4  run-world-state-scenario industrial_takeover  (+ save/load round trip)
Pass 5  playable inspection layer + inspection-metadata validation
Pass 6  package-check + repair + destroy + rebuild + strict re-validate
Pass 7  optional expand toward 50 maps
Pass 8  docs/runbook + final regression shield (poi_lite_seed, production_seed green)
```

## Final integration gate (definition of done)

`desert_mvp_world` is DONE when, from a clean tree:

```bash
make worldforge-doctor
make create-world-pack        PACK=desert_mvp_world JOBS=6
make validate-world-pack      PACK=desert_mvp_world DEEP=1 STRICT=1
make run-world-state-scenario PACK=desert_mvp_world SCENARIO=industrial_takeover
make package-check            PACK=desert_mvp_world
make repair-world-pack        PACK=desert_mvp_world
make destroy-world-pack       PACK=desert_mvp_world CONFIRM=1
make create-world-pack        PACK=desert_mvp_world JOBS=6
make validate-world-pack      PACK=desert_mvp_world DEEP=1 STRICT=1
```

all pass, AND the v0.5–v0.9 regression packs (`desert_poi_lite_seed`, `desert_production_seed`) remain green.

## Known environment gates (not regressions)

- **D7 / Content\*\*\* gate:** generated maps + materials live under `Content/**` and are CODEOWNERS/CI-gated against agent authorship. UE materialization (map build, terrain heightmap import, material overrides) is therefore a **human/editor step**; validators record those checks as `GATED_HUMAN_EDITOR` (non-blocking even under `--strict`) until the editor-authorized command runs. The data/spec/prep/coverage/lifecycle layers are fully agent-runnable and strictly validated.
- **Master base-color render bug:** deferred to TICKET-001; not a v1.0 blocker.

## Explicitly out of scope for v1.0

Open-world streaming, final art, new biome family, MeshForge / Substance replacement / external library import, QuestForge / NPCForge / FactionForge / EconomyForge / SettlementForge / DungeonForge / WeatherForge, web dashboards, editor plugins, recipe visual editors, general-purpose game generation.
