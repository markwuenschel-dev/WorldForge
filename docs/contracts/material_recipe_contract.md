# Material Recipe Contract v1.1

**Purpose**: Define the safe interface between human-authored Substance graphs and agent-editable recipes. YAML is the **authoring source**. It generates UE-native Data Assets and Material Instances for runtime.

## 1. Schema (Strict)

```yaml
schema_version: "1.1"
id: string                          # e.g. terrain_rock_desert_01
graph: string                       # e.g. terrain_rock_strata.sbs (must exist)
resolution: int                     # 1024 | 2048 | 4096 (power of two)

parameters:                         # Whitelisted per graph
  base_hue: float
  saturation: float
  value: float
  crack_density: float
  crack_depth: float
  strata_angle: float
  erosion_strength: float
  sand_overlay: float
  # ... only parameters exposed in the master graph

outputs:
  base_color: string                # Texture asset name (without extension)
  normal: string
  roughness: string
  ambient_occlusion: string
  height: string

ue:
  parent_material: string           # /Game/Materials/Masters/M_Terrain_Master
  instance_path: string             # Full path including name, e.g. /Game/Materials/Terrain/MI_Terrain_Rock_Desert_01
  texture_folder: string            # e.g. Textures/Terrain
  texture_group: string
  compression:
    base_color: string
    normal: string
    masks: string
  generate_data_asset: bool         # Usually true
  data_asset_class: string          # e.g. MaterialRecipeDataAsset
```

## 2. Generation Target

From a valid recipe the build automation **must** produce:

1. 5 texture assets with correct settings and naming
2. One Material Instance under the correct folder
3. One `MaterialRecipeDataAsset` (or Data Table row) containing:
   - Source recipe path + commit
   - Parameter values used
   - Generated texture references
   - Provenance metadata

Runtime systems read the Data Asset, never the YAML.

## 3. Validation Rules (Enforced by validate_recipe.py + UE Data Validation)

- All required fields present and correctly typed
- `graph` file exists in master graphs folder
- All `parameters` keys are on the allowed list for that graph
- Texture names follow naming conventions
- UE paths are valid
- Resolution is supported power of two
- No unknown keys (strict mode)
- Performance budget checks (see performance_budgets.md):
  - Texture resolution within limits
  - Generated material instruction count estimate (if possible)
  - Proper compression and sRGB settings

## 4. Parameter Whitelisting

Each master graph maintains its own allowed parameter list in `validate_recipe.py`. Agents may only modify values inside documented ranges. Adding new parameters requires a human to update the master graph and contract.

## 5. Provenance

Every generated Material Instance and Data Asset must embed or reference:
- Source YAML path
- Git commit hash at generation time
- Exact parameter values
- Build timestamp

This enables "which recipe produced this asset?" debugging.

## 6. Agent Rules

Agents **may**:
- Create new recipe files from templates
- Modify parameter values within ranges
- Run the full build pipeline

Agents **must not**:
- Add parameters not in the whitelist
- Change output texture names or UE paths without contract update
- Edit the master `.sbs` graph

---

This contract makes material variation safe, reproducible, and fully traceable while keeping runtime assets as normal UE Data Assets.