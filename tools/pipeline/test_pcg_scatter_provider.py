#!/usr/bin/env python3
"""test_pcg_scatter_provider -- prove the yield rail fires, and that the sink
accepts what this provider emits without being changed to suit it.

What these assertions defend:

  * A plan with no ``yield_observation_key`` is REFUSED (WF1273). This is the
    rail the module exists for: the previous PCG lane bound a graph, tagged the
    actor, and never counted anything, and 121 slice reports say
    pcg_graph_bound=true while none says what the graph produced.
  * A refusal carries no volume and no postconditions, so a caller that reads
    the volume and ignores the flag still materialises nothing.
  * The emitted request is accepted by ``run_wfcore_transaction.validate_request``
    UNCHANGED. If the sink had to be modified to take it, the seam would not be
    a seam.
  * The mutation claims ``compensating`` rollback -- honest here precisely
    because a PCG volume is an ACTOR, which is the whole reason this lane is
    reimplemented through the sink instead of adapted around it.
  * Mutation test on the yield rail itself: defeat it and the refusal must stop
    happening. Otherwise the refusal assertion could be passing for some other
    reason entirely.
"""

import copy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import pcg_scatter_provider as P        # noqa: E402
from pipeline import run_wfcore_transaction as TX     # noqa: E402
from wfcore.failure import FailureCode as C           # noqa: E402
from wfcore.providers import base as PB               # noqa: E402
from wfcore.transaction import delta as TD            # noqa: E402

_FAILS = []
_N = [0]

GOOD_REGION = {"min": [-4000.0, -4000.0, 0.0], "max": [4000.0, 4000.0, 800.0]}
GRAPH = "/Game/Procedural/PCG/PCG_FoliageScatter"
YIELD_KEY = "pcg.test_region.point_count"


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))
    return ok


def _good_plan(**over):
    kw = dict(region=copy.deepcopy(GOOD_REGION), graph_path=GRAPH,
              yield_observation_key=YIELD_KEY, expected_min_points=50)
    kw.update(over)
    return P.plan_pcg_scatter(**kw)


# --------------------------------------------------------------------------- #
# the rail this module exists for
# --------------------------------------------------------------------------- #
def test_missing_yield_key_is_refused():
    for bad in (None, "", "   "):
        plan = _good_plan(yield_observation_key=bad)
        if not check("yield_key_{!r}_refused".format(bad), plan["refused"],
                     "a plan that cannot say how its scatter is measured was "
                     "ACCEPTED; binding is not execution"):
            continue
        check("yield_key_{!r}_names_wf1273".format(bad),
              C.CORE_PCG_YIELD_UNMEASURABLE in plan["failure_codes"],
              "refusal must name WF1273, got {}".format(plan["failure_codes"]))


def test_yield_rail_is_not_tautological():
    """MUTATION: defeat the yield check and the refusal must stop happening."""
    real = P.plan_pcg_scatter

    def mutated(region, graph_path, yield_observation_key, expected_min_points=None):
        # supply a key the caller did not: exactly the "harmless default" this
        # rail refuses to have
        return real(region, graph_path, yield_observation_key or "defaulted.key",
                    expected_min_points)

    plan = mutated(copy.deepcopy(GOOD_REGION), GRAPH, None, 50)
    check("mutation_defeats_yield_rail", not plan["refused"],
          "with a default supplied the plan STILL refused, so the real "
          "assertion is not testing the yield rail")


def test_refusal_is_inert():
    plan = _good_plan(yield_observation_key=None)
    check("refusal_has_no_volume", plan["volume"] is None,
          "a refused plan carrying a volume can still be materialised by a "
          "caller that reads the volume and ignores the flag")
    check("refusal_has_no_postconditions", not plan["postconditions"],
          "a refused plan must promise nothing")
    req, errs = P.build_transaction_request(
        plan, "op_x", "step_x", "/Game/Maps/_wf_test_lvl", "wfpcg_x")
    check("refused_plan_yields_no_request", req is None and bool(errs),
          "build_transaction_request must refuse a refused plan; got req={!r} "
          "errs={!r}".format(req, errs))


# --------------------------------------------------------------------------- #
# region validation
# --------------------------------------------------------------------------- #
def test_bad_regions_refused():
    cases = {
        "inverted": {"min": [0.0, 0.0, 0.0], "max": [-10.0, -10.0, -10.0]},
        "degenerate": {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]},
        "sub_minimum": {"min": [0.0, 0.0, 0.0], "max": [10.0, 10.0, 10.0]},
        "not_an_object": [1, 2, 3],
        "short_vector": {"min": [0.0, 0.0], "max": [1.0, 1.0]},
        "non_numeric": {"min": ["a", 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
    }
    for name, region in cases.items():
        plan = _good_plan(region=region)
        check("region_{}_refused".format(name), plan["refused"],
              "a {} region was ACCEPTED".format(name))


def test_negative_expected_points_refused():
    check("negative_expectation_refused",
          _good_plan(expected_min_points=-5)["refused"],
          "a negative yield expectation was accepted")
    check("non_int_expectation_refused",
          _good_plan(expected_min_points="lots")["refused"],
          "a non-integer yield expectation was accepted")


# --------------------------------------------------------------------------- #
# the happy path, and the seam
# --------------------------------------------------------------------------- #
def test_plan_is_valid_and_measurable():
    plan = _good_plan()
    check("plan_accepted", not plan["refused"],
          "refused: {}".format(plan.get("refusal_reason")))
    bad = [c for c in P.validate_pcg_plan(plan, strict=True) if not c[1]]
    check("plan_validates", not bad,
          "validator rejected its own plan: {}".format([(c[0], c[2]) for c in bad]))
    post = plan["postconditions"][0]
    check("postcondition_names_declared_key",
          post["observation_key"] == YIELD_KEY,
          "postcondition must measure the key the caller declared")
    check("postcondition_is_a_count", isinstance(post["value"], int),
          "a threshold that is not a number cannot be compared to a count")


def test_determinism():
    a, b = _good_plan(), _good_plan()
    check("repeat_is_byte_identical", P.canonical(a) == P.canonical(b),
          "two plans over the same region differed")
    c_ = _good_plan(region={"min": [-2000.0, -2000.0, 0.0],
                            "max": [2000.0, 2000.0, 400.0]})
    check("different_region_differs", P.canonical(a) != P.canonical(c_),
          "a different region produced an identical plan, so the region is not "
          "actually reaching the output")


def test_sink_accepts_request_unchanged():
    plan = _good_plan()
    req, errs = P.build_transaction_request(
        plan, "op_pcg_t", "step_pcg", "/Game/Maps/_wf_test_lvl", "wfpcg_t")
    check("request_built", req is not None and not errs, "errors: {}".format(errs))
    if req is None:
        return
    errors, _warnings = TX.validate_request(req)
    check("sink_accepts_unchanged", not errors,
          "the sink REJECTED this provider's request: {}. If the sink must be "
          "changed to accept a new provider, the seam is not a seam".format(errors))
    addr = TX.parse_actor_address(req["mutations"][0]["target_path"])
    check("address_grammar_parses", addr is not None and addr[0] and addr[1],
          "the sink could not parse the actor address {!r}; a slash here passes "
          "every schema validator and is rejected by the executor".format(
              req["mutations"][0]["target_path"]))


def test_mutation_claims_honest_rollback():
    plan = _good_plan()
    req, _errs = P.build_transaction_request(
        plan, "op_pcg_t", "step_pcg", "/Game/Maps/_wf_test_lvl", "wfpcg_t")
    m = req["mutations"][0]
    check("target_is_an_actor", m["target_kind"] == TD.TARGET_ACTOR,
          "a PCG volume is an actor; that is why this lane can be rolled back "
          "and therefore why it goes through the sink at all")
    check("rollback_is_compensating",
          m["rollback_mode"] == PB.ROLLBACK_COMPENSATING,
          "an actor CAN be un-spawned, so the compensating claim is honest here "
          "in a way it would not be for an asset")
    check("before_state_is_absent",
          m["before_state"] == TD.absent_state(),
          "a create must declare its before_state absent, or the isolation rail "
          "fires at apply time")


# --------------------------------------------------------------------------- #
# declaration
# --------------------------------------------------------------------------- #
def test_declaration_valid():
    d = P.declaration()
    bad = [c for c in PB.validate_provider_declaration(d, strict=True) if not c[1]]
    check("declaration_valid", not bad,
          "declaration rejected: {}".format([(c[0], c[2]) for c in bad]))
    check("no_stale_determinism_evidence", "determinism_evidence" not in d,
          "determinism is stable_within_environment, so the example's "
          "placeholder evidence would be a claim about a suite that does not "
          "exist")
    check("capability_is_scatter",
          d["capabilities"] == [PB.CAP_PROCEDURAL_SCATTER],
          "got {!r}".format(d["capabilities"]))


def main():
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)),
                     key=lambda f: f.__name__):
        fn()
    if _FAILS:
        print("test_pcg_scatter_provider: {} assertion(s) passed, {} FAILED"
              .format(_N[0], len(_FAILS)))
        for f in _FAILS:
            print("  FAIL {}".format(f))
        return 1
    print("test_pcg_scatter_provider: {} assertion(s) passed, 0 failed".format(_N[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
