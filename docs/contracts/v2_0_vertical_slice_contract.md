# v2.0 VerticalSliceForge — Contract Spine

**Status:** Wave 1 shipped — contract spine + fail-closed shield. Runtime (Wave R)
and package (Wave P) gates are honestly RED until their evidence exists.
**Milestone:** Integrate the v1.5–v1.9 substrates into the first generated
**playable slice** — a coherent loop where a player launches a generated build,
enters generated missions, traverses grounded space, meets active NPCs, survives
combat pressure, completes objectives, earns rewards, saves/loads, and can inspect
evidence proving the slice was generated safely. This is a **vertical-slice
substrate, NOT a full game** — coherence and proof over scale.
**Baseline:** sits on v1.5 (asset/visual materialization), v1.6z (grounded
traversal), v1.7 (NPC runtime behavior), v1.8 (CombatForge), v1.9
(reward/progression + save/load). It adds no new game systems.
**Pack:** `worldforge_vertical_slice` (a bounded subset of `encounter_loop_world`).
**Failure-code band:** `WF671–WF710` (`SLICE_*`), defined in
`tools/pipeline/failure_codes.py`. `validate_failure_codes.py` proves the band is
coherent (well-formed, unique WF numbers, every code has a severity and a taxonomy
entry) as the first gate of every shield.
**Schema module:** `tools/pipeline/slice_contracts.py` — the six slice contracts
as `*_REQUIRED`/`*_ALLOWED` field tuples + `validate_X(obj, strict)` returning
`(name, ok, detail, code)` check-tuples + `_example_X` factories + a `CONTRACTS`
registry (valid + owning-code known-bad per contract) split into `CONTRACT_GROUPS`
lanes. Hand-rolled field checks via the shared `runtime_schema` (RS) helpers — no
`jsonschema` (house style).

---

## Honesty invariants (anti-fake-green)

1. **A slice contract's `scenario_count` must equal the matrix product**
   (`biomes × mission_archetypes × encounter_profiles × seeds`), and every
   dimension must have no duplicate values. → `WF672 SLICE_SCENARIO_SET_INVALID`.
2. **A runtime report may claim `slice_completed_runtime` only if every major
   system is true** — `launched`, `player_spawned`, `traversal_completed`,
   `npc_behavior_seen`, `combat_damage_seen`, `mission_completed`,
   `reward_granted` — with ≥1 telemetry path and an **empty** `failure_codes`
   list. → `WF686 SLICE_PARTIAL_MATRIX` and the per-system codes (`WF677/679/680/
   702/703`).
3. **Reward participation that mutates no persistent state is fake reward** — a
   completed slice requires `inventory_mutated` OR `progression_mutated`. →
   `WF704 SLICE_REWARD_WITHOUT_MUTATION`.
4. **Save/load must round-trip AND use a v1.9 reward slot** (`WFReward_State` /
   `WFInventory_State` / `WFProgression_State`), never the mission/NPC/combat
   slots. → `WF684 SLICE_SAVE_LOAD_FAILED`, `WF705 SLICE_SAVE_LOAD_WRONG_SLOT`.
5. **A package report cannot pass with no package** — `package_exists=true`
   requires `package_size_bytes > 0`, and a passing report (empty `failure_codes`)
   requires a real package on disk. `created_at=="live"` requires a real `git_sha`.
   → `WF675 SLICE_PACKAGE_MISSING`, `WF676 SLICE_PACKAGE_INVALID`,
   `WF687 SLICE_STALE_EVIDENCE`.
6. **The evidence index must cover every scenario** — `integrity_result=ok`
   requires `scenario_count_seen == scenario_count_expected`, empty
   `missing_evidence`/`stale_evidence`, and one report per scenario per evidence
   category. → `WF685 SLICE_EVIDENCE_INDEX_INVALID`, `WF686`, `WF687`.
7. **No orphan / duplicate scenario reports** — a report whose scenario id is not
   in the manifest is an orphan; duplicate scenario ids are rejected. →
   `WF707 SLICE_DUPLICATE_SCENARIO_REPORT`, `WF709 SLICE_ORPHAN_REPORT`.

---

## Contracts

| Contract | Validator (`slice_contracts.py`) | Lane | Primary code |
|---|---|---|---|
| VerticalSliceContract | `validate_vertical_slice_contract` | definition | `WF671` |
| SliceScenario | `validate_slice_scenario` | definition | `WF696` |
| SliceManifest | `validate_slice_manifest` | definition | `WF697` |
| SliceRuntimeReport | `validate_slice_runtime_report` | runtime | `WF678` |
| SlicePackageReport | `validate_slice_package_report` | package | `WF674/675` |
| SliceEvidenceIndex | `validate_slice_evidence_index` | evidence | `WF685` |

Required fields per contract are the source of truth in `slice_contracts.py`
(`*_REQUIRED` tuples); this table is the index, not a duplicate schema.

### Selected slice matrix (bound in Wave 2)
- **Biomes (2):** `alpine_snow` (visually readable) · `volcanic_ashlands`
  (traversal/encounter-stress). Both fully materialized + fully evidenced under
  the `encounter_loop_world` lineage. *Desert is NOT used — it has maps but no
  mission/encounter/reward/route spine.*
- **Mission archetypes (3):** `survey_landmark` (reach objective) ·
  `recover_resource` (recover item) · `clear_hazard` (survive/clear encounter).
- **Encounter profiles (2):** `light_pressure` · `standard_pressure` (the real
  ids; the brief's "baseline/high" maps to these).
- **Seeds (2 per biome×archetype):** the two materialized maps per cell.
- **Product:** 2 × 3 × 2 × 2 = **24 scenarios**.
- **Reward binding:** `rwt_<archetype>_<band>`, band = `light_pressure→baseline`,
  `standard_pressure→high`. **Route binding:** `route_<map_id>__<archetype>`
  (runtime route catalog).

---

## Command surface

`make` is not installed in this environment; the Makefile targets document the
canonical command surface — run the mapped `python tools/pipeline/*.py --pack
<PACK> --strict` directly. Run Python validators with `PYTHONUTF8=1` on Windows
(emoji in reports crash cp1252).

### Contracts (Wave 1, GREEN)
```
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_failure_codes.py --strict
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_vertical_slice_contracts.py --pack encounter_loop_world --strict
PYTHONUTF8=1 STRICT=1 python tools/pipeline/slice_negatives.py --strict
```

### Shield
```
# contracts-only — GREEN from Wave 1
PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_0_shield.py --pack encounter_loop_world --strict
# full — honestly RED until Waves 2/R/P build the runtime & package gates
PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_0_shield.py --pack encounter_loop_world --strict --slices --require-live --package --torture
```

### Authoring / runtime / package / hostile (Waves 2–P — fail-closed until built)
`generate_slice_scenarios.py` · `validate_slice_scenarios.py` ·
`validate_slice_environment.py` · `validate_slice_assets.py` ·
`run_slice_forge_alpha.py` · `validate_slice_traversal.py` ·
`validate_slice_npc_combat.py` · `validate_slice_rewards.py` ·
`validate_slice_save_load.py` · `validate_slice_evidence_index.py` ·
`validate_slice_package.py` · `slice_fuzz.py` · `slice_torture.py` ·
`slice_report_integrity.py` · `slice_hygiene.py`

---

## Evidence output policy

```
procedural/generated/slice/vertical_slice_contract.json   # the slice definition
procedural/generated/slice/manifest.json                  # index over the slice
procedural/generated/slice/scenarios/*.json               # 24 SliceScenario files
procedural/reports/slice/validate_*_report.json           # contract/authoring gates
procedural/reports/slice/negatives/slice_negatives_report.json
procedural/reports/slice/runtime/slice_runtime_<slice_scenario_id>.json
procedural/reports/slice/runtime/slice_traversal_<slice_scenario_id>.json
procedural/reports/slice/runtime/slice_npc_combat_<slice_scenario_id>.json
procedural/reports/slice/runtime/slice_rewards_<slice_scenario_id>.json
procedural/reports/slice/save_load/slice_save_load_<slice_scenario_id>.json
procedural/reports/slice/package/slice_package_<slice_id>.json
procedural/reports/slice/integrity/slice_evidence_index_<slice_id>.json
```

Slice evidence is independently inspectable; it may **reference** the
combat/npc/reward/ground trees (`procedural/reports/{combat,npc,rewards,ground}/`)
but does not mix into them.

---

## Hard non-goals

v2.0 is an **integration and packaging milestone**, not feature sprawl. It adds no
full game, campaign, open/streaming world, multiplayer, final art/combat/loot
feel, inventory UI, crafting, vendors, economy, quests, factions, or tactical AI;
no new Fab/Megascans acquisition, Houdini live cook, biome system, or mission
archetype. NPCs remain v1.7/v1.8 sentry/waypoint pressure; combat is the v1.8
substrate; rewards are the v1.9 bounded deterministic consequence substrate;
traversal remains `grounded_manual_waypoint` / `grounded_worldforge_route` with no
native UE navmesh dependency added.
