# v2.5 Lane 4 (ContractForge / transition spine) — Contract Spine

Status: COMPLETE (uncommitted; commander handles commits)
Worktree: `D:\Unreal Projects\WorldForge-UE58` (active 5.8 transition worktree)
Date: 2026-07-12

## Files created
- `tools/pipeline/transition_contracts.py` — the 7-contract schema spine (registry
  module). Mirrors `tactical_contracts.py` structure exactly.
- `tools/pipeline/validate_transition_contracts.py` — the always-on dogfood gate.
  Mirrors `validate_tactical_contracts.py` exactly.

`failure_codes.py` was already carrying the WF1011–1039 transition band (Lane 0/1 work);
this lane consumes those codes and does not add new ones.

## The 7 contracts and the failure code each known-bad is rejected FOR

| Contract | Covers | KNOWN_BAD_OWNING_CODE |
|----------|--------|------------------------|
| `EngineIdentity` | WF1013 | `ENGINE_VERSION_MISMATCH` (bad: engine_major=4) |
| `CapabilityManifest` | WF1011/1012 | `CAPABILITY_UNAVAILABLE` (bad: required cap unavailable) |
| `ConversionManifest` | WF1014/1015/1016 | `CONVERSION_ACTOR_LOSS` (bad: actor loss, 0 accounted deletions) |
| `PluginBuildReport` | WF1017/1018/1019 | `BUILD_FAILED` (bad: overall_ok=True while build failed) |
| `TransitionRegressionReport` | WF1020/1021/1022 | `REGRESSION_WORLDFORGE_REGRESSION` (bad: regression_free w/ regression diff) |
| `GloamBridgeProbe` | WF1023–1030 | `BRIDGE_ABSENT_PLUGIN` (bad: probe "ready" with no plugin) |
| `TransitionBaseline` | WF1031/1032/1033 | `EVIDENCE_5_7_CONTAMINATION` (bad: 5.7-tagged entry in 5.8 baseline) |

`CONTRACT_GROUPS` partitions the registry into `identity_capability`, `conversion_build`,
`regression_bridge`, `baseline`. `TRANSITION_CODES` collects the WF1011–1060 band (29 codes
present today).

## Honesty checks each contract enforces (beyond shape)
- **EngineIdentity** — engine_major==5, engine_minor ∈ {7,8}, path_identity `<12hex>:<basename>`.
- **CapabilityManifest** — a `required` capability that is not `available` → WF1011; an
  `available` capability whose `actual_version` != `required_version` → WF1012.
- **ConversionManifest** — `actors_after >= actors_before - accounted_deletions` (no silent
  actor loss); `len(maps) == expected_map_count` (complete); `churn_class` ∈ accounted set;
  `source_engine`/`target_engine` pinned to 5.7/5.8; map paths must be relative (no abs leak).
- **PluginBuildReport** — `overall_ok` implies build succeeded AND plugin_loaded AND
  `binary_mtime >= newest_source_mtime` (not stale).
- **TransitionRegressionReport** — `regression_free` implies all maps loaded, every diff
  classified, and no `worldforge_regression` diff; must run on `engine_minor==8`.
- **GloamBridgeProbe** — targets engine 5.8 + a Gloamstead project; a `ready` claim must be
  backed by plugin_present + map_present; no absolute-path leak in evidence; a
  `rejected_dry_probe` must carry a rejection_reason. (v2.5 example IS a rejecting dry probe.)
- **TransitionBaseline** — every entry tagged with the index engine (8); no 5.7-tagged entry;
  no path drawn from the `procedural/reports/ue5_7` subtree; entry_count matches.

## Proof (REAL, run from the worktree)
```
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_transition_contracts.py --strict
  -> [transition-contracts] PASS — worldforge_vertical_slice (0 failure(s), 0 warning(s), strict=on)  EXIT=0

PYTHONUTF8=1 python tools/pipeline/v2_5_shield.py            (no flags — always-on lane)
  -> [PASS] transition-contracts
  -> v2.5 shield: GREEN — 1/1 gates passed
```
The always-on `transition-contracts` lane has flipped **RED (0/1) -> GREEN (1/1)**. The
remaining 11 gates stay honestly fail-closed until their Wave-2..7 scripts land.

Report: `procedural/reports/ue5_8/validate_transition_contracts_report.json`
(git_sha real under Git Bash; engine identity attached via `build_meta(extra=engine_identity())`).

## Open decision for Lane 8 (report-integrity)
The contract-spine report is **runtime-free / engine-agnostic** but is written under the
`ue5_8/` subtree, and with no `WF_UE_CMD` set it resolves `engine_minor=7` (uproject 5.7
association fallback). When Lane 8's `transition_report_integrity.py` gates reports under
`procedural/reports/ue5_8`, it must EITHER exempt runtime-free contract/spine reports from the
"declares engine_minor==8" rule, OR the shield must run this gate with `WF_UE_CMD=D:/UE_5.8`
so the spine report honestly declares the 5.8 line it gates. Do not silently hard-code 8 into
the gate — the spine did not execute 5.8 code. Flagged here so the integrity rule is a
deliberate choice, not an accident.

## Assumptions later lanes MUST honor
1. Import contracts from `transition_contracts` (`CONTRACTS`, `CONTRACT_GROUPS`,
   `KNOWN_BAD_OWNING_CODE`, `TRANSITION_CODES`) — one source of truth, same as the tactical spine.
2. Wave-2..7 gates own cross-artifact resolution (does the binary exist? did 5.8 open the
   map?). The spine is schema-only and proves shape/honesty at authoring time.
3. Run with `PYTHONUTF8=1` on Windows; run the shield under **Git Bash** (git not on the PS
   child PATH → git_sha 'unknown' → integrity RED).
