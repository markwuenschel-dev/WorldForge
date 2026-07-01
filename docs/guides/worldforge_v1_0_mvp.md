# WorldForge v1.0 — MVP Guide

## What WorldForge v1.0 is

A **data-driven factory for a small playable adaptive world pack**. From a single
pack spec plus reusable definitions, it composes terrain, materials, placement,
POIs, and world-state into generated, validated, inspectable, packageable,
repairable/destroyable maps. The v1.0 deliverable is one proven pack:
`desert_mvp_world` (25 maps).

It proves the full chain end to end:

```
pack spec → terrain/material/placement/POI/state composition → generated maps
→ runtime scenarios → save/load → strict validation → budgets
→ registry/provenance → repair/destroy lifecycle → package-check → playable inspection
```

## What WorldForge v1.0 is NOT

Not open-world streaming, not final art, not a new biome family, not MeshForge /
Substance replacement / external-library import, not Quest/NPC/Faction/Economy/
Settlement/Dungeon/Weather systems, not a web dashboard or editor plugin, and not a
general-purpose game generator. See `docs/status/v1_0_known_limitations.md`.

## How it fits together

- **World pack** (`procedural/world_packs/desert_mvp_world.yaml`) references one or
  more **slice packs**.
- **Slice pack** (`procedural/slice_packs/desert_mvp_world.yaml`) is the 25-row
  matrix. Each row = `{name, variant, seed, placement, state_preset, terrain, poi}`
  plus MVP metadata (`scenarios`, `intent`). Every row earns its place by contrast,
  organised into three scenario paths: `industrial_takeover`, `clean_preserve`,
  `resource_survey`.
- **Definitions** are the reusable surfaces: variant templates
  (`procedural/slices/desert_<variant>.yaml`), terrain recipes
  (`definitions/terrain/`), placement presets (`definitions/placement/desert/`),
  POI templates (`definitions/poi/`), state presets (`definitions/state/desert/`),
  scenarios (`definitions/scenarios/`).

New in v1.0 (smallest gap-fill only): terrain forms `cracked_ridge` + `sandy_basin`,
placement preset `reclaimed_scrub`, scenario `industrial_takeover`, and the tooling
`validate-world-pack-spec`, `run-world-state-scenario`, `inspect-world-pack` /
`validate-inspection`. Two incomplete variant templates (`desert_light_industrial`,
`desert_ruined_industrial`) were completed (missing `preview_base_color`), and the
spec validator was hardened to check variant-template completeness so that class of
defect is caught at spec time, not generation time.

## Command surface

| Purpose | Command |
|---|---|
| Health check | `make worldforge-doctor` |
| Spec pre-flight (no UE) | `make validate-world-pack-spec PACK=desert_mvp_world STRICT=1` |
| Generate | `make create-world-pack PACK=desert_mvp_world JOBS=6` |
| Strict deep validate | `make validate-world-pack PACK=desert_mvp_world DEEP=1 STRICT=1` |
| Runtime scenario | `make run-world-state-scenario PACK=desert_mvp_world SCENARIO=industrial_takeover STRICT=1` |
| Inspection metadata | `make inspect-world-pack PACK=desert_mvp_world` / `make validate-inspection PACK=desert_mvp_world` |
| Package check | `make package-check PACK=desert_mvp_world` |
| Lifecycle | `make repair-world-pack ...` / `make destroy-world-pack ... CONFIRM=1` |

Full step-by-step: `docs/runbooks/desert_mvp_world_runbook.md`. Definition of done
and coverage contract: `docs/contracts/v1_0_mvp_contract.md`.

## Interpreting reports

- **Coverage** (`reports/coverage/desert_mvp_world_coverage.json`) — matrix breadth
  vs MVP minimums.
- **Validation** — per-map 34-check strict result; `PASS/WARN/FAIL/GATED`. `GATED`
  means a D7 human/editor UE step is pending, never a failure.
- **Scenario** (`reports/world_packs/.../run_world_state_scenario_report.json`) —
  per-map state delta, POI evidence, save/load round-trip.
- **Package** (`reports/package_check/.../package_check_report.json`) — budgets +
  ownership/provenance/path integrity.
- **Inspection** (`reports/inspection/desert_mvp_world_inspection.json`) — human-
  readable composition + primary POI + playability per map.
