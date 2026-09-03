#!/usr/bin/env python3
"""test_route_placement_provider -- prove the generator refuses, contains, repeats.

The happy path is the least interesting thing here and gets the least space. What
these assertions are actually defending:

  * a plan asked for against an unmeasured anchor REFUSES -- and the refusal
    carries no placements, so a caller that reads the list and ignores the flag
    still materialises nothing
  * containment is decided by COORDINATES. The dedicated case puts a placement on
    a permitted asset path but outside the planar extent, which is precisely the
    combination path-list containment cannot see
  * an unsatisfiable exclusion escalates instead of being nudged away quietly
  * output is byte-identical across repeats, including when the inputs are
    rebuilt from scratch and when the caller mutates its own input afterwards
"""

import copy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import route_placement_provider as RP    # noqa: E402
from wfcore.providers import base as PB                # noqa: E402
from wfcore.transaction import delta as TD             # noqa: E402

_FAILS = []
_N = [0]


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))


# A 2000cm straight run along +X, centred on the origin. Chosen so the
# arithmetic is checkable by hand: 3 markers land at -500, 0, +500.
def _anchors(a=(-1000.0, 0.0, 0.0), b=(1000.0, 0.0, 0.0)):
    return [{"anchor_id": "anchor.start", "location_cm": list(a)},
            {"anchor_id": "anchor.end", "location_cm": list(b)}]


def _bound(ex=4000.0, ey=4000.0, ox=0.0, oy=0.0):
    return {"origin_x_cm": ox, "origin_y_cm": oy,
            "extent_x_cm": ex, "extent_y_cm": ey}


def _valid(plan):
    return [c for c in RP.validate_placement_plan(plan, strict=True) if not c[1]]


# --------------------------------------------------------------------------- #
def test_spacing_is_arithmetic_we_can_check():
    plan = RP.plan_route_placements(_anchors(), 3, _bound())
    check("accepted", not plan["refused"], plan.get("refusal_reason"))
    check("count_matches", len(plan["placements"]) == 3,
          len(plan["placements"]))
    xs = [p["location_cm"][0] for p in plan["placements"]]
    check("evenly_spaced_interior", xs == [-500.0, 0.0, 500.0], xs)
    check("route_length_measured", plan["route_length_cm"] == 2000.0,
          plan["route_length_cm"])
    check("endpoints_not_occupied",
          all(x not in (-1000.0, 1000.0) for x in xs), xs)
    check("plan_validates", not _valid(plan), _valid(plan))


def test_refuses_unobserved_anchor():
    for bad in (None, "unknown", [0, 0], [0, 0, float("nan")],
                [0, 0, float("inf")]):
        a = _anchors()
        a[1]["location_cm"] = bad
        plan = RP.plan_route_placements(a, 3, _bound())
        check("refuses_anchor_{!r}".format(bad)[:44], plan["refused"],
              "accepted a plan against location {!r}".format(bad))
        check("refusal_is_empty_{!r}".format(bad)[:44],
              plan["placements"] == [], plan["placements"])
        check("refusal_names_wf1292_{!r}".format(bad)[:44],
              "WF1292_CORE_PLACEMENT_ANCHOR_UNOBSERVED" in plan["failure_codes"],
              plan["failure_codes"])
        # The validator must independently agree the refusal is well-formed.
        check("refusal_validates_{!r}".format(bad)[:44], not _valid(plan),
              _valid(plan))

    missing = [{"anchor_id": "only.one", "location_cm": [0.0, 0.0, 0.0]}]
    check("refuses_single_anchor",
          RP.plan_route_placements(missing, 2, _bound())["refused"])


def test_containment_is_coordinate_math_not_path_membership():
    # The route runs far outside a small extent. Path-list containment would be
    # perfectly satisfied here -- the asset path is on the allowed list -- and
    # only a coordinate test can notice the geometry is wrong.
    tiny = _bound(ex=100.0, ey=100.0)
    plan = RP.plan_route_placements(_anchors(), 3, tiny)
    check("out_of_extent_refuses", plan["refused"], plan.get("refusal_reason"))
    check("out_of_extent_names_wf1294",
          "WF1294_CORE_PLACEMENT_OUT_OF_BOUNDS" in plan["failure_codes"],
          plan["failure_codes"])

    # An offset origin must move the verdict: same route, bound recentred away.
    offset = _bound(ex=1000.0, ey=1000.0, ox=50000.0)
    check("offset_origin_refuses",
          RP.plan_route_placements(_anchors(), 3, offset)["refused"])

    # And the positive control: a bound that genuinely contains the route.
    ok = RP.plan_route_placements(_anchors(), 3, _bound())
    check("containing_bound_accepts", not ok["refused"])
    check("every_placement_carries_a_coordinate_proof",
          all(p["containment"]["method"] == "coordinate_comparison"
              and p["containment"]["inside"] is True
              for p in ok["placements"]))

    inside, _d = RP.within_planar_bound([0.0, 0.0, 0.0], _bound(100.0, 100.0))
    outside, _d = RP.within_planar_bound([500.0, 0.0, 0.0], _bound(100.0, 100.0))
    check("within_planar_bound_positive", inside)
    check("within_planar_bound_negative", not outside)


def test_exclusion_slide_then_escalate():
    # A small exclusion sitting on the middle marker: a short slide clears it.
    small = [{"exclusion_id": "ex.small", "center_cm": [0.0, 0.0, 0.0],
              "radius_cm": 100.0}]
    plan = RP.plan_route_placements(_anchors(), 3, _bound(), exclusions=small)
    check("small_exclusion_is_survivable", not plan["refused"],
          plan.get("refusal_reason"))
    mid = [p for p in plan["placements"] if p["index"] == 2][0]
    check("middle_marker_moved", mid["slid_cm"] > 0, mid["slid_cm"])
    check("middle_marker_now_clear",
          abs(mid["location_cm"][0]) > 100.0, mid["location_cm"])
    check("slide_stayed_within_budget",
          mid["slid_cm"] <= RP.DEFAULT_MAX_SLIDE_CM, mid["slid_cm"])

    # An exclusion swallowing the whole route cannot be escaped, and the planner
    # must say so rather than placing the marker anyway or dropping it.
    huge = [{"exclusion_id": "ex.huge", "center_cm": [0.0, 0.0, 0.0],
             "radius_cm": 100000.0}]
    ref = RP.plan_route_placements(_anchors(), 3, _bound(), exclusions=huge)
    check("unsatisfiable_exclusion_refuses", ref["refused"])
    check("unsatisfiable_names_wf1295",
          "WF1295_CORE_PLACEMENT_EXCLUSION_UNSATISFIABLE" in ref["failure_codes"],
          ref["failure_codes"])
    check("unsatisfiable_drops_no_markers_silently", ref["placements"] == [])

    # THE BUDGET CASE, and it is here because mutation testing caught its
    # absence: the "huge exclusion" above escalates because the whole route is
    # swallowed, so removing the slide budget entirely still passed it. This
    # exclusion is escapable -- but only by sliding FURTHER than the budget
    # allows. It is the one fixture that fails if the bound stops being enforced.
    escapable_but_far = [{"exclusion_id": "ex.wide", "center_cm": [0.0, 0.0, 0.0],
                          "radius_cm": 600.0}]
    tight = RP.plan_route_placements(_anchors(), 3, _bound(),
                                     exclusions=escapable_but_far,
                                     max_slide_cm=200.0)
    check("budget_too_small_escalates", tight["refused"],
          "slid past a 200cm budget to clear a 600cm exclusion")
    check("budget_refusal_names_wf1295",
          "WF1295_CORE_PLACEMENT_EXCLUSION_UNSATISFIABLE"
          in tight["failure_codes"], tight["failure_codes"])

    # ...and the same exclusion with a budget that genuinely suffices must be
    # accepted, or the case above would pass for a provider that refuses always.
    roomy = RP.plan_route_placements(_anchors(), 3, _bound(),
                                     exclusions=escapable_but_far,
                                     max_slide_cm=900.0)
    check("sufficient_budget_succeeds", not roomy["refused"],
          roomy.get("refusal_reason"))
    mid2 = [p for p in roomy["placements"] if p["index"] == 2][0]
    check("cleared_the_wide_exclusion", abs(mid2["location_cm"][0]) > 600.0,
          mid2["location_cm"])


def test_determinism():
    base = RP.canonical(RP.plan_route_placements(_anchors(), 5, _bound()))
    for i in range(4):
        again = RP.canonical(RP.plan_route_placements(_anchors(), 5, _bound()))
        check("repeat_{}_is_byte_identical".format(i), again == base)

    # Inputs rebuilt from scratch, in fresh objects: catches any accidental
    # dependence on object identity or on a mutated input.
    fresh_anchors = [dict(a) for a in _anchors()]
    fresh = RP.canonical(RP.plan_route_placements(fresh_anchors, 5,
                                                  dict(_bound())))
    check("fresh_objects_identical", fresh == base)

    # The planner must not mutate what it was handed.
    handed = _anchors()
    snapshot = copy.deepcopy(handed)
    RP.plan_route_placements(handed, 5, _bound())
    check("planner_does_not_mutate_its_input", handed == snapshot, handed)

    # Different input must give different output, or "identical" proves nothing.
    other = RP.canonical(RP.plan_route_placements(_anchors(), 6, _bound()))
    check("different_count_differs", other != base)
    moved = RP.canonical(RP.plan_route_placements(
        _anchors(b=(2000.0, 0.0, 0.0)), 5, _bound()))
    check("different_anchors_differ", moved != base)


def test_transaction_request_shape():
    plan = RP.plan_route_placements(_anchors(), 3, _bound())
    req, errs = RP.build_transaction_request(
        plan, operation_id="op_test_0001", step_id="step_place",
        target_package="/Game/Maps/TestMap", actor_prefix="marker",
        actor_class="StaticMeshActor")
    check("request_built", req is not None and not errs, errs)
    check("has_all_four_keys",
          set(req) == {"operation_id", "bounds", "mutations", "evidence_refs"},
          sorted(req))
    check("mutation_per_placement", len(req["mutations"]) == 3)
    check("evidence_refs_nonempty", bool(req["evidence_refs"]))

    # The sink's own validators must accept it -- that is the whole point of
    # generating this shape rather than a convenient one.
    for b in req["bounds"]:
        bad = [c for c in TD.validate_mutation_bound(b, strict=True) if not c[1]]
        check("bound_validates", not bad, bad)
    for m in req["mutations"]:
        bad = [c for c in TD.validate_mutation(m, strict=False) if not c[1]]
        check("mutation_validates", not bad, bad)
        check("mutation_is_planned", m["status"] == TD.MUT_PLANNED)
        check("create_expects_absent_before",
              m["operation"] != TD.OP_CREATE
              or m["before_state"].get("state_kind") == TD.STATE_ABSENT,
              m["before_state"])

    # THE EXECUTOR'S OWN PARSER must accept every address. The delta validators
    # check the shape of a mutation record; they say nothing about the grammar of
    # the address inside it, and a generator that emits an unparseable address
    # passes every schema gate and then dies at request validation. Found exactly
    # that way -- by running the sink, not by reading it.
    from pipeline import run_wfcore_transaction as TX
    for m in req["mutations"]:
        pkg, label, err = TX.parse_actor_address(m["target_path"])
        check("sink_parses_target_address", err is None, (m["target_path"], err))
        check("address_names_the_target_package", pkg == "/Game/Maps/TestMap", pkg)
        check("address_carries_a_label", bool(label), label)
    errs2, _warns = TX.validate_request(req)
    check("sink_accepts_the_whole_request", not errs2, errs2)

    # Every mutated actor must be inside the bound it ships with.
    allowed = set(req["bounds"][0]["allowed_actors"])
    check("every_target_is_in_its_own_bound",
          all(m["target_path"] in allowed for m in req["mutations"]))

    # A refused plan must yield NO request.
    # WorldForge must not choose the caller's content: no actor_class, no request.
    noclass, ec = RP.build_transaction_request(
        plan, "op", "step", "/Game/Maps/TestMap", "marker")
    check("missing_actor_class_refuses", noclass is None, noclass)
    check("missing_actor_class_explains", bool(ec) and "actor_class" in ec[0], ec)
    for blank in ("", "   ", None):
        nb, _e = RP.build_transaction_request(
            plan, "op", "step", "/Game/Maps/TestMap", "marker", actor_class=blank)
        check("blank_actor_class_refuses_{!r}".format(blank)[:40], nb is None)

    # The payload must be the SINK's grammar, not this module's internal names.
    for m in req["mutations"]:
        pl = (m["expected_after_state"] or {}).get("payload") or {}
        check("payload_has_actor_class", pl.get("actor_class") == "StaticMeshActor", pl)
        check("payload_uses_sink_keys",
              set(pl) == {"actor_class", "location", "rotation", "scale"}, sorted(pl))
        check("payload_location_is_finite_xyz",
              isinstance(pl.get("location"), list) and len(pl["location"]) == 3,
              pl.get("location"))

    refused = RP.plan_route_placements([], 3, _bound())
    r2, e2 = RP.build_transaction_request(
        refused, "op", "step", "/Game/Maps/TestMap", "marker",
        actor_class="StaticMeshActor")
    check("refused_plan_yields_no_request", r2 is None, r2)
    check("refused_plan_explains_itself", bool(e2))


def test_validator_catches_a_lying_plan():
    good = RP.plan_route_placements(_anchors(), 3, _bound())

    lying = copy.deepcopy(good)
    lying["refused"] = True
    lying["refusal_reason"] = "nope"
    lying["failure_codes"] = ["WF1293_CORE_PLACEMENT_PLAN_INVALID"]
    names = {c[0] for c in RP.validate_placement_plan(lying) if not c[1]}
    check("refusal_with_placements_is_caught",
          "route_placement.refusal_carries_no_placements" in names, names)

    short = copy.deepcopy(good)
    short["placements"] = short["placements"][:1]
    names = {c[0] for c in RP.validate_placement_plan(short) if not c[1]}
    check("undercount_is_caught",
          "route_placement.count_matches_request" in names, names)

    forged = copy.deepcopy(good)
    forged["placements"][0]["containment"] = {"inside": True,
                                              "method": "path_membership"}
    names = {c[0] for c in RP.validate_placement_plan(forged) if not c[1]}
    check("path_membership_is_not_a_containment_proof",
          any("containment_proved" in n for n in names), names)

    uncoded = copy.deepcopy(good)
    uncoded.update({"refused": True, "placements": [], "failure_codes": []})
    names = {c[0] for c in RP.validate_placement_plan(uncoded) if not c[1]}
    check("refusal_without_a_code_is_caught",
          "route_placement.refusal_names_a_code" in names, names)


def test_declaration_is_valid_and_honest():
    d = RP.declaration()
    bad = [c for c in PB.validate_provider_declaration(d, strict=True)
           if not c[1]]
    check("declaration_validates", not bad, bad)
    check("declares_scatter_capability",
          PB.CAP_PROCEDURAL_SCATTER in d["capabilities"], d["capabilities"])
    check("claims_no_rollback_because_it_mutates_nothing",
          d["rollback"] == PB.ROLLBACK_NONE, d["rollback"])
    check("determinism_claim_is_backed",
          d["determinism"] == PB.DET_SEEDED and bool(d.get("determinism_evidence")))
    check("declares_limitations", len(d["limitations"]) >= 1)


def main():
    for fn in (test_spacing_is_arithmetic_we_can_check,
               test_refuses_unobserved_anchor,
               test_containment_is_coordinate_math_not_path_membership,
               test_exclusion_slide_then_escalate,
               test_determinism,
               test_transaction_request_shape,
               test_validator_catches_a_lying_plan,
               test_declaration_is_valid_and_honest):
        fn()

    if _FAILS:
        print("test_route_placement_provider: {} passed, {} FAILED".format(
            _N[0], len(_FAILS)))
        for f in _FAILS:
            print("  - {}".format(f))
        return 1
    print("test_route_placement_provider: {} assertion(s) passed, "
          "0 failed".format(_N[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
