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
    args = p.parse_args(argv)

    py = sys.executable
    results: List[Dict[str, Any]] = []

    suites = discover_suites()
    for mod in suites:
        results.append(_run(mod, [py, "-m", mod]))

    results.append(_run("wfcore.hygiene", [py, "-m", "wfcore.hygiene"]))

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
