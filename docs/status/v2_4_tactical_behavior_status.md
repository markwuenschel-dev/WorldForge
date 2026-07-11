# WorldForge v2.4 AdvancedAIForge / TacticalBehaviorForge — Status

Branch: `worldforge/v2.4-tacticalbehaviorforge` (off `main` @ v2.3 merge `6a18bd2`)
Failure-code band: **WF931–WF1010** `TACTICAL_*` (WF931–974 defined, WF975–1010 reserved)

## Baseline (to verify before downstream waves)

* v2.3 shield GREEN 22/22 · v2.2 GREEN 22/22 · v2.1 GREEN 20/20 · v2.0 GREEN 20/20

## Wave status

| Wave | Scope | State |
|------|-------|-------|
| 1 | Tactical contracts + fail-closed shield | ✅ **DONE** — spine + negatives GREEN, downstream RED |
| 2 | Profiles / roles / affordance authoring | ⏳ pending |
| 3 | Tactical NPC / group bindings | ⏳ pending |
| 4 | Tactical runtime / decision proof (24 scenarios) | ⏳ pending |
| 5 | Tactical save/load + budgets | ⏳ pending |
| 6 | OperatorForge tactical views | ⏳ pending |
| R | Hostile closure + v2.4 shield green + regressions | ⏳ pending |

## Wave 1 result — contract spine GREEN, downstream fail-closed RED

```
python tools/pipeline/validate_tactical_contracts.py --strict   # PASS (15 contracts dogfooded)
python tools/pipeline/tactical_negatives.py --strict            # PASS (51 known-bads, each owning-code)
python tools/pipeline/v2_4_shield.py --strict                   # GREEN 4/4 (always-lane)
python tools/pipeline/v2_4_shield.py --strict --tactical --advanced-ai   # RED 4/23 (fail-closed, correct)
```

Delivered in Wave 1:

* `tools/pipeline/failure_codes.py` — WF931–974 `TACTICAL_*` band (44 codes; backfill
  auto-registers SEVERITY + GATE_TAXONOMY; `validate_failure_codes` GREEN)
* `tools/pipeline/tactical_contracts.py` — 15 schema-only contracts, `CONTRACTS` registry,
  `CONTRACT_GROUPS`, `KNOWN_BAD_OWNING_CODE`, `TACTICAL_CODES`
* `tools/pipeline/validate_tactical_contracts.py` — dogfood gate (valid passes, known-bad
  rejected for owning code, registry coherent)
* `tools/pipeline/tactical_negatives.py` — 51 hostile negative fixtures, one honesty
  invariant each, all rejected for the owning code
* `tools/pipeline/v2_4_shield.py` — fail-closed aggregator (`--tactical` / `--advanced-ai`
  / `--regressions`)
* `Makefile` — v2.4 section (Wave-1 targets: `tactical-contracts`,
  `tactical-negative-fixtures`, `v2-4-shield`; later targets land per wave)
* `docs/contracts/v2_4_tactical_behavior_contract.md`, this status doc

## Honest caveats (carried into the PR)

* v2.4 is a **bounded tactical behavior substrate**, not final game AI.
* Runtime matrix is intentionally **24 scenarios**, not 120.
* Runtime mode will be labeled honestly (`deterministic_tactical_simulation` or
  `live_tactical_runtime`); a simulation is never labeled live AI.
* NPC behavior stays bounded by existing routes, anchors, cover affordances, and
  streaming scopes. No native UE navmesh claim, no BT editor / GOAP / EQS / RL / LLM NPC.
* Combat = v1.8 substrate; streaming = v2.3 substrate; quest/faction = v2.2 substrate.
