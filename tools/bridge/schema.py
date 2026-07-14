#!/usr/bin/env python3
"""tools/bridge/schema.py — v2.5 cross-repository bridge REQUEST/RESPONSE contract.

Two dataclasses model the wire between WorldForge (this repo) and a Gloamstead
UE 5.8 project:

* ``BridgeRequest``  — everything the caller must state to ask the far side to do
  a bounded piece of work: which repos/commits, which engine, which project/map,
  which plugin (+ version), the requested operation, where output must land, and
  a timeout policy. The request is pure intent; building one launches nothing.

* ``BridgeResponse`` — everything the far side must return so the result is
  auditable *without trusting it*: the resolved target repo/commit it actually
  saw, the observed engine/project/map/plugin, a plugin capability manifest, the
  process exit status, evidence paths + hashes, and a failure classification.

v2.5 SCOPE BOUNDARY: this is the bridge FOUNDATION. The only response v2.5 ever
produces is a *rejected dry probe* (see probe.py). No live invocation, no
Gloamstead courtyard, no compatibility claim.

Self-contained: stdlib only. Every field is always present on ``to_dict()`` so an
absent key is itself an integrity smell (same discipline as report_meta).
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# The probe report shape is the GloamBridgeProbe contract in
# transition_contracts.py (RT_GLOAM_BRIDGE). We mirror its literal here to stay
# self-contained; a divergence is caught by the dogfood in validate_gloam_bridge.py.
BRIDGE_SCHEMA_VERSION = "wf.transition.gloam_bridge_probe.v1"

# The bridge targets Gloamstead on UE 5.8. Any other engine is WF1023.
BRIDGE_ENGINE = "5.8"

# Probe results — mirror BRIDGE_RESULTS in transition_contracts.py.
PROBE_RESULT_REJECTED = "rejected_dry_probe"
PROBE_RESULT_READY = "ready"
PROBE_RESULTS = (PROBE_RESULT_REJECTED, PROBE_RESULT_READY)

# Process exit status vocabulary for a BridgeResponse. In v2.5 only NOT_INVOKED
# is ever emitted (the dry probe never launches a process).
EXIT_NOT_INVOKED = "not_invoked"
EXIT_SUCCESS = "success"
EXIT_FAILURE = "failure"
EXIT_STATUSES = (EXIT_NOT_INVOKED, EXIT_SUCCESS, EXIT_FAILURE)


@dataclass
class BridgeRequest:
    """The bridge REQUEST contract (pure intent; building one launches nothing)."""

    operation_id: str
    source_repository: str
    source_commit: str
    target_repository: str
    target_commit: str
    target_engine: str
    target_project: str
    target_map: str
    required_plugin: str
    required_plugin_version: str
    requested_operation: str
    output_location: str
    timeout_seconds: int = 300

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BridgeResponse:
    """The bridge RESPONSE contract (auditable without trusting the far side)."""

    operation_id: str
    resolved_target_repository: Optional[str]
    resolved_target_commit: Optional[str]
    observed_engine: Optional[str]
    observed_project: Optional[str]
    observed_map: Optional[str]
    observed_plugin: Optional[str]
    plugin_capability_manifest: List[Dict[str, Any]] = field(default_factory=list)
    process_exit_status: str = EXIT_NOT_INVOKED
    evidence_paths: List[str] = field(default_factory=list)
    evidence_hashes: List[str] = field(default_factory=list)
    failure_classification: Optional[str] = None
    # Provenance: which operation actually produced the evidence. If this drifts
    # from operation_id the evidence was reused/stale (WF1026).
    evidence_operation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_request(**over: Any) -> BridgeRequest:
    """Build a bridge request targeting a Gloamstead UE 5.8 project.

    Defaults describe the canonical v2.5 target (Gloamstead 5.8) so callers only
    override what they must. All paths are project-relative — no machine paths.
    """
    d: Dict[str, Any] = dict(
        operation_id="op_v2_5_gloam_bridge_0001",
        source_repository="WorldForge",
        source_commit="HEAD",
        target_repository="Gloamstead5_8",
        target_commit="HEAD",
        target_engine=BRIDGE_ENGINE,
        target_project="Gloamstead5_8",
        target_map="Content/Maps/gloam_courtyard.umap",
        required_plugin="WorldForgeRuntime",
        required_plugin_version="2.5.0",
        requested_operation="materialize_courtyard_probe",
        output_location="procedural/reports/ue5_8/gloam",
        timeout_seconds=300,
    )
    d.update(over)
    return BridgeRequest(**d)


def build_response(request: BridgeRequest, **over: Any) -> BridgeResponse:
    """Build a bridge response keyed to a request's operation_id.

    v2.5 default is the honest dry-probe response: nothing was invoked, nothing
    was observed, exit status is ``not_invoked``. Overrides let tests model the
    dishonest responses the validator must reject.
    """
    d: Dict[str, Any] = dict(
        operation_id=request.operation_id,
        resolved_target_repository=None,
        resolved_target_commit=None,
        observed_engine=None,
        observed_project=None,
        observed_map=None,
        observed_plugin=None,
        plugin_capability_manifest=[],
        process_exit_status=EXIT_NOT_INVOKED,
        evidence_paths=[],
        evidence_hashes=[],
        failure_classification=PROBE_RESULT_REJECTED,
        evidence_operation_id=request.operation_id,
    )
    d.update(over)
    return BridgeResponse(**d)
