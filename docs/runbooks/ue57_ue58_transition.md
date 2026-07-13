# UE 5.7 → 5.8 Transition Runbook (WorldForge v2.5)

Operator guide for building/running each engine track, where evidence goes, the
preservation refs, and the dual-track isolation guarantees. Lane 2 owns the
repository / engine-identity / track-isolation surface described here.

## 1. The two tracks

| Track | Worktree | Branch | Engine | Engine root |
|-------|----------|--------|--------|-------------|
| Frozen 5.7 (LTS) | `D:/Unreal Projects/WorldForge` | `worldforge/v2.4-tacticalbehaviorforge` (+ `release/ue5.7-v2.4-lts`) | UE 5.7 | `C:/Program Files/Epic Games/UE_5.7` |
| Active 5.8 (transition) | `D:/Unreal Projects/WorldForge-UE58` | `worldforge/v2.5-ue58-transition` | UE 5.8 | `D:/UE_5.8` |

Both worktrees are linked worktrees of ONE repository (shared git common dir
`D:/Unreal Projects/WorldForge/.git`). They share history and one
`repository_identifier`, but each has a distinct `worktree_identifier` — that
distinction is the isolation anchor.

## 2. Engine identity — host vs observed runtime

`tools/pipeline/engine_identity.py` records *which engine actually ran a report*
by reading `Engine/Build/Build.version`, resolved (in precedence order) from:

1. explicit `--engine-root`
2. `WF_UE_CMD` env (strip `Engine/Binaries/Win64/<exe>`)
3. `WorldForge.uproject` `EngineAssociation` → `KNOWN_ENGINE_ROOTS`

> NOTE (documented fallback): the 5.8 worktree's `WorldForge.uproject` still reads
> `EngineAssociation: "5.7"`, so a **runtime-free** report host-resolves to
> `engine_minor = 7`. This is the interpreter HOST identity, **not** the observed
> UE runtime, and is **never** contamination on its own. To make the host block
> report 5.8, set `WF_UE_CMD=D:/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe`.

### Meta-identity convention (binding, Lane 7 depends on it)

Every transition report's `meta` block carries — via
`build_meta(..., extra=transition_identity(...))` — these keys alongside the seven
`engine_identity()` keys:

| key | meaning |
|-----|---------|
| `declared_target_engine` | the engine this run TARGETS (`"5.8"`) |
| `observed_runtime_engine` | UE minor a runtime run OBSERVED, or `null` if none ran |
| `runtime_execution_required` | does this gate need a real UE runtime to be meaningful? |
| `runtime_executed` | did a real UE runtime actually run? |
| `repository_identifier` | 12-hex of the shared git common dir (same both tracks) |
| `worktree_identifier` | `<12hex>:<basename>` per-worktree fingerprint |

A report is **CONTAMINATED** only if:
`runtime_execution_required=True` AND `observed_runtime_engine != declared minor`;
OR an evidence entry is tagged with a non-target engine; OR a path lives under
`procedural/reports/ue5_7`. A runtime-free report resolving `engine_minor=7`
(uproject fallback) is NOT contamination.

Runtime-FREE gates set `runtime_execution_required=False`,
`runtime_executed=False`, `observed_runtime_engine=None`.

## 3. Where evidence goes

Reports route by engine minor (see `engine_identity.reports_dir`):

- 5.7 evidence → `procedural/reports/ue5_7/`
- 5.8 evidence → `procedural/reports/ue5_8/`  ← all v2.5 transition gates write here

The two subtrees are disjoint (neither contains the other). Copying a 5.7 report
into the 5.8 baseline, or referencing a `procedural/reports/ue5_7` path from a 5.8
baseline entry, is contamination (WF1032 / WF1033).

## 4. Preservation refs (5.7 recoverability)

The frozen 5.7 line must always be recoverable:

- branch `release/ue5.7-v2.4-lts`
- tag `worldforge-v2.4-ue5.7-final`

Both currently EXIST. `validate_track_isolation.py` verifies them; if either is
ever absent it emits a NON-BLOCKING known-gap for the commander to create (this
lane never creates refs itself).

## 5. Building / running each track (explicit engine)

Always drive the UE build under **PowerShell**, never Git Bash (spaced install
paths break under bash). Run all Python with `PYTHONUTF8=1`.

Frozen 5.7 (regression / LTS reproduction):

```powershell
& "C:/Program Files/Epic Games/UE_5.7/Engine/Build/BatchFiles/Build.bat" `
  WorldForgeEditor Win64 Development `
  -project="D:/Unreal Projects/WorldForge/WorldForge.uproject"
```

Active 5.8 (transition build — Lane 1 owns the real handshake):

```powershell
& "D:/UE_5.8/Engine/Build/BatchFiles/Build.bat" `
  WorldForgeEditor Win64 Development `
  -project="D:/Unreal Projects/WorldForge-UE58/WorldForge.uproject"
$env:WF_UE_CMD = "D:/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
```

Setting `WF_UE_CMD` makes `engine_identity()` (and thus every report's meta) reflect
the 5.8 install for runtime-executed evidence.

## 6. Isolation guarantees (what Lane 2 proves)

`validate_track_isolation.py` (shield `--track-isolation`) asserts, on the REAL
filesystem, that the two tracks resolve to DIFFERENT absolute
`Saved / Intermediate / Binaries / DerivedDataCache` paths — no shared writable
build/output dir a 5.8 build could clobber in the 5.7 tree or vice versa — and
that the report subtrees are disjoint. Because the two worktrees have distinct
roots, every per-worktree dir is distinct by construction; the gate guards against
regressions (e.g. a future config pointing both tracks at one DDC).

## 7. Runtime-free gate quick reference (Lane 2)

```bash
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_transition_topology.py    --strict
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_capability_manifest.py    --strict
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_engine_identity.py        --strict
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_track_isolation.py        --strict
```

All four are GREEN from Wave 1 (no 5.8 artifact required). The conversion /
plugin-build / regression / bridge / baseline gates stay honestly RED until real
5.8 artifacts exist.
