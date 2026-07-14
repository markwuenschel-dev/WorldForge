# v2.5.1 Lane 4 — LIVE cross-repository bridge (DoD #17)

**Status: GREEN.** The live run genuinely succeeded. A real UE 5.8 editor process
executed a real operation inside a **separate project in a separate git repository**
and returned hash-verified evidence across the boundary.

## Why this lane existed

v2.5 shipped `gloam_bridge_probe.py` — a **rejecting dry probe** — as the bridge
gate. A dry probe asserts *"nothing ran"*. It is a **negative** test: it is GREEN
precisely when no far side was touched. DoD #17 requires a **positive** gate — a
real run against a separate UE 5.8 project. A negative test cannot satisfy a
positive requirement, so the v2.5 bridge gate never met DoD #17.

The dry probe was not wrong; it was **mislabelled as the gate**. So it stays exactly
as it is, untouched, and is now used as the **headline negative** of the live gate:
the v2.5 report is fed to the live gate and must go RED (fail-closed proof #1).

## What was built

| Path | Role |
| --- | --- |
| `tools/bridge/live.py` | The LIVE contract (`wf.transition.gloam_bridge_live.v1`) + positive validation rules. |
| `tools/bridge/far_side.py` | Runs **inside** the far-side UE 5.8 editor. Observes and executes; never asserts. |
| `tools/bridge/fixture.py` | Creates the separate UE 5.8 fixture project + its own git repo. |
| `tools/bridge/paths.py` | The arg → env → discovery → registry resolution ladder. No baked paths. |
| `tools/pipeline/gloam_bridge_live.py` | The live runner. |
| `tools/pipeline/validate_gloam_bridge_live.py` | The POSITIVE gate. |
| `procedural/reports/ue5_8/gloam/live/` | Live report + gate report. |

Untouched, as required: `gloam_bridge_probe.py`, `validate_gloam_bridge.py`,
`tools/bridge/{__init__,schema,probe}.py`, `transition_contracts.py`,
`failure_codes.py`, `v2_5_shield.py`, `audit_conversion_diff.py`, all manifests.

## The fixture (the far side)

`D:/Unreal Projects/WF-BridgeFixture58` — **outside** this repo, **its own git
repository**, created reproducibly by `tools/bridge/fixture.py`:

- own `WFBridgeFixture58.uproject` (`EngineAssociation: 5.8`), no C++ module of its own;
- the WorldForge plugin copied in **as a binary plugin** (5.8-built DLLs), so the
  editor loads it from precompiled binaries and never invokes a compiler;
- `git init` + one commit — this is what makes *"target commit resolved"* a real
  cross-repository resolution rather than an echo of our own SHA;
- minimal: no maps, no content beyond what the operation authors.

**It is not Gloamstead, and it never claims to be.** Gloamstead is not on this
machine. The honest move is a project that is *genuinely separate* and to **say** it
is a stand-in — the live report carries `fixture_standin: true` and
`is_gloamstead_target: false`, and a report claiming otherwise is **rejected**
(WF1037, proof #13). What this proves is the **bridge mechanism**. What it does not
prove is **Gloamstead compatibility**, and nothing here claims it.

Naming the fixture `Gloam*` to satisfy the `GloamBridgeProbe` contract's
`"gloam" in target_project` substring check (WF1024) was available and was
**rejected** — that is precisely the laundering this lane exists to prevent. Hence
the separate live schema.

## The real operation

`materialize_recipe_asset` — inside the far-side editor:

1. constructs `UMaterialRecipeDataAsset` (a **plugin-owned UCLASS** from WorldForgeCore);
2. stamps the bridge `operation_id` into its provenance;
3. serialises it through UE's package system to a **real `.uasset` on disk** in the
   target project;
4. **reloads it from disk** and verifies the `operation_id` survived the round trip.

It cannot succeed unless the plugin's code is genuinely loaded and running. The
artifact is real: `Content/WFBridge/WFBridgeRecipe_<operation_id>.uasset`.

## How each DoD #17 sub-requirement is proven

| Requirement | How | Not by |
| --- | --- | --- |
| Target repository resolved | far side runs `git rev-parse --show-toplevel` **in its own tree** | trusting our own repo |
| Target commit resolved | far side's real `HEAD`; gate re-checks it against the fixture repo's actual HEAD | an assertion |
| Correct `.uproject` selected | `unreal.Paths.get_project_file_path()` from the running editor | a config lookup |
| Observed engine is UE 5.8 | `unreal.SystemLibrary.get_engine_version()` → `5.8.0-55116800+++UE5+Release-5.8` | **not** read from any `.uproject`/`.ini` |
| Plugin present **and** loaded | `.uplugin` on disk **plus** plugin UCLASSes in the reflection registry (a UCLASS registers only when its DLL loads) | presence alone |
| Capability handshake | 3 plugin-owned reflection symbols probed, all `available: true` | a declared list |
| Real operation executes | a real `.uasset` authored, saved, reloaded, round-trip verified | a log line |
| Evidence across the boundary | 2 artifacts read back from the target project | far-side say-so |
| `operation_id` end-to-end | echoed by the far side; also survives the asset round trip | local comparison only |
| Evidence hashes validate | **the gate re-hashes every artifact from the bytes on disk** and compares | trusting reported hashes |
| No machine-specific path | every path via arg → env → discovery → registry; the rung used is recorded in `resolution_sources` | baked constants |

Plugin binaries are selected by **BuildId match against the engine about to run**
(not by directory name). During development this correctly refused the 5.7-built
binaries (BuildId `47537391`) against the 5.8 engine (`55116800`) — WF1019 in
spirit, caught before launch.

## Fail-closed proofs (13/13 RED, verified against the real gate)

Each tampers with the **real on-disk report** and runs the **real gate** as a
subprocess:

| # | Case | Result | Codes |
| --- | --- | --- | --- |
| 1 | **v2.5 dry probe submitted to the live gate** | RED | WF1011/1018/1023/1024/1025/1026 |
| 2 | dry probe **relabelled** with the live schema string | RED | WF1011/1018/1023/1024/1025/1026 |
| 3 | process exits zero but evidence missing | RED | WF1028, WF1034 |
| 4 | wrong engine observed (5.7) | RED | WF1023, WF1031 |
| 5 | plugin absent | RED | WF1018, WF1025 |
| 6 | plugin present but never loaded | RED | WF1018 |
| 7 | `operation_id` mismatch end-to-end | RED | WF1030 |
| 8 | evidence belonging to another project | RED | WF1024, WF1028, WF1029 |
| 9 | stale/reused evidence | RED | WF1026 |
| 10 | runtime never executed | RED | WF1034 |
| 11 | evidence hash tampered | RED | WF1034 |
| 12 | artifact deleted from disk | RED | WF1028 |
| 13 | false Gloamstead claim | RED | WF1037 |

Untampered report restored → GREEN. The gate carries 96 checks (49 real, 38
negatives, 6 DoD #17 headline, 2 dogfood), 0 failures, strict on.

## Failure codes used

Only existing codes from the **WF1011–WF1039** band; **none added**. Bridge band
WF1023–WF1030 carries the bridge semantics:

`WF1011` CAPABILITY_UNAVAILABLE · `WF1018` PLUGIN_LOAD_FAILED · `WF1023`
BRIDGE_WRONG_ENGINE · `WF1024` BRIDGE_WRONG_PROJECT · `WF1025` BRIDGE_ABSENT_PLUGIN ·
`WF1026` BRIDGE_STALE_PLUGIN · `WF1028` BRIDGE_EMPTY_EVIDENCE · `WF1029`
BRIDGE_ABSOLUTE_PATH_LEAK · `WF1030` BRIDGE_OPERATION_ID_MISMATCH · `WF1031`
EVIDENCE_ENGINE_MISMATCH · `WF1034` TRANSITION_REPORT_INTEGRITY_FAILED · `WF1035`
TRANSITION_NEGATIVE_ACCEPTED · `WF1037` TRANSITION_HYGIENE_FAILED.

`WF1027` BRIDGE_MAP_MISSING is **not** used: the fixture operation authors an asset,
not a map, so there is no honest map claim to make.

## Reproduce

```bash
# live run (rebuilds the fixture from scratch)
MSYS_NO_PATHCONV=1 PYTHONUTF8=1 python tools/pipeline/gloam_bridge_live.py --rebuild-fixture

# positive gate
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_gloam_bridge_live.py --strict

# fully parameterised (any machine)
export WF_BRIDGE_FIXTURE_ROOT=/path/to/fixture
export WF_BRIDGE_ENGINE_ROOT=/path/to/UE_5.8
export WF_BRIDGE_PLUGIN_SOURCE=/path/to/Plugins/WorldForge   # must hold 5.8-built binaries
```

Verified: runs are **repeatable** (back-to-back re-runs stay GREEN) and work from a
**clean room** (fixture deleted → rebuilt → GREEN), and at an **alternate fixture
path** resolved purely from env.

## Honest limits

1. **Not Gloamstead.** The far side is a fixture stand-in. The bridge *mechanism* is
   proven against a genuinely separate UE 5.8 repository; **Gloamstead
   compatibility is not proven** and is not claimed. A Gloamstead run needs the
   Gloamstead repo present locally.
2. **No map operation.** The operation authors a DataAsset, not a courtyard.
   `target_map` is empty and WF1027 is unused rather than faked.
3. **New live schema, not the frozen contract.** `wf.transition.gloam_bridge_live.v1`
   lives in `tools/bridge/live.py`, not `transition_contracts.py`, which this lane
   may not edit. Folding it into the frozen contract registry is follow-up work.
4. **Plugin binaries are a build artifact.** The fixture needs 5.8-built plugin DLLs
   discovered from a worktree that has built them. On a machine with no 5.8 build,
   the runner fails loudly (it does not fabricate a pass).
5. **The dry probe remains** the negative test it always was, and its gate still
   passes unchanged.
