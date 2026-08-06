# WorldForge Core — consumer-driven platform run state

## STATUS: all twelve flow stages built. One item is operator-gated by design.

```
cd tools
PYTHONUTF8=1 python wfcore_shield.py --baseline <manifest>   # 8 suites + hygiene + boundary
PYTHONUTF8=1 python pipeline/test_consumer_flow.py           # consumer proof
PYTHONUTF8=1 python pipeline/test_wfcore_unreal_sink.py      # 189 checks
PYTHONUTF8=1 python tools/pipeline/validate_failure_codes.py
```

All green as of commit `79c70352` (10 commits on `worldforge/wfcore-consumer-platform`).

**The proof:** capture Core → run `demoarena` → run `demoexpanse` → verify.
`sha256:1f91927f…091d6003` (39 files) before and after. PROOF HOLDS.

**Still open, and it cannot be closed from here:** no real importing game has sent a
request. Both consumers are WorldForge-authored demonstrations that say so in their own
provenance records, and the runner refuses to label such a run caller-originated
(`WF1288`). Closing this needs the caller lane to send a real request — an operator
action, not an engineering one.


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

## v2.6 fixture smoke — NOW FULLY GREEN [verified 2026-08-05]

Final state after repair: **`verified=21 unavailable=0 failed=0 still_assumed=0 missing=0`**,
`gate_green: true` in the report itself. Commit `2a200a7c`.

Three defects, all found only by running it. See that commit message for the full
reasoning; the durable lessons:

1. **UE drops the bool.** A UFUNCTION declared `bool` + out-param binds as `None`
   for false and the **bare out-param** for true (`PyGenUtil.cpp:1160-1183`). Both
   decoders assumed `(bool, out)`, so correct `HitResult`/`Array` results were
   rejected as "unrecognised shape". **The shape IS the answer.**
2. **`GameplayStatics.break_hit_result` does not exist in UE 5.8 Python.** Probed
   live. FHitResult members are not Python attributes and `get_editor_property`
   raises for every one; the real routes are `HitResult.to_dict()` (named) and
   `HitResult.to_tuple()` (exactly 18 values, same order). Prefer named.
3. **Ordering defect**: `classify()` graded the manifest probe before the digest was
   folded in, and could only downgrade. Fixed; independence preserved.

Also: a line-trace **miss** and an **empty** capsule-overlap set are complete
observations, not failures.

### D18 — the measurement now says DO NOT promote to C++
On the first (defective) run `c1_python_cannot_expose_data` was `measured_pass` —
but only *because* the geometry probes were failing on defect (1). With the decoders
fixed it is **`measured_fail`**. All six criteria are answered and **none is met**, so
the locked D18 promotion criteria for a support-grid C++ collector are **not satisfied**.
Latest fit: `alpha=-1.06e-04s`, `beta=1.52e-05 s/sample`, `R2=0.9387`, `ok=N/N` at every N.

---

## Historical: the first execution [correct RED]

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
| `contracts/` | DONE, 74 assertions | consumer profile, asset catalog, world request, revision policy, acceptance criteria |
| `models/` | DONE, 22 tests | desired/observed world, experience + env-state graphs |
| `providers/` | DONE, 85 assertions | declaration, capability registry, result-driven selection |
| `analysis/` | DONE, 25 tests | desired-vs-observed reconciliation |
| `planning/` | DONE, 127 assertions | typed generation/revision plan |
| `transaction/` | DONE, 101 assertions | bounded world delta + rollback |
| `acceptance/` | DONE, 24 tests | acceptance evaluation |
| `repair/` | DONE, 21 tests | evidence-driven repair loop |

Engine-backed sink (outside Core, where engine code belongs):
`tools/unreal/wfcore_unreal_sink.py` (far side) + `tools/pipeline/run_wfcore_transaction.py`
(near side). 189-check headless gate. **Two live editor runs proved the loop on real
content** — `committed` with `verification=satisfied`, and `rolled_back` with
`rollback_completeness=satisfied` after a real `WF1278` apply failure destroyed a real
actor and re-observation confirmed absence. Journals under
`procedural/reports/core/transaction/`.

### THE OPEN ITEM — caller provenance (operator-gated, by design)
The locked rule is that an acceptance request must **originate from the caller lane**;
WorldForge must never fabricate caller provenance (now `WF1288`). `Gloamstead5_8` is a
separate, edit-forbidden repository from this session, so a genuinely Gloamstead-originated
request **cannot be produced here** — and manufacturing one would be precisely the error the
architecture exists to prevent.

What is therefore being proven instead: two **WorldForge-authored demonstration consumers**,
explicitly labelled as such in their own records, driving the full flow with Core proven
untouched. That discharges the platform claim (M12). It does **not** discharge "a real
importing game asked for this" — that step needs the caller lane to send a request, and only
the operator can arrange it.

Also outside Core: `tools/wfcore_shield.py` — the single Core gate. Discovers suites
(never a hardcoded list), runs hygiene + the boundary proof, and **fails when it
discovers zero suites** (exit 2). Negative-controlled.

```
cd tools && PYTHONUTF8=1 python wfcore_shield.py --baseline <manifest>
  suites discovered : 6   → contracts 74 · models 22 · providers 85 ·
                            analysis 25 · planning 127 · transaction 101
  GATE GREEN
```

### Verified cross-lane seam
Planning's `_example_plan_step()` feeds transaction's `bound_from_step()` cleanly;
`selected_provider` is the plain string planning declares; declared paths classify
`in_bound`, an undeclared path returns WF1247. Two independently-built lanes agreeing
on the captain-fixed contract, checked rather than assumed.

### The rollback property, demonstrated
Two runs differing only in the sink's honesty, both reporting `undo_reported_ok=True`
on every mutation:

| sink | outcome | restoration |
|---|---|---|
| undo lies (reports ok, restores nothing) | `partial_commit` | `['violated','satisfied']` |
| undo honest | `rolled_back` | `['satisfied','satisfied']` |

Only re-observation separates them. `undo_reported_ok` is written at three sites in
`executor.py` and **read by no verdict path** — confirmed by grep, not by claim.

### Engine facts that constrain the real sink (researched 2026-08-05)
- UE 5.8 Python exposes `ScopedEditorTransaction` (begin/commit/`.cancel()`) but **no
  generic `Undo()`**. Python cannot drive the engine's undo stack. Every mutation kind
  therefore needs an explicit compensating action, and an uncompensatable kind must be
  refused BEFORE apply (WF1279), never discovered afterwards.
- `ScopedEditorTransaction.cancel()` does not restore a package's dirty flag.
- There is no per-package `is_dirty()` — only the two engine-wide dirty-package sets.
- No existing script captures a before-state or reports what it actually wrote.

Outside Core: `tools/core_boundary_proof.py` — digests Core before/after a consumer
run and requires identity. Mutation-tested (catches MODIFIED and ADDED, names paths).
`capture --out <f>` then `verify --baseline <f>`.

### The plan → delta boundary (captain-fixed, both lanes code against it)
A `PlanStep` carries `step_id`, `capability`, `selected_provider`, `depends_on`,
`preconditions`, `postconditions`, `allowed_side_effects`,
`expected_changed_packages`, `expected_changed_actors`, `evidence_requirements`,
`fallback_policy`, `rollback`. The last two of the changed-* pair are **the mutation
bound** the executor enforces against what was ACTUALLY mutated, not what was intended.

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
