# Biome & Terraform Stage Definition Contract v1.1

**Purpose**: Define biomes, their healing stages, and the resulting state for all systems. YAML is authoring source. Generates `BiomeDefinitionDataAsset` (or Data Table) for runtime.

## 1. Core Schema

```yaml
schema_version: "1.1"
id: string                          # reclaimed_desert
display_name: string

global_influence_weight: float      # How much GlobalWorldHealth affects this biome

stages:
  - threshold: float                # 0.0 – 1.0 (on BiomeHealth or blended value)
    name: string                    # "toxic", "dormant", "reclaiming", "thriving"
    
    landscape:
      material_instance: string     # MI_Terrain_Toxic_Soil or similar
      rvt_settings: ...             # Runtime Virtual Texture config if used
    
    foliage:
      density_multiplier: float
      species_weights:              # Normalized weights
        dead_scrub: 0.8
        reclaimed_grass: 0.15
        young_tree: 0.05
      pcg_rule_overrides:           # Optional per-stage tweaks to PCG parameters
    
    water:
      color_tint: [r, g, b]
      clarity: float
      caustics_intensity: float
    
    enemies:
      spawn_table: string           # Reference to spawn table or rules
      aggression_modifier: float
      perception_range_multiplier: float
    
    vfx:
      ambient_particles: string     # dust, pollen, healing_mist, etc.
    
    audio:
      ambience_layer: string
      intensity: float
    
    post_process:
      color_grading_profile: string
      fog_density: float
    
    unlocks:
      - sanctuary_pylon_tier_1
      - advanced_farm
```

## 2. Three-Tier Consumption

- `GlobalWorldHealth` provides base bias
- `BiomeHealth[id]` is the primary driver for stage selection
- `LocalTerraformField` can push individual locations past stage thresholds for local effects (e.g. a healthy oasis inside a still-toxic biome)

## 3. Generation Target

Build automation produces:
- `BiomeDefinitionDataAsset` (Primary Data Asset recommended)
- Any referenced Data Tables (spawn tables, foliage rules, etc.)
- Validation that all referenced assets exist

Runtime systems (BiomeSubsystem, TerraformSubsystem, PCG, Material system) read these Data Assets.

## 4. Validation Requirements

- All stage thresholds are strictly increasing
- All referenced assets (materials, Data Tables, VFX, audio) exist
- Species weights sum to ~1.0
- Performance budgets respected (PCG density caps per stage, enemy count implications)
- Naming follows conventions

## 5. Agent Permissions

Agents may:
- Add new stages to existing biomes (within schema)
- Adjust weights, multipliers, and references
- Create new biome definitions from template

Agents must not:
- Change the core three-tier model
- Invent new consumption points without architecture update

This contract enables rich, data-driven world progression while keeping the authoring surface safe for agents.