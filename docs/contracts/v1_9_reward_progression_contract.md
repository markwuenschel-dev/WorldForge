# v1.9 LoadoutForge + RewardForge + ProgressionForge — Contract Spine

**Status:** Wave 1 shipped (contract spine + fail-closed shield). Waves 2/R/7
(authoring, runtime bridge, hostile suite) in progress.

**Milestone:** Turn mission and combat completion into persistent loadout,
reward, inventory, unlock, and progression outcomes. This is the durable
player-**consequence** substrate — **not** a loot game, itemization system,
economy, or UI.

**Baseline:** sits directly on v1.8 CombatForge (real in-engine combat proof),
v1.7 NPCForge behavior, and v1.6z grounded traversal.

**Pack:** `encounter_loop_world`.

**Failure-code band:** `WF631–WF670` (`REWARD_*`), defined in
`tools/pipeline/failure_codes.py`. Severity + gate-taxonomy are auto-backfilled;
`validate_failure_codes.py` proves the band is coherent (unique, well-formed,
severity + taxonomy present).

**Schema module:** `tools/pipeline/reward_contracts.py` — one section per
contract, each with `X_REQUIRED` / `X_ALLOWED` field sets, a
`validate_X(obj, strict)` returning `(name, ok, detail, code)` check tuples, and
a canonical `_example_X` factory. `CONTRACTS` pairs each validator with a valid
and a known-bad example; `CONTRACT_GROUPS` splits them into the three gate lanes.

---

## Honesty invariants (anti-fake-green)

The substrate is worthless if a reward can be claimed without durable
consequence. These are enforced at the schema layer and dogfooded by the
contract gates:

1. **Reward requires completion.** A `RewardGrantEvent` must reference a real
   `source_completion_report`; a `RewardCompletionReport` in the success class
   requires `mission_completed = true`. → `WF648 REWARD_WITHOUT_COMPLETION`.
2. **Completion+reward requires mutation.** A rewarding grant must change durable
   state — `pre_*_hash != post_*_hash` for inventory or progression; a success
   report requires `inventory_mutated` or `progression_mutated` true. A reward
   that appears only in a report is fake. → `WF647 COMPLETION_WITHOUT_REWARD`.
3. **No hidden grants.** A `no_reward` grant must **not** mutate state.
4. **grant_once is once.** A `grant_once` reward needs a stable id and cannot be
   granted twice. → `WF638 REWARD_DUPLICATE_GRANT`.
5. **Hashes match contents.** `inventory_hash` / `progression_hash` are recomputed
   from contents and must match. → `WF659` / `WF660`.
6. **Budgets bounded.** Reward tables have a valid `[budget_min, budget_max]`
   range; loadouts have finite power/risk budgets. → `WF664 REWARD_BUDGET_EXCEEDED`.
7. **Level follows the curve.** `level == level_for_xp(xp_total)` per the single
   shared `LEVEL_XP_CURVE`. → `WF662 LEVEL_CURVE_MISMATCH`.
8. **Dedicated save slots.** Reward/inventory/progression persist to
   `WFReward_State` / `WFInventory_State` / `WFProgression_State` and must **never**
   reuse `WFRuntime_Complete` / `WFNPC_State` / `WFCombat_State`.
9. **Risk/reward consistency.** The success class must classify as
   `baseline_reward` or `high_risk_high_reward` and be exploit-`clean`; over-/under-
   reward and duplicate grant_once classify as `over_rewarded` / `under_rewarded`
   / `exploit_suspected`. → `WF646`, `WF639`.

---

## Contracts

| Contract | Validator | Lane | Primary code |
|---|---|---|---|
| `LoadoutProfile` | `validate_loadout_profile` | loadout | WF632 |
| `EquipmentItem` | `validate_equipment_item` | loadout | WF655 |
| `RewardTable` (+ entries) | `validate_reward_table` | reward | WF636 |
| `RewardGrantEvent` | `validate_reward_grant_event` | reward | WF637/WF656 |
| `RewardCompletionReport` | `validate_reward_completion_report` | reward | WF657 |
| `InventoryState` (+ items) | `validate_inventory_state` | progression | WF633 |
| `ProgressionState` | `validate_progression_state` | progression | WF634 |
| `UnlockState` | `validate_unlock_state` | progression | WF635 |

Required fields per contract are the source of truth in `reward_contracts.py`
(`*_REQUIRED` tuples); this table is the index, not a duplicate schema. Refer to
the module for the authoritative field sets and per-field rules.

### Taxonomy (bounded, one source of truth)

- **Slots:** `primary`, `secondary`, `tool`, `consumable`
- **Item types:** `weapon`, `tool`, `consumable`, `gadget`, `armor`
- **Rarity bands:** `common`, `uncommon`, `rare`, `elite` (a value tier, not a casino)
- **Reward types:** `item`, `xp`, `unlock`, `currency`, `no_reward`
- **Risk bands:** `low`, `baseline`, `high`, `extreme`
- **Unlock types:** `loadout_slot`, `equipment`, `mission_archetype`, `biome`, `modifier`
- **Risk/reward classes:** `no_reward`, `baseline_reward`, `high_risk_high_reward`,
  `over_rewarded`, `under_rewarded`, `exploit_suspected`, `invalid`
  (blocking: `over_rewarded`, `exploit_suspected`, `invalid`)
- **Reward completion classes:** success = `reward_granted_runtime`; honest
  non-grant = `no_reward_runtime`; everything else names an owned failure surface.

---

## Command surface

`make` is not installed in this environment — targets document the canonical
surface; run the mapped `python tools/pipeline/*.py --pack <PACK> --strict`
directly. Env: run Python validators with `PYTHONUTF8=1` on Windows.

### Contracts (shipped, GREEN)
```
python tools/pipeline/validate_loadout_contracts.py     --pack encounter_loop_world --strict
python tools/pipeline/validate_reward_contracts.py      --pack encounter_loop_world --strict
python tools/pipeline/validate_progression_contracts.py --pack encounter_loop_world --strict
```

### Shield
```
python tools/pipeline/v1_9_shield.py --pack encounter_loop_world --strict            # contracts only -> GREEN
python tools/pipeline/v1_9_shield.py --pack encounter_loop_world --strict \
    --rewards --progression --torture --require-live                                 # full -> RED until built
```

### Authoring / runtime / hostile (Waves 2/R/7 — fail-closed until built)
`generate_reward_tables.py`, `validate_reward_tables.py`, `classify_risk_reward.py`,
`validate_risk_reward.py`, `generate_progression_state.py`,
`validate_progression_state.py`, `validate_unlock_state.py`,
`validate_inventory_save_load.py`, `validate_progression_save_load.py`,
`validate_next_mission_state.py`, `run_reward_forge_alpha.py`,
`validate_reward_bridge.py`, `reward_negatives.py`, `reward_fuzz.py`,
`reward_torture.py`, `reward_report_integrity.py`, `reward_hygiene.py`.

---

## Evidence output policy

Reward/progression state is **independently inspectable** and never mixed into
combat/npc/runtime reports:

```
procedural/generated/loadouts/**
procedural/generated/rewards/tables/**
procedural/generated/rewards/events/**
procedural/generated/progression/**
procedural/reports/rewards/completion/**     reward_completion_<scenario_id>.json
procedural/reports/rewards/telemetry/**       reward_telemetry_<scenario_id>.json
procedural/reports/rewards/save_load/**       inventory_save_load_<scenario_id>.json
procedural/reports/progression/**             progression_save_load_<scenario_id>.json
```

---

## Hard non-goals

No RPG itemization, crafting, economy simulation, loot rarity casino, vendors,
shop/inventory UI, equipment-comparison UI, full weapon/ability systems,
procedural affixes, live-service loops, multiplayer/account persistence, new
biomes, or new mission archetypes. v1.9 is the persistence-and-consequence
substrate only.
