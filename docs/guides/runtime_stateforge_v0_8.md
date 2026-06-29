# Runtime StateForge (v0.8)

> Make generated worlds **react** and **remember**.

Canonical scenario:

```
activate_industrial_forge
  → industrial_pressure increases
  → terrain darkens through the MPC bridge
  → POI state evidence updates
  → save/load preserves state
  → map remains valid
```

v0.8 splits into two surfaces:

- **Authoring-side (pure Python, runs anywhere):** `run-state-sim` simulates the
  scenario over data and writes a deterministic result descriptor;
  `validate-runtime-state` proves the result.
- **UE-side (in-editor):** `apply-state-scenario` applies the same post-state via
  the `WorldForge.SetState` console path and reads the MPC render-mirror back.

The authoring side is the contract; the UE bridge is validated against it.

## Commands

```bash
# 1. Simulate the scenario against a target (slice id / Region context_id)
make run-state-sim NAME=Desert_Ash_IndustrialYard_01 SCENARIO=activate_industrial_forge

# 2. Validate the simulated result
make validate-runtime-state NAME=Desert_Ash_IndustrialYard_01

# 3. (UE-side) apply + read back the MPC bridge, with the slice map open
make apply-state-scenario NAME=Desert_Ash_IndustrialYard_01 SCENARIO=activate_industrial_forge
```

`run-state-sim` resolves `NAME` to a slice spec at
`procedural/slices/<biome>/generated/<NAME>.json` when one exists (using its
recorded `state.before` as the baseline); otherwise `NAME` is treated as a
Region `context_id` and the scenario's `initial_state` is the baseline.

## Scenario recipe fields

`procedural/definitions/scenarios/<scenario_id>.yaml`:

| Field | Meaning |
|-------|---------|
| `scenario_id`, `display_name`, `biome`, `description` | Identity. |
| `compatible_slices`, `compatible_poi` | Advisory targeting hints. |
| `scope` | State scope to mutate (`Region`). |
| `initial_state` | Baseline per key, used when no slice spec resolves. |
| `state_deltas` | Additive, clamped mutation per key (the reaction). |
| `expected_mpc` | Curated `state_key -> MPC param` the render mirror must reflect. |
| `expected_poi_evidence` | Per POI type: `operational_state`, `driven_by_key`, `evidence_fields`. |
| `save_load.persist_keys` / `expect_roundtrip` | What must survive save/load. |
| `validation_thresholds` | `state_min`, `state_max`, `max_delta_per_key` bounds. |

State keys are **data-defined**. Validators never hard-code `industrial_pressure`
— add new scenarios/keys without touching the tools (curated keys that reach the
MPC are listed in `WorldStateSubsystem.cpp`: `industrial_pressure`,
`corruption_level`, `restoration_level`, `wetness`, `ashfall`).

## Output locations

```
procedural/generated/scenarios/<run_id>/result.json        # result descriptor
procedural/generated/scenarios/<run_id>/state_save.json    # persisted post-state
procedural/generated/worldforge_scenario_registry.json     # run registry
procedural/reports/scenarios/<run_id>/validate_runtime_state_report.json
procedural/reports/scenarios/<run_id>/ue_state_scenario_report.json  # UE bridge
```

`run_id = "<NAME>__<scenario_id>"`.

## What validate-runtime-state proves

Initial state read · state mutated by the scenario's bounded/clamped deltas ·
post-state aggregated · MPC bridge effect correctly expected (curated key → param
→ post-value) · POI state evidence updated · **save/load round-trip restored the
persisted state** · provenance present.

Two checks are `warn_only` until the editor is involved:

- `post_scenario_map_valid` — passes once `make validate-slice` has passed for the
  target slice.
- `ue_state_applied` — passes once `make apply-state-scenario` has written a
  passing `ue_state_scenario_report.json`.

The report surfaces a legible before/after summary, `affected_poi`, and
`save_load` status for inspection.

## Known limitations

- Save/load is implemented and validated at the **data layer** (a real
  write→read→compare round-trip in `state_save.json`). In-editor world-state
  serialization is a later milestone; the UE bridge currently applies state and
  reads the MPC back but does not yet persist the live world.
- `apply-state-scenario` must run with the scenario's slice map open so the
  world's `UWorldStateSubsystem` and `MPC_WorldState` instance are live.
- POI evidence is computed from the driving state key; richer per-template
  evidence models are future work.
