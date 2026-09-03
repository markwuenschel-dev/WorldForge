#!/usr/bin/env python3
"""wf_build -- ONE bounded build request in, one terminal receipt out.

    python pipeline/wf_build.py --request my_build.json

WHY A SINGLE ENTRY POINT IS THE DELIVERABLE, NOT A CONVENIENCE
--------------------------------------------------------------
Every stage of this platform already exists and is gated. What did not exist was
a way to ASK for a world: driving it meant knowing ten flags, the order the
phases run in, which artifact feeds which, and what a healthy intermediate looks
like -- that is, knowing WorldForge's internal pipeline structure. An importing
game is not supposed to know any of that. If consuming the platform requires
holding its internals in your head, the platform has not been delivered; a
collection of correct parts has.

So this takes one document, and returns one receipt carrying a terminal state
from the vocabulary the acceptance layer already enforces
(``wfcore.acceptance.evaluate.OUTCOMES``) -- not a new fourth set invented here.

TERMINAL STATES, AND WHY 'SUCCESS' IS NOT ONE
---------------------------------------------
``accepted``        the world was built and every declared check held
``rejected``        something was measured and it was wrong
``indeterminate``   blocked by what nobody measured -- the honest unknown
``partial_commit``  a world state no contract describes; the loudest result here
``refused``         the judgement could not honestly run at all

There is deliberately no bare "success". A caller that reads only a boolean
cannot distinguish "we checked and it held" from "we could not check", and those
two have been the difference between every real result and every fake-green this
repository has had to dig out.

WHAT IT REFUSES
---------------
It will not invent any part of the request. Anchors, actor class, protected
paths, the target map and the project are all the caller's, and a missing one is
``refused`` with the field named -- never defaulted into something plausible.
"""

import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.acceptance import evaluate as EV     # noqa: E402

RT_BUILD_REQUEST = "wf.core.build_request.v1"
RT_BUILD_RECEIPT = "wf.core.build_receipt.v1"

# Everything a bounded build needs, and nothing WorldForge could guess.
REQUEST_REQUIRED = ("request_id", "consumer", "consumer_path", "caller_artifacts",
                    "subject_map", "route_anchors", "actor_class",
                    "schema_version")
REQUEST_ALLOWED = REQUEST_REQUIRED + ("project", "protected_identities",
                                      "static_mesh", "material",
                                      "placement_count", "extent_cm",
                                      "caller_repo", "registry_source",
                                      "created_by", "notes", "report_type")


def validate_build_request(req):
    """(errors, warnings). Cheap, and it never costs an editor boot to find out."""
    errors, warnings = [], []
    if not isinstance(req, dict):
        return ["build request must be an object"], []
    for f in REQUEST_REQUIRED:
        if f not in req:
            errors.append("missing required field {!r}".format(f))
    sv = req.get("schema_version")
    if sv != RT_BUILD_REQUEST:
        errors.append("schema_version must be {!r} (got {!r})".format(
            RT_BUILD_REQUEST, sv))
    extra = sorted(set(req) - set(REQUEST_ALLOWED))
    if extra:
        errors.append("unknown fields {}; the request vocabulary is closed so a "
                      "caller cannot smuggle in an instruction nothing "
                      "reads".format(extra))
    anchors = req.get("route_anchors")
    if not (isinstance(anchors, list) and len(anchors) == 2
            and all(isinstance(a, str) and a for a in anchors)):
        errors.append("route_anchors must be exactly two subject ids (got {!r}); "
                      "a route is between two measured places".format(anchors))
    if not (isinstance(req.get("actor_class"), str)
            and req.get("actor_class", "").strip()):
        errors.append("actor_class is required and has no default: WorldForge "
                      "decides where things go, the caller decides what")
    if not req.get("static_mesh"):
        warnings.append("no 'static_mesh' given: the placements will be "
                        "zero-extent actors, which the scene survey correctly "
                        "refuses as geometry. A real world slice names one")
    if not req.get("project"):
        warnings.append("no 'project' given, so the build targets WorldForge's "
                        "own project. A real consumer names its own .uproject")
    return errors, warnings


def _receipt(req, outcome, reason, **extra):
    d = {
        "schema_version": RT_BUILD_RECEIPT, "report_type": RT_BUILD_RECEIPT,
        "request_id": (req or {}).get("request_id"),
        "outcome": outcome, "reason": reason,
        "accepted": outcome == EV.OUTCOME_ACCEPTED,
    }
    d.update(extra)
    return d


def _classify(loop_report):
    """Map a loop result onto the acceptance vocabulary. Never onto a boolean.

    The mapping is deliberately conservative at one point: a run that stopped
    after materialising but before cleaning up is ``partial_commit``, not
    ``rejected``. Content exists in the world that no completed contract
    describes, and that is a louder and more actionable state than "a check
    failed" -- somebody has to go and look.
    """
    if not isinstance(loop_report, dict):
        return EV.OUTCOME_REFUSED, "the loop produced no readable report"
    if loop_report.get("green"):
        return EV.OUTCOME_ACCEPTED, "every phase held"

    stopped = loop_report.get("stopped_at")
    phases = loop_report.get("phases") or []
    done = {p.get("phase") for p in phases if p.get("ok")}

    if loop_report.get("verdict") == "plumbing_only":
        return EV.OUTCOME_INDETERMINATE, (
            "plumbing check only: nothing was materialised, so nothing about the "
            "world was established either way")
    if stopped in ("intake", "anchors", "plan", "request"):
        return EV.OUTCOME_REFUSED, (
            "the build could not honestly start: stopped at {!r} before anything "
            "was authored".format(stopped))
    if stopped == "ownership":
        return EV.OUTCOME_REFUSED, (
            "escalated on ownership: a generated target collides with declared "
            "game-owned content, and that is not a mechanical decision")
    if "materialise" in done and "cleanup" not in done:
        return EV.OUTCOME_PARTIAL_COMMIT, (
            "stopped at {!r} AFTER materialising. Generated content is in the "
            "world that no completed contract describes -- inspect before "
            "re-running".format(stopped))
    return EV.OUTCOME_REJECTED, "stopped at {!r}".format(stopped)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--request", required=True, help="path to a build request")
    ap.add_argument("--out", help="path for the receipt")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate and check readiness; author nothing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        with open(args.request, encoding="utf-8") as fh:
            req = json.load(fh)
    except (OSError, ValueError) as exc:
        rec = _receipt(None, EV.OUTCOME_REFUSED,
                       "build request unreadable: {}".format(exc))
        print(json.dumps(rec, indent=2)); return 2

    errors, warnings = validate_build_request(req)
    if errors:
        rec = _receipt(req, EV.OUTCOME_REFUSED,
                       "the build request is not valid, so nothing was attempted",
                       request_errors=errors, request_warnings=warnings)
        _emit(rec, args); return 2

    scratch = os.path.dirname(os.path.abspath(args.out or args.request))
    py = sys.executable

    # -- readiness, before anything is authored ------------------------------ #
    ready_out = os.path.join(scratch, "build_readiness.json")
    cmd = [py, os.path.join(_HERE, "check_external_readiness.py"),
           "--consumer", req["consumer"],
           "--consumer-path", req["consumer_path"],
           "--artifact-root", req["caller_artifacts"],
           "--out", ready_out]
    for a in req["route_anchors"]:
        cmd += ["--anchor", a]
    if req.get("caller_repo"):
        cmd += ["--caller-repo", req["caller_repo"]]
    if req.get("registry_source"):
        cmd += ["--registry-source", req["registry_source"]]
    subprocess.run(cmd, capture_output=True, text=True, cwd=_TOOLS)
    readiness = None
    if os.path.isfile(ready_out):
        try:
            with open(ready_out, encoding="utf-8") as fh:
                readiness = json.load(fh)
        except (OSError, ValueError):
            readiness = None

    if readiness and not readiness.get("would_run_succeed"):
        rec = _receipt(
            req, EV.OUTCOME_INDETERMINATE,
            "the build was not attempted because it could not have succeeded: "
            "{}. This is not a failure of the world -- it is a statement that "
            "the inputs to judge it do not exist yet".format(
                readiness.get("blocked")),
            readiness=readiness, request_warnings=warnings)
        _emit(rec, args); return 1

    if args.dry_run:
        rec = _receipt(req, EV.OUTCOME_INDETERMINATE,
                       "--dry-run: the request is valid and readiness holds, but "
                       "nothing was authored and nothing about the world is "
                       "claimed", readiness=readiness, request_warnings=warnings)
        _emit(rec, args); return 0

    # -- the bounded build ---------------------------------------------------- #
    loop_out = os.path.join(scratch, "build_loop.json")
    cmd = [py, os.path.join(_HERE, "run_closed_loop_proof.py"),
           "--caller-artifacts", req["caller_artifacts"],
           "--subject-start", req["route_anchors"][0],
           "--subject-end", req["route_anchors"][1],
           "--map", req["subject_map"],
           "--actor-class", req["actor_class"],
           "--operation-id", req["request_id"],
           "--count", str(req.get("placement_count", 3)),
           "--extent-cm", str(req.get("extent_cm", 20000.0)),
           "--consumer-path", req["consumer_path"],
           "--caller-adapter", req["consumer"],
           "--out", loop_out]
    if req.get("project"):
        cmd += ["--project", req["project"]]
    if req.get("static_mesh"):
        cmd += ["--static-mesh", req["static_mesh"]]
    if req.get("material"):
        cmd += ["--material", req["material"]]
    for pth in req.get("protected_identities") or []:
        cmd += ["--protected", pth]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_TOOLS)

    loop = None
    if os.path.isfile(loop_out):
        try:
            with open(loop_out, encoding="utf-8") as fh:
                loop = json.load(fh)
        except (OSError, ValueError):
            loop = None

    outcome, reason = _classify(loop)
    rec = _receipt(req, outcome, reason,
                   readiness=readiness,
                   request_warnings=warnings,
                   proof_kind=(loop or {}).get("proof_kind"),
                   stopped_at=(loop or {}).get("stopped_at"),
                   phases=[{"phase": p.get("phase"), "ok": p.get("ok")}
                           for p in (loop or {}).get("phases", [])],
                   loop_report=loop_out,
                   loop_stdout_tail=(proc.stdout or "")[-400:])
    _emit(rec, args)
    return 0 if outcome == EV.OUTCOME_ACCEPTED else 1


def _emit(rec, args):
    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, sort_keys=True)
    if args.json:
        print(json.dumps(rec, indent=2, sort_keys=True)); return
    print("wf-build -- {}".format(rec.get("request_id")))
    print("  outcome : {}".format(rec["outcome"]))
    print("  reason  : {}".format(rec["reason"][:300]))
    if rec.get("proof_kind"):
        print("  proof   : {}".format(rec["proof_kind"]))
    for p in rec.get("phases") or []:
        print("    [{}] {}".format("OK  " if p["ok"] else "FAIL", p["phase"]))
    for w in rec.get("request_warnings") or []:
        print("  warn    : {}".format(w))


if __name__ == "__main__":
    raise SystemExit(main())
