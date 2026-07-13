# v2.5 Lane 4 — Runtime Regression & UE 5.8 Baseline (handoff)

Branch: `worldforge/v2.5-ue58-transition` · Worktree: `D:\Unreal Projects\WorldForge-UE58`
Wave: validators + harness scaffolding ONLY (no UE, no live runtime, no real baseline).

## Objective

Build the shield `--regression` runner, its dogfood validator, the one-time baseline
BUILDER (gated), and the shield `--baseline` gate — so that the moment the commander's
serial UE 5.8 work lands (Wave 8), these gates flip from honest-RED to real GREEN with no
further scaffolding. This wave runs NO Unreal and produces NO passing report: the
regression and baseline gates are **honestly RED by design** because there is no UE 5.8
runtime, no ported plugin binary, and no converted maps yet.

## Files created

| File | Role |
|---|---|
| `tools/pipeline/transition_regression.py` | shield `--regression` runner; emits honest-incomplete `TransitionRegressionReport`; exits non-zero |
| `tools/pipeline/validate_transition_regression.py` | dogfoods `TransitionRegressionReport`; validates the emitted report if present |
| `tools/pipeline/build_transition_baseline.py` | one-time baseline BUILDER, double-gated (AUTHORIZED file + completed regression); refuses by default |
| `tools/pipeline/validate_transition_baseline.py` | shield `--baseline` gate; dogfoods `TransitionBaseline`; validates the index if present |
| `docs/status/v2_5_lane_4_runtime_status.md` | this handoff |

Machine-generated scaffolding reports written under:
`procedural/reports/ue5_8/regression/` and `procedural/reports/ue5_8/baseline/`.

Untouched (read-only inputs): `transition_contracts.py`, `validate_transition_contracts.py`,
`report_meta.py`, `validation_report.py`, `runtime_schema.py`, `engine_identity.py`,
`failure_codes.py`, `v2_5_shield.py`. Left alone per lane boundary:
`docs/status/v2_5_lane_4_status.md` (Wave-1 contract-spine doc — different file).

## Contracts dogfooded

- `TransitionRegressionReport` (`wf.transition.regression_report.v1`) — via
  `validate_transition_regression.py` and re-validated inside `transition_regression.py`.
- `TransitionBaseline` (`wf.transition.baseline_index.v1`) — via
  `validate_transition_baseline.py` and inside `build_transition_baseline.py` before write.

Each dogfood asserts: the canonical valid example passes with zero failures, the registry
known-bad is rejected for its owning code, and extra inline known-bads prove each honesty
rail (see below). Dogfoods are GREEN this wave.

### Regression known-bads proven rejected
- `regression_free=True` + `worldforge_regression` diff → `WF1022_REGRESSION_WORLDFORGE_REGRESSION`
- `regression_free=True` + `maps_loaded < maps_checked` → `WF1020_MAP_LOAD_FAILED`
- `regression_free=True` + `unclassified` diff → `WF1021_REGRESSION_UNCLASSIFIED_DIFF`

### Baseline known-bads proven rejected
- entry `engine_minor != 8` (9) → `WF1031_EVIDENCE_ENGINE_MISMATCH`
- registry known-bad: 5.7-tagged entry → `WF1032_EVIDENCE_5_7_CONTAMINATION`
- entry `report_path` under `procedural/reports/ue5_7` → `WF1033_EVIDENCE_COPIED_FROM_OLD_ENGINE`
- `entry_count != len(entries)` → `WF1034_TRANSITION_REPORT_INTEGRITY_FAILED`
- absolute `report_path` → `WF1034_TRANSITION_REPORT_INTEGRITY_FAILED`

## Meta convention (binding)

Every runtime report attaches via `build_meta(extra={ **engine_identity(),
declared_target_engine="5.8", observed_runtime_engine=None,
runtime_execution_required=True, runtime_executed=False })`. `runtime_executed` is NEVER
set True without a real UE 5.8 run (there is none this wave). In this worktree
`engine_identity()` currently resolves `engine_minor=7` (the uproject still associates 5.7
and 5.7 is the installed engine) — so host-generated reports are honestly tagged 5.7 and
the Wave-8 baseline scan (which requires `meta.engine_minor==8`) correctly finds nothing
yet.

## Exact commands + real output

```
PYTHONUTF8=1 python tools/pipeline/transition_regression.py --strict          # EXIT=1 (RED, by design)
  FAIL: payload::rg::number::maps_loaded: maps_loaded=0 must be >0
  FAIL: regression::runtime_executed: no UE 5.8 regression run this wave — runtime_executed=False
  FAIL: regression::regression_free: regression not proven free under 5.8 (regression_free=False)

PYTHONUTF8=1 python tools/pipeline/validate_transition_regression.py --strict  # EXIT=1 (dogfoods GREEN, present-report honesty RED)
  FAIL: present::rg::number::maps_loaded / present::runtime_executed / present::regression_free
  (all dogfood::* checks PASS)

PYTHONUTF8=1 python tools/pipeline/build_transition_baseline.py                # EXIT=2 (refuses)
  baseline not authorized
    reason: authorization file absent: procedural/reports/ue5_8/baseline/AUTHORIZED

PYTHONUTF8=1 python tools/pipeline/validate_transition_baseline.py --strict    # EXIT=1 (dogfoods GREEN, index absent → fail-closed RED)
  FAIL: present::baseline_exists: no baseline index ... (build is Wave-8-gated)

PYTHONUTF8=1 python tools/pipeline/v2_5_shield.py --strict --regression --baseline   # SHIELD RED — 1/3
  [PASS] transition-contracts   [FAIL] transition-regression   [FAIL] transition-baseline
```

Builder gate-ladder verified in an isolated in-repo sandbox (no real files touched,
cleaned up): (1) no AUTHORIZED → refuse rc 2; (2) AUTHORIZED + incomplete regression →
refuse rc 2; (3) AUTHORIZED + completed regression + a 5.8-tagged report → writes a
contract-valid `baseline_index.json`, rc 0, zero contract failures.

## Why regression & baseline gates are honestly RED

No UE 5.8 engine has run. A green regression or a built baseline without a real 5.8 run
would be a laundered claim — the exact failure mode the v2.5 contracts exist to block. So:
- `transition_regression.py` emits `runtime_executed=False`, `regression_free=False`,
  `maps_loaded=0` and exits non-zero. Fail-closed, honest-incomplete — NOT a passing report.
- `build_transition_baseline.py` refuses to build (double-gated).
- `validate_transition_baseline.py` fails-closed on the absent index.

These flip GREEN only when a real 5.8 run replaces the scaffold.

## Authorization contract for Wave 8 (what flips baseline GREEN)

The commander must, after the serial UE 5.8 work lands:

1. Produce a COMPLETED regression by running `transition_regression.py` (upgraded to drive
   the real 5.8 run) so that
   `procedural/reports/ue5_8/regression/transition_regression_report.json` has
   **`meta.runtime_executed == True`, `regression_free == True`, `maps_loaded == maps_checked`,
   every diff classified, and passes the `TransitionRegressionReport` contract.**
2. Create the authorization file **`procedural/reports/ue5_8/baseline/AUTHORIZED`** (any
   content). This tool NEVER creates it — it is the commander's explicit consent gate.
3. Run `python tools/pipeline/build_transition_baseline.py`. With both gates met it scans
   the `procedural/reports/ue5_8/` tree for reports whose `meta.engine_minor == 8`,
   assembles the `TransitionBaseline` index, validates it against the contract, and writes
   `procedural/reports/ue5_8/baseline/baseline_index.json`.
4. `python tools/pipeline/validate_transition_baseline.py --strict` then goes GREEN, and the
   shield `--baseline` gate turns GREEN.

## Harness spec (representative subsystems)

`transition_regression.HARNESS_SUBSYSTEMS` (bounded, unique, 10 entries) — the subsystems a
real 5.8 regression must exercise end-to-end before the port is regression-free:
`project_launch, map_load, runtime_actor_spawn, mission_completion, combat_mutation,
save_load, streaming_lifecycle, quest_faction_state, tactical_behavior, evidence_generation`.
Prior-authoring shields re-run: `v2_4_shield, v2_3_shield, v2_2_shield`. Regression surface:
the v2.0 24-slice map matrix (`SLICE_MAP_COUNT = 24`).

## Limitations

- No Unreal launched; no live runtime smoke; no real baseline built — all gated on the
  commander's serial UE work.
- `transition_regression.py` currently only emits the honest-incomplete scaffold; Wave 8
  must extend it to actually drive the 5.8 run and populate `maps_loaded`/`diffs`.
- The `maps_loaded=0` positive-int failure is an intentional additional honest signal that
  the regression is incomplete; it disappears once a real run loads maps.

## Git status

New, uncommitted (not added/committed/pushed per lane rules):
`tools/pipeline/{transition_regression,validate_transition_regression,build_transition_baseline,validate_transition_baseline}.py`,
`procedural/reports/ue5_8/regression/`, `procedural/reports/ue5_8/baseline/`,
`docs/status/v2_5_lane_4_runtime_status.md`.
