# WorldForge v2.5 — Swarm Milestone Ledger (Lane 0 / Commander)

Commander: Lane 0. Worktree: `D:\Unreal Projects\WorldForge-UE58`.
Branch: `worldforge/v2.5-ue58-transition`. Base commit: `fa922a37` (Wave 1 foundation).
UE 5.8: `D:\UE_5.8` (explicit; never rely on the uproject `5.7` association fallback).
Last updated: 2026-07-13.

## Commander decisions (binding for all lanes)
1. **Single worktree, disjoint file ownership.** Rule 1 ("separate branches/worktrees")
   is satisfied via strictly disjoint file ownership below + serial commander commits.
   Python/fixture/doc lanes run concurrently in THIS worktree and DO NOT commit — Lane 0
   commits. This avoids 6-way worktree merge overhead for disjoint Python files.
2. **The UE-dependent critical path is serial and Lane-0-driven.** Plugin build (Lane 1),
   authoritative asset conversion (Lane 3 conversion window), live runtime smokes + full
   baseline (Lane 4), and the live bridge fixture (Lane 6 Wave 7) run one-at-a-time. Their
   gates stay **fail-closed** until a real UE 5.8 run proves them. No fake greens.
3. **Shield location:** the existing `tools/pipeline/v2_5_shield.py` is authoritative
   (NOT `tools/shields/`). Lane 7 extends it; gate scripts auto-flip the shield when present.
4. `failure_codes.py` (WF1011–1039 band) and `engine_identity.py` are **read-only** to all
   lanes except where noted; Lane 2 builds `transition_identity.py` ON TOP of engine_identity.

## Ownership manifest (disjoint — no lane edits another's files)

| Lane | Owner | Owned paths |
|------|-------|-------------|
| 0 | commander (me) | `docs/status/v2_5_swarm_status.md`; all commits; shield integration |
| 1 | commander (serial UE) | `Plugins/WorldForge/Source/**`, `Source/**`, `*.Target.cs`, `Plugins/WorldForge/WorldForge.uplugin`, `tools/pipeline/validate_plugin_build.py`, `docs/status/v2_5_lane_1_*.md` |
| 2 | subagent | `tools/pipeline/transition_identity.py`, `validate_engine_identity.py`, `validate_track_isolation.py`, `validate_transition_topology.py`, `validate_capability_manifest.py`, `docs/status/v2_5_lane_2_status.md`, `docs/runbooks/ue57_ue58_transition.md` |
| 3 | subagent (inventory) + commander (conversion) | `tools/pipeline/build_conversion_manifest.py`, `validate_conversion_manifest.py`, `audit_conversion_diff.py`, `procedural/manifests/ue5_8_conversion/**`, `docs/status/v2_5_lane_3_status.md` |
| 4 | subagent (validators) + commander (runtime) | `tools/pipeline/transition_regression.py`, `validate_transition_regression.py`, `build_transition_baseline.py`, `validate_transition_baseline.py`, `procedural/reports/ue5_8/regression/**`, `procedural/reports/ue5_8/baseline/**`, `docs/status/v2_5_lane_4_runtime_status.md` |
| 5 | subagent | `tools/pipeline/discover_unreal_engine.py`, `run_transition_ci.py`, `docs/status/v2_5_lane_5_status.md`, CI/Makefile via commander |
| 6 | subagent (contract/probe) + commander (live) | `tools/bridge/**`, `tools/pipeline/gloam_bridge_probe.py`, `validate_gloam_bridge.py`, `docs/contracts/cross_repo_bridge.md`, `docs/status/v2_5_lane_6_status.md` |
| 7 | subagent | `tools/pipeline/validate_transition_integrity.py`, `run_transition_known_bads.py`, `run_transition_torture.py`, `transition_negatives.py`, `transition_fuzz.py`, `transition_report_integrity.py`, `transition_hygiene.py`, `procedural/known_bads/v2_5/**`, `procedural/reports/ue5_8/hostile/**`, `docs/status/v2_5_lane_7_status.md`; shield wiring w/ Lane 0 |

## Shield gate → owner → expected Wave-2 state

| Gate | Script | Owner | Wave-2 expectation |
|------|--------|-------|--------------------|
| transition-contracts | `validate_transition_contracts.py` | done | **GREEN** (committed) |
| transition-topology | `validate_transition_topology.py` | L2 | GREEN (schema/registry) |
| capability-manifest | `validate_capability_manifest.py` | L2 | GREEN (shape; availability pending L1 handshake) |
| plugin-build | `validate_plugin_build.py` | L1/cmd | **RED (gated on 5.8 build)** |
| conversion-manifest | `validate_conversion_manifest.py` | L3 | **RED (gated on authoritative conversion)** |
| transition-regression | `transition_regression.py` | L4/cmd | **RED (gated on runtime smokes)** |
| transition-baseline | `validate_transition_baseline.py` | L4 | **RED (gated on authorized baseline)** |
| gloam-bridge | `validate_gloam_bridge.py` | L6 | GREEN (rejecting dry-probe contract; live fixture Wave 7) |
| transition-negatives | `transition_negatives.py` | L7 | GREEN |
| transition-fuzz | `transition_fuzz.py` | L7 | GREEN |
| transition-report-integrity | `transition_report_integrity.py` | L7 | GREEN |
| transition-hygiene | `transition_hygiene.py` | L7 | GREEN |

## Lane status

| Lane | Status | Latest | Blockers | Evidence |
|------|--------|--------|----------|----------|
| 0 | ACTIVE | Wave 1 committed `fa922a37`; ledger published | — | this doc |
| 1 | **DONE** | **UE 5.8 compile GREEN + load GREEN**: build#3 exit 0; headless boot loaded WorldForgeCore+WorldForgeEd from fresh 5.8 DLLs, engine-init reached; `--plugin` gate PASS (engine 5.8.0/55116800, plugin v0.1.0, not-stale, 5 negatives reject). Port = Target.cs V6→V7 + include 5.7→5.8 + HoudiniNiagara optional. | — | `procedural/reports/ue5_8/plugin/` |
| 2 | READY_FOR_REVIEW | 4 gates GREEN (topology/capability/engine-identity/track-isolation); preservation refs `release/ue5.7-v2.4-lts` + tag EXIST | — | `procedural/reports/ue5_8/` |
| 3 | READY_FOR_REVIEW | 179 assets/124 maps inventoried (hash 0a9b6987…); dogfood+audit GREEN; conversion gate honest-RED | authoritative conversion (Wave 5) | `procedural/manifests/ue5_8_conversion/pre_conversion_manifest.json` |
| 4 | **DONE** | Wave 6 runtime smokes COMPLETED (real UE 5.8 evidence): regression `runtime_executed=True`, `regression_free=True`, 124/124 maps. Wave 8 one-time baseline BUILT (11 entries, all engine_minor==8, indexes the runtime regression). `transition-regression` + `transition-baseline` gates GREEN. | — | `procedural/reports/ue5_8/regression/`, `procedural/reports/ue5_8/baseline/` |

**Commander integration TODO — DONE (2026-07-14):** `WorldForge.uproject` EngineAssociation flipped `5.7→5.8` (build proven) so `engine_identity()` resolves minor=8 natively against `D:\UE_5.8`; the 6 host reports still host-resolved to minor=7 were regenerated → 11 ue5_8 reports now carry `meta.engine_minor==8`. (The 5.7 CI summary legitimately stays minor=7 and is correctly excluded from the 5.8 baseline.)
| 5 | READY_FOR_REVIEW | discover_unreal_engine + run_transition_ci GREEN (python-only exit 0); 5.7=51494982@5.7.4, 5.8=55116800@5.8.0; cache isolation proven; Makefile/CI blocks proposed for cmd | commander applies Makefile/CI | `procedural/reports/ue5_8/ci/` |
| 6 | READY_FOR_REVIEW | **bridge gate GREEN** (--bridge 2/2, dry-probe contract, 8 negatives→WF1023-1030); no live run | live fixture (later gated wave) | `procedural/reports/ue5_8/gloam/` |
| 7 | READY_FOR_REVIEW | 4 hostile gates GREEN (subagent, re-verified); umbrella+known-bads+torture commander-completed after subagent auth-death; integrity umbrella 6/6 GREEN; fixed a torture false-positive (advisory/nullable fields) honestly | — | `procedural/reports/ue5_8/hostile/` |

## SHIELD STATUS (2026-07-14, post Wave-8 baseline)
Full shield all-flags: **GREEN 14/14** — all gates pass, including the 3 formerly
honest-RED gates now genuinely satisfied by real UE 5.8 work: `conversion-manifest`
(Wave 5), `transition-regression` (Wave 6 runtime smokes), `transition-baseline` (Wave 8).
Downstream regressions GREEN: v2.4 (`--tactical`), v2.3 (`--streaming --worldscale`),
v2.2 (`--quests --factions`).

```
python tools/pipeline/v2_5_shield.py --strict --topology --conversion --plugin \
  --capability --regression --baseline --bridge --hostile   # GREEN 14/14
python tools/pipeline/v2_5_shield.py --strict --regressions                    # GREEN 4/4
```

NOTE: Lane 2's engine-identity + track-isolation gates pass standalone but are not yet wired
as shield flags (shield refinement TODO — add `--identity`/`--isolation`).

## Authorization gates (Lane 0 holds these)
- **Authoritative conversion (Wave 5):** requires plugin build GREEN + module load GREEN +
  track isolation GREEN + pre-conversion inventory complete + conversion validator GREEN.
- **One-time full baseline (Wave 8):** requires all targeted smokes GREEN + conversion audit
  GREEN + plugin load GREEN + report integrity GREEN + zero unresolved `unknown`.

## Wave 5 — authoritative conversion (USER-AUTHORIZED 2026-07-13, commander sole writer)
- Actor-census method: `wf_map_actor_census.py` run in-editor under each engine (read-only load+count).
- **5.8 pre-resave census: 123 maps, ALL loaded (0 failures), 2797 actors.** Every 5.7-authored
  map opens under 5.8 with actors intact — strongest possible pre-resave signal.
- **5.7 authoritative census: 131 maps (123 committed + 8 untracked test), all loaded, 2799 actors.**
- **ACTOR-LOSS VERDICT: CLEAN.** 123 common committed maps, all load under both engines, ZERO
  actor losses (5.8 count ≥ 5.7 count on every map). The 2-actor total delta is entirely in the
  8 untracked 5.7-only test maps (not authoritative content). No unexplained loss, no load failures.
- ResavePackages under 5.8 running (the on-disk 5.7→5.8 format upgrade; frozen 5.7 worktree untouched).
- Next: post-resave census → build authoritative `conversion_manifest.json` → validate + audit → flip gate.

## Wave 6 — runtime smokes (real UE 5.8 evidence) + Wave 8 — one-time baseline (USER-AUTHORIZED 2026-07-14)
- **Runtime evidence (Wave 6):** `procedural/evidence/ue5_8/runtime_smoke.json` (actor spawn/destroy
  roundtrip, ok) + the 5.7/5.8 post-resave censuses drive `transition_regression.py`, which
  reassembles a COMPLETED report (`runtime_executed=True`, `regression_free=True`, 124/124 maps
  loaded, 1 accounted `expected_engine_diff`). No fabricated greens — the runner stays honest-RED
  without this evidence.
- **Engine-identity honesty (integration TODO closed):** uproject flipped `5.7→5.8` so
  `engine_identity()` resolves minor=8 natively (`D:\UE_5.8`); regenerated the 6 host reports that
  were still host-resolved to minor=7. Result: 11 ue5_8 reports at `meta.engine_minor==8`.
- **Baseline (Wave 8, double-gated):** Gate 1 = `procedural/reports/ue5_8/baseline/AUTHORIZED`
  (commander-created; the builder NEVER creates it). Gate 2 = the completed regression above.
  `build_transition_baseline.py` scanned the ue5_8 tree and wrote `baseline_index.json` with
  **11 engine_minor==8 entries**, including the runtime regression itself. Contract-valid
  (every entry engine_minor==8, no 5.7 contamination, no ue5_7-tree paths).
- **Result: v2.5 shield GREEN 14/14 + regressions GREEN 4/4.**

## Stop conditions active? — NONE (see plan §Stop conditions). Update if any trip.
