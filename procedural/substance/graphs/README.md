# Master Substance Graphs

This folder contains the **human-authored** master `.sbs` files.

## Rules

- Only humans create or significantly modify files in this folder.
- Agents are **not allowed** to edit these graphs directly.
- Every master graph must expose a clean, documented set of parameters.
- The parameter list must be kept in sync with `docs/contracts/material_recipe_contract.md` and `ALLOWED_PARAMETERS` in `validate_recipe.py`.

## Current Master Graphs

- `terrain_rock_strata.sbs` — Base rock generation with cracks, strata, erosion, and sand overlay.  
  **Exposed parameters**: base_hue, saturation, value, crack_density, crack_depth, strata_angle, erosion_strength, sand_overlay, normal_intensity, height_strength

## How to Add a New Master Graph

1. Create the graph in Substance Designer.
2. Expose only the parameters you want agents to control.
3. Document the exact parameter names and ranges.
4. Update `validate_recipe.py` → `ALLOWED_PARAMETERS`.
5. Update `material_recipe_contract.md`.
6. Create an example recipe in `recipes/`.
7. Test the full pipeline.

## Recommended Best Practices

- Use consistent node naming and organization.
- Group related parameters with frames.
- Add comments inside the graph explaining what each exposed input does.
- Keep the graph focused (one material family per graph is ideal).
- Test parameter extremes to ensure the graph remains stable.

Once a master graph is stable, agents can safely generate dozens of variants through recipes alone.