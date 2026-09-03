## Summary

v1.9 adds the player-facing consequence substrate on top of v1.8 CombatForge.

Mission and combat completion now produce contract-valid reward grants, inventory/progression mutation, unlock state, independent save/load proof, next-mission state handoff, and risk/reward classification. The milestone adds strict reward/loadout/progression contracts, deterministic reward tables, a `WF_REWARD_ENABLED`-gated C++ runtime reward bridge (three dedicated save slots — `WFReward_State` / `WFInventory_State` / `WFProgression_State` — never reusing the mission/NPC/combat slots), runtime reward evidence, hostile validators, fuzz/torture, and report-integrity gates.

This is the persistence-and-consequence substrate — **not** a loot game.

## Validation

- v1.9 shield **GREEN 22/22** (`--rewards --progression --torture --require-live`)
- **120/120 genuine `reward_granted_runtime`**, 0 failed (real headless `-game`, `created_at=live`, real git sha)
- reward / loadout / progression / telemetry contracts dogfooded (valid passes, known-bad rejected)
- 12 deterministic reward tables generated and validated (item/unlock cross-refs resolve)
- inventory save/load **GREEN** via `WFInventory_State`
- progression save/load **GREEN** via `WFProgression_State`
- next-mission handoff **GREEN** (12-scenario progression chain: level 6 / 1680 xp / 6 unlocks)
- risk/reward classifier **GREEN** (baseline→baseline_reward, high→high_risk_high_reward, none blocking)
- 33 negatives rejected (each for its owning failure code)
- fuzz-300 **GREEN** (0 invalid accepted, deterministic)
- torture **GREEN** (dup grant_once, over-reward, save-drift, capacity, no-completion — all caught)
- report-integrity **GREEN** (zero-record success rejected, telemetry-file existence enforced)
- hygiene **GREEN** (132 backed scenarios, 0 orphans / leaks / junk)
- v1.8 regression **GREEN 18/18**
- v1.7 regression **GREEN 20/20**
- v1.6z regression **GREEN 16/16**
- exactly one authorized 120-scenario runtime matrix, after compile + smoke

## Honest caveats

- v1.9 proves the persistence and consequence substrate, **not** full RPG itemization.
- Inventory/progression are contract + runtime state, not final UI or loot feel.
- Rewards are bounded deterministic grants, not final loot balance.
- No crafting, vendors, economy simulation, or rarity casino.
- Combat remains the v1.8 substrate.
- NPC behavior remains v1.7/v1.8 pressure, not tactical AI.
- Traversal remains `grounded_manual_waypoint`.
- Seed parity currently binds each mission archetype to a single risk band (→ 6 distinct reward tables: 60 baseline / 60 high).
- Save/load evidence is unified onto one `roundtrip_ok` proof schema across authoring and runtime (the engine's in-process reload-verify IS the roundtrip).

Caveats are disclosed, not hidden.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
