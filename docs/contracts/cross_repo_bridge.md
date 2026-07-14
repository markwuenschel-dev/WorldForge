# Cross-Repository Bridge Contract (v2.5 Foundation)

The bridge is the wire between **WorldForge** (this repo, the authoring/validation
plane) and a **Gloamstead** Unreal Engine **5.8** project (a separate repo — see
`memory/gloamstead-separate-repo.md`). It lets WorldForge ask the far side to
perform one bounded piece of work and get back an **auditable** result that can be
trusted *without trusting the far side*.

## Scope boundary (binding for v2.5)

v2.5 lays the bridge **FOUNDATION only**:

- The REQUEST and RESPONSE contracts below are defined and dogfooded.
- A rejecting **DRY PROBE** proves the contract end-to-end **offline**.
- **No live UE process is launched.** **No Gloamstead courtyard is authored.**
  **No Gloamstead compatibility is claimed.**

The only response v2.5 ever produces is a `rejected_dry_probe`
(`rejection_reason = "v2.5 lays the bridge contract only; no live invocation"`).
The **live Gloamstead fixture run is a later, explicitly gated wave** and requires
the far-side repo, a real UE 5.8 install, and a built `WorldForgeRuntime` plugin.

## REQUEST contract (`tools.bridge.BridgeRequest`)

The request is **pure intent** — building one launches nothing. All paths are
**project-relative**; no absolute/machine-specific paths.

| Field | Meaning |
| --- | --- |
| `operation_id` | Stable id for this bridge operation; the response MUST echo it. |
| `source_repository` | The calling repo (`WorldForge`). |
| `source_commit` | The calling repo commit (git SHA or `HEAD`). |
| `target_repository` | The far-side repo (`Gloamstead5_8`). |
| `target_commit` | The far-side commit to resolve against. |
| `target_engine` | Required engine — MUST be `"5.8"` (else WF1023). |
| `target_project` | Far-side project; MUST name a Gloamstead project (else WF1024). |
| `target_map` | Map the operation acts on (e.g. `Content/Maps/gloam_courtyard.umap`). |
| `required_plugin` | Plugin the operation depends on (`WorldForgeRuntime`). |
| `required_plugin_version` | Exact plugin version required (string match). |
| `requested_operation` | The bounded operation to perform. |
| `output_location` | Project-relative directory where evidence MUST land. |
| `timeout_seconds` | Timeout policy: the far side MUST abort past this budget and return `failure` rather than hang. |

## RESPONSE contract (`tools.bridge.BridgeResponse`)

The response carries everything needed to audit the result **without trusting it**.

| Field | Meaning |
| --- | --- |
| `operation_id` | MUST equal the request's `operation_id` (else WF1030). |
| `resolved_target_repository` | The repo the far side actually resolved. |
| `resolved_target_commit` | The commit the far side actually checked out. |
| `observed_engine` | Engine the far side actually ran on (`None` for a dry probe). |
| `observed_project` | Project actually opened. |
| `observed_map` | Map actually loaded. |
| `observed_plugin` | Plugin actually present/loaded. |
| `plugin_capability_manifest` | The far side's plugin capabilities (list; empty for a dry probe). |
| `process_exit_status` | `not_invoked` \| `success` \| `failure`. A `success` claim with no evidence is WF1028. |
| `evidence_paths` | Project-relative evidence paths (an absolute/foreign path is WF1029). |
| `evidence_hashes` | Content hashes of the evidence, for tamper/staleness detection. |
| `failure_classification` | How the operation is classified (`rejected_dry_probe` in v2.5). |
| `evidence_operation_id` | Which operation actually produced the evidence; a drift from `operation_id` is stale reuse (WF1026). |

## Probe report shape (`GloamBridgeProbe`, `wf.transition.gloam_bridge_probe.v1`)

`dry_probe(request)` projects the request + response into the **GloamBridgeProbe**
contract defined in `tools/pipeline/transition_contracts.py` (the honesty gate).
Required fields: `probe_id`, `operation_id`, `target_engine`, `target_project`,
`probe_result`, `plugin_present`, `map_present`, `evidence_entries`,
`schema_version`. The report additionally carries `meta` (see below),
`report_type`, `created_by`, `created_at`, and `rejection_reason`.

### Meta convention (binding)

The dry-probe report attaches its meta via `report_meta.build_meta(extra=...)`
with, because a dry probe performs **no live run**:

```
declared_target_engine   = "5.8"
observed_runtime_engine  = None
runtime_execution_required = False
runtime_executed         = False
```

## Failure classification (WF1023–WF1030)

| Code | Symbol | Rejected when |
| --- | --- | --- |
| WF1023 | `BRIDGE_WRONG_ENGINE` | `target_engine != "5.8"`. |
| WF1024 | `BRIDGE_WRONG_PROJECT` | `target_project` does not name a Gloamstead project. |
| WF1025 | `BRIDGE_ABSENT_PLUGIN` | `probe_result="ready"` but `plugin_present` is not `True`. |
| WF1026 | `BRIDGE_STALE_PLUGIN` | Evidence reused from a prior operation (`evidence_operation_id` drift). |
| WF1027 | `BRIDGE_MAP_MISSING` | `probe_result="ready"` but `map_present` is not `True`. |
| WF1028 | `BRIDGE_EMPTY_EVIDENCE` | A probe/response that claims to have looked (or claims `success`) carries no evidence. |
| WF1029 | `BRIDGE_ABSOLUTE_PATH_LEAK` | Any evidence path is absolute/foreign (not project-relative). |
| WF1030 | `BRIDGE_OPERATION_ID_MISMATCH` | Response `operation_id` != request `operation_id`. |

The single-object `GloamBridgeProbe` contract owns WF1023/1024/1025/1027/1028/1029.
The request↔response **pair** invariants (`tools.bridge.validate_bridge_response`)
own WF1026 and WF1030 (and re-assert 1028/1029/1023 across the pair), because those
cannot be seen from a single probe object.

## Tooling

- `tools/bridge/` — self-contained package: `schema.py` (request/response
  dataclasses + factories), `probe.py` (`dry_probe`, `dry_probe_response`,
  `validate_bridge_response`). Stdlib + shared `report_meta`/`failure_codes`
  only; never launches a process, never writes a file.
- `tools/pipeline/gloam_bridge_probe.py` — offline CLI: builds a Gloamstead 5.8
  request, runs the dry probe, writes
  `procedural/reports/ue5_8/gloam/gloam_bridge_probe_report.json`.
- `tools/pipeline/validate_gloam_bridge.py` — the shield `--bridge` gate: dogfoods
  the contract, validates the real dry-probe report, and rejects the negatives.

## What the live fixture wave still needs

- The Gloamstead repo present locally on UE 5.8, with a real courtyard map.
- A built `WorldForgeRuntime` plugin loadable inside the Gloamstead project.
- A real far-side invocation path producing `process_exit_status=success` with
  non-empty, hash-verified, project-relative `evidence_paths` — at which point a
  `probe_result="ready"` response becomes legal (and must satisfy WF1025/1027).
