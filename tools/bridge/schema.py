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

v2.6 SEMANTIC-AUTHORITY BOUNDARY: WorldForge owns *capability*, the caller owns
*intent*. A default that names a specific target-game asset is therefore a bug in
this module, not a convenience: it lets WorldForge silently choose a subject the
caller never asked for. ``target_map`` consequently has NO default and
``build_request`` fails closed without it, and the request now carries the
caller's already-resolved ``subject`` rather than leaving WorldForge to find one.

Self-contained: stdlib only. Every field is always present on ``to_dict()`` so an
absent key is itself an integrity smell (same discipline as report_meta). That
applies to the v2.6 additions too: ``subject`` and the observed_* echo fields are
always emitted, defaulting to ``None`` to state "not carried" explicitly rather
than by omission.
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

# The plugin the bridge requires in the target project. This is the plugin's real
# name — ``Plugins/WorldForge/WorldForge.uplugin`` (FriendlyName "WorldForge"), and
# the name Gloamstead5_8.uproject enables. There has never been a "WorldForgeRuntime"
# plugin; the modules inside are WorldForgeCore and WorldForgeEd.
BRIDGE_PLUGIN_NAME = "WorldForge"

# VersionName in WorldForge.uplugin. Not the WorldForge *pipeline* version (v2.5/v2.6)
# — conflating the two is how a request comes to demand a plugin build that has never
# existed.
BRIDGE_PLUGIN_VERSION = "0.1.0"

# A neutral requested_operation. The caller states what it actually wants; this
# default names no target-game asset and no target-game feature.
DEFAULT_REQUESTED_OPERATION = "bridge_probe"


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
    # A far-side map is named by its UE PACKAGE path ("/Game/Maps/Foo"), not by a
    # content-file path ("Content/Maps/Foo.umap"): the far side resolves packages,
    # not files. The empty string is a legal, explicit "this operation needs no map"
    # — but it must be *stated*, never defaulted (see build_request).
    target_map: str
    required_plugin: str
    required_plugin_version: str
    requested_operation: str
    output_location: str
    timeout_seconds: int = 300
    # v2.6 — the caller's ALREADY-RESOLVED survey subject, carried opaquely.
    # Shape is SceneSurveySubject (tools/pipeline/scene_survey_contracts.py). It is
    # carried as a plain dict on purpose: this module is stdlib-only and must not
    # import the pipeline contracts, so it transports the subject without ever being
    # able to interpret — or invent — one. ``None`` means no subject was carried.
    subject: Optional[Dict[str, Any]] = None
    # v2.6 — the caller's pin on the plugin SOURCE tree it expects the far side to
    # be running (see paths.resolve_plugin_source_hash). ``None`` means the caller
    # stated no pin; a non-matching hash is WF1026 (stale plugin).
    required_plugin_source_hash: Optional[str] = None

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
    # v2.6 — the far side's ECHO of the subject it actually anchored on. These are
    # observations, never requests: the pair validator compares them against
    # request.subject so "WorldForge surveyed what the caller asked for" becomes a
    # checkable claim instead of an assumption. ``None`` means not observed.
    resolved_subject_id: Optional[str] = None
    observed_anchor_location: Optional[List[float]] = None
    observed_anchor_object_path: Optional[str] = None
    observed_map_asset_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RequestContractError(ValueError):
    """Raised when a bridge request omits something only the caller can state."""


# Arguments WorldForge must never invent on the caller's behalf. Each names
# something in the CALLER's project; a default here would be WorldForge choosing
# the caller's intent, which is the exact authority inversion v2.6 removes.
CALLER_OWNED_FIELDS = ("target_map",)


def build_request(**over: Any) -> BridgeRequest:
    """Build a bridge request. ``target_map`` is REQUIRED — there is no default.

    Defaults here describe only what WorldForge legitimately owns: the engine it
    targets, the plugin it requires, its own report location, its own timeout. They
    deliberately name NO asset inside the caller's project.

    ``target_map`` must be supplied by the caller as a UE package path
    ("/Game/Maps/Foo"). The empty string is accepted as an explicit "no map needed"
    — the rule is that the caller must *state* it, not that it must be non-empty.
    Omitting it raises :class:`RequestContractError` (fail closed) rather than
    silently surveying a map nobody asked for.

    All paths are project-relative — no machine paths.
    """
    missing = [f for f in CALLER_OWNED_FIELDS if f not in over]
    if missing:
        raise RequestContractError(
            "build_request() is missing caller-owned argument(s) {}: WorldForge owns "
            "capability, the caller owns intent, so there is no default for these. "
            "Pass target_map as a UE package path ('/Game/Maps/Foo'), or '' to state "
            "explicitly that the operation needs no map.".format(missing))
    d: Dict[str, Any] = dict(
        operation_id="op_v2_5_gloam_bridge_0001",
        source_repository="WorldForge",
        source_commit="HEAD",
        target_repository="Gloamstead5_8",
        target_commit="HEAD",
        target_engine=BRIDGE_ENGINE,
        target_project="Gloamstead5_8",
        required_plugin=BRIDGE_PLUGIN_NAME,
        required_plugin_version=BRIDGE_PLUGIN_VERSION,
        requested_operation=DEFAULT_REQUESTED_OPERATION,
        output_location="procedural/reports/ue5_8/gloam",
        timeout_seconds=300,
        subject=None,
        required_plugin_source_hash=None,
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
        # Nothing ran, so nothing was observed. Stated as explicit None rather than
        # echoed from the request: echoing the request here would manufacture the
        # very agreement the pair validator exists to test.
        resolved_subject_id=None,
        observed_anchor_location=None,
        observed_anchor_object_path=None,
        observed_map_asset_path=None,
    )
    d.update(over)
    return BridgeResponse(**d)
