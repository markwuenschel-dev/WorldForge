#!/usr/bin/env python3
"""tools/bridge/capability_ops.py — the "one door, N ops" capability registry.

The bridge has exactly one door: a caller states a ``requested_operation`` in a
:class:`~tools.bridge.schema.BridgeRequest`, and WorldForge executes it. Before
this module existed, the scene-survey operation was wired into its runner by hand
— the runner knew which far-side script to launch, which payload fields mattered,
and how to shape the response, all inline. That is fine for exactly one operation
and becomes an authority leak at two: each new operation would re-implement (and
quietly re-interpret) the same three decisions.

This registry names those three decisions once, per operation:

    requested_operation  ->  ( payload validator, far-side script, response builder )

* **payload validator** — the caller-supplied intent for this operation, checked
  against the operation's own contract. It returns the house
  ``(name, ok, detail, code)`` tuple list, so a failing rail names itself and its
  owning WF code. It NEVER repairs, defaults, or infers a missing field: an
  operation whose payload is unresolved is rejected, not completed on the
  caller's behalf.
* **far-side script** — the repo-relative path of the script handed to the target
  editor via ``-ExecutePythonScript=``. Stored here rather than in the runner so
  "which code runs inside the caller's project" is a registry fact, not a
  hard-coded constant in whichever runner happened to launch it.
* **response builder** — folds the far side's OBSERVED echo into a
  :class:`~tools.bridge.schema.BridgeResponse`. Observations only: the builder is
  deliberately not given the request's subject to copy from, because echoing the
  request here would manufacture the very agreement the pair validators exist to
  test (same discipline as ``schema.build_response``).

Dependency discipline: stdlib only **at import time**. The scene-survey payload
validator needs ``tools/pipeline/scene_survey_contracts.py``, which is a pipeline
module, so that import is deferred into the validator body. Keeping it out of the
module header is what lets a UE-side or minimal-environment consumer import this
registry to learn *which* operations exist without dragging the pipeline in.

Self-contained: stdlib + (lazily) the shared pipeline contracts. Never launches a
process and never writes a file.

Discovery (what operations does this door accept?):
    cd tools && PYTHONUTF8=1 python -m bridge.capability_ops --list

Self-dogfood (relative imports, so it runs as a module, not a script):
    cd tools && PYTHONUTF8=1 python -m bridge.capability_ops
"""

import sys
from collections import namedtuple
from pathlib import Path

from .schema import EXIT_FAILURE, EXIT_SUCCESS, build_response  # noqa: F401

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PIPELINE = _REPO_ROOT / "tools" / "pipeline"

# ---------------------------------------------------------------------------
# Operation names. A requested_operation that is not one of these is refused —
# there is no "unknown operation, try our best" path, because guessing what a
# caller meant is exactly the authority inversion v2.6 removes.
# ---------------------------------------------------------------------------
OP_SCENE_SURVEY = "scene_survey"


class UnknownCapabilityOperation(KeyError):
    """Raised when a requested_operation has no entry in :data:`CAPABILITY_OPS`."""


CapabilityOp = namedtuple("CapabilityOp", (
    "operation",           # the requested_operation string
    "summary",             # one line, for operator output
    "far_side_script",     # repo-relative posix path of the -ExecutePythonScript target
    "validate_payload",    # (payload, strict=False) -> [(name, ok, detail, code), ...]
    "build_response",      # (request, far_doc, **over) -> BridgeResponse
    "payload_keys",        # the payload keys this operation reads (documented surface)
))


def _pipeline():
    """Import the pipeline contract spine + failure codes (deferred on purpose).

    Deferred so importing this registry costs nothing but stdlib; see the module
    docstring. The sys.path insert mirrors the one every pipeline consumer does.
    """
    if str(_PIPELINE) not in sys.path:
        sys.path.insert(0, str(_PIPELINE))
    import scene_survey_contracts as SS  # noqa: E402
    from failure_codes import FailureCode as C  # noqa: E402
    return SS, C


# =========================================================================== #
# scene_survey
# =========================================================================== #
_SCENE_SURVEY_PAYLOAD_KEYS = ("subject", "captures")


def validate_scene_survey_payload(payload, strict=False):
    """Validate the caller's scene-survey intent. Returns house check tuples.

    The payload is ``{"subject": <SceneSurveySubject>, "captures": [<kind>, ...]}``.

    ``subject`` is delegated verbatim to
    ``scene_survey_contracts.validate_scene_survey_subject`` — this module does not
    re-implement (and so cannot quietly relax) a single subject rail. Its check
    names are re-prefixed ``ss::`` -> ``op::subject::`` so a failing rail stays
    unique and self-describing when folded into a larger run.

    ``captures`` is capture-OPT-IN: an absent or empty list is legal and means "do
    not render". It is validated as a subset of the bounded CAMERA_KINDS so a typo
    ("topdown") is refused rather than silently producing no capture.
    """
    SS, C = _pipeline()
    ch = []
    if not isinstance(payload, dict):
        return [("op::payload_is_object", False,
                 "scene_survey payload must be an object (got {!r})".format(
                     type(payload).__name__),
                 C.SCENE_SURVEY_SUBJECT_UNRESOLVED)]
    sub = payload.get("subject")
    ch.append(("op::subject_is_object", isinstance(sub, dict),
               "scene_survey requires a caller-resolved 'subject' object "
               "(got {!r}) — WorldForge must never resolve one itself".format(
                   type(sub).__name__),
               C.SCENE_SURVEY_SUBJECT_UNRESOLVED))
    if isinstance(sub, dict):
        for (n, ok, detail, code) in SS.validate_scene_survey_subject(sub, strict=strict):
            head, sep, tail = n.partition("::")
            ch.append(("op::subject::" + (tail if sep and len(head) == 2 else n),
                       ok, detail, code))
    caps = payload.get("captures", [])
    caps_ok = (isinstance(caps, list) and all(isinstance(x, str) for x in caps)
               and all(x in SS.CAMERA_KINDS for x in caps))
    ch.append(("op::captures_subset", caps_ok,
               "captures must be a (possibly empty) subset of {} — capture is "
               "opt-in (got {!r})".format(list(SS.CAMERA_KINDS), caps),
               C.SCENE_SURVEY_UNKNOWN_CAPTURE))
    unknown = [k for k in payload if k not in _SCENE_SURVEY_PAYLOAD_KEYS]
    if strict:
        ch.append(("op::no_unknown_payload_keys", not unknown,
                   "unknown scene_survey payload key(s): {}".format(unknown[:6]),
                   C.SCENE_SURVEY_SUBJECT_UNRESOLVED))
    return ch


def build_scene_survey_response(request, far_doc, **over):
    """Fold the far side's OBSERVED echo into a BridgeResponse.

    Every field set here is an observation the far side reported about the process
    it actually ran. Nothing is copied from ``request``: the pair validators
    (``probe.validate_bridge_response`` for the bridge, and
    ``scene_survey_contracts.validate_subject_binding`` for the subject) compare
    request against response, and a builder that echoed the request would make
    both of them vacuous.

    ``far_doc`` is the far-side JSON dict (possibly ``{}`` when the far side never
    wrote one — in which case every observation is honestly ``None``).
    """
    far = far_doc if isinstance(far_doc, dict) else {}
    uproject = far.get("resolved_uproject") or ""
    observed_project = (uproject.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
                        or None)
    d = dict(
        observed_engine=far.get("observed_engine_version"),
        observed_project=observed_project,
        observed_map=far.get("map") or None,
        observed_map_asset_path=far.get("map") or None,
        resolved_subject_id=far.get("subject_id"),
        observed_anchor_location=far.get("observed_anchor_location"),
        observed_anchor_object_path=far.get("observed_anchor_object_path"),
        process_exit_status=EXIT_FAILURE if far.get("error") else EXIT_SUCCESS,
        evidence_operation_id=far.get("operation_id"),
    )
    d.update(over)
    return build_response(request, **d)


# =========================================================================== #
# The registry itself.
# =========================================================================== #
CAPABILITY_OPS = {
    OP_SCENE_SURVEY: CapabilityOp(
        operation=OP_SCENE_SURVEY,
        summary="read-only spatial survey of a caller-resolved subject in a target map",
        far_side_script="tools/bridge/scene_survey_far_side.py",
        validate_payload=validate_scene_survey_payload,
        build_response=build_scene_survey_response,
        payload_keys=_SCENE_SURVEY_PAYLOAD_KEYS,
    ),
}


def get_op(requested_operation):
    """Return the :class:`CapabilityOp` for ``requested_operation``, or raise.

    Fails closed. There is no nearest-match, no default operation, and no
    "unregistered but probably fine" path: an operation WorldForge does not
    implement is a capability the caller cannot have, and saying so is the honest
    answer (the caller maps this to WF1011_CAPABILITY_UNAVAILABLE).
    """
    try:
        return CAPABILITY_OPS[requested_operation]
    except KeyError:
        raise UnknownCapabilityOperation(
            "no capability registered for requested_operation {!r}; registered: {}"
            .format(requested_operation, sorted(CAPABILITY_OPS)))


def far_side_script_path(op, repo_root=None):
    """Absolute path to an operation's far-side script (repo-relative in the registry)."""
    return Path(repo_root or _REPO_ROOT) / op.far_side_script


# ---------------------------------------------------------------------------
# Discovery. Until now the only way to learn what this door accepts was to ask
# for an operation that does NOT exist and read the name list out of the
# resulting exception message. That is a diagnostic, not an API: a caller in
# another repository should be able to enumerate the supported operations
# without provoking a failure and without knowing a script filename.
# ---------------------------------------------------------------------------
def list_ops():
    """Every registered operation name, sorted. Stdlib-only, import-cheap."""
    return sorted(CAPABILITY_OPS)


def describe_op(operation, repo_root=None):
    """A JSON-serializable description of one registered operation.

    Deliberately excludes the callables: a description is for a caller deciding
    whether an operation exists and what it needs, not a handle to invoke it.
    Invocation still goes through ``get_op``.
    """
    op = get_op(operation)
    script = far_side_script_path(op, repo_root)
    return {
        "operation": op.operation,
        "summary": op.summary,
        "far_side_script": op.far_side_script,
        "far_side_script_present": script.is_file(),
        "payload_keys": list(op.payload_keys),
    }


def describe_ops(repo_root=None):
    """Describe every registered operation, in sorted order."""
    return [describe_op(name, repo_root) for name in list_ops()]


if __name__ == "__main__":
    # Discovery mode: enumerate the door's operations without provoking a failure.
    # Kept above the dogfood so `--list` needs no pipeline import at all.
    if "--list" in sys.argv[1:]:
        import json as _json
        print(_json.dumps(describe_ops(), indent=2, sort_keys=True))
        sys.exit(0)

    # Self-dogfood: every registered op resolves, its far-side script exists on
    # disk, its validator accepts the contract's own valid example and REJECTS a
    # known-bad for the right owning code (rejection for the wrong reason is not
    # real coverage).
    _SS, _C = _pipeline()
    _ok = True
    for _name, _op in sorted(CAPABILITY_OPS.items()):
        if _op.operation != _name:
            print("REGISTRY FAIL {}: operation field is {!r}".format(_name, _op.operation))
            _ok = False
        if not far_side_script_path(_op).is_file():
            print("REGISTRY FAIL {}: far-side script missing: {}".format(
                _name, _op.far_side_script))
            _ok = False
    # The discovery API must describe the registry it claims to describe — a
    # catalogue that silently omits an operation is worse than none, because a
    # caller would conclude the capability does not exist.
    if list_ops() != sorted(CAPABILITY_OPS):
        print("DISCOVERY FAIL: list_ops() {} != registry {}".format(
            list_ops(), sorted(CAPABILITY_OPS)))
        _ok = False
    _desc = describe_ops()
    if [d["operation"] for d in _desc] != list_ops():
        print("DISCOVERY FAIL: describe_ops() does not cover list_ops()")
        _ok = False
    for _d in _desc:
        if not _d["far_side_script_present"]:
            print("DISCOVERY FAIL {}: described far-side script is absent: {}".format(
                _d["operation"], _d["far_side_script"]))
            _ok = False
        if not _d["payload_keys"]:
            print("DISCOVERY FAIL {}: no payload keys described".format(_d["operation"]))
            _ok = False
    _good = {"subject": _SS._example_scene_survey_subject(), "captures": []}
    _gf = [c for c in validate_scene_survey_payload(_good, strict=True) if not c[1]]
    if _gf:
        print("DOGFOOD FAIL scene_survey: valid payload rejected: {}".format(
            [c[0] for c in _gf]))
        _ok = False
    _bad = {"subject": _SS._example_scene_survey_subject(resolved_by="worldforge"),
            "captures": []}
    _bf = {c[3] for c in validate_scene_survey_payload(_bad, strict=True) if not c[1]}
    if _C.SCENE_SURVEY_SUBJECT_INFERRED not in _bf:
        print("DOGFOOD FAIL scene_survey: a WorldForge-resolved subject was not "
              "rejected for {} (got {})".format(
                  _C.SCENE_SURVEY_SUBJECT_INFERRED, sorted(_bf)))
        _ok = False
    _badcap = {"subject": _SS._example_scene_survey_subject(), "captures": ["topdown"]}
    _cf = {c[3] for c in validate_scene_survey_payload(_badcap, strict=True) if not c[1]}
    if _C.SCENE_SURVEY_UNKNOWN_CAPTURE not in _cf:
        print("DOGFOOD FAIL scene_survey: unknown capture kind not rejected for {} "
              "(got {})".format(_C.SCENE_SURVEY_UNKNOWN_CAPTURE, sorted(_cf)))
        _ok = False
    print("CAPABILITY-OPS SELF-DOGFOOD: {} ({} op(s))".format(
        "PASS" if _ok else "FAIL", len(CAPABILITY_OPS)))
    sys.exit(0 if _ok else 1)
