# v2.5 Lane 2 — Repository, Engine Identity & Dual-Track Isolation (handoff)

## Objective

Own the repository / engine-identity / dual-track-isolation surface of the UE
5.7 → 5.8 transition: build the meta-identity convention helper on top of
`engine_identity`, and stand up the four runtime-free shield gates that prove
engine-identity honesty, dual-track isolation, contract-registry topology, and a
real declared 5.8 capability manifest — all GREEN under `STRICT=1 --strict`.

## Files created (Lane 2 only — no other lane's files touched)

- `tools/pipeline/transition_identity.py` — convention/fingerprint helper + `--selfcheck`
- `tools/pipeline/validate_engine_identity.py` — shield `--engine-identity` gate
- `tools/pipeline/validate_track_isolation.py` — shield `--track-isolation` gate
- `tools/pipeline/validate_transition_topology.py` — shield `--topology` gate
- `tools/pipeline/validate_capability_manifest.py` — shield `--capability` gate
- `docs/runbooks/ue57_ue58_transition.md` — operator runbook
- `docs/status/v2_5_lane_2_status.md` — this handoff

Read-only imports used: `engine_identity` (IDENTITY_KEYS, engine_identity,
project_path_identity), `transition_contracts` (CONTRACTS, CONTRACT_GROUPS,
KNOWN_BAD_OWNING_CODE, TRANSITION_CODES, validators/examples, RT_* , AUTHORING_TS),
`report_meta.build_meta`, `validation_report.ValidationReport`, `runtime_schema`,
`failure_codes.FailureCode`. No modification to any of them.

## Meta-identity convention (implemented verbatim)

`transition_identity(declared_target_engine, runtime_required=False,
runtime_executed=False, observed_runtime_engine=None, engine_root=None)` returns
the seven `engine_identity()` keys merged with the four convention keys
(`declared_target_engine`, `observed_runtime_engine`, `runtime_execution_required`,
`runtime_executed`) plus `repository_identifier` (12-hex of the shared git
common dir — identical for both worktrees) and `worktree_identifier`
(`project_path_identity()` — distinct per worktree). Every Lane 2 report attaches
it via `build_meta(..., extra=transition_identity("5.8", runtime_required=False,
runtime_executed=False, observed_runtime_engine=None))` → runtime-free reports.

Honesty separation respected: the 5.8 worktree uproject still reads
`EngineAssociation: "5.7"`, so `engine_identity()` host-resolves `engine_minor=7`.
This is NOT contamination for a runtime-free report; the convention only judges
contamination via `observed_runtime_engine` vs `declared` under
`runtime_execution_required=True` (`transition_identity.contamination_reason`).

## Contracts dogfooded

- `EngineIdentity` — valid example passes; known-bad rejected for owning
  `WF1013_ENGINE_VERSION_MISMATCH`; **live** `engine_identity()` block also run
  through the contract (passes at host minor=7, a valid evidence minor).
- `CapabilityManifest` — valid example passes; known-bad rejected for owning
  `WF1011_CAPABILITY_UNAVAILABLE`; real authored 5.8 manifest validated GREEN.
- Registry topology of all 7 contracts (partition, owning-code coverage,
  code reality, `TRANSITION_CODES` superset of referenced WF1011–1033 codes).

## Failure codes covered (owning codes asserted on real negatives)

| Rejected condition | Owning code |
|---|---|
| 5.8-declared report with 5.7 OBSERVED runtime | `WF1031_EVIDENCE_ENGINE_MISMATCH` |
| runtime_execution_required with observed=None | `WF1013_ENGINE_VERSION_MISMATCH` |
| runtime-free report claiming runtime_executed=True | `WF1037_TRANSITION_HYGIENE_FAILED` |
| absolute-path leak in an identity fingerprint field | `WF1029_BRIDGE_ABSOLUTE_PATH_LEAK` |
| report fingerprinted to the wrong worktree | `WF1034_TRANSITION_REPORT_INTEGRITY_FAILED` |
| shared writable Saved/Intermediate/Binaries/DDC across tracks | `WF1037_TRANSITION_HYGIENE_FAILED` |
| CapabilityManifest known-bad (required cap unavailable) | `WF1011_CAPABILITY_UNAVAILABLE` |
| EngineIdentity known-bad (engine_major!=5) | `WF1013_ENGINE_VERSION_MISMATCH` |
| topology violations (fake code / missing owning) | `WF1039_TRANSITION_UNKNOWN_FAILURE_CODE`, `WF1034` |

## Exact commands run + real output

```
$ PYTHONUTF8=1 python tools/pipeline/transition_identity.py --selfcheck
transition_identity self-check OK   (exit 0)

$ PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_transition_topology.py --strict
[transition-topology] PASS — transition_topology (0 failure(s), 0 warning(s), strict=on)   exit=0

$ PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_capability_manifest.py --strict
[capability-manifest] PASS — capability_manifest (0 failure(s), 0 warning(s), strict=on)   exit=0

$ PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_engine_identity.py --strict
[engine-identity] PASS — engine_identity (0 failure(s), 0 warning(s), strict=on)   exit=0

$ PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_track_isolation.py --strict
[track-isolation] PASS — track_isolation (0 failure(s), 0 warning(s), strict=on)   exit=0

# regression: pre-existing contract-spine gate still green
$ PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_transition_contracts.py --strict
[transition-contracts] PASS — worldforge_vertical_slice (0 failure(s), 0 warning(s), strict=on)   exit=0
```

Per-gate check counts (all PASS, 0 WARN):
`topology=49, engine_identity=15, track_isolation=14, capability_manifest=9`.

Negative-rejection proof (each rejected for its owning code; good meta passes):
```
declared_5_8_observed_5_7 : rejected=True owning=WF1031 ✓
required_but_observed_none: rejected=True owning=WF1013 ✓
free_but_pretends_executed: rejected=True owning=WF1037 ✓
abs_path_leak_in_identity : rejected=True owning=WF1029 ✓
wrong_worktree            : rejected=True owning=WF1034 ✓
good runtime-free meta    : passes=True
```

## Reports generated (all under procedural/reports/ue5_8/)

- `validate_transition_topology_report.json`
- `validate_capability_manifest_report.json`
- `validate_engine_identity_report.json`
- `validate_track_isolation_report.json`

## Real 5.8 capability manifest (authored, disk-verified)

| capability | kind | required | available | proof |
|---|---|---|---|---|
| PCGFramework | engine_module | true | true | `D:/UE_5.8/Engine/Plugins/PCG` present |
| WorldPartition | editor_subsystem | true | true | `D:/UE_5.8/Engine/Source/Runtime/Engine/Private/WorldPartition` present |
| UnrealBuildTool | build_tool | true | true | `D:/UE_5.8/.../UnrealBuildTool.exe` present |
| WorldForgeRuntime | plugin_module | false | false | DECLARED — pending Lane 1 load handshake (NOT claimed available) |

UE 5.8 `Build.version`: Major 5, Minor 8, Patch 0, CL 55116800, `++UE5+Release-5.8`.

## Known-gaps / blockers for the commander

- **Preservation refs EXIST** — no action needed: branch `release/ue5.7-v2.4-lts`
  and tag `worldforge-v2.4-ue5.7-final` are both present (verified via
  `git branch --list` / `git tag --list`). If they were ever deleted, the
  track-isolation gate emits a non-blocking known-gap; only the commander creates
  refs.
- **uproject EngineAssociation still "5.7" in the 5.8 worktree.** Intentional for
  now (host identity ≠ observed runtime; runtime-free gates unaffected). When
  runtime-EXECUTED 5.8 evidence is produced, set
  `WF_UE_CMD=D:/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe` (or flip
  EngineAssociation) so `observed_runtime_engine=8` and the meta reflects 5.8.
- **WorldForge plugin availability is DECLARED, not proven.** Lane 1 owns the real
  build/load handshake; the capability manifest deliberately does not claim it
  available. When Lane 1 lands the proof, its entry can move to
  required=true/available=true with a real `actual_version`.
- **Shield wiring:** Lane 2 does NOT own `v2_5_shield.py`. The four gates are ready
  for the shield to invoke as `--topology`, `--capability`, `--engine-identity`,
  `--track-isolation`. Each exits non-zero on failure and honors `--strict` / `STRICT=1`.

## Integration assumptions

- `failure_codes.FailureCode` carries the WF1011–1039 band (present; unchanged).
- `transition_contracts.CONTRACTS/CONTRACT_GROUPS/KNOWN_BAD_OWNING_CODE/TRANSITION_CODES`
  are stable (imported read-only). If a lane adds an 8th contract, topology's
  `registry_has_seven` (>=7) and partition checks still hold.
- Both worktrees present at `D:/Unreal Projects/WorldForge` (5.7) and
  `D:/Unreal Projects/WorldForge-UE58` (5.8); UE 5.8 at `D:/UE_5.8`.

## Limitations

- All four gates are RUNTIME-FREE: they prove schema/identity/topology/isolation
  and on-disk capability presence, NOT that the 5.8 editor opened a map or the
  plugin loaded. Those remain the (honestly-RED-until-real) conversion / plugin-
  build / regression / bridge gates owned by other lanes.
- Isolation is proven for the current two-worktree layout; it guards against a
  future shared-writable-dir regression via inline negatives but cannot foresee a
  config that redirects a dir outside the worktree root (would need path capture).

## git status (Lane 2 files, end of session — untracked, NOT committed)

```
?? docs/runbooks/ue57_ue58_transition.md
?? docs/status/v2_5_lane_2_status.md
?? tools/pipeline/transition_identity.py
?? tools/pipeline/validate_capability_manifest.py
?? tools/pipeline/validate_engine_identity.py
?? tools/pipeline/validate_track_isolation.py
?? tools/pipeline/validate_transition_topology.py
```

The commander commits. Lane 2 did not `git add`, `git commit`, or push.
