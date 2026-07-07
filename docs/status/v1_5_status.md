# WorldForge v1.5 — AssetAcquisitionForge + AssetRealizationForge + VisualEnvironmentForge

**Status: COMPLETE — full shield matrix green, all prior shields non-regressed.**
Branch `worldforge/v1.5-asset-realization`. Date 2026-07-06.

v1.5 turns *validated generated structure* into *validated generated spaces*: real
catalog-backed meshes replace the v1.4x cube cover proxies, every biome gets a
distinct visual environment kit, and every acquired asset proves
license/provenance/ownership/hash through a first-class quarantine gate.

## Shield matrix (canonical, all STRICT)

```
full_shield encounter_loop_world  --strict --deep --torture --missions --encounters
            --playtest-beta --balance --visuals --assets --materialize --meshes  → 129/129
full_shield mission_loop_world     --strict --torture --meshes --missions --playtest --visuals → 69/69
full_shield biome_expansion_world  --strict --torture --meshes                                 → 76/76
full_shield desert_mvp_world       --strict --torture                                          → 33/33
```

Zero fail / zero missing / zero skipped across all four.

## What shipped

- **AssetAcquisitionForge** — gap analysis (26 `AssetNeed` from 120 encounters) →
  procurement manifest → source adapters → **first-class quarantine** (content
  sha256 + license snapshot + fail-closed) → approval → catalog. 17/17 asset gates
  green on real data. 22 negative fixtures + 7 source-torture attacks, all caught.
- **AssetRealizationForge** — 9 `generated_owned` baseline cover meshes (hybrid
  guaranteed floor) + hybrid resolver + 240 `RealizedCoverBinding`s. Live UE:
  **240/240 cover cubes swapped to real meshes, 0 remaining**, across 60 maps.
- **VisualEnvironmentForge** — 5 biome visual kits composed from the v1.3.5 profile
  system, materialized live (incl. weather-Niagara spawn, previously deferred), 5
  inspection screenshots.
- **Integration** — WF350–WF436 failure codes, v1.5 report-identity meta
  (`report_type`/`report_id`/`records_*`), `full_shield` asset+realization+visual-kit
  gate groups with `--assets`/`--materialize` flags, 42 Makefile targets. 54 new
  pipeline scripts + 5 `tools/unreal` drivers.

## Live acquisition proof (this workstation)

- **PolyHaven CC0 — live network download**: 3 assets, 2,955,919 bytes, real content
  hashes + CC0 license snapshots, quarantine-first, then approved + cataloged
  (deterministic).
- **Megascans — live cache scan**: 51 assets read-only from
  `D:\WorldForgeAssetCache\...\FabLibrary`, copy-quarantined (cache never mutated).

## Honest caveats (tracked, not hidden)

- **Hybrid outcome — all 240 cover bindings resolved to the `generated_owned`
  baseline.** Correct behavior: the only cataloged third-party assets are 3 CC0
  terrain/sand materials with no cover-intent/biome match, so the hybrid rule fell
  back to the guaranteed baseline for every cover (never leaving a family uncovered).
  The third-party *upgrade path* is built + validated but not exercised for cover
  until a cover-matched third-party asset is approved.
- **Houdini** remains `metadata_only` (no live cook environment).
- **Manual Fab** acquisition is assisted-only — WorldForge emits shopping lists +
  import plans; it performs no purchase/login/EULA/download.
- **TICKET-001** (headless SceneCapture renders MIC texture-param overrides
  near-white) is unresolved; inspection shots use SceneCapture and the report
  discloses the limitation. Screenshots are evidence, not the product.
- **Weather VFX** spawns `WF_WeatherVFX`; where no biome Niagara system exists yet it
  spawns an honest placeholder (`weather_placeholder:true`).
- **Live runtime player traversal** is NOT in v1.5 — that is v1.6 (PlaytestForge
  Gamma / LiveRuntimeForge). v1.5 prepares the spaces for it.

## UE materialization notes (for future drivers)

- `-ExecutePythonScript` resolves relative paths against the UE **binaries** dir —
  always pass an **absolute** script path.
- Visual/render actors (VolumetricCloud/Niagara/SkyLight) **crash under `-nullrhi`**
  — run kit + capture drivers with a real RHI; asset-only ops (mesh build/swap) are
  fine under `-nullrhi`.
- Live-replacement state lives in the sidecar
  `procedural/reports/realization/ue_replace/<binding_id>.json`; the
  `RealizedCoverBinding` stays schema-clean. `live_materialized` is derived from the
  swap report (0 remaining cubes), so headless resolver re-runs never clobber it.

## Merge readiness

Known-good passes; known-bad fails for its owning code; no validator weakened; no
prior shield regressed; ownership/lifecycle protection proven (third-party/human
never destroyed); acquisition is quarantine-first with license/provenance/hash. The
60 encounter `.umap` files carry real cover meshes + visual kits (modified in-tree).
Ready to commit + open PR on request.
