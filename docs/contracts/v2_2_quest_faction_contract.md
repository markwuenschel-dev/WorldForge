# WorldForge v2.2 — QuestForge + FactionStateForge Contract

Status: **COMPLETE — all waves done; v2.2 shield GREEN 22/22**
Branch: `worldforge/v2.2-quest-faction`
Failure-code band: **WF771–WF850** (`QUEST_FACTION_*`), WF805–850 reserved.

v2.2 adds the first **stateful narrative-consequence substrate** for WorldForge. It
is **not** a story campaign, dialogue system, or lore generator. It proves that a
generated mission can belong to a quest, a quest has steps and outcomes, a faction
cares about the result, faction state mutates, those consequences persist, and the
next mission can see the changed state — all inspectable in OperatorForge.

## Core design principle (handoff §5)

* A **quest** is a validated **state machine** over existing v2.0 scenario actions.
* A **faction** is a persistent bounded **state vector** that receives bounded
  deltas from quest outcomes.

Everything else is presentation. Quest text is keyed placeholder metadata, not
final writing. Factions are bounded state vectors, not a diplomacy simulator.

## Scenario scope

Bounded to the existing v2.0 vertical-slice matrix (no new 120 matrix):

```
2 biomes (alpine_snow, volcanic_ashlands)
  × 3 quest archetypes (Survey→survey_landmark, Recovery→recover_resource,
                        HazardClearance→clear_hazard)
  × 2 faction pressure profiles (baseline, high)
  × 2 seeds (s1, s2)
= 24 quest/faction scenarios
```

`StabilizeRoute` is a known-to-schema optional stretch archetype (reuses the
`clear_hazard` mission binding); the core generator uses the three core archetypes.

## Contracts (`tools/pipeline/quest_faction_contracts.py`)

Every contract is schema-only: it validates the *structure and internal coherence*
of a single record via the shared `runtime_schema` (RS) helpers. Cross-record
resolution (scenario binding resolves to a real v2.0 scenario, relationship targets
a real faction, ledger path exists on disk) is the job of the Wave-2 authoring
validators and Wave-3 runtime/index validators, which have the datasets in hand.

| # | Contract | Code | Key honesty invariant |
|---|----------|------|-----------------------|
| 1 | QuestDefinition | WF771 | >=1 non-optional step; known archetype; explicit failure conditions; bounded next-mission hooks |
| 2 | QuestStep | WF772 | contiguous `step_order`; machine-checkable completion/failure predicate over a known runtime-claim category |
| 3 | QuestRuntimeState | WF777 | `completed` requires all required steps; outcome-bearing state requires `faction_deltas_applied`; `reward_granted` needs a real binding |
| 4 | FactionDefinition | WF781 | known class/risk; valid bounds pairs; preferred/opposed disjoint; normalized tags |
| 5 | FactionState | WF782 | every value within bounds; a quest can't be active AND completed |
| 6 | FactionDelta | WF786 | each facet within its per-facet cap; `bounded=true` |
| 7 | ConsequenceLedger | WF789 | `applied_deltas` non-empty ⇒ `post_faction_state_hash != pre`; carries `save_load_result` |
| 8 | QuestFactionRuntimeReport | WF794 | a clean report (empty `failure_codes`) requires real evidence: runtime started, ledger path, `roundtrip_ok`, next state, and (outcome-bearing) mutated faction |
| 9 | QuestFactionEvidenceIndex | WF795 | `integrity_result=pass` requires the full 24/24 matrix + empty missing/stale evidence + real sha |
| 10 | OperatorQuestView | WF797 | a clean `roundtrip_ok` view must link real consequence-ledger evidence |
| 11 | OperatorFactionView | WF797 | a faction with mutation history must link >=1 state path |

**Failure can be a valid quest outcome.** `quest_outcome=failure` is a valid,
"clean" runtime report (the run happened and was recorded). The report's success is
about *evidence completeness*, not the quest winning. `abandoned`/`invalid` are not
outcome-bearing (no faction mutation, not a clean report).

### Bounded taxonomy (one source of truth)

* Quest states: `not_started, active, completed, failed, blocked, invalid`
* Quest outcomes: `success, partial_success, failure, abandoned, invalid`
  (outcome-bearing: `success, partial_success, failure`)
* Objective types: `survey_landmark, recover_resource, clear_hazard,
  reach_objective, survive_pressure, extract_reward`
* Faction classes: `protector, explorer, extractor, stabilizer, opportunist`
* State bounds: standing `[-100,100]`, influence/trust/alarm/territory_pressure
  `[0,100]`, relationships `[-100,100]`, resources `[0,1000]`
* Delta caps: standing/influence/trust/alarm/relationship `±25`, resources `±100`

## Shield (`tools/pipeline/v2_2_shield.py`)

Fail-closed. Spine-only (`--strict`) is GREEN from Wave 1; the full surface
(`--quests --factions`) is honestly RED until Waves 2/3/4/R build their scripts.

```
PYTHONUTF8=1 python tools/pipeline/v2_2_shield.py --strict                     # spine → GREEN
PYTHONUTF8=1 python tools/pipeline/v2_2_shield.py --strict --quests --factions # full  → RED until built
```

Lanes: contract spine + negatives (always) · quest/faction authoring (`--quests` /
`--factions`) · runtime + operator + hostile (both flags) · regressions
(`--regressions` → v2.1/v2.0 authoring shields).

## Output roots

```
procedural/generated/quests/**              procedural/reports/quest_faction/**
procedural/generated/factions/**            procedural/reports/quest_faction/runtime/**
procedural/generated/consequences/**        procedural/reports/quest_faction/save_load/**
procedural/reports/operator/quests/**       procedural/reports/operator/factions/**
```

v2.0/v2.1/v1.9 evidence is referenced, never rewritten in place.
