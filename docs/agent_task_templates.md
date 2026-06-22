# Agent Task Templates

These templates are designed to keep AI/code agents inside safe, high-value boundaries.

Copy-paste or adapt them when giving tasks to Cursor, Windsurf, Claude, Aider, or custom agents.

## Core Principle

**Good tasks** tell the agent:
- Exactly which master graph to use
- Which files it is allowed to edit (only under `recipes/`)
- Required outputs and validation steps
- Success criteria (must pass validation + generate previews)

**Bad tasks** ask the agent to:
- "Make a cool rock material"
- Invent new parameters or new Substance graphs
- Manually edit Blueprints or `.uasset` files
- Make artistic judgment calls without data

## Template 1: Create New Material Variants (Recommended Starting Point)

```text
Task:
Create 8 new terrain rock material variants for a desert / wasteland biome.

Constraints & Requirements:
- Master graph: procedural/substance/graphs/terrain_rock_strata.sbs
- Only modify or create YAML files under procedural/substance/recipes/
- Resolution: 2048
- Must output: Base Color, Normal, Roughness, AO, Height
- Must create UE5 Material Instances from M_Terrain_Master
- All assets must pass naming conventions and validation
- Generate preview thumbnails for every variant
- Produce a short report listing each recipe, key parameter changes, and final asset paths

Allowed parameter ranges (do not exceed):
- base_hue, saturation, value: 0.0–1.0
- crack_density, crack_depth, erosion_strength, sand_overlay: 0.0–1.0
- strata_angle: -30 to +30

Deliverables:
1. 8 new .yaml recipe files (or updates to existing ones)
2. Validation report (all must pass)
3. Preview images
4. Summary of what changed between variants
```

## Template 2: Extend an Existing Recipe (Small Change)

```text
Task:
Create a "cracked mud" variant from the existing desert rock recipe.

Constraints:
- Start from procedural/substance/recipes/terrain_rock_desert_01.yaml
- Duplicate it to terrain_mud_cracked_01.yaml
- Only increase crack_density and erosion_strength significantly
- Lower value and saturation to create a darker, drier look
- Keep all other rules the same (2048, same outputs, same master material)
- Must pass full validation + preview generation
```

## Template 3: Add a New Master Graph (Human + Agent Handoff)

```text
Task (Human first):
Create a new master Substance graph: terrain_healed_grass.sbs
Expose these parameters: grass_density, moss_amount, wetness, normal_intensity, height_strength

Then hand off to agent:
"Using the new terrain_healed_grass.sbs master graph, create 4 recipe variants for early, mid, and late-stage world healing. Follow the exact material_recipe_contract.md. Generate full pipeline output including UE5 material instances."
```

## Template 4: Full Pipeline Validation & Cleanup

```text
Task:
Audit all existing material recipes under procedural/substance/recipes/

Requirements:
- Run validate_recipe.py on every file
- Fix any naming or schema violations
- Regenerate any missing or outdated texture exports
- Re-import into UE5 and re-create material instances where needed
- Update the preview gallery
- Produce a summary report of issues found and fixed
```

## Template 5: World Healing System (Future Slice)

```text
Task:
Extend the pipeline to support the data-driven world healing system.

1. Create a new YAML schema under procedural/definitions/ for biome stages (see example in architecture spec)
2. Create 3–4 stage definitions for "reclaimed_desert"
3. Update the master landscape material to use Material Layers + MPC driven by TerraformProgress
4. Wire PCG foliage density to the same progress value
5. Validate everything and generate documentation
```

## Success Criteria for All Tasks

A task is only complete when:
- All validation scripts pass with zero errors
- Preview thumbnails exist and are committed
- A clear diff/report is produced
- No raw `.uasset` files were manually edited
- Naming conventions are followed exactly
- The change is fully reproducible from the recipe files

---

Use these templates. They turn vague "make stuff" requests into precise, auditable, agent-safe work.