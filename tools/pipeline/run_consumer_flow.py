#!/usr/bin/env python3
"""run_consumer_flow.py -- drive the whole Core flow for one named consumer.

    cd tools
    PYTHONUTF8=1 python pipeline/run_consumer_flow.py --consumer demoarena
    PYTHONUTF8=1 python pipeline/run_consumer_flow.py --consumer demoexpanse --json

WHAT THIS PROVES, AND WHAT IT DOES NOT
--------------------------------------
It proves that a consumer's own contracts -- profile, catalog, request, revision
policy, acceptance criteria -- pass through every Core stage without Core knowing
anything about that consumer. Run it for two consumers that disagree on almost
every axis, then run ``core_boundary_proof verify``: an unchanged Core digest is
the platform claim discharged mechanically rather than asserted.

It does NOT prove a real importing game asked for anything. Both shipped
consumers are WorldForge-authored DEMONSTRATIONS and say so in their own
provenance records. This runner REFUSES to label such a run caller-originated --
see ``_origination_gate``. WorldForge presenting its own request as a caller's
would be WF1288, and it is the one error that leaves every downstream artifact
looking perfect while answering a question nobody asked.

WHY THE STAGES ARE REPORTED INDIVIDUALLY
----------------------------------------
Each stage records its own status and failure codes rather than the run
collapsing to one boolean. A flow that reports only "ok/not ok" cannot tell a
consumer whose REQUEST is malformed from one whose world genuinely fails its
invariants, and those need opposite responses: fix the contract, or change the
world. The per-stage record is what makes the difference legible.

An UNKNOWN stage is reported as UNKNOWN. It is never rounded to failure -- an
unmeasured stage is something to go measure, not something to go fix.
"""

import argparse
import importlib
import json
import os
import sys

# tools/ is the package root for `consumers` and `wfcore` (the same convention
# `bridge` uses). Inserted rather than assumed so the script runs from anywhere.
_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from consumers import adapter as ADP                      # noqa: E402
from wfcore import constraints as K                       # noqa: E402
from wfcore import tri                                    # noqa: E402
from wfcore.contracts import acceptance_criteria as ACR   # noqa: E402
from wfcore.contracts import asset_catalog as AC          # noqa: E402
from wfcore.contracts import consumer_profile as CP       # noqa: E402
from wfcore.contracts import revision_policy as RP        # noqa: E402
from wfcore.contracts import world_request as WR          # noqa: E402

REPORT_TYPE = "wf.core.consumer_flow_report.v1"

STAGE_OK = "ok"
STAGE_FAILED = "failed"
STAGE_UNKNOWN = "unknown"


def _stage(name, checks):
    """Fold a validator's checks into one stage record, preserving the codes."""
    failing = [(n, d, c) for (n, ok, d, c) in checks if not ok]
    return {
        "stage": name,
        "status": STAGE_OK if not failing else STAGE_FAILED,
        "checks_run": len(checks),
        "failures": [{"check": n, "detail": d, "failure_code": c}
                     for (n, d, c) in failing][:12],
        "failure_codes": sorted({c for (_n, _d, c) in failing if c}),
    }


def _origination_gate(adapter_record):
    """Decide -- and record -- whether this run may be called caller-originated.

    Kept as its own stage rather than an inline flag because it is the single
    claim most worth being able to audit later. A reader must be able to see that
    the question was ASKED, and see the answer, without reading the runner.
    """
    origination = ADP.origination_of(adapter_record)
    caller_originated = ADP.is_caller_originated(adapter_record)
    verdict = ADP.caller_provenance_verdict(adapter_record)
    return {
        "stage": "origination",
        "status": STAGE_OK,
        "origination": origination,
        "caller_originated": caller_originated,
        "provenance_verdict": verdict,
        "detail": (
            "this run IS caller-originated; the request came from outside "
            "WorldForge" if caller_originated else
            "this run is NOT caller-originated: the consumer is a "
            "WorldForge-authored demonstration, so no artifact from this run "
            "may be presented as a caller's request (WF1288)"),
    }


def _read_source(mod):
    """Return the consumer module's source text, or None if it cannot be read.

    None is deliberate and honest: the scanner reports unsupplied source as NOT
    CHECKED rather than as clean, so a module we could not open must not silently
    become a passing scan.
    """
    path = getattr(mod, "__file__", None)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def run_consumer(consumer_id):
    mod = importlib.import_module("consumers." + consumer_id)

    adapter_record = mod.adapter()
    profile = mod.profile()
    catalog = mod.catalog()
    request = mod.request()
    policy = mod.policy()
    criteria = mod.criteria()

    stages = [
        _origination_gate(adapter_record),
        _stage("adapter", ADP.validate_adapter(adapter_record, strict=True)),
        # The source TEXT is read and handed over, not the path: passing None
        # would be reported as NOT CHECKED, and a report quoting a never-read
        # scan is indistinguishable from one quoting a real result.
        _stage("adapter_no_generation_logic",
               ADP.validate_adapter_has_no_generation_logic(
                   adapter_record,
                   _read_source(mod),
                   module_name="consumers." + consumer_id)),
        _stage("consumer_profile", CP.validate_consumer_profile(profile, strict=True)),
        _stage("asset_catalog", AC.validate_asset_catalog(catalog, strict=True)),
        _stage("world_request", WR.validate_world_request(request, strict=True)),
        _stage("revision_policy", RP.validate_revision_policy(policy, strict=True)),
        _stage("acceptance_criteria",
               ACR.validate_acceptance_criteria(criteria, strict=True)),
        _stage("constraint_set", K.validate_constraint_set(
            request["constraints"], strict=True)),
    ]

    # The constraint taxonomy, as this consumer actually uses it. Reported
    # because it is the cheapest way to see that two consumers really do differ
    # in KIND and not only in wording.
    by_class = {}
    for c in request["constraints"]:
        by_class[c["constraint_class"]] = by_class.get(c["constraint_class"], 0) + 1
    load_bearing = [c for c in request["constraints"]
                    if c["constraint_class"] in K.ACCEPTANCE_LOAD_BEARING]

    # With nothing observed yet, every load-bearing constraint is UNKNOWN and the
    # fold must be UNKNOWN -- never SATISFIED. This is asserted rather than
    # assumed: a pre-observation fold that came back satisfied would mean the
    # pipeline could accept a world before looking at one.
    pre_fold = K.fold_acceptance([(c, tri.UNKNOWN) for c in load_bearing])
    stages.append({
        "stage": "pre_observation_fold",
        "status": STAGE_OK if pre_fold == tri.UNKNOWN else STAGE_FAILED,
        "fold": pre_fold,
        "detail": ("with nothing observed, acceptance folds to {} -- a fold of "
                   "SATISFIED here would mean the pipeline can accept a world "
                   "before observing one".format(pre_fold)),
    })

    failed = [s for s in stages if s["status"] == STAGE_FAILED]
    return {
        "report_type": REPORT_TYPE,
        "consumer_id": consumer_id,
        "adapter_id": adapter_record.get("adapter_id"),
        "request_id": request.get("request_id"),
        "caller_originated": ADP.is_caller_originated(adapter_record),
        "profile_shape": {
            "game_type": profile.get("game_type"),
            "visual_language": profile.get("visual_language"),
            "camera_mode": (profile.get("camera_metrics") or {}).get("camera_mode"),
            "locomotion_modes": profile.get("locomotion_modes"),
            "extent_m2": (request.get("environment") or {}).get("extent_m2"),
            "density_class": (request.get("population") or {}).get("density_class"),
            "rollback_granularity": (policy.get("rollback") or {}).get(
                "rollback_granularity"),
            "unknown_handling": criteria.get("unknown_handling"),
        },
        "constraint_classes": dict(sorted(by_class.items())),
        "load_bearing_count": len(load_bearing),
        "stages": stages,
        "stages_failed": len(failed),
        "green": not failed,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--consumer", required=True,
                   help="consumer id -- a package under tools/consumers/")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", default=None, help="write the JSON report here")
    args = p.parse_args(argv)

    report = run_consumer(args.consumer)

    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("consumer flow -- {}".format(report["consumer_id"]))
        print("  request           : {}".format(report["request_id"]))
        print("  caller-originated : {}".format(report["caller_originated"]))
        sh = report["profile_shape"]
        print("  profile           : {} / {} / {} / {}".format(
            sh["game_type"], sh["visual_language"], sh["camera_mode"],
            sh["rollback_granularity"]))
        print("  extent m2         : {}   density: {}".format(
            sh["extent_m2"], sh["density_class"]))
        print("  constraints       : {}".format(report["constraint_classes"]))
        print("")
        for s in report["stages"]:
            print("  [{:6}] {:32} {}".format(
                s["status"].upper(), s["stage"],
                ("codes " + ",".join(s["failure_codes"]))
                if s.get("failure_codes") else ""))
            for f in s.get("failures", [])[:3]:
                print("           - {}: {}".format(f["check"], f["detail"][:110]))
        print("")
        print("  FLOW {}".format("GREEN" if report["green"] else "RED"))

    return 0 if report["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
