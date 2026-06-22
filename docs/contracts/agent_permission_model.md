# Agent Permission Model v1.1

**Goal**: Make it impossible for agents to accidentally (or intentionally) damage the project while still giving them high agency inside safe boundaries.

## 1. Three Permission Tiers

### Tier 1: Fully Allowed (No human review required)
Agents may freely create, modify, and delete within these surfaces:

- All files under `procedural/substance/recipes/`
- All files under `procedural/definitions/` (Biome, TerraformStage, Enemy, Weapon, Projectile, Wave, FoliageSpawnRules, etc.)
- Build scripts and validation rules (with passing tests)
- Documentation that describes contracts (not architecture decisions)
- Preview renders and reports

### Tier 2: Review Required
These changes trigger human review before merge:

- Modifications to master Substance graphs or PCG graph structure
- Changes to core master materials or Material Layer setups
- New validation rules that could block the pipeline
- Significant changes to performance budgets
- New Data Asset classes or major schema changes

### Tier 3: Forbidden (Without explicit human exception)
Agents must never:

- Edit raw `.uasset` or `.umap` files directly
- Modify Substance graphs or PCG graph node structure
- Write runtime gameplay logic in Python
- Change core subsystem architecture or MassEntity fragment definitions without approval
- Make final visual or balance decisions (they can propose via data, not enforce)
- Bypass validation or provenance emission

## 2. Valid vs Invalid Agent Task Examples

**Valid**:
> Create 6 new material variants for the toxic soil graph using only the allowed parameters. Generate full pipeline output including Data Assets and previews. All must pass validation.

**Invalid**:
> Make the desert look more alive and mysterious. Improve the rock material.

**Valid**:
> Add a new "thriving" stage to the ReclaimedDesert biome definition. Increase foliage density and add young_tree weight. Update enemy spawn modifiers for lower aggression.

**Invalid**:
> Rewire the PCG foliage graph to look better in the new stage.

**Valid**:
> Implement the three-tier health model in the TerraformSubsystem and expose queries for materials, PCG, and audio. Update the relevant Data Asset generation.

**Invalid**:
> Just make the world heal when the player builds things.

## 3. Enforcement Mechanisms

- Repository branch protection + CODEOWNERS on sensitive folders
- Pre-commit / CI hooks that run validation on changed definition files
- `validate_recipe.py` and equivalent definition validators reject out-of-contract changes
- Build automation refuses to generate assets from invalid inputs
- Human review checklist for Tier 2 changes

## 4. Spirit of the Model

Agents are powerful when given clear contracts.  
They become dangerous when asked to make artistic or architectural decisions outside those contracts.

The permission model exists to protect both the project quality and the long-term ability of agents to contribute safely at scale.