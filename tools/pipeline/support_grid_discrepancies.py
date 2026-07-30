#!/usr/bin/env python3
"""support_grid_discrepancies.py — cross-language DIVERGENCE fixtures for v2.6.

Every fixture here is a case where the NATIVE support classification
(``Plugins/WorldForge/Source/WorldForgeCore/Private/SceneSurvey.cpp``) and the
CANONICAL support mathematics (``support_grid_canonical.py``) give different
answers for the same world.

These are documented on purpose. A divergence that is written down, cited, and
asserted by a test is a known limit; a divergence discovered later in a report is
an unattributable bug. ``support_grid_conformance.py`` asserts that every fixture
STILL diverges exactly as described — so if someone fixes the C++ without
updating this file, the harness goes RED and forces the doc to catch up.

WARNING — the ``_native_model_*`` functions below are a **MODEL** of the shipping
C++, written from a line-by-line reading and cited accordingly. They are NOT an
authority, they are not a second implementation anybody may classify with, and
nothing outside this module may import them. Their only job is to make the
divergence mechanically checkable without an editor.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import support_grid_canonical as SG  # noqa: E402

CPP_REL = "Plugins/WorldForge/Source/WorldForgeCore/Private/SceneSurvey.cpp"

# Fixture status vocabulary — bounded on purpose.
ST_RESOLVED = "resolved_by_lane5"          # the C++ was changed; kept as regression
ST_OPEN_OPERATOR = "open_operator_decision"  # needs a declared value / ruling
ST_ACCEPTED = "accepted_divergence"        # native is weaker by design; documented


# --------------------------------------------------------------------------- #
# A MODEL of the shipping C++. Not an authority. See module warning.
# --------------------------------------------------------------------------- #
_NATIVE_VALID = "valid"
_NATIVE_UNSUPPORTED = "unsupported"
_NATIVE_EDGE = "edge"
_NATIVE_BLOCKED = "blocked"
_NATIVE_TRACE_ERROR = "trace_error"
_NATIVE_UNKNOWN = "unknown"

_NATIVE_MAX_SLOPE = 44.0   # SceneSurvey.cpp:90  MaxSlope
_NATIVE_MAX_STEP_H = 45.0  # SceneSurvey.cpp:90  MaxStepH


def _native_model_k(radius_cm: float, step_cm: float, *, pre_lane5: bool) -> int:
    """Grid half-extent index as the C++ computes it.

    ``pre_lane5=True``  -> ``FMath::Max(1, (int32)(RadiusCm / StepCm))`` (the old line 90)
    ``pre_lane5=False`` -> ``FMath::FloorToInt(RadiusCm / StepCm)``      (SceneSurvey.cpp:103)
    """
    q = int(radius_cm / step_cm)  # C-style truncation; R,s > 0 so == floor
    return max(1, q) if pre_lane5 else int(math.floor(radius_cm / step_cm))


def _native_model_classify(cells: Sequence[SG.RawCell], k: int) -> Dict[Tuple[int, int], str]:
    """Two passes exactly as SceneSurvey.cpp:110-203 performs them.

    Pass 1 (SceneSurvey.cpp:110-157):
      no hit                      -> unsupported            (:123)
      NaN / degenerate geometry   -> trace_error            (:125-134)
      degrees(acos(clamp(n.Z)))>44-> blocked                (:138-143)
      head trace hits             -> blocked, else valid    (:147-152)
    Pass 2 (SceneSurvey.cpp:176-203):
      neighbour missing from map  -> SKIPPED, not an edge   (:188)
      neighbour in {unsupported, trace_error, unknown} -> edge  (:189)
      |dz| > MaxStepH*2           -> edge                   (:195)
      NOTE: a BLOCKED neighbour does not trigger an edge (:189 omits CLS_BLOCKED),
      and there is NO normal-discontinuity term at all.
    """
    cls: Dict[Tuple[int, int], str] = {}
    gridz: Dict[Tuple[int, int], float] = {}

    for c in cells:
        key = (c.i, c.j)
        g = c.ground
        if g.hit is None:
            # The C++ has no representation for "the trace did not run": the
            # engine call returns a bool. Modelled as trace_error to match the
            # NaN/degenerate branch, which is the nearest native state.
            cls[key] = _NATIVE_TRACE_ERROR
            continue
        if g.hit is False:
            cls[key] = _NATIVE_UNSUPPORTED
            continue
        n = g.normal
        p = g.impact_point
        bad_geo = (not SG._is_finite_vec(p) or not SG._is_finite_vec(n)
                   or (n is not None
                       and math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) <= 1e-4))
        if bad_geo:
            cls[key] = _NATIVE_TRACE_ERROR
            continue
        gridz[key] = float(p[2])
        # Raw ImpactNormal.Z — the C++ does NOT normalise (SceneSurvey.cpp:138-139).
        slope = math.degrees(math.acos(max(-1.0, min(1.0, n[2]))))
        if slope > _NATIVE_MAX_SLOPE:
            cls[key] = _NATIVE_BLOCKED
            continue
        head_blocked = bool(c.head is not None and c.head.hit is True)
        cls[key] = _NATIVE_BLOCKED if head_blocked else _NATIVE_VALID

    for (i, j) in SG.sample_indices(k):
        if cls.get((i, j)) != _NATIVE_VALID:
            continue
        z = gridz.get((i, j))
        for (di, dj) in SG.NEIGHBOUR_DELTAS:
            nk = (i + di, j + dj)
            nc = cls.get(nk)
            if nc is None:
                continue  # off-grid neighbour: not evidence of an edge (:188)
            if nc in (_NATIVE_UNSUPPORTED, _NATIVE_TRACE_ERROR, _NATIVE_UNKNOWN):
                cls[(i, j)] = _NATIVE_EDGE
                break
            nz = gridz.get(nk)
            if z is not None and nz is not None and abs(z - nz) > _NATIVE_MAX_STEP_H * 2.0:
                cls[(i, j)] = _NATIVE_EDGE
                break
    return cls


# --------------------------------------------------------------------------- #
# Fixture scaffolding
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Discrepancy:
    fixture_id: str
    status: str
    summary: str
    cpp_citation: str
    native: str          # what the native path answers
    canonical: str       # what the canonical authority answers
    why_it_matters: str
    check: Callable[[], Tuple[bool, str]]   # -> (divergence_still_holds, detail)


def _flat_ground_cell(i: int, j: int, z: float = 0.0,
                      normal=(0.0, 0.0, 1.0), head_hit: bool = False) -> SG.RawCell:
    """A cell whose ground trace hit and whose head trace ran."""
    x, y = float(i) * 100.0, float(j) * 100.0
    return SG.RawCell(
        i=i, j=j,
        ground=SG.RawTrace(trace_start=(x, y, z + 1000.0), trace_end=(x, y, z - 3000.0),
                           hit=True, impact_point=(x, y, z), normal=normal,
                           actor_path="/Game/Fixture.Floor", component_path="Root"),
        head=SG.RawTrace(trace_start=(x, y, z + 50.0), trace_end=(x, y, z + 176.0),
                         hit=head_hit,
                         impact_point=(x, y, z + 120.0) if head_hit else None,
                         normal=(0.0, 0.0, -1.0) if head_hit else None))


def _missing_ground_cell(i: int, j: int) -> SG.RawCell:
    """A cell whose ground trace ran and cleanly missed (hit=False, no geometry)."""
    x, y = float(i) * 100.0, float(j) * 100.0
    return SG.RawCell(
        i=i, j=j,
        ground=SG.RawTrace(trace_start=(x, y, 1000.0), trace_end=(x, y, -3000.0),
                           hit=False),
        head=None)


def _tilted_normal(deg_from_up: float, azimuth_deg: float = 0.0
                   ) -> Tuple[float, float, float]:
    t = math.radians(deg_from_up)
    a = math.radians(azimuth_deg)
    return (math.sin(t) * math.cos(a), math.sin(t) * math.sin(a), math.cos(t))


# --------------------------------------------------------------------------- #
# Fixture 1 — grid extent when R < s   [RESOLVED by lane 5]
# --------------------------------------------------------------------------- #
def _check_extent_r_lt_s() -> Tuple[bool, str]:
    r, s = 50.0, 100.0
    old = _native_model_k(r, s, pre_lane5=True)
    new = _native_model_k(r, s, pre_lane5=False)
    canon = SG.grid_extent_k(r, s)
    diverged_before = (old != canon)
    agrees_now = (new == canon == 0)
    # The old formula reached +/- s = 100cm, i.e. outside the 50cm half-extent.
    over_extension_cm = old * s
    ok = diverged_before and agrees_now
    return ok, ("R={} s={}: pre-lane5 k={} (N={}, reach +/-{}cm, OUTSIDE the {}cm "
                "half-extent); post-lane5 k={} (N={}); canonical k={} (N={})".format(
                    r, s, old, SG.nominal_sample_count(old), over_extension_cm, r,
                    new, SG.nominal_sample_count(new),
                    canon, SG.nominal_sample_count(canon)))


# --------------------------------------------------------------------------- #
# Fixture 2 — float32 vs float64 quotient   [probe]
# --------------------------------------------------------------------------- #
def _check_float32_quotient() -> Tuple[bool, str]:
    """Sweep realistic (R, s) for a k that differs between float32 and float64.

    The C++ divides two ``float``s; Python divides two ``float64``s. Where the
    two floors differ, the collectors disagree on the SAMPLE COUNT itself.
    """
    bad: List[str] = []
    steps = [10.0, 25.0, 50.0, 100.0, 125.0, 250.0, 333.0, 500.0]
    for s in steps:
        r = s
        while r <= 6000.0:
            a = SG.grid_extent_k(r, s)
            b = SG.grid_extent_k_float32(r, s)
            if a != b:
                bad.append("R={} s={} f64_k={} f32_k={}".format(r, s, a, b))
            r += s / 3.0
    # The divergence is STRUCTURAL (two different float widths), so the fixture
    # always holds; the sweep only tells us whether a concrete witness exists in
    # the range the probe actually uses.
    if bad:
        return True, ("{} concrete witness(es) in the swept range; first: {}".format(
            len(bad), "; ".join(bad[:3])))
    return True, ("structural divergence (float32 quotient natively vs float64 "
                  "canonically); NO concrete witness over the swept range "
                  "(steps {}, R up to 6000cm). A sweep is not a proof of "
                  "agreement.".format(steps))


# --------------------------------------------------------------------------- #
# Fixture 3 — ridge crest, no height step   [OPEN: C++ has no tau_n term]
# --------------------------------------------------------------------------- #
#: The crest sits BETWEEN column i=0 and column i=1, so a 4-connected neighbour
#: pair genuinely straddles it. The earlier version of this fixture put a flat
#: crown row at i=0, which meant the largest separation any NEIGHBOUR pair ever
#: showed was 40 deg — the advertised "80 deg" was only ever visible between
#: i=-1 and i=+1, which are not neighbours and are never compared. The predicate
#: is 4-connected (contract §5.1), so the fixture must be too.
_RIDGE_TILT_DEG = 40.0
_RIDGE_NEIGHBOUR_SEPARATION_DEG = 2.0 * _RIDGE_TILT_DEG   # 80 deg, across i=0|1


def _ridge_crest_cells() -> List[SG.RawCell]:
    """A 3x3 patch that is a roof ridge: same Z everywhere, faces tilted +/-40
    degrees away from a crest line running between columns i=0 and i=1.

    No height step at all, so tau_h never fires; the ONLY thing that can detect
    this crest is the tau_n term. Both faces are standable (40 < theta_max=44),
    so both sides are genuinely supported and the crest is a real walk-off
    hazard rather than a wall.
    """
    cells = []
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            n = _tilted_normal(_RIDGE_TILT_DEG, 180.0 if i <= 0 else 0.0)
            cells.append(_flat_ground_cell(i, j, z=0.0, normal=n))
    return cells


def _check_tau_n_ridge_crest() -> Tuple[bool, str]:
    cells = _ridge_crest_cells()
    native = _native_model_classify(cells, k=1)
    grid = SG.derive_grid(cells, (0.0, 0.0), radius_cm=100.0, step_cm=100.0)
    canon = {(c.i, c.j): c for c in grid.cells}

    # Native: every cell is a clean `valid`, no edge anywhere. Pass 2 has no
    # normal term AND retains no normals to build one from — SceneSurvey.cpp:140
    # stores only ImpactPoint.Z into GridZ, so the normal is discarded inside the
    # pass-1 iteration and lines 184-200 could not evaluate tau_n even if it were
    # declared there.
    native_all_valid = all(v == _NATIVE_VALID for v in native.values())

    # Canonical: with tau_n DECLARED (= theta_max), the 80 deg neighbour step
    # across the crest fires the normal-discontinuity term and the cells either
    # side of the crest are PROVED edges.
    fired = [c for c in canon.values()
             if SG.TERM_NORMAL_DISCONTINUITY in c.edge_terms]
    canon_proves_edges = len(fired) == 6 and all(c.edge is True for c in fired)
    # And nothing is left indeterminate any more — that was the r1 behaviour.
    canon_none_indeterminate = all(c.edge is not None for c in canon.values())

    ok = native_all_valid and canon_proves_edges and canon_none_indeterminate
    return ok, ("ridge crest (|dz|=0, {} deg between the 4-connected neighbours "
                "straddling the crest): native = {} valid / 0 edge; canonical = "
                "{} cells proved `edge` via normal_discontinuity. The normal step "
                "is invisible to the native predicate — SceneSurvey.cpp:184-200 "
                "has no tau_n term and :140 keeps no normal to build one from."
                .format(_RIDGE_NEIGHBOUR_SEPARATION_DEG,
                        sum(1 for v in native.values() if v == _NATIVE_VALID),
                        len(fired)))


# --------------------------------------------------------------------------- #
# Fixture 4 — a BLOCKED neighbour is not an edge natively   [new finding]
# --------------------------------------------------------------------------- #
def _check_blocked_neighbour() -> Tuple[bool, str]:
    """A supported cell adjacent to a too-steep cell.

    Canonical: ``NOT S_q`` holds (a blocked cell is not supported), so the
    supported cell IS an edge. Native: ``SceneSurvey.cpp:189`` tests only
    ``CLS_UNSUPPORTED / CLS_TRACE_ERROR / CLS_UNKNOWN`` — ``CLS_BLOCKED`` is
    omitted, so the same cell stays plain ``valid``. This is a standing-on-the-
    lip-of-a-cliff-face case, and the native answer is the unsafe one.
    """
    cells = []
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            if (i, j) == (1, 0):
                cells.append(_flat_ground_cell(i, j, z=0.0,
                                               normal=_tilted_normal(70.0)))
            else:
                cells.append(_flat_ground_cell(i, j, z=0.0))
    native = _native_model_classify(cells, k=1)
    grid = SG.derive_grid(cells, (0.0, 0.0), radius_cm=100.0, step_cm=100.0)
    canon = {(c.i, c.j): c for c in grid.cells}

    native_centre = native[(0, 0)]
    canon_centre = canon[(0, 0)]
    ok = (native_centre == _NATIVE_VALID
          and canon_centre.edge is True
          and SG.TERM_NEIGHBOUR_UNSUPPORTED in canon_centre.edge_terms)
    return ok, ("cell (0,0) beside a 70 deg blocked cell at (1,0): native={} "
                "(SceneSurvey.cpp:189 omits CLS_BLOCKED from the invalid set); "
                "canonical edge={} terms={}".format(
                    native_centre, canon_centre.edge, canon_centre.edge_terms))


# --------------------------------------------------------------------------- #
# Fixture 5 — the `unknown` class is unreachable natively   [accepted]
# --------------------------------------------------------------------------- #
def _check_unknown_unreachable() -> Tuple[bool, str]:
    """A cell inside the region with NO observation recorded at all.

    Canonical calls it ``unknown`` (fail-closed). The native pass writes an entry
    for every index in the loop, so ``CLS_UNKNOWN`` is structurally unreachable
    and its counter is always 0 — which is what makes a downstream rail of the
    form "valid excludes unknown" vacuous.
    """
    cells = [_flat_ground_cell(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1)
             if (i, j) != (0, 1)]
    grid = SG.derive_grid(cells, (0.0, 0.0), radius_cm=100.0, step_cm=100.0)
    canon = {(c.i, c.j): c for c in grid.cells}
    native = _native_model_classify(cells, k=1)

    canon_unknown = canon[(0, 1)].resolved_class == SG.CLS_UNKNOWN
    native_has_no_entry = (0, 1) not in native  # the loop would have written one
    ok = canon_unknown and native_has_no_entry
    return ok, ("unobserved cell (0,1): canonical resolved_class={}; native has "
                "no way to express it — SceneSurvey.cpp:155 writes a class for "
                "every index, so CLS_UNKNOWN is unreachable and its counter is "
                "always 0".format(canon[(0, 1)].resolved_class))


# --------------------------------------------------------------------------- #
# Fixture 6 — head trace never attempted   [accepted]
# --------------------------------------------------------------------------- #
def _check_head_trace_not_attempted() -> Tuple[bool, str]:
    """Ground hit, head trace refused (e.g. the collector bailed mid-grid).

    Canonical: ``trace_error``, S=None, fail-closed. Native: the head trace's
    return value is a plain bool, so "did not run" is indistinguishable from
    "ran and did not hit" — it reads as CLEAR and the cell is counted ``valid``.
    """
    cells = [_flat_ground_cell(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1)]
    x, y = 0.0, 0.0
    cells = [c for c in cells if (c.i, c.j) != (0, 0)]
    cells.append(SG.RawCell(
        i=0, j=0,
        ground=SG.RawTrace(trace_start=(x, y, 1000.0), trace_end=(x, y, -3000.0),
                           hit=True, impact_point=(x, y, 0.0),
                           normal=(0.0, 0.0, 1.0)),
        head=None))
    grid = SG.derive_grid(cells, (0.0, 0.0), radius_cm=100.0, step_cm=100.0)
    canon = {(c.i, c.j): c for c in grid.cells}
    native = _native_model_classify(cells, k=1)

    ok = (canon[(0, 0)].resolved_class == SG.CLS_TRACE_ERROR
          and canon[(0, 0)].supported is None
          and native[(0, 0)] == _NATIVE_VALID)
    return ok, ("centre cell with head trace NOT attempted: canonical={} "
                "(supported=None, fail-closed); native={} — a bool return cannot "
                "distinguish 'did not run' from 'ran and was clear'".format(
                    canon[(0, 0)].resolved_class, native[(0, 0)]))


# --------------------------------------------------------------------------- #
# Fixture 7 — non-unit impact normal   [accepted]
# --------------------------------------------------------------------------- #
def _check_non_unit_normal() -> Tuple[bool, str]:
    """A normal of length 0.5 pointing 30 degrees off up.

    Canonical normalises (the contract writes ``n_hat``, a unit vector) and gets
    a 30 deg slope -> supported. Native compares the RAW ``ImpactNormal.Z``
    (SceneSurvey.cpp:139), reads 0.5*cos30 = 0.433, and calls it a 64 deg slope
    -> blocked. Same surface, opposite verdict.
    """
    n_unit = _tilted_normal(30.0)
    n_half = tuple(0.5 * c for c in n_unit)
    cells = [_flat_ground_cell(0, 0, z=0.0, normal=n_half)]
    grid = SG.derive_grid(cells, (0.0, 0.0), radius_cm=50.0, step_cm=100.0)
    canon = grid.cells[0]
    native = _native_model_classify(cells, k=0)

    native_slope = math.degrees(math.acos(max(-1.0, min(1.0, n_half[2]))))
    ok = (canon.resolved_class == SG.CLS_VALID
          and native[(0, 0)] == _NATIVE_BLOCKED)
    return ok, ("|n|=0.5 tilted 30 deg: canonical normalises -> 30.0 deg -> {}; "
                "native reads raw n.Z={:.4f} -> {:.1f} deg -> {}".format(
                    canon.resolved_class, n_half[2], native_slope, native[(0, 0)]))


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
DISCREPANCIES: Tuple[Discrepancy, ...] = (
    Discrepancy(
        fixture_id="extent_r_lt_s",
        status=ST_RESOLVED,
        summary="R < s sampled a 3x3 block reaching +/-s, outside the half-extent",
        cpp_citation="{}:103 (was: FMath::Max(1, (int32)(RadiusCm/StepCm)))".format(CPP_REL),
        native="pre-lane5 k=1, N=9, reach +/-s",
        canonical="k=0, N=1, one centre sample",
        why_it_matters=("a collector that samples outside the region it was handed "
                        "reports support for ground the caller never asked about"),
        check=_check_extent_r_lt_s),
    Discrepancy(
        fixture_id="float32_quotient",
        status=ST_ACCEPTED,
        summary="k is floored on a float32 quotient natively, float64 canonically",
        cpp_citation="{}:103 (float division)".format(CPP_REL),
        native="floor(float32(R)/float32(s))",
        canonical="floor(float64(R/s))",
        why_it_matters=("a one-ULP difference in the quotient changes the SAMPLE "
                        "COUNT, not just a cell class"),
        check=_check_float32_quotient),
    Discrepancy(
        fixture_id="tau_n_ridge_crest",
        status=ST_OPEN_OPERATOR,
        summary="a sharp normal change with no height step is invisible NATIVELY",
        cpp_citation=("{}:184-200 (no tau_n term in pass 2) and :140 "
                      "(pass 1 stores only ImpactPoint.Z — the normal is "
                      "discarded, so pass 2 has no data to compare)".format(CPP_REL)),
        native="valid on both sides of the crest, 0 edges",
        canonical="6 cells proved `edge` via normal_discontinuity (tau_n = theta_max)",
        why_it_matters=("this is the term that catches a ridge, a kerb lip, or a "
                        "ramp/wall join. Canonical now SEES it; the C++ cannot, "
                        "and closing the gap needs per-cell normal retention in "
                        "pass 1, not just a new comparison — so this stays open "
                        "as a native-collector work item"),
        check=_check_tau_n_ridge_crest),
    Discrepancy(
        fixture_id="blocked_neighbour_not_edge",
        status=ST_OPEN_OPERATOR,
        summary="native omits CLS_BLOCKED from the 'invalid neighbour' set",
        cpp_citation="{}:189".format(CPP_REL),
        native="valid — a cell beside a too-steep cell is not an edge",
        canonical="edge — NOT S_q holds for a blocked neighbour",
        why_it_matters=("standing on the lip above a 70 deg face reads as ordinary "
                        "open floor natively; the native answer is the unsafe one"),
        check=_check_blocked_neighbour),
    Discrepancy(
        fixture_id="unknown_class_unreachable",
        status=ST_ACCEPTED,
        summary="CLS_UNKNOWN is structurally unreachable in the C++",
        cpp_citation="{}:120,155".format(CPP_REL),
        native="never emitted; counter always 0",
        canonical="emitted for any cell inside the region with no observation",
        why_it_matters=("a downstream rail 'valid excludes unknown' is vacuous "
                        "against the native counter and must not be cited as a gate"),
        check=_check_unknown_unreachable),
    Discrepancy(
        fixture_id="head_trace_not_attempted",
        status=ST_ACCEPTED,
        summary="a head trace that did not run is indistinguishable from 'clear'",
        cpp_citation="{}:150-152 (bool return)".format(CPP_REL),
        native="valid — not-run reads as clear",
        canonical="trace_error, supported=None — fail-closed",
        why_it_matters=("this is the miss-vs-failure conflation the tri-state rule "
                        "exists to prevent, sitting in the native collector"),
        check=_check_head_trace_not_attempted),
    Discrepancy(
        fixture_id="non_unit_normal",
        status=ST_ACCEPTED,
        summary="native slope-tests the raw ImpactNormal.Z, canonical normalises",
        cpp_citation="{}:138-139".format(CPP_REL),
        native="blocked (reads a shortened normal as a steeper slope)",
        canonical="valid (n_hat is a unit normal by definition)",
        why_it_matters=("only bites if a collision surface ever returns a non-unit "
                        "normal, but if one does the two channels invert"),
        check=_check_non_unit_normal),
)


def run_all() -> List[Tuple[Discrepancy, bool, str]]:
    return [(d,) + d.check() for d in DISCREPANCIES]


if __name__ == "__main__":
    print("support-grid cross-language discrepancy fixtures\n")
    for d, holds, detail in run_all():
        print("  [{}] {:28} {}".format("HOLDS " if holds else "CHANGED",
                                       d.fixture_id, d.status))
        print("      {}".format(detail))
        print()
    sys.exit(0)
