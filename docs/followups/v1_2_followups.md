# WorldForge v1.2 — tracked follow-ups (NOT v1.3 blockers)

These are verification upgrades deferred from v1.2 by environment limits, not
product gaps. They do not block v1.3. Do not let them become a swamp.

## WF-FOLLOWUP-HOUDINI-LIVE-COOK
Run the live Houdini/hython cook → bake → import path when the environment has
Houdini Engine or `hython` available. v1.2 shipped `HOUDINI=metadata_only`
because no Houdini Engine / `hython` is on the current runner (only a
license-server component). The intake contract + cook/bake/import report
validation are already in place; this follow-up swaps declared metadata for a
real cook.

## WF-FOLLOWUP-FULL-SEED-BUILD
Run the full `make full-shield PACK=biome_expansion_world MESHES=1
HOUDINI=metadata_only MEGASCANS=1 SEEDS=200` (and with `--build`, no `--no-build`)
when build time is acceptable. v1.2 verified with `--no-build` + `SEEDS=5`; the
200-seed + build weight is orthogonal to the mesh/source work and already proven
green in v1.1.

## WF-FOLLOWUP-UE-VISUAL-MATERIALIZE (v1.3.5) — RESOLVED 2026-07-04
Live in-editor spawning of the resolved environment rigs. v1.3.5 resolves every
map's environment profile into a complete, validated UE-actor/component SPEC
(SkyAtmosphere / DirectionalLight / SkyLight / ExponentialHeightFog /
VolumetricCloud / PostProcessVolume / weather VFX) and the driver
`tools/unreal/materialize_environment_rig.py` spawns them.

**Resolution (2026-07-04):** executed live against a running NeoStack-enabled
editor via `execute_script` (Lua LevelDesign API), equivalent to the Python
driver: all 60 maps under `/Game/WorldForge/Maps/` had their generic v1.1 env
actors (Sun/SkyAtmosphere/SkyLight/ExponentialHeightFog) replaced with the
spec-bound rig — WF_SkyAtmosphere, WF_Sun (pitch=-sun_angle_deg, intensity_lux,
atmosphere sun light, shadows), WF_SkyLight (intensity_scale, realtime capture),
WF_HeightFog (density/falloff/start/max-opacity/volumetric/inscattering color),
WF_VolumetricCloud, WF_PostProcess (unbound, AutoExposureBias=exposure_ev) —
and each map saved. Weather Niagara stays deferred (no concrete system asset in
project). Live-spawn reports written to
`procedural/reports/visual/ue_materialize/<slice_id>.json` (`live_spawned:true`,
driver-contract schema `wf.visual.ue_materialize.v1`). Note: AEM_Manual exposure
was deliberately NOT applied — manual metering vs physical-lux suns blows out the
image; per-profile EV is realized as exposure bias over default auto-exposure,
matching the Python driver's realization.
