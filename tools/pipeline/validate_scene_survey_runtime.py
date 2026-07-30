#!/usr/bin/env python3
"""validate_scene_survey_runtime.py — v2.6 scene-survey runtime evidence gate.

FAIL-CLOSED: green ONLY when a real runtime survey report exists for the operation
the CALLER named, is bound to that operation's request by hash, is fresh, validates
against the SceneSurveyReport contract, was produced by a genuine editor run
(runtime_executed=True), is deterministic across its repeat runs, AND every derived
value it reports is independently RE-DERIVED here from the raw evidence and found to
match. Until run_scene_survey_probe.py boots a target and writes that report with its
raw evidence bundle, this gate is honestly RED — there is no runtime truth to
validate yet.

A blocked-pending-camera report (the honest state of a -nullrhi spatial pass) is
ACCEPTED here: the runtime gate proves the survey ran, was well-formed, deterministic
and evidence-backed — camera completeness is a separate rendering pass, not faked
into a pass. What is rejected: a missing report, an invalid report, a report that
never executed, a report whose repeat runs disagree (WF1094), and a report whose
numbers do not follow from its own raw evidence (WF1112/WF1114).

SUBJECT BINDING (WF1106/1107/1108). A survey is only runtime truth about the thing
the CALLER asked about. So the runtime envelope must carry the SceneSurveySubject it
was handed alongside the report it produced, and the two must bind: same subject_id,
same map, the observed anchor within tolerance of the requested one (or on the exact
requested object), and resolved_by="caller" on both sides. A report that cannot be
bound to a request is unfalsifiable — it could have surveyed anything — so its
absence is a hard FAIL here, not a skip.

OPERATION BINDING (WF1096/1127/1128). Before v2.6-R this file read ONE hard-coded
path with no way to say WHICH operation was being graded, so any well-formed report
satisfied any operation forever; the gate was observed grading an eight-day-old
artifact without noticing. Input selection is now operation-scoped
(``--operation-id``), the artifact must be newer than the code that produces it, it
must be inside the caller's declared max age, and — when the operation manifest and
the originating request are available — it must match the request hash. Every one of
those is fail-closed: an operation nobody named is an operation nobody can verify.

WHY THE RED IS RED (WF1128/WF1129/WF1097). Three completely different situations
used to render as the same RED, so the gate's colour carried no information:

  * ``input::operation_id_resolved``   WF1128 — WIRING DEFECT. No source produced an
    operation id at all. The caller forgot to say what to grade. Fixed by editing a
    command line.
  * ``input::operation_id_unambiguous`` WF1129 — AMBIGUITY. More than one candidate
    operation was offered. The gate refuses to choose; picking one silently is how a
    run grades the wrong operation and nobody finds out.
  * ``input::caller_evidence_present``  WF1097 — ABSENT CALLER EVIDENCE. The gate
    knows exactly which operation it would grade, and no runtime artifact for that
    operation exists yet. THIS is the intentional RED this whole module is waiting
    on; it is fixed by booting an editor, not by editing a command line.

Exactly one of the three can be a blocking failure on any given run: the evidence
rail is SKIPPED when no id resolved, and the two resolution rails are mutually
exclusive by construction. See ``resolve_operation_id``.

INDEPENDENT RE-DERIVATION. This gate does not consult ANY of the report's own
success flags, derived booleans or summary counts. ``tools/pipeline/
scene_survey_recompute.py`` re-derives actor_bounds_valid, temporary_placements_
grounded, overlap_count, player_clearance_valid, cleanup_verified and world identity
from the raw ATOMS in the far-side evidence bundle, using a second implementation
that deliberately does not call the assembler's derivations — see that module's
docstring for which vocabulary is shared and why sharing it is not circular.

PROBE DEPENDENCY (v2.6, in flight): this rail requires run_scene_survey_probe.py to
write the resolved subject into the runtime envelope under "subject", and the
far-side raw evidence bundle under "raw_evidence" (or as manifest-bound far_side_run
artifacts). Until it does, this gate stays honestly RED — which is the correct
fail-closed state, not a defect in the rail. See the REPORT-BACK note.

Dogfooded on a synthetic clean envelope + one tamper per rail so the gate cannot
fake-green, and every dogfood negative runs the PRODUCTION rail rather than
re-evaluating a literal it just built.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_scene_survey_runtime.py \
        --operation-id op_v2_6_scene_survey_0001 \
        --request procedural/generated/scene_survey/requests/op_v2_6_scene_survey_0001.json \
        --strict
Reports -> procedural/reports/scene_survey/runtime/validate_scene_survey_runtime_report.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as SS
import scene_survey_operation as OP
import scene_survey_recompute as RC
from failure_codes import FailureCode as C
from report_meta import build_meta, git_sha, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "runtime"
# The legacy unscoped path. Retained ONLY as an explicitly-labelled fallback so an
# operator who omits --operation-id still gets a diagnostic report; the selection
# rails below refuse to treat anything found here as bound to an operation.
LEGACY_RUNTIME_REPORT = REPORT_DIR / "scene_survey_report.json"

# Producing code. An artifact older than the code that produces it cannot be
# evidence ABOUT that code, however well-formed it is — that is precisely how an
# eight-day-old report went on satisfying a gate whose producer had moved on.
PRODUCER_FILES = (
    REPO_ROOT / "tools" / "pipeline" / "run_scene_survey_probe.py",
    REPO_ROOT / "tools" / "bridge" / "scene_survey_far_side.py",
    REPO_ROOT / "tools" / "pipeline" / "scene_survey_contracts.py",
    REPO_ROOT / "tools" / "pipeline" / "scene_survey_evidence.py",
)

DEFAULT_MAX_AGE_SECONDS = 86400  # 24h; override with --max-age-seconds


# --------------------------------------------------------------------------- #
# operation-id resolution — an explicit, CLOSED set of sources
# --------------------------------------------------------------------------- #
# THE DEFECT THIS EXISTS FOR. v2_6_shield.py invokes this gate as
# ``validate_scene_survey_runtime.py --pack <pack> --strict`` and passes no
# --operation-id at all, so the gate went RED on a MISSING ARGUMENT — wearing the
# same colour as the honest, intentional RED this module is actually waiting on
# (no live runtime evidence has been produced yet). One of those is fixed by
# editing a command line; the other is fixed by booting an editor. A gate that
# renders them identically is a gate whose RED carries no information, and a
# wiring defect that hides behind an expected RED is a wiring defect nobody fixes.
#
# Resolution is an ordered walk over a CLOSED tuple of NAMED sources. Each
# terminal state gets its own check name and its own failure code:
#
#   argument          --operation-id was passed                 -> resolved
#   pack_declaration  the pack declares exactly ONE bound op    -> resolved
#   (no candidate)    no source produced one                    -> WF1128 WIRING
#   (>1 candidate)    sources produced several distinct ids     -> WF1129 AMBIGUOUS
#
# WHAT IS DELIBERATELY NOT A SOURCE: the operations directory on disk
# (scene_survey_operation.py MANIFEST_DIR_REL). "Scan it and take the newest" is
# the eight-day-old-artifact defect in a new costume — the gate would once again
# be grading whatever ran last instead of the operation it was ASKED about, and
# it would go green off another operation's evidence. Nothing in this module
# lists, globs or sorts that directory; scene_survey_operation.py exposes no
# enumerator either (every entry point there is id-first). The negative harness
# tools/pipeline/test_negative_scene_survey_operation_resolution.py proves the
# absence behaviourally, by making every directory-enumeration primitive raise
# for the duration of a resolve.

OP_SOURCE_ARGUMENT = "argument"
OP_SOURCE_PACK = "pack_declaration"
#: The complete, ordered set of places an operation id may come from. A source
#: that is not in this tuple is not consulted — that is what makes the resolver
#: auditable rather than "whatever the filesystem happened to contain".
OPERATION_ID_SOURCES = (OP_SOURCE_ARGUMENT, OP_SOURCE_PACK)

OUTCOME_RESOLVED = "resolved"
OUTCOME_WIRING_DEFECT = "wiring_defect"
OUTCOME_AMBIGUOUS = "ambiguous"

#: Keys a pack document would have to carry for a bound operation to be derivable
#: from it. NONE OF THESE EXIST IN ANY PACK IN THIS REPOSITORY TODAY — they are a
#: PROPOSAL, read only from an explicitly-supplied document. See
#: ``pack_operation_candidates`` for what the pack format actually permits.
PACK_OPERATION_KEYS = ("scene_survey_operation_id", "scene_survey_operation_ids")


def _usable_operation_id(value, repo_root=None):
    """Strict validation of a candidate id. Returns the id, or None.

    An id is usable only if it survives ``OP.manifest_path_for`` unchanged. That
    function slugs the id into a directory name, and the slug is LOSSY: two
    different ids can slug to the same directory, at which point the gate would
    read one operation's evidence while believing it read another's. So a
    candidate that had to be rewritten to become filesystem-safe is REFUSED
    rather than quietly normalised. ``confine_path`` inside that call also fails
    an id that would escape the repository (WF1130).
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    res = OP.manifest_path_for(REPO_ROOT if repo_root is None else repo_root, text)
    if not res.ok:
        return None
    if Path(res.value["absolute"]).parent.name != text:
        return None
    return text


def pack_operation_candidates(pack, pack_document=None, repo_root=None):
    """Operation ids the SELECTED PACK declares as bound to it.

    WHAT THE PACK FORMAT ACTUALLY PERMITS TODAY: nothing. This returns ``[]`` for
    every pack that exists, and that is a fact about the repository, not a stub.

      * ``--pack`` in this file is a report LABEL, not a document reference. Its
        value reaches exactly two places — ``ValidationReport("pack", args.pack)``
        and ``build_meta(pack=args.pack)`` in ``main`` — and is never resolved to
        a path, opened, or parsed.
      * The name the shield passes, ``worldforge_vertical_slice``, does not name a
        pack document at all: the pack YAMLs live in ``procedural/world_packs/``
        and ``procedural/slice_packs/`` and there is no file of that name in
        either. It is a SLICE id (``package_slice.py:35``), and the slice package
        report that carries it names ``pack_id="encounter_loop_world"``.
      * No pack schema anywhere in the repository carries an operation field.

    So source #2 of ``OPERATION_ID_SOURCES`` is INERT until a pack schema grows a
    bound-operation field — a change to the pack format, which this module does
    not own. The seam is written out rather than omitted because the ambiguity
    rail must be reachable and testable BEFORE that schema exists; a rail whose
    only possible input is "no candidates" has never been observed rejecting
    anything, and an unobserved rail is not a rail.

    ``pack_document`` is the injection point: an in-memory mapping standing in for
    the pack document a future schema would supply. Passing one exercises the
    real resolution path. Returns ``(candidates, detail)``.
    """
    if pack_document is None:
        return [], ("pack {!r} declares no bound operation: no pack schema in this "
                    "repository carries one, and this gate never loads a pack "
                    "document — --pack is a report label, not a document "
                    "reference".format(pack))
    if not isinstance(pack_document, dict):
        return [], ("pack {!r} supplied a {} where a pack document (mapping) was "
                    "required; refusing to guess at its shape".format(
                        pack, type(pack_document).__name__))
    raw = []
    for key in PACK_OPERATION_KEYS:
        if key not in pack_document:
            continue
        value = pack_document[key]
        raw.extend(list(value) if isinstance(value, (list, tuple)) else [value])
    if not raw:
        return [], ("pack {!r} carries a document but none of the declared "
                    "bound-operation keys {}".format(pack, list(PACK_OPERATION_KEYS)))
    return raw, "pack {!r} declares {} candidate(s)".format(pack, len(raw))


def resolve_operation_id(args, repo_root=None, pack_document=None):
    """Resolve WHICH operation is being graded, from named sources only.

    Never touches the filesystem to discover an operation: the only path call in
    here is ``OP.manifest_path_for``, which FORMS a path from an id it was already
    given and never reads a directory. See ``OPERATION_ID_SOURCES``.

    Returns a dict with ``operation_id`` (str or None), ``source``, ``outcome``
    (one of ``OUTCOME_*``), ``candidates`` and ``detail``.
    """
    repo_root = REPO_ROOT if repo_root is None else Path(repo_root)
    res = {"operation_id": None, "source": None, "outcome": None, "candidates": [],
           "sources_consulted": list(OPERATION_ID_SOURCES),
           "pack": getattr(args, "pack", None), "detail": ""}

    # 1. an explicitly passed --operation-id wins, and nothing else is consulted.
    raw = getattr(args, "operation_id", None)
    if raw is not None and str(raw).strip():
        explicit = _usable_operation_id(raw, repo_root)
        if explicit is None:
            res["outcome"] = OUTCOME_WIRING_DEFECT
            res["detail"] = (
                "--operation-id {!r} was passed but is not a usable operation id "
                "(it is not filesystem-safe as written, or it would escape the "
                "repository). It is refused rather than normalised: the slug is "
                "lossy, so two ids can name one directory".format(raw))
            return res
        res.update(operation_id=explicit, source=OP_SOURCE_ARGUMENT,
                   outcome=OUTCOME_RESOLVED, candidates=[explicit],
                   detail="--operation-id was passed explicitly; source {!r} wins "
                          "and no other source was consulted".format(OP_SOURCE_ARGUMENT))
        return res

    # 2. the pack, IF its contract permits it to declare exactly one bound op.
    if pack_document is None:
        pack_document = getattr(args, "pack_document", None)
    raw_candidates, why = pack_operation_candidates(
        getattr(args, "pack", None), pack_document, repo_root)
    usable, rejected = [], []
    for cand in raw_candidates:
        ok = _usable_operation_id(cand, repo_root)
        if ok is None:
            rejected.append(cand)
        else:
            usable.append(ok)
    distinct = sorted(set(usable))
    res["candidates"] = distinct

    if len(distinct) == 1:
        res.update(operation_id=distinct[0], source=OP_SOURCE_PACK,
                   outcome=OUTCOME_RESOLVED,
                   detail="derived under strict validation from the single bound "
                          "operation the pack declares ({}); rejected as unusable: "
                          "{}".format(why, rejected))
    elif len(distinct) > 1:
        res.update(outcome=OUTCOME_AMBIGUOUS,
                   detail="the pack declares {} distinct bound operations {} — this "
                          "gate refuses to choose".format(len(distinct), distinct))
    else:
        res.update(outcome=OUTCOME_WIRING_DEFECT,
                   detail="{}{}".format(
                       why,
                       "" if not rejected else
                       "; candidate(s) {} were rejected as unusable operation "
                       "ids".format(rejected)))
    return res


def _validate_operation_id_resolution(rep, res):
    """Two mutually-exclusive rails, so the RED says WHICH failure this is.

    Ambiguity and wiring are separate terminal states of ``resolve_operation_id``,
    so at most one of these can fail on any run. Neither is the absent-evidence
    rail: that one lives at the end of ``_select_input`` and only becomes
    reachable once an operation id HAS been resolved.
    """
    outcome = res.get("outcome")
    rep.check("input::operation_id_unambiguous", outcome != OUTCOME_AMBIGUOUS,
              "AMBIGUOUS OPERATION (not a missing argument, and not absent "
              "evidence): more than one candidate operation was offered and this "
              "gate will not pick one. Silently choosing is how a run grades the "
              "wrong operation and reports success about it. Name the one you mean "
              "with --operation-id. {}".format(res.get("detail")),
              code=C.SCENE_SURVEY_CONCURRENT_OPERATION)
    rep.check("input::operation_id_resolved", outcome != OUTCOME_WIRING_DEFECT,
              "WIRING DEFECT (this is NOT the absent-runtime-evidence RED): no "
              "operation id was produced by ANY of the declared sources {}. The "
              "caller did not say what to grade, so nothing was graded — fix the "
              "invocation, not the editor. {}".format(
                  list(OPERATION_ID_SOURCES), res.get("detail")),
              code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)


# --------------------------------------------------------------------------- #
# input selection — WHICH operation is being graded, and is this its artifact?
# --------------------------------------------------------------------------- #
def _select_input(rep, args, now=None, repo_root=None, resolution=None):
    """Resolve the report path for the NAMED operation, fail-closed.

    Returns a context dict. Every failure here is blocking: a gate that cannot say
    which operation it graded has not graded an operation.

    ``repo_root`` is a parameter rather than a module constant so this rail can be
    driven to GREEN over a synthetic tree in ``_dogfood``. A rail that has only ever
    been observed failing is indistinguishable from a rail that always fails.

    ``resolution`` is the output of ``resolve_operation_id``; it is computed here
    when not supplied so every caller — including the dogfood harness — goes
    through the same resolution rails.
    """
    repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT
    if resolution is None:
        resolution = resolve_operation_id(args, repo_root=repo_root)
    _validate_operation_id_resolution(rep, resolution)

    operation_id = resolution.get("operation_id")
    ctx = {"report_path": None, "manifest": None, "manifest_path": None,
           "request": None, "operation_id": operation_id,
           "operation_id_source": resolution.get("source"),
           "resolution": resolution,
           "selection": None, "repo_root": repo_root}

    stated = bool(operation_id)

    # 1. explicit path wins, but is still bound to the stated operation below.
    if args.report:
        ctx["report_path"] = Path(args.report)
        if not ctx["report_path"].is_absolute():
            ctx["report_path"] = repo_root / args.report
        ctx["selection"] = "explicit_path"
    elif stated:
        res = OP.report_path_for(repo_root, operation_id)
        if res.ok:
            ctx["report_path"] = res.value["absolute"]
            ctx["selection"] = "operation_scoped"
        else:
            rep.check("input::operation_report_path", False,
                      "cannot form an operation-scoped report path: {} [{}]".format(
                          res.detail, res.code),
                      code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)
    report_on_disk = ctx["report_path"] is not None and ctx["report_path"].is_file()
    # Kept before the legacy-fallback rewrite below: the absent-evidence rail must
    # name the address the operation's artifact WOULD have, not the shared fixed
    # filename the diagnostic path degrades to.
    ctx["operation_scoped_report_path"] = ctx["report_path"]
    if not report_on_disk:
        # Fall back to the legacy fixed path so the operator still gets a
        # diagnostic, and say plainly that nothing found there is operation-bound.
        fallback = repo_root / LEGACY_RUNTIME_REPORT.relative_to(REPO_ROOT)
        rep.check("input::operation_scoped_artifact", report_on_disk,
                  "no operation-scoped report at {} — falling back to the legacy "
                  "unscoped path {} for diagnosis only; a report at a shared fixed "
                  "filename cannot prove which operation produced it".format(
                      ctx["report_path"], fallback),
                  code=C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING)
        ctx["report_path"] = fallback
        ctx["selection"] = (ctx["selection"] or "legacy_fixed_path") + "+legacy_fallback"
    else:
        rep.check("input::operation_scoped_artifact", True,
                  "graded {}".format(ctx["report_path"]))

    # 2. the operation manifest is the only artifact that binds evidence to a request.
    manifest_on_disk = False
    if stated:
        mres = OP.manifest_path_for(repo_root, operation_id)
        if mres.ok:
            ctx["manifest_path"] = mres.value["absolute"]
            manifest_on_disk = Path(mres.value["absolute"]).is_file()
            lres = OP.load_operation_manifest(ctx["manifest_path"])
            rep.check("identity::manifest_present", bool(lres.ok),
                      "operation manifest for {!r} must exist and carry an intact "
                      "digest ({}): {}".format(operation_id,
                                               mres.value["relative_posix"],
                                               "" if lres.ok else lres.detail),
                      code=C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING)
            if lres.ok:
                ctx["manifest"] = lres.value
    else:
        rep.check("identity::manifest_present", False,
                  "no operation stated, so no manifest can be located",
                  code=C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING)

    # 3. the request. Without it there is no hash to bind the evidence to.
    if args.request:
        rpath = Path(args.request)
        if not rpath.is_absolute():
            rpath = repo_root / args.request
        try:
            ctx["request"] = json.loads(rpath.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            rep.check("identity::request_loadable", False,
                      "--request {} is unreadable/unparseable: {}".format(rpath, exc),
                      code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)

    have_pair = isinstance(ctx["manifest"], dict) and isinstance(ctx["request"], dict)
    if have_pair:
        vres = OP.verify_operation_evidence(
            repo_root, ctx["manifest"], ctx["request"],
            max_age_seconds=args.max_age_seconds, now=now, check_files=True)
        rep.check("identity::request_hash_bound", bool(vres.ok),
                  "the manifest must bind this evidence to THIS request by hash, "
                  "with every referenced artifact re-digested: {} [{}/{}]".format(
                      vres.detail, vres.code, vres.reason),
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)
    else:
        rep.check("identity::request_hash_bound", False,
                  "cannot bind evidence to a request: manifest={} request={} — "
                  "pass --operation-id and --request. An unbound report answers a "
                  "question nobody can reconstruct".format(
                      isinstance(ctx["manifest"], dict), isinstance(ctx["request"], dict)),
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)

    # 4. THE INTENTIONAL RED. Everything above can fail for reasons that are the
    # CALLER'S fault (wrong id, tampered request, drifted hash). This rail fails
    # for the one reason that is nobody's fault yet: the gate knows exactly which
    # operation it would grade, formed both of that operation's addresses, and
    # neither address has anything at it — no live survey has ever run. That is
    # the honest RED this module was built to hold, and it must never be confused
    # with the wiring RED above, which is repaired by editing a command line.
    if not stated:
        rep.skip("input::caller_evidence_present",
                 "not evaluated: no operation id was resolved, so there is no "
                 "address to look for caller evidence at. The blocking failure on "
                 "this run is input::operation_id_resolved / "
                 "input::operation_id_unambiguous, NOT absent evidence",
                 code=C.SCENE_SURVEY_EVIDENCE_MISSING)
    else:
        rep.check("input::caller_evidence_present",
                  bool(report_on_disk and manifest_on_disk),
                  "ABSENT CALLER EVIDENCE — the intentional RED. Operation {!r} is "
                  "named and unambiguous (source={}), so this gate knows precisely "
                  "what it would grade; nothing has produced it. report={} "
                  "present={} | manifest={} present={}. This is NOT a wiring "
                  "defect and NOT ambiguity: it is repaired by running "
                  "run_scene_survey_probe.py against a target, not by changing "
                  "this invocation".format(
                      operation_id, ctx.get("operation_id_source"),
                      ctx.get("operation_scoped_report_path"), bool(report_on_disk),
                      ctx.get("manifest_path"), bool(manifest_on_disk)),
                  code=C.SCENE_SURVEY_EVIDENCE_MISSING)
    return ctx


def _validate_freshness(rep, ctx, args, now=None):
    """The artifact must not predate the code that produces it, or the caller's window."""
    now = time.time() if now is None else now
    path = ctx.get("report_path")
    exists = isinstance(path, Path) and path.is_file()
    if not exists:
        rep.check("freshness::artifact_present", False,
                  "no runtime survey report at {} — run run_scene_survey_probe.py "
                  "against a target first (fail-closed until a live survey runs)".format(
                      path), code=C.SCENE_SURVEY_EVIDENCE_MISSING)
        return
    rep.check("freshness::artifact_present", True, str(path))

    mtime = path.stat().st_mtime
    newer = []
    for producer in PRODUCER_FILES:
        if producer.is_file() and producer.stat().st_mtime > mtime:
            newer.append("{} (+{:.1f}h)".format(
                producer.relative_to(REPO_ROOT).as_posix(),
                (producer.stat().st_mtime - mtime) / 3600.0))
    rep.check("freshness::not_older_than_producers", not newer,
              "the report predates the code that produces it, so it cannot be "
              "evidence about that code — re-run the probe. Newer: {}".format(newer),
              code=C.SCENE_SURVEY_STALE_EVIDENCE)

    if args.max_age_seconds is not None:
        age = now - mtime
        rep.check("freshness::within_max_age", age <= args.max_age_seconds,
                  "report is {:.1f}h old; --max-age-seconds is {} ({:.1f}h)".format(
                      age / 3600.0, args.max_age_seconds,
                      args.max_age_seconds / 3600.0),
                  code=C.SCENE_SURVEY_STALE_EVIDENCE)


def _validate_declared_freshness(rep, obj, args, now=None):
    """Freshness from the artifact's OWN declared build time, not just its mtime.

    An mtime rail alone is launderable: rewriting a stale artifact with identical
    bytes — or a bare ``touch`` — makes it look current. This was observed live
    during this change: the report at the legacy path was rewritten byte-for-byte
    with a new mtime while its declared ``meta.timestamp`` stayed on 2026-07-19.

    The report's own timestamp is self-attested, which is fine in THIS direction:
    nobody forges an artifact to look older than it is. So both clocks must be
    fresh, and the OLDER of the two governs. ``survey.created_at`` is deliberately
    NOT used — ``run_scene_survey_probe.py:343`` sets it to the frozen constant
    ``SS.AUTHORING_TS``, so it is an authoring marker, not a build time.
    """
    now = time.time() if now is None else now
    meta = (obj or {}).get("meta") or {}
    declared = RC.parse_iso_epoch(meta.get("timestamp"))

    rep.check("freshness::declared_timestamp_present", declared is not None,
              "the envelope's meta.timestamp must be a parseable ISO-8601 instant "
              "(got {!r}) — without it, file mtime is the only clock and mtime is "
              "launderable by a rewrite".format(meta.get("timestamp")),
              code=C.SCENE_SURVEY_STALE_EVIDENCE)
    if declared is None:
        return

    if args.max_age_seconds is not None:
        age = now - declared
        rep.check("freshness::declared_within_max_age", age <= args.max_age_seconds,
                  "the report DECLARES it was built {:.1f}h ago (meta.timestamp={}); "
                  "--max-age-seconds is {:.1f}h. Touching the file does not move this "
                  "clock".format(age / 3600.0, meta.get("timestamp"),
                                 args.max_age_seconds / 3600.0),
                  code=C.SCENE_SURVEY_STALE_EVIDENCE)

    stale_vs = []
    for producer in PRODUCER_FILES:
        if producer.is_file() and producer.stat().st_mtime > declared:
            stale_vs.append("{} (+{:.1f}h)".format(
                producer.relative_to(REPO_ROOT).as_posix(),
                (producer.stat().st_mtime - declared) / 3600.0))
    rep.check("freshness::declared_after_producers", not stale_vs,
              "the report declares a build time earlier than the code that produces "
              "it — re-run the probe, do not re-save the artifact. Newer: {}".format(
                  stale_vs), code=C.SCENE_SURVEY_STALE_EVIDENCE)

    head = git_sha()
    claimed_sha = meta.get("git_sha")
    rep.check("freshness::git_sha_matches_head",
              bool(claimed_sha) and claimed_sha == head,
              "the report was produced at git_sha={!r} but HEAD is {!r} — it is "
              "evidence about a different revision of this repository".format(
                  claimed_sha, head),
              warn_only=True, code=C.SCENE_SURVEY_STALE_EVIDENCE)


# --------------------------------------------------------------------------- #
# envelope shape — a malformed wrapper must be distinguishable from a bare report
# --------------------------------------------------------------------------- #
def _load_envelope(rep, path, tag="live"):
    """Parse the envelope with duplicate-key and non-finite detection.

    Returns ``(obj, survey, subject)`` where any element may be None.

    The previous ``survey = obj.get("survey", obj)`` silently fell back to the whole
    object, so an envelope missing its "survey" block was indistinguishable from a
    bare SceneSurveyReport — and the bare-report reading would then be validated as
    though the wrapper had been checked. The shape is now DECLARED, not guessed.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        rep.check("envelope::{}::readable".format(tag), False,
                  "runtime report unreadable: {}".format(exc),
                  code=C.SCENE_SURVEY_EVIDENCE_MISSING)
        return None, None, None
    try:
        obj, duplicates = RC.parse_json_no_duplicates(text)
    except ValueError as exc:
        rep.check("envelope::{}::parseable".format(tag), False,
                  "runtime report is not valid JSON: {}".format(exc),
                  code=C.SCENE_SURVEY_REPORT_INVALID)
        return None, None, None
    rep.check("envelope::{}::parseable".format(tag), True, "parsed")

    rep.check("envelope::{}::no_duplicate_record_ids".format(tag), not duplicates,
              "duplicate object key(s) {} — json.loads keeps the LAST value, so a "
              "document can ship two answers and have every reader pick the "
              "convenient one".format(duplicates),
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)

    nonfinite = RC.nonfinite_numerics(obj)
    rep.check("envelope::{}::finite_numerics".format(tag), not nonfinite,
              "non-finite number(s) at {} — NaN/Infinity compare False against "
              "everything, including themselves".format(nonfinite[:6]),
              code=C.SCENE_SURVEY_REPORT_INVALID)

    is_obj = isinstance(obj, dict)
    rep.check("envelope::{}::is_object".format(tag), is_obj,
              "the runtime envelope must be a JSON object (got {})".format(
                  type(obj).__name__), code=C.SCENE_SURVEY_REPORT_INVALID)
    if not is_obj:
        return None, None, None

    has_survey = isinstance(obj.get("survey"), dict)
    looks_bare = "report_id" in obj and "schema_version" in obj and "survey" not in obj
    rep.check("envelope::{}::survey_declared".format(tag), has_survey,
              "the envelope must declare its SceneSurveyReport under 'survey'. "
              "{} — a wrapper is NOT inferred from a bare report, because then a "
              "malformed envelope and a bare report are the same input".format(
                  "this looks like a bare SceneSurveyReport" if looks_bare
                  else "no 'survey' object present"),
              code=C.SCENE_SURVEY_REPORT_INVALID)

    has_subject = isinstance(obj.get("subject"), dict) and bool(obj.get("subject"))
    rep.check("envelope::{}::subject_declared".format(tag), has_subject,
              "the envelope must carry the caller-resolved SceneSurveySubject under "
              "'subject' (run_scene_survey_probe.py must emit it)",
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)

    return obj, (obj.get("survey") if has_survey else None), \
        (obj.get("subject") if has_subject else None)


def _validate_operation_identity(rep, ctx, survey, tag="live"):
    """The artifact's own operation_id must be the one the caller named."""
    want = ctx.get("operation_id")
    if not want:
        return
    got = (survey or {}).get("operation_id")
    rep.check("identity::{}::report_operation_id".format(tag), got == want,
              "the report declares operation_id={!r} but this gate was asked to "
              "grade {!r}".format(got, want),
              code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)
    manifest = ctx.get("manifest")
    if isinstance(manifest, dict):
        rep.check("identity::{}::manifest_operation_id".format(tag),
                  manifest.get("operation_id") == want,
                  "the manifest declares operation_id={!r}, not {!r}".format(
                      manifest.get("operation_id"), want),
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)


# --------------------------------------------------------------------------- #
# the original runtime-truth rails (unchanged in substance)
# --------------------------------------------------------------------------- #
def _validate_runtime_obj(rep, obj, tag):
    """Apply the runtime-truth rails to a survey report object."""
    obj = obj if isinstance(obj, dict) else {}
    fails = [c for c in SS.validate_scene_survey_report(obj, strict=True) if not c[1]]
    rep.check("runtime::{}::contract_valid".format(tag), len(fails) == 0,
              "runtime report must satisfy the SceneSurveyReport contract: {}".format(
                  [c[0] for c in fails][:4]),
              code=C.SCENE_SURVEY_REPORT_INVALID)
    rep.check("runtime::{}::executed".format(tag), obj.get("runtime_executed") is True,
              "runtime_executed must be True — a report with no real editor run is not "
              "runtime truth", code=C.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM)


def _validate_runtime_binding(rep, subject, report, tag):
    """The runtime report must bind to the subject the CALLER handed over."""
    present = isinstance(subject, dict) and bool(subject)
    rep.check("runtime::{}::subject_present".format(tag), present,
              "the runtime envelope must carry the caller-resolved SceneSurveySubject "
              "under 'subject' — a report that cannot be bound to a request is "
              "unfalsifiable (run_scene_survey_probe.py must emit it)",
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)
    if not present:
        return
    sfails = [c for c in SS.validate_scene_survey_subject(subject, strict=True) if not c[1]]
    rep.check("runtime::{}::subject_valid".format(tag), len(sfails) == 0,
              "the handed-over subject must satisfy the SceneSurveySubject contract: "
              "{}".format([c[0] for c in sfails][:4]),
              code=C.SCENE_SURVEY_SUBJECT_UNRESOLVED)
    bfails = [c for c in SS.validate_subject_binding(subject, report or {}, strict=True)
              if not c[1]]
    rep.check("runtime::{}::binds_to_subject".format(tag), len(bfails) == 0,
              "the survey did not bind to the subject it was handed: {}".format(
                  [(c[0], c[2]) for c in bfails][:3]),
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)
    rep.check("runtime::{}::resolved_by_caller".format(tag),
              subject.get("resolved_by") == "caller"
              and (report or {}).get("subject_resolved_by") == "caller",
              "both sides must declare resolved_by='caller' — WorldForge must never "
              "resolve the survey subject itself (subject={!r}, report={!r})".format(
                  subject.get("resolved_by"), (report or {}).get("subject_resolved_by")),
              code=C.SCENE_SURVEY_SUBJECT_INFERRED)


# --------------------------------------------------------------------------- #
# provenance — a request-derived field labelled `observed` is a forgery
# --------------------------------------------------------------------------- #
def _validate_provenance(rep, obj, survey, tag="live"):
    """subject_id / subject_resolved_by are caller vocabulary. Always.

    WorldForge has no channel that could observe either — the assembler says so in
    its own comment (run_scene_survey_probe.py:311-316) and the evidence model
    classifies both CALLER_SUPPLIED (scene_survey_evidence.py:517-522). A record
    presenting one as `observed` is not making a stronger claim; it is making an
    impossible one, and it is the exact shape that would let a report satisfy the
    subject rails with no caller involved at all.
    """
    forged = []
    for container in (obj, survey, (obj or {}).get("evidence"),
                      (survey or {}).get("evidence"), (survey or {}).get("fields")):
        forged.extend(RC.forged_provenance(container))
    rep.check("provenance::{}::request_fields_not_observed".format(tag), not forged,
              "forged provenance on request-derived field(s): {} — {} are "
              "caller_supplied by nature".format(sorted(set(forged))[:4],
                                                 list(RC.REQUEST_DERIVED_FIELDS)),
              code=C.SCENE_SURVEY_SUBJECT_INFERRED)


# --------------------------------------------------------------------------- #
# raw evidence — the only input this gate is willing to derive from
# --------------------------------------------------------------------------- #
def _collect_raw(rep, ctx, obj, survey, tag="live"):
    """Load the far-side raw evidence bundles for THIS operation.

    Preference order, and why:
      1. manifest ``raw_evidence`` records with role ``far_side_run`` — the only
         source that is operation-bound AND digest-verified.
      2. the envelope's own ``raw_evidence`` block, if the probe inlined it.
      3. the report's ``evidence_paths`` — self-attested, so it is accepted only as
         a diagnostic and flagged, never as a binding source.
    Returns ``(bundles, source)`` where bundles is an ordered list of
    ``(label, raw_bundle, doc)``.
    """
    bundles, source = [], None
    manifest = ctx.get("manifest")
    candidates = []

    if isinstance(manifest, dict):
        for record in manifest.get("raw_evidence") or []:
            if isinstance(record, dict) and record.get("role") == "far_side_run":
                candidates.append(record.get("path"))
        if candidates:
            source = "manifest"

    if not candidates and isinstance(obj, dict) and isinstance(obj.get("raw_evidence"), dict):
        bundles.append(("envelope", obj["raw_evidence"], obj))
        source = "envelope_inline"

    if not candidates and not bundles:
        for rel in (survey or {}).get("evidence_paths") or []:
            candidates.append(rel)
        if candidates:
            source = "report_self_attested"

    for rel in candidates:
        path = Path(ctx.get("repo_root") or REPO_ROOT) / str(rel)
        if not path.is_file():
            rep.check("raw::{}::artifact_{}".format(tag, rel), False,
                      "declared raw evidence artifact is absent: {}".format(rel),
                      code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
            continue
        try:
            doc, dups = RC.parse_json_no_duplicates(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            rep.check("raw::{}::artifact_{}".format(tag, rel), False,
                      "raw evidence artifact is unreadable/unparseable: {}".format(exc),
                      code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
            continue
        if dups:
            rep.check("raw::{}::no_duplicate_ids_{}".format(tag, rel), False,
                      "duplicate record id(s) {} in {}".format(dups, rel),
                      code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
        bundle = doc.get("raw_evidence") if isinstance(doc, dict) else None
        if not isinstance(bundle, dict):
            rep.check("raw::{}::bundle_{}".format(tag, rel), False,
                      "{} carries no 'raw_evidence' bundle — the far side must emit "
                      "the raw atoms, not just its own conclusions".format(rel),
                      code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
            continue
        bundles.append((str(rel), bundle, doc))

    rep.check("raw::{}::bundle_present".format(tag), bool(bundles),
              "no raw evidence bundle could be loaded (source={}) — every derived "
              "value below is therefore unverifiable, and an unverifiable derived "
              "value is not evidence".format(source),
              code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
    rep.check("raw::{}::bundle_operation_bound".format(tag), source == "manifest",
              "raw evidence was taken from {!r}; only manifest-bound far_side_run "
              "records are tied to this operation and digest-verified".format(source),
              code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)

    # Cross-operation refs: every run doc must name THIS operation.
    want = ctx.get("operation_id") or (survey or {}).get("operation_id")
    crossing = [label for label, _b, doc in bundles
                if want and isinstance(doc, dict)
                and doc.get("operation_id") not in (None, want)]
    if bundles:
        rep.check("raw::{}::no_cross_operation_refs".format(tag), not crossing,
                  "raw evidence artifact(s) {} declare a different operation_id than "
                  "{!r} — evidence that crosses operations binds two runs together "
                  "with nobody noticing".format(crossing, want),
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)
        dangling = []
        for label, bundle, _doc in bundles:
            dangling.extend("{}: {}".format(label, d) for d in RC.dangling_refs(bundle))
        rep.check("raw::{}::refs_resolve".format(tag), not dangling,
                  "raw evidence references record(s) that are not present: {}".format(
                      dangling[:5]),
                  code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
    return bundles, source


def _validate_determinism(rep, survey, bundles, tag="live"):
    """Determinism, RECOMPUTED — never read from the report's own meta.

    The previous rail read ``meta.per_run_hashes`` and ``meta.determinism_consistent``
    straight out of the report being validated: the report attested to its own
    determinism and the gate agreed with it. Here the per-run artifacts are hashed
    independently and compared to each other; the report's claim is then checked
    AGAINST that result, and a report claiming more runs than there are artifacts is
    a hard failure rather than a larger number.
    """
    meta = (survey or {}).get("meta") or {}
    claimed_hashes = meta.get("per_run_hashes") or []
    claimed_consistent = meta.get("determinism_consistent")

    rep.check("determinism::{}::runs_available".format(tag), len(bundles) >= 1,
              "determinism needs at least one per-run artifact to hash; found {}"
              .format(len(bundles)), code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
    if not bundles:
        return

    digests = []
    for label, bundle, _doc in bundles:
        res = OP.canonical_json(bundle)
        if not res.ok:
            rep.check("determinism::{}::hashable_{}".format(tag, label), False,
                      "raw bundle is not canonicalizable: {}".format(res.detail),
                      code=C.SCENE_SURVEY_REPORT_INVALID)
            return
        digests.append(OP.digest_bytes(res.value.encode("utf-8")))

    rep.check("determinism::{}::runs_identical".format(tag), len(set(digests)) == 1,
              "the per-run raw bundles are not byte-identical after canonicalisation "
              "— recomputed digests {}".format([d[:19] for d in digests]),
              code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)

    rep.check("determinism::{}::claim_count_matches".format(tag),
              len(claimed_hashes) == len(digests),
              "the report claims {} per-run hash(es) but {} per-run artifact(s) were "
              "found and hashed here — a claim about runs whose evidence is absent "
              "is not a determinism proof".format(len(claimed_hashes), len(digests)),
              code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)

    # Carried over verbatim from the rail this function replaces, so the rewrite
    # cannot be a weakening: the report's OWN claimed hashes must also agree with
    # each other. Recomputation subsumes this in the honest case, but a report can
    # claim mutually-different hashes alongside determinism_consistent=True, and
    # dropping this conjunct would have stopped catching that.
    rep.check("determinism::{}::claimed_hashes_agree".format(tag),
              len(set(claimed_hashes)) <= 1,
              "the report's own per_run_hashes disagree with each other while it "
              "claims determinism_consistent={!r} (per_run_hashes={})".format(
                  claimed_consistent, claimed_hashes),
              code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)

    recomputed_consistent = len(set(digests)) == 1
    rep.check("determinism::{}::claim_matches_recomputation".format(tag),
              (claimed_consistent is True) == recomputed_consistent,
              "the report claims determinism_consistent={!r} but independent "
              "re-hashing of its run artifacts says {!r}".format(
                  claimed_consistent, recomputed_consistent),
              code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)


def _validate_recompute(rep, subject, survey, bundles, args, tag="live",
                        operation_id=None):
    """r_reported = f(E_raw), for every aggregate the report presents as decided."""
    if not bundles:
        rep.check("recompute::{}::possible".format(tag), False,
                  "no raw evidence bundle: not one reported aggregate can be "
                  "re-derived, so none of them is accepted",
                  code=C.SCENE_SURVEY_EVIDENCE_INSUFFICIENT)
        return
    rep.check("recompute::{}::possible".format(tag), True,
              "{} bundle(s)".format(len(bundles)))

    # The report folds the LAST run (run_scene_survey_probe.py:260 `last = runs[-1]`),
    # so that is the bundle its aggregates must follow from.
    label, bundle, _doc = bundles[-1]
    requested_map = (subject or {}).get("map_asset_path")
    recomputed = RC.recompute_all(
        bundle, requested_map=requested_map,
        subject=subject, report=survey, operation_id=operation_id,
        tau_anchor_transform_cm=args.tau_anchor_transform_cm,
        tau_supported=args.tau_supported_fraction,
        tau_z_cm=args.tau_ground_dz_cm,
        theta_max_deg=args.theta_max_deg)

    rep.check("recompute::{}::no_contradictory_atoms".format(tag),
              not recomputed["_contradictions"],
              "a raw record restates an observation its own atoms contradict: {} "
              "(source {})".format(recomputed["_contradictions"][:4], label),
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)

    mismatches, invented = RC.compare(survey or {}, recomputed)
    rep.check("recompute::{}::aggregates_follow_from_raw".format(tag), not mismatches,
              "the report does not follow from its own evidence: {}".format(
                  mismatches[:4]),
              code=C.SCENE_SURVEY_EVIDENCE_REDERIVATION_MISMATCH)
    rep.check("recompute::{}::no_unknown_presented_as_decided".format(tag), not invented,
              "the report presents a decided value where the raw evidence cannot "
              "decide one: {}".format(invented[:4]),
              code=C.SCENE_SURVEY_EVIDENCE_INSUFFICIENT)

    world = recomputed["world_identity_ok"]
    rep.check("recompute::{}::world_identity_ok".format(tag),
              world.get("sufficient") and world.get("verdict") is True,
              "the world the editor actually opened must be the world the caller "
              "requested, measured from raw: {}".format(world.get("detail")),
              code=C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)

    bounds = recomputed["actor_bounds_valid"]
    rep.check("recompute::{}::actor_bounds_from_bounds".format(tag),
              bounds.get("sufficient") and bounds.get("verdict") is True,
              "actor bounds validity must be decided from per-actor bounds extents, "
              "never from an actor count: {}".format(bounds.get("detail")),
              code=C.SCENE_SURVEY_ACTOR_BOUNDS_MISSING)

    cleanup = recomputed["cleanup_verified"]
    rep.check("recompute::{}::cleanup_from_inventories".format(tag),
              cleanup.get("sufficient") and cleanup.get("verdict") is True,
              "cleanup must be verified by comparing the pre and post inventories "
              "(actors, dirty packages AND operation-owned actors): {}".format(
                  cleanup.get("detail") or cleanup),
              code=C.SCENE_SURVEY_CLEANUP_UNVERIFIED)

    # ---- ACCEPTANCE ELIGIBILITY, re-derived from raw ------------------------- #
    # This gate used to reach eligibility ONLY through SS.validate_subject_binding
    # (:415), which calls scene_survey_contracts.evaluate_acceptance_eligibility —
    # the same predicate run_scene_survey_probe.py:795 used to WRITE the claim.
    # Producer and checker agreed by construction. The three rails below read
    # RC.acceptance_eligibility, which never touches that predicate and derives its
    # six terms from raw["world"], raw["actor"] and raw["marker"] instead.
    #
    # NOT a "must be True" rail, unlike world identity / bounds / cleanup above: an
    # explicit_transform survey is legitimately valid AND legitimately ineligible
    # (scene_survey_contracts.py:1002-1004). What is required is AGREEMENT — in
    # BOTH directions. A report claiming eligible over raw that denies it is an
    # over-claim; a report claiming ineligible over raw that supports it is a
    # report that still does not follow from its own evidence, and it is the
    # direction scene_survey_contracts.py:1144-1153 explicitly left uninstalled.
    acc = recomputed["acceptance_eligible"]
    claimed = RC.claimed_value(survey or {}, "acceptance_eligible")
    decided = acc.get("sufficient") and RC.is_decided(acc.get("verdict"))
    rep.check("recompute::{}::acceptance_claim_matches_raw".format(tag),
              bool(decided) and claimed is acc.get("verdict"),
              "the report's acceptance_eligible claim must equal the value the RAW "
              "atoms re-derive, in both directions: report states {!r}, raw "
              "re-derives {!r} ({})".format(
                  "<absent>" if claimed is RC._NO_CLAIM else claimed,
                  acc.get("verdict"), acc.get("detail")),
              code=C.SCENE_SURVEY_EVIDENCE_UNSUPPORTED_CLAIM)

    comp_mis, comp_inv = RC.compare(survey or {}, recomputed,
                                    RC.ACCEPTANCE_COMPONENT_FIELDS)
    rep.check("recompute::{}::acceptance_components_follow_from_raw".format(tag),
              not comp_mis and not comp_inv,
              "a stated acceptance component does not follow from the raw atoms: "
              "mismatch={} invented={}".format(comp_mis[:3], comp_inv[:3]),
              code=C.SCENE_SURVEY_EVIDENCE_REDERIVATION_MISMATCH)

    # E is the one term with no counterpart in the shared predicate, so nothing
    # else can red on it. A False here means the raw itself is incomplete, split
    # across operations, non-finite or self-contradictory — in which case every
    # other term above was computed over evidence that should not have been read.
    # UNKNOWN is permitted: it propagates into the verdict above and reds any
    # decided claim there, which is where that failure belongs.
    ev = recomputed["acceptance_raw_observations_complete"]
    rep.check("recompute::{}::acceptance_evidence_not_contradicted".format(tag),
              ev.get("verdict") is not False,
              "the raw evidence acceptance stands on is itself broken: {} — {}"
              .format(ev.get("detail"), ev.get("conjuncts")),
              code=C.SCENE_SURVEY_EVIDENCE_INSUFFICIENT)


# --------------------------------------------------------------------------- #
# dogfood — every rail gets a negative, and every negative runs the REAL rail
# --------------------------------------------------------------------------- #
def _ran(fn, *a, **kw):
    """Run a production rail into a throwaway report; return its failure names.

    This is the whole point of the helper: a dogfood check that re-evaluates a
    literal it just built (``rep.check("not_executed_rejected",
    (t1.get("runtime_executed") is True) is False, ...)``) proves that Python
    compares booleans correctly, not that the RAIL rejects the input. The old
    ``dogfood::not_executed_rejected`` was exactly that tautology. Everything below
    invokes the shipped function and reads what it actually failed.
    """
    probe = ValidationReport("suite", "dogfood", strict=True)
    fn(probe, *a, **kw)
    return {name for name, c in probe.checks.items() if not c["ok"]}


def _ran_blocking(fn, *a, **kw):
    """As ``_ran``, but only the checks that actually turn the gate RED.

    ``_ran`` reports every non-PASS check, and ``ValidationReport.skip`` records
    SKIP_NOT_APPLICABLE with ``ok=False``. That is the right reading for the
    tamper negatives, but it is the WRONG reading for the three-way RED
    distinguishability rails: a deliberately skipped rail would look like a
    failure and every "and the other two did not fire" clause would be vacuous.
    """
    probe = ValidationReport("suite", "dogfood", strict=True)
    fn(probe, *a, **kw)
    return {name for name, c in probe.checks.items() if c.get("blocking")}


class _Args(object):
    """Minimal argparse stand-in for driving the production rails in dogfood."""

    def __init__(self, **kw):
        self.operation_id = kw.get("operation_id")
        self.pack = kw.get("pack", "dogfood_pack")
        self.pack_document = kw.get("pack_document")
        self.report = kw.get("report")
        self.request = kw.get("request")
        self.max_age_seconds = kw.get("max_age_seconds", DEFAULT_MAX_AGE_SECONDS)
        self.tau_supported_fraction = kw.get("tau_supported_fraction",
                                             RC.TAU_SUPPORTED_FRACTION)
        self.tau_ground_dz_cm = kw.get("tau_ground_dz_cm", RC.TAU_GROUND_DZ_CM)
        self.theta_max_deg = kw.get("theta_max_deg", RC.THETA_MAX_DEG)
        self.tau_anchor_transform_cm = kw.get("tau_anchor_transform_cm",
                                              RC.TAU_ANCHOR_TRANSFORM_CM)


def _dogfood(rep):
    """Prove every rail rejects a tampered input (the gate cannot fake-green)."""
    clean = SS._example_scene_survey_report()
    subject = SS._example_scene_survey_subject()
    cfails = [c for c in SS.validate_scene_survey_report(clean, strict=True) if not c[1]]
    rep.check("dogfood::clean_report_valid", len(cfails) == 0,
              "synthetic clean report must validate: {}".format([c[0] for c in cfails][:4]),
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)

    # ---- contract rails: run the REAL rail, read what it failed ------------- #
    rep.check("dogfood::clean_passes_runtime_obj",
              not _ran(_validate_runtime_obj, clean, "df"),
              "the runtime rails must accept a clean report, or every negative "
              "below is meaningless: {}".format(_ran(_validate_runtime_obj, clean, "df")),
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::not_executed_rejected",
              "runtime::df::executed" in _ran(
                  _validate_runtime_obj, dict(clean, runtime_executed=False), "df"),
              "the executed RAIL must reject runtime_executed=False (this invokes "
              "the shipped rail; it does not re-test a literal)",
              code=C.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM)
    rep.check("dogfood::valid_gt_total_rejected",
              "runtime::df::contract_valid" in _ran(
                  _validate_runtime_obj, dict(clean, support_samples_valid=99999), "df"),
              "valid>total must be rejected by the contract rail",
              code=C.SCENE_SURVEY_REPORT_INVALID)
    rep.check("dogfood::self_resolved_rejected",
              C.SCENE_SURVEY_SUBJECT_INFERRED in {
                  c[3] for c in SS.validate_scene_survey_report(
                      dict(clean, subject_resolved_by="worldforge"), strict=True)
                  if not c[1]},
              "a report claiming WorldForge resolved the subject must be rejected",
              code=C.SCENE_SURVEY_SUBJECT_INFERRED)
    rep.check("dogfood::no_observed_anchor_rejected",
              C.SCENE_SURVEY_SUBJECT_UNRESOLVED in {
                  c[3] for c in SS.validate_scene_survey_report(
                      dict(clean, observed_anchor_location=None), strict=True)
                  if not c[1]},
              "an executed run with no observed anchor must be rejected",
              code=C.SCENE_SURVEY_SUBJECT_UNRESOLVED)

    # ---- binding rails ------------------------------------------------------ #
    rep.check("dogfood::bound_subject_accepted",
              not _ran(_validate_runtime_binding, subject, clean, "df"),
              "the binding rail must pass a genuinely matched pair (got {})".format(
                  _ran(_validate_runtime_binding, subject, clean, "df")),
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::absent_subject_rejected",
              "runtime::df::subject_present" in _ran(
                  _validate_runtime_binding, None, clean, "df"),
              "an envelope with no 'subject' block must FAIL the binding rail",
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)
    for label, over, rail in (
            ("wrong_subject_id", {"subject_id": "subject_fixture_beta"},
             "runtime::df::binds_to_subject"),
            ("wrong_map", {"map_asset_path": "/Game/Fixture/Lvl_Other"},
             "runtime::df::binds_to_subject"),
            ("anchor_drift", {"observed_anchor_location": [1200.0, -450.0, 97.5]},
             "runtime::df::binds_to_subject"),
            ("self_resolved", {"subject_resolved_by": "worldforge"},
             "runtime::df::resolved_by_caller")):
        rep.check("dogfood::binding_{}_rejected".format(label),
                  rail in _ran(_validate_runtime_binding, subject,
                               dict(clean, **over), "df"),
                  "an unbound survey must fail {} (got {})".format(
                      rail, _ran(_validate_runtime_binding, subject,
                                 dict(clean, **over), "df")),
                  code=C.SCENE_SURVEY_SUBJECT_MISMATCH)

    # ---- envelope shape ----------------------------------------------------- #
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="wf_scene_survey_dogfood_"))
    try:
        good_env = {"status": "ok", "checks": [], "subject": subject, "survey": clean}

        def _write(name, text):
            p = tmp / name
            p.write_text(text, encoding="utf-8")
            return p

        p_ok = _write("ok.json", json.dumps(good_env))
        rep.check("dogfood::envelope_clean_accepted",
                  not _ran(_load_envelope, p_ok, "df"),
                  "a well-formed envelope must pass every shape rail: {}".format(
                      _ran(_load_envelope, p_ok, "df")),
                  code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
        # NEGATIVE: a BARE report must not be silently promoted to an envelope.
        p_bare = _write("bare.json", json.dumps(clean))
        rep.check("dogfood::bare_report_not_promoted",
                  "envelope::df::survey_declared" in _ran(_load_envelope, p_bare, "df"),
                  "a bare SceneSurveyReport must FAIL the envelope rail — the old "
                  "`obj.get('survey', obj)` fallback made it indistinguishable from "
                  "a malformed wrapper",
                  code=C.SCENE_SURVEY_REPORT_INVALID)
        # NEGATIVE: duplicate keys.
        p_dup = _write("dup.json", '{"subject": {}, "survey": {}, "survey": {}}')
        rep.check("dogfood::duplicate_keys_rejected",
                  "envelope::df::no_duplicate_record_ids" in _ran(
                      _load_envelope, p_dup, "df"),
                  "a duplicated object key must be caught at parse time",
                  code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
        # NEGATIVE: non-finite numerics.
        p_nan = _write("nan.json", '{"subject": {}, "survey": {"x": NaN}}')
        rep.check("dogfood::nonfinite_rejected",
                  "envelope::df::finite_numerics" in _ran(_load_envelope, p_nan, "df"),
                  "NaN/Infinity must be rejected, not parsed and compared",
                  code=C.SCENE_SURVEY_REPORT_INVALID)
        # NEGATIVE: unparseable.
        p_bad = _write("bad.json", "{not json")
        rep.check("dogfood::unparseable_rejected",
                  "envelope::df::parseable" in _ran(_load_envelope, p_bad, "df"),
                  "an unparseable report must fail, never be skipped",
                  code=C.SCENE_SURVEY_REPORT_INVALID)
        # NEGATIVE: absent file.
        rep.check("dogfood::absent_report_rejected",
                  "envelope::df::readable" in _ran(
                      _load_envelope, tmp / "nope.json", "df"),
                  "an absent report must fail the readable rail",
                  code=C.SCENE_SURVEY_EVIDENCE_MISSING)

        # ---- input selection / freshness ---------------------------------- #
        # POSITIVE CONTROL for the whole selection/identity chain. Without this, a
        # rail that has only ever been observed failing is indistinguishable from a
        # rail that fails unconditionally, and "the gate is honestly RED" would be
        # an unfalsifiable claim.
        root = tmp / "repo"
        run_dir = root / "procedural" / "reports" / "scene_survey" / "runtime"
        run_dir.mkdir(parents=True, exist_ok=True)
        op_id = "op_dogfood_positive_0001"
        raw_ok0 = RC._clean_bundle()
        (run_dir / "far_side_run1.json").write_text(
            json.dumps({"operation_id": op_id, "raw_evidence": raw_ok0}),
            encoding="utf-8")
        env_res = OP.report_path_for(root, op_id)
        env_path = env_res.value["absolute"]
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(json.dumps(
            {"status": "ok", "checks": [], "subject": subject,
             "survey": dict(clean, operation_id=op_id)}), encoding="utf-8")
        req = {"operation_id": op_id, "output_location": "procedural/reports/x",
               "timeout_seconds": 900, "requested_operation": "scene_survey",
               "subject": subject, "target_map": subject["map_asset_path"],
               "target_project": "T.uproject", "target_repository": "t",
               "target_commit": "c", "target_engine": "5.8",
               "source_repository": "wf", "source_commit": "s",
               "required_plugin": "WorldForge", "required_plugin_version": "1",
               "required_plugin_source_hash": "sha256:deadbeef"}
        (root / "request.json").write_text(json.dumps(req), encoding="utf-8")
        man = OP.build_operation_manifest(
            root, req,
            raw_evidence=[{"path": "procedural/reports/scene_survey/runtime/"
                                   "far_side_run1.json", "role": "far_side_run"}],
            derived_report=env_res.value["relative_posix"])
        pub = OP.publish_operation_manifest(root, man.value) if man.ok else man
        sel = _ran(_select_input, _Args(operation_id=op_id, request="request.json"),
                   repo_root=root)
        rep.check("dogfood::selection_positive_control", not sel,
                  "a fully-bound operation (manifest + request + operation-scoped "
                  "report) must pass EVERY selection rail, or 'honestly RED' is an "
                  "unfalsifiable claim. manifest_built={} published={} failures={}"
                  .format(man.ok, getattr(pub, "ok", None), sorted(sel)),
                  code=C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING)
        # NEGATIVE on the same tree: mutate the request so its hash no longer binds.
        tampered = dict(req, target_map="/Game/Fixture/Lvl_Somewhere_Else")
        (root / "tampered.json").write_text(json.dumps(tampered), encoding="utf-8")
        rep.check("dogfood::request_hash_mismatch_rejected",
                  "identity::request_hash_bound" in _ran(
                      _select_input,
                      _Args(operation_id=op_id, request="tampered.json"),
                      repo_root=root),
                  "a request whose hash does not match the manifest must FAIL — the "
                  "same tree that just went green",
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)
        # NEGATIVE: an operation-scoped artifact for a DIFFERENT operation id.
        rep.check("dogfood::unknown_operation_rejected",
                  "input::operation_scoped_artifact" in _ran(
                      _select_input, _Args(operation_id="op_never_ran"),
                      repo_root=root),
                  "an operation with no artifact of its own must FAIL rather than "
                  "inherit whatever sits at the legacy fixed path",
                  code=C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING)

        rep.check("dogfood::unnamed_operation_rejected",
                  "input::operation_id_resolved" in _ran(_select_input, _Args()),
                  "a gate asked to grade no particular operation must FAIL — that "
                  "is the fixed-filename defect this rail exists for",
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)

        # ---- the three REDs must be TELLABLE APART ------------------------- #
        # This is the whole point of the resolution rails: a missing --operation-id
        # (a caller wiring bug) used to render identically to "no live survey has
        # run yet" (the intentional state). Each case below asserts BOTH that its
        # own rail fires AND that the other two do not, over the SAME synthetic
        # tree that just went green above.
        wiring = _ran_blocking(_select_input, _Args(), repo_root=root)
        rep.check("dogfood::wiring_defect_is_distinguishable",
                  "input::operation_id_resolved" in wiring
                  and "input::operation_id_unambiguous" not in wiring
                  and "input::caller_evidence_present" not in wiring,
                  "no operation id from any source must fire ONLY the wiring rail: "
                  "it is a missing argument, not absent evidence and not ambiguity "
                  "(got {})".format(sorted(wiring)),
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)

        ambiguous = _ran_blocking(
            _select_input,
            _Args(pack_document={"scene_survey_operation_ids":
                                 [op_id, "op_dogfood_positive_0002"]}),
            repo_root=root)
        rep.check("dogfood::ambiguity_is_distinguishable",
                  "input::operation_id_unambiguous" in ambiguous
                  and "input::operation_id_resolved" not in ambiguous
                  and "input::caller_evidence_present" not in ambiguous,
                  "two declared bound operations must fire ONLY the ambiguity rail, "
                  "and the gate must NOT pick one (got {})".format(sorted(ambiguous)),
                  code=C.SCENE_SURVEY_CONCURRENT_OPERATION)

        absent = _ran_blocking(_select_input,
                               _Args(operation_id="op_dogfood_never_ran_0001"),
                               repo_root=root)
        rep.check("dogfood::absent_evidence_is_distinguishable",
                  "input::caller_evidence_present" in absent
                  and "input::operation_id_resolved" not in absent
                  and "input::operation_id_unambiguous" not in absent,
                  "a named operation with nothing on disk must fire ONLY the "
                  "absent-caller-evidence rail — the gate knew what to grade and "
                  "nobody has produced it (got {})".format(sorted(absent)),
                  code=C.SCENE_SURVEY_EVIDENCE_MISSING)

        # POSITIVE: a pack declaring exactly ONE bound operation resolves it,
        # under the same strict id validation the argument path uses.
        one_pack = resolve_operation_id(
            _Args(pack_document={"scene_survey_operation_id": op_id}),
            repo_root=root)
        rep.check("dogfood::single_pack_declaration_resolves",
                  one_pack["operation_id"] == op_id
                  and one_pack["source"] == OP_SOURCE_PACK,
                  "one declared bound operation must resolve from the pack source, "
                  "not fall through to the wiring RED (got {})".format(one_pack),
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)

        # NEGATIVE: the newest-on-disk shortcut must be UNREACHABLE. There are two
        # published operations under `root` at this point; a resolver that scanned
        # would return one of them for an invocation that named neither.
        second = OP.report_path_for(root, "op_dogfood_positive_0002")
        second.value["absolute"].parent.mkdir(parents=True, exist_ok=True)
        second.value["absolute"].write_text("{}", encoding="utf-8")
        scanned = resolve_operation_id(_Args(), repo_root=root)
        rep.check("dogfood::no_newest_on_disk_fallback",
                  scanned["operation_id"] is None
                  and scanned["outcome"] == OUTCOME_WIRING_DEFECT
                  and scanned["sources_consulted"] == list(OPERATION_ID_SOURCES),
                  "with operations present on disk and no source naming one, the "
                  "resolver must still resolve NOTHING — 'take the newest' is the "
                  "eight-day-old-artifact defect in a new costume (got {})".format(
                      scanned), code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)
        rep.check("dogfood::unbound_request_rejected",
                  "identity::request_hash_bound" in _ran(
                      _select_input, _Args(operation_id="op_dogfood_absent")),
                  "an operation with no manifest+request pair must FAIL the "
                  "request-hash binding rail",
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)
        # NEGATIVE: an artifact older than the caller's window.
        old_ctx = {"report_path": p_ok}
        stale = _ran(_validate_freshness, old_ctx,
                     _Args(max_age_seconds=0), now=time.time() + 10.0)
        rep.check("dogfood::stale_artifact_rejected",
                  "freshness::within_max_age" in stale,
                  "an artifact outside the declared max age must FAIL (got {})".format(
                      stale), code=C.SCENE_SURVEY_STALE_EVIDENCE)
        # NEGATIVE: an artifact older than the code that produces it.
        import os
        old = time.time() - 400 * 86400
        os.utime(p_ok, (old, old))
        predates = _ran(_validate_freshness, {"report_path": p_ok},
                        _Args(max_age_seconds=None))
        rep.check("dogfood::predating_artifact_rejected",
                  "freshness::not_older_than_producers" in predates,
                  "an artifact older than its producing code must FAIL (got {})".format(
                      predates), code=C.SCENE_SURVEY_STALE_EVIDENCE)

        # ---- declared freshness: the rail an mtime `touch` must not defeat --- #
        import datetime

        def _iso(offset_s):
            return datetime.datetime.fromtimestamp(
                time.time() + offset_s, datetime.timezone.utc).isoformat()

        fresh_env = {"meta": {"timestamp": _iso(0), "git_sha": git_sha()}}
        rep.check("dogfood::declared_freshness_positive",
                  not _ran(_validate_declared_freshness, fresh_env, _Args()),
                  "a just-built envelope at HEAD must pass every declared-freshness "
                  "rail: {}".format(_ran(_validate_declared_freshness, fresh_env,
                                         _Args())),
                  code=C.SCENE_SURVEY_STALE_EVIDENCE)
        rep.check("dogfood::declared_timestamp_absent_rejected",
                  "freshness::declared_timestamp_present" in _ran(
                      _validate_declared_freshness, {"meta": {}}, _Args()),
                  "an envelope with no meta.timestamp must FAIL: mtime alone is "
                  "launderable by a rewrite",
                  code=C.SCENE_SURVEY_STALE_EVIDENCE)
        stale_env = {"meta": {"timestamp": _iso(-8 * 86400), "git_sha": git_sha()}}
        stale_named = _ran(_validate_declared_freshness, stale_env, _Args())
        rep.check("dogfood::declared_stale_rejected",
                  "freshness::declared_within_max_age" in stale_named
                  and "freshness::declared_after_producers" in stale_named,
                  "an eight-day-old DECLARED build time must FAIL both the max-age "
                  "and the predates-producers rails even when the file was touched "
                  "one second ago — this is the exact defect being repaired (got "
                  "{})".format(stale_named), code=C.SCENE_SURVEY_STALE_EVIDENCE)
        rep.check("dogfood::wrong_git_sha_rejected",
                  "freshness::git_sha_matches_head" in _ran(
                      _validate_declared_freshness,
                      {"meta": {"timestamp": _iso(0), "git_sha": "0" * 40}}, _Args()),
                  "a report produced at another revision must not pass silently",
                  code=C.SCENE_SURVEY_STALE_EVIDENCE)

        # ---- operation identity -------------------------------------------- #
        rep.check("dogfood::wrong_operation_rejected",
                  "identity::df::report_operation_id" in _ran(
                      _validate_operation_identity,
                      {"operation_id": "op_expected"}, clean, "df"),
                  "a report for a different operation must FAIL identity binding",
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)

        # ---- provenance ----------------------------------------------------- #
        rep.check("dogfood::clean_provenance_accepted",
                  not _ran(_validate_provenance, good_env, clean, "df"),
                  "a report with no evidence records must not trip the provenance rail",
                  code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
        forged_env = {"survey": dict(clean),
                      "evidence": {"subject_id": {"classification": RC.OBSERVED,
                                                  "value": "subject_fixture_alpha"}}}
        rep.check("dogfood::forged_observed_subject_rejected",
                  "provenance::df::request_fields_not_observed" in _ran(
                      _validate_provenance, forged_env, clean, "df"),
                  "a subject_id record claiming classification 'observed' must FAIL: "
                  "WorldForge has no channel that could observe caller vocabulary",
                  code=C.SCENE_SURVEY_SUBJECT_INFERRED)

        # ---- raw collection / determinism / recompute ----------------------- #
        raw_ok = RC._clean_bundle()
        run_doc = {"operation_id": "op_dogfood", "raw_evidence": raw_ok}
        _write("far_side_run1.json", json.dumps(run_doc))
        bundles_ok = [("far_side_run1.json", raw_ok, run_doc)]

        rep.check("dogfood::no_raw_rejected",
                  "raw::df::bundle_present" in _ran(
                      _collect_raw, {"operation_id": "op_dogfood"},
                      {"survey": clean}, clean, "df"),
                  "an envelope with no reachable raw bundle must FAIL, because every "
                  "derived value in it is then unverifiable",
                  code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
        rep.check("dogfood::cross_operation_evidence_rejected",
                  "raw::df::no_cross_operation_refs" in _ran(
                      _collect_raw, {"operation_id": "op_other"},
                      {"raw_evidence": raw_ok, "operation_id": "op_dogfood"},
                      dict(clean, operation_id="op_dogfood"), "df"),
                  "raw evidence declaring a different operation_id must FAIL",
                  code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)

        det_survey = {"meta": {"per_run_hashes": ["a", "a"],
                               "determinism_consistent": True}}
        drift = dict(raw_ok)
        drift["marker"] = {"marker_000": dict(raw_ok["marker"]["marker_000"],
                                              accepted=False)}
        two = bundles_ok + [("far_side_run2.json", drift, run_doc)]
        det = _ran(_validate_determinism, det_survey, two, "df")
        rep.check("dogfood::determinism_drift_rejected",
                  "determinism::df::runs_identical" in det,
                  "two run bundles that differ must FAIL determinism on RECOMPUTED "
                  "digests, not on the report's self-attested per_run_hashes (got "
                  "{})".format(det), code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)
        overclaim = _ran(_validate_determinism,
                         {"meta": {"per_run_hashes": ["a", "a", "a"],
                                   "determinism_consistent": True}},
                         bundles_ok, "df")
        rep.check("dogfood::determinism_overclaim_rejected",
                  "determinism::df::claim_count_matches" in overclaim,
                  "a report claiming more runs than there are artifacts must FAIL "
                  "(got {})".format(overclaim),
                  code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)
        self_contradicting = _ran(_validate_determinism,
                                  {"meta": {"per_run_hashes": ["a", "b"],
                                            "determinism_consistent": True}},
                                  bundles_ok + [("far_side_run2.json", raw_ok, run_doc)],
                                  "df")
        rep.check("dogfood::determinism_self_contradicting_claim_rejected",
                  "determinism::df::claimed_hashes_agree" in self_contradicting,
                  "a report whose OWN per_run_hashes disagree while claiming "
                  "consistency must FAIL — this conjunct is carried over from the "
                  "rail this function replaced (got {})".format(self_contradicting),
                  code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)
        rep.check("dogfood::determinism_clean_accepted",
                  not _ran(_validate_determinism,
                           {"meta": {"per_run_hashes": ["a"],
                                     "determinism_consistent": True}},
                           bundles_ok, "df"),
                  "one artifact + one claimed hash + consistent must pass",
                  code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)

        honest = dict(clean, actor_bounds_valid=True,
                      temporary_placements_grounded=1, overlap_count=0,
                      player_clearance_valid=True, cleanup_verified=True,
                      map_asset_path="/Game/Fixture/Lvl_Fixture")
        subj_fix = dict(subject, map_asset_path="/Game/Fixture/Lvl_Fixture")
        rep.check("dogfood::recompute_clean_accepted",
                  not _ran(_validate_recompute, subj_fix, honest, bundles_ok, _Args(), "df"),
                  "a report whose aggregates follow from its raw must pass every "
                  "recompute rail: {}".format(
                      _ran(_validate_recompute, subj_fix, honest, bundles_ok,
                           _Args(), "df")),
                  code=C.SCENE_SURVEY_EVIDENCE_REDERIVATION_MISMATCH)
        # NEGATIVE: a forged aggregate.
        forged_agg = _ran(_validate_recompute, subj_fix,
                          dict(honest, overlap_count=7), bundles_ok, _Args(), "df")
        rep.check("dogfood::forged_aggregate_rejected",
                  "recompute::df::aggregates_follow_from_raw" in forged_agg,
                  "a reported aggregate the raw does not produce must FAIL (got "
                  "{})".format(forged_agg),
                  code=C.SCENE_SURVEY_EVIDENCE_REDERIVATION_MISMATCH)
        # NEGATIVE: actor_bounds_valid from a COUNT, with no bounds in the raw.
        no_bounds = dict(raw_ok)
        no_bounds["actor"] = {"a": {"path_name": "/A", "collection_ok": False}}
        counted_only = _ran(_validate_recompute, subj_fix, honest,
                            [("run", no_bounds, run_doc)], _Args(), "df")
        rep.check("dogfood::bounds_from_count_rejected",
                  "recompute::df::no_unknown_presented_as_decided" in counted_only,
                  "actor_bounds_valid=True with no per-actor bounds in the raw must "
                  "FAIL as an undecidable presented as decided (got {})".format(
                      counted_only), code=C.SCENE_SURVEY_EVIDENCE_INSUFFICIENT)
        # NEGATIVE: cleanup_verified as a literal, with no inventories at all.
        no_inv = dict(raw_ok)
        no_inv["inventory"] = {}
        literal_cleanup = _ran(_validate_recompute, subj_fix, honest,
                               [("run", no_inv, run_doc)], _Args(), "df")
        rep.check("dogfood::literal_cleanup_rejected",
                  "recompute::df::cleanup_from_inventories" in literal_cleanup,
                  "cleanup_verified=True with no pre/post inventory must FAIL (got "
                  "{})".format(literal_cleanup),
                  code=C.SCENE_SURVEY_CLEANUP_UNVERIFIED)
        # NEGATIVE: a restatement that contradicts its own atom.
        contra = json.loads(json.dumps(raw_ok))
        contra["marker"]["marker_000"]["grounded"] = False
        contradicted = _ran(_validate_recompute, subj_fix, honest,
                            [("run", contra, run_doc)], _Args(), "df")
        rep.check("dogfood::contradictory_atoms_rejected",
                  "recompute::df::no_contradictory_atoms" in contradicted,
                  "a marker restating grounded=False over a trace that hit must FAIL "
                  "(got {})".format(contradicted),
                  code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
        # NEGATIVE: a dangling ref.
        dangle = json.loads(json.dumps(raw_ok))
        dangle["marker"]["marker_000"]["ground_trace_ref"] = "trace#gone"
        dangled = _ran(_collect_raw, {"operation_id": "op_dogfood"},
                       {"raw_evidence": dangle}, dict(clean, operation_id="op_dogfood"),
                       "df")
        rep.check("dogfood::dangling_ref_rejected",
                  "raw::df::refs_resolve" in dangled,
                  "a raw_ref that resolves to no record must FAIL (got {})".format(
                      dangled), code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING)
        # NEGATIVE: world identity measured against a different map.
        wrong_world = _ran(_validate_recompute,
                           dict(subject, map_asset_path="/Game/Fixture/Lvl_Other"),
                           honest, bundles_ok, _Args(), "df")
        rep.check("dogfood::wrong_world_rejected",
                  "recompute::df::world_identity_ok" in wrong_world,
                  "a survey of a world other than the requested one must FAIL (got "
                  "{})".format(wrong_world),
                  code=C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)

        # ---- ACCEPTANCE ELIGIBILITY: one negative per term, all through the
        # SHIPPED rail. Each case is the single acceptance fixture with exactly one
        # atom changed, so a rail that reds can only be reading that atom.
        ACC_RAIL = "recompute::df::acceptance_claim_matches_raw"
        ACC_COMP = "recompute::df::acceptance_components_follow_from_raw"
        ACC_EV = "recompute::df::acceptance_evidence_not_contradicted"

        def _acc(mutate=None, operation_id=RC._ACC_OP):
            """Run the shipped recompute rail over the acceptance fixture."""
            a_sub, a_rep, a_raw = RC._clean_acceptance_case()
            if mutate is not None:
                mutate(a_sub, a_rep, a_raw)
            return _ran(_validate_recompute, a_sub, a_rep,
                        [("acceptance_fixture", a_raw, {"operation_id": operation_id})],
                        _Args(), "df", operation_id=operation_id)

        rep.check("dogfood::acceptance_clean_accepted", not _acc(),
                  "an acceptance-eligible survey whose raw supports every term must "
                  "pass EVERY rail, or each negative below is meaningless: {}".format(
                      sorted(_acc())),
                  code=C.SCENE_SURVEY_EVIDENCE_REDERIVATION_MISMATCH)

        def _m_explicit(sub, _rep, _raw):
            sub["anchor_mode"] = "explicit_transform"
            sub["anchor_object_path"] = None
            sub["anchor_location"] = list(RC._ACC_ANCHOR)

        def _w_other_world(_sub, _rep, raw):
            raw["world"]["observed"]["package_name"] = "/Game/Fixture/Lvl_Elsewhere"

        def _p_substituted(_sub, _rep, raw):
            rec = raw["actor"].pop(RC._ACC_PATH)
            rec["path_name"] = RC._ACC_OTHER + "_substitute"
            rec["actor_object_path"] = rec["path_name"]
            raw["actor"][rec["path_name"]] = rec

        def _t_drifted(_sub, report, _raw):
            report["observed_anchor_location"] = [RC._ACC_ANCHOR[0] + 500.0,
                                                  RC._ACC_ANCHOR[1], RC._ACC_ANCHOR[2]]

        def _b_wrong_origin(_sub, _rep, raw):
            raw["actor"][RC._ACC_OTHER]["distance_to_anchor_cm"] = 999.0

        def _e_two_operations(_sub, _rep, raw):
            raw["actor"][RC._ACC_OTHER]["operation_id"] = "op_some_other_run"

        for term, label, mutate, rails in (
                ("M", "explicit_transform_is_never_eligible", _m_explicit, (ACC_RAIL,)),
                ("W", "world_other_than_requested", _w_other_world, (ACC_RAIL,)),
                ("P", "substituted_anchor_actor", _p_substituted, (ACC_RAIL,)),
                ("T", "anchor_transform_not_the_actors", _t_drifted, (ACC_RAIL,)),
                ("B", "survey_not_centred_on_the_actor", _b_wrong_origin, (ACC_RAIL,)),
                ("E", "raw_split_across_operations", _e_two_operations,
                 (ACC_RAIL, ACC_EV))):
            got = _acc(mutate)
            rep.check("dogfood::acceptance_{}_{}_rejected".format(term, label),
                      all(rail in got for rail in rails),
                      "term {} of A(o)=M∧W∧P∧T∧B∧E must deny an otherwise-perfect "
                      "report that still claims acceptance_eligible=True; expected "
                      "{} in the failures, got {}".format(term, list(rails),
                                                          sorted(got)),
                      code=C.SCENE_SURVEY_EVIDENCE_UNSUPPORTED_CLAIM)

        # NEGATIVE: the bundle belongs to a DIFFERENT operation than the one graded.
        rep.check("dogfood::acceptance_foreign_operation_rejected",
                  ACC_EV in _acc(operation_id="op_the_one_being_graded"),
                  "raw whose records name another operation must deny term E, "
                  "however clean each individual measurement is",
                  code=C.SCENE_SURVEY_EVIDENCE_INSUFFICIENT)

        # NEGATIVE: the SYMMETRIC direction scene_survey_contracts.py:1144-1153
        # declined to install — a report under-claiming against its own evidence.
        def _under_claim(_sub, report, _raw):
            report["acceptance_eligible"] = False
            report["acceptance_ineligibility_reason"] = \
                "independent_subject_anchor_not_observable"

        rep.check("dogfood::acceptance_underclaim_rejected",
                  ACC_RAIL in _acc(_under_claim),
                  "a report claiming acceptance_eligible=False over raw that "
                  "re-derives True must FAIL too: an under-claim is still a report "
                  "that does not follow from its own evidence",
                  code=C.SCENE_SURVEY_EVIDENCE_UNSUPPORTED_CLAIM)

        # NEGATIVE: a per-component claim forged to True over raw that denies it.
        def _forged_component(_sub, report, raw):
            raw["actor"][RC._ACC_OTHER]["distance_to_anchor_cm"] = 999.0
            report["meta"]["acceptance_components"][
                "survey_bound_to_observed_actor"] = True

        rep.check("dogfood::acceptance_forged_component_rejected",
                  ACC_COMP in _acc(_forged_component),
                  "a meta.acceptance_components entry the raw denies must FAIL the "
                  "component rail, not just the aggregate one",
                  code=C.SCENE_SURVEY_EVIDENCE_REDERIVATION_MISMATCH)

        # NEGATIVE: raw too thin to decide, claim stated anyway.
        def _no_actors(_sub, _rep, raw):
            raw["actor"] = {}

        thin = _acc(_no_actors)
        rep.check("dogfood::acceptance_undecidable_claim_rejected",
                  ACC_RAIL in thin
                  and "recompute::df::no_unknown_presented_as_decided" in thin,
                  "an acceptance claim over raw that cannot decide it must FAIL as "
                  "an unknown presented as decided, not pass as agreement (got "
                  "{})".format(sorted(thin)),
                  code=C.SCENE_SURVEY_EVIDENCE_INSUFFICIENT)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # The recompute module's own dogfood must be green, or every rail above is
    # standing on an unverified derivation.
    rep.check("dogfood::recompute_module_selftest", RC._main() == 0,
              "tools/pipeline/scene_survey_recompute.py self-dogfood must pass",
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey runtime evidence gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--operation-id", default=None,
                    help="the operation being graded. Wins over every other source. "
                         "When omitted, the only other source is a pack that "
                         "declares exactly ONE bound operation — no pack schema "
                         "carries that field today, so omitting this flag is a "
                         "WIRING DEFECT (WF1128), reported separately from the "
                         "absent-runtime-evidence RED (WF1097) and from ambiguity "
                         "(WF1129). The operations directory is never scanned")
    ap.add_argument("--report", default=None,
                    help="explicit envelope path (still bound to --operation-id)")
    ap.add_argument("--request", default=None,
                    help="the originating BridgeRequest JSON, for request-hash binding")
    ap.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS,
                    help="reject an artifact older than this (default 24h)")
    ap.add_argument("--tau-supported-fraction", type=float,
                    default=RC.TAU_SUPPORTED_FRACTION)
    ap.add_argument("--tau-ground-dz-cm", type=float, default=RC.TAU_GROUND_DZ_CM)
    ap.add_argument("--theta-max-deg", type=float, default=RC.THETA_MAX_DEG)
    ap.add_argument("--tau-anchor-transform-cm", type=float,
                    default=RC.TAU_ANCHOR_TRANSFORM_CM,
                    help="how far the STATED anchor transform may sit from the "
                         "measured actor transform before term T of acceptance "
                         "eligibility is denied (cm)")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    _dogfood(rep)

    resolution = resolve_operation_id(args)
    ctx = _select_input(rep, args, resolution=resolution)
    _validate_freshness(rep, ctx, args)

    obj, survey, subject = _load_envelope(rep, ctx["report_path"], "live")
    if obj is not None:
        _validate_declared_freshness(rep, obj, args)
        _validate_operation_identity(rep, ctx, survey, "live")
        _validate_provenance(rep, obj, survey, "live")
        _validate_runtime_obj(rep, survey, "live")
        _validate_runtime_binding(rep, subject, survey, "live")
        bundles, _source = _collect_raw(rep, ctx, obj, survey, "live")
        _validate_determinism(rep, survey, bundles, "live")
        _validate_recompute(rep, subject, survey, bundles, args, "live",
                            operation_id=ctx.get("operation_id"))

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-scene-survey-runtime", pack=args.pack, strict=strict,
        status=rep.status, report_type="wf.scene_survey.runtime_gate.v1",
        extra={"operation_id": ctx.get("operation_id"),
               "operation_id_argument": args.operation_id,
               "operation_id_source": resolution.get("source"),
               "operation_id_outcome": resolution.get("outcome"),
               "operation_id_candidates": resolution.get("candidates"),
               "operation_id_sources_consulted": resolution.get("sources_consulted"),
               "operation_id_detail": resolution.get("detail"),
               "input_selection": ctx.get("selection"),
               "graded_artifact": str(ctx.get("report_path")),
               "tau_supported_fraction": args.tau_supported_fraction,
               "tau_ground_dz_cm": args.tau_ground_dz_cm,
               "theta_max_deg": args.theta_max_deg,
               "tau_anchor_transform_cm": args.tau_anchor_transform_cm}))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_scene_survey_runtime_report.json")
    rep.print_summary("validate-scene-survey-runtime")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
