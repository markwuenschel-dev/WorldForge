# Placement Rules Contract v1.1 (FoliageSpawnRules)

**Purpose**: Define the safe interface between a human-authored **PCG graph** and
agent-editable **FoliageSpawnRules** definitions. YAML is the **authoring source**.
It generates a UE-native `UPlacementRulesDataAsset` the PCG graph reads at runtime.

PlacementForge is the second state-aware consumer after the material MPC tracer
(forge_design_decisions D13). It mirrors the MaterialForge contract shape exactly:
`definition → validate → manifest → DataAsset → validate`.

## 1. Schema (Strict)

```yaml
schema_version: "1.1"
id: string                          # e.g. reclaimed_desert_foliage
biome: string                       # e.g. reclaimed_desert (free-form linkage)
pcg_graph: string                   # /Game/... path to the human-owned PCG template (Tier 2)

species:                            # 1..12 entries
  - id: string                      # species id (unique within the ruleset)
    mesh: string                    # /Game/... StaticMesh path (soft ref)
    base_density: float             # target instances per 100 m^2, (0, 50]
    scale_min: float                # (0, 100], <= scale_max
    scale_max: float                # (0, 100]
    state_scope: enum               # Global | Region | Local | Settlement  (default Region)
    state_key: enum                 # allowed world-state key, or "none" (default none)
    density_at_state_zero: float    # density multiplier at state=0.0, [0, 5]  (default 1.0)
    density_at_state_one: float     # density multiplier at state=1.0, [0, 5]  (default 1.0)

ue:
  data_asset_path: string           # Optional; defaults to /Game/Procedural/Placement/DA_<Id>
  data_asset_class: string          # must be "PlacementRulesDataAsset"
  generate_data_asset: bool         # usually true
```

### Allowed `state_key` values

Mirrors the curated world-state keys (`UWorldStateSubsystem::GetCuratedMpcParams`)
plus `none`. Adding a key is a human contract change (Tier 2):

`industrial_pressure`, `corruption_level`, `restoration_level`, `wetness`, `ashfall`, `none`.

## 2. The state-aware rule (D13)

The PCG graph does two things per cell:
1. Reads `species[]` (mesh, base density, scale) from the generated `UPlacementRulesDataAsset`.
2. Pulls the **live** world-state value at `(state_scope, <cell's context id>, state_key)`
   via `UWorldStateSubsystem::GetStateValue` and modulates density:

```
effective_density = base_density * lerp(density_at_state_zero, density_at_state_one, state_value)
```

**The response (the two endpoints) is baked; the state value is read live.**
Never bake a resolved state value into the Data Asset — that kills runtime reactivity.

## 3. Generation Target

From a valid definition the build automation **must** produce:

1. One `UPlacementRulesDataAsset` under the correct folder, containing:
   - Identity (`RulesId`, `SchemaVersion`, `Biome`)
   - The `Species[]` runtime rules + the `PcgGraphTemplate` reference
   - Provenance (source path + commit + manifest + input hash) copied verbatim

Runtime systems (the PCG graph) read the Data Asset, never the YAML.

## 4. Validation Rules

Tier 1 (`validate_placement.py`, no UE):
- All required fields present and correctly typed; no unknown keys (strict)
- `pcg_graph`, `mesh`, `data_asset_path` are `/Game/` paths
- `state_scope` is a valid enum; `state_key` is on the allowed list
- Species ids unique; `scale_min <= scale_max`
- Performance budgets respected (see performance_budgets.md §3)

Tier 3 (`validate_placement_assets.py`, requires UE):
- Data Asset exists, correct class, `DA_`-prefixed, `rules_id` matches
- Species count matches the manifest; budgets re-checked defensively
- Provenance copied verbatim; recorded hash matches (staleness guard)
- Mesh reference integrity (a **warning** here, since WorldForge is the tooling
  layer — the actual meshes live in the consuming game project)

## 5. Provenance

Stamped once at manifest generation (`generate_placement_manifest.py`) via the
shared `provenance.py` helper, then copied **verbatim** into the Data Asset by
`create_placement_data_asset.py`. Identical honesty rules to MaterialForge: a dirty
input tree is flagged not hidden; `--strict` hard-fails on dirty; Tier 3 rejects
stale provenance.

`UPlacementRulesDataAsset` is a plain `UDataAsset` (in `WorldForgeCore`). Unlike
`UMaterialRecipeDataAsset` (provenance/linkage only) it also carries a **runtime-read
payload** (`Species[]`). Same upgrade trigger (D3): promote to `UPrimaryDataAsset`
only when a runtime system must discover/enumerate/async-load rulesets by id/tag.

## 6. Agent Rules

Agents **may**:
- Create new definition files from templates
- Adjust species, densities, scales, and state responses within ranges
- Run the authoring-side pipeline (validate + manifest)

Agents **must not**:
- Add a `state_key` not on the whitelist
- Edit the PCG graph (`.uasset`) node structure (Tier 2/3 — human-owned)
- Bake a resolved state value into the definition
- Change `data_asset_class` or invent new top-level keys without a contract update

---

This contract makes foliage placement variation safe, reproducible, and fully
traceable while keeping the PCG graph human-owned and runtime reactivity intact.
