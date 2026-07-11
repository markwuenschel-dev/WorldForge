# WorldForge v2.3 — StreamingForge / WorldScaleForge Contract

Status: **Wave 1 (contracts + fail-closed shield) — in progress**
Branch: `worldforge/v2.3-streamingforge`
Failure-code band: **WF851–WF930** (`STREAMING_*`), WF895–930 reserved.

v2.3 adds the first **cross-tile generated-region substrate** for WorldForge. It is
**not** a full open world, multiplayer streaming, or a final World Partition
implementation. It proves generated content can span streamed tiles without breaking
anchors, traversal, missions, NPCs, combat, quest/faction state, save/load, package
budgets, or operator evidence.

## Core design principle (handoff §5)

A streamed region is a validated **graph** of generated tiles connected by stable
cross-tile **anchors** + **routes**, with bounded runtime lifecycle, cross-tile
save/load continuity, and inspectable evidence. Every tile boundary must be
explainable; every cross-tile claim must have proof.

## Scenario scope (handoff §3)

```
2 generated regions (hub_spoke + linear_chain, 3 tiles each)
  × 3 mission archetypes (survey_landmark / recover_resource / clear_hazard)
  × 2 streaming profiles (adjacent_tile_crossing / hub_to_spoke_transition)
  × 2 seeds
= 24 streaming scenarios
```

Bounded: 3–5 tiles per region, no new 120 matrix, no open-world grid.

## Contracts (`tools/pipeline/streaming_contracts.py`) — 13, schema-only

| # | Contract | Code | Key honesty invariant |
|---|----------|------|-----------------------|
| 1 | RegionDefinition | WF851 | entry/exit ∈ tile_ids; 3–5 tiles; known layout/profile |
| 2 | StreamingTileDefinition | WF852 | finite bounds; no self-neighbor; known role/policies |
| 3 | CrossTileAnchor | WF855 | finite location; boundary anchors link ≥1 partner; type compatible with tile role |
| 4 | CrossTileRoute | WF857 | ≥2 distinct tiles; transition point per boundary; **no navmesh overclaim** (pass ⇒ proved grounded WorldForge mode); failed ⇒ not pass |
| 5 | StreamedMissionBinding | WF861 | ≥2 required tiles; machine-checkable runtime claims; required routes |
| 6 | StreamedNPCBinding | WF862 | perception/pressure/combat scope ⊆ allowed tiles (no pressure in unloaded tile) |
| 7 | StreamingBudgetProfile | WF863 | all maxes > 0; max_loaded_tiles ≥ 1 |
| 8 | TileLifecycleReport | WF864 | active ⇒ load_completed; reload ⇒ state_preserved; clean ⇒ loaded + budget not exceeded |
| 9 | StreamingRuntimeReport | WF883 | clean ⇒ ≥2 tiles + ≥1 transition + ≥1 route + ≥1 anchor + mission_completed + roundtrip_ok + budget ok; **no full_ue_streaming overclaim** |
| 10 | CrossTileSaveState | WF870 | roundtrip_ok ⇒ tile_state_hash for every loaded tile |
| 11 | StreamingEvidenceIndex | WF884 | pass ⇒ 24/24 seen + empty missing/stale + real sha |
| 12 | OperatorRegionView | WF885 | non-empty scenarios; real definition path |
| 13 | OperatorTileView | WF885 | passing ⇒ links ≥1 lifecycle report |

### Truth guards (handoff §5/§8.4/§12)

* **Navmesh overclaim** (WF882): `grounded_navmesh` is a headless `path_missing`
  limit — it may never be a proved objective-access mode. Only
  `grounded_worldforge_route` / `grounded_manual_waypoint` prove access.
* **Runtime mode honesty** (WF882): the alpha must label itself
  `simulated_streaming_lifecycle` or `process_isolated_tile_sequence`, never
  `full_ue_streaming` unless native UE streaming is actually proved.

## Shield (`tools/pipeline/v2_3_shield.py`)

Fail-closed. Spine-only (`--strict`) is GREEN from Wave 1; the full surface
(`--streaming --worldscale`) is honestly RED until Waves 2/3/4/5/R build their
scripts.

```
python tools/pipeline/v2_3_shield.py --strict                        # spine → GREEN
python tools/pipeline/v2_3_shield.py --strict --streaming --worldscale  # full → RED until built
```

## Output roots

```
procedural/generated/regions|tiles|anchors|routes|streaming/**
procedural/reports/streaming/{runtime,lifecycle,save_load,budgets}/**
procedural/reports/operator/regions|tiles/**
```

v2.0/v2.1/v2.2 evidence is referenced, never rewritten in place.
