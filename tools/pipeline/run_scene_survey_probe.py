#!/usr/bin/env python3
r"""run_scene_survey_probe.py — v2.6 SceneSurveyForge operator command.

The single documented surface that runs a READ-ONLY scene survey against an external
UE 5.8 project. It boots the target project's editor headless, executes
tools/bridge/scene_survey_far_side.py inside it (which drives the compiled
USceneSurveyStatics primitives over the caller's subject), then DERIVES a
SceneSurveyReport from the far side's STRUCTURED ``raw_evidence`` bundle — without
trusting the far side (runtime_executed only when a real process returned 0 AND the
far side left its document behind; observed engine comes from the running editor,
never a config file).

WHERE REPORTED VALUES COME FROM (v2.6, changed)
===============================================
Every reported value is sourced from ``far["raw_evidence"]`` (the structured bundle
addressed by tools/pipeline/scene_survey_evidence.py:245-258) or from a structured
top-level far-side scalar. THE STDOUT ``WF_SURVEY_*`` MARKER LINES ARE DIAGNOSTIC
ONLY. A regex over human-readable editor log text is the weakest observation chain
available, and it may no longer SUPPLY a reported value — it survives solely as a
corroboration signal (``_channel_disagreements``), which can only ever CONTRADICT
the structured channel, never stand in for it.

Consequently: WHEN A STRUCTURED RECORD IS ABSENT, THE VALUE IS ``unknown``. It is
reported as ``None``, its evidence record is classified ``failed`` / ``unsupported``
/ ``not_requested`` with ``value=None``, and it is NEVER reconstructed from log text
and NEVER coerced to ``0`` or ``False``. ``meta.evidence`` carries the full
tri-state record for every reported field; ``meta.evidence_unknown_fields``
enumerates the ones nothing observed.

KNOWN CROSS-LANE COLLISION (stated, not papered over): the report contract
(scene_survey_contracts.REPORT_REQUIRED :647-664 / _REPORT_NULLABLE :671-672) still
demands a non-null int for ``support_samples_valid`` / ``unsupported_regions`` /
``edge_regions`` / ``proxy_owners`` and a non-null bool for ``proxies_disabled``,
while this pass has no structured channel that observes any of them. An honest
``unknown`` therefore makes the report fail its own contract, loudly and by name,
which is the correct direction: the previous code satisfied the contract by
asserting ``0`` / ``False`` / ``True``. Adding those fields to ``_REPORT_NULLABLE``
belongs to the contract lane.

OPERATION IDENTITY (v2.6, new)
==============================
Evidence is now published per OPERATION, not to one shared mutable filename:

    procedural/reports/scene_survey/runtime/operations/<operation_id>/
        far_side_run<N>.json        raw inputs
        scene_survey_report.json    the derived report (AUTHORITATIVE)
        operation_manifest.json     the seal, published LAST

Publication order is temp -> flush/validate -> atomic rename -> manifest LAST: a
manifest visible before its evidence would be a lie. The shared
``runtime/scene_survey_report.json`` is still written, but as a NON-AUTHORITATIVE
mirror for the existing runtime gate; the manifest binds the operation-scoped copy.
A single-writer lock is taken BEFORE every refusal path (all of which used to fire
before any cleanup ran) and released in a ``finally``. ``output_location`` is
confined to the repository (WF1130) before anything is created under it.

WHO CHOOSES THE SUBJECT (v2.6): the caller does, and only the caller. A survey is
requested with --request <BridgeRequest.json>, whose ``subject`` is an
already-resolved SceneSurveySubject. There is exactly ONE way to state a subject;
the legacy --map/--anchor pair cannot express a resolved subject and is REJECTED
rather than silently overridden, because a command that accepts two ways to say
where to look is a command that can look somewhere the caller did not ask about.
The far side VERIFIES that subject and echoes what it actually anchored on; this
side BINDS the two with validate_subject_binding (WF1107/WF1108).

Read-only w.r.t. the target: never saves the map, authors no permanent actor, and
places no persistent marker (marker CLEARANCE is trace-probed, never spawned). This
pass runs under -nullrhi and does the spatial work (enumeration + support sampling +
marker clearance). MeshForge proxy toggle needs a -game pass and is honestly
reported as UNOBSERVED — value None, never a zero. Camera capture is OPT-IN
(--capture, default none).

Before booting, the plugin SOURCE tree in the target project is hashed and compared
against the request's required_plugin_source_hash; a mismatch (or an unstated pin) is
WF1026 and the editor is NOT launched.

Determinism: --repeat N runs the survey N times and proves the STRUCTURED spatial
results are byte-identical (determinism_hash); a mismatch is WF1094.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/run_scene_survey_probe.py --smoke
    PYTHONUTF8=1 python tools/pipeline/run_v2_6_assembler_probes.py --strict
Live (single-writer against a real project):
    PYTHONUTF8=1 python tools/pipeline/run_scene_survey_probe.py \
        --project "<abs>/<Target>.uproject" \
        --request procedural/generated/scene_survey/requests/<operation_id>.json \
        --capture "" \
        --sample-radius-cm 3000 --sample-step-cm 100 --temporary-markers 3 \
        --repeat 2 --strict
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import scene_survey_contracts as SS  # noqa: E402
import scene_survey_evidence as SSE  # noqa: E402
import scene_survey_operation as OP  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta  # noqa: E402

# The shared, mutable "latest" location. It is a MIRROR now, not the authority:
# tools/pipeline/validate_scene_survey_runtime.py:49-50 still binds this one
# filename, so it keeps being written — but the manifest seals the operation-scoped
# copy under runtime/operations/<operation_id>/ and that is the evidence of record.
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "runtime"
LEGACY_REPORT = REPORT_DIR / "scene_survey_report.json"
FAR_SIDE = REPO_ROOT / "tools" / "bridge" / "scene_survey_far_side.py"

# The capability this command drives. The registry (tools/bridge/capability_ops.py)
# owns the mapping requested_operation -> (payload validator, far-side script,
# response builder); this module only asks it for the scene-survey entry.
OPERATION = "scene_survey"

# Collector names carried on evidence records, so every value states WHO measured it.
FAR_COLLECTOR = "scene_survey_far_side"
ASSEMBLER = "run_scene_survey_probe"
PATHS_COLLECTOR = "bridge.paths"

DEFAULT_OPERATION_ID = "op_v2_6_scene_survey_0001"

# DIAGNOSTIC ONLY. These parse the editor's human-readable log text. Nothing below
# may source a REPORTED value from them; they exist so the structured channel can be
# contradicted (WF1109), which is the one thing a weak channel is good for.
RE_SUPPORT = re.compile(
    r"WF_SURVEY_SUPPORT total=(\d+) valid=(\d+) unsupported=(\d+) edge=(\d+) "
    r"blocked=(\d+) trace_error=(\d+) unknown=(\d+)")
RE_ENUM = re.compile(r"WF_SURVEY_ENUM actors=(\d+) components=(\d+)")
RE_MARKER = re.compile(
    r"WF_SURVEY_MARKER .*grounded=(\d) footprint=(\d) overlap=(\d) "
    r"clearance=(\d) accepted=(\d)")

NO_STRUCTURED_SUPPORT_BREAKDOWN = (
    "the far side emits no per-class support breakdown: USceneSurveyStatics."
    "sample_survey_support returns only a TOTAL (scene_survey_far_side.py:1273) and "
    "the raw_evidence bundle carries no per-sample records. The valid/unsupported/"
    "edge split exists only in the WF_SURVEY_SUPPORT log line, which is a diagnostic "
    "channel and may not supply a reported value. Unobserved, therefore unknown — "
    "not zero.")


def _resolve_paths(args):
    """Resolve engine root + UnrealEditor-Cmd via the bridge ladder (arg->env->registry)."""
    from bridge import paths as P
    engine_root = P.resolve_engine_root(args.engine_root)
    ue_cmd = P.resolve_ue_cmd(engine_root.value, args.ue_cmd)
    return engine_root, ue_cmd


def _run_editor(ue_cmd, uproject, script, env_extra, timeout):
    """Launch the target project's editor headless; return (exit_code, stdout, secs)."""
    env = dict(os.environ)
    env.update(env_extra)
    env["PYTHONUTF8"] = "1"
    cmd = [
        str(ue_cmd),
        str(uproject).replace("\\", "/"),
        "-ExecutePythonScript={}".format(str(script).replace("\\", "/")),
        "-unattended", "-nopause", "-nosplash", "-nullrhi", "-stdout",
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, env=env, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), round(time.time() - t0, 2)
    except subprocess.TimeoutExpired as exc:
        return None, (exc.stdout or b"").decode("utf-8", "replace"), round(time.time() - t0, 2)


def _parse_markers(stdout):
    """DIAGNOSTIC parse of the WF_SURVEY_* marker lines. Never a value source.

    The lines are emitted by the compiled C++ primitives (SceneSurvey.cpp), so they
    can CORROBORATE the structured bundle — a disagreement between the two is real
    information (WF1109). What they cannot do, and no longer do, is stand in for a
    structured record that is missing: a regex over log text is not evidence, and an
    absent measurement must read as unknown rather than as whatever the log happened
    to print.
    """
    r = {"support": None, "enum": None, "markers": []}
    m = RE_SUPPORT.search(stdout or "")
    if m:
        keys = ("total", "valid", "unsupported", "edge", "blocked", "trace_error", "unknown")
        r["support"] = {k: int(v) for k, v in zip(keys, m.groups())}
    m = RE_ENUM.search(stdout or "")
    if m:
        r["enum"] = {"actors": int(m.group(1)), "components": int(m.group(2))}
    for mk in RE_MARKER.finditer(stdout or ""):
        g = [int(x) for x in mk.groups()]
        r["markers"].append(dict(zip(
            ("grounded", "footprint", "overlap", "clearance", "accepted"), g)))
    return r


# --------------------------------------------------------------------------- #
# structured evidence access
# --------------------------------------------------------------------------- #
def _far_doc(run):
    far = (run or {}).get("far") if isinstance(run, dict) else None
    return far if isinstance(far, dict) else {}


def _raw_bundle(far):
    """The far side's structured raw-evidence bundle, or an empty one.

    An empty bundle is NOT an empty world: it means nothing structured was
    collected, and every derivation over it must come back insufficient rather than
    confidently zero (scene_survey_evidence.py:268-305).
    """
    raw = (far or {}).get("raw_evidence")
    return raw if isinstance(raw, dict) else {}


def _refs(raw, kind):
    """Every raw_ref of one kind, sorted. A derived claim must cite its inputs."""
    d = (raw or {}).get(kind)
    if not isinstance(d, dict):
        return []
    return [SSE.raw_ref(kind, k) for k in sorted(d)]


def _ledger_refs(raw):
    """[ledger record id] when the operation filed one, [] when it did not.

    Cited as an input to every cleanup claim. The empty list is not a formatting
    detail: a cleanup record whose raw_refs do not include the ledger is a cleanup
    claim derived from inventories alone, and the derivation refuses to produce one
    (scene_survey_evidence._ledger_sufficiency).
    """
    return [SSE.LEDGER_REF] if SSE.temporary_object_ledger(raw) is not None else []


def _package_hash_reason(raw):
    """The far side's own reason string for P's content half, or this side's.

    Preferred from the raw record so the report carries the reason the COLLECTOR
    gave rather than a copy this file maintains separately and lets rot.
    """
    led = SSE.temporary_object_ledger(raw) or {}
    reason = led.get("persistent_package_hash_unsupported_reason")
    if isinstance(reason, str) and reason.strip():
        return reason
    return ("no UE Python api exposes a content hash or save-state digest of a "
            "persistent package, so P_1 == P_0 cannot be evaluated on package "
            "CONTENT. The observable identity half is folded into cleanup_verified "
            "as persistent_package_identity_equal; this record stays unsupported "
            "with a null value rather than being coerced into agreement. (The far "
            "side filed no ledger record carrying its own reason.)")


def _projection(d, keys):
    """Stable, key-sorted projection of one raw kind — the determinism preimage."""
    if not isinstance(d, dict):
        return {}
    return {ident: {k: rec.get(k) for k in keys}
            for ident, rec in sorted(d.items()) if isinstance(rec, dict)}


def _spatial_hash(run):
    """Deterministic hash over the STRUCTURED spatial result (the determinism unit).

    Previously this hashed the stdout regex parse, which made determinism a property
    of the log formatter rather than of the measurements. It now covers the far
    side's structured scalars plus the per-actor and per-marker raw records, so two
    runs agree only when the OBSERVATIONS agree.

    Serialization is OP.canonical_json, which refuses NaN/Infinity outright rather
    than emitting a token no other JSON parser accepts; an unhashable payload is
    reported as such and can never masquerade as a stable hash.
    """
    far = _far_doc(run)
    raw = _raw_bundle(far)
    payload = {
        "actor_count": far.get("actor_count"),
        "support_total": far.get("support_total"),
        "marker_total": far.get("marker_total"),
        "marker_accepted": far.get("marker_accepted"),
        "observed_world_package": far.get("observed_world_package"),
        "actor": _projection(raw.get("actor"),
                             ("path_name", "location", "bounds_origin", "bounds_extent")),
        "marker": _projection(raw.get("marker"),
                              ("location", "grounded", "footprint", "overlap",
                               "capsule_clear", "accepted")),
    }
    canon = OP.canonical_json(payload)
    if not canon.ok:
        return "unhashable:{}".format(canon.reason or "not_canonicalizable")
    return "sha256:" + OP.sha256_hex(canon.value.encode("utf-8"))[:32]


def _channel_disagreements(parsed, far):
    """Compare the DIAGNOSTIC stdout channel against the structured far-side JSON.

    Returns (disagreements, corroborated). A field is compared only when BOTH
    channels reported it; a field only one channel saw is not a disagreement, it is
    an absence — and ``corroborated`` is what says the run was cross-checked at all.
    Values are the C++ return values by construction: enumerate_survey_actors returns
    the actor count and logs WF_SURVEY_ENUM actors=N; sample_survey_support returns
    the sample total and logs WF_SURVEY_SUPPORT total=N; probe_temp_marker returns the
    accepted bool and logs WF_SURVEY_MARKER accepted=d
    (Plugins/WorldForge/Source/WorldForgeCore/Private/SceneSurvey.cpp:75,183,233).

    This function is the ONLY remaining consumer of the stdout parse. It can raise a
    contradiction; it cannot supply a value.
    """
    far = far if isinstance(far, dict) else {}
    en = parsed.get("enum") or {}
    sup = parsed.get("support") or {}
    mks = parsed.get("markers") or []
    ran = far.get("actor_count") is not None
    # Was the stdout channel PRESENT at all? This is the one thing len(markers)
    # cannot tell us: an empty marker list means "no WF_SURVEY_MARKER lines", which
    # is "zero markers" only if the channel was speaking. When no WF_SURVEY_* line
    # parsed at all, the channel is ABSENT, and an absence compared as a zero is the
    # exact coercion this file exists to remove — here it would manufacture a WF1109
    # hard failure out of a missing log, on a value stdout is no longer allowed to
    # supply in the first place.
    stdout_live = bool(en) or bool(sup) or bool(mks)
    pairs = [
        ("actor_count", en.get("actors"), far.get("actor_count")),
        ("support_total", sup.get("total"), far.get("support_total")),
    ]
    if ran and stdout_live:
        # Marker counts are only comparable once the primitives ran at all; before
        # that both channels are legitimately zero/empty for the same reason.
        pairs.append(("marker_total", len(mks), far.get("marker_total")))
        pairs.append(("marker_accepted", sum(1 for m in mks if m.get("accepted")),
                      far.get("marker_accepted")))
    out = []
    for name, stdout_v, far_v in pairs:
        if stdout_v is None or far_v is None:
            continue
        if int(stdout_v) != int(far_v):
            out.append("{}: stdout_markers={} far_side_json={}".format(name, stdout_v, far_v))
    corroborated = bool(en) and bool(sup) and ran
    return out, corroborated


def _one_run(args, subject, captures, request_path, ue_cmd, out_json, request_hash=None):
    """Boot the editor once. The subject rides as inline JSON; the map comes from it."""
    try:
        subject_json = json.dumps(subject, sort_keys=True, allow_nan=False)
    except ValueError as exc:
        # allow_nan=False: a NaN/Infinity in the subject is REFUSED, not emitted as a
        # non-standard JSON token the far side's parser would read back as a float.
        return {"exit_code": None, "stdout": "", "secs": 0.0,
                "far": {"error": "subject is not serializable without NaN/Infinity: "
                                 "{}".format(exc)},
                "parsed": _parse_markers("")}
    env_extra = {
        "WF_SURVEY_OUT": str(out_json).replace("\\", "/"),
        # PRIMARY subject channel. There is deliberately no WF_SURVEY_MAP: a second
        # map knob could disagree with the subject about what was surveyed.
        "WF_SURVEY_SUBJECT": subject_json,
        # FALLBACK channel, read by the far side only if WF_SURVEY_SUBJECT is empty.
        "WF_SURVEY_REQUEST": str(Path(request_path).resolve()).replace("\\", "/"),
        "WF_SURVEY_CAPTURES": ",".join(captures),
        "WF_SURVEY_RADIUS_CM": str(args.sample_radius_cm),
        "WF_SURVEY_STEP_CM": str(args.sample_step_cm),
        "WF_SURVEY_MARKERS": str(args.temporary_markers),
        "WF_SURVEY_OPERATION_ID": args.operation_id,
        # The QUESTION this run answers, carried into the editor so a raw record can
        # state which request it was produced for rather than being adoptable by any
        # later asking (scene_survey_operation.hash_request).
        "WF_SURVEY_REQUEST_HASH": str(request_hash or ""),
    }
    if out_json.exists():
        out_json.unlink()  # never let a prior run's file masquerade as this one's
    code, stdout, secs = _run_editor(ue_cmd, args.project, FAR_SIDE, env_extra, args.timeout)
    far = {}
    if out_json.is_file():
        try:
            far = json.loads(out_json.read_text(encoding="utf-8"))
        except ValueError as exc:
            far = {"error": "unparseable far-side json: {}".format(exc)}
    return {"exit_code": code, "stdout": stdout, "secs": secs, "far": far,
            "parsed": _parse_markers(stdout)}


def _canon_package(p):
    """Canonical PACKAGE form of a package/object path, case preserved, or None.

    ``/Game/Maps/Foo.Foo`` names the object inside package ``/Game/Maps/Foo``; both
    denote one package. Case is preserved because this value is EMITTED as the
    observed map — lowercasing an observation to make a comparison succeed would be
    doctoring the evidence to fit the rail.
    """
    if not isinstance(p, str):
        return None
    s = p.strip().rstrip("/")
    if not s:
        return None
    head, sep, tail = s.rpartition("/")
    if sep and "." in tail:
        s = head + "/" + tail.split(".", 1)[0]
    return s or None


def _norm_package(p):
    """Comparison key for package identity: canonical form, case-folded.

    Mirrors ``scene_survey_far_side._norm_package``: the far side reports the raw
    observation and this side re-derives the verdict, so both must agree on what
    "the same package" means.

    Case-folding here but not in ``_canon_package`` means a run whose engine returns
    a different CASE than the caller requested satisfies the identity verdict while
    still failing ``sb::map_match`` on exact equality. That combination fails closed
    (binding failures are hard failures), which is the correct direction: it reports
    a real disagreement rather than papering over it, just under WF1107 rather than
    WF1122.
    """
    c = _canon_package(p)
    return c.lower() if c is not None else None


# --------------------------------------------------------------------------- #
# evidence records — one per reported field, tri-state, always stating its source
# --------------------------------------------------------------------------- #
def _observed_int(far, key, stage, detail):
    """OBSERVED record from a structured top-level far-side integer, else `failed`."""
    if not isinstance(far, dict) or key not in far:
        return SSE.failed(
            "the far-side document carries no {!r}; there is no structured record to "
            "read and the stdout marker text may not stand in for one".format(key),
            stage=stage, collector=FAR_COLLECTOR)
    v = far.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        return SSE.failed(
            "far-side {!r} is {!r}, which is not an integer measurement".format(key, v),
            stage=stage, collector=FAR_COLLECTOR)
    return SSE.record(v, SSE.OBSERVED, stage=stage, collector=FAR_COLLECTOR,
                      collection_ok=True, detail=detail)


def _observed_bool(far, key, stage, detail):
    """OBSERVED record from a structured top-level far-side boolean, else `failed`."""
    v = (far or {}).get(key)
    if not isinstance(v, bool):
        return SSE.failed(
            "far-side {!r} is {!r}, which is not a boolean observation".format(key, v),
            stage=stage, collector=FAR_COLLECTOR)
    return SSE.record(v, SSE.OBSERVED, stage=stage, collector=FAR_COLLECTOR,
                      collection_ok=True, detail=detail)


def _proxy_owner_record(raw):
    """MeshForge proxy owners: an OBSERVATION if one exists, otherwise UNSUPPORTED.

    Replaces the asserted ``proxy_owners: 0``. A literal zero here was
    indistinguishable from a real measurement of an empty set — which is exactly the
    claim a -nullrhi editor pass cannot make, because runtime proxies spawn at game
    BeginPlay and this pass never reaches it.
    """
    rec = (raw or {}).get("proxy", {})
    rec = rec.get("runtime_proxies") if isinstance(rec, dict) else None
    if not isinstance(rec, dict):
        return SSE.failed(
            "the far side emitted no proxy observation record at proxy#runtime_proxies",
            stage="observe", collector=FAR_COLLECTOR)
    stage = rec.get("stage") if rec.get("stage") in SSE.STAGES else "observe"
    if rec.get("collection_ok") is True and rec.get("value") is not None:
        return SSE.record(rec.get("value"), SSE.OBSERVED, stage=stage,
                          collector=rec.get("collector") or FAR_COLLECTOR,
                          collection_ok=True,
                          raw_refs=[SSE.raw_ref("proxy", "runtime_proxies")],
                          detail=rec.get("detail"))
    return SSE.unsupported(
        rec.get("detail") or "runtime proxies were not observed in this pass",
        stage=stage, collector=rec.get("collector") or FAR_COLLECTOR)


def _proxies_disabled_record(args, raw):
    """Was the debug-proxy toggle verified? Replaces the asserted ``False``.

    There is no observation channel for the toggle in an editor pass: the same
    BeginPlay constraint that makes ``proxy_owners`` unobservable makes "they are
    disabled" unverifiable. Asking for it (--disable-debug-proxies) and not being
    able to check it is a FAILED collection; not asking is NOT_REQUESTED. Neither is
    a False.
    """
    asked = bool(getattr(args, "disable_debug_proxies", False))
    detail = ("MeshForge debug proxies spawn at game BeginPlay; a -nullrhi editor "
              "pass never reaches BeginPlay, so neither their presence nor their "
              "disablement is observable here (proxy raw record present={})".format(
                  isinstance((raw or {}).get("proxy", {}).get("runtime_proxies"), dict)))
    if asked:
        return SSE.failed("--disable-debug-proxies was requested but " + detail,
                          stage="observe", collector=FAR_COLLECTOR)
    return SSE.not_requested(
        "the caller did not request the debug-proxy toggle; " + detail, stage="observe")


def _camera_record(far, captures):
    """Camera capture: opt-in, and False here is a real observation, not a default."""
    if not captures:
        return SSE.record(False, SSE.OBSERVED, stage="observe", collector=FAR_COLLECTOR,
                          collection_ok=True,
                          detail="no captures were requested (capture is opt-in); the "
                                 "far side reports camera_capture_ran={!r}".format(
                                     (far or {}).get("camera_capture_ran")))
    return _observed_bool(far, "camera_capture_ran", "observe",
                          "structured far-side flag: did a camera capture actually run")


def _engine_root_record(args):
    """The engine root actually resolved by the bridge ladder — never "resolved"."""
    resolved = getattr(args, "resolved_engine_root", None) or getattr(args, "engine_root", None)
    if not resolved:
        return SSE.failed(
            "the engine root was not resolved in this context (bridge.paths."
            "resolve_engine_root was not run), so no path can be stated. The literal "
            "string 'resolved' that used to sit here was a status word wearing a "
            "path's clothes.", stage="preparation", collector=PATHS_COLLECTOR)
    return SSE.record(str(resolved), SSE.OBSERVED, stage="preparation",
                      collector=PATHS_COLLECTOR, collection_ok=True,
                      detail="resolved via the bridge ladder (arg -> env -> registry)")


def _build_evidence(args, far, captures, runtime_executed):
    """One evidence record per reported field, all sourced from the STRUCTURED channel.

    Every derived value goes through scene_survey_evidence.derived_record, which
    refuses to answer when the raw is insufficient and returns an honest ``failed``
    record instead — so an empty bundle produces ``unknown`` rather than the
    confident zero an ``all()``/``sum()`` over an empty list would produce.
    """
    raw = _raw_bundle(far)
    actor_refs = _refs(raw, "actor")
    marker_refs = _refs(raw, "marker")
    inv = raw.get("inventory") if isinstance(raw.get("inventory"), dict) else {}
    inv_refs = [SSE.raw_ref("inventory", k) for k in ("pre", "post")
                if isinstance(inv.get(k), dict)]

    ev = {}
    # runtime_executed is an observation about OUR OWN process, not the far side's
    # self-report: a real editor returned 0 and left its document behind.
    ev["runtime_executed"] = SSE.record(
        bool(runtime_executed), SSE.OBSERVED, stage="boot", collector=ASSEMBLER,
        collection_ok=True,
        detail="the editor subprocess returned exit code 0 AND the far side wrote a "
               "document carrying its own operation_id. A non-zero exit, a timeout "
               "(exit_code None) or an absent/unparseable document is NOT an "
               "execution.")
    ev["engine_root"] = _engine_root_record(args)

    ev["actor_count"] = _observed_int(
        far, "actor_count", "observe",
        "USceneSurveyStatics.enumerate_survey_actors return value, read structurally "
        "from the far-side document (never from WF_SURVEY_ENUM log text)")
    ev["support_samples_total"] = _observed_int(
        far, "support_total", "classify",
        "USceneSurveyStatics.sample_survey_support return value, read structurally "
        "from the far-side document (never from WF_SURVEY_SUPPORT log text)")
    for name in ("support_samples_valid", "unsupported_regions", "edge_regions"):
        ev[name] = SSE.unsupported(NO_STRUCTURED_SUPPORT_BREAKDOWN, stage="classify",
                                   collector=FAR_COLLECTOR)

    # ActorBoundsValid = (n>0) AND for every actor i: finite(min) AND finite(max) AND
    # for every axis min<=max. derive_actor_bounds_valid checks a finite, non-
    # degenerate extent per actor (scene_survey_evidence.py:284-296) and its
    # sufficiency precondition refuses to answer from a COUNT (:270-281).
    ev["actor_bounds_valid"] = SSE.derived_record(
        "actor_bounds_valid", raw, "observe", ASSEMBLER, refs=actor_refs)
    ev["temporary_placements_requested"] = SSE.derived_record(
        "temporary_placements_requested", raw, "classify", ASSEMBLER, refs=marker_refs)
    ev["temporary_placements_accepted"] = SSE.derived_record(
        "temporary_placements_accepted", raw, "classify", ASSEMBLER, refs=marker_refs)
    # GROUNDED, not accepted. accepted = grounded AND footprint AND clearance, so the
    # old wiring reported the strictly stronger value under the weaker name and made
    # the two fields incapable of disagreeing.
    ev["temporary_placements_grounded"] = SSE.derived_record(
        "temporary_placements_grounded", raw, "classify", ASSEMBLER, refs=marker_refs)
    ev["overlap_count"] = SSE.derived_record(
        "overlap_count", raw, "classify", ASSEMBLER, refs=marker_refs)
    ev["player_clearance_valid"] = SSE.derived_record(
        "player_clearance_valid", raw, "classify", ASSEMBLER, refs=marker_refs)
    # cleanup_verified needs a pre AND a post inventory, and the post must be taken
    # at or after the cleanup stage. "nothing was spawned, so nothing to clean" is a
    # claim about the world, and a claim about the world needs two snapshots of it.
    # It ALSO needs the operation's temporary-object ledger: two snapshots cannot see
    # an object created and destroyed between them, so a missing ledger makes the
    # per-object conjunct unaskable and the whole claim `unknown`
    # (scene_survey_evidence._ledger_sufficiency). The ledger record is cited as an
    # input so the claim's provenance includes the thing its refusal turns on.
    ev["cleanup_verified"] = SSE.derived_record(
        "cleanup_verified", raw, "cleanup", ASSEMBLER,
        refs=inv_refs + _ledger_refs(raw))
    # The two population predicates the evidence model registers for the cleanup
    # kinds. Both were registered and NOBODY REQUESTED THEM — a predicate with no
    # consumer is a rail that has never been asked to hold anything up. Requested
    # here so the per-object ledger observations and the per-snapshot dirty-package
    # observations each produce a re-derivable, forgery-checkable claim of their own
    # rather than only ever being folded into cleanup_verified's conjunction.
    #
    # An empty population comes back INSUFFICIENT, i.e. an honest `failed` record
    # that projects to None and is named in meta.evidence_unknown_fields. That is
    # the correct reading of a survey that placed nothing: there is no population to
    # aggregate over, and an all() across an empty list is a confident answer about
    # nothing.
    ev["temporary_cleanup_valid"] = SSE.derived_record(
        "temporary_cleanup_valid", raw, "cleanup", ASSEMBLER,
        refs=_refs(raw, "temporary_placement") + _ledger_refs(raw))
    ev["package_cleanliness_valid"] = SSE.derived_record(
        "package_cleanliness_valid", raw, "cleanup", ASSEMBLER, refs=inv_refs)
    # P_1 == P_0, content half. UNSUPPORTED with a null value — never a fabricated
    # zero and never a True. See the far side's PACKAGE_HASH_UNSUPPORTED_REASON.
    ev["persistent_package_hash_stable"] = SSE.unsupported(
        _package_hash_reason(raw), stage="cleanup", collector=FAR_COLLECTOR)

    ev["proxy_owners"] = _proxy_owner_record(raw)
    ev["proxies_disabled"] = _proxies_disabled_record(args, raw)
    ev["camera_capture_ok"] = _camera_record(far, captures)
    return ev


def _reported(rec):
    """Project an evidence record into the report. Unknown projects to None.

    ``satisfies_rail`` is True only for observed/derived records whose collection
    actually succeeded (scene_survey_evidence.py:233-237). Everything else —
    unsupported, not_requested, failed — projects to None and NEVER to 0 or False.
    That is the whole tri-state, enforced in one place.
    """
    if not isinstance(rec, dict):
        return None
    return rec.get("value") if SSE.satisfies_rail(rec) else None


def _evidence_dir(args):
    """Where THIS operation's raw far-side artifacts live."""
    d = getattr(args, "artifact_dir", None)
    return Path(d) if d else REPORT_DIR


def _build_report(args, subject, captures, runs, determinism_ok):
    """Fold the runs into a SceneSurveyReport (per the v2.6 contract).

    Every reported value comes from the far side's structured channel via
    ``_build_evidence``; ``meta.evidence`` carries the record behind each one.

    Capture policy (v2.6): capture is OPT-IN. WF1068 is appended only when the
    caller actually requested captures and none could be produced.
    """
    last = runs[-1]
    far = _far_doc(last)
    parsed = last.get("parsed") or {"support": None, "enum": None, "markers": []}
    raw = _raw_bundle(far)

    # A REAL run: a process that returned 0 and a far side that left its document
    # behind. The old predicate (exit_code is not None) was true for a crashed
    # editor and for every non-zero exit — everything except a timeout.
    runtime_executed = (last.get("exit_code") == 0
                        and isinstance(far.get("operation_id"), str)
                        and bool(far.get("operation_id")))

    ev = _build_evidence(args, far, captures, runtime_executed)

    disagreements, corroborated = _channel_disagreements(parsed, far)
    subject_resolved = far.get("subject_resolved") is True
    obs_loc = far.get("observed_anchor_location")
    obs_path = far.get("observed_anchor_object_path")

    # ---- world identity: the ONE binding input that is not a copy of the request --
    # Re-derived here from the far side's RAW observation, independently of whatever
    # the far side concluded. far["map"], far["subject_id"] and
    # far["subject_resolved_by"] are echoes of the subject (scene_survey_far_side.py
    # :1187-1191), so consuming those instead of `subject` would compare a value to a
    # copy of itself just as surely. observed_world_package is measured from the live
    # editor, so it is the only one that can disagree.
    requested_map = subject.get("map_asset_path", "")
    observed_pkg = far.get("observed_world_package")
    map_loaded = far.get("loaded") is True
    world_identity_ok = (map_loaded
                         and _norm_package(observed_pkg) is not None
                         and _norm_package(observed_pkg) == _norm_package(requested_map))
    # The report's map_asset_path is the OBSERVED world, not the requested one. That
    # is what makes sb::map_match a real comparison instead of a tautology. When
    # identity could not be established we emit "" rather than the request — an
    # unobserved map must never be reported as an observed one.
    observed_map_asset_path = _canon_package(observed_pkg) if world_identity_ok else ""

    ev_dir = _evidence_dir(args)
    evidence_paths = []
    for i in range(1, len(runs) + 1):
        p = ev_dir / "far_side_run{}.json".format(i)
        if p.is_file():
            try:
                evidence_paths.append(p.resolve().relative_to(REPO_ROOT).as_posix())
            except ValueError:
                evidence_paths.append(p.as_posix())

    camera_capture_ok = _reported(ev["camera_capture_ok"])
    captures_missing = bool(captures) and camera_capture_ok is not True

    report = {
        "report_id": "scene_survey_report_{}".format(args.operation_id),
        "operation_id": args.operation_id,
        # OBSERVED (world package read from the live editor), not the request.
        "map_asset_path": observed_map_asset_path,
        # CALLER_SUPPLIED, and honestly so: subject_id is caller vocabulary and
        # subject_resolved_by is provenance metadata. WorldForge has no channel that
        # could ever observe either, so sb::subject_id_match and
        # sb::resolver_not_worldforge are continuity checks on the caller's own
        # values — NOT evidence that the right subject was surveyed. Sourcing them
        # from far[...] would not change that: the far side echoes the same subject.
        "subject_id": subject.get("subject_id", ""),
        "observed_anchor_location": obs_loc,
        "observed_anchor_object_path": obs_path,
        "subject_resolved_by": subject.get("resolved_by"),
        "captures_requested": list(captures),
        # ---- every value below is a projection of an evidence record -------------
        "camera_capture_ok": camera_capture_ok,
        "actor_bounds_valid": _reported(ev["actor_bounds_valid"]),
        "support_samples_total": _reported(ev["support_samples_total"]),
        "support_samples_valid": _reported(ev["support_samples_valid"]),
        "unsupported_regions": _reported(ev["unsupported_regions"]),
        "edge_regions": _reported(ev["edge_regions"]),
        "proxy_owners": _reported(ev["proxy_owners"]),
        "proxies_disabled": _reported(ev["proxies_disabled"]),
        "temporary_placements_grounded": _reported(ev["temporary_placements_grounded"]),
        "overlap_count": _reported(ev["overlap_count"]),
        "player_clearance_valid": _reported(ev["player_clearance_valid"]),
        "cleanup_verified": _reported(ev["cleanup_verified"]),
        "determinism_hash": _spatial_hash(last),
        "runtime_mode": "live_survey_runtime" if runtime_executed else "deterministic_survey_simulation",
        "runtime_executed": runtime_executed,
        "evidence_paths": evidence_paths,
        "failure_codes": [],
        "status": "fail",
        "schema_version": SS.RT_SURVEY_REPORT,
        "report_type": SS.RT_SURVEY_REPORT,
        "created_by": "worldforge.v2.6",
        "created_at": SS.AUTHORING_TS,
        "meta": {
            "engine_root": _reported(ev["engine_root"]),
            "observed_engine_version": far.get("observed_engine_version"),
            "uproject": far.get("resolved_uproject") or str(args.project),
            "runtime_executed": runtime_executed,
            "repeat": args.repeat,
            "determinism_consistent": determinism_ok,
            "per_run_hashes": [_spatial_hash(r) for r in runs],
            "subject_source": far.get("subject_source"),
            "anchor_detail": far.get("anchor_detail"),
            # The stdout channel is retained ONLY as corroboration. It supplies no
            # reported value; it can only contradict the structured one.
            "stdout_channel_role": "diagnostic_only",
            "channel_corroborated": corroborated,
            "channel_disagreements": disagreements,
            "camera_pass": far.get("camera_capture_reason"),
            "proxy_pass": far.get("proxy_pass_reason"),
            "raw_evidence_schema": far.get("raw_evidence_schema"),
            "raw_evidence_present": bool(raw),
            "raw_evidence_counts": {k: len(v) for k, v in sorted(raw.items())
                                    if isinstance(v, dict)},
            "far_side_collection_errors": far.get("collection_errors") or [],
            # The tri-state, in full: value + classification + stage + collector +
            # derivation + the raw records each claim was computed from.
            "evidence": ev,
        },
    }

    # ---- what nothing observed -------------------------------------------------
    # A field whose record may not satisfy a rail is UNKNOWN. It is listed by name so
    # a reader never has to infer "unknown" from a suspicious-looking zero, and so
    # the difference between "measured 0" and "never collected" survives to disk.
    unknown_fields = sorted(n for n, rec in ev.items() if not SSE.satisfies_rail(rec))
    report["meta"]["evidence_unknown_fields"] = unknown_fields
    # The evidence records police themselves: a derived record with no raw_refs, or
    # an "unsupported" one smuggling a usable value, is a defect in THIS assembler.
    ev_record_failures = []
    for name in sorted(ev):
        ev_record_failures += [c[0] for c in SSE.validate_record(ev[name], name, strict=True)
                               if not c[1]]
    report["meta"]["evidence_record_failures"] = ev_record_failures

    # ---- acceptance eligibility ------------------------------------------------
    # Computed by the ONE shared predicate, never re-implemented here: the
    # independent validator imports the same function and re-derives from the same
    # pair, so a second implementation would be a second opinion rather than a
    # check. An `explicit_transform` survey can be perfectly valid and is still
    # never acceptance-eligible — only the world is independently observed, the
    # anchor is the caller's own input handed back, so the observation cannot
    # distinguish a correct subject from arbitrary coordinates.
    _acc = SS.evaluate_acceptance_eligibility(subject, report)
    report["acceptance_eligible"] = bool(_acc.get("eligible"))
    report["acceptance_ineligibility_reason"] = _acc.get("reason")
    report["meta"]["acceptance_components"] = _acc.get("components")
    report["meta"]["acceptance_failed_components"] = _acc.get("failed_components")

    # ---- subject binding: did we survey the subject we were handed? ------------
    binding = SS.validate_subject_binding(subject, report, strict=True)
    binding_fails = [c for c in binding if not c[1]]
    report["meta"]["subject_binding_failures"] = [c[0] for c in binding_fails]

    # ---- failure codes ---------------------------------------------------------
    fcodes = []
    if not runtime_executed:
        fcodes.append(C.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM)
    if not determinism_ok:
        fcodes.append(C.SCENE_SURVEY_DETERMINISM_MISMATCH)
    if far.get("error"):
        fcodes.append(C.SCENE_SURVEY_REPORT_INVALID)
    if not subject_resolved:
        fcodes.append(C.SCENE_SURVEY_SUBJECT_UNRESOLVED)
    # A survey of the wrong world is a wrong answer, not a partial one. These are
    # distinct failures: the map never opened, vs it opened something we cannot
    # confirm is the requested world.
    if not map_loaded:
        fcodes.append(C.SCENE_SURVEY_MAP_LOAD_FAILED)
    elif not world_identity_ok:
        fcodes.append(C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)
    if disagreements:
        fcodes.append(C.SCENE_SURVEY_CHANNEL_DISAGREEMENT)
    for c in binding_fails:
        if str(c[3]) not in [str(x) for x in fcodes]:
            fcodes.append(c[3])
    # Capture: opt-in. Only a REQUESTED-but-absent capture is a shortfall.
    if captures_missing:
        fcodes.append(C.SCENE_SURVEY_CAMERA_CAPTURE_MISSING)
    # Any field nothing observed. BLOCKED, not FAIL: an unobserved capability is an
    # incomplete survey, not a wrong one — and the report says exactly which fields.
    if unknown_fields:
        fcodes.append(C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
    if ev_record_failures:
        fcodes.append(C.SCENE_SURVEY_EVIDENCE_CLASSIFICATION_INVALID)
    if report["cleanup_verified"] is not True:
        fcodes.append(C.SCENE_SURVEY_CLEANUP_UNVERIFIED)
    if report["proxy_owners"] is None or report["proxies_disabled"] is None:
        fcodes.append(C.SCENE_SURVEY_PROXY_DISABLE_UNVERIFIED)
    # A survey that saw nothing cannot claim a pass, whatever else went right.
    # NOTE the isinstance guard: support_samples_total is now None when unobserved,
    # and `None > 0` is a TypeError, not a False.
    tot = report["support_samples_total"]
    if not (report["actor_bounds_valid"] is True
            and isinstance(tot, int) and tot > 0
            and evidence_paths):
        fcodes.append(C.SCENE_SURVEY_EVIDENCE_MISSING)

    # A wrong/absent subject, a forged-looking channel, a non-deterministic or
    # non-executed run are FAILURES. A merely incomplete one (capture pending, an
    # unobserved capability, no spatial evidence yet) is BLOCKED. Neither is ever
    # quietly a pass.
    hard = (not runtime_executed or not determinism_ok or bool(far.get("error"))
            or not subject_resolved or bool(disagreements) or bool(binding_fails)
            # Independent of far["error"] on purpose: this side re-derives the world
            # identity verdict from the raw observation, so a far side that failed to
            # set its own error string cannot talk this gate into a pass.
            or not world_identity_ok)
    fcodes = [str(x) for x in fcodes]
    report["failure_codes"] = fcodes
    report["status"] = "fail" if hard else ("blocked" if fcodes else "pass")
    return report, disagreements, corroborated, binding_fails


# --------------------------------------------------------------------------- #
# request loading / preflight
# --------------------------------------------------------------------------- #
def _load_request(path):
    """Load a BridgeRequest JSON. Returns (request_obj, request_dict, error_or_None)."""
    from bridge.schema import BridgeRequest
    p = Path(path)
    if not p.is_file():
        return None, None, "no request file at {}".format(p)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, None, "request is not valid JSON: {}".format(exc)
    if not isinstance(doc, dict):
        return None, None, "request must be a JSON object (got {})".format(type(doc).__name__)
    fields = set(BridgeRequest.__dataclass_fields__)
    unknown = sorted(set(doc) - fields)
    if unknown:
        return None, doc, "request carries unknown field(s): {}".format(unknown)
    try:
        req = BridgeRequest(**doc)
    except TypeError as exc:
        return None, doc, "request does not satisfy the BridgeRequest contract: {}".format(exc)
    return req, doc, None


def _preflight_plugin_source(project, required_hash):
    """Hash the TARGET project's plugin source and compare it to the caller's pin.

    Returns (ok, detail, observed_or_None). An unstated pin is NOT a pass: the
    caller must state which plugin source it expects, or the far side's code is
    simply unidentified (tools/bridge/paths.py:302-324).
    """
    from bridge import paths as P
    plugin_dir = Path(project).resolve().parent / "Plugins" / "WorldForge"
    try:
        observed = P.resolve_plugin_source_hash(plugin_dir=plugin_dir)
    except P.ResolutionError as exc:
        return False, "cannot hash target plugin source: {}".format(exc), None
    ok, detail = P.plugin_source_hash_matches(required_hash, observed.value)
    return ok, detail, observed.value


def _sha256_file(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return "sha256:" + h.hexdigest()


def _emit_response(req, survey, far, out_dir):
    """Write the BridgeResponse ATOMICALLY into the request's CONFINED output_location.

    Returns (dest_or_None, OpResult). ``out_dir`` must already be the confined
    absolute directory from OP.confine_path — this function never joins a
    caller-supplied string onto the repo root.
    """
    from bridge import capability_ops as OPS
    op = OPS.get_op(OPERATION)
    paths, hashes = [], []
    for rel in survey.get("evidence_paths", []):
        abs_p = REPO_ROOT / rel
        if abs_p.is_file():
            paths.append(rel)
            hashes.append(_sha256_file(abs_p))
    resp = op.build_response(req, far, evidence_paths=paths, evidence_hashes=hashes)
    dest = Path(out_dir) / "scene_survey_response_{}.json".format(req.operation_id)
    # atomic_write_json refuses NaN/Infinity outright (scene_survey_operation.py
    # :186-190) and publishes by same-directory temp + fsync + os.replace, so no
    # reader ever sees a truncated response.
    res = OP.atomic_write_json(dest, resp.to_dict(), repo_root=REPO_ROOT)
    return (dest if res.ok else None), res


# --------------------------------------------------------------------------- #
# smoke
# --------------------------------------------------------------------------- #
def _smoke():
    """Bootless self-check: far-side present, contracts import, both capture policies hold."""
    problems = []
    if not FAR_SIDE.is_file():
        problems.append("far-side script missing: {}".format(FAR_SIDE))

    # the capability registry is the one door; its scene_survey entry must resolve
    # and must point at the far-side script this command actually launches.
    try:
        from bridge import capability_ops as OPS
        op = OPS.get_op(OPERATION)
        if OPS.far_side_script_path(op).resolve() != FAR_SIDE.resolve():
            problems.append("capability registry far-side script {!r} != {}".format(
                op.far_side_script, FAR_SIDE))
        pfails = [c for c in op.validate_payload(
            {"subject": SS._example_scene_survey_subject(), "captures": []},
            strict=True) if not c[1]]
        if pfails:
            problems.append("capability payload validator rejects a valid payload: {}".format(
                [c[0] for c in pfails][:4]))
    except Exception as exc:  # noqa: BLE001
        problems.append("capability registry unusable: {}: {}".format(type(exc).__name__, exc))

    example = SS._example_scene_survey_report()
    fails = [c for c in SS.validate_scene_survey_report(example, strict=True) if not c[1]]
    if fails:
        problems.append("example SceneSurveyReport fails validation: {}".format(
            [c[0] for c in fails][:4]))

    # capture OPT-IN: a survey nobody asked to render is a legal clean pass.
    optin = SS._example_scene_survey_report(
        captures_requested=[], camera_capture_ok=False, status="pass", failure_codes=[])
    ofails = [c for c in SS.validate_scene_survey_report(optin, strict=True) if not c[1]]
    if ofails:
        problems.append("capture-opt-in clean report fails validation: {}".format(
            [c[0] for c in ofails][:4]))

    # capture REQUESTED but absent: still blocked, still WF1068. The rail stays.
    blocked = SS._example_scene_survey_report(
        captures_requested=list(SS.CAMERA_KINDS), camera_capture_ok=False, status="blocked",
        failure_codes=[str(C.SCENE_SURVEY_CAMERA_CAPTURE_MISSING)])
    bfails = [c for c in SS.validate_scene_survey_report(blocked, strict=True) if not c[1]]
    if bfails:
        problems.append("blocked-pending-camera report fails validation: {}".format(
            [c[0] for c in bfails][:4]))
    # ...and a requested-but-absent capture must NOT be passable as clean.
    sneaky = SS._example_scene_survey_report(
        captures_requested=list(SS.CAMERA_KINDS), camera_capture_ok=False,
        status="pass", failure_codes=[])
    sfails = {c[3] for c in SS.validate_scene_survey_report(sneaky, strict=True) if not c[1]}
    if C.SCENE_SURVEY_EVIDENCE_MISSING not in sfails:
        problems.append("a pass claimed with requested-but-missing captures was NOT "
                        "rejected for {} (got {})".format(
                            C.SCENE_SURVEY_EVIDENCE_MISSING, sorted(sfails)))

    # subject binding: the matched pair is clean, a mismatched one is caught.
    pair = [c for c in SS.validate_subject_binding(
        SS._example_scene_survey_subject(), example, strict=True) if not c[1]]
    if pair:
        problems.append("matched subject/report pair fails binding: {}".format(
            [c[0] for c in pair][:4]))
    bad_pair = {c[3] for c in SS.validate_subject_binding(
        SS._example_scene_survey_subject(),
        SS._example_scene_survey_report(subject_id="subject_fixture_beta"),
        strict=True) if not c[1]}
    if C.SCENE_SURVEY_SUBJECT_MISMATCH not in bad_pair:
        problems.append("a report bound to the wrong subject was not rejected for {}".format(
            C.SCENE_SURVEY_SUBJECT_MISMATCH))

    problems += _smoke_evidence_sourcing()
    problems += _smoke_operation_wiring()

    if problems:
        for p in problems:
            print("[scene-survey-smoke] FAIL — {}".format(p))
        return 1
    print("[scene-survey-smoke] PASS — operator surface wired (far-side present, "
          "capability registered, report contract satisfied, capture opt-in proven "
          "both ways, subject binding enforced, stdout demoted to diagnostic, "
          "unknown never coerced to 0/False, operation manifest + confinement live)")
    return 0


class _SmokeArgs(object):
    """The argparse surface _build_report reads, for the bootless checks below."""

    def __init__(self):
        self.operation_id = "op_smoke_scene_survey"
        self.engine_root = None
        self.resolved_engine_root = None
        self.project = "smoke.uproject"
        self.repeat = 1
        self.disable_debug_proxies = False
        self.artifact_dir = None


# The one world identity the populated smoke fixture is taken in. Named once
# because it is LOAD-BEARING in three places at once: both inventory snapshots and
# every temporary-object record must agree on it, or
# `scene_survey_evidence._foreign_world_placements` correctly reports the placement
# as evidence imported from a world these snapshots never witnessed.
_SMOKE_MAP = "/Game/Fixture/Lvl_Fixture"


def _smoke_temporary_object_records(op_id, world):
    """The ledger + one owned-object record of an HONEST, CLEAN operation.

    Hand-built to mirror what `_SpawnLedger` actually emits — `spawn_transient`
    then `cleanup` then `write_manifest` (tools/bridge/scene_survey_far_side.py:
    1405-1464, 1474-1579, 1581-1690) — because the far side cannot be imported here:
    it is an -ExecutePythonScript entry point that needs `unreal`. The shape is
    therefore copied, never invented; the closed vocabularies are taken from the
    CONSUMER's own constants (`SSE.PRESENCE_ABSENT`, `SSE.DESTRUCTION_DESTROYED`,
    ...) so a fixture and the module that reads it cannot drift into two spellings.

    THE STORY IT TELLS, and why each field is what it is. One transient object,
    `t0`, spawned AFTER the pre snapshot and destroyed BEFORE the post one — the
    case two inventories are blind to, which is the entire reason the ledger exists:

      creation_observed=True      the spawn call returned a live handle, so `t0` is
                                  in O_created and the per-object conjunct must
                                  actually range over it. False here would make the
                                  quantifier vacuous, which is the shape this
                                  fixture must NOT have.
      destruction_attempted=True  cleanup reached this object.
      destroy_returned=True       the destroy CALL's own outcome — the runtime's
      destruction_result=destroyed  claim about itself, never the proof.
      is_valid_before/after       False->True inverted: True before, False after.
                                  This is the falsifiable channel, and it is the
                                  one that CAN say no.
      absent_after_cleanup=True   = NOT is_valid_after_destroy, registered in
      post_cleanup_presence=absent  `derived_fields` exactly as `cleanup` registers
                                  them, so `_placement_contradictions` sees one
                                  is_valid measurement under two names rather than
                                  a summary somebody wrote over an honest atom.
      enumeration_* / vacuous     absence from `get_all_level_actors` is recorded
                                  and flagged VACUOUS: a transient actor is never
                                  enumerated, so this channel cannot fail and is
                                  never the cleanup proof.

    The manifest's aggregates (`object_count`, `object_ids`, `created_object_ids`,
    `created_object_count`) are computed from that single atom the way
    `write_manifest` computes them, because `scene_survey_evidence.
    _ledger_contradictions` rejects the whole bundle when a summary disagrees with
    the measurements it sits beside — a lying aggregate is not made safe by nobody
    consuming it.
    """
    ident = "t0"
    tag = "worldforge.scene_survey/{}".format(op_id)
    path = "{0}.{1}:PersistentLevel.WFSurveyTemp_{2}".format(
        world, world.rsplit("/", 1)[-1], ident)
    spawn_api = "unreal.EditorActorSubsystem.spawn_actor_from_class"
    destroy_api = "unreal.EditorActorSubsystem.destroy_actor"
    is_valid_api = "unreal.SystemLibrary.is_valid"
    cleanup_api = " + ".join((spawn_api, destroy_api, is_valid_api))
    vacuity = ("an actor spawned with transient=True is never returned by "
               "get_all_level_actors at all, so its absence from the enumeration is "
               "true before destruction as well as after and cannot distinguish the "
               "two (the far side's measured statement of this is "
               "scene_survey_far_side.ENUMERATION_VACUITY_REASON)")
    hash_reason = ("no UE Python api exposes a content hash or save-state digest of "
                   "a persistent package, so the CONTENT half of P_1 == P_0 is "
                   "unsupported with a null value; only the identity half is "
                   "observable (scene_survey_far_side."
                   "PACKAGE_HASH_UNSUPPORTED_REASON)")

    placement = {
        # ---- the envelope every raw record carries (far_side:528-568) ---------
        "record_schema": "wf.scene_survey.raw_evidence_record.v1",
        "operation_id": op_id,
        "request_hash": None,
        "request_hash_algorithm": None,
        "record_id": SSE.raw_ref("temporary_placement", ident),
        "record_type": "temporary_placement",
        "record_ident": ident,
        "stage": "cleanup",
        "collector": "scene_survey_far_side._SpawnLedger.spawn_transient",
        "collection_status": "collected",
        "evidence_class": "observed",
        "source_api": cleanup_api,
        "world_identity": world,
        "actor_object_path": path,
        "component_object_path": None,
        "failure_code": None,
        "derived_fields": {
            # Both derived from ONE atom, `is_valid_after_destroy`, and both say so
            # — the same registration `_SpawnLedger.cleanup` writes.
            "absent_after_cleanup": {
                "evidence_class": "derived_from_observed",
                "derivation": "absent_after_cleanup = NOT is_valid_after_destroy",
                "inputs": ["is_valid_after_destroy"],
                "source_api": is_valid_api,
            },
            "post_cleanup_presence": {
                "evidence_class": "derived_from_observed",
                "derivation": ("post_cleanup_presence = 'absent' when "
                               "is_valid_after_destroy is False, 'present' when it "
                               "is True, 'unknown' when it could not be read"),
                "inputs": ["is_valid_after_destroy"],
                "source_api": is_valid_api,
            },
        },
        "measured_fields": ["path_name", "destroy_returned", "absent_after_cleanup",
                            "is_valid_before_destroy", "is_valid_after_destroy",
                            "enumeration_present_before_cleanup",
                            "enumeration_present_after_cleanup",
                            "enumeration_absent_after_cleanup"],
        # ---- identity + ownership -------------------------------------------
        "ident": ident,
        "object_id": ident,
        "ownership_tag": tag,
        "package_identity": world,
        "requested_location": [10.0, 20.0, 30.0],
        "spawn_attempted": True,
        "spawn_ok": True,
        # ---- the life story --------------------------------------------------
        "creation_observed": True,
        "creation_stage": "observe",
        "destruction_attempted": True,
        "destruction_result": SSE.DESTRUCTION_DESTROYED,
        "post_cleanup_presence": SSE.PRESENCE_ABSENT,
        "transient": True,
        "path_name": path,
        "destroy_attempted": True,
        "destroy_returned": True,
        "absent_after_cleanup": True,
        # ---- the two channels, kept apart ------------------------------------
        "is_valid_before_destroy": True,
        "is_valid_after_destroy": False,
        "validity_api": is_valid_api,
        "enumeration_present_before_cleanup": False,
        "enumeration_present_after_cleanup": False,
        "enumeration_absent_after_cleanup": True,
        "enumeration_absence_is_vacuous": True,
        "enumeration_vacuity_reason": vacuity,
        "cleanup_channel": "is_valid",
        "collection_ok": True,
        "errors": [],
    }

    created = [ident] if placement["creation_observed"] is True else []
    object_ids = [ident]
    ledger = {
        "record_schema": "wf.scene_survey.raw_evidence_record.v1",
        "operation_id": op_id,
        "request_hash": None,
        "request_hash_algorithm": None,
        "record_id": SSE.LEDGER_REF,
        "record_type": SSE.LEDGER_KIND,
        "record_ident": SSE.LEDGER_IDENT,
        "stage": "cleanup",
        "collector": "scene_survey_far_side._SpawnLedger.write_manifest",
        "collection_status": "collected",
        "evidence_class": "observed",
        "source_api": cleanup_api,
        "world_identity": world,
        "actor_object_path": None,
        "component_object_path": None,
        "failure_code": None,
        "derived_fields": {},
        "measured_fields": [],
        "is_temporary_object_ledger": True,
        "ownership_tag": tag,
        "spawn_policy": "transient-only",
        "spawn_entry_point": "scene_survey_far_side._SpawnLedger.spawn_transient",
        # One spawn call site in the module, and it is inside the ledger: a SECOND
        # one would mean O_created can be incomplete, and `_ledger_sufficiency`
        # refuses the verdict on a positive `unledgered_spawn_call_sites`. That the
        # REAL far side still measures 1/1 is asserted by
        # test_negative_scene_survey_cleanup.py::producer::single_spawn_path, not
        # here — this fixture only states the clean case it represents.
        "spawn_call_sites_in_module": 1,
        "spawn_call_sites_in_ledger": 1,
        "unledgered_spawn_call_sites": 0,
        # Aggregates, computed from the atoms above rather than typed beside them.
        "object_ids": object_ids,
        "object_count": len(object_ids),
        "created_object_ids": created,
        "created_object_count": len(created),
        # Emptied by cleanup: nothing is still owned. That is a measurement, and it
        # is why both inventories carry operation_owned_actor_paths == [].
        "still_owned_object_ids": [],
        "temporary_object_refs": [SSE.raw_ref("temporary_placement", i)
                                  for i in object_ids],
        "cleanup_ran": True,
        "package_identity": world,
        "persistent_package_hash": None,
        "persistent_package_hash_supported": False,
        "persistent_package_hash_evidence_class": "unsupported",
        "persistent_package_hash_unsupported_reason": hash_reason,
        "presence_states": list(SSE.PRESENCE_STATES),
        "destruction_results": list(SSE.DESTRUCTION_RESULTS),
        "collection_ok": True,
        "errors": [],
    }
    return {ident: placement}, {SSE.LEDGER_IDENT: ledger}


def _smoke_evidence_sourcing():
    """THE tri-state rails: no structured record => unknown, never a scrape, never 0.

    Anti-vacuity: the same assembler is driven twice, once with an EMPTY structured
    bundle and once with a populated one, so a "nothing is ever reported" regression
    fails the second half just as loudly as a "log text was used" regression fails
    the first.
    """
    problems = []
    args = _SmokeArgs()

    # (1) A run whose structured bundle is EMPTY while stdout is FULL of markers.
    # Every spatial field must come back None. If any of them equals the log value,
    # the regex is supplying evidence again.
    loud_stdout = ("WF_SURVEY_SUPPORT total=158 valid=120 unsupported=20 edge=10 "
                   "blocked=8 trace_error=0 unknown=0\n"
                   "WF_SURVEY_ENUM actors=12 components=44\n"
                   "WF_SURVEY_MARKER x grounded=1 footprint=1 overlap=0 clearance=1 "
                   "accepted=1\n")
    bare_far = {"operation_id": "op_smoke_scene_survey", "loaded": True,
                "observed_world_package": "/Game/Fixture/Lvl_Fixture",
                "camera_capture_ran": False}
    bare_ev = _build_evidence(args, bare_far, [], True)
    for field in ("actor_bounds_valid", "support_samples_valid", "unsupported_regions",
                  "edge_regions", "temporary_placements_grounded", "overlap_count",
                  "player_clearance_valid", "cleanup_verified", "proxy_owners",
                  "proxies_disabled", "support_samples_total"):
        rec = bare_ev[field]
        if _reported(rec) is not None:
            problems.append("{} was reported as {!r} from a run with NO structured "
                            "record — a missing measurement must project to None".format(
                                field, _reported(rec)))
        if rec.get("value") is not None:
            problems.append("{} carries value={!r} on a non-satisfying record; "
                            "unknown must be None, never a zero or a False".format(
                                field, rec.get("value")))
        if rec.get("classification") not in SSE.NON_SATISFYING:
            problems.append("{} classified {!r} with nothing to observe".format(
                field, rec.get("classification")))
    # ...and the diagnostic parse must still SEE those markers, so the check above is
    # about wiring rather than about an unparseable string.
    if (_parse_markers(loud_stdout).get("support") or {}).get("total") != 158:
        problems.append("the diagnostic stdout parser stopped parsing; the "
                        "no-scrape rails above would then be vacuous")

    # (2) A populated structured bundle must actually produce values — otherwise the
    # rails above would pass on an assembler that reports nothing at all, ever.
    # The fixture must satisfy scene_survey_evidence.bundle_integrity: capsule_clear
    # is the complement of overlap (far_side:946) and accepted implies grounded AND
    # footprint AND clearance (SceneSurvey.cpp:230). m0 is decided-blocked, m1 is
    # decided-clean, so grounded (2) and accepted (1) genuinely differ.
    #
    # cleanup_verified additionally needs the operation's TEMPORARY-OBJECT LEDGER.
    # Two inventory snapshots cannot see an object created and destroyed between
    # them, so without a ledger O_created is unknown and the per-object conjunct is
    # unaskable (scene_survey_evidence._ledger_sufficiency). The fixture therefore
    # carries a real one — one transient object, created, destroyed, witnessed gone
    # — so the True below is EARNED by a bundle that could have said otherwise, not
    # granted by a derivation that stopped asking.
    _placements, _ledger_doc = _smoke_temporary_object_records(
        args.operation_id, _SMOKE_MAP)
    _inv = {"collection_ok": True, "actor_paths": ["/A"], "dirty_packages": [],
            "operation_owned_actor_paths": [],
            "map_identity": _SMOKE_MAP,
            "package_identity": _SMOKE_MAP}
    rich_far = dict(bare_far)
    rich_far.update({
        "actor_count": 2, "support_total": 158,
        "raw_evidence": {
            "actor": {"/A": {"bounds_origin": [0.0, 0.0, 0.0],
                             "bounds_extent": [10.0, 10.0, 10.0]},
                      "/B": {"bounds_origin": [5.0, 5.0, 5.0],
                             "bounds_extent": [1.0, 2.0, 3.0]}},
            "marker": {"m0": {"grounded": True, "footprint": True, "accepted": False,
                              "overlap": True, "capsule_clear": False},
                       "m1": {"grounded": True, "footprint": True, "accepted": True,
                              "overlap": False, "capsule_clear": True}},
            "inventory": {"pre": dict(_inv, stage="anchor_bind"),
                          "post": dict(_inv, stage="cleanup")},
            "temporary_placement": _placements,
            "document": _ledger_doc,
            "proxy": {"runtime_proxies": {"value": None, "collection_ok": False,
                                          "stage": "observe", "detail": "no BeginPlay"}},
        },
    })
    rich_ev = _build_evidence(args, rich_far, [], True)
    expected = {"actor_bounds_valid": True, "support_samples_total": 158,
                "temporary_placements_grounded": 2, "overlap_count": 1,
                "player_clearance_valid": False, "cleanup_verified": True,
                "temporary_placements_accepted": 1}
    for field, want in sorted(expected.items()):
        got = _reported(rich_ev[field])
        if got != want:
            problems.append("with a populated structured bundle, {} derived {!r}, "
                            "expected {!r} ({})".format(field, got, want,
                                                        rich_ev[field].get("detail")))
    # grounded must not silently equal accepted — that was the discarded-value bug.
    if _reported(rich_ev["temporary_placements_grounded"]) == \
            _reported(rich_ev["temporary_placements_accepted"]):
        problems.append("temporary_placements_grounded equals ..._accepted on a "
                        "fixture built to make them differ; the grounded observation "
                        "is being discarded again")
    # every record must be a well-formed evidence record (derived ones cite raw).
    for name in sorted(rich_ev):
        bad = [c[0] for c in SSE.validate_record(rich_ev[name], name, strict=True)
               if not c[1]]
        if bad:
            problems.append("evidence record {} is malformed: {}".format(name, bad))

    # (3) runtime_executed must not be true on a failed exit code.
    for code, want in ((0, True), (1, False), (None, False)):
        run = {"exit_code": code, "stdout": "", "secs": 0.0, "far": rich_far,
               "parsed": _parse_markers("")}
        rep, _d, _c, _b = _build_report(args, SS._example_scene_survey_subject(), [],
                                        [run], True)
        if rep["runtime_executed"] is not want:
            problems.append("runtime_executed is {!r} for exit_code={!r}; a non-zero "
                            "exit is not an execution".format(rep["runtime_executed"], code))
    return problems


def _smoke_operation_wiring():
    """The operation library must actually refuse what it exists to refuse."""
    problems = []
    for hostile in ("C:/evil", "../outside", "/etc/passwd", "\\\\server\\share",
                    "procedural/../../escape"):
        res = OP.confine_path(REPO_ROOT, hostile)
        if res.ok:
            problems.append("confine_path ACCEPTED the escaping output_location {!r} "
                            "-> {}".format(hostile, res.value))
    good = OP.confine_path(REPO_ROOT, "procedural/reports/scene_survey/runtime")
    if not good.ok:
        problems.append("confine_path refused a legitimate repo-relative "
                        "output_location: [{}] {}".format(good.code, good.detail))
    mp = OP.manifest_path_for(REPO_ROOT, "op_smoke_scene_survey")
    rp = OP.report_path_for(REPO_ROOT, "op_smoke_scene_survey")
    if not (mp.ok and rp.ok):
        problems.append("operation-scoped artifact paths do not resolve: {} / {}".format(
            mp.detail, rp.detail))
    elif mp.value["absolute"].parent != rp.value["absolute"].parent:
        problems.append("the manifest and the derived report are not in the same "
                        "operation directory ({} vs {})".format(
                            mp.value["absolute"].parent, rp.value["absolute"].parent))
    # NaN must be refused at serialization, not emitted.
    nan_res = OP.pretty_json_bytes({"x": float("nan")})
    if nan_res.ok:
        problems.append("pretty_json_bytes emitted NaN instead of refusing it")
    return problems


# --------------------------------------------------------------------------- #
# the survey itself (everything here runs UNDER the single-writer lock)
# --------------------------------------------------------------------------- #
def _run_survey(args):
    """Every refusal path below is inside main()'s try/finally, so the lock releases.

    That is the whole reason this is a separate function: the eight early ``return
    2`` guards all fire BEFORE any artifact work, and each one used to leave the
    previous operation's report on disk. They now also each have to release a lock,
    and eight hand-written releases is eight chances to forget one.
    """
    # ---- exactly one way to state a subject ---------------------------------
    legacy = [n for n, v in (("--map", args.map), ("--anchor", args.anchor)) if v is not None]
    if legacy:
        print("[scene-survey] FAIL — {} cannot express a caller-resolved survey subject "
              "and is refused (not overridden). Pass --request <BridgeRequest.json> whose "
              "'subject' is a SceneSurveySubject: WorldForge verifies a subject, it never "
              "picks one.".format(" / ".join(legacy)))
        return 2
    if not args.request:
        print("[scene-survey] FAIL — --request <BridgeRequest.json> is required for a live "
              "survey (or use --smoke for the bootless self-check)")
        return 2
    if not args.project:
        print("[scene-survey] FAIL — --project is required for a live survey")
        return 2

    req, _raw, err = _load_request(args.request)
    if err:
        print("[scene-survey] FAIL — {}".format(err))
        return 2
    if req.requested_operation != OPERATION:
        print("[scene-survey] FAIL — {} — request declares requested_operation {!r}, but "
              "this command drives {!r}".format(
                  C.CAPABILITY_UNAVAILABLE, req.requested_operation, OPERATION))
        return 2

    captures = [c.strip() for c in (args.capture or "").split(",") if c.strip()]
    subject = req.subject if isinstance(req.subject, dict) else None

    # Delegate BOTH the subject and the capture list to the capability registry's
    # payload validator — one validator, not a second copy that could drift.
    from bridge import capability_ops as OPS
    pfails = [c for c in OPS.get_op(OPERATION).validate_payload(
        {"subject": subject, "captures": captures}, strict=True) if not c[1]]
    if pfails:
        print("[scene-survey] FAIL — the request's survey payload is invalid:")
        for name, _ok, detail, code in pfails[:8]:
            print("[scene-survey]   {} [{}] {}".format(name, code, detail))
        return 2

    # The request states a map and the subject states a map. They must be the same
    # map, or the pair silently disagrees about what was surveyed (WF1107).
    if req.target_map and req.target_map != subject.get("map_asset_path"):
        print("[scene-survey] FAIL — {} — request target_map {!r} != subject "
              "map_asset_path {!r}".format(C.SCENE_SURVEY_SUBJECT_MISMATCH,
                                           req.target_map, subject.get("map_asset_path")))
        return 2

    # ---- plugin SOURCE preflight: do NOT boot a stale/unidentified far side ----
    ok, detail, observed_hash = _preflight_plugin_source(
        args.project, req.required_plugin_source_hash)
    if not ok:
        print("[scene-survey] FAIL — {} — {}".format(C.BRIDGE_STALE_PLUGIN, detail))
        print("[scene-survey] editor NOT launched (preflight is before the boot, on "
              "purpose: a stale plugin produces a plausible survey of the wrong code)")
        return 2
    print("[scene-survey] plugin source preflight OK — {}".format(detail))

    # ---- operation identity ----------------------------------------------------
    # The request owns the operation id. A --operation-id that disagrees with it is a
    # refusal, not a silent override: the two would name different operations and the
    # manifest could only bind one of them.
    if args.operation_id and args.operation_id != req.operation_id:
        print("[scene-survey] FAIL — {} — --operation-id {!r} disagrees with the "
              "request's operation_id {!r}. One asking, one id.".format(
                  C.SCENE_SURVEY_OPERATION_ID_MISMATCH, args.operation_id, req.operation_id))
        return 2
    args.operation_id = req.operation_id

    hashed = OP.hash_request(req)
    if not hashed.ok:
        print("[scene-survey] FAIL — {} — cannot hash the request ({}): {}".format(
            hashed.code, hashed.reason, hashed.detail))
        return 2
    request_hash = hashed.value["request_hash"]

    # ---- output_location confinement (WF1130) ----------------------------------
    # Previously: response_dir = REPO_ROOT / req.output_location, straight into
    # mkdir(parents=True). On Windows Path(r"D:\repo") / "C:/evil" IS "C:/evil", so a
    # caller-supplied absolute path replaced the root and this command created
    # directories outside the repository.
    conf = OP.confine_path(REPO_ROOT, req.output_location)
    if not conf.ok:
        print("[scene-survey] FAIL — {} — output_location {!r} is refused ({}): {}".format(
            conf.code, req.output_location, conf.reason, conf.detail))
        return 2
    response_dir = conf.value["absolute"]

    man_res = OP.manifest_path_for(REPO_ROOT, args.operation_id)
    rep_res = OP.report_path_for(REPO_ROOT, args.operation_id)
    for res in (man_res, rep_res):
        if not res.ok:
            print("[scene-survey] FAIL — {} — {}".format(res.code, res.detail))
            return 2
    manifest_path = man_res.value["absolute"]
    op_report_path = rep_res.value["absolute"]
    op_dir = manifest_path.parent

    # ---- refuse conflicting pre-existing operation output -----------------------
    # An operation is one asking. If this id already published a manifest, either it
    # answers a DIFFERENT question (a conflict) or it answers this one (a replay);
    # overwriting either would destroy the evidence that made the distinction
    # visible. A re-run needs a fresh operation_id.
    if manifest_path.exists():
        existing = OP.load_operation_manifest(manifest_path)
        if not existing.ok:
            print("[scene-survey] FAIL — {} — operation {!r} already has output at {} "
                  "and it is unusable ({}): {}".format(
                      existing.code, args.operation_id,
                      manifest_path.relative_to(REPO_ROOT).as_posix(),
                      existing.reason, existing.detail))
            return 2
        bound = OP.verify_operation_evidence(REPO_ROOT, existing.value, req,
                                             check_files=False)
        print("[scene-survey] FAIL — {} — operation {!r} has ALREADY published a "
              "manifest at {}. {} Refusing to overwrite an operation's own evidence; "
              "issue a new operation_id for a new asking.".format(
                  C.SCENE_SURVEY_OPERATION_ID_MISMATCH, args.operation_id,
                  manifest_path.relative_to(REPO_ROOT).as_posix(),
                  ("It binds this exact request (a replay)." if bound.ok
                   else "It does not bind this request ({}): {}".format(
                       bound.reason, bound.detail))))
        return 2

    _engine_root, ue_cmd = _resolve_paths(args)
    args.resolved_engine_root = str(getattr(_engine_root, "value", _engine_root))
    args.artifact_dir = op_dir
    try:
        op_dir.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print("[scene-survey] FAIL — cannot create the operation directory {}: {}".format(
            op_dir, exc))
        return 2

    # Stale-artifact discipline, now scoped to THIS operation's own directory. The
    # shared "latest" path is no longer unlinked ahead of a run that might refuse:
    # it is a mirror, republished atomically at the end or left exactly as it was.
    for stale in sorted(op_dir.glob("far_side_run*.json")):
        if stale.is_file():
            stale.unlink()

    runs = []
    for i in range(1, max(1, args.repeat) + 1):
        out_json = op_dir / "far_side_run{}.json".format(i)
        print("[scene-survey] run {}/{} -> booting {} on {} (subject {})".format(
            i, args.repeat, Path(str(args.project)).name,
            subject.get("map_asset_path"), subject.get("subject_id")))
        runs.append(_one_run(args, subject, captures, args.request, ue_cmd.value,
                             out_json, request_hash))

    hashes = [_spatial_hash(r) for r in runs]
    # Determinism over the STRUCTURED channel, and never vacuous: identical hashes of
    # two runs that both observed nothing prove nothing about determinism.
    determinism_ok = (len(set(hashes)) == 1
                      and _far_doc(runs[0]).get("support_total") is not None)
    survey, disagreements, corroborated, binding_fails = _build_report(
        args, subject, captures, runs, determinism_ok)

    # validate the domain SceneSurveyReport against its contract before writing.
    fails = [c for c in SS.validate_scene_survey_report(survey, strict=True) if not c[1]]
    unknown_fields = survey["meta"]["evidence_unknown_fields"]
    if fails:
        print("[scene-survey] WARNING — survey failed self-validation: {}".format(
            [c[0] for c in fails][:8]))
        if unknown_fields:
            print("[scene-survey]   this is EXPECTED while {} field(s) are unobserved: "
                  "{}. The contract (scene_survey_contracts.REPORT_REQUIRED) demands a "
                  "non-null int/bool for them; an honest 'unknown' is None. The fix is "
                  "in the contract's _REPORT_NULLABLE, not a fabricated zero here."
                  .format(len(unknown_fields), unknown_fields))

    # Evidence ownership: WorldForge may author only under procedural/ inside any
    # tree it writes to (tools/bridge/live.py:362-394). A leak here would mean this
    # command wrote somewhere it does not own.
    from bridge.live import evidence_belongs_to
    foreign = evidence_belongs_to(survey["evidence_paths"], None, worldforge_authored=True)

    # Wrap the domain report in a house report so the report-integrity gate (which
    # scans *_report.json for a real meta block + checks + a bounded status) accepts
    # it. The domain SceneSurveyReport (with its own status vocab pass/fail/blocked)
    # rides under "survey"; the house wrapper carries build_meta + checks + ok/fail.
    tot = survey["support_samples_total"]
    checks = [
        {"name": "runtime_executed", "verdict": "pass" if survey["runtime_executed"] else "fail"},
        {"name": "subject_resolved_by_caller",
         "verdict": "pass" if survey["subject_resolved_by"] == "caller" else "fail"},
        {"name": "subject_binding", "verdict": "pass" if not binding_fails else "fail"},
        {"name": "channels_corroborated",
         "verdict": "fail" if disagreements else ("pass" if corroborated else "warn")},
        # An unobserved value is "unknown", never a silent fail and never a pass.
        {"name": "support_samples_present",
         "verdict": ("pass" if tot > 0 else "fail") if isinstance(tot, int) else "unknown"},
        {"name": "actors_enumerated",
         "verdict": ("pass" if survey["actor_bounds_valid"] else "fail")
                    if survey["actor_bounds_valid"] is not None else "unknown"},
        {"name": "deterministic", "verdict": "pass" if determinism_ok else "fail"},
        {"name": "cleanup_verified",
         "verdict": ("pass" if survey["cleanup_verified"] else "fail")
                    if survey["cleanup_verified"] is not None else "unknown"},
        {"name": "contract_valid", "verdict": "pass" if not fails else "fail"},
        {"name": "evidence_ownership", "verdict": "fail" if foreign else "pass"},
        # Capture is opt-in: not-applicable when nobody asked, fail when they did.
        {"name": "camera_capture",
         "verdict": ("pass" if survey["camera_capture_ok"] else "fail") if survey["captures_requested"]
                    else "skip_not_applicable"},
    ]
    house_status = "fail" if any(c["verdict"] == "fail" for c in checks) else "ok"
    wrapped = {
        "status": house_status,
        "checks": checks,
        # The REQUESTED subject rides alongside the survey so the report can be
        # bound back to the request that produced it. Without it the evidence is
        # unfalsifiable: you cannot ask "was this the subject I asked for?" of a
        # report that never states what was asked. validate_scene_survey_runtime
        # binds these two with validate_subject_binding (WF1107/WF1108).
        "subject": subject,
        "survey": survey,
        "operation": {
            "operation_id": args.operation_id,
            "request_hash": request_hash,
            "request_hash_field_set_version": hashed.value["field_set_version"],
            "manifest_path": manifest_path.relative_to(REPO_ROOT).as_posix(),
            "authoritative_report_path": op_report_path.relative_to(REPO_ROOT).as_posix(),
            "shared_mirror_path": LEGACY_REPORT.relative_to(REPO_ROOT).as_posix(),
        },
        "meta": build_meta(
            command="run-scene-survey-probe", pack="worldforge_vertical_slice",
            strict=args.strict, status=house_status, record_count=1, records_total=1,
            report_type=SS.RT_SURVEY_REPORT),
    }

    # ======================= ATOMIC PUBLICATION ORDER ========================== #
    # temp -> flush/fsync -> validate -> rename into final -> MANIFEST LAST.
    # A manifest visible before its evidence is a lie, so the seal is the last thing
    # that appears and every artifact it names is already durable when it does.
    pub = OP.atomic_write_json(op_report_path, wrapped, repo_root=REPO_ROOT)
    if not pub.ok:
        print("[scene-survey] FAIL — {} — could not publish the derived report ({}): "
              "{}".format(pub.code, pub.reason, pub.detail))
        return 2
    mirror = OP.atomic_write_json(LEGACY_REPORT, wrapped, repo_root=REPO_ROOT)
    if not mirror.ok:
        print("[scene-survey] WARNING — the shared mirror {} was not updated ({}): "
              "{}".format(LEGACY_REPORT.name, mirror.reason, mirror.detail))

    response, resp_res = _emit_response(req, survey, _far_doc(runs[-1]), response_dir)
    if response is None:
        print("[scene-survey] FAIL — {} — could not publish the response ({}): {}".format(
            resp_res.code, resp_res.reason, resp_res.detail))
        return 2

    # ---- the manifest, built over artifacts that are already on disk ------------
    raw_entries = [{"path": rel, "role": "far_side_run"} for rel in survey["evidence_paths"]]
    req_rel = OP.relative_posix(REPO_ROOT, Path(args.request))
    if req_rel.ok:
        raw_entries.append({"path": req_rel.value, "role": "request"})
    resp_rel = OP.relative_posix(REPO_ROOT, response)
    if resp_rel.ok:
        raw_entries.append({"path": resp_rel.value, "role": "response"})

    # Only CLAIM cleanup when the derivation was actually sufficient. Handing the
    # library its default block would publish cleanup_verified=False as though it
    # were a finding; handing it a fabricated True is what this whole change exists
    # to stop. When cleanup is unknown, the manifest says nothing about it.
    cleanup_block = None
    if survey["cleanup_verified"] is not None:
        inputs = (survey["meta"]["evidence"]["cleanup_verified"].get("inputs") or {})
        cleanup_block = {
            "cleanup_verified": bool(survey["cleanup_verified"]),
            "temporary_placements": len(
                (_raw_bundle(_far_doc(runs[-1])).get("temporary_placement") or {})),
            "residual_actor_paths": list(inputs.get("leaked_actors") or []),
        }

    manifest = OP.build_operation_manifest(
        REPO_ROOT, req, raw_evidence=raw_entries,
        derived_report={"path": op_report_path.relative_to(REPO_ROOT).as_posix(),
                        "role": "other"},
        captures=[], cleanup=cleanup_block)
    if not manifest.ok:
        print("[scene-survey] FAIL — {} — could not build the operation manifest ({}): "
              "{}".format(manifest.code, manifest.reason, manifest.detail))
        return 2
    sealed = OP.publish_operation_manifest(REPO_ROOT, manifest.value, dest=manifest_path)
    if not sealed.ok:
        print("[scene-survey] FAIL — {} — could not publish the operation manifest ({}): "
              "{}".format(sealed.code, sealed.reason, sealed.detail))
        return 2

    report = survey  # for the summary print below
    print("[scene-survey] -> {}  (AUTHORITATIVE)".format(
        op_report_path.relative_to(REPO_ROOT).as_posix()))
    print("[scene-survey] -> {}  (shared mirror, not the evidence of record)".format(
        LEGACY_REPORT.relative_to(REPO_ROOT).as_posix()))
    print("[scene-survey] -> {}  (manifest, published LAST)".format(
        manifest_path.relative_to(REPO_ROOT).as_posix()))
    try:
        print("[scene-survey] -> {}".format(response.relative_to(REPO_ROOT).as_posix()))
    except ValueError:
        print("[scene-survey] -> {}".format(response))
    for k in ("status", "runtime_executed", "subject_id", "observed_anchor_location",
              "observed_anchor_object_path", "captures_requested",
              "support_samples_total", "support_samples_valid",
              "unsupported_regions", "edge_regions", "temporary_placements_grounded",
              "overlap_count", "player_clearance_valid", "cleanup_verified",
              "proxy_owners", "proxies_disabled",
              "determinism_hash", "failure_codes"):
        v = report.get(k)
        print("[scene-survey]   {:<28} = {}".format(
            k, "unknown (nothing observed it)" if v is None and k in unknown_fields else v))
    print("[scene-survey]   evidence_unknown_fields      = {}".format(unknown_fields or "none"))
    print("[scene-survey]   determinism_consistent       = {} ({})".format(
        determinism_ok, hashes))
    print("[scene-survey]   channel_corroborated         = {} {}  [stdout is "
          "diagnostic only]".format(corroborated, disagreements or ""))
    print("[scene-survey]   request_hash                 = {}".format(request_hash[:19]))
    print("[scene-survey]   plugin_source_hash           = {}".format(
        (observed_hash or "?")[:12]))
    # A clean survey exits 0. "blocked" (incomplete but honest) and "fail" exit 1.
    return 0 if report["status"] == "pass" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 SceneSurveyForge operator command.")
    ap.add_argument("--smoke", action="store_true", help="bootless self-check; no UE launch")
    ap.add_argument("--target-repository", default=None)
    ap.add_argument("--project", default=None, help="external .uproject to survey")
    ap.add_argument("--engine-root", default=None)
    ap.add_argument("--ue-cmd", default=None)
    ap.add_argument("--request", default=None,
                    help="BridgeRequest JSON carrying the caller-resolved subject "
                         "(the ONLY way to state a survey subject)")
    # Retained ONLY so they can be REJECTED with a real explanation. Neither can
    # express a caller-resolved subject, and silently honouring one would let
    # WorldForge survey somewhere the caller never asked about. No default, no
    # choices: any value at all is refused.
    ap.add_argument("--map", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--anchor", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--capture", default="",
                    help="comma-separated capture kinds to request; empty (default) "
                         "requests none — capture is opt-in")
    ap.add_argument("--sample-radius-cm", type=float, default=3000.0)
    ap.add_argument("--sample-step-cm", type=float, default=100.0)
    ap.add_argument("--temporary-markers", type=int, default=3)
    ap.add_argument("--disable-debug-proxies", action="store_true")
    ap.add_argument("--cleanup", action="store_true")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    # No default: the REQUEST owns the operation id. Passing this is an assertion
    # that the request agrees, and a disagreement is refused rather than resolved.
    ap.add_argument("--operation-id", default=None)
    args, _ = ap.parse_known_args(argv)

    if args.smoke:
        return _smoke()

    # ---- single-writer lock, BEFORE every refusal path -------------------------
    # All eight early `return 2` guards live inside _run_survey. Acquiring here and
    # releasing in `finally` is what makes a refused run give the lock back: eight
    # hand-written releases would be eight chances to leave it held for the full TTL
    # (DEFAULT_LOCK_TTL_SECONDS = 3600).
    lock = OP.acquire_operation_lock(REPO_ROOT, args.operation_id or DEFAULT_OPERATION_ID)
    if not lock.ok:
        print("[scene-survey] FAIL — {} — {}".format(lock.code, lock.detail))
        return 2
    print("[scene-survey] single-writer lock — {}".format(lock.detail))
    try:
        return _run_survey(args)
    finally:
        released = OP.release_operation_lock(lock.value)
        if not released.ok:
            print("[scene-survey] WARNING — {} — the operation lock was not released "
                  "({}): {}".format(released.code, released.reason, released.detail))


if __name__ == "__main__":
    sys.exit(main())
