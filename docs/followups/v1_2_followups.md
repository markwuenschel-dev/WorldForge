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

## WF-FOLLOWUP-UE-VISUAL-MATERIALIZE (v1.3.5)
Live in-editor spawning of the resolved environment rigs. v1.3.5 resolves every
map's environment profile into a complete, validated UE-actor/component SPEC
(SkyAtmosphere / DirectionalLight / SkyLight / ExponentialHeightFog /
VolumetricCloud / PostProcessVolume / weather VFX) and the driver
`tools/unreal/materialize_environment_rig.py` spawns them — but there is no
running NeoStackAI-enabled editor on this runner (unreal_status: no runtime.json),
so live spawn is deferred. When an editor is available, run the driver per map;
`validate_environment_rig` then sees `live_spawned:true`. Same convention as the
deferred UE StaticMesh materialization and Houdini live cook.
