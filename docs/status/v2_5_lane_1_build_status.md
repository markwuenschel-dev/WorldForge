# v2.5 Lane 1 (Plugin Build + UE API Port) — Build/Load Handoff

Status: COMPLETE (uncommitted; commander commits). Worktree: `D:\Unreal Projects\WorldForge-UE58`.
Engine: `D:\UE_5.8` (5.8.0, build_id `55116800@++UE5+Release-5.8`). Date: 2026-07-13.

## Objective
Prove the real WorldForge plugin builds AND loads under UE 5.8 (the milestone's critical path).

## Break surface (captured before fixing) → port
The 5.8 build failed in three ordered layers; each fix is the canonical 5.7→5.8 upgrade, no
suppression:
1. **Shared-environment warning levels.** `WorldForge(Editor).Target.cs` used
   `BuildSettingsVersion.V6`, whose Off defaults for Unreachable/ReturnType/Dangling warning
   levels differ from 5.8's shared UnrealEditor environment (Error). UBT forbids modifying a
   shared environment. Fix: `V6 → V7` + `IncludeOrderVersion Unreal5_7 → Unreal5_8` in BOTH
   `Source/WorldForge.Target.cs` and `Source/WorldForgeEditor.Target.cs`. (V7 also promotes
   dangling/return/unreachable to errors — the code compiled clean under them, no fixes needed.)
2. **Missing plugin.** `WorldForge.uproject` required `HoudiniNiagara`, absent in the 5.8
   install. Consistent with WorldForge's long-standing deferred/metadata-only Houdini posture,
   marked it `"Optional": true` so its absence does not block the 5.8 track. Verified ONLY the
   Houdini plugins are missing — NeoStackAI + all 13 other required plugins are present in 5.8.
3. **Compile.** `Build.bat WorldForgeEditor Win64 Development` → **Result: Succeeded** (17/17
   steps, 56.9s). Fresh binaries: `UnrealEditor-WorldForgeCore.dll`, `-WorldForgeEd.dll`,
   `-WorldForge.dll` (project module, carries `WFRuntime.cpp`).

## Files changed (Lane 1 ownership)
- `Source/WorldForge.Target.cs`, `Source/WorldForgeEditor.Target.cs` — V7 + 5.8 include order.
- `WorldForge.uproject` — HoudiniNiagara `Optional: true`.
- `tools/pipeline/validate_plugin_build.py` — the `--plugin` gate (build+load evidence).

## Load smoke (Phase 4)
`UnrealEditor-Cmd.exe WorldForge.uproject -nullrhi -unattended -nosplash -nop4 -execcmds=quit`.
UE log evidence (distilled to `procedural/reports/ue5_8/plugin/plugin_load_evidence.json`):
- `LogPluginManager: Mounting Project plugin WorldForge`
- `LogModuleManager: InternalLoadLibrary: 'WorldForgeCore' (…/UnrealEditor-WorldForgeCore.dll)`
- `LogModuleManager: InternalLoadLibrary: 'WorldForgeEd' (…/UnrealEditor-WorldForgeEd.dll)`
- `LogInit: Display: Engine is initialized` — no fatal, no module-load failure.

## Gate result
`PYTHONUTF8=1 python tools/pipeline/validate_plugin_build.py --strict --engine-root D:/UE_5.8 --load-log <boot log>`
→ **PASS (0 failures, strict)**. overall_ok=True; engine 5.8.0; both modules loaded from fresh
binaries; binaries not stale (mtime ≥ newest C++ source). Capability handshake:
`procedural/reports/ue5_8/plugin/plugin_capability_handshake.json` (engine 5.8.0, plugin 0.1.0,
modules WorldForgeCore+WorldForgeEd).

## Acceptance
UE 5.8 compile PASS · required modules load PASS · explicit engine identity PASS · capability
handshake emitted · not-stale PASS. Contract dogfood negatives (wrong engine / build-failed /
module-not-loaded / binary-predates-source / missing-module) all rejected.

## Limitations / handoff
- The `--plugin` gate reads distilled load evidence on shield re-runs; pass `--load-log` once
  after any rebuild to refresh it. On a clean checkout the binaries must be rebuilt first
  (they are engine output, not committed).
- Live stale-binary NEGATIVE (deleting fresh DLLs so only 5.7 binaries remain) is covered at
  contract level; a live filesystem variant can be added to Lane 7 torture if desired.
- The `WorldForgeRuntime` name referenced elsewhere = the project `WorldForge` module's
  `WFRuntime.cpp`, not a separate module.
