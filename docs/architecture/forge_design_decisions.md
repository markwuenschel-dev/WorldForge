# Forge Design Decisions (Living Log)

**Status**: Active — updated as decisions are locked during design.
**Scope**: How the "Forge" vision is realized in this repo. Aligns to and refines `procedural_world_architecture.md` (target architecture) without contradicting it.

This is an append-as-we-go decision record. Each entry is a locked decision with its rationale and the alternative rejected.

---

## Work-state labels (used throughout this document)

Earlier revisions used "done", "built", "working" and "green" interchangeably, which let a thing that
had never been executed read as a thing that had been proven. These seven labels are **independent
axes**, not a ladder. State each one you mean; never let one stand in for another.

| Label | Means exactly |
|---|---|
| `implemented` | The code exists and is complete for its stated job. Says nothing about whether it has ever run. |
| `unit-tested` | Exercised by in-repo tests that run **without** Unreal, and they pass. |
| `runtime-qualified` | **Executed inside a live Unreal editor** and produced a machine-written artifact recording what was observed. Prose, a source comment, and a commit message are **not** this. |
| `hostile-qualified` | Survived the adversarial suites — fuzz, torture, known-bads, assembler probes — each failing for its own rail. |
| `shield-integrated` | Wired into `tools/pipeline/v2_6_shield.py` as a named gate, so a regression turns something red. |
| `committed` | Present at HEAD. A working-tree-only file is implemented but not committed. |
| `blocked-by-caller` | Complete on the WorldForge side; the remaining input is caller-originated and WorldForge must not manufacture it. |

**The combination that keeps recurring, and the one to watch for:** a surface can be
`implemented` + `unit-tested` + `hostile-qualified` + `shield-integrated` + `committed` and still
**not** `runtime-qualified`. That is the exact state of the v2.6 fixture smoke (D18). Nothing about
the first five earns the sixth.

---

## D1 — Build order: depth-first, harden MaterialForge first
Finish MaterialForge to **true contract-completeness** (Data Asset + provenance + validation gates) before standing up any new forge.
- **Why**: It's the stated rule ("harden the foundation first"), and the Data-Asset-with-provenance pattern is the template every other forge copies. Shipping the wrong shape propagates to all six forges.
- **Rejected**: breadth-first tracer across all forges.

## D2 — A "Forge" is a logical lane, not a plugin
Material runtime types live in the existing `WorldForgeCore`; build automation stays in `tools/`; editor registration in `WorldForgeEd`; master/content in `CoreTerrainMaterials`. No per-forge plugin.
- **Why**: `WorldForgeCore` exists to be the shared, game-agnostic runtime-contract home; provenance and world-state types are cross-forge. Per-forge plugins multiply UBT/boilerplate for no payoff.
- **Rejected**: one UE plugin per forge.

## D3 — `MaterialRecipeDataAsset` = plain `UDataAsset` (provenance + linkage record)
A `UMaterialRecipeDataAsset : UDataAsset` in `WorldForgeCore`. Hard object refs for now. Fields: `RecipeId`, `SchemaVersion`, `SourceRecipePath`, `ManifestPath`, `GeneratorName`, `GeneratorVersion`, `GeneratedAtUtc`, `SourceCommit`, `bSourceTreeDirty`, `MaterialInstance`, `TextureOutputs` (map), `Parameters` (map).
- **Job**: answer "which recipe/params/commit/manifest produced this MI and these textures?" — for tooling, validation, audit, future world-state integration. **Not** a runtime-queried registry.
- **Upgrade trigger**: promote to `UPrimaryDataAsset` only when a runtime system must discover/enumerate/async-load/bundle recipes by id/type/tag.
- **Rejected**: `UPrimaryDataAsset` now (AssetManager cost is YAGNI).

## D4 — Provenance stamped at manifest generation, flows into the Data Asset
`generate_manifest.py` records `source_commit`, `dirty`, generator name/version, schema version, timestamp, and input hashes into the manifest; the UE step copies them verbatim into the Data Asset.
- **Honesty rules**: dirty working tree is **recorded, never hidden** (`bSourceTreeDirty` / `-dirty` suffix). Validation **rejects** a manifest older than its recipe (stale provenance).
- **Dirty policy**: allow-but-flag by default; `--strict` (CI/agent) hard-fails on dirty.
- **Rejected**: stamping at the UE step (duplicates git logic, leaves manifest provenance-less).

## D5 — Dedicated `create_data_asset.py` step
New single-purpose UE script, run after `create-material`. Manifest owns the output path (`ue.data_asset_path`, e.g. `/Game/WorldForge/Materials/DA_Terrain_Rock_Desert_01`). It reads the manifest, loads the MI + textures, creates/updates the Data Asset, copies provenance verbatim, saves, emits JSON. It does **not** create/mutate the MI or textures.
- **Why**: preserves one-job-per-script; provenance can be regenerated/repaired without touching the MI.
- **Pipeline order**: validate-recipe → generate-manifest → import-textures → create-material → create-data-asset → validate-assets.

## D6 — Validation: Python now, native `UEditorValidatorBase` deferred
Keep Python / UE-Python validators for v1; add native `UEditorValidatorBase` later (when rules are stable and Content-Browser/Data-Validation integration is wanted). Validation taxonomy:
- **Tier 1** — recipe/manifest (contract + provenance + staleness + naming).
- **Tier 2** — master-material (shader/sampler/permutation budget; human-owned `M_Terrain_Master`).
- **Tier 3** — generated-asset correctness (texture limits ≤2048 + sRGB + compression + mips + group; reference integrity; provenance copied; naming).
- **Key insight**: Material Instances inherit the master's shader cost, so heavy material-stat budgets belong to Tier 2 (master), not per-recipe.

## D-EDIT — Agents drive the editor directly; ownership/provenance protects human-authored assets
Agents materialize generated assets by driving the Unreal editor directly. There is no deferral to a separate manual editor step. What still protects hand-authored work is the **ownership/provenance model**, not an agent gate.
- **CI contract checks (GitHub, no UE)** — text-contract: `validate_recipe.py`, `generate_manifest.py`, negative fixtures, manifest JSON validity, "no YAML in `tools/unreal/`", Makefile `-n` sanity, provenance/staleness. CODEOWNERS requests code-owner review on binary/authoring assets.
- **Ownership/provenance** — human-authored master sources (`.uasset` / `.umap` / `.sbs`, `Source/WorldForge*`, master materials) stay owner-owned and are protected from repair/destroy by provenance ownership tags. Generated assets are agent-owned and freely rebuilt.
- **UE-requiring checks** run locally / on a self-hosted UE runner, **not** in hosted CI (don't make hosted CI run Unreal: perfect gate → no gate).
- **New files**: `.github/CODEOWNERS`, `.github/workflows/worldforge_contracts.yml`, `tests/fixtures/invalid_recipes/`, `tools/pipeline/test_negative_recipes.py`.

## D8 — MaterialForge v1 done-line
- **In**: `create_data_asset.py` + `UMaterialRecipeDataAsset`; provenance + input-hash + staleness guard; `validate_assets.py` extended to full Tier-3; Tier 0 + Tier 1 CI; docs updated.
- **Deferred (tracked)**: preview render (keep `make preview` failing-by-design), Tier-2 master-material validator, native `UEditorValidatorBase`, self-hosted UE CI.

## D9 — After MaterialForge: thin StateForge spine next
Not the full state system — a minimal `WorldStateSubsystem` + the state-consumption contract (`FWorldForgeStateContract` already started) + **one** proven end-to-end reaction (e.g. region `industrial_pressure` → soot param on the terrain MI via an MPC). Then PlacementForge becomes the second state-aware consumer.
- **Why**: world state is the vision's centerpiece; building all content forges blind to state and retrofitting is the real failure mode. A thin tracer spine ≠ the premature state monolith `adaptive_world_state_system.md` warns against.
- **Rejected**: state strictly last (A/C) — risks four content forges with no state hooks.

## D10 — State read contract: CPU pull-query (source of truth) + MPC render mirror
- **Canonical API** (the thing all forges bind to): `float GetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Default = 0.f) const`.
- **Address** = `Scope + ContextId + Key`, float-valued. `ContextId` by scope: Global → `NAME_None`, Region → RegionId, Local → InfluenceFieldId, Settlement → SettlementId.
- **CPU consumers** (PlacementForge, enemies, economy, quests, factions, settlements, encounters) pull from the subsystem; they **never** read the MPC.
- **Materials** read a curated `MPC_WorldState` mirror, pushed on change — render-facing values only (IndustrialPressure, CorruptionLevel, RestorationLevel, Wetness, Ashfall, FactionTint). Gameplay-scale state stays in the subsystem.
- **Rule**: Pull API = source of truth; MPC = render-only projection.

## D11 — State write contract: authoritative setter now; accumulation + persistence deferred
- **Now**: `void SetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Value)` — the authoritative primitive; a debug console command drives the tracer. In-memory store only.
- **Deferred (layer on top, all resolve *into* `SetStateValue`)**: `AddInfluence(...)`, influence-source tracking, falloff fields, aggregation rules, save/load persistence, region simulation, settlement emitters.
- **One required Tier-2 human edit**: `M_Terrain_Master` samples `MPC_WorldState.IndustrialPressure` to drive a soot/industrial overlay lerp (no MPC sample → no visible reaction; an agent can't do this and it can't be deferred).
- **Acceptance tracer**: `SetStateValue(Region, Desert_Valley_01, industrial_pressure, 0.75)` → subsystem updates `MPC_WorldState.IndustrialPressure` → terrain soot param visibly changes.

## D12 — MeshForge: mirror MaterialForge, Blender first, sequenced after PlacementForge
- **Pattern**: same contract shape — human-owned procedural graph (Blender GN / Houdini HDA) → agent recipe YAML → headless generation → mesh export → UE import → `StaticMesh` + provenance Data Asset → validation. "MaterialForge with meshes."
- **Tool**: Blender Geometry Nodes first (free, scriptable, headless, CI-friendly). Houdini = optional later backend, not a v1 dependency.
- **Why deferred**: mesh import is the heaviest problem (LODs, collision, Nanite, UVs, scale, pivots, material slots). PlacementForge needs *usable* meshes, not *generated* ones.
- **Spine-doc addition**: "External DCC forges follow the same recipe→manifest→import→DataAsset→validate contract as MaterialForge. Blender is the first MeshForge backend; Houdini is optional later."

## D13 — PlacementForge: state-aware PCG via pull
- Human-owned PCG graph = master template; agent-edited spawn-rule YAML (`FoliageSpawnRules.yaml`) = variation surface → generated `PlacementRulesDataAsset` the graph reads.
- The PCG graph reads rules from the Data Asset **and** pulls live state per-cell via `WorldStateSubsystem.GetStateValue` (density/species modulated by region values) — the **second state-aware consumer** after MaterialForge's MPC tracer.
- Same recipe→manifest→DataAsset→validate contract. **Do not** bake state into the Data Asset (kills runtime reactivity).

## D14 — ValidationForge is not a forge
It's the cross-cutting QA substrate every forge plugs into — Tier 0 (repo permissions), Tier 1 (text/contract), Tier 2 (master asset), Tier 3 (generated asset) — not a sequenced content lane.

## D15 — Repo structure: functional layout, "Forge" as vocabulary
Keep `tools/{substance,pipeline,unreal}` and `procedural/{manifests,reports,…}`. Add the contract-referenced `procedural/definitions/`. No forge-centric folder rename — "Forge" is a logical lane (per D2), not repo structure.

## D16 — Converge to build; grill later forges just-in-time
Stop up-front grilling of Terrain/POI/full-State. Build Milestone 1; grill remaining forges when their turn comes.

## D17 — PlacementForge v1: mirror MaterialForge, make the Data Asset runtime-read
Built the agent-operability + data spine of PlacementForge by copying the proven
contract: `definition → validate_placement → generate_placement_manifest →
create_placement_data_asset → validate_placement_assets`, with Tier-0/1 CI gates and
negative fixtures. FoliageSpawnRules live in `procedural/definitions/placement/`.
- **Key shape difference from MaterialForge**: `UPlacementRulesDataAsset` is NOT
  provenance-only. It carries a **runtime-read payload** (`Species[]`: mesh, density,
  scale, state-response endpoints) that the PCG graph consumes, *plus* the same
  provenance block. `UMaterialRecipeDataAsset` only links + records provenance.
- **State stays live (D13)**: only the density *response* (`density_at_state_zero/one`)
  is baked. The PCG graph pulls the live value via `WorldStateSubsystem.GetStateValue`
  per cell and lerps. Baking a resolved state value is forbidden by the contract.
- **No new C++ read node needed**: `GetStateValue` is already `BlueprintCallable`/
  `BlueprintPure`, so the PCG graph binds to it directly — the pull API is the seam (D10).
- **Agent-safe surface**: `state_key` is whitelisted to the curated keys + `none`;
  density/scale/species-count budgets are hard-enforced in Tier 1 and re-checked in Tier 3.
- **Shared provenance**: factored `tools/pipeline/provenance.py`; `generate_manifest.py`
  now uses it too (verified byte-identical output, modulo timestamp). Manifest paths
  normalized to POSIX `/` for cross-OS-stable hashing and git-friendliness.
- **One required human Tier-2 edit** (mirrors D11's `M_Terrain_Master` soot edit): author
  the PCG graph `/Game/Procedural/PCG/PCG_FoliageScatter` so it (a) reads `Species[]`
  from `DA_*`, and (b) per cell calls `GetStateValue(state_scope, region, state_key)` and
  modulates density. An agent can't author the `.uasset` graph; it can't be deferred — no
  graph → no scatter. The data spine + contract make that edit small and well-specified.
- **Deferred (tracked)**: the PCG graph `.uasset` itself; resolving a cell→RegionId
  context mapping; Tier-3 mesh-reference integrity is a warning (meshes live in the game
  project, not this tooling repo); multi-biome rulesets beyond the example.

## D18 — Support-grid collector stays in Python until measurement says otherwise
The per-cell support-grid collector is **deferred from C++** until the v2.6 queue is
finished in Python and the controlled fixture UE smoke has run.
- **Why**: authoring it now would stand up a second implementation before the existing Python
  evidence chain has survived one real engine execution. A bad result could then originate in
  Unreal API assumptions, transport, evidence assembly, grid mathematics, *or* the new C++ — five
  candidate sources instead of four. The fixture smoke collapses that uncertainty first.
- **Rejected**: "C++ looks more production." Not a promotion criterion. Neither is the fact that
  `SampleSurveySupport` already builds a full grid internally — it does, in two nested passes over
  `[-K, K]²` with per-cell `TMap<int64,…>` state (`Cls`, `GridZ`), and then discards the grid and
  returns a bare total
  (`USceneSurveyStatics::SampleSurveySupport`,
  `Plugins/WorldForge/Source/WorldForgeCore/Private/SceneSurvey.cpp`).

**State of the code as observed 2026-07-30, re-verified at reconciliation against HEAD `89f97f8a`.**
The eight files that were being edited concurrently during the 11:04–11:16Z pass
(`SceneSurvey.{h,cpp}`, `run_scene_survey_probe.py`, `run_v2_6_fixture_smoke.py`,
`scene_survey_evidence.py`, `scene_survey_recompute.py`, `validate_scene_survey_runtime.py`,
`scene_survey_far_side.py`) are now **`committed` and clean in the working tree**
(`git status --porcelain` names none of them). Line citations below were re-taken against the
committed file and are good as of `89f97f8a`; if that lane reopens, re-verify before relying on
them.
- *"Stays in Python"* describes the intended destination, **not a collector that exists today.**
  There is no per-cell Python collector. The far side makes one aggregate call and receives one
  integer — `doc["support_total"] = int(stat.sample_survey_support(world, ctr, RADIUS, STEP))`
  (the sole `sample_survey_support` call in `tools/bridge/scene_survey_far_side.py`); a repo-wide
  search of `tools/` for `support_grid` / `collect_support` found no per-cell loop.
- A canonical Python **derivation** module, `tools/pipeline/support_grid_canonical.py`, appeared
  during this session and is now **`committed` and clean at 900 lines** (an earlier revision of this
  bullet said "645 lines, currently untracked" — both numbers were true when written and are now
  stale). It carries `grid_extent_k`, `sample_points`, `classify_support`, `derive_edges`,
  `derive_grid`, and since the tolerance/identity closure also `derive_tau_n_deg`, `sample_id`,
  `parse_sample_id`. It is the language-independent mathematics, not the raw collector.

- **The fixture smoke: `implemented`, not `runtime-qualified`.** An earlier revision of this bullet
  said `procedural/reports/scene_survey/fixture_smoke/` "does not exist". **That is stale and
  wrong** — the directory exists and holds artifacts. What follows is the corrected account, split
  along the labels above because the two halves have opposite answers:

  * **`implemented` — yes, and completely.** `tools/pipeline/run_v2_6_fixture_smoke.py` declares
    **21 probes**, and every required geometry surface has a real call site in it, not a stub:
    `line_trace_single` (`:1506`), `break_hit_result` / `hit_result_decomposition` (`:237`),
    `capsule_overlap_actors` (`:242`), `capsule_overlap_components` (`:246`), and all three
    `USceneSurveyStatics` primitives — `enumerate_survey_actors` (`:1420`),
    `sample_survey_support` (`:1442`), `probe_temp_marker` (`:1469`).
  * **`runtime-qualified` — no. It has NEVER produced live evidence.** Every artifact under
    `procedural/reports/scene_survey/fixture_smoke/` is a **`.norun`** report. The canonical
    `v2_6_fixture_smoke_report.json` **does not exist**; the harness itself records why, in
    `canonical_report_note`: *"this run did NOT produce live evidence, so it was written to
    `v2_6_fixture_smoke_report.norun.json` and the canonical report … was left untouched."*
    In the latest attempt (`generated_at` `2026-07-30T20:04:33Z`, run nonce `52fa2026f59d…`):
    `runtime_executed: false`, `gate_green: false`, `report_kind:
    "editor_boot_produced_no_observations"`, `editor_exit_code: 1`, `elapsed_seconds: 6.37`, and the
    probe tally is **`runtime_verified: 0`, `runtime_unavailable: 21`** — all 21 probes are in
    `unmet_required_probes`.
  * **Two live attempts, one root cause, and it is not the harness.** Both editor boots died the
    same way. The project and plugin module manifests
    (`Binaries/Win64/UnrealEditor.modules` and `Plugins/WorldForge/Binaries/Win64/UnrealEditor.modules`)
    carry `"BuildId": "47537391"` while the installed engine is `55116800`. Unreal skips every
    mismatched module — `LogModuleManager: Skipping out-of-date modules in manifest '…' (BuildId
    47537391 != 55116800)` — the game module is then not found (*"The game module 'WorldForge' could
    not be found. Please ensure that this module exists and that it is compiled."*), and the editor
    exits **before Python ever runs**. Preserved verbatim under
    `procedural/reports/scene_survey/fixture_smoke/diagnostic/`
    (`WorldForge.editor.2026-07-30T112136Z.log`, `WorldForge.editor.attempt2.195813Z.log`, plus the
    matching `.norun` reports).
  * **The fix is a rebuild, and the rebuild is BLOCKED.** UnrealBuildTool refuses while a Live
    Coding session is alive under a separate editor process: *"Unable to build while Live Coding is
    active. Exit the editor and game, or press Ctrl+Alt+F11…"*, `Result: Failed
    (OtherCompilationError)`, exit code 6. Recorded at
    `procedural/reports/build/wf_build_proof.json` with the build log beside it. **This is the whole
    of what stands between `implemented` and `runtime-qualified`.**
  * Consequently the narrower "live `-nullrhi` boot verified 2026-07-27" claim that circulates
    elsewhere still rests entirely on prose — a `RUNTIME FINDING` source comment in the harness, and
    commit `6e629e68`'s message. **No machine-written artifact corroborates it.** Every
    geometry/trace symbol listed above therefore remains **ASSUMED**, which the far side says of
    itself in the "ASSUMED and labelled as such at each call site" block of
    `tools/bridge/scene_survey_far_side.py`.
- *"the six-step v2.6 queue"* (D19 step 1; this entry's opening line has been changed to say just
  "the v2.6 queue") — the phrase occurred **only in this document**, and the six steps are **not
  enumerated anywhere in the repo**. D19's own "Locked sequence" below lists five items, the first
  of which *is* this queue. Treat the numeral as unverified until the queue is written down
  somewhere machine-readable.
- **Not indefinite.** Cost model — for radius `R` and grid spacing `s`, the nominal square-grid
  sample count and approximate collection time are:

  ```
  k = floor(R / s)
  N = (2k + 1)^2
  T_grid = N * (T_trace + T_interop + T_record)
  ```

  `k = floor(R / s)` **matches the C++, and that change is now `committed`** —
  `const int32 K = FMath::FloorToInt(RadiusCm / StepCm);` at
  `Plugins/WorldForge/Source/WorldForgeCore/Private/SceneSurvey.cpp:103`, the grid-extent line in
  `USceneSurveyStatics::SampleSurveySupport`, verified at HEAD `89f97f8a` with the file clean in the
  working tree. An earlier revision of this bullet carried two caveats that are **both now stale and
  have been removed**: it said the change was "uncommitted — the file is modified-unstaged", and it
  named HEAD as `bd8dfa32` where the expression was still `FMath::Max(1, (int32)(RadiusCm / StepCm))`.
  The historical point survives the correction and is worth keeping: `max(1, floor(R/s))` disagrees
  with this cost model exactly when `R < s` (`k=0`, one centre sample, versus a 3×3 block reaching
  ±s **outside** the requested half-extent), which is why the change was made.

- **Promotion criteria — move the collector to C++ when the fixture smoke demonstrates at least
  one of these.** Each is a measurement, not an opinion:
  1. Unreal Python cannot expose the required trace, collision, package, or component data reliably.
  2. Python↔Unreal interop overhead materially dominates trace execution (`T_interop` >> `T_trace`).
  3. The maximum supported `(R, s)` combination cannot meet a declared runtime budget.
  4. Python collection produces nondeterministic ordering or incomplete raw records that cannot be
     corrected cleanly.
  5. Cleanup or world-lifetime correctness requires native scoped ownership.
  6. A native batch trace materially reduces cost while preserving identical semantics.

- **Measured state of the six criteria: ALL SIX ARE `not_measured`. The promotion decision is
  OPEN on every one of them.** No live run has occurred (see the fixture-smoke bullet above), so
  there is nothing to read. The harness's own vocabulary is explicit that this is never a default:
  *"`not_measured`: not answered by this run — the promotion decision stays OPEN on this criterion.
  NEVER a default; always carries a reason."*

  **Two of the six were emitted with a non-`not_measured` verdict by a run that collected zero
  usable points. Treat both as a SUSPECTED HARNESS DEFECT UNDER REVIEW, not as measurements:**

  | Criterion | Verdict as emitted | Why it cannot be a measurement |
  |---|---|---|
  | `c1_python_cannot_expose_data` | `measured_fail` | Its reason reads *"all 17 data-exposure probes returned usable trace, collision, package and component data"* — but the same report's tally is `runtime_verified: 0, runtime_unavailable: 21`. **No probe returned anything.** The verdict was derived from an empty verified-set read as a satisfied one. |
  | `c5_cleanup_needs_native_ownership` | `measured_pass` | Every input in its evidence block is `null` (`dirty_content_pre/post`, `dirty_maps_pre/post`, `spawn_probe_status`, `target_map_dirty_after`), and its own reason says *"Python-side cleanup could not be re-observed as correct (spawn/destroy probe is None)"*. An unobserved cleanup was scored as a met promotion trigger — the fail-open direction. |

  The remaining four (`c2`, `c3`, `c4`, `c6`) each carry an honest `not_measured` with a reason
  naming the missing input. **Nothing in this document should be read as saying the collector has
  earned promotion to C++, or has been cleared of it. It has been neither.**

- **The support mathematics is language-independent.** Python and any later C++ implementation
  share one contract for sample coordinates, support classification, edge detection, tolerances,
  and canonical ordering. See `docs/contracts/v2_6_support_grid_contract.md`.
  - Both remaining declaration gaps in that contract are now **closed**: `τ_n` is declared **by
    derivation** as `derive_tau_n_deg(θ_max) = TAU_N_MULTIPLIER * θ_max` with `TAU_N_MULTIPLIER =
    1.0`, giving **`τ_n = 44.0°`** from `θ_max = 44°` (§5.2.1–5.2.2); and **canonical sample
    identity** is specified (§1.4) as
    `sample_id = version | shape | "k=" k | "i=" ±i | "j=" ±j`, built only from canonical grid
    coordinates and declared names.
  - **`θ_max = 44°` is the value the shipping C++ actually uses** —
    `const float MaxSlope = 44.f, MaxStepH = 45.f;` at `SceneSurvey.cpp:90`, flagged in-source as a
    contract value. So the derivation is anchored on the live constant, not on a paper one.
  - **The shipping C++ cannot implement the `τ_n` normal term, and this is a structural limit, not
    an omission.** Pass 1 stores only the impact height —
    `GridZ.Add(GridKey(ix, iy), (float)H.ImpactPoint.Z);` at `SceneSurvey.cpp:140` — and discards
    `H.ImpactNormal` after using it for the slope test. **Pass 2 therefore has no per-cell normal to
    compare**, so a normal-discontinuity edge is unreachable in native code without new per-cell
    normal retention. The contract records this as its `[HANDOFF]` (§5.2.6) and pins it with an
    XFAIL golden. **This is a genuine input to the promotion decision** — a C++ collector is not a
    like-for-like port until it retains normals.
- **A C++ collector would emit raw observations only.** It must never become a second authority
  for report truth — that would reintroduce the verdict-emitting far side the evidence model
  exists to forbid (raw → assembler derives → validator re-derives independently).

## D19 — The engine substrate is the next milestone after v2.6, before any new Forge capability
Once v2.6 closes on real runtime evidence, the next milestone is **engine consumption** — moving
the stable execution-facing kernel into the plugin. It is not v3.0 and it is not another
data-contract system.
- **Locked sequence** (state of each step at reconciliation, in the labels above):
  1. Complete the six-step v2.6 queue (Python). — *`implemented` / `unit-tested` /
     `hostile-qualified` / `shield-integrated` / `committed`.*
  2. Pass the controlled fixture UE smoke. — **NOT reached. `implemented` but not
     `runtime-qualified`;** blocked on the BuildId mismatch plus the Live Coding build lock (D18).
  3. Receive and execute the caller-originated Gloamstead request. — `blocked-by-caller`, by
     design. WorldForge must not author this request for itself (D20).
  4. Close v2.6 with real runtime evidence.
  5. Begin the engine-consumption milestone — before naming v3.0 or stacking further
     data-contract systems.
- **Why now and not later**: every additional Forge capability added before the crossing exists
  widens the surface that will have to cross it, and each one is built against a boundary that has
  never been executed natively.
- **Milestone responsibilities** — it establishes the permanent crossing, it does not add a demo:
  a real `WorldForgeCore` runtime capability registry — **none exists today**: `WorldForgeCore` is
  eleven source files carrying `UMaterialRecipeDataAsset`, `UPlacementRulesDataAsset`,
  `UWorldStateSubsystem` and `USceneSurveyStatics`, and the only `Register*` call in the whole
  plugin is `IConsoleManager::Get().RegisterConsoleCommand(` at
  `Plugins/WorldForge/Source/WorldForgeCore/Private/WorldStateSubsystem.cpp:31` (verified
  2026-07-30); a real `WorldForgeEd` editor/operator entry
  point — the module is currently **empty boilerplate**: `StartupModule`/`ShutdownModule` contain
  only intent comments ("Register procedural-material / manifest / import tooling here"),
  `WorldForgeEd.cpp:7-15`, and the module is three files total under `Source/`
  (`Private/WorldForgeEd.cpp`, `Public/WorldForgeEd.h`, `WorldForgeEd.Build.cs`; the further
  `WorldForgeEd` paths under `Intermediate/Build/` are build output, not module source);
  version-negotiated request and evidence contracts; native
  operation lifecycle and cancellation boundaries; typed capability discovery; operation-scoped
  temporary-object ownership; raw evidence emission from engine code; durable failure propagation
  back to the operator layer; compatibility checks between generated Python contracts and native
  structs; and **one production consumer** proving the engine consumes WorldForge output without
  bespoke glue.
- **The boundary stays**:

  ```
  target intent -> versioned WorldForge request -> native capability execution
                -> raw observations -> independent evidence derivation -> validated result
  ```

- **Scope discipline — promote the kernel, not the corpus.** The plugin must NOT ingest the
  accumulated contract corpus wholesale, nor duplicate its Python implementation. (An earlier
  draft said "twenty-two generations of contracts"; that number is unsupported and has been
  removed. The verifiable count as of 2026-07-30 is **fifteen** files in `docs/contracts/`, of
  which nine carry a version token — `v0_9, v1_0, v1_8, v1_9, v2_0, v2_2, v2_3, v2_4, v2_6` —
  and there is no contracts index in the repo to count "generations" from.)
  Promote only: capability identity; request version and operation identity; engine-side inputs;
  lifecycle; raw observations; mutation ownership; failure codes.
- **Stays external** unless measurement justifies moving it: orchestration, report assembly,
  adversarial validation, cross-version compatibility, higher-order evidence analysis.
- **Consistent with D2** — this is not a per-forge plugin. It is the single shared runtime
  contract home `WorldForgeCore` was created to be.

## D20 — A gate's red must name *which* red it is: a wiring defect is never the caller rail
`validate-scene-survey-runtime` is the single red in the v2.6 shield, and **two completely
different situations were rendering as that same red**. One was a **defect in us**; the other is the
**intentional boundary this whole milestone is waiting on**. Collapsing them meant the gate's colour
carried no information, and — worse — meant a bug in our own command line could be mistaken for
correct principled behaviour and left in place. **The taxonomy below is locked.**

| | (a) VALIDATOR WIRING DEFECT | (b) ABSENT CALLER-ORIGINATED ACCEPTANCE EVIDENCE |
|---|---|---|
| Code | `WF1128_SCENE_SURVEY_OPERATION_ID_MISMATCH` | `WF1097_SCENE_SURVEY_EVIDENCE_MISSING` |
| Rail | `input::operation_id_resolved` | `input::caller_evidence_present` |
| What actually happened | The shield invoked the validator **without `--operation-id`**, so no source produced an operation id at all. The gate could not name what it was grading. | The gate knows **exactly** which operation it would grade, and no runtime artifact for that operation exists yet. |
| What it means | **A BUG. Ours.** A missing argument was masquerading as absent caller evidence — the gate looked principled while being merely misconfigured. | **CORRECT AND INTENTIONAL.** No caller has run a survey. There is no runtime truth to validate. |
| How it is fixed | *"Fixed by editing a command line."* | *"Fixed by booting an editor, not by editing a command line."* |
| Status | **FIXED.** `tools/pipeline/v2_6_shield.py:45` declares `RUNTIME_OPERATION_ID = "op_v2_6_scene_survey_0001"` and `:110-111` passes it explicitly as `--operation-id`. | **STILL RED, and it should be.** This is the gate the caller's survey is meant to turn green. |

A **third** case exists and must not be folded into either: `input::operation_id_unambiguous` /
`WF1129_SCENE_SURVEY_CONCURRENT_OPERATION` — **AMBIGUITY**, more than one candidate operation was
offered. The gate refuses to choose, because *"picking one silently is how a run grades the wrong
operation and nobody finds out."*

- **Exactly one of the three can block on any given run**, by construction: the evidence rail is
  skipped when no id resolved, and the two resolution rails are mutually exclusive
  (`tools/pipeline/validate_scene_survey_runtime.py:37-53`, `resolve_operation_id`).
- **The rule this generalizes to, and the reason it is a locked decision:** *a red that cannot say
  which of its causes fired is not a gate, it is a mood.* Any fail-closed rail that can fire for
  both "we are misconfigured" and "the world has not happened yet" MUST split those into distinct
  codes with distinct rails before it is trusted. The failure mode is not the red — it is the red
  that flatters a defect by making it look like principle.
- **Do not soften (b) into a caveat.** It is not "expected noise" and not "a known limitation". It
  is an outstanding, load-bearing RED: WorldForge has never been handed a caller-originated survey.
  It closes when a caller runs one, and by nothing else. See D19 step 3.

---

## Roadmap (locked order)

> The ✅ / ⏳ markers below **predate the work-state labels** at the top of this document and have
> **not** been re-audited against them. Read them as milestone bookkeeping, not as label claims —
> in particular, ✅ here does **not** assert `runtime-qualified`. Only D18/D19/D20 carry labelled
> state that has been checked.

1. **MaterialForge v1** — contract-complete (D1–D8). ✅ **Done**.
2. **Thin StateForge spine** — subsystem + read/write contract + one tracer reaction (D9–D11). ✅ **Done**.
3. **PlacementForge** — PCG placement driven by state, on placeholder/marketplace meshes (D13, D17).
   ✅ **Data spine + contract + Tier-0/1 gates done**. ⏳ Remaining: the human-owned PCG graph (Tier 2).
4. **MeshForge** — Blender GN, reusing the proven pattern (D12).
5. **TerrainForge / POIForge** — later.
- Cross-cutting throughout: validation/provenance/ownership (D6, D-EDIT). Full StateForge (accumulation, persistence, emitters) layers on after the spine.

---

## Implementation Plan

**Milestone 1 — MaterialForge v1 (build first)** — refs D3–D8
1. `UMaterialRecipeDataAsset : UDataAsset` in `WorldForgeCore`.
2. Provenance in `generate_manifest.py`: `source_commit` + `dirty` + timestamp + generator name/version + schema + input hash; staleness guard; `--strict` for CI.
3. `create_data_asset.py` (new step); manifest gains `ue.data_asset_path`.
4. `validate_assets.py` → full Tier-3 (texture budgets, reference integrity, Data Asset linkage + provenance match, naming).
5. Preview deferred (keep `make preview` failing-by-design).

**Milestone 2 — CI contract gates** — refs D-EDIT
- `.github/CODEOWNERS`, `.github/workflows/worldforge_contracts.yml`, `tests/fixtures/invalid_recipes/` + `tools/pipeline/test_negative_recipes.py`. Text-contract checks enforced in GitHub CI (no UE).

**Milestone 3 — Thin StateForge spine** — refs D9–D11
- `WorldStateSubsystem` (`UWorldSubsystem`, `WorldForgeCore`): `GetStateValue` / `SetStateValue`, `MPC_WorldState` push bridge, Tier-2 edit to `M_Terrain_Master` (sample `IndustrialPressure`), `industrial_pressure → soot` tracer + debug command.

**Milestone 4 — PlacementForge** — refs D13
- Human-owned PCG graph; agent spawn-rule YAML → `PlacementRulesDataAsset`; PCG pulls live state per-cell.

---

### Cross-references to update when implemented
- `material_recipe_contract.md` — add the "MaterialRecipeDataAsset is a provenance/linkage `UDataAsset`, not a runtime registry" clause + upgrade trigger.
- `performance_budgets.md` — note the Tier-1/2/3 split and that per-recipe validation excludes shader-cost budgets.
