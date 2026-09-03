#!/usr/bin/env python3
"""validate_pcg_execution.py -- binding a PCG graph is not running one.

WHAT WAS ACTUALLY PROVEN, AND WHAT WAS NOT
------------------------------------------
``tools/unreal/create_slice_map.py`` spawns a real ``PCGVolume``, finds its
``PCGComponent``, binds the graph, and records ``pcg_graph_bound`` and
``pcg_kind`` into its slice report. 121 slice reports carry
``pcg_graph_bound: true`` / ``pcg_kind: "PCGVolume"`` and none carry ``false``.
That is real, and it is a WIRING fact.

``tools/unreal/validate_slice.py`` then checks three things: that an actor
carries the ``wf_pcg`` tag, that its ``wf_pcg_graph`` tag STRING equals the
expected graph path, and that its ``wf_placement_da`` tag STRING equals the
expected data-asset path. All three are tag comparisons -- and the tags are
written by ``create_slice_map.py``. Writer and reader are the same pipeline, so
the check cannot fail for any reason that matters.

Nothing anywhere counts what the graph PRODUCED. A grep for
``pcg_generat|pcg_points|pcg_instance`` across ``tools/`` and
``procedural/reports`` returns nothing. So the honest state is: PCG binding is
verified 121 times, PCG execution is verified zero times, and the difference was
invisible because "bound" reads like "working".

WHAT CLEARS THIS GATE
---------------------
A measured generation result, read back FROM the component after generation, in
a ``pcg_execution`` block on the slice report:

    "pcg_execution": {
      "generated": true,          # generate() was actually invoked
      "point_count": 1043,        # points the graph produced
      "instance_count": 1043,     # instances that exist afterwards
      "method": "...",            # how the number was obtained
      "measured_at_utc": "..."
    }

``point_count`` of zero is a legitimate measurement and PASSES the "was it
measured" question -- a graph that ran and produced nothing is a real result,
and reporting it as unmeasured would conflate "we looked and saw none" with "we
never looked". Those are different facts and this module keeps them different.
A separate check flags a zero yield as a warning so it stays visible without
being called a measurement failure.

HONEST LIMIT
------------
This gate reads the slice report. It does not itself open the editor, so it
proves the measurement was TAKEN and recorded, not that the recorded number is
truthful. A caller that writes a false count has it read as measured -- the same
limit ``observation_intake`` declares for its own readers.

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_pcg_execution.py

Writes: procedural/reports/slices/validate_pcg_execution/
        validate_pcg_execution_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

SLICE_REPORT_GLOB = "procedural/reports/slices/*/*/create_map_report.json"

EXECUTION_BLOCK = "pcg_execution"
# What a measured generation result must record. "generated" alone is a claim;
# a count is the measurement. "method" forces the writer to say HOW it knows,
# which is what separates a readback from a restated intent.
EXECUTION_REQUIRED = ("generated", "point_count", "method", "measured_at_utc")

REPORT_REL = Path("procedural") / "reports" / "slices" / "validate_pcg_execution"


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover
        return None, "slice report unparseable: {}".format(exc)


def check_slice(rep, slice_id, data):
    def c(name, ok, detail="", code=FailureCode.PCG_EXECUTION_UNMEASURED,
          warn_only=False):
        return rep.check("{}::{}".format(slice_id, name), ok, detail,
                         code=code, warn_only=warn_only)

    bound = data.get("pcg_graph_bound")
    if not bound:
        # No PCG was bound here, so there is no execution to measure. Genuinely
        # not applicable -- recorded, not silently passed.
        rep.skip("{}::pcg_execution_measured".format(slice_id),
                 "slice records pcg_graph_bound={!r}; no PCG binding, so there "
                 "is nothing to have executed".format(bound))
        return

    block = data.get(EXECUTION_BLOCK)
    if not isinstance(block, dict) or not block:
        c("pcg_execution_measured", False,
          "slice reports pcg_graph_bound=true and pcg_kind={!r} but carries no "
          "'{}' block. Binding is a wiring fact: the volume exists and the "
          "graph is referenced. It says nothing about whether the graph ran or "
          "produced anything. The tag checks in validate_slice.py compare "
          "strings that create_slice_map.py wrote, so they cannot answer this "
          "either.".format(data.get("pcg_kind"), EXECUTION_BLOCK))
        return

    missing = [k for k in EXECUTION_REQUIRED if block.get(k) in (None, "")]
    if not c("pcg_execution_complete", not missing,
             "{} block missing {}".format(EXECUTION_BLOCK, missing)):
        return

    c("pcg_execution_ran", bool(block.get("generated")),
      "{}.generated is {!r}: the graph was bound but generation was never "
      "invoked".format(EXECUTION_BLOCK, block.get("generated")))

    count = block.get("point_count")
    c("pcg_point_count_is_a_number", isinstance(count, int) and count >= 0,
      "{}.point_count is {!r}; a measurement is a non-negative integer, and a "
      "string or null is a claim".format(EXECUTION_BLOCK, count))

    # A measured zero is a real result, not a failure to measure. Kept visible
    # as a warning so it cannot quietly become the normal case.
    if isinstance(count, int):
        c("pcg_yield_non_zero", count > 0,
          "{}.point_count is 0: the graph ran and produced nothing. This IS a "
          "measurement (not an absence), so it does not fail the measured "
          "check -- but a scatter graph yielding zero is usually a "
          "misconfiguration".format(EXECUTION_BLOCK),
          warn_only=True)


def validate(strict):
    rep = ValidationReport("pack", "slices", strict=strict)
    n = 0
    for path in sorted(REPO_ROOT.glob(SLICE_REPORT_GLOB)):
        data, err = _load(path)
        slice_id = data.get("slice_id") if isinstance(data, dict) else None
        slice_id = slice_id or path.parent.name
        if data is None:
            rep.check("{}::loads".format(slice_id), False, err,
                      code=FailureCode.PCG_EXECUTION_UNMEASURED)
            continue
        check_slice(rep, slice_id, data)
        n += 1
    if n == 0:
        rep.skip("slice_reports_discovered",
                 "no slice reports matched {}; this gate proved NOTHING about "
                 "PCG execution (not passed, not failed)".format(SLICE_REPORT_GLOB))
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Require a MEASURED PCG generation result, not a binding tag.")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-pcg-execution", pack="slices",
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / REPORT_REL, "validate_pcg_execution_report.json")
    rep.print_summary("validate-pcg-execution")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
