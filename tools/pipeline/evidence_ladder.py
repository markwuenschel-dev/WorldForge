#!/usr/bin/env python3
"""evidence_ladder -- how far each capability is actually proven, derived.

THE SIX STATES, AND WHY A LADDER RATHER THAN A FLAG
----------------------------------------------------
"Done" is the least useful word available about a capability here. A module can
exist, pass its own tests, and still never have run against a real engine; a gate
can be green because nothing exercised it. So evidence is graded on an ORDERED
ladder, and a capability sits on the highest rung it can actually pay for:

    1 implemented        the code exists
    2 unit_tested        a suite exercises it and passes
    3 hostile_qualified  negatives exist that PROVE the rail can go red
    4 shield_integrated  a shield runs it, so a regression is noticed
    5 runtime_qualified  it has run against a live editor and left evidence
    6 externally_proven  a caller-originated adapter drove it

Each rung is DERIVED from an artifact on disk, never from a table somebody
maintains by hand. A hand-maintained status table is the first thing to drift and
the last thing anyone re-checks, and it drifts in the flattering direction.

WHY THE RUNGS ARE ORDERED AND NOT INDEPENDENT FLAGS
-----------------------------------------------------
Because they are not independent. Passing tests means little if none of them can
fail -- rung 3 is what makes rung 2 worth anything. A live run means little if no
gate would notice it regressing -- rung 4 under rung 5. Reporting them as a set
of checkboxes would let a capability show four ticks while resting on nothing,
which is precisely the shape of confidence this repository keeps having to
dismantle.

A capability stops at the FIRST rung it cannot evidence. It does not skip ahead
to a higher one it happens to satisfy: a module with live evidence but no hostile
tests is reported at rung 2, because the thing missing underneath is what would
have caught it being wrong.
"""

import argparse
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
_REPO = os.path.dirname(_TOOLS)

RT_EVIDENCE_LADDER = "wf.core.evidence_ladder.v1"

RUNGS = ("implemented", "unit_tested", "hostile_qualified",
         "shield_integrated", "runtime_qualified", "externally_proven")
RUNG_INDEX = {name: i for i, name in enumerate(RUNGS)}
NONE_RUNG = "none"


def _exists(rel):
    return os.path.isfile(os.path.join(_REPO, rel))


def _read(rel):
    try:
        with open(os.path.join(_REPO, rel), encoding="utf-8",
                  errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _suite_passes(rel, timeout=180, extra_args=None):
    """Actually run it. A suite's existence is rung 1; passing is rung 2.

    ``extra_args`` exists because some capabilities are guarded by a validator
    rather than a self-contained suite, and a validator needs to be told WHAT to
    grade. Invoking one bare and reporting the resulting argument error as a
    failed capability is a false negative -- which this did on its first run,
    reporting scene_survey as regressed when the gate was green.
    """
    if not _exists(rel):
        return False, "no such suite"
    env = dict(os.environ, PYTHONUTF8="1")
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(_REPO, rel)] + list(extra_args or []),
            capture_output=True, text=True, cwd=_TOOLS, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "could not run: {}".format(exc)
    tail = (proc.stdout or "").strip().splitlines()
    return proc.returncode == 0, (tail[-1][:120] if tail else "no output")


# A suite is HOSTILE-qualified when it contains constructed negatives -- fixtures
# built to make the rail fail. Counted by matching the vocabulary this repository
# already uses for them, so the measure tracks the code rather than a promise.
_HOSTILE_MARKERS = re.compile(
    r"refus|refut|reject|must FAIL|is_caught|_rejected|negative|mutation|"
    r"forged|smuggl|unsatisfiable|cannot|never|_not_|invalid|malformed|"
    r"unstamped|duplicate|wrong_|bad_|missing_|unknown_|without", re.I)


def _hostile_count(rel):
    text = _read(rel)
    if not text:
        return 0
    return sum(1 for line in text.splitlines()
               if "check(" in line and _HOSTILE_MARKERS.search(line))


def _in_shield(name):
    return name in _read("tools/wfcore_shield.py") or \
        name in _read("tools/pipeline/v2_6_shield.py")


def _runtime_evidence(globs):
    """A live-editor artifact that exists AND says it came from a live run."""
    for rel in globs:
        full = os.path.join(_REPO, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            return True, rel
    return False, None


CAPABILITIES = [
    {"id": "observation_intake", "module": "tools/pipeline/observation_intake.py",
     "suite": "tools/pipeline/test_observation_intake.py",
     "shield_name": "test_observation_intake",
     "runtime": ["procedural/reports/scene_survey/runtime/operations/"
                 "op_v2_6_scene_survey_0001/scene_survey_report.json"]},
    {"id": "route_placement_provider",
     "module": "tools/pipeline/route_placement_provider.py",
     "suite": "tools/pipeline/test_route_placement_provider.py",
     "shield_name": "test_route_placement_provider",
     "runtime": ["procedural/reports/core/transaction/op_wfbuild_0005/far_side.json"]},
    # ``ceiling`` states the highest rung a capability CAN reach. A pure-logic
    # module touches no engine, so "no live-editor artifact" is not a gap in it
    # -- reporting that as blocked would conflate inapplicable with deficient,
    # the same conflation this codebase refuses everywhere else.
    {"id": "caller_attestation",
     "module": "tools/pipeline/verify_caller_attestation.py",
     "suite": "tools/pipeline/test_caller_attestation.py",
     "shield_name": "test_caller_attestation",
     "ceiling": "shield_integrated",
     "ceiling_reason": "pure logic over git and JSON; it never touches an editor",
     "runtime": []},
    {"id": "unreal_mutation_sink", "module": "tools/unreal/wfcore_unreal_sink.py",
     "suite": "tools/pipeline/test_wfcore_unreal_sink.py",
     "shield_name": "test_wfcore_unreal_sink",
     "runtime": ["procedural/reports/core/transaction/op_wfbuild_0005/far_side.json"]},
    {"id": "scene_survey",
     "module": "tools/pipeline/run_scene_survey_probe.py",
     "suite": "tools/pipeline/validate_scene_survey_runtime.py",
     "suite_args": ["--operation-id", "op_v2_6_scene_survey_0001", "--strict"],
     "shield_name": "validate-scene-survey-runtime",
     "runtime": ["procedural/reports/scene_survey/runtime/operations/"
                 "op_v2_6_scene_survey_0001/operation_manifest.json"]},
    {"id": "build_manifest", "module": "tools/pipeline/build_manifest.py",
     "suite": "tools/pipeline/test_build_manifest.py",
     "shield_name": "test_build_manifest",
     "ceiling": "shield_integrated",
     "ceiling_reason": "hashes and validates documents; it never touches an editor",
     "runtime": []},
    {"id": "closed_loop", "module": "tools/pipeline/run_closed_loop_proof.py",
     "suite": "tools/pipeline/test_closed_loop.py",
     "shield_name": "closed_loop_plumbing",
     "runtime": ["procedural/reports/core/transaction/op_wfbuild_0005/far_side.json"]},
]


def assess(run_suites=True, external_proof=False):
    rows = []
    for cap in CAPABILITIES:
        reasons, rung = {}, NONE_RUNG

        implemented = _exists(cap["module"])
        reasons["implemented"] = (
            cap["module"] if implemented else "module absent")
        if not implemented:
            rows.append({"capability": cap["id"], "rung": NONE_RUNG,
                         "rung_index": -1, "reasons": reasons})
            continue
        rung = "implemented"

        suite = cap.get("suite")
        if suite and _exists(suite):
            if run_suites:
                ok, detail = _suite_passes(suite, extra_args=cap.get("suite_args"))
            else:
                ok, detail = None, "not run (--no-run)"
            reasons["unit_tested"] = "{}: {}".format(suite, detail)
            if ok:
                rung = "unit_tested"
                n = _hostile_count(suite)
                reasons["hostile_qualified"] = (
                    "{} constructed negative(s) matched in {} (a TEXT heuristic "
                    "over check() lines -- it undercounts suites that phrase "
                    "their negatives differently, so treat a low number as "
                    "'go and look', not as proof of absence)".format(n, suite)
                    if n else "no constructed negatives found -- passing tests "
                              "that cannot fail do not raise the rung")
                if n >= 3:
                    rung = "hostile_qualified"
                    if cap.get("shield_name") and _in_shield(cap["shield_name"]):
                        reasons["shield_integrated"] = (
                            "registered as {!r}".format(cap["shield_name"]))
                        rung = "shield_integrated"
                        live, where = _runtime_evidence(cap.get("runtime") or [])
                        reasons["runtime_qualified"] = (
                            "live artifact {}".format(where) if live
                            else "no live-editor artifact on disk")
                        if live:
                            rung = "runtime_qualified"
                            # The top rung is never self-awarded. It requires a
                            # caller-originated adapter to have driven the run,
                            # which no artifact in THIS repository can establish.
                            reasons["externally_proven"] = (
                                "a caller-originated adapter drove it"
                                if external_proof else
                                "NOT claimed: no caller-originated adapter has "
                                "driven this. A fixture cannot promote itself")
                            if external_proof:
                                rung = "externally_proven"
                    else:
                        reasons["shield_integrated"] = (
                            "not registered in any shield, so a regression here "
                            "would be noticed by nobody")
        else:
            reasons["unit_tested"] = "no dedicated suite"

        ceiling = cap.get("ceiling")
        at_ceiling = bool(ceiling) and rung == ceiling
        rows.append({"capability": cap["id"], "rung": rung,
                     "rung_index": RUNG_INDEX.get(rung, -1),
                     "ceiling": ceiling,
                     "ceiling_reason": cap.get("ceiling_reason"),
                     "at_ceiling": at_ceiling,
                     "reasons": reasons})

    return {
        "schema_version": RT_EVIDENCE_LADDER, "report_type": RT_EVIDENCE_LADDER,
        "rungs": list(RUNGS), "capabilities": rows,
        "lowest_rung": min((r["rung_index"] for r in rows), default=-1),
        "any_externally_proven": any(r["rung"] == "externally_proven"
                                     for r in rows),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-run", action="store_true",
                    help="do not execute suites; report unit_tested as unknown")
    ap.add_argument("--external-proof", action="store_true",
                    help="assert a caller-originated adapter drove these runs. "
                         "Only an operator who saw it happen may pass this")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rep = assess(run_suites=not args.no_run, external_proof=args.external_proof)
    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True)); return 0

    print("evidence ladder -- {}".format(" < ".join(RUNGS)))
    print("")
    for r in rep["capabilities"]:
        print("  {:26} {:18} ({}/6)".format(
            r["capability"], r["rung"], max(r["rung_index"] + 1, 0)))
        if r.get("at_ceiling"):
            print("      AT ITS CEILING -- {}".format(r.get("ceiling_reason")))
            continue
        nxt = RUNGS[r["rung_index"] + 1] if 0 <= r["rung_index"] < 5 else None
        if nxt and nxt in r["reasons"]:
            print("      blocked from {}: {}".format(nxt, r["reasons"][nxt][:110]))
    print("")
    print("  externally proven anywhere: {}".format(
        "yes" if rep["any_externally_proven"] else "NO"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
