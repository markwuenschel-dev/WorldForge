# WorldForge Core — consumer-driven platform run state

Durable execution state for the "game-agnostic world-generation and world-authoring
platform" build. Update this file as milestones move; it is the handoff of record.

**Started:** 2026-08-05 · **Branch:** `main` · **Engine:** UE 5.8 (`D:\UE_5.8`, BuildId `55116800`)

---

## The flow being built

```
consumer profile + world request
  -> desired-world model -> observed-world model -> constraint analysis
  -> typed generation/revision plan -> provider selection
  -> bounded transactional world delta -> Unreal authoring
  -> save/reload/runtime validation -> acceptance evaluation
  -> evidence-driven repair -> accepted playable result
```

Ownership boundary (unchanged, load-bearing): **the importing game owns intent**;
WorldForge owns capability, observation, planning, authoring, validation, evidence,
and repair. Core must never fabricate caller provenance or invent a subject.

---

## M0 — live Unreal execution [DONE, verified 2026-08-05]

**Root cause of the long-standing blocker was NOT what the prior handoff recorded.**
The prior note attributed it to a Live Coding lock only the operator could clear.
Actually measured:

- Project binaries carried BuildId `47537391`, which is **UE 5.7**
  (`C:\Program Files\Epic Games\UE_5.7` and `D:\UE_5.7` both report it).
- `WorldForge.uproject` declares EngineAssociation `5.8` -> `D:\UE_5.8`, BuildId `55116800`.
- Mismatch -> loader skipped every project and plugin module.
- No editor and no Live Coding process was running when this was diagnosed; that lock
  was gone. The blocker was a stale-engine build, not a lock.

Two further defects surfaced during the rebuild, both **duplicate/stale plugins**:

| Plugin | Problem | Resolution (reversible, nothing deleted) |
|---|---|---|
| `NeoStackAI` | Two plugins share the name: project-local v3.0.3 (missing its `ThirdParty/Lua` + `sol2` headers) and engine marketplace v2.0.45 (complete). UBT selected the engine descriptor but the project's module rules -> unbuildable. | Renamed `Plugins/NeoStackAI/NeoStackAI.uplugin` -> `.uplugin.disabled`. Engine copy is now the sole `NeoStackAI`. Reverse by renaming back. |
| `UELLMToolkit` | `EngineVersion 5.6.0`; uses APIs changed in 5.8 (`IKRetargetBatchOperation::DuplicateAndRetarget` signature, moved `RigVMModel/RigVMVariableDescription.h`). Untracked in git, **not referenced by the .uproject** — built only via `EnabledByDefault`. | Renamed `UELLMToolkit.uplugin` -> `.uplugin.disabled`. Reverse by renaming back. |

Note: `.ubtignore` does NOT hide a plugin from discovery — it governs source-file
search and UHT only (`UE_5.8/Engine/Source/Programs/UnrealBuildTool/System/SourceFileSearch.cs:154`,
`FileMetadataPrefetch.cs:173`). Renaming the descriptor is the mechanism that works.

**Verification (live, in-process):** headless boot with `-ExecutePythonScript` returned

```
engine_version = 5.8.0-55116800+++UE5+Release-5.8
has_SceneSurveyStatics = true   has_WorldForgeIdentityStatics = true
has_WorldStateSubsystem = true
callable: enumerate_survey_actors, sample_survey_support, probe_temp_marker
```

Trap confirmed again: **probe output never reaches stdout** — it appears only in
`Saved/Logs/WorldForge.log`. Diagnose a no-observation boot by reading that log.

---

## v2.6 fixture smoke — FIRST EVER EXECUTION [correct RED]

`PYTHONUTF8=1 python tools/pipeline/run_v2_6_fixture_smoke.py`
-> `procedural/reports/scene_survey/fixture_smoke/v2_6_fixture_smoke_report.json`

`verified=16 unavailable=0 failed=4 still_assumed=1 missing=0`

This converts most of the previously-`[assumed]` UE surface into observation. D18 was
measured for the first time: `T(N) = alpha + beta*N`, `alpha=2.01e-05s`,
`beta=8.17e-06 s/sample`, `R2=0.9992`, 30 points, order stable at every N.

**Caution on D18 criterion c1** (`c1_python_cannot_expose_data = measured_pass`):
this passed *because the geometry probes failed on a shape-guard bug*, which is a
fixable Python defect, not an inherent limitation of Python. It must NOT be read as
a satisfied promotion criterion for support-grid C++ until the geometry surface is
repaired and re-measured.

### Open geometry defects (Lane A)
All four have one root cause: far-side guards were written against *assumed* return
shapes; UE 5.8 actually returns `HitResult` and `Array` objects, which the guards
reject as "unrecognised shape".

- `line_trace_single` — returned `HitResult`, hit/miss never read
- `hit_result_decomposition` — never reached, so `break_hit_result` never called
- `capsule_overlap_actors` — returned `Array`, overlap set never read
- `capsule_overlap_components` — returned `Array`, overlap set never read

### Closed (Lane B) — `operation_manifest_publication`
Not an integrity failure. **Ordering defect**: `classify()` graded the probe before
`verify_manifest_digest()` folded in the real values, and the re-grade was gated on
an already-`runtime_failed` status so it could only downgrade. The near side had
computed the correct digest (`sha256:44d5343…675efea`) all along, matching the
manifest. Fixed in `tools/pipeline/run_v2_6_fixture_smoke.py` by verifying before the
validator loop; independence preserved (still re-derived near-side, never copied).
The failure message now distinguishes "could not re-derive" from "hash mismatch".

---

## Core package — `tools/wfcore/`

Import root is `tools/` (same convention as `bridge`): `cd tools && python -m wfcore.hygiene`.

| Module | State | Purpose |
|---|---|---|
| `tri.py` | DONE, property-tested | Kleene 3-valued satisfaction. UNKNOWN never coerced; `accepts()` is `== SATISFIED`, never `!= VIOLATED` |
| `constraints.py` | DONE | The 8 constraint classes + `ACCEPTANCE_LOAD_BEARING` closed set |
| `failure.py` | DONE | Shim to the ONE code authority (`tools/pipeline/failure_codes.py`) |
| `hygiene.py` | DONE, mutation-tested | Core may not contain any consumer's vocabulary |
| `contracts/` | lane in flight | consumer profile, asset catalog, world request, revision policy, acceptance criteria |
| `models/` | lane in flight | desired/observed world, experience + env-state graphs |
| `providers/` | lane in flight | declaration, capability registry, result-driven selection |
| `planning/` | not started | typed generation/revision plan |
| `transaction/` | not started | bounded world delta + rollback |

### Failure-code band WF1200–1299 (Core)
1200–1205 constraint taxonomy · 1206–1215 consumer contracts · 1216–1225 world models ·
1226–1235 providers. 1131–1199 deliberately left free so scene-survey can extend.

**Every code must have a real raise site and a negative test.** `failure_codes.py`
auto-backfills SEVERITY and GATE_TAXONOMY for any constant typed into the class, so
defining a code proves nothing — it publishes an "owned" code nothing can emit.

---

## Verify commands

```bash
# Core hygiene (game-agnosticism gate)
cd tools && PYTHONUTF8=1 python -m wfcore.hygiene

# live UE surface probe (writes to Saved/Logs/WorldForge.log, NOT stdout)
"/d/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" WorldForge.uproject \
  -ExecutePythonScript=<script> -unattended -nopause -nosplash -nullrhi -stdout

# the v2.6 surface smoke
PYTHONUTF8=1 python tools/pipeline/run_v2_6_fixture_smoke.py

# rebuild against 5.8
"/d/UE_5.8/Engine/Build/BatchFiles/Build.bat" WorldForgeEditor Win64 Development \
  -Project="D:/Unreal Projects/WorldForge/WorldForge.uproject" -WaitMutex
```

## Standing rules for this run
- Lanes do not commit; the captain commits in narrow, ordered commits.
- Strict disjoint file ownership per lane; shared contracts fixed up front.
- Every new rail is mutation-tested: reintroduce defect, prove RED, revert, show output.
- Prefer an honest `unknown` to a fabricated zero; never coerce `unknown` to `false`.
- A correct RED is preferable to a weak GREEN.
