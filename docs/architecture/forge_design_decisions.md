# Forge Design Decisions (Living Log)

**Status**: Active — updated as decisions are locked during design.
**Scope**: How the "Forge" vision is realized in this repo. Aligns to and refines `procedural_world_architecture.md` (target architecture) without contradicting it.

This is an append-as-we-go decision record. Each entry is a locked decision with its rationale and the alternative rejected.

---

## D1 — Build order: depth-first, harden MaterialForge first
Finish MaterialForge to **true contract-completeness** (Data Asset + provenance + validation gates) before standing up any new forge.
- **Why**: It's the stated rule ("harden the foundation first"), and the Data-Asset-with-provenance pattern is the template every other forge copies. Shipping the wrong shape propagates to all six forges.
- **Rejected**: breadth-first tracer across all forges.

## D2 — A "Forge" is a logical lane, not a plugin
Material runtime types live in the existing `WorldForgeCore`; build automation stays in `tools/`; editor registration in `WorldForgeEd`; master/content in `CoreTerrainMaterials`. No per-forge plugin.
- **Why**: `WorldForgeCore` exists to be the shared, game-agnostic runtime-contract home; provenance and world-state types are cross-forge. Per-forge plugins multiply UBT/boilerplate for no payoff.
- **Rejected**: one UE plugin per forge.

## D3 — `MaterialRecipeDataAsset` = plain `UDataAsset` (provenance + linkage record)
A `UMaterialRecipeDataAsset : UDataAsset` in `WorldForgeCore`. Hard object refs for now. Fields: `RecipeId`, `SchemaVersion`, `SourceRecipePath`, `ManifestPath`, `GeneratorName`, `GeneratorVersion`, `GeneratedAtUtc`, `SourceCommit`, `bSourceTreeDirty`, `MaterialInstance`, `TextureOutputs` (map), `Parameters` (map).
- **Job**: answer "which recipe/params/commit/manifest produced this MI and these textures?" — for tooling, validation, audit, future world-state integration. **Not** a runtime-queried registry.
- **Upgrade trigger**: promote to `UPrimaryDataAsset` only when a runtime system must discover/enumerate/async-load/bundle recipes by id/type/tag.
- **Rejected**: `UPrimaryDataAsset` now (AssetManager cost is YAGNI).

## D4 — Provenance stamped at manifest generation, flows into the Data Asset
`generate_manifest.py` records `source_commit`, `dirty`, generator name/version, schema version, timestamp, and input hashes into the manifest; the UE step copies them verbatim into the Data Asset.
- **Honesty rules**: dirty working tree is **recorded, never hidden** (`bSourceTreeDirty` / `-dirty` suffix). Validation **rejects** a manifest older than its recipe (stale provenance).
- **Dirty policy**: allow-but-flag by default; `--strict` (CI/agent) hard-fails on dirty.
- **Rejected**: stamping at the UE step (duplicates git logic, leaves manifest provenance-less).

## D5 — Dedicated `create_data_asset.py` step
New single-purpose UE script, run after `create-material`. Manifest owns the output path (`ue.data_asset_path`, e.g. `/Game/WorldForge/Materials/DA_Terrain_Rock_Desert_01`). It reads the manifest, loads the MI + textures, creates/updates the Data Asset, copies provenance verbatim, saves, emits JSON. It does **not** create/mutate the MI or textures.
- **Why**: preserves one-job-per-script; provenance can be regenerated/repaired without touching the MI.
- **Pipeline order**: validate-recipe → generate-manifest → import-textures → create-material → create-data-asset → validate-assets.

## D6 — Validation: Python now, native `UEditorValidatorBase` deferred
Keep Python / UE-Python validators for v1; add native `UEditorValidatorBase` later (when rules are stable and Content-Browser/Data-Validation integration is wanted). Validation taxonomy:
- **Tier 1** — recipe/manifest (contract + provenance + staleness + naming).
- **Tier 2** — master-material (shader/sampler/permutation budget; human-owned `M_Terrain_Master`).
- **Tier 3** — generated-asset correctness (texture limits ≤2048 + sRGB + compression + mips + group; reference integrity; provenance copied; naming).
- **Key insight**: Material Instances inherit the master's shader cost, so heavy material-stat budgets belong to Tier 2 (master), not per-recipe.

## D7 — Agent-operability enforcement: in scope now, split by where it can run
- **Tier 0 (GitHub CI, no UE)** — repo/permission: CODEOWNERS, branch protection, forbidden-path checks (`check_agent_permissions.py`). Agent-editable: `procedural/substance/recipes/`, `procedural/definitions/`, `tools/`, `docs/`, `tests/`. Human-review: master content/`.uasset`/`.umap`/`.sbs`, `Source/WorldForge*`.
- **Tier 1 (GitHub CI, no UE)** — text-contract: `validate_recipe.py`, `generate_manifest.py`, negative fixtures, manifest JSON validity, "no YAML in `tools/unreal/`", Makefile `-n` sanity, provenance/staleness.
- **Tier 2 / Tier 3 (require UE)** — local pre-merge gate now; self-hosted UE runner later. **Not** required in hosted CI.
- **Principle**: enforce what's cheap and deterministic now; don't make hosted CI run Unreal (perfect gate → no gate).
- **New files**: `.github/CODEOWNERS`, `.github/workflows/worldforge_contracts.yml`, `tools/pipeline/check_agent_permissions.py`, `tests/fixtures/invalid_recipes/`, `tools/pipeline/test_negative_recipes.py`.

## D8 — MaterialForge v1 done-line
- **In**: `create_data_asset.py` + `UMaterialRecipeDataAsset`; provenance + input-hash + staleness guard; `validate_assets.py` extended to full Tier-3; Tier 0 + Tier 1 CI; docs updated.
- **Deferred (tracked)**: preview render (keep `make preview` failing-by-design), Tier-2 master-material validator, native `UEditorValidatorBase`, self-hosted UE CI.

## D9 — After MaterialForge: thin StateForge spine next
Not the full state system — a minimal `WorldStateSubsystem` + the state-consumption contract (`FWorldForgeStateContract` already started) + **one** proven end-to-end reaction (e.g. region `industrial_pressure` → soot param on the terrain MI via an MPC). Then PlacementForge becomes the second state-aware consumer.
- **Why**: world state is the vision's centerpiece; building all content forges blind to state and retrofitting is the real failure mode. A thin tracer spine ≠ the premature state monolith `adaptive_world_state_system.md` warns against.
- **Rejected**: state strictly last (A/C) — risks four content forges with no state hooks.

## D10 — State read contract: CPU pull-query (source of truth) + MPC render mirror
- **Canonical API** (the thing all forges bind to): `float GetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Default = 0.f) const`.
- **Address** = `Scope + ContextId + Key`, float-valued. `ContextId` by scope: Global → `NAME_None`, Region → RegionId, Local → InfluenceFieldId, Settlement → SettlementId.
- **CPU consumers** (PlacementForge, enemies, economy, quests, factions, settlements, encounters) pull from the subsystem; they **never** read the MPC.
- **Materials** read a curated `MPC_WorldState` mirror, pushed on change — render-facing values only (IndustrialPressure, CorruptionLevel, RestorationLevel, Wetness, Ashfall, FactionTint). Gameplay-scale state stays in the subsystem.
- **Rule**: Pull API = source of truth; MPC = render-only projection.

## D11 — State write contract: authoritative setter now; accumulation + persistence deferred
- **Now**: `void SetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Value)` — the authoritative primitive; a debug console command drives the tracer. In-memory store only.
- **Deferred (layer on top, all resolve *into* `SetStateValue`)**: `AddInfluence(...)`, influence-source tracking, falloff fields, aggregation rules, save/load persistence, region simulation, settlement emitters.
- **One required Tier-2 human edit**: `M_Terrain_Master` samples `MPC_WorldState.IndustrialPressure` to drive a soot/industrial overlay lerp (no MPC sample → no visible reaction; an agent can't do this and it can't be deferred).
- **Acceptance tracer**: `SetStateValue(Region, Desert_Valley_01, industrial_pressure, 0.75)` → subsystem updates `MPC_WorldState.IndustrialPressure` → terrain soot param visibly changes.

## D12 — MeshForge: mirror MaterialForge, Blender first, sequenced after PlacementForge
- **Pattern**: same contract shape — human-owned procedural graph (Blender GN / Houdini HDA) → agent recipe YAML → headless generation → mesh export → UE import → `StaticMesh` + provenance Data Asset → validation. "MaterialForge with meshes."
- **Tool**: Blender Geometry Nodes first (free, scriptable, headless, CI-friendly). Houdini = optional later backend, not a v1 dependency.
- **Why deferred**: mesh import is the heaviest problem (LODs, collision, Nanite, UVs, scale, pivots, material slots). PlacementForge needs *usable* meshes, not *generated* ones.
- **Spine-doc addition**: "External DCC forges follow the same recipe→manifest→import→DataAsset→validate contract as MaterialForge. Blender is the first MeshForge backend; Houdini is optional later."

## D13 — PlacementForge: state-aware PCG via pull
- Human-owned PCG graph = master template; agent-edited spawn-rule YAML (`FoliageSpawnRules.yaml`) = variation surface → generated `PlacementRulesDataAsset` the graph reads.
- The PCG graph reads rules from the Data Asset **and** pulls live state per-cell via `WorldStateSubsystem.GetStateValue` (density/species modulated by region values) — the **second state-aware consumer** after MaterialForge's MPC tracer.
- Same recipe→manifest→DataAsset→validate contract. **Do not** bake state into the Data Asset (kills runtime reactivity).

## D14 — ValidationForge is not a forge
It's the cross-cutting QA substrate every forge plugs into — Tier 0 (repo permissions), Tier 1 (text/contract), Tier 2 (master asset), Tier 3 (generated asset) — not a sequenced content lane.

## D15 — Repo structure: functional layout, "Forge" as vocabulary
Keep `tools/{substance,pipeline,unreal}` and `procedural/{manifests,reports,…}`. Add the contract-referenced `procedural/definitions/`. No forge-centric folder rename — "Forge" is a logical lane (per D2), not repo structure.

## D16 — Converge to build; grill later forges just-in-time
Stop up-front grilling of Terrain/POI/full-State. Build Milestone 1; grill remaining forges when their turn comes.

## D17 — PlacementForge v1: mirror MaterialForge, make the Data Asset runtime-read
Built the agent-operability + data spine of PlacementForge by copying the proven
contract: `definition → validate_placement → generate_placement_manifest →
create_placement_data_asset → validate_placement_assets`, with Tier-0/1 CI gates and
negative fixtures. FoliageSpawnRules live in `procedural/definitions/placement/`.
- **Key shape difference from MaterialForge**: `UPlacementRulesDataAsset` is NOT
  provenance-only. It carries a **runtime-read payload** (`Species[]`: mesh, density,
  scale, state-response endpoints) that the PCG graph consumes, *plus* the same
  provenance block. `UMaterialRecipeDataAsset` only links + records provenance.
- **State stays live (D13)**: only the density *response* (`density_at_state_zero/one`)
  is baked. The PCG graph pulls the live value via `WorldStateSubsystem.GetStateValue`
  per cell and lerps. Baking a resolved state value is forbidden by the contract.
- **No new C++ read node needed**: `GetStateValue` is already `BlueprintCallable`/
  `BlueprintPure`, so the PCG graph binds to it directly — the pull API is the seam (D10).
- **Agent-safe surface**: `state_key` is whitelisted to the curated keys + `none`;
  density/scale/species-count budgets are hard-enforced in Tier 1 and re-checked in Tier 3.
- **Shared provenance**: factored `tools/pipeline/provenance.py`; `generate_manifest.py`
  now uses it too (verified byte-identical output, modulo timestamp). Manifest paths
  normalized to POSIX `/` for cross-OS-stable hashing and git-friendliness.
- **One required human Tier-2 edit** (mirrors D11's `M_Terrain_Master` soot edit): author
  the PCG graph `/Game/Procedural/PCG/PCG_FoliageScatter` so it (a) reads `Species[]`
  from `DA_*`, and (b) per cell calls `GetStateValue(state_scope, region, state_key)` and
  modulates density. An agent can't author the `.uasset` graph; it can't be deferred — no
  graph → no scatter. The data spine + contract make that edit small and well-specified.
- **Deferred (tracked)**: the PCG graph `.uasset` itself; resolving a cell→RegionId
  context mapping; Tier-3 mesh-reference integrity is a warning (meshes live in the game
  project, not this tooling repo); multi-biome rulesets beyond the example.

---

## Roadmap (locked order)
1. **MaterialForge v1** — contract-complete (D1–D8). ✅ **Done**.
2. **Thin StateForge spine** — subsystem + read/write contract + one tracer reaction (D9–D11). ✅ **Done**.
3. **PlacementForge** — PCG placement driven by state, on placeholder/marketplace meshes (D13, D17).
   ✅ **Data spine + contract + Tier-0/1 gates done**. ⏳ Remaining: the human-owned PCG graph (Tier 2).
4. **MeshForge** — Blender GN, reusing the proven pattern (D12).
5. **TerrainForge / POIForge** — later.
- Cross-cutting throughout: validation/provenance/enforcement (D6, D7). Full StateForge (accumulation, persistence, emitters) layers on after the spine.

---

## Implementation Plan

**Milestone 1 — MaterialForge v1 (build first)** — refs D3–D8
1. `UMaterialRecipeDataAsset : UDataAsset` in `WorldForgeCore`.
2. Provenance in `generate_manifest.py`: `source_commit` + `dirty` + timestamp + generator name/version + schema + input hash; staleness guard; `--strict` for CI.
3. `create_data_asset.py` (new step); manifest gains `ue.data_asset_path`.
4. `validate_assets.py` → full Tier-3 (texture budgets, reference integrity, Data Asset linkage + provenance match, naming).
5. Preview deferred (keep `make preview` failing-by-design).

**Milestone 2 — Agent-operability gates** — refs D7
- `.github/CODEOWNERS`, `.github/workflows/worldforge_contracts.yml`, `tools/pipeline/check_agent_permissions.py`, `tests/fixtures/invalid_recipes/` + `tools/pipeline/test_negative_recipes.py`. Tier 0/1 enforced in GitHub CI (no UE).

**Milestone 3 — Thin StateForge spine** — refs D9–D11
- `WorldStateSubsystem` (`UWorldSubsystem`, `WorldForgeCore`): `GetStateValue` / `SetStateValue`, `MPC_WorldState` push bridge, Tier-2 edit to `M_Terrain_Master` (sample `IndustrialPressure`), `industrial_pressure → soot` tracer + debug command.

**Milestone 4 — PlacementForge** — refs D13
- Human-owned PCG graph; agent spawn-rule YAML → `PlacementRulesDataAsset`; PCG pulls live state per-cell.

---

### Cross-references to update when implemented
- `material_recipe_contract.md` — add the "MaterialRecipeDataAsset is a provenance/linkage `UDataAsset`, not a runtime registry" clause + upgrade trigger.
- `performance_budgets.md` — note the Tier-1/2/3 split and that per-recipe validation excludes shader-cost budgets.
- `agent_permission_model.md` — reconcile path lists with D7 Tier 0.
