# v1.8 Wave R Prime — Runtime Combat Evidence Contract (LOCKED)

Single source of truth for the C++ ↔ batch-runner ↔ validator interface. Every
Wave-R-Prime lane builds against THIS. Combat rides the v1.7 NPC behavior runtime
(`AWFEncounterManager` + `AWFGroundedRuntimePawn` + `AWFNPCPawn` in
`Source/WorldForge/WFRuntime.{h,cpp}`), adding real damage on top. No flight, no
teleport, no navmesh dependency (unchanged from v1.6z/v1.7).

## 1. Activation
Combat is INERT unless `WF_COMBAT_ENABLED=1` is set. When absent, the process is a
pure v1.7 behavior run (health never mutates) — this is what keeps the v1.7 + v1.6z
regressions green. The v1.7 batch runner never sets it; only
`run_combat_forge_alpha.py` does.

## 2. Environment variables (set per scenario by run_combat_forge_alpha.py)
Reused from v1.7 (drive spawn): `WF_NPC_SCENARIO_ID` (= the underlying
behavior_scenario_id), `WF_NPC_PROFILE`, `WF_NPC_COUNT`, `WF_NPC_ENGAGE_RADIUS`.
New combat vars:
- `WF_COMBAT_ENABLED` = "1"
- `WF_COMBAT_MAX_HEALTH` = player max health, e.g. "100"
- `WF_COMBAT_SOURCE` = "npc_pressure" | "hazard" | "both"
- `WF_COMBAT_DAMAGE_PER_TICK` = NPC per-pressure-tick damage, e.g. "4.0"
- `WF_COMBAT_HAZARD_DAMAGE` = hazard per-tick damage (0 if no hazard), e.g. "5.0"

## 3. C++ log markers (emitted by WFRuntime.cpp; parsed from stdout)
One line each unless noted. `%.1f`/`%.2f` floats, `%d` ints.
- `WF_COMBAT_START scenario=<sid> max_health=<f> source=<src>`
- `WF_COMBAT_HEALTH_INIT player=<id> max=<f>`
- `WF_COMBAT_DAMAGE source=<npc_pressure|hazard> src_id=<id> type=<proximity_tick|ranged_tick|contact|hazard_zone|dot> amount=<f> before=<f> after=<f> at=<f>`  ← ONE per damage event; the ordered set of these lines IS `damage_events`.
- `WF_COMBAT_HEALTH_CHANGED player=<id> health=<f> min=<f>`
- `WF_COMBAT_SAVE saved=<0|1> slot=WFCombat_State events=<d> taken=<f>`
- `WF_COMBAT_VERIFY persisted_<true|false> health=<f> events=<d>`
- `WF_COMBAT_DONE scenario.completed scenario=<sid> events=<d> min_health=<f> final_health=<f> mission=<0|1>`
- `WF_COMBAT_FAIL <why> scenario=<sid>`  (on any broken combat chain)

Combat completion (`WF_COMBAT_DONE`) fires only when: mission objective genuinely
complete AND >=1 real `WF_COMBAT_DAMAGE` event AND player still alive (final_health>0)
AND combat save/load verified. `WFCombat_State` is a DISTINCT save slot — independent
of mission (`WFRuntime_Complete`) and NPC (`WFNPC_State`) slots.

## 4. Evidence files (written by run_combat_forge_alpha.py, one per scenario)
- Completion: `procedural/reports/combat/completion/cs_<combat_scenario_id>.json` — a `CombatCompletionReport` (combat_contracts.COMBAT_COMPLETION_REQUIRED). Success class `combat_completed_runtime` requires damage_events_seen>0, player_min_health<player_max_health, player_final_health>0, mission_completed=true, save_load_result=pass, survivability_band=survivable. MUST carry a top-level `damage_events` list (each a DamageEvent per combat_contracts.DAMAGE_EVENT_REQUIRED) alongside the report fields. Carries `meta` via report_meta.build_meta.
- Telemetry: `procedural/reports/combat/telemetry/cs_<id>.json` — `events` list of COMBAT_EVENT_TYPES incl every COMPLETION_REQUIRED_COMBAT_EVENTS.
- Save/load proof: `procedural/reports/combat/save_load/<combat_scenario_id>.json` — the persisted `PlayerCombatState` (combat_contracts.validate_player_combat_state must pass on it), proving combat save/load independent of mission save/load.

## 5. Matrix scope
120 combat scenarios = the 120 v1.7 behavior scenarios with combat enabled. Marker
`cs_<id>` derives from the behavior `bs_<id>`. Hazard source only for hazard_field /
hazard-tagged scenarios; others npc_pressure. ONE full 120 matrix authorized after
compile + smoke pass — never rerun for metadata/report-only changes.

## 6. Hard gate before the 120 matrix
Do NOT launch the 120 matrix until: (a) C++ compiles clean; (b) a 1-scenario smoke
shows `WF_COMBAT_HEALTH_INIT` + >=1 `WF_COMBAT_DAMAGE` with after<before + a valid
`cs_*.json` carrying a non-empty top-level `damage_events`.
