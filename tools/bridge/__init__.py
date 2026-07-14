#!/usr/bin/env python3
"""tools.bridge — WorldForge v2.5 cross-repository bridge FOUNDATION.

v2.5 lays the WorldForge -> Gloamstead (UE 5.8) bridge *contract* and a rejecting
DRY probe only. No live UE process is launched, no Gloamstead courtyard is
authored, and no Gloamstead compatibility is claimed here. The live fixture run
is a later, explicitly gated wave.

Public surface:
    schema.BridgeRequest / build_request(...)   the bridge REQUEST contract
    schema.BridgeResponse / build_response(...)  the bridge RESPONSE contract
    schema.BRIDGE_SCHEMA_VERSION / BRIDGE_ENGINE / PROBE_* constants
    probe.dry_probe(request)                     GloamBridgeProbe-shaped report
    probe.dry_probe_response(request)            the rich BridgeResponse
    probe.validate_bridge_response(req, resp)    request<->response invariants

The package is self-contained (stdlib + the shared report_meta/failure_codes
infra). It never imports Unreal, never shells out, and never writes files.
"""

from . import schema  # noqa: F401
from . import probe   # noqa: F401
from .schema import (  # noqa: F401
    BRIDGE_SCHEMA_VERSION,
    BRIDGE_ENGINE,
    PROBE_RESULT_REJECTED,
    PROBE_RESULT_READY,
    PROBE_RESULTS,
    BridgeRequest,
    BridgeResponse,
    build_request,
    build_response,
)
from .probe import (  # noqa: F401
    dry_probe,
    dry_probe_response,
    validate_bridge_response,
    REJECTION_REASON,
)

__all__ = [
    "schema", "probe",
    "BRIDGE_SCHEMA_VERSION", "BRIDGE_ENGINE",
    "PROBE_RESULT_REJECTED", "PROBE_RESULT_READY", "PROBE_RESULTS",
    "BridgeRequest", "BridgeResponse", "build_request", "build_response",
    "dry_probe", "dry_probe_response", "validate_bridge_response",
    "REJECTION_REASON",
]
