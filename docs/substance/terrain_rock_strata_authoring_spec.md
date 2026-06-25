# Authoring spec — `terrain_rock_strata.sbs` master graph

**Status:** the master graph is currently a 0-byte stub; the texture lane runs on flat
placeholder PNGs (`make placeholder-exports`). This doc is the contract your real
Substance Designer graph must honor so the existing pipeline consumes it with **zero code
changes**. Authoring the graph is human-owned work (see `procedural/substance/graphs/README.md`);
agents will not edit `.sbs` files.

Scope decision (2026-06-25): real procedural textures are deferred to the human (you).
The runtime "soot/industrial" look is **already handled by state** (`M_Terrain_Master` +
MPC `IndustrialPressure`), so the master graph is about the **dry base terrain look**, not
industrial states — do **not** add a soot parameter here.

---

## 1. What the pipeline already expects

The recipe → manifest → export contract is fixed by `terrain_rock_desert_01.yaml`,
`validate_recipe.py` (`ALLOWED_PARAMETERS`, `PARAMETER_RANGES`), and
`docs/contracts/material_recipe_contract.md`. Match these exactly.

### Exposed parameters (graph input identifiers must match these names)
| Parameter | Range | Meaning |
|---|---|---|
| `base_hue` | 0.0–1.0 | base rock hue |
| `saturation` | 0.0–1.0 | base saturation |
| `value` | 0.0–1.0 | base brightness |
| `crack_density` | 0.0–1.0 | crack coverage |
| `crack_depth` | 0.0–1.0 | crack depth in height/normal |
| `strata_angle` | (degrees) | strata tilt |
| `erosion_strength` | 0.0–1.0 | erosion amount |
| `sand_overlay` | 0.0–1.0 | sand-fill in crevices |
| `normal_intensity` | 0.0–1.0 | normal map strength |
| `height_strength` | 0.0–1.0 | height output strength |

If you expose a **new** parameter you must, in the same change: update
`ALLOWED_PARAMETERS` + `PARAMETER_RANGES` in `tools/substance/validate_recipe.py`, the
contract doc, and the graph README. Recipes can only use names in `ALLOWED_PARAMETERS`.

### Output channels (exactly five, this order of usage)
`base_color`, `normal`, `roughness`, `ambient_occlusion`, `height`
— matching the recipe `outputs:` block and the manifest `exports`.

**Output naming gotcha:** `render_with_sbsrender.py` calls
`sbsrender render --output-name "{inputName}"`, and the manifest expects files at
`procedural/substance/exports/<recipe_id>/<output_value>.png` (e.g.
`T_Terrain_Rock_Desert_01_BC.png`). So either:
- name the graph's **output nodes** so the rendered filenames equal the recipe `outputs`
  values (`T_Terrain_Rock_Desert_01_BC`, `_N`, `_R`, `_AO`, `_H`), **or**
- adjust `--output-name` / add a rename step so exports land at those exact paths.
Confirm one of these before wiring CI — a mismatch here is the most likely first failure.

### Resolution
Recipes carry `resolution` (desert uses 2048). The graph must render at the requested size.

---

## 2. Cook + render flow (what to install / run)

1. **Install Substance Automation Toolkit** so `sbsrender` (and `sbscooker`) are on PATH.
   `validate_recipe.py` is pure-python and already passes; only rendering needs these.
2. `sbsrender` renders **`.sbsar`**, not `.sbs` — cook first:
   `sbscooker terrain_rock_strata.sbs --output-path procedural/substance/graphs/`
   (add this as a `make cook-substance` step, or cook inside `render_with_sbsrender.py`).
3. Swap placeholder → real: today recipes are exported via `make placeholder-exports`.
   Once the graph exists, use `make render-substance RECIPE=terrain_rock_desert_01`
   (already wired to `render_with_sbsrender.py`). `make build RECIPE=...` chains
   validate → render-substance → manifest.

---

## 3. How to verify it plugged in (no code changes needed)

1. `make validate-recipe RECIPE=terrain_rock_desert_01` — unchanged, must pass.
2. `make render-substance RECIPE=terrain_rock_desert_01` — produces the 5 real PNGs at the
   expected export paths (the naming gotcha above is the thing to watch).
3. `make generate-manifest RECIPE=terrain_rock_desert_01` — hashes the real inputs.
4. UE material lane (headless, same launcher pattern as `biome-slice`):
   `import-textures` → `create-material` → `create-data-asset` → `validate-assets`.
5. `make biome-slice BIOME=desert VARIANT=industrialized` — must still PASS; the ground now
   shows real rock instead of flat tan, still reacting to soot via state.

---

## 4. Then variants become cheap (agent work, ask anytime)

Once the master graph renders real, distinct textures from its parameters, the preset
library is pure-YAML recipe clones again (the original plan):
- `terrain_rock_desert_cracked_01` (high `crack_density`/`crack_depth`)
- `terrain_sand_desert_01` (high `sand_overlay`, low `crack_density`)
- `terrain_rock_desert_ash_01` (desaturated, low `value`)

Each clones `terrain_rock_desert_01.yaml`, changes only `parameters` + the `id`/output/MI
names, runs the lane above, and a new `procedural/slices/*.yaml` points `render.terrain_mi`
at the variant MI — the slice orchestration already consumes that field.

### Pre-Substance stopgap — IMPLEMENTED 2026-06-25
`make_placeholder_exports.py` now derives **five coherent maps from a single shared
procedural height base** (value-noise fbm + rotated strata + ridged crack network), driven
by the recipe `parameters`. A crack that appears in `base_color` also appears in
`height`/`normal`/`AO`/`roughness`; changing params (or the recipe `id`) yields a
deterministic, visibly distinct material. This makes recipe clones **visually distinct now**,
before the real `.sbs` exists — exactly the hybrid path (UE master material = runtime truth,
Python = coherent masks/maps/state variants).

- Default mode is procedural; `make placeholder-exports RECIPE=...` is unchanged and now
  emits real-looking textures at the recipe `resolution` (computed at `--work-size` 512,
  nearest-upscaled). `--solid` restores the original flat-colour-per-channel placeholders.
- **Zero contract change**: same five outputs/paths/PNG format; `validate_recipe.py`,
  the manifest, and the UE import lane are untouched. Pure stdlib for PNG encoding; PyYAML
  (already a dep) only to read recipe params via the manifest's `source_recipe`.
- This is a stopgap, not a Substance replacement — when the real `.sbs` lands, switch the
  lane to `make render-substance` and these placeholders fall away with no other changes.

---

## 5. Boundaries

- Agents do not create/modify `.sbs` files (human-owned, per graph README).
- One material family per graph; keep this graph focused on desert rock/strata.
- The industrial/soot axis lives in the runtime state system, **not** in baked textures.
