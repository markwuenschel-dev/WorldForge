# WorldForge

**WorldForge is a tooling layer, not a game.** It is the factory that lets you build
adaptive games faster.

```
Unreal Engine 5.7
    ↓
WorldForge tooling layer   ← this project
    ↓
Your actual game           ← a separate project, built later
```

The game built on top could be an open-world RPG, a base-builder survival game, a
colony sim, or a faction-driven sandbox. WorldForge stays general enough to
support any of them.

## What it provides

Two halves, one contract-driven pipeline:

- **The headless forge (Python, `tools/` + `procedural/`)** — generates world
  content as validated data: terrain, biome slices, POIs, placement, meshes,
  missions, environment rigs. Every generator has validators, negative fixtures,
  and lifecycle (destroy/rebuild) coverage. Nothing counts as done until its
  validation gate is green under `STRICT`.
- **The UE plugin (`Plugins/WorldForge/`)** — the reusable in-engine factory:
  world-state contracts, generation-rule primitives (`WorldForgeCore`, runtime)
  and procedural materials / manifest import automation (`WorldForgeEd`,
  editor-only). Port this folder into any game.

Agents drive a live Unreal editor through the NeoStackAI bridge
(`execute_script`) to materialize the generated specs as real maps and actors —
60 biome/mission maps currently carry fully spec-bound environment rigs
(sky, sun, skylight, fog, volumetric cloud, post-process).

## The forge lineage

| Version | System | Status |
| --- | --- | --- |
| v0.2–v0.8 | Slice factory, world packs, TerrainForge/POIForge Lite, runtime StateForge | shipped |
| v0.9 | Hardening: STRICT mode, audit, package-check, lifecycle | merged to `main` |
| v1.0/v1.0x | `desert_mvp_world` (25 maps) + hostile validation platform (~40 validators) | shipped |
| v1.1 | BiomeForge: 5 biomes × 60 maps, materialized in-editor | shipped |
| v1.2 | MeshForge intake: 42 generated meshes + 51 Megascans (ownership-distinct) | shipped |
| v1.3 | MissionForge + PlaytestForge: 60 biome-aware mission loops, 60/60 playtested | shipped |
| v1.3.5 | Visual Fidelity: 60 environment rigs resolved **and live-spawned in UE** | shipped |

Canonical verification (all under `STRICT=1`):

```
full_shield.py --pack mission_loop_world  --strict --torture --meshes --missions --playtest --visuals   → 69/69
full_shield.py --pack biome_expansion_world --strict --torture --meshes                                 → 76/76
full_shield.py --pack desert_mvp_world      --strict --torture                                          → 33/33
```

## Running the pipeline

Every `Makefile` target maps 1:1 to a `python tools/pipeline/<script>.py`
entrypoint, so `make` is optional. On Windows always run with `PYTHONUTF8=1`.

```bash
# the whole shield for a world pack
PYTHONUTF8=1 STRICT=1 MEGASCANS=1 HOUDINI=metadata_only \
  python tools/pipeline/full_shield.py --pack mission_loop_world \
  --jobs 8 --strict --torture --meshes --missions --playtest --visuals

# single factory operations (see `make help` / Makefile for the full set, 100+ targets)
make create-slice BIOME=desert VARIANT=dunes NAME=my_slice
make create-slice-pack PACK=desert_foundation
make create-terrain / create-poi / run-state-sim ...
```

Flags thread through the environment: `STRICT`, `DEEP`, `TORTURE`, `SEEDS`,
`MESHES`, `MEGASCANS`, `HOUDINI`, `MISSIONS`, `PLAYTEST`, `VISUALS`.

## Layout

```
WorldForge/
├── WorldForge.uproject         UE 5.7 host shell (disposable)
├── Source/WorldForge/          minimal primary game module
├── Plugins/WorldForge/         THE reusable factory — port this into any game
│   └── Source/
│       ├── WorldForgeCore/     Runtime: world-state contracts + generation-rule primitives
│       └── WorldForgeEd/       Editor-only: materials, manifest pipeline, import automation
├── tools/
│   ├── pipeline/               headless generators + validators (the shield)
│   └── unreal/                 in-editor drivers (run inside UE / via NeoStack bridge)
├── procedural/
│   ├── definitions/            hand-authored specs (recipes, presets, profiles)
│   ├── generated/              generator output — never hand-edit
│   └── reports/                validation evidence, one report per gate
├── Content/WorldForge/Maps/    materialized biome/mission maps (60 rigged)
├── docs/                       ARCHITECTURE.md, contracts/, runbooks/, followups/
└── tests/
```

The ownership rule of thumb:

| Belongs in the factory | Does **not** belong |
| --- | --- |
| Material/generation pipelines | Specific lore, factions, enemies |
| World-state contracts (schemas) | Specific quests, base buildings |
| Import/manifest automation | Hand-authored game content |
| Generation *rules* | Generation *results* (those go to `procedural/generated/`) |

Third-party content stays ownership-distinct: Megascans assets are cataloged as
`third_party_owned` (destroy-protected, never vendored as "generated"); Houdini
plugin binaries are not committed (`HOUDINI=metadata_only` until a live cook
environment exists).

## Getting started

1. Open `WorldForge.uproject` in Unreal Editor 5.7 (or right-click → Generate
   Visual Studio project files) and let it compile `WorldForge`,
   `WorldForgeCore`, and `WorldForgeEd`.
2. `python tools/pipeline/full_shield.py --pack desert_mvp_world --strict` to
   confirm the headless pipeline is green on your machine.

## Conventions for agents

- Treat `Plugins/WorldForge/` as reusable infrastructure. No game-specific
  content, lore, or assets in it.
- Runtime-safe code goes in `WorldForgeCore`; editor-only tooling in `WorldForgeEd`.
- World-state contracts describe *capabilities and parameters*, never specific
  game content.
- Never hand-edit `procedural/generated/` or `procedural/reports/` — regenerate
  through the pipeline so provenance and determinism checks stay honest.
- Never weaken a validator to make a gate pass; fix the content or the generator.
  Every new validator ships with negative fixtures proving it can fail.
- Run Python tooling with `PYTHONUTF8=1` on Windows.
- A live editor is available through the NeoStackAI bridge — drive it
  (`execute_script`, LevelDesign API) rather than deferring editor-side work.
