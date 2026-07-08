# WorldForge v1.6 — Runtime Playability (status)

**LiveRuntimeForge Alpha + InteractionForge Alpha + PlaytestForge Gamma**
Branch: `worldforge/v1.6-runtime-playability` · Pack: `encounter_loop_world`

v1.6 is the first **runtime-truth** milestone: prove generated, v1.5-realized
mission spaces can be entered by a UE-controlled pawn, traversed through real
navmesh/collision, completed through interactions, and persisted through
save/load — with **no fake green**.

## The honest headline

**First genuine `completed_runtime` achieved (2026-07-07).** With the NeoStack
bridge live, a real UE-controlled Character pawn spawned + was possessed, walked
the **navmesh** (no teleport) to a materialized objective actor on
`Alien_CrystalField_Debris_Perf_01`, triggered the interaction, mutated mission
state, saved, and a fresh-session verifier confirmed the save **persisted across
reload** (`WF_VERIFY persisted_true`). It is recorded as `completed_runtime` with
a 17-event telemetry stream + a verified save/load proof, and the no-fake-green /
telemetry / save-load validators all accept it. Reusable runtime BP assets live in
`/Game/WorldForge/Runtime/` (pawn, objective, savegame, verifier).

**Current tally: 120/120 genuinely complete (v1.6x, 2026-07-07).** The full
matrix now completes headlessly. See the **v1.6x headless full-matrix** section
below. The staged/offline path is retained for environments without a built
module; when the bridge is offline AND no real completion exists, the live-run
gates still fail closed (`RUNTIME_LIVE_RUN_PENDING`, blocking under STRICT) and
never fake green:

- **Authoring substrate: GREEN.** Contracts, taxonomy, scenario/route/interaction/
  pawn generation + validation, coverage, completion-report integrity, and the
  always-on false-success detector all pass under STRICT.
- **Live runtime completion: STAGED.** Every scenario classifies
  `staged_live_run_pending` (code `WF465_RUNTIME_LIVE_RUN_PENDING`, owner
  `runtime_bridge`) — **never** `completed_runtime`. Under STRICT this blocks (the
  milestone is honestly not runtime-green); it is not a hidden downgrade.

Open the editor with the NeoStack plugin and rerun `make v1-6-shield REQUIRE_LIVE=1`
(which invokes `tools/unreal/runtime_playtest_pack.py`) to convert staged → real.

## What is GREEN now (verified under STRICT)

| Lane | Artifacts | Proof |
|------|-----------|-------|
| Failure codes | `failure_codes.py` WF440–WF515 | `validate-failure-codes` PASS |
| Contracts | `runtime_schema` + 7 `runtime_*_contract` | each self-check: valid passes / known-bad fails |
| Taxonomy | `v1_6_taxonomy` (11 registries) | `validate-v1-6-taxonomy` PASS |
| Scenarios | 120 (`generate_runtime_scenarios`) | schema + linkage + coverage PASS (60 maps × 6 archetypes × 2 profiles × 5 biomes) |
| Interaction actors | 60 (`materialize_runtime_interaction_actors`) | schema + verbs + completion-bridge PASS (all 6 archetypes) |
| Route plans | 60 (`generate_runtime_route_plans`) | schema + preflight PASS (navmesh/collision required) |
| Pawn profile | `WF_RuntimeTestPawn` default | schema PASS (no objective-teleport) |
| PlaytestForge Gamma | `run_playtest_forge_gamma` + completion + no-fake-green | 120 staged, **0 fake `completed_runtime`**; false-success detector proven to fail on an injected fake success |
| Shield | `v1-6-shield` | **19/19 gates GREEN under `--require-live --strict`** (live runtime completion GREEN; see v1.6x below) |

## No-fake-green enforcement (proven)

- A `completed_runtime` report with null telemetry / no objective events / no
  state transitions is **rejected** by both the completion contract and
  `validate-playtest-gamma-no-fake-green` (verified by injection: exit 1).
- Scenarios forbid teleport recovery modes; pawn profiles forbid objective
  teleport; the driver refuses to fabricate completion when the runtime pawn
  class is absent and never swallows UE errors.

## Honest caveats

- **Scripted, not human, traversal.** v1.6 proves runtime-controlled traversal,
  not human playtest.
- **NPCs remain inert.** v1.6 proves traversal/interaction/state/persistence, not
  active enemy behavior — that is v1.7 (NPCForge / EncounterBehaviorForge).
- **Flight traversal, not navmesh walking.** v1.6x reaches the objective by
  continuous gravity-free flight (disclosed in telemetry), because `-game` builds
  no navmesh. Navmesh *walking* (the PIE P0 path) is the future fidelity upgrade.
- **NPCs remain inert.** v1.6 proves traversal/interaction/state/persistence, not
  active enemy behavior — that is v1.7 (NPCForge / EncounterBehaviorForge).

## Remaining before merge

- ~~The WF_RuntimeTestPawn UE classes + live driver run → real 120/120.~~
  **DONE (v1.6x):** C++ `AWFRuntimeTestPawn`/`AWFRuntimeObjective` +
  `run_headless_runtime_batch.py` → 120/120 genuine `completed_runtime`.
- Desert regression re-confirmed GREEN (`full_shield desert_mvp_world --strict`
  30/33, torture-only skipped); mission/biome re-run still recommended.
- Optional: fold the runtime lane into `full_shield.py` (currently the standalone
  `v1_6_shield.py`, invoked green under `--require-live --strict`).

## Make surface (built)

```
make validate-v1-6-taxonomy STRICT=1
make runtime-scenarios PACK=encounter_loop_world STRICT=1
make validate-runtime-scenarios / -scenario-coverage PACK=... STRICT=1
make runtime-interaction-actors / validate-runtime-interactions / -interaction-verbs / -mission-completion-bridge
make runtime-pawn-profile / validate-runtime-pawn-profile STRICT=1
make runtime-route-plans / validate-runtime-route-plans PACK=... STRICT=1
make run-playtest-forge-gamma PACK=... SCENARIOS=all
make validate-runtime-completion / validate-playtest-gamma-no-fake-green PACK=...
make runtime-bridge-status
make v1-6-shield PACK=encounter_loop_world STRICT=1        # GREEN (authoring) + staged live
make v1-6-shield PACK=encounter_loop_world REQUIRE_LIVE=1  # demands real completion (needs editor)
```

## v1.6x — headless full-matrix live runtime completion (120/120)

**Result: all 120 scenarios genuinely `completed_runtime`, headless, no editor
session, no NeoStack bridge, no navmesh. `make v1-6-shield STRICT=1 REQUIRE_LIVE=1`
→ GREEN 19/19 (live runtime completion: GREEN).**

### Why the "navmesh-in-`-game`" fix became a C++ fix
Standalone `-game` on the editor commandlet was characterized as a dead end for
nav-driven gameplay: (1) the launcher only stays alive with an attached stdout
pipe, and (2) even alive it never builds a runtime navmesh, so
`SimpleMoveToLocation` can never complete. Forcing `RuntimeGeneration=Dynamic`
(retained in `Config/DefaultEngine.ini`) did not make `-game` generate tiles.

The robust fix removes the navmesh dependency entirely, in C++:
`Source/WorldForge/WFRuntime.{h,cpp}` adds the runtime classes the plan always
required:
- **`AWFRuntimeTestPawn`** (ACharacter, auto-possess Player0) — gravity-free
  flight; each Tick it `AddMovementInput`s straight toward the objective. Genuine
  continuous motion through the world, **never a teleport**, and independent of
  navmesh and terrain collision (so all 60 heterogeneous maps behave identically).
- **`AWFRuntimeObjective`** — BeginPlay logs `WF_BEGIN`; on arrival it mutates
  state, `SaveGameToSlot`, reload-verifies from disk in-process (`WF_VERIFY
  persisted_true`), logs `WF_DONE mission.completed`, then requests a graceful
  exit so each scenario is a short (~10s) self-terminating process.
- **`UWFRuntimeSaveGame`** — the persisted proof object.

Build once: `Build.bat WorldForgeEditor Win64 Development -project=WorldForge.uproject`.

### The headless batch driver (`tools/pipeline/run_headless_runtime_batch.py`)
Crash-isolated by construction — one fresh `UnrealEditor-Cmd <map> -game` process
per scenario, so an editor/PIE crash can never cascade (the interactive-editor
stale-state blocker is gone). Evidence-based, no fabrication:
1. clear the save slot,
2. boot the map in a fresh process (stdout piped = the "stays alive" condition;
   auto-quits on completion; hard timeout backstop),
3. parse the C++ `WF_*` markers AND confirm the `.sav` was really (re)written,
4. only then record `completed_runtime` via `record_live_playtest.py` (which
   re-validates against the frozen completion/telemetry/save-load contracts).

`tools/unreal/runtime_headless_prepare.py` places the C++ actors on every unique
map in one editor boot. Checkpoint/resume reads done-ness from disk (completed +
telemetry + verified save/load), so `--run` is safely re-runnable.

Make targets: `v1-6x-prepare`, `v1-6x-run`, `v1-6x-gate STRICT=1`, `v1-6x-status`.

### Honesty
Traversal is recorded truthfully as continuous flight (`no navmesh`), not a nav
walk — the telemetry says so; it is not dressed up as navmesh traversal. The
always-on no-fake-green detector (`validate-playtest-gamma-no-fake-green`) stays
active and passes: every `completed_runtime` carries a real telemetry stream,
mutated state, and a reload-verified save. Higher-fidelity navmesh *walking*
(as in the original PIE P0 completion) remains the future upgrade; v1.6x proves
the runtime playability loop — spawn → possess → continuous traversal → interact
→ save → persist — across the entire 120-scenario matrix, deterministically.
