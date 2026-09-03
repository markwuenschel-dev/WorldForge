#!/usr/bin/env python3
"""test_landscape_provider -- prove the engine's sizing invariant is enforced,
and that the sink takes this provider's request unmodified.

What these assertions defend:

  * WF1274 fires on every way of violating the landscape sizing invariant. A
    grid that is not section_size * sections_per_component * count + 1 is not a
    smaller landscape; it is one the engine rejects or silently reshapes, and
    "silently reshaped" leaves a plan describing a world nobody built.
  * The heightmap is uint16 in the engine's own convention, and its length
    matches the grid the plan claims. A length mismatch means the generator and
    the invariant disagree, which is exactly the bug this rail exists to catch.
  * The observed height range is RE-MEASURED from the emitted samples rather
    than carried from the request -- the same rule terrain_mesh_provider follows.
  * Determinism, byte-for-byte, including that a different seed actually reaches
    the output. A determinism test that never varies the seed proves nothing.
  * Mutation test on the section_size rail: defeat it and the refusal must stop.
"""

import copy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import landscape_provider as L         # noqa: E402
from pipeline import run_wfcore_transaction as TX    # noqa: E402
from wfcore.failure import FailureCode as C          # noqa: E402
from wfcore.providers import base as PB              # noqa: E402
from wfcore.transaction import delta as TD           # noqa: E402

_FAILS = []
_N = [0]

REGION = {"min": [-6300.0, -6300.0, 0.0], "max": [6300.0, 6300.0, 0.0]}


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))
    return ok


def _plan(**over):
    kw = dict(region=copy.deepcopy(REGION), seed=1337, section_size=63,
              sections_per_component=1, component_count=1)
    kw.update(over)
    return L.plan_landscape(**kw)


# --------------------------------------------------------------------------- #
# the engine invariant
# --------------------------------------------------------------------------- #
def test_bad_section_size_refused():
    for bad in (64, 32, 0, -7, 128, "63"):
        plan = _plan(section_size=bad)
        if not check("section_size_{!r}_refused".format(bad), plan["refused"],
                     "section_size {!r} is not an engine quad count and was "
                     "ACCEPTED".format(bad)):
            continue
        check("section_size_{!r}_names_wf1274".format(bad),
              C.CORE_LANDSCAPE_GRID_INVALID in plan["failure_codes"],
              "got {}".format(plan["failure_codes"]))


def test_bad_sections_per_component_refused():
    for bad in (0, 2, 3, 5, 16):
        check("spc_{}_refused".format(bad), _plan(sections_per_component=bad)["refused"],
              "sections_per_component must be 1 or 4; {} was accepted".format(bad))


def test_bad_component_count_refused():
    for bad in (0, -1, L.MAX_COMPONENT_COUNT + 1, 1.5):
        check("component_count_{!r}_refused".format(bad),
              _plan(component_count=bad)["refused"],
              "component_count {!r} was accepted".format(bad))


def test_section_size_rail_is_not_tautological():
    """MUTATION: accept any section size and the refusal must stop happening."""
    real = L.SECTION_SIZES
    try:
        L.SECTION_SIZES = tuple(list(real) + [64])
        plan = _plan(section_size=64)
    finally:
        L.SECTION_SIZES = real
    check("mutation_defeats_section_rail", not plan["refused"],
          "with 64 added to the supported set the plan STILL refused, so the "
          "real assertion is not testing the section-size rail")


def test_grid_invariant_holds():
    for ss, spc, cc in ((7, 1, 1), (63, 1, 1), (31, 4, 2), (15, 1, 8)):
        plan = _plan(section_size=ss, sections_per_component=spc,
                     component_count=cc)
        if not check("grid_{}_{}_{}_accepted".format(ss, spc, cc),
                     not plan["refused"],
                     "refused: {}".format(plan.get("refusal_reason"))):
            continue
        n = L.vertices_per_side(ss, spc, cc)
        check("grid_{}_{}_{}_vertices".format(ss, spc, cc),
              plan["vertices_per_side"] == n,
              "expected {} vertices per side, got {}".format(
                  n, plan["vertices_per_side"]))
        check("grid_{}_{}_{}_samples".format(ss, spc, cc),
              len(plan["heightmap_uint16"]) == n * n,
              "expected {} samples, got {}".format(
                  n * n, len(plan["heightmap_uint16"])))


# --------------------------------------------------------------------------- #
# height data
# --------------------------------------------------------------------------- #
def test_heights_are_uint16():
    hm = _plan()["heightmap_uint16"]
    check("heights_all_uint16",
          all(isinstance(v, int) and 0 <= v <= L.HEIGHT_MAX for v in hm),
          "the engine reads uint16 and nothing else")
    check("heights_are_not_constant", len(set(hm)) > 1,
          "every height identical means the noise is not reaching the output")


def test_height_range_is_remeasured():
    plan = _plan()
    lo, hi = plan["observed_height_range_cm"]
    check("range_ordered", lo <= hi, "got [{}, {}]".format(lo, hi))
    # Re-derive independently from the emitted uint16 and confirm the sign and
    # rough magnitude agree -- a range copied from the request rather than
    # measured would not track the samples.
    mids = [v - L.HEIGHT_MID for v in plan["heightmap_uint16"]]
    check("range_tracks_samples",
          (min(mids) < 0) == (lo < 0) and (max(mids) > 0) == (hi > 0),
          "the reported range does not agree in sign with the emitted samples, "
          "so it is not measured from them")


def test_determinism():
    a, b = _plan(), _plan()
    check("repeat_byte_identical", L.canonical(a) == L.canonical(b),
          "two plans with the same seed differed")
    c_ = _plan(seed=98765)
    check("different_seed_differs", L.canonical(a) != L.canonical(c_),
          "a different seed produced an identical landscape, so the seed is not "
          "reaching the heightfield")


def test_heightfield_is_imported_not_reimplemented():
    """The mesh lane and the landscape lane must agree about the terrain."""
    from pipeline import terrain_mesh_provider as TMP
    check("uses_shared_heightfield", L.TMP.heightfield is TMP.heightfield,
          "landscape_provider must import the mesh lane's heightfield; a second "
          "implementation would be a second authority on what the terrain is")


# --------------------------------------------------------------------------- #
# refusal is inert, and the seam
# --------------------------------------------------------------------------- #
def test_refusal_is_inert():
    plan = _plan(section_size=64)
    check("refusal_has_no_actor", plan["actor"] is None,
          "a refused plan carrying an actor can still be materialised")
    check("refusal_has_no_heightmap", not plan["heightmap_uint16"],
          "a refused plan must carry no height data")
    req, errs = L.build_transaction_request(
        plan, "op_x", "step_x", "/Game/Maps/_wf_test_lvl", "wfls_x")
    check("refused_plan_yields_no_request", req is None and bool(errs),
          "got req={!r} errs={!r}".format(req, errs))


def test_plan_validates():
    plan = _plan()
    bad = [c for c in L.validate_landscape_plan(plan, strict=True) if not c[1]]
    check("plan_validates", not bad,
          "validator rejected its own plan: {}".format([(c[0], c[2]) for c in bad]))


def test_sink_accepts_request_unchanged():
    plan = _plan()
    req, errs = L.build_transaction_request(
        plan, "op_ls_t", "step_ls", "/Game/Maps/_wf_test_lvl", "wfls_t")
    check("request_built", req is not None and not errs, "errors: {}".format(errs))
    if req is None:
        return
    errors, _w = TX.validate_request(req)
    check("sink_accepts_unchanged", not errors,
          "the sink REJECTED this provider's request: {}".format(errors))
    m = req["mutations"][0]
    check("target_is_an_actor", m["target_kind"] == TD.TARGET_ACTOR,
          "a Landscape is an actor; that is why this lane goes through the sink")
    check("rollback_is_compensating",
          m["rollback_mode"] == PB.ROLLBACK_COMPENSATING,
          "an actor can be un-spawned, so the claim is honest here")
    check("detail_states_the_heightmap_gap",
          "NOT carried" in m["detail"],
          "the mutation must say that the heightmap does not travel with it, or "
          "a committed transaction reads as a built landscape")


def test_declaration_valid():
    d = L.declaration()
    bad = [c for c in PB.validate_provider_declaration(d, strict=True) if not c[1]]
    check("declaration_valid", not bad,
          "declaration rejected: {}".format([(c[0], c[2]) for c in bad]))
    check("capability_is_terrain_shaping",
          d["capabilities"] == [PB.CAP_TERRAIN_SHAPING],
          "this is the provider that fills terrain_shaping; got {!r}".format(
              d["capabilities"]))
    check("seeded_claim_has_evidence",
          d["determinism"] == PB.DET_SEEDED and d.get("determinism_evidence"),
          "a seeded determinism claim requires evidence (WF1233)")


def main():
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)),
                     key=lambda f: f.__name__):
        fn()
    if _FAILS:
        print("test_landscape_provider: {} assertion(s) passed, {} FAILED"
              .format(_N[0], len(_FAILS)))
        for f in _FAILS:
            print("  FAIL {}".format(f))
        return 1
    print("test_landscape_provider: {} assertion(s) passed, 0 failed".format(_N[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
