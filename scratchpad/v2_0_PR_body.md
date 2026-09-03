v2.0 VerticalSliceForge integrates the v1.5–v1.9 WorldForge substrates into the first generated playable slice.

The slice selects a bounded 24-scenario matrix across biomes, mission archetypes, encounter profiles, and seeds, then proves generated environments, grounded traversal, NPC behavior, combat pressure, reward/progression consequences, save/load, package/build evidence, and hostile report integrity in one coherent milestone.

## Slice matrix (24 scenarios, bound to real content)

`2 biomes × 3 mission archetypes × 2 encounter profiles × 2 seeds = 24`, all bound to real `encounter_loop_world` content (the runtime route catalog is the source of truth — no invented ids):

- **Biomes:** `alpine_snow` (visually readable) · `volcanic_ashlands` (traversal/encounter-stress)
- **Archetypes:** `survey_landmark` (reach) · `recover_resource` (recover) · `clear_hazard` (survive/clear)
- **Encounter profiles:** `baseline` · `high` pressure
- **Seeds:** the two materialized site variants per biome×archetype (12 real maps × 2 profiles = 24)

## Validation

```
v2.0 shield GREEN — 18/18
24/24 slice runtime scenarios completed (GENUINE slice_completed_runtime)
vertical slice contracts GREEN
slice scenario matrix GREEN (every binding resolves to a real file)
environment/materialization validation GREEN
traversal validation GREEN
NPC/combat validation GREEN (damage_events 9–13 per scenario, real)
reward/progression validation GREEN
save/load validation GREEN (roundtrip_ok on WFReward_State)
package proof GREEN (321 MB WorldForge.exe, 12 maps, RunUAT BuildCookRun)
negative validators GREEN (29 fixtures, each rejected for its owning code)
fuzz-300 GREEN (caught + drove 4 real schema bugs, now fixed)
torture GREEN
report-integrity GREEN
hygiene GREEN
v1.9 regression GREEN — 16/16
v1.8 regression GREEN — 18/18
v1.7 regression GREEN — 20/20
v1.6z regression GREEN — 16/16
```

Runtime evidence was produced headless (`-game`) reusing the already-compiled `Source/WorldForge/WFRuntime.cpp` actors — **no new engine code and no rebuild**. `WF_NPC_SCENARIO_ID` makes `UWFRuntimeAutoSpawnSubsystem` materialize the grounded pawn + NPCs + objective + encounter manager; `WF_COMBAT_ENABLED` + `WF_REWARD_ENABLED` drive combat + reward; `AWFEncounterManager::FinalizeReward` emits the reward markers. Every `SliceRuntimeReport` is validated against the strict schema before writing, so a fake-green report cannot be emitted.

## Failure code band

`WF671–WF710 SLICE_*` (integration honesty invariants), defined in `tools/pipeline/failure_codes.py`; `validate_failure_codes.py` proves the band coherent.

## Honest caveats

- v2.0 is a generated **playable slice, not a full game**. It prioritizes coherence and proof over scale.
- The matrix is intentionally **24 scenarios, not 120**.
- NPCs remain v1.7/v1.8 **sentry/waypoint pressure, not tactical AI**.
- Combat remains the **v1.8 substrate, not final combat feel**.
- Rewards remain the **v1.9 bounded deterministic consequence substrate, not final loot feel**.
- Traversal remains **grounded_manual_waypoint / grounded_worldforge_route** — **no native UE navmesh dependency** was added.
- The authored encounters are all `light_pressure`; the slice's `baseline`/`high` are **slice-level pressure profiles** over the shared base encounter (selecting the matching reward risk band), **not separately-authored encounters**.
- Desert content was **not** used (it has maps but no mission/encounter/reward/route spine); the slice binds to the `encounter_loop_world` lineage.
- No crafting, vendors, economy, quests, factions, streaming, or multiplayer.
- The bulky `Build/` package output (321 MB) is **not committed** (repo policy §12); the committed `SlicePackageReport` is the inspectable proof (path, size, maps, git_sha).
- Visual quality is **slice-proof level, not final art direction**.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
