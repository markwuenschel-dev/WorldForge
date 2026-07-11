# WorldForge v2.2 QuestForge + FactionStateForge — Status

Branch: `worldforge/v2.2-quest-faction` (off `main` @ `1c5406c`)
Failure-code band: **WF771–WF850** `QUEST_FACTION_*`

## Baseline (verified before build)

* v2.1 shield GREEN 20/20 (`--strict --operator`)
* v2.0 shield GREEN 4/4 (`--strict --package`)

## Wave status

| Wave | Scope | State |
|------|-------|-------|
| 1 | Contracts + fail-closed shield | ✅ **DONE** |
| 2 | Authoring generators (quests + factions) | ✅ **DONE** — 24 quests / 4 factions |
| 3 | Runtime quest/faction proof (24 scenarios) | ✅ **DONE** — 16/6/2 success/partial/failure |
| 4 | OperatorForge integration | ✅ **DONE** — 24 quest + 4 faction views |
| R | Hostile closure + v2.2 shield green | ✅ **DONE** — shield GREEN 22/22 |

## Final result — v2.2 shield GREEN 22/22 (24/24 with regressions)

```
PYTHONUTF8=1 python tools/pipeline/v2_2_shield.py --strict --quests --factions               # GREEN 22/22
PYTHONUTF8=1 python tools/pipeline/v2_2_shield.py --strict --quests --factions --regressions  # GREEN 24/24
```

Runtime matrix: 24/24 complete. Outcomes 16 success / 6 partial_success / 2 failure
(all outcome-bearing → all mutate faction state). 24 consequence ledgers (all
post-hash != pre-hash). Save/load roundtrip_ok on all 24 (saved state == ledger post
hash). World faction state accumulated across runs (e.g. wardens standing 0→100).
Regressions: v2.1 GREEN 20/20, v2.0 GREEN. v1.9/v1.8/v1.7/v1.6z NOT rerun — v2.2
changed none of their semantics (handoff §14: no full-matrix reruns by default; the
live-UE regressions run via their own shields with --require-live).

## Deferred (honest caveats)

* Live in-editor UE quest/faction run — Wave 3 is a deterministic simulation
  consuming the generated datasets + v2.0 slice matrix, producing genuine
  contract-valid consequence evidence (same posture as v1.9 reward / v2.0 slice).
* Quest text is keyed placeholder metadata; factions are bounded state vectors.

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
