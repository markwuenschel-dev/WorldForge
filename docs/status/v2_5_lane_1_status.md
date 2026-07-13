# v2.5 Lane 1 (ContractForge / topology) — Engine Identity

Status: COMPLETE (uncommitted; commander handles commits)
Worktree: `D:\Unreal Projects\WorldForge-UE58` (active 5.8 transition worktree)
Date: 2026-07-12

## Files changed
- `tools/pipeline/engine_identity.py` — NEW. Engine-identity resolver + report routing helpers + CLI.
- `docs/status/v2_5_lane_1_status.md` — NEW. This handoff.

`report_meta.py` was NOT modified (read-only dependency). `engine_identity.py`
imports only `report_meta.hash_text` from it.

## The exact key set the identity dict emits
Contract keys (ALWAYS present, the seven `IDENTITY_KEYS`):
```
engine_major, engine_minor, engine_patch, engine_build_id,
project_commit, plugin_commit, project_path_identity
```
Plus two additive diagnostic breadcrumbs (not part of the seven-key contract,
safe to ignore or strip): `engine_root`, `_resolution`.

Field semantics:
- `engine_major/minor/patch` — from the RESOLVED engine's
  `Engine/Build/Build.version` (Major/Minor/PatchVersion). Reflects the engine
  that RAN, never the uproject's EngineAssociation.
- `engine_build_id` — `"<Changelist>@<BranchName>"` (e.g.
  `55116800@++UE5+Release-5.8`), or just the changelist if branch is absent, or
  `None` if unresolved.
- `project_commit` — `git rev-parse HEAD` of the worktree.
- `plugin_commit` — `git log -1 --format=%H -- Plugins/WorldForge`, falling back
  to `project_commit` when the plugin has no distinct history.
- `project_path_identity` — `hash_text(<normalized abs worktree root>)[:12] + ":" + basename`.
  For this worktree: `731a1b255046:WorldForge-UE58`. Ties a report to the
  frozen-5.7 vs active-5.8 worktree.

## Engine resolution precedence
`resolve_engine_root(engine_root=None)` resolves in this order:
1. Explicit `engine_root` argument (from `--engine-root` or a caller).
2. `WF_UE_CMD` env var — the install root is derived by stripping the trailing
   `Engine/Binaries/Win64/<exe>` (e.g.
   `D:/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe` -> `D:/UE_5.8`).
3. `WorldForge.uproject` EngineAssociation mapped to a known install:
   `5.7 -> C:/Program Files/Epic Games/UE_5.7`, `5.8 -> D:/UE_5.8`.
4. If none resolve, the dict is still returned with `engine_* = None` and
   `_resolution` explains why. It NEVER raises.

`Build.version` existence is (re)checked when read, so an explicit non-existent
root yields `engine_* = None` with a clear `_resolution` note rather than a crash.

## CLI / `--engine-root` usage
```
# Default: resolve via WF_UE_CMD, else uproject EngineAssociation
PYTHONUTF8=1 python tools/pipeline/engine_identity.py --emit

# Override the resolved install explicitly (either spelling works)
PYTHONUTF8=1 python tools/pipeline/engine_identity.py --emit --engine-root "D:/UE_5.8"
PYTHONUTF8=1 python tools/pipeline/engine_identity.py --emit --engine-root="C:/Program Files/Epic Games/UE_5.7"

# Contract self-check (asserts all seven keys, engine_minor is int when resolvable)
PYTHONUTF8=1 python tools/pipeline/engine_identity.py --selfcheck
```
`--emit` prints the identity dict as pretty JSON to stdout and exits 0.

## Report routing helpers (for later lanes)
- `report_root_for_engine(engine_minor)` -> `"ue5_7"` (7), `"ue5_8"` (8),
  else `"ue5_<minor>"`.
- `reports_dir(base="procedural/reports", engine_minor=None)` -> `Path`. With
  `engine_minor=None` it resolves the current engine to pick the subtree; if
  unresolved it returns `base` unchanged. Route reports under
  `procedural/reports/ue5_7/` vs `procedural/reports/ue5_8/` so 5.7 and 5.8
  runs never collide.

## Sample `--emit` output (REAL, run from the worktree with PYTHONUTF8=1)

### `--emit --engine-root "D:/UE_5.8"` (active 5.8)
```json
{
  "engine_major": 5,
  "engine_minor": 8,
  "engine_patch": 0,
  "engine_build_id": "55116800@++UE5+Release-5.8",
  "project_commit": "4641ee8724d7eb901dde890afa9dc3e5b5c7ca41",
  "plugin_commit": "2940a5afd71828c336d918356fb71ff9aa6a1c81",
  "project_path_identity": "731a1b255046:WorldForge-UE58",
  "engine_root": "D:\\UE_5.8",
  "_resolution": "explicit engine_root argument; read D:\\UE_5.8\\Engine\\Build\\Build.version"
}
```

### `--emit --engine-root "C:/Program Files/Epic Games/UE_5.7"` (frozen 5.7)
```json
{
  "engine_major": 5,
  "engine_minor": 7,
  "engine_patch": 4,
  "engine_build_id": "51494982@++UE5+Release-5.7",
  "project_commit": "4641ee8724d7eb901dde890afa9dc3e5b5c7ca41",
  "plugin_commit": "2940a5afd71828c336d918356fb71ff9aa6a1c81",
  "project_path_identity": "731a1b255046:WorldForge-UE58",
  "engine_root": "C:\\Program Files\\Epic Games\\UE_5.7",
  "_resolution": "explicit engine_root argument; read C:\\Program Files\\Epic Games\\UE_5.7\\Engine\\Build\\Build.version"
}
```
(Default `--emit` with no `WF_UE_CMD` resolves via uproject EngineAssociation
`5.7`, producing the same 5.7 block with `_resolution` noting the uproject path.)

## Assumptions later lanes MUST honor
1. Attach identity via `build_meta(..., extra=engine_identity())`. `build_meta`
   does `meta.update(extra)`, so the engine_* / *_commit / project_path_identity
   keys land alongside existing meta keys with no report_meta.py change.
2. To pin a specific engine in a report, pass `engine_identity(engine_root=...)`
   or set `WF_UE_CMD` before the run — do not trust the uproject alone.
3. `engine_minor` may be `None` if the engine is unresolvable; guard before
   using it for routing (or call `reports_dir` which handles None by returning
   the base path).
4. Route engine-specific reports under `reports_dir(engine_minor=...)` so 5.7 and
   5.8 outputs stay in separate subtrees.
5. Run with `PYTHONUTF8=1` on Windows (repo policy); output is emoji-free.

## Known limitations
- `KNOWN_ENGINE_ROOTS` fallback maps only 5.7 and 5.8; a new install requires a
  map entry OR an explicit `engine_root` / `WF_UE_CMD`. (D:/UE_5.7 exists on this
  machine but the `5.7` association maps to the C:/ install; use `--engine-root
  "D:/UE_5.7"` if the D:/ copy is needed.)
- Identity reflects the CURRENT `HEAD`/plugin commit at call time — it is not
  pinned to a report's generation moment beyond when `engine_identity()` runs.
- `_resolution`/`engine_root` are diagnostic extras; do not gate on their exact
  wording. Gate on the seven contract keys only.
- git-missing / not-a-repo yields `project_commit`/`plugin_commit` = `None`
  (no crash), mirroring `report_meta.git_sha`'s tolerance.

## Verification performed
- `--emit` default (uproject 5.7 -> C:/ install): engine_minor 5.7, patch 4.
- `--emit --engine-root D:/UE_5.8`: engine_minor 5.8, patch 0. (pasted above)
- `--emit --engine-root "C:/Program Files/Epic Games/UE_5.7"`: 5.7. (pasted above)
- `WF_UE_CMD` precedence: env `.../UnrealEditor-Cmd.exe` -> `D:/UE_5.8`, minor 8.
- Unresolvable root (`Z:/does/not/exist`): engine_* = None, project_commit still
  present, `_resolution` explains — no crash.
- `--selfcheck`: OK (all seven keys, engine_minor int).
