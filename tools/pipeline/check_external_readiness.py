#!/usr/bin/env python3
"""check_external_readiness -- can the external acceptance run actually succeed?

WHY THIS EXISTS
---------------
"Blocked on the caller" is a sentence. It is not checkable, it goes stale
silently, and it puts the burden on whoever reads it next to re-derive what was
actually missing. This turns that sentence into an exit code and a per-item
checklist computed from the caller's own repository.

It is READ-ONLY with respect to the caller. It imports their adapter, reads the
artifacts they emit, and writes nothing anywhere near their tree. Running it is
not driving their lane and not nudging them: it answers a question WorldForge
needs answered on its own side -- *would a run succeed if we started one?* --
and the honest answer to that today is no, for a reason nobody should have to
take on trust.

WHAT IT DOES NOT DO
-------------------
It does not decide whether WorldForge is ALLOWED to author into the caller's
project. That is a human authorization, it is not inferable from any file, and
a script that concluded "the paths are all present, therefore proceed" would be
manufacturing consent out of a directory listing. Readiness and permission are
different questions; this answers only the first, and says so in its output.
"""

import argparse
import glob
import importlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from consumers import adapter as ADP                    # noqa: E402
from pipeline import observation_intake as OI           # noqa: E402
from pipeline import verify_caller_attestation as VA    # noqa: E402

RT_READINESS = "wf.core.external_readiness.v1"

READY = "ready"
BLOCKED = "blocked"
UNKNOWN = "unknown"


def _item(name, state, detail, owner=None, **extra):
    d = {"item": name, "state": state, "detail": detail, "owner": owner}
    d.update(extra)
    return d


def _resolved_subjects(artifact_root, require=None):
    """subject_id -> locator, for artifacts that actually resolved."""
    require = require or {"status": "resolved"}
    out = {}
    if not artifact_root or not os.path.isdir(artifact_root):
        return out
    for path in sorted(glob.glob(os.path.join(artifact_root, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        if all(doc.get(k) == v for k, v in require.items()):
            sid = doc.get("subject_id")
            if sid:
                out[sid] = path
    return out


def read_declared_subjects(registry_source):
    """Subject ids the caller's registry DECLARES, read from its source.

    A missing anchor means two very different things depending on this. If the
    subject is declared, the caller can produce it by running their survey. If
    it is not declared, no survey will ever emit it and the game needs a source
    change first. Reporting both as "missing" would send someone to re-run a
    survey that structurally cannot help.
    """
    if not registry_source or not os.path.isfile(registry_source):
        return None
    import re
    try:
        text = io_open_text(registry_source)
    except OSError:
        return None
    # The declaration idiom in a UE registry: SubjectId = TEXT("some.id");
    return set(re.findall(r'SubjectId\s*=\s*TEXT\("([^"]+)"\)', text))


def io_open_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def assess(adapter, artifact_root, needed_anchors, caller_repo=None,
           declared_subjects=None):
    items = []

    # 1. Is this a real caller at all?
    origination = ADP.origination_of(adapter)
    caller = origination == ADP.ORIGINATION_CALLER
    # NOT a blocker on whether a run can SUCCEED, and the distinction matters:
    # a WorldForge demonstration consumer can drive a perfectly valid build, it
    # simply cannot produce an externally_proven one. Grading this as BLOCKED
    # conflated "this cannot run" with "this cannot be claimed as external
    # proof", and made the entry point untestable without a real caller.
    items.append(_item(
        "caller_originated", READY if caller else UNKNOWN,
        "adapter declares origination={!r}. This does not gate whether a build "
        "can run; it caps the PROOF RUNG the run can reach -- only a "
        "caller-originated adapter can yield externally_proven, everything else "
        "tops out at mechanism_proof".format(origination),
        owner="caller", proof_ceiling=(
            "externally_proven" if caller else "mechanism_proof")))

    # 2. Is its self-description checkable?
    att = VA.build_attestation_record(adapter, repo_path=caller_repo)
    st = att["resolution_state"]
    items.append(_item(
        "attestation", READY if st == VA.RESOLVED else UNKNOWN if st in (
            VA.ABSENT, VA.UNRESOLVED) else BLOCKED,
        "structured provenance attestation resolves to {!r} ({}). ABSENT is not a "
        "failure -- it means the caller volunteered nothing to check".format(
            st, att.get("declared_commit_sha")),
        owner="caller", record=att))

    # 3. THE ONE THAT DECIDES IT: are the anchors measured?
    resolved = _resolved_subjects(artifact_root)
    missing = [a for a in needed_anchors if a not in resolved]
    items.append(_item(
        "anchors_measured", READY if not missing else BLOCKED,
        "the route needs {} measured anchor(s) {}; the caller has resolved "
        "live evidence for {}. Missing: {}. Placement REFUSES on an unmeasured "
        "anchor rather than inventing a coordinate, so this alone stops the "
        "run".format(len(needed_anchors), needed_anchors,
                     sorted(resolved) or "nothing", missing or "none"),
        owner="caller", resolved=sorted(resolved), missing=missing))

    # 4. Is the missing anchor even surveyable, or does it need a code change?
    #    A subject the caller's registry never declares cannot be produced by
    #    re-running their survey -- it needs new source. Those are different
    #    asks and collapsing them would misdirect whoever picks this up.
    if not missing:
        items.append(_item("missing_anchors_are_declarable", READY,
                           "nothing missing", owner="caller"))
    elif declared_subjects is None:
        items.append(_item(
            "missing_anchors_are_declarable", UNKNOWN,
            "no registry source supplied, so it is not known whether the missing "
            "anchors {} are subjects the caller could survey today or subjects "
            "that do not exist in their game at all. Pass --registry-source to "
            "decide it".format(missing), owner="caller", missing=missing))
    else:
        surveyable = [a for a in missing if a in declared_subjects]
        undeclared = [a for a in missing if a not in declared_subjects]
        items.append(_item(
            "missing_anchors_are_declarable",
            READY if not undeclared else BLOCKED,
            "the caller's registry declares {}. Missing anchors that ARE declared "
            "(need only a survey run): {}. Missing anchors that are NOT declared "
            "(need a source change in the game before any survey could produce "
            "them): {}. Those are different asks and must not be reported as one "
            "backlog item".format(sorted(declared_subjects),
                                  surveyable or "none", undeclared or "none"),
            owner="caller", surveyable=surveyable, undeclared=undeclared))

    # 5. Ownership: does the caller say what must never be touched?
    protected = adapter.get("protected_identities") or []
    items.append(_item(
        "protected_identities_declared", READY if protected else UNKNOWN,
        "the caller declares {} protected path(s). An empty list is not proof "
        "that nothing is protected -- it is an absence of a statement, and the "
        "loop's ownership guard can only refuse what it was told about".format(
            len(protected)), owner="caller", count=len(protected)))

    # 6. The one thing NO file can answer.
    items.append(_item(
        "authorization_to_author", UNKNOWN,
        "whether WorldForge may write generated content into this project is a "
        "human decision. It is not inferable from any artifact, and this script "
        "deliberately does not guess it. Readiness is not permission",
        owner="human"))

    blocked = [i for i in items if i["state"] == BLOCKED]
    return {
        "schema_version": RT_READINESS, "report_type": RT_READINESS,
        "items": items,
        "blocked": [i["item"] for i in blocked],
        "would_run_succeed": not blocked,
        "verdict": READY if not blocked else BLOCKED,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--consumer", required=True)
    ap.add_argument("--consumer-path", action="append", default=[])
    ap.add_argument("--artifact-root", required=True,
                    help="directory of caller-emitted observation artifacts")
    ap.add_argument("--anchor", action="append", required=True,
                    help="a subject id the route needs. Repeatable")
    ap.add_argument("--caller-repo")
    ap.add_argument("--registry-source",
                    help="the caller's survey-registry source file. Lets this "
                         "distinguish 'needs a survey run' from 'needs a source "
                         "change in the game'")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    for d in args.consumer_path:
        if d not in sys.path:
            sys.path.insert(0, d)
    name = args.consumer if "." in args.consumer else "consumers." + args.consumer
    try:
        mod = importlib.import_module(name)
    except ImportError as exc:
        print("could not import consumer {!r}: {}".format(name, exc))
        return 2

    report = assess(mod.adapter(), args.artifact_root, args.anchor,
                    caller_repo=args.caller_repo,
                    declared_subjects=read_declared_subjects(
                        args.registry_source))

    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("external acceptance readiness -- {}".format(args.consumer))
        for i in report["items"]:
            print("  [{:7}] {:32} ({})".format(
                i["state"].upper(), i["item"], i["owner"]))
            print("            {}".format(i["detail"][:150]))
        print("")
        print("  would a run succeed today? {}".format(
            "YES" if report["would_run_succeed"] else "NO -- blocked on {}".format(
                report["blocked"])))
    return 0 if report["would_run_succeed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
