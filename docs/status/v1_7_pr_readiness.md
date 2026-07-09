# WorldForge v1.7 — NPCForge runtime behavior: PR readiness

**Status: GREEN — v1.7 shield 24/24, reproducible from a clean checkout.**
Branch `worldforge/v1.7-npcforge-behavior`. Date 2026-07-09.

v1.7 turns the validated NPC behavior matrix into genuine engine-executed behavior:
120/120 `behavior_completed_runtime`, headless, 0 failures — NPC sentries spawn as real
grounded `AWFNPCPawn`s, perceive the moving grounded player, apply per-tick pressure,
persist NPC state to an independent save slot, and reload-verify it. Mission completion
rides the v1.6y/v1.6z grounded runtime spine.

## What the PR-readiness pass found and fixed

The committed Wave R evidence validated on paper, but a 3-scenario live smoke exposed a
real defect: **the 120/120 evidence was not reproducible from a clean checkout.** The
runtime depended on an `AWFEncounterManager` *baked into 60 maps by an editor prepare
step that was never committed* — there was no runtime spawner, so a clean map produced
no `WF_NPC_MGR` at all and the scenario hung. `validate-npc-actors` reporting 0/60 was a
**true** red, not a gate defect.

**Fix — runtime-spawn is now the canonical materialization mode:**

- **`UWFRuntimeAutoSpawnSubsystem`** (C++, `Source/WorldForge/WFRuntime.{h,cpp}`): on
  world begin-play in standalone `-game`, when the batch sets `WF_NPC_SCENARIO_ID` and no
  manager already exists, it spawns the same actor set the editor prepare step baked
  (grounded pawn + objective + encounter manager) and possesses the pawn. Inert in
  editor / PIE / normal play; idempotent on baked maps (so `--bake` / editor-preview
  still works untouched).
- **Gate correction** (`materialize_npc_actors.py`, `validate_npc_actors.py`,
  `npc_contracts.py`): `runtime_spawn` is the default mode. The manifest is emitted from
  committed completion evidence; the validator **independently re-derives** the realized
  set from that evidence and requires the manifest to match it exactly — fail-closed, no
  fake-green. `--bake` retained as the optional editor-preview (`baked_editor`) path.
- **Evidence regenerated on clean maps**: 120/120 `behavior_completed_runtime`, 0 failed,
  all 5 biomes × 24 — with every baked `.umap` reverted. A clean checkout now reproduces
  the full matrix with **zero committed `.umap` edits**.

Proof on the exact map that failed twice (Alien_CrystalField, clean): after the fix,
`WF_AUTOSPAWN spawned pawn=1 obj=1 mgr=1` → `WF_NPC_MGR scenario.started` → genuine,
12.3s.

## Shield status (STRICT)

```
v1-7-shield encounter_loop_world --npc --behavior --torture --require-live → GREEN 24/24
v1-6z-shield encounter_loop_world --require-live                          → GREEN 16/16 (no regression)
```

v1.7 gates: contracts, archetypes, spawn-groups, behavior-profiles, scenarios (+validate),
**materialize (runtime_spawn 60/60)**, **validate-actors**, spawn-placement, route-binding,
behavior matrix-P2 (120/120), runtime-core, perception, movement, telemetry, completion,
save-load, classify-pressure, balance, negatives (30), fuzz-300, torture, report-integrity.

## Evidence integrity

- Completion 120/120 success · telemetry 120 · save/load 120/120 verified — all strict PASS.
- Hostile: 30 negative fixtures each rejected · 506 reports integrity-checked · fuzz-300 clean.
- Determinism note: 20/120 standard_pressure scenarios record **−1 pressure tick** vs the
  prior baked-map evidence (systematic one-frame spawn-latency difference of runtime-spawn
  vs baked placement). All 120 remain genuine (pressure > 0, mission completed) and classify
  `balanced`; 0 `npc_count` changes.

## Hygiene

- Reverted: timestamp-only mission-loop churn (63 files), 66 baked `.umap` leftovers from
  the prior prepare session, stale re-run reports, and `WorldForge.uproject`'s 4 unused AI
  plugins (LearningAgents/MassAI/MassCrowd/MLAdapter — not used by v1.7).
- The PR changeset = C++ auto-spawn + 3 gate scripts + regenerated reproducible evidence.
- Untracked environment clutter (Plugins/, Houdini temp, `_wf_test` maps, terrain assets)
  is left out of the PR.

## Honest boundaries

- Traversal is `grounded_manual_waypoint` / `grounded_worldforge_route`; **no native
  headless navmesh**.
- NPC movement is waypoint/sentry behavior, **not tactical navmesh AI** — no cover/hazard
  avoidance, no combat damage loop. Pressure is behavior/state pressure, not final combat.
- Materialization is `runtime_spawn` (canonical). Baked editor placement is optional
  (`--bake`, editor-preview / v1.7x) and not required by the matrix.
- **Correction:** an earlier note recorded "materialize 60/60" — that was false (0/60
  baked; the runtime depended on uncommitted baked maps). It is now genuinely reproducible
  via runtime-spawn.

## Merge recommendation

**Merge-ready.** v1.7 shield green and — the material change from before — reproducible
from a clean checkout. Suggested next milestone: v1.8 CombatForge (turn behavior pressure
into combat pressure).
```
