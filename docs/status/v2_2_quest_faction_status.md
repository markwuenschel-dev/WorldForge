# WorldForge v2.2 QuestForge + FactionStateForge — Status

Branch: `worldforge/v2.2-quest-faction` (off `main` @ `1c5406c`)
Failure-code band: **WF771–WF850** `QUEST_FACTION_*`

## Baseline (verified before build)

* v2.1 shield GREEN 20/20 (`--strict --operator`)
* v2.0 shield GREEN 4/4 (`--strict --package`)

## Wave status

| Wave | Scope | State |
|------|-------|-------|
| 1 | Contracts + fail-closed shield | ✅ **DONE** — spine GREEN, downstream honestly RED |
| 2 | Authoring generators (quests + factions) | ⏳ pending |
| 3 | Runtime quest/faction proof (24 scenarios) | ⏳ pending |
| 4 | OperatorForge integration | ⏳ pending |
| R | Hostile closure + v2.2 shield green | ⏳ pending |

## Wave 1 — delivered

* **Failure band WF771–WF804** registered in `failure_codes.py` (auto-backfilled
  into SEVERITY + GATE_TAXONOMY; `validate_failure_codes.py` GREEN).
* **`quest_faction_contracts.py`** — 11 strict contracts (schema-only), one source
  of truth for taxonomy/bounds/caps, valid + known-bad example factories,
  `CONTRACTS` / `CONTRACT_GROUPS` / `KNOWN_BAD_OWNING_CODE` registries.
* **Contract dogfood gates** (GREEN, runtime-free):
  * `validate_quest_contracts.py` (quest group)
  * `validate_faction_contracts.py` (faction group)
  * `validate_quest_faction_contracts.py` (all 11 + partition/registry coherence)
* **`quest_faction_negatives.py`** — 44 in-code known-bad fixtures, each rejected
  for its owning WF77x–80x code, plus reverse-dogfood + vacuous-suite guard (GREEN).
* **`v2_2_shield.py`** — fail-closed shield. Spine-only GREEN 6/6; full
  (`--quests --factions`) honestly RED 6/22.
* **Makefile** v2.2 section (contract/negative/shield targets; more per wave).
* Docs: `docs/contracts/v2_2_quest_faction_contract.md`, this status file.

### Wave 1 acceptance (all GREEN)

```
PYTHONUTF8=1 python tools/pipeline/validate_failure_codes.py --strict
PYTHONUTF8=1 python tools/pipeline/validate_quest_contracts.py --strict
PYTHONUTF8=1 python tools/pipeline/validate_faction_contracts.py --strict
PYTHONUTF8=1 python tools/pipeline/validate_quest_faction_contracts.py --strict
PYTHONUTF8=1 python tools/pipeline/quest_faction_negatives.py --strict
PYTHONUTF8=1 python tools/pipeline/v2_2_shield.py --strict            # GREEN 6/6
PYTHONUTF8=1 python tools/pipeline/v2_2_shield.py --strict --quests --factions  # RED (fail-closed)
```

## Honest caveats

* Quest text is keyed placeholder metadata, not final writing.
* Factions are bounded state vectors, not a diplomacy/economy simulator.
* No dialogue trees, cinematics, companions, or campaign scripting.
* Runtime matrix is intentionally 24 scenarios (reuses v2.0 slice), not 120.
* Built over existing v2.0/v1.9 substrates; combat stays v1.8, rewards stay v1.9.
* No new player-facing UI; OperatorForge views are local/static control-plane views.
* No native navmesh claim introduced.
