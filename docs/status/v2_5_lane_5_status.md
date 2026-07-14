# WorldForge v2.5 — Lane 5 (Build Automation + CI Matrix) status

Worktree: `D:\Unreal Projects\WorldForge-UE58` · Branch: `worldforge/v2.5-ue58-transition`
Base commit: `fa922a37` · Last updated: 2026-07-13 · Owner: Lane 5 (subagent)

## Objective

Give the transition a build-automation spine that is **honest about the engine
boundary**: resolve which UE install a gate runs against, know per-gate whether an
install / a live runtime is required, run the no-UE gate tier for real in CI, and
mark every UE gate GATED with the exact command it *would* run — never a fabricated
UE result, never 5.7 evidence laundered as 5.8. Cross-engine build caches are
proven non-reusable.

## Files owned by this lane

| File | Purpose |
|------|---------|
| `tools/pipeline/discover_unreal_engine.py` | Resolve engine root/exe/Build.bat/build_id per `--version`; report `(requires_engine, requires_runtime)` per `--gate`; print the full gate matrix. Reuses `engine_identity.resolve_engine_root` / `engine_identity()` (no duplicated resolver logic). |
| `tools/pipeline/run_transition_ci.py` | CI matrix orchestrator. Runs python-only gates for real (discover-by-presence → SKIPPED if a sibling isn't built yet), prints would-run commands for UE gates as GATED, emits a CI summary report with an unforgeable runtime-provenance block, and asserts 5.7≠5.8 cache-key isolation. `--engine 5.7|5.8`, `--python-only`. |
| `docs/status/v2_5_lane_5_status.md` | This handoff. |

Not edited (proposed as text below for the commander to apply): `Makefile`,
`.github/workflows/**`, `failure_codes.py`, `engine_identity.py`, `v2_5_shield.py`.

## The full v2.5 CI matrix

Cell legend: **PY** = runs for real on a no-UE runner · **BUILD** = needs an
install (Build.bat) but no live editor · **RUNTIME** = needs a live engine process
· **GATED** = command printed, not executed by CI (runtime lanes / commander run it).

| CI gate (mission row) | canonical gate key | engine req | runtime req | UE 5.7 (frozen) | UE 5.8 (active) |
|-----------------------|--------------------|:----------:|:-----------:|-----------------|-----------------|
| Python contracts | `transition-contracts` (+topology, capability, gloam-bridge, negatives, fuzz, report-integrity, hygiene) | no | no | **PY — run for real** | **PY — run for real** |
| Plugin compile | `plugin-compile` | yes | no | BUILD — GATED | BUILD — GATED |
| Editor smoke | `editor-smoke` | yes | yes | RUNTIME — GATED | RUNTIME — GATED |
| Commandlet smoke | `commandlet-smoke` | yes | yes | RUNTIME — GATED | RUNTIME — GATED |
| New features | `new-features` | yes | yes | RUNTIME — GATED | RUNTIME — GATED |
| Full baseline | `full-baseline` (+`conversion-manifest`, `transition-regression`) | yes | yes | RUNTIME — GATED | RUNTIME — GATED |
| Final shield | `final-shield` (`v2_5_shield.py`) | yes | yes | aggregate — GATED | aggregate — GATED |

Notes:
- **5.7 is the frozen LTS track**; its CI is a *regression floor* (contracts + a
  plugin-compile/editor-smoke sanity). The transition's forward baseline is 5.8.
- Plugin compile is `engine=yes, runtime=no`: `Build.bat` compiles the editor
  target without launching an editor. Everything below it needs a live process.
- The python-only tier is GREEN today because the contract spine is committed;
  the other python gates flip from SKIPPED→PASS automatically as Lanes 2/6/7 land
  their scripts (discover-by-presence — no orchestrator edit needed).

## Discovered engines (real resolution)

| Version | engine_root | exists | build_id | resolution |
|---------|-------------|:------:|----------|-----------|
| 5.7 | `C:\Program Files\Epic Games\UE_5.7` | yes | `51494982@++UE5+Release-5.7` (5.7.4) | explicit engine_root (KNOWN_ENGINE_ROOTS) |
| 5.8 | `D:\UE_5.8` | yes | `55116800@++UE5+Release-5.8` (5.8.0) | explicit engine_root (KNOWN_ENGINE_ROOTS) |

Both installs resolve a real `UnrealEditor-Cmd.exe` and `Build.bat`.

## Cache-key isolation proof

`gate_engine_cache_key(version)` = `wf-transition | ue<ver> | build=<build_id> |
plugin=<plugin_commit> | project=<project_commit>`. Even though 5.7 and 5.8 share
the same worktree (identical plugin/project commit), the engine `build_id`
guarantees separation. `run_transition_ci.assert_cache_isolation()` runs this at
the top of every invocation and is fatal on collision.

```
5.7 -> wf-transition|ue5.7|build=51494982@++UE5+Release-5.7|plugin=2940a5af…|project=fa922a37…
5.8 -> wf-transition|ue5.8|build=55116800@++UE5+Release-5.8|plugin=2940a5af…|project=fa922a37…
5.7 key != 5.8 key -> True
```

## Exact commands run + real output

```
# 1. discover 5.7 and 5.8 — both resolve (rc=0)
PYTHONUTF8=1 python tools/pipeline/discover_unreal_engine.py --version 5.7   # build_id 51494982@++UE5+Release-5.7
PYTHONUTF8=1 python tools/pipeline/discover_unreal_engine.py --version 5.8   # build_id 55116800@++UE5+Release-5.8

# 2. gate matrix
PYTHONUTF8=1 python tools/pipeline/discover_unreal_engine.py --table
#   transition-contracts .. transition-hygiene : engine=no  runtime=no  (python)
#   plugin-compile                              : engine=yes runtime=no  (ue_build)
#   editor/commandlet/conversion/regression/new-features/full-baseline : engine=yes runtime=yes (ue_runtime)
#   final-shield                                : engine=yes runtime=yes (aggregate)

# 3. gate requirement lookup (alias resolves)
PYTHONUTF8=1 python tools/pipeline/discover_unreal_engine.py --version 5.8 --gate baseline
#   -> {'gate':'full-baseline','gate_alias_of':'baseline','requires_engine':True,'requires_runtime':True}
PYTHONUTF8=1 python tools/pipeline/discover_unreal_engine.py --gate bogus   # rc=1 (unknown gate)

# 4. CI matrix, python-only — MUST exit 0 with contracts GREEN, UE gates GATED
PYTHONUTF8=1 python tools/pipeline/run_transition_ci.py --engine 5.8 --python-only   # EXIT=0
PYTHONUTF8=1 python tools/pipeline/run_transition_ci.py --engine 5.7 --python-only   # EXIT=0
```

`run_transition_ci.py --engine 5.8 --python-only` tail:

```
  [PASS   ] transition-contracts         [transition-contracts] PASS — worldforge_vertical_slice (0 failure(s)…)
  [SKIPPED] transition-topology …        sibling script not yet built — pending a later wave   (x7)
  [GATED  ] plugin-compile               would run: "D:\UE_5.8\…\Build.bat" WorldForgeEditor Win64 Development -Project="…\WorldForge.uproject" -waitmutex
  [GATED  ] editor-smoke                 would run: "D:\UE_5.8\…\UnrealEditor-Cmd.exe" "…\WorldForge.uproject" /Game/Maps/encounter_loop_world -unattended -nullrhi …
  … (commandlet-smoke, conversion-manifest, transition-regression, new-features, full-baseline, final-shield all GATED)
python gates: 1 ran, 1 passed, 0 failed | 7 skipped(pending) | 8 GATED(UE)
CI summary -> procedural\reports\ue5_8\ci\transition_ci_summary_ue5_8.json
transition CI (5.8): GREEN
EXIT=0
```

Emitted CI summary `build_meta` block (both engines, python-only run):
`declared_target_engine=<5.7|5.8>`, `observed_runtime_engine=None`,
`runtime_execution_required=False`, `runtime_executed=False`,
`cache_isolation.isolated=True`, `status=ok`. Reports at
`procedural/reports/ue5_8/ci/transition_ci_summary_ue5_7.json` and `…_ue5_8.json`.

## PROPOSED Makefile targets — for the commander to apply

Append near the other v2.x shields (after the `v2-4-shield` block). Mirrors the
existing `$(PYTHON) tools/pipeline/...` + `.PHONY` style.

```make
# --- v2.5 build automation + CI matrix (Lane 5) ------------------------
# discover-engine: resolve a UE install (VERSION=5.7|5.8) or a gate's requirement.
discover-engine:
	$(PYTHON) tools/pipeline/discover_unreal_engine.py \
	  $(if $(VERSION),--version $(VERSION),) $(if $(GATE),--gate $(GATE),) $(if $(TABLE),--table,)

# transition-ci: run the no-UE gate tier for real; UE gates printed as GATED.
#   make transition-ci ENGINE=5.8 PYTHON_ONLY=1
transition-ci:
	$(PYTHON) tools/pipeline/run_transition_ci.py \
	  --engine $(if $(ENGINE),$(ENGINE),5.8) $(if $(PYTHON_ONLY),--python-only,)

.PHONY: discover-engine transition-ci
```

## PROPOSED CI workflow block — for the commander to apply

Add a **new job** to `.github/workflows/worldforge_contracts.yml` (it already runs
`ubuntu-latest`, no UE). This runs the python-only transition tier for both
declared engines; UE gates stay GATED (the workflow name already says "no UE").
`discover_unreal_engine` still resolves *paths* on Linux even without the install
present (it reports `engine_root_exists:false`), but the python-only CI does not
depend on the install, so the job is green on hosted runners.

```yaml
  transition-ci:
    name: v2.5 transition (python-only, no UE)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Transition contract + gate matrix (declared 5.8)
        env:
          PYTHONUTF8: "1"
        run: |
          python tools/pipeline/discover_unreal_engine.py --table
          python tools/pipeline/run_transition_ci.py --engine 5.8 --python-only
      - name: Transition regression floor (declared 5.7)
        env:
          PYTHONUTF8: "1"
        run: |
          python tools/pipeline/run_transition_ci.py --engine 5.7 --python-only
```

> The **UE tier** (plugin compile / editor+commandlet smoke / conversion /
> regression / baseline / final shield) is intentionally NOT in hosted CI. It runs
> on the commander's self-hosted UE 5.8 box via `make transition-ci ENGINE=5.8`
> (no `PYTHON_ONLY`) which prints the exact would-run commands, and via
> `v2_5_shield.py` once Lanes 1/3/4/6 land real 5.8 evidence. `run_transition_ci`
> never executes a UE process, so a hosted runner cannot fake a runtime GREEN.

## Limitations / honesty notes

- `run_transition_ci` **never** launches UE. UE gates are always GATED; the tool is
  a matrix reporter + no-UE runner, not a UE driver. The fail-closed authority over
  UE gates remains `v2_5_shield.py`.
- The would-run commands for `editor-smoke` / `commandlet-smoke` / `new-features`
  use a representative runtime entry (`/Game/Maps/encounter_loop_world`,
  `-run=WorldForgeRuntimeSmoke`); the authoritative invocations belong to Lanes
  1/4. The load-bearing part is the **explicit engine path** substituted per
  `--engine`, and the GATED marking — not the exact commandlet name.
- 7 python sibling gates were absent at authoring time and show SKIPPED. As Lanes
  2/6/7 land them they flip to PASS/FAIL automatically (discover-by-presence). At
  the time of writing several appeared mid-session (other lanes are concurrent);
  the orchestrator re-scans on every run.
- `engine_identity()` with no arg reflects the worktree's **ambient** identity
  (uproject `EngineAssociation=5.7`), so `meta.engine_minor` in the CI report reads
  7 while `build_meta.declared_target_engine` is the authoritative CI target (5.8).
  This is intentional and honest — ambient association ≠ declared CI target.
- CI summary reports are written under `procedural/reports/ue5_8/ci/`; a default
  (non-`--python-only`) run overwrites the same filename with
  `runtime_execution_required=True`. The committed-state reports on disk are from
  the `--python-only` runs (`runtime_execution_required=False`).

## Git status (this lane)

No commits, adds, or pushes made (per swarm rule — Lane 0 commits). New untracked
files: the two tools above + this doc + `procedural/reports/ue5_8/ci/*.json`.
One report I churned by running the contract gate
(`validate_transition_contracts_report.json`, Lane 4's committed file) was restored
via a surgical `git checkout --` of that single path (no broad checkout — other
lanes have concurrent uncommitted work in this worktree).
