#!/usr/bin/env python3
"""test_closed_loop -- the loop's decision logic, tested without an editor.

The loop's live behaviour is proven by running it. What that cannot prove is
that its JUDGEMENTS are right, because a live run only exercises the paths that
happened to occur. The functions here decide what a run MEANS -- which terminal
state a caller is told, which targets a repair may touch, whether an absence was
detected -- and every one of them is pure, so every one of them can be put under
a fixture that makes it decide the wrong thing.

The assertion that matters most is the terminal-state mapping. A run that
stopped after materialising left content in the world; calling that ``rejected``
tells a reader "a check failed, try again", when the truth is "go and look,
something is in your world that no contract describes". Those send a person to
different places, and only one of them is safe.
"""

import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import run_closed_loop_proof as CL     # noqa: E402
from pipeline import wf_build as WB                  # noqa: E402
from wfcore.acceptance import evaluate as EV         # noqa: E402
from wfcore.transaction import delta as TD           # noqa: E402

_FAILS = []
_N = [0]


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))


def _loop(green=False, stopped=None, ok_phases=(), verdict=None):
    return {"green": green, "stopped_at": stopped, "verdict": verdict,
            "phases": [{"phase": p, "ok": True} for p in ok_phases]
            + ([{"phase": stopped, "ok": False}] if stopped else [])}


def _bound(ex=1000.0, ey=1000.0, ox=0.0, oy=0.0):
    return {"origin_x_cm": ox, "origin_y_cm": oy,
            "extent_x_cm": ex, "extent_y_cm": ey}


# --------------------------------------------------------------------------- #
def test_terminal_state_mapping():
    ok, _r = WB._classify(_loop(green=True))
    check("green_is_accepted", ok == EV.OUTCOME_ACCEPTED, ok)

    # THE ONE THAT MATTERS. Stopped after materialising => content is in the
    # world that no completed contract describes.
    for stopped in ("repair", "resurvey", "destroy", "rebuild", "equivalence"):
        o, r = WB._classify(_loop(stopped=stopped,
                                  ok_phases=("materialise", "compare")))
        check("stopped_at_{}_is_partial_commit".format(stopped),
              o == EV.OUTCOME_PARTIAL_COMMIT, (o, r))
        check("stopped_at_{}_is_not_rejected".format(stopped),
              o != EV.OUTCOME_REJECTED)

    # Stopped BEFORE anything was authored => refused, not rejected: nothing
    # about the world was established either way.
    for stopped in ("intake", "anchors", "plan", "request"):
        o, _r = WB._classify(_loop(stopped=stopped))
        check("stopped_at_{}_is_refused".format(stopped),
              o == EV.OUTCOME_REFUSED, o)

    o, r = WB._classify(_loop(stopped="ownership"))
    check("ownership_escalates_as_refused", o == EV.OUTCOME_REFUSED, o)
    check("ownership_reason_says_escalated", "escalat" in r.lower(), r)

    o, _r = WB._classify(_loop(stopped="materialise", verdict="plumbing_only"))
    check("plumbing_only_is_indeterminate", o == EV.OUTCOME_INDETERMINATE, o)

    o, _r = WB._classify(None)
    check("unreadable_report_is_refused", o == EV.OUTCOME_REFUSED, o)

    # A cleaned-up run that still failed late is a plain rejection: the world was
    # returned, so nothing is left for anyone to go and find.
    o, _r = WB._classify(_loop(stopped="equivalence",
                               ok_phases=("materialise", "compare", "cleanup")))
    check("cleaned_up_failure_is_rejected", o == EV.OUTCOME_REJECTED, o)

    _vocab = {getattr(EV, n) for n in dir(EV) if n.startswith("OUTCOME_")}
    check("no_bare_success_in_the_vocabulary", "success" not in _vocab, _vocab)
    check("vocabulary_has_five_states", len(_vocab) == 5, _vocab)


def test_containment_blockers_are_coordinates():
    inside = {"/M:a": {"location": [0.0, 0.0, 0.0]}}
    outside = {"/M:b": {"location": [9999.0, 0.0, 0.0]}}
    check("inside_is_not_a_blocker",
          CL._containment_blockers(inside, _bound()) == [])
    check("outside_is_a_blocker",
          CL._containment_blockers(outside, _bound()) == ["out_of_bounds::/M:b"])

    # Unreadable is neither silently in nor silently out.
    junk = {"/M:c": {"location": "over there"}}
    check("unreadable_location_is_flagged_not_skipped",
          CL._containment_blockers(junk, _bound()) == ["unreadable::/M:c"])
    check("missing_payload_is_flagged",
          CL._containment_blockers({"/M:d": None}, _bound())
          == ["unreadable::/M:d"])
    check("empty_world_yields_no_blockers",
          CL._containment_blockers({}, _bound()) == [])

    # The bound must actually be consulted -- same point, different extent.
    pt = {"/M:e": {"location": [400.0, 0.0, 0.0]}}
    check("bound_extent_changes_the_verdict",
          CL._containment_blockers(pt, _bound(1000.0, 1000.0)) == []
          and CL._containment_blockers(pt, _bound(100.0, 100.0)) != [])


def test_ownership_refusal():
    prot = ["/Game/Maps/M:Sacred", "/Game/Maps/Other"]
    check("exact_path_collides",
          CL._ownership_refusal(["/Game/Maps/M:Sacred"], prot)
          == ["/Game/Maps/M:Sacred"])
    check("actor_in_a_protected_package_collides",
          CL._ownership_refusal(["/Game/Maps/Other:thing"], prot)
          == ["/Game/Maps/Other:thing"])
    check("unrelated_path_does_not_collide",
          CL._ownership_refusal(["/Game/Maps/M:ours"], prot) == [])
    check("no_declaration_means_no_collision",
          CL._ownership_refusal(["/Game/Maps/M:ours"], []) == [])
    check("blank_declarations_are_ignored_not_matched",
          CL._ownership_refusal(["/Game/Maps/M:ours"], ["", "   "]) == [])


def test_deleted_targets_come_from_the_record(tmp):
    """Drives the REAL function. The first version of this test rebuilt the
    filter inline and asserted against its own copy -- which proves Python can
    compare strings, not that the shipped function distinguishes an applied
    delete from a planned one. That is the exact tautology this repository's
    own helpers warn about, so it is written the other way round now."""
    check("no_far_side_means_no_claim",
          CL._deleted_targets({"far_side_document": None}) == set())

    far = os.path.join(tmp, "far.json")
    with open(far, "w", encoding="utf-8") as fh:
        json.dump({"delta": {"mutations": [
            {"target_path": "/M:gone", "status": "applied",
             "operation": "delete"},
            {"target_path": "/M:planned", "status": "planned",
             "operation": "delete"},
            {"target_path": "/M:moved", "status": "applied",
             "operation": "modify"},
            {"target_path": "/M:failed", "status": "apply_failed",
             "operation": "delete"},
        ]}}, fh)

    got = CL._deleted_targets({"far_side_document": far})
    check("applied_delete_is_reported", "/M:gone" in got, got)
    check("planned_delete_is_NOT_reported", "/M:planned" not in got, got)
    check("applied_modify_is_NOT_reported", "/M:moved" not in got, got)
    check("failed_delete_is_NOT_reported", "/M:failed" not in got, got)
    check("exactly_one_removal_claimed", got == {"/M:gone"}, got)

    bad = os.path.join(tmp, "bad.json")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    check("unreadable_far_side_claims_nothing",
          CL._deleted_targets({"far_side_document": bad}) == set())


def test_destroy_request_declares_the_observed_state():
    apply_req = {
        "bounds": [{"step_id": "s", "allowed_packages": ["/Game/Maps/M"],
                    "allowed_actors": ["/Game/Maps/M:a"],
                    "schema_version": TD.RT_MUTATION_BOUND}],
        "mutations": [{"mutation_id": "m0", "step_id": "s",
                       "provider_id": "p", "target_path": "/Game/Maps/M:a",
                       "rollback_mode": "compensating"}],
    }
    observed = {"/Game/Maps/M:a": {"actor_class": "StaticMeshActor",
                                   "location": [1.0, 2.0, 3.0],
                                   "rotation": [0.0, 0.0, 0.0],
                                   "scale": [1.0, 1.0, 1.0]}}
    req = CL._destroy_request(apply_req, observed, "op_d")
    check("one_delete_per_observed_target", len(req["mutations"]) == 1)
    m = req["mutations"][0]
    check("operation_is_delete", m["operation"] == TD.OP_DELETE)
    check("before_state_is_the_OBSERVED_payload",
          m["before_state"]["payload"] == observed["/Game/Maps/M:a"],
          m["before_state"])
    check("expects_absent_after", m["expected_after_state"]["state_kind"]
          == TD.STATE_ABSENT)
    check("bound_step_matches_mutation_step",
          req["bounds"][0]["step_id"] == m["step_id"])

    # A target with no observation is DROPPED, not guessed at: a delete whose
    # before-state was invented has no restore point.
    req2 = CL._destroy_request(apply_req, {}, "op_d")
    check("unobserved_target_is_not_deleted", req2["mutations"] == [],
          req2["mutations"])


def test_transform_request_is_bounded_to_its_targets():
    observed = {"/M:a": {"actor_class": "C", "location": [0.0, 0.0, 0.0],
                         "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
                "/M:b": {"actor_class": "C", "location": [1.0, 0.0, 0.0],
                         "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}}
    req = CL._transform_request("op", "step_r", ["/M:a"], observed,
                                {"/M:a": [5.0, 5.0, 5.0]})
    check("only_the_named_target_is_mutated",
          [m["target_path"] for m in req["mutations"]] == ["/M:a"])
    # The bound is rebuilt from the targets, NOT inherited: a repair whose bound
    # still admits every actor the first pass could reach is not bounded.
    check("bound_admits_only_the_target",
          req["bounds"][0]["allowed_actors"] == ["/M:a"],
          req["bounds"][0]["allowed_actors"])
    check("bystander_is_absent_from_the_bound",
          "/M:b" not in req["bounds"][0]["allowed_actors"])
    check("new_location_is_the_expected_after",
          req["mutations"][0]["expected_after_state"]["payload"]["location"]
          == [5.0, 5.0, 5.0])
    check("before_state_is_what_was_observed",
          req["mutations"][0]["before_state"]["payload"]["location"]
          == [0.0, 0.0, 0.0])


def test_build_request_validation_refuses_what_it_cannot_guess():
    base = {"schema_version": WB.RT_BUILD_REQUEST, "request_id": "r",
            "consumer": "c", "consumer_path": "/p", "caller_artifacts": "/a",
            "subject_map": "/Game/Maps/M", "route_anchors": ["x", "y"],
            "actor_class": "StaticMeshActor"}
    errs, _w = WB.validate_build_request(base)
    check("complete_request_validates", not errs, errs)

    for field in ("request_id", "consumer", "subject_map", "actor_class"):
        bad = dict(base)
        del bad[field]
        e, _w = WB.validate_build_request(bad)
        check("missing_{}_is_refused".format(field), bool(e), field)

    for anchors in ([], ["only"], ["a", "b", "c"], "ab", None):
        bad = dict(base, route_anchors=anchors)
        e, _w = WB.validate_build_request(bad)
        check("bad_anchors_{!r}_refused".format(anchors)[:44], bool(e))

    e, _w = WB.validate_build_request(dict(base, actor_class="  "))
    check("blank_actor_class_refused", bool(e))

    e, _w = WB.validate_build_request(dict(base, sneaky="do this too"))
    check("unknown_field_refused", bool(e), e)

    e, _w = WB.validate_build_request(dict(base, schema_version="v0"))
    check("wrong_schema_version_refused", bool(e))

    _e, w = WB.validate_build_request(base)
    check("missing_mesh_warns_about_invisible_actors",
          any("static_mesh" in x for x in w), w)
    check("missing_project_warns", any("project" in x for x in w), w)


def main():
    tmp = tempfile.mkdtemp(prefix="wf_loop_")
    try:
        test_deleted_targets_come_from_the_record(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for fn in (test_terminal_state_mapping,
               test_containment_blockers_are_coordinates,
               test_ownership_refusal,
               test_destroy_request_declares_the_observed_state,
               test_transform_request_is_bounded_to_its_targets,
               test_build_request_validation_refuses_what_it_cannot_guess):
        fn()
    if _FAILS:
        print("test_closed_loop: {} passed, {} FAILED".format(_N[0], len(_FAILS)))
        for f in _FAILS:
            print("  - {}".format(f))
        return 1
    print("test_closed_loop: {} assertion(s) passed, 0 failed".format(_N[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
