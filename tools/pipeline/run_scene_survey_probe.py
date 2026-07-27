#!/usr/bin/env python3
r"""run_scene_survey_probe.py — v2.6 SceneSurveyForge operator command.

The single documented surface that runs a READ-ONLY scene survey against an external
UE 5.8 project. It boots the target project's editor headless, executes
tools/bridge/scene_survey_far_side.py inside it (which drives the compiled
USceneSurveyStatics primitives over the caller's subject), then re-derives a
SceneSurveyReport from the WF_SURVEY_* markers on stdout and the far-side JSON —
without trusting the far side (runtime_executed=True only when a real process
returned; observed engine comes from the running editor, never a config file).

WHO CHOOSES THE SUBJECT (v2.6): the caller does, and only the caller. A survey is
requested with --request <BridgeRequest.json>, whose ``subject`` is an
already-resolved SceneSurveySubject. There is exactly ONE way to state a subject;
the legacy --map/--anchor pair cannot express a resolved subject and is REJECTED
rather than silently overridden, because a command that accepts two ways to say
where to look is a command that can look somewhere the caller did not ask about.
The far side VERIFIES that subject and echoes what it actually anchored on; this
side BINDS the two with validate_subject_binding (WF1107/WF1108).

TWO INDEPENDENT CHANNELS, CORROBORATED: the spatial result arrives twice — as
WF_SURVEY_* marker lines emitted by the compiled C++ primitives (which the far-side
Python cannot forge) and as the far-side JSON. They are asserted to agree; a
divergence is WF1109 and fails the survey. Both channels are kept precisely because
either alone would have to be taken on trust.

Read-only w.r.t. the target: never saves the map, authors no permanent actor, and
places no persistent marker (marker CLEARANCE is trace-probed, never spawned). This
pass runs under -nullrhi and does the spatial work (enumeration + 6-class support +
marker clearance). MeshForge proxy toggle needs a -game pass and is honestly reported
as not-run-in-this-pass. Camera capture is OPT-IN (--capture, default none): a survey
that was never asked to render is NOT failed for not rendering, so a clean -nullrhi
spatial pass can and does exit 0. When captures ARE requested and cannot be produced,
WF1068 fires and the status is "blocked" — the honesty rail is preserved exactly
where it was earned.

Before booting, the plugin SOURCE tree in the target project is hashed and compared
against the request's required_plugin_source_hash; a mismatch (or an unstated pin) is
WF1026 and the editor is NOT launched.

Determinism: --repeat N runs the survey N times and proves the spatial results are
byte-identical (determinism_hash); a mismatch is WF1094.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/run_scene_survey_probe.py --smoke   (bootless self-check)
Live (single-writer against a real project):
    PYTHONUTF8=1 python tools/pipeline/run_scene_survey_probe.py \
        --project "<abs>/<Target>.uproject" \
        --request procedural/generated/scene_survey/requests/<operation_id>.json \
        --capture "" \
        --sample-radius-cm 3000 --sample-step-cm 100 --temporary-markers 3 \
        --repeat 2 --strict
Report   -> procedural/reports/scene_survey/runtime/scene_survey_report.json
Response -> <request.output_location>/scene_survey_response_<operation_id>.json
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
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "runtime"
FAR_SIDE = REPO_ROOT / "tools" / "bridge" / "scene_survey_far_side.py"

# The capability this command drives. The registry (tools/bridge/capability_ops.py)
# owns the mapping requested_operation -> (payload validator, far-side script,
# response builder); this module only asks it for the scene-survey entry.
OPERATION = "scene_survey"

RE_SUPPORT = re.compile(
    r"WF_SURVEY_SUPPORT total=(\d+) valid=(\d+) unsupported=(\d+) edge=(\d+) "
    r"blocked=(\d+) trace_error=(\d+) unknown=(\d+)")
RE_ENUM = re.compile(r"WF_SURVEY_ENUM actors=(\d+) components=(\d+)")
RE_MARKER = re.compile(
    r"WF_SURVEY_MARKER .*grounded=(\d) footprint=(\d) overlap=(\d) "
    r"clearance=(\d) accepted=(\d)")


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
    """Extract the spatial result from the WF_SURVEY_* marker lines.

    This is the channel the far-side Python cannot forge: the lines are emitted by
    the compiled C++ primitives themselves (SceneSurvey.cpp), so agreement between
    this and the far-side JSON is real corroboration rather than one source quoted
    twice.
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


def _spatial_hash(parsed):
    """Deterministic hash over the spatial result (the determinism unit)."""
    payload = json.dumps({"support": parsed["support"], "enum": parsed["enum"],
                          "markers": parsed["markers"]}, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _channel_disagreements(parsed, far):
    """Compare the stdout marker channel against the far-side JSON channel.

    Returns (disagreements, corroborated). A field is compared only when BOTH
    channels reported it; a field only one channel saw is not a disagreement, it is
    an absence — and ``corroborated`` is what says the run was cross-checked at all.
    Values are the C++ return values by construction: enumerate_survey_actors returns
    the actor count and logs WF_SURVEY_ENUM actors=N; sample_survey_support returns
    the sample total and logs WF_SURVEY_SUPPORT total=N; probe_temp_marker returns the
    accepted bool and logs WF_SURVEY_MARKER accepted=d
    (Plugins/WorldForge/Source/WorldForgeCore/Private/SceneSurvey.cpp:75,183,233).
    """
    far = far if isinstance(far, dict) else {}
    en = parsed.get("enum") or {}
    sup = parsed.get("support") or {}
    mks = parsed.get("markers") or []
    ran = far.get("actor_count") is not None
    pairs = [
        ("actor_count", en.get("actors"), far.get("actor_count")),
        ("support_total", sup.get("total"), far.get("support_total")),
    ]
    if ran:
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


def _one_run(args, subject, captures, request_path, ue_cmd, out_json):
    """Boot the editor once. The subject rides as inline JSON; the map comes from it."""
    env_extra = {
        "WF_SURVEY_OUT": str(out_json).replace("\\", "/"),
        # PRIMARY subject channel. There is deliberately no WF_SURVEY_MAP: a second
        # map knob could disagree with the subject about what was surveyed.
        "WF_SURVEY_SUBJECT": json.dumps(subject, sort_keys=True),
        # FALLBACK channel, read by the far side only if WF_SURVEY_SUBJECT is empty.
        "WF_SURVEY_REQUEST": str(Path(request_path).resolve()).replace("\\", "/"),
        "WF_SURVEY_CAPTURES": ",".join(captures),
        "WF_SURVEY_RADIUS_CM": str(args.sample_radius_cm),
        "WF_SURVEY_STEP_CM": str(args.sample_step_cm),
        "WF_SURVEY_MARKERS": str(args.temporary_markers),
        "WF_SURVEY_OPERATION_ID": args.operation_id,
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


def _build_report(args, subject, captures, runs, determinism_ok):
    """Fold the runs into a SceneSurveyReport (per the v2.6 contract).

    Capture policy (v2.6): capture is OPT-IN. WF1068 is appended only when the
    caller actually requested captures and none could be produced. A survey that was
    never asked to render is not failed for not rendering, which is what makes a
    clean -nullrhi pass able to exit 0.
    """
    last = runs[-1]
    parsed, far = last["parsed"], last["far"]
    sup = parsed.get("support") or {}
    en = parsed.get("enum") or {}
    runtime_executed = last["exit_code"] is not None
    markers = parsed.get("markers") or []
    grounded = sum(1 for mk in markers if mk.get("accepted"))
    overlaps = sum(1 for mk in markers if mk.get("overlap"))
    clearance_ok = all((not mk.get("accepted")) or mk.get("clearance") for mk in markers)

    disagreements, corroborated = _channel_disagreements(parsed, far)
    subject_resolved = far.get("subject_resolved") is True
    obs_loc = far.get("observed_anchor_location")
    obs_path = far.get("observed_anchor_object_path")

    # ---- world identity: the ONE binding input that is not a copy of the request --
    # Re-derived here from the far side's RAW observation, independently of whatever
    # the far side concluded. far["map"], far["subject_id"] and
    # far["subject_resolved_by"] are echoes of the subject (scene_survey_far_side.py
    # :197-202), so consuming those instead of `subject` would compare a value to a
    # copy of itself just as surely. observed_world_package is measured from the live
    # editor, so it is the only one that can disagree.
    requested_map = subject.get("map_asset_path", "")
    observed_pkg = far.get("observed_world_package")
    map_loaded = far.get("loaded") is True
    world_identity_ok = (map_loaded
                         and _norm_package(observed_pkg) is not None
                         and _norm_package(observed_pkg) == _norm_package(requested_map))
    # The report's map_asset_path is now the OBSERVED world, not the requested one.
    # That is what makes sb::map_match a real comparison instead of a tautology: if
    # the editor opened a different world, the two sides now differ and the rail
    # fires. When identity could not be established we emit "" rather than the
    # request — an unobserved map must never be reported as an observed one.
    observed_map_asset_path = _canon_package(observed_pkg) if world_identity_ok else ""

    evidence = []
    for i in range(1, len(runs) + 1):
        p = REPORT_DIR / "far_side_run{}.json".format(i)
        if p.is_file():
            evidence.append(p.relative_to(REPO_ROOT).as_posix())

    # Capture is opt-in; nothing here can render under -nullrhi, so camera_capture_ok
    # is only ever True if a future rendering pass populated it. It is never asserted.
    camera_capture_ok = bool(far.get("camera_capture_ran"))
    captures_missing = bool(captures) and not camera_capture_ok

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
        "camera_capture_ok": camera_capture_ok,
        "actor_bounds_valid": bool(en.get("actors", 0) > 0 and not far.get("error")),
        "support_samples_total": int(sup.get("total", 0)),
        "support_samples_valid": int(sup.get("valid", 0)),
        "unsupported_regions": int(sup.get("unsupported", 0)),
        "edge_regions": int(sup.get("edge", 0)),
        "proxy_owners": 0,
        "proxies_disabled": False,
        "temporary_placements_grounded": int(grounded),
        "overlap_count": int(overlaps),
        "player_clearance_valid": bool(clearance_ok),
        "cleanup_verified": True,  # markers are trace-probed, never spawned: nothing to clean
        "determinism_hash": _spatial_hash(parsed),
        "runtime_mode": "live_survey_runtime" if runtime_executed else "deterministic_survey_simulation",
        "runtime_executed": runtime_executed,
        "evidence_paths": evidence,
        "failure_codes": [],
        "status": "fail",
        "schema_version": SS.RT_SURVEY_REPORT,
        "report_type": SS.RT_SURVEY_REPORT,
        "created_by": "worldforge.v2.6",
        "created_at": SS.AUTHORING_TS,
        "meta": {
            "engine_root": args.engine_root or "resolved",
            "observed_engine_version": far.get("observed_engine_version"),
            "uproject": far.get("resolved_uproject") or str(args.project),
            "runtime_executed": runtime_executed,
            "repeat": args.repeat,
            "determinism_consistent": determinism_ok,
            "per_run_hashes": [_spatial_hash(r["parsed"]) for r in runs],
            "subject_source": far.get("subject_source"),
            "anchor_detail": far.get("anchor_detail"),
            "channel_corroborated": corroborated,
            "channel_disagreements": disagreements,
            "camera_pass": far.get("camera_capture_reason"),
            "proxy_pass": far.get("proxy_pass_reason"),
        },
    }

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
    # A survey that saw nothing cannot claim a pass, whatever else went right.
    if not (report["actor_bounds_valid"] and report["support_samples_total"] > 0
            and evidence):
        fcodes.append(C.SCENE_SURVEY_EVIDENCE_MISSING)

    # A wrong/absent subject, a forged-looking channel, a non-deterministic or
    # non-executed run are FAILURES. A merely incomplete one (capture pending, no
    # spatial evidence yet) is BLOCKED. Neither is ever quietly a pass.
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
    """Write the BridgeResponse for this operation into the request's output_location."""
    from bridge import capability_ops as OPS
    op = OPS.get_op(OPERATION)
    paths, hashes = [], []
    for rel in survey.get("evidence_paths", []):
        abs_p = REPO_ROOT / rel
        if abs_p.is_file():
            paths.append(rel)
            hashes.append(_sha256_file(abs_p))
    resp = op.build_response(req, far, evidence_paths=paths, evidence_hashes=hashes)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "scene_survey_response_{}.json".format(req.operation_id)
    dest.write_text(json.dumps(resp.to_dict(), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return dest


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

    if problems:
        for p in problems:
            print("[scene-survey-smoke] FAIL — {}".format(p))
        return 1
    print("[scene-survey-smoke] PASS — operator surface wired (far-side present, "
          "capability registered, report contract satisfied, capture opt-in proven "
          "both ways, subject binding enforced)")
    return 0


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
    ap.add_argument("--operation-id", default="op_v2_6_scene_survey_0001")
    args, _ = ap.parse_known_args(argv)

    if args.smoke:
        return _smoke()

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

    _engine_root, ue_cmd = _resolve_paths(args)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Stale-artifact discipline: every artifact THIS operation writes is removed
    # before launching, so nothing a prior run left behind can masquerade as this
    # run's result (the per-run far-side JSON is also unlinked in _one_run).
    out = REPORT_DIR / "scene_survey_report.json"
    response_dir = REPO_ROOT / req.output_location
    response_path = response_dir / "scene_survey_response_{}.json".format(req.operation_id)
    for stale in [out, response_path] + sorted(REPORT_DIR.glob("far_side_run*.json")):
        if stale.is_file():
            stale.unlink()

    runs = []
    for i in range(1, max(1, args.repeat) + 1):
        out_json = REPORT_DIR / "far_side_run{}.json".format(i)
        print("[scene-survey] run {}/{} -> booting {} on {} (subject {})".format(
            i, args.repeat, Path(str(args.project)).name,
            subject.get("map_asset_path"), subject.get("subject_id")))
        runs.append(_one_run(args, subject, captures, args.request, ue_cmd.value, out_json))

    hashes = [_spatial_hash(r["parsed"]) for r in runs]
    determinism_ok = len(set(hashes)) == 1 and runs[0]["parsed"]["support"] is not None
    survey, disagreements, corroborated, binding_fails = _build_report(
        args, subject, captures, runs, determinism_ok)

    # validate the domain SceneSurveyReport against its contract before writing.
    fails = [c for c in SS.validate_scene_survey_report(survey, strict=True) if not c[1]]
    if fails:
        print("[scene-survey] WARNING — survey failed self-validation: {}".format(
            [c[0] for c in fails][:6]))

    # Evidence ownership: WorldForge may author only under procedural/ inside any
    # tree it writes to (tools/bridge/live.py:362-394). A leak here would mean this
    # command wrote somewhere it does not own.
    from bridge.live import evidence_belongs_to
    foreign = evidence_belongs_to(survey["evidence_paths"], None, worldforge_authored=True)

    # Wrap the domain report in a house report so the report-integrity gate (which
    # scans *_report.json for a real meta block + checks + a bounded status) accepts
    # it. The domain SceneSurveyReport (with its own status vocab pass/fail/blocked)
    # rides under "survey"; the house wrapper carries build_meta + checks + ok/fail.
    checks = [
        {"name": "runtime_executed", "verdict": "pass" if survey["runtime_executed"] else "fail"},
        {"name": "subject_resolved_by_caller",
         "verdict": "pass" if survey["subject_resolved_by"] == "caller" else "fail"},
        {"name": "subject_binding", "verdict": "pass" if not binding_fails else "fail"},
        {"name": "channels_corroborated",
         "verdict": "fail" if disagreements else ("pass" if corroborated else "warn")},
        {"name": "support_samples_present",
         "verdict": "pass" if survey["support_samples_total"] > 0 else "fail"},
        {"name": "actors_enumerated", "verdict": "pass" if survey["actor_bounds_valid"] else "fail"},
        {"name": "deterministic", "verdict": "pass" if determinism_ok else "fail"},
        {"name": "cleanup_verified", "verdict": "pass" if survey["cleanup_verified"] else "fail"},
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
        "meta": build_meta(
            command="run-scene-survey-probe", pack="worldforge_vertical_slice",
            strict=args.strict, status=house_status, record_count=1, records_total=1,
            report_type=SS.RT_SURVEY_REPORT),
    }

    out.write_text(json.dumps(wrapped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    response = _emit_response(req, survey, runs[-1]["far"], response_dir)
    report = survey  # for the summary print below

    print("[scene-survey] -> {}".format(out.relative_to(REPO_ROOT).as_posix()))
    try:
        print("[scene-survey] -> {}".format(response.relative_to(REPO_ROOT).as_posix()))
    except ValueError:
        print("[scene-survey] -> {}".format(response))
    for k in ("status", "runtime_executed", "subject_id", "observed_anchor_location",
              "observed_anchor_object_path", "captures_requested",
              "support_samples_total", "support_samples_valid",
              "unsupported_regions", "edge_regions", "temporary_placements_grounded",
              "overlap_count", "player_clearance_valid", "cleanup_verified",
              "determinism_hash", "failure_codes"):
        print("[scene-survey]   {:<28} = {}".format(k, report.get(k)))
    print("[scene-survey]   determinism_consistent       = {} ({})".format(
        determinism_ok, hashes))
    print("[scene-survey]   channel_corroborated         = {} {}".format(
        corroborated, disagreements or ""))
    print("[scene-survey]   plugin_source_hash           = {}".format(
        (observed_hash or "?")[:12]))
    # A clean survey exits 0. "blocked" (incomplete but honest) and "fail" exit 1 —
    # the caller can now gate on this, which it could not while every -nullrhi run
    # was forced non-pass regardless of outcome.
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
