# Performance Budget Validation v1.1

**Purpose**: Prevent the silent performance death that kills most procedural projects. Validation must catch both correctness **and** budget violations.

## 1. Texture Budgets

| Type              | Max Resolution | Recommended Compression | Notes |
|-------------------|----------------|-------------------------|-------|
| Base Color        | 2048           | Default / BC7           | sRGB = true |
| Normal            | 2048           | Normalmap / BC5         | sRGB = false |
| Roughness / AO / Height / Masks | 2048 | Masks / BC4 or BC5     | sRGB = false |
| Height (Displacement) | 1024–2048   | Displacementmap         | Careful with tessellation usage |

**Validation rules**:
- Reject textures above max resolution unless explicitly exempted
- Enforce correct sRGB and compression settings
- Warn on missing mipmaps or streaming settings

## 2. Material Budgets

- Target instruction count (approximate via editor stats or build logs)
- Shader permutation count limits
- Number of texture samplers
- Use of expensive features (tessellation, refraction, etc.) must be justified and budgeted per material family

**Validation**:
- Custom Data Validation rule that reads material stats where possible
- Hard fail on materials exceeding family budget
- Warning on high permutation counts

## 3. PCG Density & Complexity Budgets

- Max instances per cell / per frame for different foliage tiers
- Max PCG graph evaluation time (profiled)
- Spawn density caps per biome stage (enforced in FoliageSpawnRules)
- Hierarchical culling and LOD rules must be present for dense layers

## 4. MassEntity Budgets

- Max active entities per archetype (soft and hard caps)
- Fragment size and memory estimates
- Processor tick cost targets
- Avoid using Mass for VFX-only or purely cosmetic objects

## 5. General Asset & Cook Validation

- Naming and folder correctness (see naming_conventions.md)
- All referenced assets exist and are valid
- No broken material parents or missing textures
- Cook/package compatibility (no editor-only references in runtime assets)
- Data Asset / Data Table generation succeeded with provenance
- Preview render was generated successfully

## 6. Implementation

Validation runs in two places:
1. **Recipe/Definition validation** (`validate_*.py` scripts) — catches contract and basic budget issues early
2. **UE Data Validation** (plugin + custom validators) — runs on generated assets inside the editor, catches UE-specific problems (compression, references, performance stats)

Build pipeline must fail if any validation step fails.

## 7. Philosophy

The most dangerous failure mode is not a missing asset.  
It is an asset that exists, passes visual inspection, but quietly tanks framerate, increases shader compile time, or makes future iteration painful.

Performance budget validation exists to catch that class of problem at the point of creation.