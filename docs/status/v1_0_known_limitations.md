# WorldForge v1.0 — Known Limitations (honest)

v1.0 proves the factory can generate **a small playable adaptive world pack from
data** (`desert_mvp_world`, 25 maps). It is deliberately not a general game
generator. These are the real edges.

## `make` may not be on every environment's PATH
The canonical command surface is the Makefile, but `make` is not installed in every
shell. Every target is a one-line wrapper over `tools/pipeline/<script>.py`; run the
Python form directly with `PYTHONUTF8=1` when needed (Windows cp1252 will otherwise
crash on emoji/unicode validator output).

## Material variants share terrain material instances
The 8 material variants (ash, clean, cracked, heavy_industrial, industrialized,
light_industrial, ruined_industrial, sandy) are backed by 4 terrain MIs
(`MI_Terrain_Rock_Desert_01`, `_Ash_01`, `_Cracked_01`, `MI_Terrain_Sand_Desert_01`).
Variants differ by state intensity and preview tint; they are not 8 bespoke authored
materials. Expanding to distinct MIs per variant is out of MVP scope (no external art
import in v1.0).

## Headless base-color render override bug (TICKET-001)
The headless SceneCapture path does not apply MI texture-parameter overrides; earlier
milestones worked around it with a vector `PreviewBaseColor` proof terrain. This does
not affect map generation, playability validation, or the v1.0 gates, and remains
deferred to TICKET-001.

## Inspection playability signals are coarse
Per-map inspection records distil three boolean signals (PlayerStart, nav bounds, POI
present) from the cached validate_slice report. The authoritative playability verdict
is the map's `validation_status` (the full 34-check strict result); the three signals
are a convenience summary, not the gate.

## Runtime scenario POI evidence is data-simulated
`run-world-state-scenario` runs the authoring-side v0.8 simulation (bounded state
mutation, aggregation, MPC expectation, POI evidence, real save/load round-trip). The
in-editor MPC bridge read-back and post-scenario map re-validation are editor steps
the tooling drives directly. No quest/economy/faction/NPC state exists — scenarios
only move curated world-state keys.

## Map count is at the MVP floor
The pack ships 25 maps (the v1.0 minimum). Expansion toward 50 is intentionally
deferred until the 25-map strict + lifecycle path is proven stable; the matrix is
designed so additional contrast rows can be added without new subsystems.

## Explicitly out of scope for v1.0
Open-world streaming, final art, new biome families, MeshForge, full Substance
replacement, external asset-library import, QuestForge / NPCForge / FactionForge /
EconomyForge / SettlementForge / DungeonForge / WeatherForge, web dashboards, editor
plugins, recipe visual editors, general-purpose game generation.
