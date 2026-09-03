#!/usr/bin/env python3
"""test_observation_intake -- prove the reader cannot be talked into a value.

Every artifact here is written by the suite into a temp directory. Pointing the
reader at somebody's real checkout would make the result a fact about that disk,
and would make the negative cases -- a corrupt file, a precondition that does not
hold, a value that is simply not there -- impossible to construct.

The assertions that carry the weight:

  * the three states stay separate. ``measured`` / ``not_observed`` /
    ``observation_failed`` answer different questions, and the collapse that
    matters is a FAILED artifact quietly becoming an absence
  * a mapping cannot supply, default, or compute a value, and cannot claim a
    provenance -- the vocabulary has no room for it and the rail says so
  * two entries cannot write one field. Caught late, by a demo rather than by
    design: uniqueness had been checked on the label instead of the address, so
    a failing entry silently overwrote a measured one purely by ordering
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

from pipeline import observation_intake as OI        # noqa: E402
from wfcore.models import observed_world as OW       # noqa: E402

_FAILS = []
_N = [0]


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))


def _write(root, name, doc):
    with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def _artifact(subject, status="resolved", x=1.0, y=2.0, z=3.0,
              created_at="2026-01-01T00:00:00Z", **over):
    d = {"subject_id": subject, "status": status, "created_at": created_at,
         "anchor_mode": "actor_object_path",
         "transform": {"location": {"x": x, "y": y, "z": z}}}
    d.update(over)
    return d


def _entry(key, subject, require=None, path=None, shape=None, field="location_cm"):
    e = {"observation_key": key, "section": "semantic_landmarks",
         "entity_id": subject, "field": field,
         "select": {"subject_id": subject},
         "value_path": path or ["transform", "location"],
         "value_shape": shape or OI.SHAPE_XYZ_OBJECT}
    if require:
        e["require"] = require
    return e


def _mapping(root, entries):
    return {"mapping_id": "m_test", "consumer_id": "c_test",
            "artifact_root": root, "artifact_glob": "*.json",
            "schema_version": OI.RT_OBSERVATION_MAPPING, "entries": entries}


def _states(root, entries):
    _m = _mapping(root, entries)
    _res = OI.read_observations(_m, "op_test")[0]
    return {r["entry"]["observation_key"]: r["state"] for r in _res}


# --------------------------------------------------------------------------- #
def test_three_states_stay_separate(tmp):
    _write(tmp, "a.json", _artifact("subj.present"))
    _write(tmp, "b.json", _artifact("subj.unresolved", status="unresolved"))

    st = _states(tmp, [
        _entry("k.measured", "subj.present", {"status": "resolved"}),
        _entry("k.absent", "subj.never.written", {"status": "resolved"}),
        _entry("k.failed", "subj.unresolved", {"status": "resolved"}),
    ])
    check("present_is_measured", st["k.measured"] == "measured", st)
    check("missing_is_not_observed", st["k.absent"] == "not_observed", st)
    # THE collapse that matters: an artifact exists and its precondition did not
    # hold. That is information, and it must not read as "nothing here".
    check("unmet_require_is_failed_not_absent",
          st["k.failed"] == "observation_failed", st)
    check("failed_is_distinct_from_absent",
          st["k.failed"] != st["k.absent"])


def test_value_must_be_literally_present(tmp):
    _write(tmp, "a.json", _artifact("s.nopath"))
    st = _states(tmp, [
        _entry("k.badpath", "s.nopath", path=["transform", "rotation"]),
        _entry("k.deep_missing", "s.nopath",
               path=["transform", "location", "w"], field="w"),
    ])
    check("absent_value_path_fails", st["k.badpath"] == "observation_failed", st)
    check("missing_leaf_fails", st["k.deep_missing"] == "observation_failed", st)

    # Nothing is substituted. The failed field must carry no value at all.
    res = OI.read_observations(
        _mapping(tmp, [_entry("k.badpath", "s.nopath",
                              path=["transform", "rotation"])]), "op")[0]
    check("failed_field_has_no_value", res[0]["field"].get("value") is None,
          res[0]["field"].get("value"))
    check("failed_field_is_unbacked",
          res[0]["field"]["provenance"] not in OW.BACKED_PROVENANCE)


def test_shape_is_checked_not_coerced(tmp):
    _write(tmp, "s.json", _artifact("s.shape"))
    _write(tmp, "t.json", {"subject_id": "s.str", "status": "resolved",
                           "transform": {"location": "over there"}})
    _write(tmp, "u.json", {"subject_id": "s.short", "status": "resolved",
                           "transform": {"location": [1.0, 2.0]}})

    st = _states(tmp, [
        _entry("k.wrongshape", "s.shape", shape=OI.SHAPE_NUMBER),
        _entry("k.stringloc", "s.str"),
        _entry("k.shortarray", "s.short", shape=OI.SHAPE_XYZ_ARRAY),
    ])
    check("object_read_as_number_fails",
          st["k.wrongshape"] == "observation_failed", st)
    check("string_read_as_xyz_fails", st["k.stringloc"] == "observation_failed", st)
    check("two_element_array_is_not_xyz",
          st["k.shortarray"] == "observation_failed", st)

    ok, val, _why = OI._coerce({"x": 1, "y": 2, "z": 3}, OI.SHAPE_XYZ_OBJECT)
    check("xyz_object_reads", ok and val == [1.0, 2.0, 3.0], val)
    ok2, _v2, _w2 = OI._coerce({"x": 1, "y": 2}, OI.SHAPE_XYZ_OBJECT)
    check("xyz_object_needs_all_three", not ok2)
    # A bool is not a number, however much Python disagrees.
    ok3, _v3, _w3 = OI._coerce(True, OI.SHAPE_NUMBER)
    check("bool_is_not_a_number", not ok3)


def test_mapping_cannot_state_a_value_or_provenance(tmp):
    for smuggle in ("value", "default", "provenance", "fallback", "compute",
                    "expression", "measured", "observed_by"):
        e = _entry("k", "s")
        e[smuggle] = "anything at all"
        names = {c[0] for c in OI.validate_observation_mapping(
            _mapping(tmp, [e])) if not c[1]}
        check("rejects_smuggled_{}".format(smuggle),
              any("declares_no_value_or_provenance" in n for n in names), names)
        codes = {c[3] for c in OI.validate_observation_mapping(
            _mapping(tmp, [e])) if not c[1]}
        check("smuggle_raises_wf1299_{}".format(smuggle),
              "WF1299_CORE_OBSERVATION_VALUE_FABRICATED" in codes, codes)

    # The reader set is closed: an unknown shape is refused, not improvised.
    bad = _entry("k", "s", shape="eval_this_python")
    names = {c[0] for c in OI.validate_observation_mapping(
        _mapping(tmp, [bad])) if not c[1]}
    check("unknown_value_shape_refused",
          any("value_shape_known" in n for n in names), names)

    # An empty selector would match everything, which measures nothing.
    empty = _entry("k", "s")
    empty["select"] = {}
    names = {c[0] for c in OI.validate_observation_mapping(
        _mapping(tmp, [empty])) if not c[1]}
    check("empty_selector_refused",
          any("select_is_nonempty_object" in n for n in names), names)


def test_two_entries_cannot_write_one_field(tmp):
    a = _entry("label.one", "s.dup", {"status": "resolved"})
    b = _entry("label.two", "s.dup", {"status": "never"})
    names = {c[0] for c in OI.validate_observation_mapping(
        _mapping(tmp, [a, b])) if not c[1]}
    check("same_address_different_label_is_caught",
          any("target_field_unique" in n for n in names), names)

    # Distinct addresses under one entity are fine.
    c1 = _entry("l.a", "s.two", field="location_cm")
    c2 = _entry("l.b", "s.two", field="rotation_pyr",
                path=["transform", "location"])
    names2 = {n for (n, ok, _d, _c) in OI.validate_observation_mapping(
        _mapping(tmp, [c1, c2])) if not ok}
    check("distinct_fields_are_allowed",
          not any("target_field_unique" in n for n in names2), names2)

    # And if two ever reach the model anyway, the field becomes an explicit
    # conflict rather than whichever was processed last.
    _write(tmp, "d.json", _artifact("s.dup"))
    model, _r = OI.build_observed_world(_mapping(tmp, [a, b]), "op")
    fld = OW.field_map(model).get(
        "semantic_landmarks.entities.s.dup.location_cm") or {}
    check("model_refuses_to_pick_a_winner",
          fld.get("provenance") not in OW.BACKED_PROVENANCE, fld)


def test_multiple_matches_are_deterministic(tmp):
    _write(tmp, "old.json", _artifact("s.many", x=1.0,
                                      created_at="2026-01-01T00:00:00Z"))
    _write(tmp, "new.json", _artifact("s.many", x=99.0,
                                      created_at="2026-06-01T00:00:00Z"))
    _write(tmp, "mid.json", _artifact("s.many", x=50.0,
                                      created_at="2026-03-01T00:00:00Z"))
    m = _mapping(tmp, [_entry("k", "s.many", {"status": "resolved"})])
    vals = set()
    for _ in range(5):
        res = OI.read_observations(m, "op")[0]
        vals.add(tuple(res[0]["field"]["value"]))
    check("repeat_reads_agree", len(vals) == 1, vals)
    # Newest by the artifact's OWN declared time, never by file mtime.
    check("newest_declared_time_wins", vals.pop()[0] == 99.0)


def test_unreadable_artifact_is_carried_not_dropped(tmp):
    with open(os.path.join(tmp, "broken.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json at all")
    _write(tmp, "fine.json", _artifact("s.ok"))
    loaded = OI.load_artifacts(tmp, "*.json")
    errs = [e for (_l, _d, e) in loaded if e]
    check("corrupt_file_is_reported", len(errs) == 1, errs)
    check("corrupt_file_is_not_silently_dropped", len(loaded) == 2, loaded)

    m = _mapping(tmp, [_entry("k", "s.ok", {"status": "resolved"})])
    _res, ops, _ev = OI.read_observations(m, "op")
    check("scan_operation_records_the_unreadable",
          "unreadable" in ops[0]["detail"], ops[0]["detail"])


def test_model_is_valid_and_traceable(tmp):
    _write(tmp, "a.json", _artifact("s.real", x=-800.0, y=-1000.0, z=0.0))
    m = _mapping(tmp, [
        _entry("k.real", "s.real", {"status": "resolved"}),
        _entry("k.missing", "s.absent", {"status": "resolved"}),
    ])
    model, results = OI.build_observed_world(
        m, "op_model",
        world_identity={"world_id": "/Game/Maps/X", "request_id": "r1",
                        "revision": 0})
    bad = [c for c in OW.validate_observed_world(model, strict=True) if not c[1]]
    check("observed_world_validates", not bad, bad)

    fields = OW.field_map(model)
    got = fields.get("semantic_landmarks.entities.s.real.location_cm") or {}
    check("measured_value_is_the_file_value",
          got.get("value") == [-800.0, -1000.0, 0.0], got.get("value"))
    check("measured_is_backed",
          got.get("provenance") in OW.BACKED_PROVENANCE, got.get("provenance"))
    # Every backed field must cite a locator that resolves in the index.
    refs = list(got.get("evidence_refs") or [])
    check("backed_field_cites_a_locator", bool(refs), refs)
    check("citation_resolves_in_the_index",
          all(r in model["evidence_index"] for r in refs),
          (refs, sorted(model["evidence_index"])))

    census = OI.intake_census(results)
    check("census_counts_agree",
          census["measured"] == 1 and census["not_observed"] == 1, census)


def test_identity_refuses_to_be_partial(tmp):
    _write(tmp, "a.json", _artifact("s.real"))
    m = _mapping(tmp, [_entry("k", "s.real", {"status": "resolved"})])

    partial, _r = OI.build_observed_world(
        m, "op", world_identity={"world_id": "/Game/Maps/X"})
    ident = OW.field_map(partial).get("world_identity") or {}
    check("partial_identity_is_not_backed",
          ident.get("provenance") not in OW.BACKED_PROVENANCE, ident)

    none_id, _r2 = OI.build_observed_world(m, "op")
    ident2 = OW.field_map(none_id).get("world_identity") or {}
    check("absent_identity_is_not_backed",
          ident2.get("provenance") not in OW.BACKED_PROVENANCE, ident2)

    full, _r3 = OI.build_observed_world(
        m, "op", world_identity={"world_id": "/Game/Maps/X",
                                 "request_id": "r", "revision": 0})
    ident3 = OW.field_map(full).get("world_identity") or {}
    check("complete_identity_is_backed",
          ident3.get("provenance") in OW.BACKED_PROVENANCE, ident3)


def test_bridge_to_the_planner(tmp):
    _write(tmp, "a.json", _artifact("route.start", x=-1000.0, y=0.0, z=0.0))
    _write(tmp, "b.json", _artifact("route.end", x=1000.0, y=0.0, z=0.0))
    _write(tmp, "c.json", _artifact("route.broken", status="unresolved"))
    m = _mapping(tmp, [
        _entry("k.start", "route.start", {"status": "resolved"}),
        _entry("k.end", "route.end", {"status": "resolved"}),
        _entry("k.broken", "route.broken", {"status": "resolved"}),
        _entry("k.never", "route.never", {"status": "resolved"}),
    ])
    model, _res = OI.build_observed_world(
        m, "op", world_identity={"world_id": "/Game/Maps/X",
                                 "request_id": "r", "revision": 0})

    anchors = OI.anchors_from_observed(
        model, "semantic_landmarks", ["route.start", "route.end"])
    check("backed_anchors_carry_locations",
          [a["location_cm"] for a in anchors]
          == [[-1000.0, 0.0, 0.0], [1000.0, 0.0, 0.0]], anchors)

    # The full chain: observations -> anchors -> concrete mutations.
    from pipeline import route_placement_provider as RP
    plan = RP.plan_route_placements(
        anchors, 3, {"origin_x_cm": 0.0, "origin_y_cm": 0.0,
                     "extent_x_cm": 4000.0, "extent_y_cm": 4000.0})
    check("observed_anchors_produce_a_plan", not plan["refused"],
          plan.get("refusal_reason"))
    check("plan_is_the_expected_geometry",
          [p["location_cm"][0] for p in plan["placements"]]
          == [-500.0, 0.0, 500.0],
          [p["location_cm"] for p in plan["placements"]])

    req, errs = RP.build_transaction_request(
        plan, "op_chain", "step_place", "/Game/Maps/X", "marker", actor_class="StaticMeshActor")
    check("chain_reaches_a_transaction_request", req is not None and not errs,
          errs)
    check("chain_produced_real_mutations", len(req["mutations"]) == 3)

    # ...and the two unbacked kinds both refuse, for reasons that differ.
    failed = OI.anchors_from_observed(
        model, "semantic_landmarks", ["route.start", "route.broken"])
    absent = OI.anchors_from_observed(
        model, "semantic_landmarks", ["route.start", "route.never"])
    for label, ax in (("failed", failed), ("absent", absent)):
        p = RP.plan_route_placements(
            ax, 3, {"origin_x_cm": 0.0, "origin_y_cm": 0.0,
                    "extent_x_cm": 4000.0, "extent_y_cm": 4000.0})
        check("unbacked_anchor_{}_refuses".format(label), p["refused"], p)
        check("unbacked_anchor_{}_names_wf1292".format(label),
              "WF1292_CORE_PLACEMENT_ANCHOR_UNOBSERVED" in p["failure_codes"],
              p["failure_codes"])
    check("the_two_unbacked_kinds_are_distinguishable",
          failed[1]["provenance"] != absent[1]["provenance"],
          (failed[1]["provenance"], absent[1]["provenance"]))


def main():
    tmp = tempfile.mkdtemp(prefix="wf_intake_")
    try:
        for fn in (test_three_states_stay_separate,
                   test_value_must_be_literally_present,
                   test_shape_is_checked_not_coerced,
                   test_mapping_cannot_state_a_value_or_provenance,
                   test_two_entries_cannot_write_one_field,
                   test_multiple_matches_are_deterministic,
                   test_unreadable_artifact_is_carried_not_dropped,
                   test_model_is_valid_and_traceable,
                   test_identity_refuses_to_be_partial,
                   test_bridge_to_the_planner):
            fn(tempfile.mkdtemp(prefix="case_", dir=tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if _FAILS:
        print("test_observation_intake: {} passed, {} FAILED".format(
            _N[0], len(_FAILS)))
        for f in _FAILS:
            print("  - {}".format(f))
        return 1
    print("test_observation_intake: {} assertion(s) passed, 0 failed".format(
        _N[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
