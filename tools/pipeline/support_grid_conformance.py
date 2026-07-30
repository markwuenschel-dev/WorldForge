#!/usr/bin/env python3
"""support_grid_conformance.py — conformance harness for the v2.6 support grid.

Proves that ``support_grid_canonical.py`` actually holds the properties
``docs/contracts/v2_6_support_grid_contract.md`` claims, and that every
documented cross-language divergence in ``support_grid_discrepancies.py`` still
diverges exactly as written.

Lanes:
  extent::      k = floor(R/s) boundary cases (R<s, R==s, R slightly >s, R==k*s)
  order::       canonical row-major ordering and its stability
  neighbour::   the off-grid-neighbour rule and the perimeter asymmetry it creates
  tristate::    miss vs failure — a trace that did not run is hit=None, never False
  support::     S_ij, cos(theta_max) comparison, head-clearance window
  edge::        E_ij two-pass separation, tau_h, the DERIVED tau_n and its
                non-vacuity, and the still-live refusal path
  identity::    canonical sample identity (§1.4): determinism, round-trip, and
                disjointness from the fixture-smoke ordering token
  golden::      written-out expected values — extent, rejection, square vs disk,
                canonical order, and tau_n below/at/above threshold
  tolerance::   the one declaration agrees with the C++ literals AND with
                scene_survey_evidence.CONTRACT_CONSTANTS; and the C++ still does
                NOT implement tau_n
  divergence::  every documented native/canonical discrepancy still holds

Every check is blocking. A conformance harness with warn-only checks is a
conformance harness that can go green while the contract is broken.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/support_grid_conformance.py --strict

Reports -> procedural/reports/scene_survey/support_grid_conformance_report.json
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import support_grid_canonical as SG  # noqa: E402
import support_grid_discrepancies as SD  # noqa: E402
from failure_codes import FailureCode as F  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

CPP_PATH = (REPO_ROOT / "Plugins" / "WorldForge" / "Source" / "WorldForgeCore"
            / "Private" / "SceneSurvey.cpp")
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey"
REPORT_NAME = "support_grid_conformance_report.json"
REPORT_TYPE = "wf.scene_survey.support_grid_conformance.v1"

C_GEOM = F.SCENE_SURVEY_SUPPORT_SAMPLE_INVALID
C_EDGE = F.SCENE_SURVEY_EDGE_CLASSIFICATION_INVALID
C_FAILCLOSED = F.SCENE_SURVEY_SUPPORT_UNKNOWN_OVERCLAIM
C_RAW = F.SCENE_SURVEY_EVIDENCE_RAW_MISSING
C_TOL = F.SCENE_SURVEY_PROFILE_INVALID
C_DIVERGE = F.SCENE_SURVEY_CHANNEL_DISAGREEMENT


def _cell(i, j, z=0.0, normal=(0.0, 0.0, 1.0), head_hit=False, step=100.0):
    x, y = i * step, j * step
    return SG.RawCell(
        i=i, j=j,
        ground=SG.RawTrace(trace_start=(x, y, z + 1000.0),
                           trace_end=(x, y, z - 3000.0), hit=True,
                           impact_point=(x, y, z), normal=normal),
        head=SG.RawTrace(trace_start=(x, y, z + 50.0), trace_end=(x, y, z + 176.0),
                         hit=head_hit,
                         impact_point=(x, y, z + 100.0) if head_hit else None,
                         normal=(0.0, 0.0, -1.0) if head_hit else None))


def _miss(i, j, step=100.0):
    x, y = i * step, j * step
    return SG.RawCell(i=i, j=j,
                      ground=SG.RawTrace((x, y, 1000.0), (x, y, -3000.0), hit=False),
                      head=None)


def _tilt(deg, az=0.0):
    t, a = math.radians(deg), math.radians(az)
    return (math.sin(t) * math.cos(a), math.sin(t) * math.sin(a), math.cos(t))


def _flat_grid(k, step=100.0):
    return [_cell(i, j, step=step) for (i, j) in SG.sample_indices(k)]


def _executable_source(func_name):
    """The body of a canonical function with docstrings and comments removed.

    The prose in that module deliberately says "no acos, no degrees", so a raw
    substring search would find the words it is asserting the absence of. Only
    the executable text may be searched.
    """
    src = Path(SG.__file__).read_text(encoding="utf-8")
    body = src.split("def {}".format(func_name), 1)[1].split("\ndef ", 1)[0]
    body = re.sub(r'"""..*?"""', "", body, flags=re.S)
    body = re.sub(r"'''.*?'''", "", body, flags=re.S)
    return "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())


# --------------------------------------------------------------------------- #
# extent:: k = floor(R/s)
# --------------------------------------------------------------------------- #
def lane_extent(rep):
    cases = [
        # (label,            R,       s,     expected k, expected N)
        ("r_lt_s",           50.0,   100.0,  0,  1),
        ("r_eq_s",          100.0,   100.0,  1,  9),
        ("r_just_over_s",   100.001, 100.0,  1,  9),
        ("r_just_under_s",   99.999, 100.0,  0,  1),
        ("r_eq_k_times_s",  300.0,   100.0,  3, 49),
        ("r_just_under_ks", 299.999, 100.0,  2, 25),
        ("r_just_over_ks",  300.001, 100.0,  3, 49),
        ("r_much_lt_s",       0.5,   100.0,  0,  1),
        ("probe_default",  3000.0,   100.0, 30, 61 * 61),
    ]
    for label, r, s, want_k, want_n in cases:
        got_k = SG.grid_extent_k(r, s)
        rep.check("extent::{}::k".format(label), got_k == want_k,
                  "R={} s={}: k={} expected {}".format(r, s, got_k, want_k),
                  code=C_GEOM)
        got_n = SG.nominal_sample_count(got_k)
        rep.check("extent::{}::N".format(label), got_n == want_n,
                  "R={} s={}: N={} expected {}".format(r, s, got_n, want_n),
                  code=C_GEOM)

    # The single-centre-sample guarantee, stated as its own rail.
    k0 = SG.grid_extent_k(50.0, 100.0)
    idx = SG.sample_indices(k0)
    rep.check("extent::r_lt_s::single_centre_sample",
              idx == ((0, 0),),
              "R<s must yield exactly the centre sample; got {}".format(idx),
              code=C_GEOM)

    # No sample may fall outside the requested half-extent, for any (R, s).
    worst = []
    for r, s in ((50.0, 100.0), (100.0, 100.0), (250.0, 100.0), (3000.0, 100.0),
                 (999.0, 250.0), (1.0, 1000.0)):
        for (i, j, x, y) in SG.sample_points((0.0, 0.0), r, s):
            if abs(x) > r + 1e-9 or abs(y) > r + 1e-9:
                worst.append((r, s, i, j, x, y))
    rep.check("extent::no_sample_outside_half_extent", not worst,
              "samples outside the requested half-extent: {}".format(worst[:4]),
              code=C_GEOM)

    # Bad parameters are refused, not silently clamped.
    for bad_r, bad_s in ((0.0, 100.0), (-1.0, 100.0), (100.0, 0.0), (100.0, -5.0)):
        try:
            SG.grid_extent_k(bad_r, bad_s)
            ok = False
        except SG.ContractViolation:
            ok = True
        rep.check("extent::rejects_bad_params::R{}_s{}".format(bad_r, bad_s), ok,
                  "R={} s={} must raise ContractViolation".format(bad_r, bad_s),
                  code=C_GEOM)


# --------------------------------------------------------------------------- #
# order:: canonical row-major
# --------------------------------------------------------------------------- #
def lane_order(rep):
    k = 3
    idx = SG.sample_indices(k)
    rep.check("order::count", len(idx) == SG.nominal_sample_count(k),
              "expected {} indices, got {}".format(
                  SG.nominal_sample_count(k), len(idx)), code=C_GEOM)

    expected = tuple((i, j) for i in range(-k, k + 1) for j in range(-k, k + 1))
    rep.check("order::row_major_i_outer_j_inner", idx == expected,
              "i must be the OUTER loop and j the INNER one (contract §6)",
              code=C_GEOM)

    strictly_increasing = all(
        SG.canonical_sort_key(a) < SG.canonical_sort_key(b)
        for a, b in zip(idx, idx[1:]))
    rep.check("order::strictly_increasing", strictly_increasing,
              "(i,j) < (i',j') iff i<i' or (i==i' and j<j') must hold pairwise",
              code=C_GEOM)

    # Stability: any permutation re-sorts to the identical sequence.
    shuffled = list(idx)
    shuffled.reverse()
    shuffled = shuffled[7:] + shuffled[:7]
    rep.check("order::sort_is_stable_under_permutation",
              tuple(sorted(shuffled, key=SG.canonical_sort_key)) == idx,
              "canonical_sort_key must recover the canonical order from any input "
              "order — raw records feed a determinism hash", code=C_GEOM)

    # derive_grid emits in canonical order regardless of input order.
    cells = _flat_grid(1)
    cells.reverse()
    grid = SG.derive_grid(cells, (0.0, 0.0), 100.0, 100.0)
    emitted = tuple((c.i, c.j) for c in grid.cells)
    rep.check("order::derive_grid_emits_canonical",
              emitted == SG.sample_indices(1),
              "derive_grid must re-order to canonical; got {}".format(emitted),
              code=C_GEOM)


# --------------------------------------------------------------------------- #
# neighbour:: off-grid rule + perimeter asymmetry
# --------------------------------------------------------------------------- #
def lane_neighbour(rep):
    rep.check("neighbour::von_neumann_4_connected",
              SG.NEIGHBOUR_DELTAS == ((1, 0), (-1, 0), (0, 1), (0, -1)),
              "neighbourhood must be 4-connected (contract §5.1); got {}".format(
                  SG.NEIGHBOUR_DELTAS), code=C_EDGE)

    # A uniform flat 5x5 with a declared tau_n: NOTHING may be an edge. If an
    # off-grid neighbour counted as invalid, the whole perimeter would fire.
    tol = SG.SupportTolerances(tau_n_deg=30.0)
    grid = SG.derive_grid(_flat_grid(2), (0.0, 0.0), 200.0, 100.0, tol=tol)
    edges = [(c.i, c.j) for c in grid.cells if c.edge is True]
    rep.check("neighbour::off_grid_is_not_an_edge", not edges,
              "a uniform flat grid must contain ZERO edges; off-grid neighbours "
              "are skipped, not treated as invalid (SceneSurvey.cpp:188). "
              "Got edges at {}".format(edges), code=C_EDGE)

    perimeter = [(c.i, c.j) for c in grid.cells
                 if abs(c.i) == grid.k or abs(c.j) == grid.k]
    rep.check("neighbour::perimeter_not_edge",
              all((i, j) not in edges for (i, j) in perimeter),
              "no perimeter cell may be an edge purely from the window shape",
              code=C_EDGE)

    # The asymmetry that convention creates, asserted rather than assumed:
    # corner cells see 2 neighbours, side cells 3, interior cells 4.
    def n_on_grid(i, j, k):
        return sum(1 for (di, dj) in SG.NEIGHBOUR_DELTAS
                   if abs(i + di) <= k and abs(j + dj) <= k)

    k = 2
    rep.check("neighbour::perimeter_asymmetry_corner_sees_2",
              n_on_grid(-k, -k, k) == 2 and n_on_grid(k, k, k) == 2,
              "corner cells are evaluated against 2 neighbours", code=C_EDGE)
    rep.check("neighbour::perimeter_asymmetry_side_sees_3",
              n_on_grid(-k, 0, k) == 3 and n_on_grid(0, k, k) == 3,
              "non-corner perimeter cells are evaluated against 3 neighbours",
              code=C_EDGE)
    rep.check("neighbour::perimeter_asymmetry_interior_sees_4",
              n_on_grid(0, 0, k) == 4,
              "interior cells are evaluated against 4 neighbours; perimeter cells "
              "are therefore systematically LESS likely to be classified edge, "
              "and downstream evidence must not present them as equal evidence",
              code=C_EDGE)

    # An unsupported neighbour DOES fire — proving the rule above is not vacuous.
    cells = [c for c in _flat_grid(1) if (c.i, c.j) != (1, 0)] + [_miss(1, 0)]
    g2 = SG.derive_grid(cells, (0.0, 0.0), 100.0, 100.0, tol=tol)
    centre = [c for c in g2.cells if (c.i, c.j) == (0, 0)][0]
    rep.check("neighbour::unsupported_neighbour_does_fire",
              centre.edge is True
              and SG.TERM_NEIGHBOUR_UNSUPPORTED in centre.edge_terms,
              "a supported cell beside a clean miss MUST be an edge; got edge={} "
              "terms={}".format(centre.edge, centre.edge_terms), code=C_EDGE)

    # A sample outside the requested half-extent is refused, not absorbed.
    over = _flat_grid(1) + [_cell(2, 0)]
    try:
        SG.derive_grid(over, (0.0, 0.0), 100.0, 100.0, tol=tol)
        ok = False
    except SG.ContractViolation:
        ok = True
    rep.check("neighbour::rejects_sample_outside_region", ok,
              "an observation outside [-k,k] must raise ContractViolation — that "
              "is how the R<s over-extension is caught at the seam", code=C_GEOM)


# --------------------------------------------------------------------------- #
# tristate:: miss vs failure
# --------------------------------------------------------------------------- #
def lane_tristate(rep):
    # hit=None without a failure reason is malformed.
    try:
        SG.RawTrace((0, 0, 0), (0, 0, -1), hit=None)
        ok = False
    except SG.ContractViolation:
        ok = True
    rep.check("tristate::hit_none_requires_failure", ok,
              "hit=None means the trace did not run and REQUIRES a failure reason",
              code=C_RAW)

    # A trace that ran must not also carry a failure.
    try:
        SG.RawTrace((0, 0, 0), (0, 0, -1), hit=False, failure="timeout")
        ok = False
    except SG.ContractViolation:
        ok = True
    rep.check("tristate::ran_trace_has_no_failure", ok,
              "hit=False with a failure reason conflates 'missed' with 'never ran'",
              code=C_RAW)

    # A clean miss carries no geometry — never a zero vector.
    try:
        SG.RawTrace((0, 0, 0), (0, 0, -1), hit=False,
                    impact_point=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 0.0))
        ok = False
    except SG.ContractViolation:
        ok = True
    rep.check("tristate::miss_carries_no_zero_vector", ok,
              "p_impact and n_hat are None on a clean miss, never a zero vector",
              code=C_RAW)

    # A trace that did not run cannot carry geometry.
    try:
        SG.RawTrace((0, 0, 0), (0, 0, -1), hit=None, failure="refused",
                    impact_point=(1.0, 2.0, 3.0))
        ok = False
    except SG.ContractViolation:
        ok = True
    rep.check("tristate::not_run_carries_no_geometry", ok,
              "a trace that did not run cannot carry an impact point", code=C_RAW)

    # The three states classify differently and fail closed.
    x = 0.0
    ran_and_missed = SG.RawCell(0, 0, SG.RawTrace((x, x, 1000.0), (x, x, -3000.0),
                                                 hit=False))
    never_ran = SG.RawCell(0, 0, SG.RawTrace((x, x, 1000.0), (x, x, -3000.0),
                                             hit=None, failure="editor_refused"))
    ran_and_hit = _cell(0, 0)

    p_miss = SG.classify_support(ran_and_missed)
    p_fail = SG.classify_support(never_ran)
    p_hit = SG.classify_support(ran_and_hit)

    rep.check("tristate::miss_is_unsupported_and_decided",
              p_miss.pass1_class == SG.CLS_UNSUPPORTED and p_miss.supported is False,
              "a clean miss is a real observation: unsupported, S=False; got {} {}"
              .format(p_miss.pass1_class, p_miss.supported), code=C_FAILCLOSED)
    rep.check("tristate::failure_is_trace_error_and_undecided",
              p_fail.pass1_class == SG.CLS_TRACE_ERROR and p_fail.supported is None,
              "a trace that did not run is trace_error with S=None (UNKNOWN), "
              "never unsupported; got {} {}".format(
                  p_fail.pass1_class, p_fail.supported), code=C_FAILCLOSED)
    rep.check("tristate::miss_and_failure_are_distinct",
              p_miss.pass1_class != p_fail.pass1_class
              and p_miss.supported is not p_fail.supported,
              "'missed' and 'never attempted' must not collapse to one state",
              code=C_FAILCLOSED)
    rep.check("tristate::hit_is_supported",
              p_hit.pass1_class == SG.CLS_VALID and p_hit.supported is True,
              "a clean flat hit with head clearance is support", code=C_GEOM)

    # Fail-closed: an undecided cell is never counted as support.
    rep.check("tristate::unknown_never_counts_valid",
              SG.VALID_SUPPORT_CLASSES == (SG.CLS_VALID,),
              "only valid_support counts as support; unknown and trace_error "
              "never do", code=C_FAILCLOSED)


# --------------------------------------------------------------------------- #
# support:: S_ij
# --------------------------------------------------------------------------- #
def lane_support(rep):
    tol = SG.CONTRACT_TOLERANCES

    # The slope test is a direct cos comparison, and it is exact at the boundary.
    at_limit = _cell(0, 0, normal=_tilt(tol.max_slope_deg))
    just_over = _cell(0, 0, normal=_tilt(tol.max_slope_deg + 0.01))
    just_under = _cell(0, 0, normal=_tilt(tol.max_slope_deg - 0.01))
    rep.check("support::slope_at_theta_max_is_supported",
              SG.classify_support(at_limit).supported is True,
              "slope == theta_max is standable (the C++ blocks on Slope > MaxSlope, "
              "strictly); got {}".format(SG.classify_support(at_limit).pass1_class),
              code=C_GEOM)
    rep.check("support::slope_over_theta_max_is_blocked",
              SG.classify_support(just_over).pass1_class == SG.CLS_BLOCKED,
              "slope just over theta_max must be blocked", code=C_GEOM)
    rep.check("support::slope_under_theta_max_is_supported",
              SG.classify_support(just_under).supported is True,
              "slope just under theta_max must be supported", code=C_GEOM)

    # cos(theta_max) is used directly, not reconstructed through acos/degrees.
    body = _executable_source("classify_support")
    rep.check("support::no_acos_roundtrip_in_predicate",
              "acos" not in body and "degrees" not in body,
              "classify_support must compare n_hat.z against cos(theta_max) "
              "directly; an acos/degrees round-trip is where two languages "
              "disagree in the last bits", code=C_GEOM)

    # Head clearance is required, and its window is the declared one.
    lo, hi = SG.head_trace_window(0.0, tol)
    rep.check("support::head_window_is_50_to_176", (lo, hi) == (50.0, 176.0),
              "head-clearance window must be [impact+50, impact+176] cm; got "
              "[{}, {}]".format(lo, hi), code=C_GEOM)
    rep.check("support::head_blocked_is_blocked",
              SG.classify_support(_cell(0, 0, head_hit=True)).pass1_class
              == SG.CLS_BLOCKED,
              "a head-blocked cell is blocked, never valid", code=C_GEOM)

    # Non-finite / degenerate geometry is a failed measurement, not a miss.
    nan = float("nan")
    bad_pt = SG.RawCell(0, 0, SG.RawTrace((0, 0, 1000.0), (0, 0, -3000.0), hit=True,
                                          impact_point=(0.0, 0.0, nan),
                                          normal=(0.0, 0.0, 1.0)))
    bad_n = SG.RawCell(0, 0, SG.RawTrace((0, 0, 1000.0), (0, 0, -3000.0), hit=True,
                                         impact_point=(0.0, 0.0, 0.0),
                                         normal=(0.0, 0.0, 0.0)))
    rep.check("support::nan_impact_is_trace_error",
              SG.classify_support(bad_pt).pass1_class == SG.CLS_TRACE_ERROR
              and SG.classify_support(bad_pt).supported is None,
              "a NaN impact point is trace_error with S=None", code=C_FAILCLOSED)
    rep.check("support::degenerate_normal_is_trace_error",
              SG.classify_support(bad_n).pass1_class == SG.CLS_TRACE_ERROR
              and SG.classify_support(bad_n).supported is None,
              "a zero-length normal is trace_error with S=None", code=C_FAILCLOSED)

    # A supported cell with no head observation is UNKNOWN, not clear.
    no_head = SG.RawCell(0, 0, SG.RawTrace((0, 0, 1000.0), (0, 0, -3000.0), hit=True,
                                           impact_point=(0.0, 0.0, 0.0),
                                           normal=(0.0, 0.0, 1.0)), head=None)
    rep.check("support::missing_head_observation_is_not_clear",
              SG.classify_support(no_head).supported is None,
              "an unattempted head trace must never read as clearance",
              code=C_FAILCLOSED)

    # Sample coordinates.
    pts = SG.sample_points((1000.0, -500.0), 200.0, 100.0)
    rep.check("support::sample_point_formula",
              pts[0][2:] == (1000.0 - 2 * 100.0, -500.0 - 2 * 100.0)
              and pts[-1][2:] == (1000.0 + 2 * 100.0, -500.0 + 2 * 100.0),
              "p_ij = (a_x + i*s, a_y + j*s); got first={} last={}".format(
                  pts[0], pts[-1]), code=C_GEOM)


# --------------------------------------------------------------------------- #
# edge:: E_ij
# --------------------------------------------------------------------------- #
def lane_edge(rep):
    tol_n = SG.SupportTolerances(tau_n_deg=30.0)

    # tau_h fires strictly above the tolerance, not at it.
    def two_cell_dz(dz, tol):
        cells = [_cell(i, j, z=(dz if i == 1 else 0.0))
                 for (i, j) in SG.sample_indices(1)]
        g = SG.derive_grid(cells, (0.0, 0.0), 100.0, 100.0, tol=tol)
        return {(c.i, c.j): c for c in g.cells}[(0, 0)]

    rep.check("edge::tau_h_is_90cm", SG.CONTRACT_TOLERANCES.tau_h_cm == 90.0,
              "tau_h = 2 * h_step = 90 cm; got {}".format(
                  SG.CONTRACT_TOLERANCES.tau_h_cm), code=C_TOL)
    rep.check("edge::tau_h_not_fired_at_exactly_90",
              two_cell_dz(90.0, tol_n).edge is False,
              "|dz| == tau_h is NOT an edge (the predicate is strictly >)",
              code=C_EDGE)
    rep.check("edge::tau_h_fires_just_over_90",
              two_cell_dz(90.001, tol_n).edge is True,
              "|dz| just over tau_h must be an edge", code=C_EDGE)

    # Two-pass separation: pass 2 must not observe its own output.
    # A chain of supported cells beside one miss: only the ADJACENT cell is an
    # edge. If pass 2 read its own writes, the edge would propagate down the row.
    cells = [c for c in _flat_grid(2) if (c.i, c.j) != (2, 0)] + [_miss(2, 0)]
    g = SG.derive_grid(cells, (0.0, 0.0), 200.0, 100.0, tol=tol_n)
    by = {(c.i, c.j): c for c in g.cells}
    rep.check("edge::two_pass_no_propagation",
              by[(1, 0)].edge is True and by[(0, 0)].edge is False
              and by[(-1, 0)].edge is False,
              "an edge must not propagate: (1,0) edge={} (0,0) edge={} "
              "(-1,0) edge={}. Fusing the passes makes the result "
              "iteration-order dependent (contract §5.3)".format(
                  by[(1, 0)].edge, by[(0, 0)].edge, by[(-1, 0)].edge),
              code=C_EDGE)

    # Order independence, asserted directly.
    shuffled = list(reversed(cells))
    g2 = SG.derive_grid(shuffled, (0.0, 0.0), 200.0, 100.0, tol=tol_n)
    rep.check("edge::order_independent",
              tuple((c.i, c.j, c.edge) for c in g.cells)
              == tuple((c.i, c.j, c.edge) for c in g2.cells),
              "the result must not depend on observation input order", code=C_EDGE)

    # Edge is a reclassification of SUPPORTED cells only.
    rep.check("edge::requires_S_ij",
              all(c.edge is not True for c in g.cells if c.supported is not True),
              "E_ij requires S_ij; an unsupported/blocked cell is never an edge",
              code=C_EDGE)

    # --- tau_n is DECLARED, and declared BY DERIVATION --------------------- #
    ct = SG.CONTRACT_TOLERANCES
    rep.check("edge::tau_n_is_declared",
              ct.tau_n_declared and ct.tau_n_deg is not None,
              "tau_n must carry a declared value; got {!r}".format(ct.tau_n_deg),
              code=C_TOL)
    rep.check("edge::tau_n_is_derived_not_typed",
              ct.tau_n_deg == SG.derive_tau_n_deg(ct.max_slope_deg)
              and SG.TAU_N_DERIVED_FROM == "max_slope_deg",
              "tau_n must come from derive_tau_n_deg(theta_max), so 44.0 is typed "
              "once; got tau_n={!r} vs derivation {!r}".format(
                  ct.tau_n_deg, SG.derive_tau_n_deg(ct.max_slope_deg)), code=C_TOL)
    rep.check("edge::tau_n_ceiling_is_two_theta_max",
              ct.tau_n_ceiling_deg == 2.0 * ct.max_slope_deg,
              "two SUPPORTED normals each lie within theta_max of up, so they "
              "are at most 2*theta_max apart", code=C_TOL)
    rep.check("edge::tau_n_is_not_vacuous",
              ct.tau_n_is_vacuous is False
              and 0.0 < ct.tau_n_deg < ct.tau_n_ceiling_deg,
              "tau_n must sit strictly inside (0, 2*theta_max); at or above the "
              "ceiling it can never fire and the declaration would be a lie. "
              "tau_n={} ceiling={}".format(ct.tau_n_deg, ct.tau_n_ceiling_deg),
              code=C_TOL)

    # The vacuity claim, proved rather than asserted: a tau_n AT the ceiling
    # cannot fire even for the sharpest crest two supported cells can form.
    sharp = []
    for (i, j) in SG.sample_indices(1):
        n = _tilt(ct.max_slope_deg, 180.0 if i <= 0 else 0.0)
        sharp.append(_cell(i, j, normal=n))
    g_ceil = SG.derive_grid(sharp, (0.0, 0.0), 100.0, 100.0,
                            tol=SG.SupportTolerances(
                                tau_n_deg=ct.tau_n_ceiling_deg))
    rep.check("edge::tau_n_at_ceiling_is_provably_vacuous",
              not any(SG.TERM_NORMAL_DISCONTINUITY in c.edge_terms
                      for c in g_ceil.cells),
              "with two faces each at exactly theta_max in opposing directions — "
              "the largest separation two supported cells can exhibit — a tau_n "
              "of 2*theta_max still does not fire. That is why the ceiling is NOT "
              "the declaration", code=C_EDGE)

    # --- the refusal path is still live and still refuses ------------------ #
    refused_tol = SG.TOLERANCES_TAU_N_REFUSED
    rep.check("edge::refused_tolerance_set_exists",
              refused_tol.tau_n_deg is None and not refused_tol.tau_n_declared,
              "a tolerance set with tau_n genuinely absent must remain "
              "constructible, or the refusal machinery is untestable and rots",
              code=C_TOL)

    try:
        refused_tol.cos_tau_n
        refused = False
    except SG.UndeclaredToleranceError:
        refused = True
    rep.check("edge::tau_n_evaluation_is_refused", refused,
              "reading cos(tau_n) on a set with no tau_n must RAISE, not return a "
              "default — a silently-chosen tau_n is exactly the cross-language "
              "drift this module exists to prevent", code=C_TOL)

    try:
        SG.derive_edges([], 0, refused_tol, refuse_undeclared_tau_n=False)
        refused2 = False
    except SG.UndeclaredToleranceError:
        refused2 = True
    rep.check("edge::cannot_opt_out_of_the_refusal", refused2,
              "asking for a full tau_n evaluation without a declared tau_n must "
              "raise; there is no default to fall back to", code=C_TOL)

    # With tau_n refused, a supported cell with neighbours is INDETERMINATE.
    g3 = SG.derive_grid(_flat_grid(1), (0.0, 0.0), 100.0, 100.0, tol=refused_tol)
    rep.check("edge::refused_tau_n_yields_indeterminate",
              all(c.edge is None for c in g3.cells),
              "with tau_n refused, no supported cell that has a neighbour can be "
              "proved NOT to be an edge; edge must be None, never False",
              code=C_EDGE)
    rep.check("edge::refused_tau_n_never_false",
              not any(c.edge is False for c in g3.cells if c.supported is True),
              "a refused term must never be silently read as 'did not fire'",
              code=C_EDGE)
    rep.check("edge::indeterminate_resolves_to_unknown",
              all(c.resolved_class == SG.CLS_UNKNOWN for c in g3.cells),
              "fail-closed: an indeterminate edge collapses to unknown, not to "
              "valid_support", code=C_FAILCLOSED)
    rep.check("edge::tau_n_evaluated_flag_is_honest",
              g3.tau_n_evaluated is False and g2.tau_n_evaluated is True,
              "GridResult must state whether the tau_n term was evaluated",
              code=C_EDGE)

    # The declared tau_n RESOLVES the indeterminacy the refusal created — this
    # is the whole point of declaring it, so it is asserted, not assumed.
    g3d = SG.derive_grid(_flat_grid(1), (0.0, 0.0), 100.0, 100.0)
    rep.check("edge::declared_tau_n_resolves_a_flat_grid",
              all(c.edge is False for c in g3d.cells)
              and all(c.resolved_class == SG.CLS_VALID for c in g3d.cells)
              and g3d.tau_n_evaluated is True,
              "with tau_n declared, a uniform flat grid must resolve to "
              "valid_support throughout instead of the r1 pile of `unknown`; got "
              "{}".format(g3d.counts()), code=C_EDGE)

    # A proved edge is still proved even with tau_n refused.
    cells2 = [c for c in _flat_grid(1) if (c.i, c.j) != (1, 0)] + [_miss(1, 0)]
    g4 = SG.derive_grid(cells2, (0.0, 0.0), 100.0, 100.0, tol=refused_tol)
    centre = {(c.i, c.j): c for c in g4.cells}[(0, 0)]
    rep.check("edge::refusal_does_not_block_a_proved_edge",
              centre.edge is True,
              "a declared term that fires still proves an edge; only the NEGATIVE "
              "is unprovable", code=C_EDGE)

    # k=0 is the one case where a non-edge IS provable without tau_n.
    g5 = SG.derive_grid([_cell(0, 0)], (0.0, 0.0), 50.0, 100.0, tol=refused_tol)
    rep.check("edge::single_cell_grid_is_provably_not_an_edge",
              g5.cells[0].edge is False
              and g5.cells[0].resolved_class == SG.CLS_VALID,
              "with no neighbours at all, no term can fire, so edge=False is "
              "provable even with tau_n refused; got edge={}".format(
                  g5.cells[0].edge), code=C_EDGE)

    # When tau_n IS declared, the normal term actually bites.
    ridge = SD._ridge_crest_cells()
    g6 = SG.derive_grid(ridge, (0.0, 0.0), 100.0, 100.0, tol=tol_n)
    fired = [c for c in g6.cells if SG.TERM_NORMAL_DISCONTINUITY in c.edge_terms]
    rep.check("edge::tau_n_term_bites_when_declared", len(fired) > 0,
              "with tau_n=30 deg declared, the ridge crest must produce "
              "normal_discontinuity edges; got {}".format(len(fired)),
              code=C_EDGE)

    # And the tau_n comparison itself avoids acos.
    rep.check("edge::tau_n_compare_avoids_acos",
              "acos" not in _executable_source("_normals_exceed_tau_n"),
              "the tau_n comparison must use cos(tau_n), not acos of the dot "
              "product", code=C_EDGE)


# --------------------------------------------------------------------------- #
# tolerance:: one declaration, cross-checked
# --------------------------------------------------------------------------- #
def _cpp_literals():
    """Parse the tolerance literals actually present in the shipping C++."""
    txt = CPP_PATH.read_text(encoding="utf-8")
    out = {}
    m = re.search(r"const float MaxSlope\s*=\s*([\d.]+)f,\s*MaxStepH\s*=\s*([\d.]+)f;",
                  txt)
    if m:
        out["MaxSlope"] = float(m.group(1))
        out["MaxStepH"] = float(m.group(2))
    m = re.search(r"ImpactPoint\.Z\s*\+\s*MaxStepH\s*\+\s*([\d.]+)f", txt)
    if m:
        out["head_lo_offset"] = float(m.group(1))
    m = re.search(r"ImpactPoint\.Z\s*\+\s*([\d.]+)f\)", txt)
    if m:
        out["head_hi"] = float(m.group(1))
    m = re.search(r"MaxStepH\s*\*\s*([\d.]+)f", txt)
    if m:
        out["tau_h_multiplier"] = float(m.group(1))
    m = re.search(r"const int32 K\s*=\s*FMath::FloorToInt\(RadiusCm\s*/\s*StepCm\);",
                  txt)
    out["k_is_floor"] = bool(m)
    out["k_is_max1"] = bool(re.search(r"FMath::Max\(1,\s*\(int32\)\(RadiusCm", txt))
    return out


def lane_tolerance(rep):
    t = SG.CONTRACT_TOLERANCES

    rep.check("tolerance::cpp_source_present", CPP_PATH.is_file(),
              "cannot cross-check without {}".format(CPP_PATH), code=C_TOL)
    if not CPP_PATH.is_file():
        return
    cpp = _cpp_literals()

    pairs = [
        ("theta_max", t.max_slope_deg, cpp.get("MaxSlope")),
        ("h_step", t.max_step_h_cm, cpp.get("MaxStepH")),
        ("head_lo_offset", t.head_clear_lo_offset_cm, cpp.get("head_lo_offset")),
        ("head_hi", t.head_clear_hi_cm, cpp.get("head_hi")),
    ]
    for name, py, c in pairs:
        rep.check("tolerance::cpp_agrees::{}".format(name), py == c,
                  "python declares {} = {!r}; SceneSurvey.cpp has {!r}".format(
                      name, py, c), code=C_TOL)
    rep.check("tolerance::cpp_agrees::tau_h_multiplier",
              cpp.get("tau_h_multiplier") == 2.0
              and t.tau_h_cm == 2.0 * t.max_step_h_cm,
              "tau_h must be 2*h_step on both sides; cpp multiplier={!r}, "
              "python tau_h={}".format(cpp.get("tau_h_multiplier"), t.tau_h_cm),
              code=C_TOL)

    # Resolution 1 must actually be in the shipping source.
    rep.check("tolerance::cpp_uses_floor_extent", cpp.get("k_is_floor") is True,
              "SceneSurvey.cpp must compute K = FMath::FloorToInt(RadiusCm/StepCm)",
              code=C_GEOM)
    rep.check("tolerance::cpp_dropped_max1_extent", cpp.get("k_is_max1") is False,
              "the old FMath::Max(1, (int32)(RadiusCm/StepCm)) must be gone",
              code=C_GEOM)

    # Resolution 2 must be stated in the shipping source.
    txt = CPP_PATH.read_text(encoding="utf-8")
    rep.check("tolerance::cpp_marks_edge_diagnostic",
              "DIAGNOSTIC edge marking" in txt
              and "edge_authority=diagnostic" in txt,
              "the C++ edge flag must be marked diagnostic in the code AND in its "
              "log line, so it cannot be mistaken for the authoritative result",
              code=C_EDGE)
    rep.check("tolerance::cpp_declares_square_region",
              "AXIS_ALIGNED_SQUARE" in txt and "shape=axis_aligned_square" in txt,
              "the C++ must name its sample region shape so square and disk "
              "semantics stay distinguishable", code=C_GEOM)
    rep.check("tolerance::cpp_can_reach_trace_error",
              "CLS_TRACE_ERROR;" in txt,
              "CLS_TRACE_ERROR must be assignable, else any 'valid excludes "
              "trace_error' rail downstream is vacuous", code=C_FAILCLOSED)

    # tau_n is declared in the CONTRACT and implemented in the CANONICAL
    # authority; the C++ diagnostic pass does NOT implement it. That asymmetry
    # is documented (§5.2) and must stay true, so it is gated in both
    # directions: if someone adds a tau_n to the C++ without updating the
    # contract, or removes the diagnostic marker, this goes RED.
    #
    # Note the C++ cannot implement tau_n with a comparison alone: pass 1 stores
    # only ImpactPoint.Z into GridZ (SceneSurvey.cpp:140) and discards the
    # normal, so pass 2 (:184-200) has no per-cell normal to compare. Closing
    # this needs a per-cell normal map, which is native-collector work (§10).
    pass2 = txt.split("// Pass 2", 1)[-1].split("// Tally", 1)[0]
    rep.check("tolerance::cpp_pass2_still_has_no_normal_term",
              "ImpactNormal" not in pass2 and "GridN" not in pass2,
              "SceneSurvey.cpp pass 2 must still contain NO normal term. If a "
              "tau_n was added natively, contract §5.2 and the tau_n_ridge_crest "
              "fixture are both stale and must be updated with it", code=C_EDGE)
    rep.check("tolerance::cpp_retains_no_per_cell_normal",
              "TMap<int64, FVector>" not in txt and "TMap<int64,FVector>" not in txt,
              "pass 1 must still discard the normal (only GridZ is retained); if "
              "a normal map appeared, the native tau_n blocker in §5.2 is stale",
              code=C_EDGE)
    rep.check("tolerance::cpp_has_no_tau_n_literal",
              not re.search(r"(?m)^\s*(?!//).*\bTauN\b", txt),
              "tau_n must not appear as executable C++ while §5.2 says the "
              "native pass does not implement it", code=C_TOL)

    # Cross-check against the other Python declaration of the same numbers.
    try:
        import scene_survey_evidence as EV
        ev_ok = True
    except Exception as exc:  # pragma: no cover
        ev_ok = False
        rep.check("tolerance::evidence_import", False,
                  "could not import scene_survey_evidence: {}".format(exc),
                  code=C_TOL)
    if ev_ok:
        rep.check("tolerance::evidence_agrees::theta_max",
                  EV.GROUND_MAX_SLOPE_DEG == t.max_slope_deg,
                  "scene_survey_evidence.GROUND_MAX_SLOPE_DEG={} vs canonical "
                  "theta_max={}".format(EV.GROUND_MAX_SLOPE_DEG, t.max_slope_deg),
                  code=C_TOL)
        rep.check("tolerance::evidence_agrees::h_step",
                  EV.GROUND_DZ_TOLERANCE_CM == t.max_step_h_cm,
                  "scene_survey_evidence.GROUND_DZ_TOLERANCE_CM={} vs canonical "
                  "h_step={}".format(EV.GROUND_DZ_TOLERANCE_CM, t.max_step_h_cm),
                  code=C_TOL)
        rep.check("tolerance::evidence_agrees::cos_theta_max",
                  EV.GROUND_MAX_SLOPE_COS == t.cos_max_slope,
                  "the precomputed cosines must be bit-identical: {!r} vs {!r}"
                  .format(EV.GROUND_MAX_SLOPE_COS, t.cos_max_slope), code=C_TOL)

    # The class vocabulary must match the contract spine exactly.
    try:
        import scene_survey_contracts as SS
        rep.check("tolerance::support_class_vocabulary_matches",
                  tuple(SS.SUPPORT_CLASSES) == ("valid_support", "unsupported",
                                                "edge", "blocked", "trace_error",
                                                "unknown")
                  and tuple(SG.SUPPORT_CLASSES) == tuple(SS.SUPPORT_CLASSES),
                  "canonical SUPPORT_CLASSES={} vs contract spine {}".format(
                      SG.SUPPORT_CLASSES, SS.SUPPORT_CLASSES), code=C_TOL)
        rep.check("tolerance::valid_support_classes_match",
                  tuple(SG.VALID_SUPPORT_CLASSES) == tuple(SS.VALID_SUPPORT_CLASSES),
                  "only valid_support may count as support on both sides",
                  code=C_FAILCLOSED)
    except Exception as exc:  # pragma: no cover
        rep.check("tolerance::contracts_import", False,
                  "could not import scene_survey_contracts: {}".format(exc),
                  code=C_TOL)

    # Region-shape modes must stay named and distinguishable.
    rep.check("tolerance::square_and_disk_are_named",
              SG.SHAPE_SQUARE in SG.SAMPLE_REGION_SHAPES
              and SG.SHAPE_DISK in SG.SAMPLE_REGION_SHAPES
              and SG.IMPLEMENTED_SAMPLE_REGION_SHAPES == (SG.SHAPE_SQUARE,),
              "both region modes must have names, and only the square one may be "
              "implemented", code=C_GEOM)
    try:
        SG.derive_grid([_cell(0, 0)], (0.0, 0.0), 50.0, 100.0,
                       sample_region_shape=SG.SHAPE_DISK)
        ok = False
    except SG.ContractViolation:
        ok = True
    rep.check("tolerance::disk_mode_is_refused_not_aliased", ok,
              "asking for the disk region must raise, never silently run the "
              "square one", code=C_GEOM)


# --------------------------------------------------------------------------- #
# identity:: canonical sample identity (contract §1.4)
# --------------------------------------------------------------------------- #
#: The literal golden for k=1. Written out rather than generated, so a change to
#: the id scheme cannot quietly agree with itself.
GOLDEN_SAMPLE_IDS_K1 = (
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=-1|j=-1",
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=-1|j=+0",
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=-1|j=+1",
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+0|j=-1",
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+0|j=+0",
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+0|j=+1",
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+1|j=-1",
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+1|j=+0",
    "wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+1|j=+1",
)


def lane_identity(rep):
    g = SG.derive_grid(_flat_grid(1), (0.0, 0.0), 100.0, 100.0)
    ids = g.sample_ids()

    rep.check("identity::matches_golden_k1", ids == GOLDEN_SAMPLE_IDS_K1,
              "sample ids drifted from the written golden.\n  got  {}\n  want {}"
              .format(ids[:3], GOLDEN_SAMPLE_IDS_K1[:3]), code=C_RAW)

    rep.check("identity::version_is_carried",
              all(s.startswith(SG.SUPPORT_GRID_CONTRACT_VERSION + "|") for s in ids)
              and SG.SUPPORT_GRID_CONTRACT_VERSION.endswith(
                  ".r{}".format(SG.SUPPORT_GRID_CONTRACT_REVISION)),
              "every id must carry the contract version; semantics changed between "
              "r1 (tau_n refused) and r2 (tau_n declared), so ids minted under the "
              "two must not compare equal", code=C_RAW)

    rep.check("identity::shape_name_is_not_abbreviated",
              all("|" + SG.SHAPE_SQUARE + "|" in s for s in ids),
              "contract §1.2 forbids square/disk from being silently substituted; "
              "the id carries the full declared NAME, never an abbreviation",
              code=C_GEOM)

    # Uniqueness within one operation.
    rep.check("identity::unique_within_an_operation",
              len(set(ids)) == len(ids) == g.nominal_count,
              "ids must be pairwise distinct across the grid; got {} unique of {}"
              .format(len(set(ids)), len(ids)), code=C_RAW)

    # Determinism: repeated generation, and generation from a permuted input.
    g_again = SG.derive_grid(_flat_grid(1), (0.0, 0.0), 100.0, 100.0)
    shuffled = list(_flat_grid(1))
    shuffled.reverse()
    g_shuf = SG.derive_grid(shuffled, (0.0, 0.0), 100.0, 100.0)
    rep.check("identity::stable_across_repeated_generation",
              g_again.sample_ids() == ids and g_shuf.sample_ids() == ids,
              "sample ids must be a pure function of (version, shape, k, i, j); "
              "regeneration and input permutation must not move them", code=C_RAW)

    # No float, no anchor, no spacing may leak in.
    g_moved = SG.derive_grid(_flat_grid(1, step=250.0), (7331.5, -12.25),
                             250.0, 250.0)
    rep.check("identity::anchor_and_spacing_do_not_leak_in",
              g_moved.sample_ids() == ids,
              "the identity is operation-LOCAL: it names a cell within a grid, not "
              "a place in the world. Admitting the anchor or the spacing would put "
              "a float in the id, and floats are exactly what fails to round-trip "
              "across the language boundary (§1.3)", code=C_RAW)

    # k is part of the identity: the same (i,j) at a different extent is a
    # different observation (§5.1 perimeter asymmetry).
    g2 = SG.derive_grid(_flat_grid(2), (0.0, 0.0), 200.0, 100.0)
    rep.check("identity::k_disambiguates_perimeter_from_interior",
              g2.sample_id_for(1, 0) != g.sample_id_for(1, 0),
              "(1,0) is a 3-neighbour perimeter cell at k=1 and a 4-neighbour "
              "interior cell at k=2; without k in the id those two "
              "non-interchangeable observations would collide", code=C_RAW)

    # Sign is always explicit, so 0 and -0 cannot both exist.
    rep.check("identity::zero_is_signed_exactly_one_way",
              "i=+0" in g.sample_id_for(0, 0) and "j=+0" in g.sample_id_for(0, 0)
              and "i=-0" not in g.sample_id_for(0, 0),
              "the sign is always explicit and always '+' for zero; got {}"
              .format(g.sample_id_for(0, 0)), code=C_RAW)

    # Round-trip. A parser that accepts what it did not emit hides corruption.
    rep.check("identity::round_trips",
              all(SG.sample_id(f["k"], f["i"], f["j"], f["sample_region_shape"]) == s
                  for s, f in ((s, SG.parse_sample_id(s)) for s in ids)),
              "parse_sample_id must invert sample_id exactly", code=C_RAW)

    for bad, why in (
            ("nope", "not enough fields"),
            ("wf.support_grid.v2_6.r1|axis_aligned_square|k=1|i=+0|j=+0",
             "wrong contract revision"),
            ("wf.support_grid.v2_6.r2|axis_aligned_disk|k=1|i=+0|j=+0",
             "shape is declared but the grid is square-only — still parses, so "
             "this one must be REJECTED downstream, not here"),
            ("wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=0|j=+0",
             "unsigned index"),
            ("wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+00|j=+0",
             "zero-padded index"),
            ("wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+2|j=+0",
             "index outside k"),
            ("wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=+0.0|j=+0",
             "float index"),
    ):
        if "still parses" in why:
            continue
        try:
            SG.parse_sample_id(bad)
            ok = False
        except SG.ContractViolation:
            ok = True
        rep.check("identity::rejects::{}".format(why.split(" ")[0] + "_"
                                                 + why.split(" ")[1]), ok,
                  "parse_sample_id must reject {!r} ({})".format(bad, why),
                  code=C_RAW)

    # A float index must never be rounded into an id.
    try:
        SG.sample_id(1, 0.0, 0)
        ok = False
    except SG.ContractViolation:
        ok = True
    rep.check("identity::float_index_is_refused_not_rounded", ok,
              "sample_id(1, 0.0, 0) must raise; silently rounding a float index "
              "is how a float enters an identity that must not contain one",
              code=C_RAW)

    # An id is NOT an ordering key. This is the concrete counterexample.
    rep.check("identity::lexical_sort_is_NOT_canonical_order",
              tuple(sorted(ids)) != ids,
              "if lexical sort happened to equal canonical order, somebody would "
              "rely on it. '+' (0x2B) sorts before '-' (0x2D), so \"i=+0\" "
              "precedes \"i=-1\" lexically while canonically -1 < 0", code=C_GEOM)
    rep.check("identity::sort_key_from_id_recovers_canonical_order",
              tuple(sorted(ids, key=SG.sort_key_from_sample_id)) == ids,
              "canonical order must be recoverable from ids via "
              "sort_key_from_sample_id — and only via it", code=C_GEOM)

    # --- the OTHER sample_id in this tree ---------------------------------- #
    # run_v2_6_fixture_smoke.sample_id (:424-432) mints "sample_0002_0001" from
    # SHIFTED non-negative indices, deliberately so that lexical order equals
    # canonical order — the opposite property to the one above. It is a
    # FIXTURE-LOCAL ordering token feeding that harness's id_sequence_sha256
    # (:2018-2020), not an evidence identity. Two ids with contradictory
    # ordering semantics may coexist ONLY if they can never be confused, so
    # that is what is asserted here rather than assumed.
    try:
        import run_v2_6_fixture_smoke as FS
        fs_ok = True
    except Exception as exc:  # pragma: no cover
        fs_ok = False
        rep.check("identity::fixture_smoke_import", False,
                  "could not import run_v2_6_fixture_smoke: {}".format(exc),
                  code=C_RAW)
    if fs_ok:
        fs_id = FS.sample_id(2, 1)
        rep.check("identity::fixture_token_is_not_a_canonical_identity",
                  fs_id not in ids and SG.SAMPLE_ID_SEP not in fs_id,
                  "run_v2_6_fixture_smoke.sample_id must not collide with the "
                  "canonical identity space; got {!r}".format(fs_id), code=C_RAW)
        try:
            SG.parse_sample_id(fs_id)
            disjoint = False
        except SG.ContractViolation:
            disjoint = True
        rep.check("identity::fixture_token_is_rejected_by_the_canonical_parser",
                  disjoint,
                  "the canonical parser must REFUSE a fixture ordering token "
                  "({!r}), so a fixture-local string can never be filed as "
                  "evidence identity".format(fs_id), code=C_RAW)


# --------------------------------------------------------------------------- #
# golden:: written-out expected values (contract §9)
# --------------------------------------------------------------------------- #
def lane_golden(rep):
    # --- extent goldens, including non-integral R/s ------------------------ #
    for label, r, s, want_k in (
            ("R_lt_s", 50.0, 100.0, 0),
            ("R_eq_s", 100.0, 100.0, 1),
            ("R_2p5_s", 250.0, 100.0, 2),        # 2.5  -> floor 2
            ("R_3p33_s", 100.0, 30.0, 3),        # 3.33 -> floor 3
            ("R_0p99_s", 99.0, 100.0, 0),        # 0.99 -> floor 0
            ("R_7p9_s", 79.0, 10.0, 7),          # 7.9  -> floor 7
    ):
        got = SG.grid_extent_k(r, s)
        rep.check("golden::extent::{}".format(label), got == want_k,
                  "R={} s={}: k={} expected {} (a non-integral quotient must "
                  "FLOOR, never round)".format(r, s, got, want_k), code=C_GEOM)

    # R < s: exactly one sample, and it sits ON the anchor.
    pts = SG.sample_points((11.0, -7.0), 50.0, 100.0)
    rep.check("golden::R_lt_s_is_one_sample_at_the_anchor",
              pts == ((0, 0, 11.0, -7.0),),
              "R<s must yield exactly the centre sample, placed at the anchor; "
              "got {}".format(pts), code=C_GEOM)

    # R == s: the full 3x3, in canonical order, with exact coordinates.
    rep.check("golden::R_eq_s_is_the_full_3x3",
              SG.sample_points((0.0, 0.0), 100.0, 100.0) == (
                  (-1, -1, -100.0, -100.0), (-1, 0, -100.0, 0.0),
                  (-1, 1, -100.0, 100.0), (0, -1, 0.0, -100.0),
                  (0, 0, 0.0, 0.0), (0, 1, 0.0, 100.0),
                  (1, -1, 100.0, -100.0), (1, 0, 100.0, 0.0),
                  (1, 1, 100.0, 100.0)),
              "R==s must yield the full 3x3 in canonical order with exact "
              "coordinates", code=C_GEOM)

    # --- spacing / radius rejection ---------------------------------------- #
    for r, s, why in ((100.0, 0.0, "zero spacing"),
                      (100.0, -100.0, "negative spacing"),
                      (100.0, -1e-9, "tiny negative spacing"),
                      (0.0, 100.0, "zero radius"),
                      (-100.0, 100.0, "negative radius"),
                      (float("nan"), 100.0, "NaN radius"),
                      (float("inf"), 100.0, "infinite radius"),
                      (100.0, float("nan"), "NaN spacing")):
        try:
            SG.grid_extent_k(r, s)
            ok = False
        except SG.ContractViolation:
            ok = True
        rep.check("golden::rejects::{}".format(why.replace(" ", "_")), ok,
                  "R={} s={} ({}) must raise ContractViolation, never be clamped "
                  "or defaulted".format(r, s, why), code=C_GEOM)

    # --- square vs disk are DIFFERENT SETS, not a rendering choice --------- #
    k = 2
    square = set(SG.sample_indices(k))
    disk = {(i, j) for (i, j) in square if i * i + j * j <= k * k}
    corners = square - disk
    #: The 12 cells at k=2 that the square includes and the disk predicate of
    #: contract §1.2 (i^2 + j^2 <= (R/s)^2) excludes. Written out, because "the
    #: corners" is the intuitive answer and it is WRONG — (1,2) is at radius
    #: sqrt(5) > 2 and is excluded too. The two shapes differ by nearly half the
    #: perimeter, which is exactly why §1.2 forbids substituting one for the
    #: other.
    GOLDEN_DISK_EXCLUDED_K2 = {
        (-2, -2), (-2, -1), (-2, 1), (-2, 2),
        (-1, -2), (-1, 2), (1, -2), (1, 2),
        (2, -2), (2, -1), (2, 1), (2, 2),
    }
    rep.check("golden::square_and_disk_differ",
              len(square) == 25 and len(disk) == 13
              and corners == GOLDEN_DISK_EXCLUDED_K2,
              "at k=2 the square has 25 cells and the disk predicate "
              "i^2+j^2<=k^2 admits 13; 12 cells are the difference. "
              "got square={} disk={} excluded={}".format(
                  len(square), len(disk), sorted(corners)), code=C_GEOM)
    rep.check("golden::disk_is_named_but_unimplemented",
              SG.SHAPE_DISK in SG.SAMPLE_REGION_SHAPES
              and SG.SHAPE_DISK not in SG.IMPLEMENTED_SAMPLE_REGION_SHAPES,
              "the disk mode must have a NAME (so it can be declared under) and "
              "must not be implemented (so it cannot be silently assumed)",
              code=C_GEOM)
    try:
        SG.derive_grid([_cell(0, 0)], (0.0, 0.0), 50.0, 100.0,
                       sample_region_shape=SG.SHAPE_DISK)
        ok = False
    except SG.ContractViolation:
        ok = True
    rep.check("golden::disk_request_raises", ok,
              "asking for the disk region must raise, never quietly run the "
              "square one", code=C_GEOM)

    # --- canonical ordering, written out ----------------------------------- #
    rep.check("golden::canonical_order_k1",
              SG.sample_indices(1) == ((-1, -1), (-1, 0), (-1, 1),
                                       (0, -1), (0, 0), (0, 1),
                                       (1, -1), (1, 0), (1, 1)),
              "i ascending OUTER, j ascending INNER (contract §6, "
              "SceneSurvey.cpp:111-113); got {}".format(SG.sample_indices(1)),
              code=C_GEOM)

    # --- normal discontinuity: below / at / above tau_n -------------------- #
    t = SG.CONTRACT_TOLERANCES

    def normal_term_fired(n_a, n_b):
        """A 1x2 strip: cell (0,0) with n_a, cell (1,0) with n_b, same Z.

        Same Z everywhere, so tau_h can never fire; both normals are within
        theta_max of up, so both cells are SUPPORTED and the neighbour-
        unsupported term can never fire either. The ONLY disjunct that can
        fire is the normal-discontinuity term.
        """
        cells = []
        for (i, j) in SG.sample_indices(1):
            cells.append(_cell(i, j, normal=(n_b if i > 0 else n_a)))
        g = SG.derive_grid(cells, (0.0, 0.0), 100.0, 100.0)
        by = {(c.i, c.j): c for c in g.cells}
        assert all(c.supported is True for c in g.cells), "fixture is not all-supported"
        return any(SG.TERM_NORMAL_DISCONTINUITY in c.edge_terms for c in g.cells), by

    up = (0.0, 0.0, 1.0)

    # BELOW: 43 deg apart. Under tau_n=44 -> no edge.
    fired_below, _ = normal_term_fired(up, _tilt(43.0))
    rep.check("golden::tau_n_below_threshold_is_not_an_edge", not fired_below,
              "a 43 deg neighbour turn is below tau_n={} and must NOT fire the "
              "normal term".format(t.tau_n_deg), code=C_EDGE)

    # AT: exactly tau_n. The predicate is strictly `>`, so equality is NOT an
    # edge. Built as up vs _tilt(tau_n) so the dot product is bit-identical to
    # cos_tau_n rather than merely close to it.
    fired_at, _ = normal_term_fired(up, _tilt(t.tau_n_deg))
    rep.check("golden::tau_n_at_threshold_is_not_an_edge", not fired_at,
              "a turn of exactly tau_n={} must NOT fire — the predicate is "
              "strictly greater-than, matching tau_h at SceneSurvey.cpp:195"
              .format(t.tau_n_deg), code=C_EDGE)

    # ABOVE: 46 deg apart, split 23/-23 so BOTH cells stay standable.
    fired_above, by_above = normal_term_fired(_tilt(23.0, 180.0), _tilt(23.0, 0.0))
    rep.check("golden::tau_n_above_threshold_is_an_edge", fired_above,
              "a 46 deg neighbour turn exceeds tau_n={} and must fire the normal "
              "term; both faces are standable (23 deg < theta_max) so no other "
              "disjunct can be doing the work".format(t.tau_n_deg), code=C_EDGE)
    rep.check("golden::tau_n_above_names_the_term_that_fired",
              by_above[(0, 0)].edge_terms == (SG.TERM_NORMAL_DISCONTINUITY,),
              "exactly the normal-discontinuity term must be named, so a fired "
              "edge is attributable; got {}".format(by_above[(0, 0)].edge_terms),
              code=C_EDGE)

    # --- cross-language golden: EXPECTED TO DIVERGE ------------------------ #
    # Contract §9 says two implementations conform when they produce identical
    # raw records. For the tau_n term they CANNOT, and this is the golden that
    # says so out loud rather than omitting the comparison.
    #
    # This check is written in the "still broken" polarity on purpose: it PASSES
    # while the native gap exists and goes RED the moment the C++ gains the term,
    # which is when §5.2, the ledger and this golden all need updating together.
    # An xfail that silently skips would let the gap close unnoticed.
    ridge = SD._ridge_crest_cells()
    native = SD._native_model_classify(ridge, k=1)
    canon = SG.derive_grid(ridge, (0.0, 0.0), 100.0, 100.0)
    native_edges = sum(1 for v in native.values() if v == SD._NATIVE_EDGE)
    canon_edges = sum(1 for c in canon.cells if c.edge is True)
    rep.check("golden::XFAIL::cpp_cannot_reproduce_tau_n_edges",
              native_edges == 0 and canon_edges == 6,
              "EXPECTED-TO-DIVERGE, and it must keep diverging exactly this way: "
              "on the {} deg ridge crest the canonical authority proves {} edges "
              "and the native pass finds {}. The C++ cannot be brought into line "
              "by adding a comparison — SceneSurvey.cpp:140 stores only "
              "ImpactPoint.Z into GridZ, so pass 2 (:184-200) has no per-cell "
              "normal to compare and needs a normal map first. HANDOFF ITEM for "
              "the native-collector promotion (§10); this lane may not edit C++."
              .format(SD._RIDGE_NEIGHBOUR_SEPARATION_DEG, canon_edges,
                      native_edges),
              code=C_DIVERGE)


# --------------------------------------------------------------------------- #
# divergence:: documented native/canonical discrepancies
# --------------------------------------------------------------------------- #
def lane_divergence(rep):
    results = SD.run_all()
    rep.check("divergence::registry_non_empty", len(results) >= 6,
              "expected at least 6 documented divergences, got {}".format(
                  len(results)), code=C_DIVERGE)
    for d, holds, detail in results:
        rep.check("divergence::{}::still_holds".format(d.fixture_id), holds,
                  "[{}] {} | {} | {}".format(d.status, d.summary,
                                             d.cpp_citation, detail),
                  code=C_DIVERGE)
        rep.check("divergence::{}::documented".format(d.fixture_id),
                  bool(d.native and d.canonical and d.why_it_matters
                       and d.cpp_citation),
                  "every divergence needs native/canonical answers, a citation, "
                  "and a stated consequence", code=C_DIVERGE)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    strict = args.strict or strict_from_env()

    rep = ValidationReport("support_grid", "v2_6_support_grid", strict=strict)
    for lane in (lane_extent, lane_order, lane_neighbour, lane_tristate,
                 lane_support, lane_edge, lane_identity, lane_golden,
                 lane_tolerance, lane_divergence):
        lane(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="python tools/pipeline/support_grid_conformance.py",
        pack=None, strict=strict, status=rep.status,
        failure_count=len(rep.failures), warning_count=len(rep.warnings),
        record_count=len(rep.checks), report_type=REPORT_TYPE))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, REPORT_NAME, quiet=args.quiet)
    rep.print_summary("support_grid")

    if not args.quiet:
        print("\n[support_grid] divergence ledger")
        for d, holds, detail in SD.run_all():
            print("  {:28} {:24} {}".format(
                d.fixture_id, d.status, "HOLDS" if holds else "CHANGED"))
            print("      {}".format(detail))

    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
