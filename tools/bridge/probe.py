#!/usr/bin/env python3
"""tools/bridge/probe.py — v2.5 rejecting DRY probe + request<->response invariants.

``dry_probe(request)`` produces a GloamBridgeProbe-shaped report (the
transition_contracts.GloamBridgeProbe contract) that honestly REJECTS: no live UE
process is launched, no plugin is present, no map is present. It exists so the
bridge contract can be proven end-to-end offline, long before any Gloamstead
courtyard exists.

``validate_bridge_response(request, response)`` enforces the request<->response
invariants the single-object GloamBridgeProbe contract cannot see (it validates
one probe object, not the pair): operation_id continuity (WF1030), evidence
freshness (WF1026), evidence presence under a claimed successful invocation
(WF1028), and absolute-path leaks in response evidence (WF1029).

Self-contained: stdlib + the shared report_meta hashing and failure_codes
registry. Never launches a process, never writes a file.
"""

import re
import sys
from pathlib import Path

# report_meta / failure_codes live in tools/pipeline (shared infra). Import them
# read-only so hashing + WF codes stay consistent with the rest of the platform.
_PIPELINE = Path(__file__).resolve().parents[2] / "tools" / "pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

from failure_codes import FailureCode as C  # noqa: E402
from report_meta import hash_text  # noqa: E402

from .schema import (  # noqa: E402
    BRIDGE_ENGINE,
    BRIDGE_SCHEMA_VERSION,
    PROBE_RESULT_REJECTED,
    EXIT_NOT_INVOKED,
    EXIT_SUCCESS,
    BridgeRequest,
    BridgeResponse,
    build_response,
)

# The single rejection reason v2.5 ever emits — auditable and stable.
REJECTION_REASON = "v2.5 lays the bridge contract only; no live invocation"

# An absolute-path leak: a Windows drive-letter path or a POSIX root path. Mirrors
# transition_contracts._ABS_PATH_RE so both agree on what "project-relative" means.
_ABS_PATH_RE = re.compile(r"^([A-Za-z]:[\\/]|[\\/])")

# Report type / created_by mirror the GloamBridgeProbe example in transition_contracts.
_REPORT_TYPE = BRIDGE_SCHEMA_VERSION
_CREATED_BY = "worldforge.v2.5"
_CREATED_AT = "2026-07-12T00:00:00+00:00"


def _is_rel(value):
    """True iff value is a string with no absolute-path leak."""
    return isinstance(value, str) and not _ABS_PATH_RE.match(value.strip())


def dry_probe_response(request: BridgeRequest) -> BridgeResponse:
    """The rich BridgeResponse for a dry probe: nothing invoked, nothing observed.

    The evidence path is the (project-relative) report the CLI will write, so the
    response points at where its own evidence lands. operation_id and
    evidence_operation_id both carry the request's operation_id (fresh, not stale).
    """
    evidence_rel = "{}/gloam_bridge_probe_report.json".format(
        request.output_location.rstrip("/"))
    return build_response(
        request,
        evidence_paths=[evidence_rel],
        evidence_hashes=[hash_text(evidence_rel)],
        failure_classification=PROBE_RESULT_REJECTED,
        process_exit_status=EXIT_NOT_INVOKED,
    )


def dry_probe(request: BridgeRequest) -> dict:
    """Produce a GloamBridgeProbe-shaped report that honestly rejects.

    probe_result="rejected_dry_probe", plugin_present=False, map_present=False,
    operation_id preserved from the request, evidence path project-relative. The
    caller (gloam_bridge_probe.py) attaches the meta block via build_meta(extra=).
    """
    resp = dry_probe_response(request)
    return {
        "probe_id": "gloam_bridge_dry_probe",
        "operation_id": request.operation_id,
        "target_engine": request.target_engine,
        "target_project": request.target_project,
        "probe_result": PROBE_RESULT_REJECTED,
        "rejection_reason": REJECTION_REASON,
        "plugin_present": False,
        "map_present": False,
        "evidence_entries": list(resp.evidence_paths),
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "report_type": _REPORT_TYPE,
        "created_by": _CREATED_BY,
        "created_at": _CREATED_AT,
    }


def validate_bridge_response(request: BridgeRequest, response: BridgeResponse):
    """Return a list of (name, ok, detail, code) request<->response invariant checks.

    These are the pair-level honesty gates the single-object GloamBridgeProbe
    contract cannot express. Mirrors the (name, ok, detail, code) tuple shape the
    rest of the platform's validators use so validation_report.collect can feed it.
    """
    ch = []
    # operation_id continuity: a response for a different operation is WF1030.
    ch.append(("bridge::operation_id_match",
               isinstance(response.operation_id, str)
               and response.operation_id == request.operation_id,
               "response operation_id {!r} != request {!r}".format(
                   response.operation_id, request.operation_id),
               C.BRIDGE_OPERATION_ID_MISMATCH))
    # evidence freshness: evidence produced for another operation is stale reuse (WF1026).
    ch.append(("bridge::evidence_fresh",
               response.evidence_operation_id == request.operation_id,
               "evidence_operation_id {!r} != operation_id {!r} (stale reuse)".format(
                   response.evidence_operation_id, request.operation_id),
               C.BRIDGE_STALE_PLUGIN))
    # a claimed successful invocation with no evidence is WF1028.
    claims_success = response.process_exit_status == EXIT_SUCCESS
    has_evidence = bool(response.evidence_paths)
    ch.append(("bridge::success_implies_evidence",
               not (claims_success and not has_evidence),
               "process_exit_status=success but evidence_paths is empty",
               C.BRIDGE_EMPTY_EVIDENCE))
    # no absolute / foreign path in the response evidence (WF1029).
    leaks = [p for p in (response.evidence_paths or []) if not _is_rel(p)]
    ch.append(("bridge::no_abs_path_leak",
               not leaks,
               "response evidence leaks absolute path(s): {}".format(leaks[:2]),
               C.BRIDGE_ABSOLUTE_PATH_LEAK))
    # target engine sanity mirrored on the request side (WF1023) — keeps the pair
    # honest even if a caller hand-builds a request off-contract.
    ch.append(("bridge::request_engine_5_8",
               request.target_engine == BRIDGE_ENGINE,
               "request target_engine must be {!r} (got {!r})".format(
                   BRIDGE_ENGINE, request.target_engine),
               C.BRIDGE_WRONG_ENGINE))
    return ch
