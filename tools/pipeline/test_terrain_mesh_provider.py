#!/usr/bin/env python3
"""test_terrain_mesh_provider -- the suite the declaration already claimed existed.

WHY THIS FILE IS NEW AND ITS NAME IS OLD
----------------------------------------
``terrain_mesh_provider.declaration()`` publishes this as its determinism
evidence:

    "pipeline/test_terrain_mesh_provider.py re-plans and compares canonical
     JSON, and asserts a different seed produces different terrain"

That file did not exist. The claim was published to every consumer as proof of
the property every reproducibility argument in this repository rests on, and
nothing behind it ran.

WF1233 is the rail meant to stop exactly this -- ``deterministic_given_seed``
requires ``determinism_evidence`` -- and it passed, because it checks that the
field is a non-empty string or list, not that what the string NAMES exists. A
rail that grades the shape of a claim and not its referent is one an author can
satisfy by writing a sentence. The sentence was true of intent and false of the
repository.

So these assertions make the published claim true. They also cover
``run_mesh_synthesis.validate_result``, which grades the far side that turns
one of these plans into a real StaticMesh asset.

THE VERTEX BRACKET, AND WHY IT IS NOT AN EQUALITY
-------------------------------------------------
The first real synthesis run reported 6144 render vertices for a description of
1089 positions -- exactly 2048 triangles x 3. A SOURCE vertex is a position; a
RENDER vertex is a (position, normal, UV, tangent) tuple, and UE's build splits
a shared position whenever its attributes differ, which per-face normals on a
heightfield do everywhere. Asserting equality between the two compared different
quantities. The bracket below is falsifiable in both directions and does not.
"""

import copy
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import terrain_mesh_provider as TMP     # noqa: E402
from pipeline import run_mesh_synthesis as RMS        # noqa: E402
from wfcore.providers import base as PB               # noqa: E402

_FAILS = []
_N = [0]

TERRAIN = {"terrain_id": "wf_suite", "asset_path": "/Game/X/SM_Suite",
           "resolution": 16, "seed": 4242, "size_cm": 2000.0, "height_cm": 300.0}


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))
    return ok


def _plan(**over):
    t = copy.deepcopy(TERRAIN)
    t.update(over)
    return TMP.plan_terrain_mesh(t)


# --------------------------------------------------------------------------- #
# the determinism claim the declaration publishes
# --------------------------------------------------------------------------- #
def test_replan_is_byte_identical():
    a, b = _plan(), _plan()
    check("replan_byte_identical", TMP.canonical(a) == TMP.canonical(b),
          "two plans from the same terrain differed; the published determinism "
          "evidence says this comparison is made")


def test_different_seed_changes_the_terrain():
    a, b = _plan(), _plan(seed=999999)
    check("seed_reaches_output", TMP.canonical(a) != TMP.canonical(b),
          "a different seed produced identical terrain, so the seed is not "
          "reaching the heightfield and 'deterministic_given_seed' would be "
          "true only vacuously")


def test_inputs_rebuilt_from_scratch_agree():
    """Guards against an accidental dependence on object identity or mutation."""
    a = _plan()
    fresh = {"terrain_id": "wf_suite", "asset_path": "/Game/X/SM_Suite",
             "resolution": 16, "seed": 4242, "size_cm": 2000.0,
             "height_cm": 300.0}
    b = TMP.plan_terrain_mesh(fresh)
    check("rebuilt_inputs_agree", TMP.canonical(a) == TMP.canonical(b),
          "a plan built from a freshly constructed input differed from one "
          "built from the module-level dict")


def test_caller_mutation_does_not_leak():
    t = copy.deepcopy(TERRAIN)
    a = TMP.plan_terrain_mesh(t)
    before = TMP.canonical(a)
    t["seed"] = 1
    t["resolution"] = 64
    check("plan_is_not_a_view_of_its_input", TMP.canonical(a) == before,
          "mutating the caller's input after planning changed the plan, so the "
          "plan holds a reference into it")


def test_declaration_evidence_names_this_file():
    d = TMP.declaration()
    ev = " ".join(d.get("determinism_evidence") or [])
    check("evidence_names_this_suite", "test_terrain_mesh_provider" in ev,
          "the declaration's determinism_evidence no longer names this suite; "
          "if the claim moved, the file it names must move with it")
    check("declaration_valid",
          not [c for c in PB.validate_provider_declaration(d, strict=True)
               if not c[1]],
          "the declaration itself does not validate")


def test_plan_validates_and_remeasures():
    plan = _plan()
    check("plan_accepted", not plan.get("refused"),
          "refused: {}".format(plan.get("refusal_reason")))
    bad = [c for c in TMP.validate_terrain_plan(plan, strict=True) if not c[1]]
    check("plan_validates", not bad,
          "validator rejected its own plan: {}".format([(c[0], c[2]) for c in bad]))
    n = TERRAIN["resolution"]
    check("vertex_count_is_grid",
          plan.get("vertex_count") == (n + 1) * (n + 1),
          "a resolution-{} grid has {} vertices, plan says {}".format(
              n, (n + 1) * (n + 1), plan.get("vertex_count")))
    check("triangle_count_is_grid",
          plan.get("triangle_count") == 2 * n * n,
          "a resolution-{} grid has {} triangles, plan says {}".format(
              n, 2 * n * n, plan.get("triangle_count")))


def test_oversize_resolution_refused():
    plan = _plan(resolution=TMP.MAX_RESOLUTION + 1)
    check("oversize_refused", plan.get("refused"),
          "a resolution above the declared cap was accepted; the cap exists so "
          "the cost is refused rather than discovered as a hang")


# --------------------------------------------------------------------------- #
# the far side's result, graded
# --------------------------------------------------------------------------- #
def _result(**over):
    doc = {"far_side_schema": RMS.RESULT_SCHEMA,
           "asset_path": "/Game/X/SM_Suite", "created": True, "saved": True,
           "vertex_count": 1734, "triangle_count": 512,
           "observed_bounds_cm": [1000.0, 1000.0, 120.0],
           "failure_codes": [], "error": None}
    doc.update(over)
    return doc


def _graded(doc, plan=None):
    plan = plan or _plan()
    return [c for c in RMS.validate_result(doc, plan, strict=True) if not c[1]]


def test_far_side_error_is_decisive():
    check("error_fails", bool(_graded(_result(error="boom"))),
          "a far side reporting an error was graded as success")
    check("codes_fail",
          bool(_graded(_result(failure_codes=["WF1279_CORE_SINK_NO_COMPENSATION"]))),
          "a far side reporting failure codes was graded as success")


def test_created_flag_cannot_outrun_its_atoms():
    bad = _graded(_result(created=True, vertex_count=0))
    check("flag_contradiction_caught",
          any("created_flag_agrees" in c[0] or "vertex_count_measured" in c[0]
              for c in bad),
          "created=true with zero vertices was accepted; that is the circular "
          "trust pattern validate_runtime_state was fixed for")


def test_triangle_equality_is_enforced():
    plan = _plan()
    bad = _graded(_result(triangle_count=plan["triangle_count"] + 1), plan)
    check("triangle_mismatch_caught",
          any("triangle_count_matches_plan" in c[0] for c in bad),
          "a build neither creates nor removes faces, so a triangle mismatch "
          "must fail")


def test_vertex_bracket_is_falsifiable_both_ways():
    plan = _plan()
    want_v, want_t = plan["vertex_count"], plan["triangle_count"]
    low = _graded(_result(vertex_count=want_v - 1,
                          triangle_count=want_t), plan)
    check("below_bracket_caught",
          any("vertex_count_within_build_bracket" in c[0] for c in low),
          "fewer render vertices than source positions means positions were "
          "lost, and must fail")
    high = _graded(_result(vertex_count=want_t * 3 + 1,
                           triangle_count=want_t), plan)
    check("above_bracket_caught",
          any("vertex_count_within_build_bracket" in c[0] for c in high),
          "more than three render vertices per triangle means vertices were "
          "invented, and must fail")
    ok = _graded(_result(vertex_count=want_t * 3, triangle_count=want_t), plan)
    check("fully_split_accepted", not ok,
          "a fully split build (3 render vertices per triangle) is what UE "
          "actually produced for a heightfield and must be accepted: {}".format(
              [(c[0], c[2]) for c in ok]))


def test_degenerate_bounds_caught():
    bad = _graded(_result(observed_bounds_cm=[1000.0, 1000.0, 0.0]))
    check("zero_extent_caught",
          any("bounds_non_degenerate" in c[0] for c in bad),
          "a mesh with zero extent on an axis is degenerate and must fail")


def test_live_run_evidence_still_grades_clean():
    """The real 2026-09-03 synthesis, re-graded from what is on disk."""
    root = os.path.dirname(_TOOLS)
    spec = os.path.join(root, "procedural", "reports", "core", "mesh_synthesis",
                        "SM_WF_Synth_01", "spec.json")
    far = os.path.join(root, "procedural", "reports", "core", "mesh_synthesis",
                       "SM_WF_Synth_01", "far_side.json")
    if not (os.path.isfile(spec) and os.path.isfile(far)):
        check("live_evidence_present", False,
              "the committed live synthesis evidence is missing; this suite "
              "asserts against a real run, not only synthetic documents")
        return
    with open(spec, encoding="utf-8") as fh:
        plan = json.load(fh)
    with open(far, encoding="utf-8") as fh:
        doc = json.load(fh)
    bad = [c for c in RMS.validate_result(doc, plan, strict=True) if not c[1]]
    check("live_run_grades_clean", not bad,
          "the real synthesis run no longer grades clean: {}".format(
              [(c[0], c[2]) for c in bad]))


def main():
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)),
                     key=lambda f: f.__name__):
        fn()
    if _FAILS:
        print("test_terrain_mesh_provider: {} assertion(s) passed, {} FAILED"
              .format(_N[0], len(_FAILS)))
        for f in _FAILS:
            print("  FAIL {}".format(f))
        return 1
    print("test_terrain_mesh_provider: {} assertion(s) passed, 0 failed"
          .format(_N[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
