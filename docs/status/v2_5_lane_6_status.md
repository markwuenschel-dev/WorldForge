# v2.5 Lane 6 — Cross-Repository Bridge Foundation (status / handoff)

## Objective

Build the WorldForge → Gloamstead (UE 5.8) bridge **CONTRACT** + a rejecting
**DRY PROBE** + validator gate + negatives — the foundation only. **No live UE
process launched, no Gloamstead courtyard authored, no Gloamstead compatibility
claimed.** The live fixture run is a later, gated wave.

## Files created (this lane only)

- `tools/bridge/__init__.py` — package surface.
- `tools/bridge/schema.py` — `BridgeRequest` / `BridgeResponse` dataclasses +
  `build_request` / `build_response` factories; `BRIDGE_SCHEMA_VERSION`,
  `BRIDGE_ENGINE`, probe/exit constants.
- `tools/bridge/probe.py` — `dry_probe(request)` (GloamBridgeProbe-shaped report),
  `dry_probe_response(request)` (rich response), `validate_bridge_response(req,
  resp)` (request↔response invariants).
- `tools/pipeline/gloam_bridge_probe.py` — offline CLI; writes the probe report.
- `tools/pipeline/validate_gloam_bridge.py` — the shield `--bridge` gate.
- `docs/contracts/cross_repo_bridge.md` — the REQUEST/RESPONSE contract + scope
  boundary.
- `docs/status/v2_5_lane_6_status.md` — this file.
- `procedural/reports/ue5_8/gloam/` (machine-generated):
  `gloam_bridge_probe_report.json`, `validate_gloam_bridge_report.json`.

No files outside this lane were touched (`failure_codes.py`, `engine_identity.py`,
`transition_contracts.py`, the shield, and other lanes' files are untouched —
imported read-only).

## Contract dogfooded

The gate dogfoods the `GloamBridgeProbe` contract from `transition_contracts.py`
(valid example passes with 0 failures; known-bad rejected for its owning code
`WF1025_BRIDGE_ABSENT_PLUGIN`) and asserts the bridge package's schema literal
matches the contract's `RT_GLOAM_BRIDGE` (`wf.transition.gloam_bridge_probe.v1`),
so the two cannot drift.

## Exact commands + real output

```
$ PYTHONUTF8=1 python tools/pipeline/gloam_bridge_probe.py
[gloam-bridge-probe] DRY PROBE -> procedural/reports/ue5_8/gloam/gloam_bridge_probe_report.json
[gloam-bridge-probe]   probe_result   = rejected_dry_probe
[gloam-bridge-probe]   operation_id   = op_v2_5_gloam_bridge_0001
[gloam-bridge-probe]   target_engine  = 5.8
[gloam-bridge-probe]   target_project = Gloamstead5_8
[gloam-bridge-probe]   plugin_present = False map_present = False
[gloam-bridge-probe]   rejection      = v2.5 lays the bridge contract only; no live invocation
[gloam-bridge-probe]   runtime_executed = False (dry probe; no live run)

$ PYTHONUTF8=1 python tools/pipeline/validate_gloam_bridge.py --strict
[gloam-bridge] PASS — worldforge_vertical_slice (0 failure(s), 0 warning(s), strict=on)
EXIT=0     # 31/31 checks OK

$ PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_5_shield.py --strict --bridge
  [PASS] transition-contracts
  [PASS] gloam-bridge
v2.5 shield: GREEN — 2/2 gates passed
```

## Bridge gate GREEN proof (dry-probe contract)

The real dry-probe report passes the `GloamBridgeProbe` contract under strict
(`real::passes_contract` OK), carries the binding meta convention
(`declared_target_engine=5.8`, `observed_runtime_engine=None`,
`runtime_execution_required=False`, `runtime_executed=False` — all OK), and its
single evidence entry is project-relative
(`procedural/reports/ue5_8/gloam/gloam_bridge_probe_report.json`). Gate status
`ok`, 31/31 checks pass, exit 0.

## Negatives → WF-code map (each asserted rejected)

Single-object `GloamBridgeProbe` contract negatives:

| Fixture | WF code |
| --- | --- |
| wrong engine (`target_engine="5.7"`) | WF1023 BRIDGE_WRONG_ENGINE |
| wrong project (`target_project="WorldForge"`) | WF1024 BRIDGE_WRONG_PROJECT |
| plugin absent while `ready` | WF1025 BRIDGE_ABSENT_PLUGIN |
| map missing while `ready` | WF1027 BRIDGE_MAP_MISSING |
| exit-zero-but-evidence-missing (empty evidence) | WF1028 BRIDGE_EMPTY_EVIDENCE |
| absolute / foreign path leak | WF1029 BRIDGE_ABSOLUTE_PATH_LEAK |

Request↔response pair-invariant negatives (`validate_bridge_response`):

| Fixture | WF code |
| --- | --- |
| operation_id mismatch (response for a different op) | WF1030 BRIDGE_OPERATION_ID_MISMATCH |
| stale evidence reused (`evidence_operation_id` drift) | WF1026 BRIDGE_STALE_PLUGIN |

All eight are asserted with a two-part check per fixture (`::rejected` and
`::code`), so a fixture that silently greened, or rejected for the wrong code,
turns the gate RED.

## Scope boundary (no live run this wave)

- No live UE process launched; the probe runs fully offline.
- No Gloamstead courtyard authored; no Gloamstead compatibility claimed.
- The only response produced is `rejected_dry_probe`.
- The live fixture run is a **later gated wave** (see below).

## Integration assumptions

- Shield `--bridge` lane already points at
  `tools/pipeline/validate_gloam_bridge.py --strict` (v2_5_shield.py); no shield
  edit needed by this lane.
- Reads `transition_contracts` (GloamBridgeProbe), `failure_codes`,
  `report_meta`, `validation_report` read-only.
- The gate calls `gloam_bridge_probe.main([])` internally so it is self-priming:
  running the gate alone produces + validates the report.

## Limitations

- WF1026 (`BRIDGE_STALE_PLUGIN`) and WF1030 (`BRIDGE_OPERATION_ID_MISMATCH`) are
  enforced at the request↔response pair level (`validate_bridge_response`), not
  by the single-object `GloamBridgeProbe` contract — a lone probe object cannot
  see its originating request.
- `source_commit` / `target_commit` default to `HEAD`; the live wave should pin
  real SHAs.
- Evidence hashing hashes the evidence *path string* for the dry probe (no file
  content exists yet); the live wave must hash real evidence file bytes.

## What the live fixture wave still needs

- The Gloamstead repo present locally on UE 5.8 with a real courtyard map.
- A built `WorldForgeRuntime` plugin loadable inside the Gloamstead project.
- A real far-side invocation producing `process_exit_status=success` with
  non-empty, content-hashed, project-relative evidence — at which point a
  `probe_result="ready"` response becomes legal and must satisfy WF1025/1027.

## Git status

All lane files are untracked/new (`??`); nothing committed, added, or pushed:

```
?? docs/contracts/cross_repo_bridge.md
?? docs/status/v2_5_lane_6_status.md
?? procedural/reports/ue5_8/gloam/
?? tools/bridge/
?? tools/pipeline/gloam_bridge_probe.py
?? tools/pipeline/validate_gloam_bridge.py
```
