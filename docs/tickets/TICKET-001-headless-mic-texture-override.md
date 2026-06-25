# TICKET-001 — Headless SceneCapture ignores MIC texture-parameter overrides

**Status:** OPEN / DEFERRED (worked around, not fixed)
**Opened:** 2026-06-25
**Severity:** medium — quality, not blocking. A render-proof workaround is live (see below).
**Area:** `tools/unreal/build_and_render_desert_valley.py`, `M_Terrain_Master`, headless render path.

## Symptom
In the headless `UnrealEditor-cmd -ExecutePythonScript` SceneCapture2D path, terrain
material **texture**-parameter overrides on a `MaterialInstanceConstant` do **not** render.
The captured ground samples the parameter *default* (`WhiteSquareTexture` → near-white),
identically for every variant, so desert presets that differ only by base-color **texture**
looked the same flat grey/white.

## Proven facts (do not re-investigate)
- The MIs store distinct `BaseColorTexture` overrides (verified via
  `get_material_instance_texture_parameter_value`).
- `M_Terrain_Master` is correctly wired `lerp(BaseColorTexture, soot, MPC.IndustrialPressure)`.
- Sampling the same textures directly through a trivial unlit material renders them
  distinctly (sand=tan, ash=dark) — textures + capture + export all work.
- **VECTOR** parameter overrides on an MIC *do* render correctly headless (the foliage
  proxies and the new render-proof terrain both rely on this).
- Did NOT help: `update_material_instance` + `post_edit_change`, `-NoTextureStreaming`,
  recreating the MIs after the wired master, extra warm-up captures.

So the bug is specific to **texture**-parameter overrides resolving to their default in the
commandlet SceneCapture path; scalar/vector params and global MPC params are fine.

## Workaround in place (WorldForge Useful v0.2)
The biome-slice render no longer depends on the MI texture path for its proof look. Each
slice spec carries `render.preview_base_color: [r,g,b]` (linear). The render script builds
`M_WF_TerrainProof` = `lerp(PreviewBaseColor_vector, soot, MPC.IndustrialPressure)` and sets
`PreviewBaseColor` as a **vector** override — which renders. Result: variants are visibly
distinct and still darken with `industrial_pressure`. The production MI pipeline is untouched.

This means the proof screenshots show a flat per-variant **base color**, not the actual
texture detail (cracks, grain). That fidelity gap is the remaining cost of this ticket.

## Candidate real fixes (when picked up — pick ONE, don't brute-force boots)
1. Flush shader/asset compilation before capture (`FAssetCompilingManager` wait +
   force texture mip residency) and re-test the MI texture path.
2. Render via PIE / `-game` instead of an editor-commandlet SceneCapture.
3. Keep the vector-color proof for the contact sheet; sample real textures only in an
   interactive editor capture for hero shots.

## Acceptance to close
The MI-driven terrain (no `preview_base_color`) renders its actual `BaseColorTexture`
distinctly per variant in the headless path, with state-driven soot still working.

Related memory: `master-basecolor-grey-bug`.
