#!/usr/bin/env python3
"""pcg_scatter_provider.py -- PCG scatter as a BOUNDED, MEASURABLE world mutation.

WHY THIS ONE IS REIMPLEMENTED AND NOT ADAPTED
---------------------------------------------
The asset lanes (textures, materials, meshes) are adapted behind the Core seam
by ``asset_lane_provider.py``, because an asset something else references cannot
be un-created honestly -- so they carry ``rollback=none`` and refusal is their
only safety mechanism.

A PCG volume is the opposite case. It is an ACTOR. The transaction sink can
un-spawn an actor, which means this lane CAN have a real compensating rollback,
and a lane that can be rolled back should be run through the thing that rolls it
back. That is the whole split: adapt what cannot be undone, reimplement what can.

WHAT THE OLD LANE PROVED, AND WHAT IT DID NOT
---------------------------------------------
``tools/unreal/create_slice_map.py`` spawns a ``PCGVolume``, binds a graph, and
tags the actor. ``tools/unreal/validate_slice.py`` then checks those tags -- and
the tags are written by ``create_slice_map.py``, so writer and reader are the
same pipeline and the check cannot fail for any reason that matters. 121 slice
reports carry ``pcg_graph_bound: true``; none carries a count of anything the
graph produced. Binding is a wiring fact. Execution is a number.

So this provider refuses to emit a plan that cannot say HOW its yield will be
measured. ``yield_observation_key`` is required, not defaulted (WF1273): a plan
whose success condition cannot be checked is a plan with no success condition,
and the previous lane is what that looks like after 121 runs.

DETERMINISM
-----------
The volume transform is pure arithmetic over the declared region -- centre is
the midpoint, extent is the span, coordinates rounded to a fixed number of
decimals. There is no RNG in this module and no dependence on traversal order,
so two runs over the same region emit byte-identical documents. The scatter
INSIDE the graph is PCG's business and this provider makes no determinism claim
about it -- which is why the declaration says stable_within_environment rather
than deterministic_given_seed.

WHAT THE LIVE RUN PROVED, AND WHAT IT DID NOT
---------------------------------------------
``op_pcg_live_0001`` is a real editor boot (exit 0, 10.65s) in which the sink
took this provider's request unchanged, spawned ``PCGVolume_0`` into
``/Game/Maps/_wf_test_lvl``, re-observed it, and reported
``outcome=committed verification=satisfied`` with zero refusals.

That proves the MUTATION path: a PCG volume is an actor, the sink can place it
inside a bound, and it can compensate by deleting it. It does NOT prove a
scatter happened -- see ``lim_graph_not_bound_by_the_sink``. The volume arrives
with no graph attached, because the sink payload has no key to attach one with.
Both facts belong in the same paragraph, because the run is exactly the kind of
green that would otherwise be read as the stronger claim.

Usage:
    cd tools && PYTHONUTF8=1 python pipeline/pcg_scatter_provider.py --demo
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.failure import FailureCode as C          # noqa: E402
from wfcore.providers import base as PB              # noqa: E402
from wfcore.transaction import delta as TD           # noqa: E402

PROVIDER_ID = "pcg_scatter_planner"
RT_PCG_PLAN = "wf.core.pcg_scatter_plan.v1"

# The actor class the sink spawns. Caller-owned in principle, but a PCG volume
# is the only class this plan shape describes, so it is named rather than
# defaulted silently.
PCG_VOLUME_CLASS = "PCGVolume"

_COORD_DECIMALS = 3

# A region smaller than this in any axis cannot hold a meaningful scatter and is
# far more likely to be a unit error than an intent. Declared, not discovered.
MIN_EXTENT_CM = 100.0


def _r(v):
    return round(float(v) + 0.0, _COORD_DECIMALS)


def plan_pcg_scatter(region, graph_path, yield_observation_key,
                     expected_min_points=None):
    """Plan one PCG scatter volume over ``region``.

    ``region`` is {min: [x,y,z], max: [x,y,z]} in cm. Returns a plan document,
    never raises -- a refusal is a value, so a caller that ignores the flag
    still materialises nothing (``build_transaction_request`` refuses too).
    """
    plan = {
        "schema_version": RT_PCG_PLAN,
        "report_type": RT_PCG_PLAN,
        "provider_id": PROVIDER_ID,
        "graph_path": graph_path,
        "yield_observation_key": yield_observation_key,
        "expected_min_points": expected_min_points,
        "volume": None,
        "postconditions": [],
        "refused": False,
        "refusal_reason": None,
        "failure_codes": [],
    }

    def refuse(reason, code=C.CORE_PLACEMENT_PLAN_INVALID):
        plan.update({"refused": True, "refusal_reason": reason, "volume": None,
                     "postconditions": []})
        if code not in plan["failure_codes"]:
            plan["failure_codes"].append(code)
        return plan

    if not isinstance(graph_path, str) or not graph_path.strip():
        return refuse("no PCG graph declared; a volume with no graph scatters "
                      "nothing and would still report as placed")

    # THE RAIL THIS MODULE EXISTS FOR. No default, no fallback.
    if not isinstance(yield_observation_key, str) or not yield_observation_key.strip():
        return refuse(
            "no yield_observation_key: this plan cannot state how its scatter "
            "will be MEASURED. Binding a graph to a volume proves the wiring, "
            "not the result -- 121 slices in this repository record "
            "pcg_graph_bound=true and not one records what the graph produced. "
            "A plan whose success condition cannot be checked has none",
            C.CORE_PCG_YIELD_UNMEASURABLE)

    if not isinstance(region, dict):
        return refuse("region must be an object with min and max")
    lo, hi = region.get("min"), region.get("max")
    if not (isinstance(lo, (list, tuple)) and isinstance(hi, (list, tuple))
            and len(lo) == 3 and len(hi) == 3):
        return refuse("region.min and region.max must each be three numbers")
    try:
        lo = [float(v) for v in lo]
        hi = [float(v) for v in hi]
    except (TypeError, ValueError):
        return refuse("region bounds must be numeric")

    extent = [hi[i] - lo[i] for i in range(3)]
    if any(e <= 0 for e in extent):
        return refuse("region.max must exceed region.min on every axis; got "
                      "extent {}".format(extent))
    if any(e < MIN_EXTENT_CM for e in extent[:2]):
        return refuse(
            "region is {}cm x {}cm; below the declared {}cm minimum this is far "
            "more likely a unit error than an intent, so it is refused rather "
            "than scattered into".format(_r(extent[0]), _r(extent[1]),
                                         MIN_EXTENT_CM))

    if expected_min_points is not None:
        if not isinstance(expected_min_points, int) or expected_min_points < 0:
            return refuse("expected_min_points must be a non-negative integer, "
                          "got {!r}".format(expected_min_points))

    plan["volume"] = {
        "actor_class": PCG_VOLUME_CLASS,
        "location": [_r((lo[i] + hi[i]) / 2.0) for i in range(3)],
        "rotation": [0.0, 0.0, 0.0],
        # UE brush volumes are 200cm cubes at scale 1, so scale is extent/200.
        # Stated here because a reader cannot otherwise tell whether the number
        # is a scale or a size.
        "scale": [_r(e / 200.0) for e in extent],
        "graph_path": graph_path,
    }
    post = {
        "observation_key": yield_observation_key,
        "comparator": "gte",
        "value": int(expected_min_points) if expected_min_points is not None else 1,
        "detail": "points the graph must actually produce, read back from the "
                  "component. NOT the bound flag and NOT an actor tag",
    }
    plan["postconditions"] = [post]
    return plan


def build_transaction_request(plan, operation_id, step_id, target_package,
                              actor_label, evidence_refs=None):
    """Turn a plan into the sink's {operation_id, bounds, mutations, evidence_refs}.

    Returns (request_or_None, errors).
    """
    errors = []
    if not isinstance(plan, dict):
        return None, ["plan must be an object"]
    if plan.get("refused"):
        return None, ["plan is refused ({}); nothing to run".format(
            plan.get("refusal_reason"))]
    if not plan.get("volume"):
        return None, ["plan carries no volume"]

    # One colon exactly -- the sink's address grammar. A slash here passes every
    # schema validator and is rejected by the executor at request-validation
    # time, because the delta validators check a mutation's SHAPE, not the
    # grammar of an address inside it.
    actor_path = "{}:{}".format(target_package.rstrip("/"), actor_label)

    bound = {
        "step_id": step_id,
        "allowed_packages": [target_package],
        "allowed_actors": [actor_path],
        "schema_version": TD.RT_MUTATION_BOUND,
    }

    vol = plan["volume"]
    payload = {
        "actor_class": vol["actor_class"],
        "location": list(vol["location"]),
        "rotation": list(vol["rotation"]),
        "scale": list(vol["scale"]),
    }
    mutation = {
        "mutation_id": "mut_{}".format(actor_label),
        "step_id": step_id,
        "provider_id": PROVIDER_ID,
        "target_kind": TD.TARGET_ACTOR,
        "target_path": actor_path,
        "operation": TD.OP_CREATE,
        "before_state": TD.absent_state(),
        "expected_after_state": TD.present_state(payload),
        "status": TD.MUT_PLANNED,
        # An actor CAN be un-spawned. That is why this lane goes through the
        # sink at all, and the claim is honest here in a way it would not be for
        # an asset.
        "rollback_mode": PB.ROLLBACK_COMPENSATING,
        "schema_version": TD.RT_MUTATION,
        "detail": "PCG volume bound to {}; yield measured via {}".format(
            vol["graph_path"], plan["yield_observation_key"]),
    }

    request = {
        "operation_id": operation_id,
        "bounds": [bound],
        "mutations": [mutation],
        "evidence_refs": list(evidence_refs or ["pcg_scatter_plan"]),
    }
    return request, errors


def validate_pcg_plan(plan, strict=False):
    """House-shape validator: List[(name, ok, detail, code)]."""
    checks = []

    def c(name, ok, detail="", code=C.CORE_PLACEMENT_PLAN_INVALID):
        checks.append((name, bool(ok), detail, None if ok else code))
        return ok

    if not isinstance(plan, dict):
        c("pcg_plan_is_object", False, "plan must be an object")
        return checks

    c("pcg_schema_version", plan.get("schema_version") == RT_PCG_PLAN,
      "schema_version must be {}".format(RT_PCG_PLAN))

    if plan.get("refused"):
        c("refusal_carries_no_volume", plan.get("volume") is None,
          "a refused plan must carry no volume, or a caller reading the volume "
          "and ignoring the flag would materialise one anyway")
        c("refusal_carries_no_postconditions", not plan.get("postconditions"),
          "a refused plan must declare no postconditions")
        c("refusal_names_a_code", bool(plan.get("failure_codes")),
          "a refusal must name why")
        return checks

    c("yield_key_present", bool(plan.get("yield_observation_key")),
      "an accepted plan must name the observation that measures its yield",
      C.CORE_PCG_YIELD_UNMEASURABLE)
    post = plan.get("postconditions") or []
    c("postcondition_present", len(post) == 1,
      "expected exactly one yield postcondition, got {}".format(len(post)),
      C.CORE_PCG_YIELD_UNMEASURABLE)
    if post:
        c("postcondition_names_the_same_key",
          post[0].get("observation_key") == plan.get("yield_observation_key"),
          "the postcondition must measure the key the plan declared")
        c("postcondition_threshold_is_a_number",
          isinstance(post[0].get("value"), int),
          "a threshold that is not a number cannot be compared to a count")

    vol = plan.get("volume") or {}
    c("volume_present", bool(vol), "an accepted plan must carry a volume")
    if vol:
        c("volume_scale_positive",
          all(isinstance(v, float) and v > 0 for v in vol.get("scale", [])),
          "scale must be positive on every axis, got {}".format(vol.get("scale")))
        c("volume_class_declared", vol.get("actor_class") == PCG_VOLUME_CLASS,
          "actor_class must be {}".format(PCG_VOLUME_CLASS))
    return checks


def declaration():
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_ID,
        capabilities=[PB.CAP_PROCEDURAL_SCATTER],
        requirements=[
            PB._example_requirement(
                requirement_id="req_pcg_graph_asset",
                requirement_kind=PB.REQ_INPUT_ARTIFACT,
                subject="pcg_graph",
                observation_key=None,
                detail="the human-owned PCG graph this volume binds. An agent "
                       "cannot author the graph .uasset; no graph, no scatter"),
        ],
        side_effects=[PB._example_side_effect(
            effect_id="eff_pcg_plan_only",
            effect_kind=PB.EFFECT_EVIDENCE_ONLY,
            scope="evidence.pcg_scatter_plan",
            reversible=True,
            detail="computes a volume transform and emits a plan plus a "
                   "transaction request. It writes nothing into the world; the "
                   "sink does, under its own bound and its own rollback")],
        determinism=PB.DET_ENV_DEPENDENT,
        rollback=PB.ROLLBACK_NONE,
        outputs=["pcg_scatter_plan", "transaction_request"],
        evidence=["pcg_scatter_plan"],
        limitations=[
            PB._example_limitation(
                limitation_id="lim_yield_is_pcg_business",
                limitation_kind="coverage_unknown",
                detail="the volume transform is this provider's; what the graph "
                       "scatters inside it is PCG's. No determinism claim is "
                       "made about the scatter itself, only about the volume"),
            PB._example_limitation(
                limitation_id="lim_requires_declared_measurement",
                limitation_kind="input_shape",
                detail="refuses a plan with no yield_observation_key. It cannot "
                       "be used by a caller unwilling to say how the result "
                       "will be counted"),
            PB._example_limitation(
                limitation_id="lim_graph_not_bound_by_the_sink",
                limitation_kind="coverage_unknown",
                detail="FOUND BY A LIVE RUN (op_pcg_live_0001). The sink's "
                       "payload vocabulary is {actor_class, location, rotation, "
                       "scale} plus optional static_mesh and material -- there "
                       "is no key that binds a PCG graph. So the volume this "
                       "plan materialises is spawned and verified, but arrives "
                       "with NO graph attached, and the yield postcondition it "
                       "declares therefore cannot be satisfied by the sink path "
                       "alone. Binding needs an optional caller-declared "
                       "pcg_graph payload key, added the same way static_mesh "
                       "and material were. Declared rather than worked around: "
                       "a provider whose success condition is unreachable must "
                       "say so, not let a green transaction imply otherwise"),
            PB._example_limitation(
                limitation_id="lim_single_volume",
                limitation_kind="scale",
                detail="plans one volume per call. A region needing several is "
                       "several calls, so each carries its own bound"),
        ],
        description="a bounded, rollback-capable PCG scatter volume whose plan "
                    "must declare how its yield is measured")
    # DET_ENV_DEPENDENT, so the rail does not require evidence -- and the
    # example's placeholder would be a claim about a suite that does not exist.
    d.pop("determinism_evidence", None)
    d["cost_profile"] = {"wall_seconds": 0.1, "operator_attention": 0.0}
    return d


def canonical(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan a bounded PCG scatter volume.")
    ap.add_argument("--demo", action="store_true",
                    help="plan over a sample region and print the plan + request")
    args = ap.parse_args(argv)
    if not args.demo:
        ap.print_help()
        return 0
    plan = plan_pcg_scatter(
        region={"min": [-4000.0, -4000.0, 0.0], "max": [4000.0, 4000.0, 800.0]},
        graph_path="/Game/Procedural/PCG/PCG_FoliageScatter",
        yield_observation_key="pcg.demo_region.point_count",
        expected_min_points=50)
    print(json.dumps(plan, indent=2, sort_keys=True))
    req, errs = build_transaction_request(
        plan, operation_id="op_pcg_demo", step_id="step_pcg",
        target_package="/Game/Maps/_wf_test_lvl", actor_label="wfpcg_demo")
    print(json.dumps({"request": req, "errors": errs}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
