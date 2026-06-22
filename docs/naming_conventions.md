# UE5 Asset Naming Conventions

Consistent naming is critical for large procedural projects. Agents must strictly follow these rules.

## Texture Naming

Format: `T_<Category>_<Subcategory>_<Variant>_<Type>`

Examples:
- `T_Terrain_Rock_Desert_01_BC`
- `T_Terrain_Rock_Desert_01_N`
- `T_Terrain_Rock_Desert_01_R`
- `T_Terrain_Rock_Desert_01_AO`
- `T_Terrain_Rock_Desert_01_H`
- `T_Building_Metal_Rust_03_BC`

**Type suffixes**:
- `BC`  = Base Color (sRGB)
- `N`   = Normal (linear, BC5 or Normalmap compression)
- `R`   = Roughness (linear)
- `M`   = Metallic (linear)
- `AO`  = Ambient Occlusion (linear)
- `H`   = Height / Displacement (linear)
- `MASK` = Packed masks (e.g. R=Curvature, G=AO, B=Thickness)

## Material Instance Naming

Format: `MI_<Category>_<Subcategory>_<Variant>`

Examples:
- `MI_Terrain_Rock_Desert_01`
- `MI_Terrain_Grass_Reclaimed_02`
- `MI_Building_Concrete_Worn_07`

## Master Material Naming

Format: `M_<Category>_Master`

Examples:
- `M_Terrain_Master`
- `M_Building_Master`
- `M_Prop_Master`
- `M_Foliage_Master`
- `M_WorldHeal_Landscape_Master`

## Folder Structure (UE5 Content)

Recommended layout:

```
/Game/
├── Materials/
│   ├── Masters/
│   │   ├── M_Terrain_Master.uasset
│   │   └── M_Building_Master.uasset
│   ├── Terrain/
│   │   ├── MI_Terrain_Rock_Desert_01.uasset
│   │   └── ...
│   └── Building/
├── Textures/
│   ├── Terrain/
│   │   ├── T_Terrain_Rock_Desert_01_BC.uasset
│   │   └── ...
│   └── Building/
└── Procedural/
    └── (optional Data Assets, PCG graphs, etc.)
```

## Validation

`validate_assets.py` and recipe validation will reject assets that do not follow these conventions.

## Why This Matters

- Enables reliable scripting and agent automation
- Makes content discoverable and diffable in git
- Prevents asset chaos as the project scales to hundreds of materials
- Supports bulk operations and dependency analysis

---

**Rule**: If an agent creates or renames an asset, it **must** follow this naming spec or the validation step will fail.