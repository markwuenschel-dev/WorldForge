#!/usr/bin/env python3
"""wfcore_shield.py -- the single gate for WorldForge Core.

Runs every Core suite plus the two structural gates, in one command, and refuses
to report green on anything it did not actually observe.

    cd tools && PYTHONUTF8=1 python wfcore_shield.py
    cd tools && PYTHONUTF8=1 python wfcore_shield.py --json

WHY A SHIELD AND NOT "run the tests"
------------------------------------
Core's suites are per-package, and per-package suites are individually easy to
forget. More importantly, two of Core's guarantees are not test suites at all --
game-agnosticism (``wfcore.hygiene``) and the untouched-Core boundary
(``core_boundary_proof``) -- and a green test run says nothing about either. A
single gate is what makes "Core is healthy" one checkable claim.

THE DISCOVERY RULE, AND WHY IT IS NOT A LIST
--------------------------------------------
Suites are DISCOVERED (``wfcore/**/test_*.py``), never enumerated in a constant.
A hardcoded list fails open in the worst way: add a package, forget the list, and
the shield goes green while covering less than it did yesterday -- silently, and
with a passing exit code that reads as reassurance.

Because discovery can also find nothing, the shield fails when it discovers ZERO
suites, and prints the count on every run. A gate that examined nothing must
never be indistinguishable from a gate that examined everything and was
satisfied.

EXIT CODES
----------
0 green, 1 a gate failed, 2 the shield could not run a gate at all (which is
NOT green -- an un-runnable gate is an unknown, and unknowns do not pass).
"""

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
CORE_ROOT = os.path.join(_HERE, "wfcore")
# Scratch inputs for the closed-loop plumbing gate. Regenerated every run rather
# than committed: a fixture that drifts from the reader it exercises turns a gate
# into decoration.
PLUMBING_DIR = os.path.join(_HERE, "..", "procedural", "reports", "core",
                            "closed_loop")
PLUMBING_FIXTURES = os.path.join(PLUMBING_DIR, "plumbing_fixtures")
PLUMBING_OUT = os.path.join(PLUMBING_DIR, "closed_loop_plumbing_report.json")


def _ensure_plumbing_fixtures():
    """Two caller-shaped observation artifacts, written fresh each run."""
    import json as _json
    os.makedirs(PLUMBING_FIXTURES, exist_ok=True)
    for name, sid, xyz in (("a.json", "route.start", (-1200.0, 0.0, 100.0)),
                           ("b.json", "route.end", (1200.0, 400.0, 100.0))):
        with open(os.path.join(PLUMBING_FIXTURES, name), "w",
                  encoding="utf-8") as fh:
            _json.dump({"subject_id": sid, "status": "resolved",
                        "anchor_mode": "actor_object_path",
                        "created_at": "2026-01-01T00:00:00Z",
                        "transform": {"location": {"x": xyz[0], "y": xyz[1],
                                                   "z": xyz[2]}}}, fh, indent=1)

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_ERROR = "error"


def discover_suites(core_root: str = CORE_ROOT) -> List[str]:
    """Every ``test_*.py`` under Core, as dotted module paths, sorted."""
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(core_root):
        dirnames[:] = [d for d in dirnames
                       if d != "__pycache__" and not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("test_") and fn.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, fn), _HERE)
                mod = rel.replace("\\", "/")[:-3].replace("/", ".")
                out.append(mod)
    return sorted(out)


def _run(label: str, argv: List[str]) -> Dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=_HERE, env=env,
                              capture_output=True, text=True, timeout=900)
    except Exception as exc:  # noqa: BLE001
        return {"gate": label, "status": STATUS_ERROR, "returncode": None,
                "detail": "could not run: {}: {}".format(type(exc).__name__, exc),
                "seconds": round(time.time() - started, 2)}
    tail = (proc.stdout or "").strip().splitlines()
    return {
        "gate": label,
        "status": STATUS_PASS if proc.returncode == 0 else STATUS_FAIL,
        "returncode": proc.returncode,
        "detail": tail[-1] if tail else (proc.stderr or "").strip()[-200:],
        "seconds": round(time.time() - started, 2),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--json", action="store_true", help="emit the report as JSON")
    p.add_argument("--baseline", default=None,
                   help="Core boundary baseline manifest; when given, the "
                        "boundary proof is run against it")
    p.add_argument("--probe-environment", action="store_true",
                   help="re-take the live plugin-environment observation with a "
                        "real editor boot (~40s) instead of grading the "
                        "committed one; the GRADING always runs either way")
    args = p.parse_args(argv)

    py = sys.executable
    results: List[Dict[str, Any]] = []

    suites = discover_suites()
    for mod in suites:
        results.append(_run(mod, [py, "-m", mod]))

    results.append(_run("wfcore.hygiene", [py, "-m", "wfcore.hygiene"]))

    # UNCONDITIONAL, not flag-gated. These police conditions that drift silently
    # between runs -- the plugin environment, and external-tool capability claims
    # -- and a gate you have to remember to ask for is one a future agent will
    # not ask for. "Six commands pass" is weaker than "the one shield fails when
    # any of these drifts", because only the second survives being forgotten.
    #
    # The environment gate grades the COMMITTED observation and refuses when the
    # plugin-descriptor fingerprint has moved since it was taken, so it cannot go
    # green on stale evidence. --probe-environment re-takes it with a live boot
    # (~40s), which is why the boot itself is opt-in and the GRADING is not.
    env_argv = [py, "pipeline/validate_execution_environment.py"]
    if args.probe_environment:
        env_argv.append("--probe")
    results.append(_run("validate_execution_environment", env_argv))
    results.append(_run("validate_external_tool_providers",
                        [py, "pipeline/validate_external_tool_providers.py"]))
    # Caller provenance attestation. Registered here rather than left to
    # discovery because it is not a wfcore.* package suite: it exercises a
    # pipeline resolver that reads real git repositories, and a rail nothing
    # runs is a rail nobody notices breaking.
    # These two were documented gates that no shield ran -- they were executed
    # by hand, which means a regression in them was noticed only when somebody
    # remembered to look. The sink is the most safety-critical file in the
    # repository; leaving its 189 checks outside the shield made every "GATE
    # GREEN" quieter than it sounded.
    results.append(_run("test_wfcore_unreal_sink",
                        [py, "pipeline/test_wfcore_unreal_sink.py"]))
    results.append(_run("test_consumer_flow",
                        [py, "pipeline/test_consumer_flow.py"]))
    results.append(_run("test_caller_attestation",
                        [py, "pipeline/test_caller_attestation.py"]))
    # The generation provider: determinism, coordinate containment, and the
    # refusal-rather-than-default rail. Registered for the same reason as
    # above -- it is a pipeline module, not a wfcore.* package suite.
    results.append(_run("test_route_placement_provider",
                        [py, "pipeline/test_route_placement_provider.py"]))
    # The observation reader: the three-state separation, and the rails that
    # stop a caller-declared mapping from stating a value it did not measure.
    results.append(_run("test_observation_intake",
                        [py, "pipeline/test_observation_intake.py"]))
    results.append(_run("test_build_manifest",
                        [py, "pipeline/test_build_manifest.py"]))
    results.append(_run("test_closed_loop",
                        [py, "pipeline/test_closed_loop.py"]))
    # The closed-loop proof's WIRING, without an editor. This gate can only say
    # "the seams still connect": its report carries verdict=plumbing_only and
    # green=false precisely so that a green shield is never mistaken for a live
    # closed-loop proof, which needs an editor and is run separately.
    _ensure_plumbing_fixtures()
    results.append(_run("closed_loop_plumbing",
                        [py, "pipeline/run_closed_loop_proof.py",
                         "--caller-artifacts", PLUMBING_FIXTURES,
                         "--subject-start", "route.start",
                         "--subject-end", "route.end",
                         "--map", "/Game/Maps/_wf_shield_plumbing",
                         "--actor-class", "StaticMeshActor", "--no-live",
                         "--out", PLUMBING_OUT]))

    if args.baseline:
        results.append(_run("core_boundary_proof",
                            [py, "core_boundary_proof.py", "verify",
                             "--baseline", args.baseline]))

    # A discovery that found nothing is a FAILURE, not an empty success.
    discovery_ok = len(suites) > 0
    failed = [r for r in results if r["status"] != STATUS_PASS]

    report = {
        "report_type": "wf.core.shield_report.v1",
        "suites_discovered": len(suites),
        "gates_run": len(results),
        "gates_failed": len(failed),
        "discovery_ok": discovery_ok,
        "results": results,
        "green": discovery_ok and not failed,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("WorldForge Core shield")
        print("  suites discovered : {}".format(len(suites)))
        print("")
        for r in results:
            mark = {STATUS_PASS: "PASS", STATUS_FAIL: "FAIL",
                    STATUS_ERROR: "ERROR"}[r["status"]]
            print("  [{:5}] {:44} {:>6}s  {}".format(
                mark, r["gate"], r["seconds"], r["detail"][:70]))
        print("")
        if not discovery_ok:
            print("  GATE RED -- discovered ZERO Core suites. A shield that "
                  "examined nothing must never read as green.")
        else:
            print("  GATE {}".format("GREEN" if not failed else "RED"))

    if not discovery_ok:
        return 2
    if any(r["status"] == STATUS_ERROR for r in results):
        return 2
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
