# WorldForge v2.4 — AdvancedAIForge / TacticalBehaviorForge Contract

Status: **IN PROGRESS — Wave 1 done (contract spine + fail-closed shield GREEN)**
Branch: `worldforge/v2.4-tacticalbehaviorforge`
Failure-code band: **WF931–WF1010** (`TACTICAL_*`), WF975–1010 reserved.

v2.4 adds the first **bounded tactical-behavior substrate** for WorldForge NPCs. It is
**not** AAA combat AI, a GOAP planner, a behavior-tree editor, EQS, RL, or an LLM-driven
NPC (handoff §4). It proves generated NPCs make **bounded, inspectable** tactical
decisions over terrain, routes, cover, objectives, mission state, quest/faction context,
and streaming tile scope — over the v2.3 streaming regions + v2.2 quest/faction stack.

## Core design principle (handoff §5)

An NPC tactical decision is valid **only if** its inputs, options, constraints, selected
action, execution result, and state mutation are recorded and validate against contracts.
No black-box AI. No "looked smart in logs" claims. Every tactical claim needs evidence.

## Scenario scope (handoff §3)

```
2 generated regions (from v2.3 streaming)
  × 3 tactical roles (sentinel / skirmisher / suppressor)
  × 2 tactical pressure profiles (baseline_tactical / high_pressure_tactical)
  × 2 seeds
= 24 tactical scenarios
```

Bounded: 12-action vocabulary, 12-stimulus vocabulary, no new 120 matrix, no open-world
simulation. The matrix **as a whole** must prove each required action class at least once.

## Runtime truth policy (handoff §12)

Two acceptable, honestly-labeled runtime modes:

* `live_tactical_runtime` — real UE/headless runtime executes the tactical decision loop
  and emits decision traces. A clean report claiming this mode **must** carry non-empty
  `live_runtime_evidence`, or it is a `WF968_TACTICAL_NAVMESH_OVERCLAIM`.
* `deterministic_tactical_simulation` — contract-valid tactical decisions simulated
  deterministically over real WorldForge region/route/cover/mission/quest/faction
  evidence. **Not** live AI, not player-facing combat feel, not UE BT/EQS execution.

## Contracts (`tools/pipeline/tactical_contracts.py`) — 15, schema-only

| # | Contract | Code | Key honesty invariant |
|---|----------|------|-----------------------|
| 1 | TacticalBehaviorProfile | WF931 | known pressure profile; roles/actions/stimuli ∈ bounded sets; weights ∈ [0,1]; positive cadence/caps |
| 2 | TacticalRoleDefinition | WF932 | preferred ⊆ allowed; forbidden ∩ allowed = ∅; ordered engagement distances; known policies |
| 3 | TacticalAffordanceMap | WF933 | well-formed cover points (WF947); bounded hazard zones; source reports exist |
| 4 | TacticalNPCBinding | WF934 | role/profile known; spawn tile ∈ allowed; streaming scope ⊆ allowed tiles |
| 5 | TacticalDecisionInput | WF938 | valid health state; known visibility/streaming; **active stimuli ∈ bounded set** (WF937) |
| 6 | TacticalDecisionOption | WF939 | valid target-action ⇒ real target (flank⇒route WF951 / retreat⇒anchor WF952 / cover⇒cover WF947); invalid ⇒ reason |
| 7 | TacticalDecisionTrace | WF940 | selected option **exists** + is **valid** (WF941); clean ⇒ completed + state delta (WF944) |
| 8 | TacticalStateDelta | WF943 | any changed flag ⇒ post hash ≠ pre hash (WF944); quest/faction change ⇒ context (WF955/956) |
| 9 | TacticalGroupState | WF945 | coordinated ⇒ ≥2 NPCs (WF946); flank_active ⇒ flank route (WF951); suppression ⇒ suppressor |
| 10 | TacticalRuntimeReport | WF961 | clean ⇒ npc>0, decisions>0, valid>0, invalid=0, actions, mission done, roundtrip, budget ok; live ⇒ evidence |
| 11 | TacticalSaveState | WF957 | roundtrip_ok ⇒ ≥1 npc hash + ≥1 decision hash |
| 12 | TacticalBudgetReport | WF959 | npc/dpm overrun ⇒ budget_result=exceeded (WF960); over_budget class ≠ pass |
| 13 | TacticalEvidenceIndex | WF962 | pass ⇒ full matrix (WF965), no missing/stale, all required actions covered (WF964) |
| 14 | OperatorTacticalScenarioView | WF963 | clean+roundtrip ⇒ ≥1 decision trace link |
| 15 | OperatorTacticalNPCView | WF963 | acted ⇒ ≥1 decision trace + ≥1 state delta link (WF944) |

## Bounded vocabulary (handoff §6)

* **Roles**: sentinel, skirmisher, suppressor (+ reinforcer stretch)
* **Actions** (12): hold_position, advance_to_anchor, retreat_to_anchor, flank_via_route,
  use_cover, leave_cover, pressure_objective, protect_objective, pursue_player,
  break_pursuit, call_reinforcement, disengage
* **Stimuli** (12): player_seen, player_lost, damage_taken, ally_damaged,
  objective_threatened, quest_objective_active, faction_priority_changed,
  tile_transition_started, tile_unload_pending, health_low, cover_available, route_blocked
* **Coordination states**: none, loose, coordinated, broken, invalid
* **Required action coverage** (matrix-wide): hold_position, advance_to_anchor,
  retreat_to_anchor, flank_via_route, use_cover, pressure_objective

## Failure-code band (`tools/pipeline/failure_codes.py`)

`WF931–WF974` `TACTICAL_*` (44 codes), WF975–1010 reserved. Backfill auto-registers each
into `SEVERITY` + `GATE_TAXONOMY`. See handoff §9 for the full list.

## Output roots

```
procedural/generated/tactical/{profiles,roles,affordances,bindings,groups}/**
procedural/reports/tactical/{runtime,decisions,save_load,budgets,negatives,authoring}/**
procedural/reports/operator/tactical/**
```

## Acceptance (canonical surface; `make` not installed — run python directly)

```
PYTHONUTF8=1 python tools/pipeline/validate_tactical_contracts.py --strict   # contract spine
PYTHONUTF8=1 python tools/pipeline/tactical_negatives.py --strict            # 51 negative fixtures
PYTHONUTF8=1 python tools/pipeline/v2_4_shield.py --strict --tactical --advanced-ai
```
