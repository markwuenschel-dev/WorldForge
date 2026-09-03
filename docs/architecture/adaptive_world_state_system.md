# Adaptive World State System v1.0

**Core Idea**: The world remembers what the player did and changes accordingly.

This replaces the previous "World Healing / Terraforming" framing. "Healing", "corruption cleansing", or "terraforming" are now treated as **possible themes** within a more general system, not the architecture itself.

## 1. Purpose

Create a persistent, multi-scale world simulation where player actions generate lasting consequences that affect:

- Visuals (materials, foliage, props, VFX)
- Gameplay (enemy spawns, patrols, quests, economy)
- Factions and NPC behavior
- Environment and audio

The goal is **reactive, consequential world simulation** — not linear progress toward "better."

## 2. Core Flow

```
Player Actions
    (building, mining, combat, quests, exploration, faction choices, resource extraction)

        ↓

Persistent World State Changes
    (multi-scale)

        ↓

Consequences across systems
    (Materials + PCG + Enemies + Economy + Factions + Quests + Audio + VFX)
```

## 3. State Layers (Multi-Scale)

The system tracks state at multiple granularities:

### GlobalWorldState
- Large-scale story and world arc
- Examples: overall faction power balance, major magical events, global trade health, world tension

### RegionState
- Per-biome, per-kingdom, or per-faction-territory state
- Examples: `ashwood_frontier`, `iron_vultures_territory`, `old_crown_protectorate`

### LocalInfluenceFields
- Spatial influence around player constructions, events, or persistent actors
- Examples: area around a mining base, shrine, watchtower, corrupted zone, battlefield

### Settlement / BaseState
- State specific to player-built or NPC settlements
- Tracks building composition, upgrades, reputation, specialization

## 4. Player Actions That Drive State

Examples of actions and resulting state changes:

| Player Action              | State Changes                                      | Example Consequences |
|---------------------------|----------------------------------------------------|----------------------|
| Builds iron forge         | +Industrial pressure, +Pollution, +Trade activity | Soot on ground, smoke VFX, more traders, higher resource demand |
| Builds watchtower         | -Local danger, +Trade safety                      | Fewer ambushes, more caravans, safer roads |
| Builds shrine             | -Local corruption, +Sanctuary influence           | Different NPCs appear, magical enemies react, plants recover |
| Mines heavily in one area | +Resource depletion, +Industrial pressure         | Fewer trees, more stumps, exposed rock, lower ore prices |
| Captures a region for a faction | +Faction control for that faction            | Banners change, patrols change, prices shift, different quests |
| Clears a corrupted zone   | -Corruption, +Restoration                         | Twisted trees → normal trees, different enemies, safer travel |

## 5. What Responds to World State

### Materials (Substance Designer Role)
Substance generates **visual material variants** from parameters.

World state decides *which variant* appears:
- High industrial pressure → dirtier, soot-covered, worn stone
- High corruption → veined, darkened, warped, glowing materials
- High faction control → painted markings, repaired roads, banners
- High resource depletion → stripped ground, exposed rock, dead vegetation

**Correct relationship**:
- Substance = offline visual variation factory
- Adaptive World State = decides when and where variants are used
- UE5 = applies them via Material Instances, Material Parameters, Runtime Virtual Textures, and PCG

### Foliage, Props & Environment (PCG)
State drives:
- Density and species selection
- Prop placement (barricades, market stalls, mine debris, shrines)
- Road formation and wear

### Enemies & AI
State influences:
- Spawn tables and density
- Patrol routes and aggression
- Faction patrols vs bandit activity
- Boss or elite spawn chances

### Economy & Quests
State affects:
- Resource prices and availability
- Quest availability and difficulty
- Trader/NPC traffic
- Black market activity in lawless areas

### Audio & VFX
State drives layered audio and particle systems (industrial noise, birdsong vs silence, corruption hum, etc.).

## 6. Buildings as Influence Emitters

Buildings are not just placed meshes. They are **state generators**.

Example definition (agent-editable):

```yaml
building: iron_forge
influence:
  industrial_pressure: 0.25
  pollution: 0.15
  trade_activity: 0.10

visual_reactions:
  ground_radius: 1200
  material_parameters:
    soot_amount: 0.6
    wear_level: 0.4

gameplay_reactions:
  attracts: [blacksmith, ore_trader]
  enemy_interest:
    raiders: 0.25
    rival_faction: 0.15
```

This pattern scales to watchtowers, shrines, farms, mines, etc.

## 7. Agent Role in This System

Agents should safely generate and maintain:

- Material recipes (visual states)
- Building influence definitions
- Region/Settlement state reaction rules
- Enemy spawn rules tied to state
- Economy and quest reaction rules

They must **not** invent core state layers or runtime simulation logic without human review.

## 8. Relationship to Material Factory

The Material Factory (Substance + UE automation) is the **visual expression layer** of the Adaptive World State System.

It must be hardened first because:
- Every adaptive world needs believable visual feedback for state changes.
- A trustworthy material pipeline makes later state-driven material swapping cheap and reliable.

## 9. Implemented Spine (v1)

The **thin StateForge spine** is now built (forge_design_decisions D9–D11). This is the
minimal tracer described below — **not** the full runtime system this document
envisions. Accumulation, influence falloff, aggregation, persistence, and building
emitters are still deferred and all resolve into `SetStateValue`.

**`UWorldStateSubsystem`** (`UWorldSubsystem`, in `WorldForgeCore`) is the source of truth:

- **Read (canonical pull-query):**
  `float GetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Default = 0.f) const`
  Every CPU consumer (PlacementForge, enemies, economy, quests…) binds to this. They
  **never** read the MPC.
- **Write (native authority):**
  `bool SetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Value)`
  writes an unreserved address. A native owner reserves an exact address with
  `ReserveStateAddress(...)`, then writes it only through a matching
  `FWorldForgeStateWriteLease` and `SetStateValueWithLease(...)`. `ReleaseStateAddress(...)`
  relinquishes that reservation, and lease destruction releases it automatically. The
  lease is opaque, move-only, and non-reflected;
  Blueprint and console routes cannot mutate a reserved address.
- **Address** = `Scope (Global/Region/Local/Settlement) + ContextId + Key`, float-valued.
  In-memory store only (no persistence in the spine).
- **Render mirror:** curated render-facing keys are pushed into `MPC_WorldState`
  (created by `tools/unreal/create_world_state_mpc.py`, at
  `/CoreTerrainMaterials/State/MPC_WorldState`). **Materials read only the MPC.**
  Curated keys: `industrial_pressure`, `corruption_level`, `restoration_level`,
  `wetness`, `ashfall` (→ `IndustrialPressure`, `CorruptionLevel`, `RestorationLevel`,
  `Wetness`, `Ashfall`).
- **No global state console command:** native callers must own an issued lease for
  reserved addresses; editor scripting may observe results but does not receive
  write authority.

**Acceptance tracer:** a native owner reserves an address, writes it through its
matching lease, and the subsystem mirrors a curated key into `MPC_WorldState` for the
render reaction.

### Required Tier-2 edit — scripted, human-run

The master material `M_Terrain_Master` (in `CoreTerrainMaterials`) must **sample**
`MPC_WorldState.IndustrialPressure` and lerp a soot/industrial overlay by it. Without
this edit there is no MPC sampler and no visible reaction.

This is scripted by `tools/unreal/wire_terrain_soot.py` (run in-editor via
`make wire-terrain-soot`): it splices a `CollectionParameter`
(`MPC_WorldState`/`IndustrialPressure`) → `Clamp` → `Lerp` into the master's base
color and roughness, toward a sooted look, and saves. It is idempotent (`--force`
rebuilds) and stamps its nodes with `WorldForge:SootReaction`.

It mutates the master `.uasset`, so it is still a **Tier-2** change: human-run /
reviewed, **not** an agent-safe Tier-0/1 step. Order: `make create-world-state-mpc`
(once) → `make wire-terrain-soot` (once).

## 10. Scope Reminder

This document defines the **target vision**. The thin spine in §9 is intentionally
minimal; the **full** Adaptive World State runtime (RegionState simulation,
LocalInfluenceFields, building emitters, persistence) still comes later, layered on
top of the spine. Do not expand the spine into the full system without human review —
harden each consumer (materials, then PlacementForge) first.
