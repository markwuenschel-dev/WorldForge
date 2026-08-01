#!/usr/bin/env python3
"""support_grid_canonical.py — the CANONICAL support-grid mathematics for v2.6.

This module is the **semantic authority** for the support grid described in
``docs/contracts/v2_6_support_grid_contract.md``. Nothing else in WorldForge may
re-derive sample coordinates, the support predicate, or the edge predicate; they
import them from here.

Why it exists
-------------
The engine-side C++ (``Plugins/WorldForge/Source/WorldForgeCore/Private/SceneSurvey.cpp``)
and the WorldForge evidence layer must NOT each own a copy of the support
mathematics. Two copies agree by duplicated convention, not by proof, and the
first time they drift the drift is unattributable. So the split of authority is:

    engine side  ->  RAW OBSERVATIONS ONLY
                     e_ij = (trace_start, trace_end, hit, impact_point, normal,
                             actor_path, component_path, failure)

    this module  ->  support S_ij, discontinuities, edges E_ij, aggregate safety

The C++ still carries a ``CLS_EDGE`` flag. That flag is **diagnostic** (it omits
the tau_n term entirely) and is explicitly not permitted to satisfy the
authoritative edge result — see ``SceneSurvey.cpp`` pass 2 and contract §5.2.

Design rules this file obeys
----------------------------
* **One declaration** of every tolerance (``CONTRACT_TOLERANCES``). No literal
  is re-typed anywhere else in Python. ``test_negative_support_grid.py`` parses
  the C++ source and asserts the two declarations still agree.
* **Compare against cos(theta_max) directly.** Round-tripping a normal through
  ``acos``/``degrees`` is exactly where two languages disagree in the last bits.
* **tau_n is DECLARED BY DERIVATION, never invented.** ``tau_n = theta_max``
  (``derive_tau_n_deg``), so the number ``44.0`` is typed exactly once. The
  derivation and its two bounds are argued in contract §5.2. The refusal
  machinery is *not* removed: a ``SupportTolerances`` built with
  ``tau_n_deg=None`` still REFUSES rather than defaulting, because a tolerance
  set that has no tau_n must never quietly acquire one. In refusal mode an edge
  can be *proved* but a non-edge can never be proved, so ``E_ij`` is tri-state
  ``True``/``None`` — never ``False`` — for a supported cell with evaluable
  neighbours.
* **Sample identity is derived from canonical grid coordinates only.** No float,
  no anchor position, no process order, no wall-clock (``sample_id``). Floats are
  exactly what does not round-trip across the language boundary (§1.3), so no
  float may enter an identity.
* **Tri-state everywhere.** ``hit=None`` (the trace did not run) is a different
  observation from ``hit=False`` (the trace ran and missed). Mixing them is the
  single most common way a survey lies.
* **Two immutable passes.** Pass 2 reads only pass-1 support values, never its
  own output, so the result is iteration-order independent (contract §5.3).
* Standard library only. A semantic authority with an import chain is a
  semantic authority that can be changed from somewhere else.

Run ``python tools/pipeline/support_grid_canonical.py`` for a self-description
of the declared contract values.
"""

from __future__ import annotations

import math
import re
import struct
import sys
from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Sample-region modes. These are NAMES, deliberately, so square and radial can
# never be silently substituted for one another (contract §1).
# --------------------------------------------------------------------------- #
SHAPE_SQUARE = "axis_aligned_square"
SHAPE_DISK = "axis_aligned_disk"
SAMPLE_REGION_SHAPES = (SHAPE_SQUARE, SHAPE_DISK)

#: The only shape the shipping collector implements. SHAPE_DISK is declared so a
#: future radial mode has a name to be declared UNDER, not so it can be assumed.
IMPLEMENTED_SAMPLE_REGION_SHAPES = (SHAPE_SQUARE,)

# --------------------------------------------------------------------------- #
# Support-class vocabulary. Mirrors scene_survey_contracts.SUPPORT_CLASSES; kept
# as literals here only so this module stays import-free. The conformance
# harness asserts the two tuples are identical.
# --------------------------------------------------------------------------- #
CLS_VALID = "valid_support"
CLS_UNSUPPORTED = "unsupported"
CLS_EDGE = "edge"
CLS_BLOCKED = "blocked"
CLS_TRACE_ERROR = "trace_error"
CLS_UNKNOWN = "unknown"
SUPPORT_CLASSES = (CLS_VALID, CLS_UNSUPPORTED, CLS_EDGE, CLS_BLOCKED,
                   CLS_TRACE_ERROR, CLS_UNKNOWN)
#: Fail-closed: only this class counts as support. Everything else, including
#: `unknown`, does not.
VALID_SUPPORT_CLASSES = (CLS_VALID,)


class UndeclaredToleranceError(Exception):
    """A tolerance term was evaluated that has no declared value.

    ``CONTRACT_TOLERANCES`` now carries a DERIVED tau_n, so this does not fire
    on the contract instance. It still fires for any ``SupportTolerances`` built
    with ``tau_n_deg=None`` — see ``TOLERANCES_TAU_N_REFUSED``. Catching it and
    substituting a default is a contract violation: it makes the Python result
    incomparable to the native result while looking like agreement.
    """


class ContractViolation(Exception):
    """An input violates a structural rule of the support-grid contract."""


# --------------------------------------------------------------------------- #
# §3 — Tolerances. THE single declaration.
# --------------------------------------------------------------------------- #
#: tau_n is DERIVED from theta_max, so 44.0 is typed exactly once — the same
#: rule tau_h already obeys (tau_h = 2 * h_step). See contract §5.2 for the
#: argument. The multiplier is named so the conformance harness can assert the
#: derivation rather than the number.
TAU_N_DERIVED_FROM = "max_slope_deg"
TAU_N_MULTIPLIER = 1.0


def derive_tau_n_deg(max_slope_deg: float) -> float:
    """tau_n = TAU_N_MULTIPLIER * theta_max, in degrees.

    Why this and not an invented constant (contract §5.2):

    * **Hard upper bound.** The normal term is only ever evaluated between two
      cells that are BOTH supported, so both unit normals satisfy
      ``n . z_hat >= cos(theta_max)`` — each lies within theta_max of world up.
      Their separation is therefore at most ``2 * theta_max``. Any tau_n at or
      above ``2 * theta_max`` is VACUOUS: it can never fire. The declaration
      must sit strictly inside ``(0, 2 * theta_max)``.
    * **Soft lower bound.** tau_n must exceed the normal variation produced by
      merely *sampling a smooth standable surface*, or every curved slope becomes
      an edge. No measured curvature bound exists in this repo, so the lower
      bound cannot be derived — only bounded away from zero.
    * **The choice.** ``theta_max`` is the midpoint of ``(0, 2 * theta_max)``:
      the maximum-margin point between the two failure modes above. It is also
      the only angle this contract already declares, and it carries the right
      meaning — it is the declared boundary between an orientation a character
      can stand on and one it cannot. Setting ``tau_n = theta_max`` says: two
      adjacent supported cells are on the same walkable surface only if their
      orientations differ by less than the entire standable range. A larger turn
      over one sample step is a crease between two faces, not a slope.

    This is a declaration with a stated derivation, not a measurement. It is
    revisable the moment a real character-controller angular tolerance exists;
    the contract table and this function change together.
    """
    return TAU_N_MULTIPLIER * max_slope_deg


@dataclass(frozen=True)
class SupportTolerances:
    """Contract values for the support grid. One instance is authoritative.

    ``tau_n_deg=None`` means the term is REFUSED, not defaulted — evaluating it
    raises. ``CONTRACT_TOLERANCES`` supplies a derived value via
    ``derive_tau_n_deg``; the refusal path stays live for any tolerance set that
    genuinely has no tau_n, so the machinery is testable rather than vacuous.
    """

    max_slope_deg: float = 44.0            # SceneSurvey.cpp `MaxSlope`
    max_step_h_cm: float = 45.0            # SceneSurvey.cpp `MaxStepH`
    head_clear_hi_cm: float = 176.0        # SceneSurvey.cpp head-trace end offset
    head_clear_lo_offset_cm: float = 5.0   # head-trace start = impact_z + h_step + 5
    #: None = REFUSED. CONTRACT_TOLERANCES fills this from derive_tau_n_deg;
    #: nothing else may supply a number without a stated derivation (§5.2).
    tau_n_deg: Optional[float] = None
    #: |n| may deviate from 1 by at most this before the normal is a failed
    #: measurement rather than a surface observation.
    unit_normal_tol: float = 1.0e-3

    @property
    def tau_h_cm(self) -> float:
        """Edge height discontinuity = 2 * h_step. Derived, never re-typed."""
        return 2.0 * self.max_step_h_cm

    @property
    def head_clear_lo_cm(self) -> float:
        """Head-clearance window low bound, relative to the impact point."""
        return self.max_step_h_cm + self.head_clear_lo_offset_cm

    @property
    def cos_max_slope(self) -> float:
        """cos(theta_max). Compare n_hat . z_hat against THIS, never via acos."""
        return math.cos(math.radians(self.max_slope_deg))

    @property
    def tau_n_declared(self) -> bool:
        return self.tau_n_deg is not None

    @property
    def tau_n_ceiling_deg(self) -> float:
        """The largest normal separation two SUPPORTED cells can ever exhibit.

        Both normals lie within theta_max of world up, so they are at most
        ``2 * theta_max`` apart. A tau_n at or above this is vacuous — it can
        never fire — which is why ``2 * theta_max`` is NOT the declaration.
        """
        return 2.0 * self.max_slope_deg

    @property
    def tau_n_is_vacuous(self) -> bool:
        """True if the declared tau_n can never fire between supported cells."""
        return (self.tau_n_deg is not None
                and self.tau_n_deg >= self.tau_n_ceiling_deg)

    @property
    def cos_tau_n(self) -> float:
        """cos(tau_n) — raises while tau_n is undeclared. No default. Ever."""
        if self.tau_n_deg is None:
            raise UndeclaredToleranceError(
                "tau_n (edge normal-discontinuity tolerance) has no declared value. "
                "The normal-discontinuity term of the edge predicate cannot be "
                "evaluated. Declare it in SupportTolerances, in the contract, and in "
                "the C++ together, or leave the term refused.")
        return math.cos(math.radians(self.tau_n_deg))


#: A tolerance set with tau_n genuinely REFUSED. Exported so the refusal path
#: stays exercisable — a guard nothing can reach is a guard that rots.
TOLERANCES_TAU_N_REFUSED = SupportTolerances()

#: THE declaration. Import this; do not construct ad-hoc tolerance sets in
#: production code (tests may, to prove the refusal machinery works).
#: tau_n is filled by DERIVATION from this same instance's theta_max, so the
#: number 44.0 is typed exactly once in this file.
CONTRACT_TOLERANCES = replace(
    TOLERANCES_TAU_N_REFUSED,
    tau_n_deg=derive_tau_n_deg(TOLERANCES_TAU_N_REFUSED.max_slope_deg))


# --------------------------------------------------------------------------- #
# §1 — Grid geometry
# --------------------------------------------------------------------------- #
def grid_extent_k(radius_cm: float, step_cm: float) -> int:
    """k = floor(R / s) for an ``axis_aligned_square`` region of half-extent R.

    R < s therefore yields k = 0, i.e. exactly ONE centre sample. A collector
    must never sample outside the half-extent it was handed; the previous
    ``max(1, floor(R/s))`` produced a 3x3 block reaching +/-s (contract §1.1).
    """
    if not (radius_cm > 0.0):
        raise ContractViolation("radius_cm must be > 0 (got {!r})".format(radius_cm))
    if not (step_cm > 0.0):
        raise ContractViolation("step_cm must be > 0 (got {!r})".format(step_cm))
    if not (math.isfinite(radius_cm) and math.isfinite(step_cm)):
        raise ContractViolation("radius_cm and step_cm must be finite")
    return int(math.floor(radius_cm / step_cm))


def grid_extent_k_float32(radius_cm: float, step_cm: float) -> int:
    """``grid_extent_k`` evaluated in float32, as the C++ ``float`` path does.

    Not the canonical answer — a cross-language *probe*. Python divides in
    float64; ``SceneSurvey.cpp`` divides two ``float``s. For any (R, s) where
    these two disagree the collectors disagree on the sample count, and the
    conformance harness sweeps for exactly that.
    """
    r32 = struct.unpack("f", struct.pack("f", radius_cm))[0]
    s32 = struct.unpack("f", struct.pack("f", step_cm))[0]
    q32 = struct.unpack("f", struct.pack("f", r32 / s32))[0]
    return int(math.floor(q32))


def nominal_sample_count(k: int) -> int:
    """N = (2k + 1)^2."""
    if k < 0:
        raise ContractViolation("k must be >= 0")
    return (2 * k + 1) ** 2


def canonical_sort_key(index: Tuple[int, int]) -> Tuple[int, int]:
    """Canonical row-major order: (i,j) < (i',j') iff i<i' or (i==i' and j<j')."""
    return (index[0], index[1])


def sample_indices(k: int) -> Tuple[Tuple[int, int], ...]:
    """All (i, j) in [-k, k]^2 in canonical row-major order (i outer, j inner)."""
    if k < 0:
        raise ContractViolation("k must be >= 0")
    return tuple((i, j) for i in range(-k, k + 1) for j in range(-k, k + 1))


def sample_point(anchor_xy: Tuple[float, float], i: int, j: int,
                 step_cm: float) -> Tuple[float, float]:
    """p_ij = (a_x + i*s, a_y + j*s).

    Written in the same expression form as ``SceneSurvey.cpp`` (``Center.X +
    ix * StepCm``) so the two do not differ by an associativity choice.
    """
    return (anchor_xy[0] + i * step_cm, anchor_xy[1] + j * step_cm)


def sample_points(anchor_xy: Tuple[float, float], radius_cm: float,
                  step_cm: float) -> Tuple[Tuple[int, int, float, float], ...]:
    """(i, j, x, y) for every sample, canonical order. Square region only."""
    k = grid_extent_k(radius_cm, step_cm)
    return tuple((i, j) + sample_point(anchor_xy, i, j, step_cm)
                 for (i, j) in sample_indices(k))


#: von Neumann (4-connected) neighbourhood, contract §5.1. Order matches
#: SceneSurvey.cpp DX/DY so any future per-neighbour trace is comparable.
NEIGHBOUR_DELTAS = ((1, 0), (-1, 0), (0, 1), (0, -1))


# --------------------------------------------------------------------------- #
# §1.4 — Canonical sample identity
# --------------------------------------------------------------------------- #
#: Bump the revision whenever the SEMANTICS of a sample change (not when prose
#: changes). r1 = tau_n refused. r2 = tau_n declared by derivation (§5.2), which
#: changes what `edge`/`resolved_class` a given cell resolves to, so a cached r1
#: sample must never be compared to an r2 sample as though they agreed.
SUPPORT_GRID_CONTRACT_ID = "wf.support_grid.v2_6"
SUPPORT_GRID_CONTRACT_REVISION = 2
SUPPORT_GRID_CONTRACT_VERSION = "{}.r{}".format(SUPPORT_GRID_CONTRACT_ID,
                                                SUPPORT_GRID_CONTRACT_REVISION)

#: Field separator. Chosen because it cannot occur in any component: the version
#: is [a-z0-9._], the shape names are [a-z_], and the indices are [-+0-9].
SAMPLE_ID_SEP = "|"


def _fmt_index(v: int) -> str:
    """Canonical rendering of a signed grid index.

    Rules, all of them load-bearing:
      * integral only — a float index is a ContractViolation, never rounded;
      * sign ALWAYS explicit, so ``0`` and ``-0`` cannot both exist;
      * plain decimal, no zero padding, no thousands separator, no locale.
    """
    if isinstance(v, bool) or not isinstance(v, int):
        raise ContractViolation(
            "grid index must be an int, got {!r} ({}). A sample identity must "
            "never be built from a float — floats are exactly what fails to "
            "round-trip across the language boundary (contract §1.3)."
            .format(v, type(v).__name__))
    return "{:+d}".format(v)


def sample_id(k: int, i: int, j: int,
              sample_region_shape: str = SHAPE_SQUARE) -> str:
    """The canonical identity of one grid sample.

    ``wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=-1|j=+0``

    Derived ONLY from canonical grid coordinates and declared contract names.
    Deterministic: the same ``(shape, k, i, j)`` always yields the same string,
    on any machine, in any process, in any iteration order. Nothing that varies
    — wall-clock, process order, anchor position, spacing, PRNG, memory address
    — is permitted to enter it.

    Components, and why each is present:

    ``version``  Semantics can change without the coordinates changing (r1 -> r2
                 flipped `edge` from indeterminate to decided). Two samples with
                 different revisions are different observations and must not
                 collide.
    ``shape``    Contract §1.2 forbids square and disk semantics from being
                 silently substituted; the identity carries the full declared
                 NAME, never an abbreviation, so the distinction survives here
                 too. Constrained to ``SAMPLE_REGION_SHAPES``.
    ``k``        The §5.1 perimeter asymmetry means a cell's evidence quality
                 depends on the grid extent: ``(1,0)`` is a 3-neighbour perimeter
                 cell at k=1 and a 4-neighbour interior cell at k=2. Without k
                 those two non-interchangeable observations would share an id.
    ``i``, ``j`` The cell itself, in canonical index space.

    **Scope: operation-local, and deliberately so.** The id is unique within one
    survey operation and is NOT globally unique — two operations at different
    anchors, or at the same anchor with a different spacing ``s``, legitimately
    produce identical ids. Anchor and spacing are floats, and admitting a float
    would make the identity disagree across the float32/float64 boundary that
    §1.3 already documents. So the identity is qualified by the operation
    (``(operation_id, sample_id)``) and never used as a substitute for it.

    **Not an ordering key.** Canonical order is ``canonical_sort_key``, and
    ONLY that. Sorting these strings lexically gives the wrong answer: ``'+'``
    (0x2B) sorts before ``'-'`` (0x2D), so ``"i=+0"`` precedes ``"i=-1"`` while
    canonically ``-1 < 0``. ``sort_key_from_sample_id`` exists for when an id is
    all you have.
    """
    if sample_region_shape not in SAMPLE_REGION_SHAPES:
        raise ContractViolation(
            "sample_region_shape={!r} is not a declared shape; declared are {}"
            .format(sample_region_shape, SAMPLE_REGION_SHAPES))
    if isinstance(k, bool) or not isinstance(k, int) or k < 0:
        raise ContractViolation("k must be a non-negative int, got {!r}".format(k))
    if abs(i) > k or abs(j) > k:
        raise ContractViolation(
            "index ({}, {}) lies outside the half-extent k={}; a sample identity "
            "must never name a cell the grid does not contain".format(i, j, k))
    return SAMPLE_ID_SEP.join((
        SUPPORT_GRID_CONTRACT_VERSION,
        sample_region_shape,
        "k={:d}".format(k),
        "i={}".format(_fmt_index(i)),
        "j={}".format(_fmt_index(j)),
    ))


def parse_sample_id(sid: str) -> Dict[str, object]:
    """Inverse of ``sample_id``. Round-tripping is the determinism proof.

    Returns ``{version, sample_region_shape, k, i, j}``. Raises
    ``ContractViolation`` on anything it did not emit itself — a lenient parser
    would let a malformed identity through as a plausible one.
    """
    if not isinstance(sid, str):
        raise ContractViolation("sample id must be a str, got {!r}".format(sid))
    parts = sid.split(SAMPLE_ID_SEP)
    if len(parts) != 5:
        raise ContractViolation(
            "sample id must have 5 fields, got {}: {!r}".format(len(parts), sid))
    version, shape, k_s, i_s, j_s = parts
    if version != SUPPORT_GRID_CONTRACT_VERSION:
        raise ContractViolation(
            "sample id was minted under {!r}; this build is {!r}. Comparing "
            "samples across contract revisions is exactly the silent drift the "
            "version field exists to stop.".format(
                version, SUPPORT_GRID_CONTRACT_VERSION))
    if shape not in SAMPLE_REGION_SHAPES:
        raise ContractViolation("unknown sample_region_shape {!r}".format(shape))

    def _field(text: str, tag: str, signed: bool) -> int:
        head, sep, val = text.partition("=")
        if head != tag or not sep:
            raise ContractViolation(
                "expected field {!r}=, got {!r}".format(tag, text))
        pattern = r"^[+-]\d+$" if signed else r"^\d+$"
        if not re.match(pattern, val):
            raise ContractViolation(
                "field {} has non-canonical value {!r} (signed={})".format(
                    tag, val, signed))
        if len(val.lstrip("+-")) > 1 and val.lstrip("+-")[0] == "0":
            raise ContractViolation(
                "field {} is zero-padded ({!r}); canonical form has no padding"
                .format(tag, val))
        return int(val)

    k = _field(k_s, "k", signed=False)
    i = _field(i_s, "i", signed=True)
    j = _field(j_s, "j", signed=True)
    if abs(i) > k or abs(j) > k:
        raise ContractViolation(
            "sample id names cell ({}, {}) outside k={}".format(i, j, k))
    return {"version": version, "sample_region_shape": shape,
            "k": k, "i": i, "j": j}


def sort_key_from_sample_id(sid: str) -> Tuple[int, int]:
    """Canonical sort key recovered from an id. NEVER sort the strings."""
    f = parse_sample_id(sid)
    return canonical_sort_key((int(f["i"]), int(f["j"])))


# --------------------------------------------------------------------------- #
# §2 — Raw observation record
# --------------------------------------------------------------------------- #
def _is_finite_vec(v: Optional[Sequence[float]]) -> bool:
    return (v is not None and len(v) == 3
            and all(isinstance(c, (int, float)) and math.isfinite(c) for c in v))


@dataclass(frozen=True)
class RawTrace:
    """One raw trace observation. No verdict, no class, nothing derived.

    Tri-state ``hit``:
      * ``True``  — the trace ran and hit.
      * ``False`` — the trace ran and cleanly missed.
      * ``None``  — the trace DID NOT RUN. ``failure`` says why.

    A cell whose trace did not run records ``failure`` with ``hit=None``, never
    ``hit=False``. "Missed" and "never attempted" are different observations.
    """

    trace_start: Optional[Tuple[float, float, float]]
    trace_end: Optional[Tuple[float, float, float]]
    hit: Optional[bool]
    impact_point: Optional[Tuple[float, float, float]] = None
    normal: Optional[Tuple[float, float, float]] = None
    actor_path: Optional[str] = None
    component_path: Optional[str] = None
    failure: Optional[str] = None

    def __post_init__(self) -> None:
        if self.hit is None and not self.failure:
            raise ContractViolation(
                "hit=None means the trace did not run and REQUIRES a failure reason; "
                "a trace that ran and missed is hit=False")
        if self.hit is not None and self.failure:
            raise ContractViolation(
                "a trace that ran (hit={!r}) must not also carry failure={!r}; "
                "pick one".format(self.hit, self.failure))
        if self.hit is False and (self.impact_point is not None
                                  or self.normal is not None):
            raise ContractViolation(
                "a clean miss carries impact_point=None and normal=None, never a "
                "zero vector and never stale geometry")
        if self.hit is None and (self.impact_point is not None
                                 or self.normal is not None):
            raise ContractViolation(
                "a trace that did not run cannot carry geometry")


@dataclass(frozen=True)
class RawCell:
    """The raw observations for one grid cell: a ground trace and, when it was
    issued, a head-clearance trace.

    ``head`` is ``None`` when the head trace was never issued — which is a real
    and common state (the ground trace missed, so there was nothing to clear
    above). ``None`` here means "not attempted" and must never read as "clear".
    """

    i: int
    j: int
    ground: RawTrace
    head: Optional[RawTrace] = None


# --------------------------------------------------------------------------- #
# §4 — Support predicate (pass 1)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Pass1Result:
    """Immutable pass-1 classification for one cell. Pass 2 reads only this."""

    i: int
    j: int
    supported: Optional[bool]          # S_ij, tri-state
    pass1_class: str                   # never CLS_EDGE — that is pass 2's output
    z: Optional[float] = None          # impact z, when observed
    unit_normal: Optional[Tuple[float, float, float]] = None
    reason: str = ""


def _unit_normal(n: Sequence[float], tol: SupportTolerances
                 ) -> Optional[Tuple[float, float, float]]:
    """Normalise an observed normal, or None if it is not a usable measurement.

    The contract writes ``n_hat``, a UNIT normal. The C++ compares the raw
    ``ImpactNormal.Z``; for a unit normal the two are identical, and for a
    non-unit normal the C++ is simply wrong. Normalising here is the faithful
    reading of the contract, and the divergence is recorded as a fixture.
    """
    if not _is_finite_vec(n):
        return None
    length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
    if not math.isfinite(length) or length <= tol.unit_normal_tol:
        return None
    return (n[0] / length, n[1] / length, n[2] / length)


def classify_support(cell: RawCell,
                     tol: SupportTolerances = CONTRACT_TOLERANCES) -> Pass1Result:
    """S_ij and the pass-1 class for one cell, from raw observations only.

        S_ij = hit
             AND finite(p_impact) AND finite(n_hat)
             AND n_hat . z_hat >= cos(theta_max)
             AND head_clear

    Tri-state ``supported``: ``None`` means UNKNOWN, never "no". Fail-closed:
    an unknown cell is not support.
    """
    g = cell.ground

    if g.hit is None:
        # The trace did not run. This is a failed measurement, not a miss.
        return Pass1Result(cell.i, cell.j, None, CLS_TRACE_ERROR,
                           reason="ground_trace_failure:{}".format(g.failure))

    if g.hit is False:
        # A clean miss IS an observation: there is no floor beneath this cell.
        return Pass1Result(cell.i, cell.j, False, CLS_UNSUPPORTED,
                           reason="clean_miss")

    if not _is_finite_vec(g.impact_point):
        return Pass1Result(cell.i, cell.j, None, CLS_TRACE_ERROR,
                           reason="non_finite_impact_point")

    n_hat = _unit_normal(g.normal, tol) if g.normal is not None else None
    if n_hat is None:
        return Pass1Result(cell.i, cell.j, None, CLS_TRACE_ERROR,
                           reason="non_finite_or_degenerate_normal")

    z = float(g.impact_point[2])

    # n_hat . z_hat, compared against cos(theta_max) DIRECTLY. No acos, no
    # degrees: that round-trip is where two languages disagree in the last bits.
    n_dot_z = n_hat[2]
    if n_dot_z < tol.cos_max_slope:
        return Pass1Result(cell.i, cell.j, False, CLS_BLOCKED, z=z,
                           unit_normal=n_hat, reason="slope_exceeds_theta_max")

    if cell.head is None:
        # The head trace was never issued for a cell that needed one. Unknown,
        # fail-closed — absolutely not "clear".
        return Pass1Result(cell.i, cell.j, None, CLS_TRACE_ERROR, z=z,
                           unit_normal=n_hat, reason="head_trace_not_attempted")
    if cell.head.hit is None:
        return Pass1Result(cell.i, cell.j, None, CLS_TRACE_ERROR, z=z,
                           unit_normal=n_hat,
                           reason="head_trace_failure:{}".format(cell.head.failure))
    if cell.head.hit is True:
        return Pass1Result(cell.i, cell.j, False, CLS_BLOCKED, z=z,
                           unit_normal=n_hat, reason="head_blocked")

    return Pass1Result(cell.i, cell.j, True, CLS_VALID, z=z,
                       unit_normal=n_hat, reason="supported")


def head_trace_window(impact_z: float,
                      tol: SupportTolerances = CONTRACT_TOLERANCES
                      ) -> Tuple[float, float]:
    """Absolute Z window the head-clearance trace must sweep for this impact."""
    return (impact_z + tol.head_clear_lo_cm, impact_z + tol.head_clear_hi_cm)


# --------------------------------------------------------------------------- #
# §5 — Edge predicate (pass 2)
# --------------------------------------------------------------------------- #
#: Names for the three disjuncts of the edge predicate, so a fired term is
#: reported by name rather than as an anonymous boolean.
TERM_NEIGHBOUR_UNSUPPORTED = "neighbour_not_supported"
TERM_HEIGHT_DISCONTINUITY = "height_discontinuity"
TERM_NORMAL_DISCONTINUITY = "normal_discontinuity"
EDGE_TERMS = (TERM_NEIGHBOUR_UNSUPPORTED, TERM_HEIGHT_DISCONTINUITY,
              TERM_NORMAL_DISCONTINUITY)


@dataclass(frozen=True)
class CellResult:
    """Final per-cell result: pass-1 support plus the tri-state edge verdict."""

    i: int
    j: int
    supported: Optional[bool]
    pass1_class: str
    edge: Optional[bool]                     # E_ij; None = INDETERMINATE
    edge_terms: Tuple[str, ...] = ()         # declared terms that fired
    z: Optional[float] = None
    unit_normal: Optional[Tuple[float, float, float]] = None
    reason: str = ""

    @property
    def resolved_class(self) -> str:
        """The 6-class label, fail-closed.

        ``edge is None`` means the tau_n term was refused, so this cell is
        either ``valid_support`` or ``edge`` and we cannot say which. Fail-closed
        collapses that to ``unknown``. The resulting pile of ``unknown`` is not a
        bug — it is the honest cost of an undeclared tau_n, and it is what makes
        declaring tau_n visibly worth doing.
        """
        if self.pass1_class != CLS_VALID:
            return self.pass1_class
        if self.edge is True:
            return CLS_EDGE
        if self.edge is False:
            return CLS_VALID
        return CLS_UNKNOWN


@dataclass(frozen=True)
class GridResult:
    k: int
    anchor_xy: Tuple[float, float]
    radius_cm: float
    step_cm: float
    tolerances: SupportTolerances
    cells: Tuple[CellResult, ...]            # canonical order, always
    tau_n_evaluated: bool
    sample_region_shape: str = SHAPE_SQUARE

    @property
    def nominal_count(self) -> int:
        return nominal_sample_count(self.k)

    def counts(self) -> Dict[str, int]:
        out = {c: 0 for c in SUPPORT_CLASSES}
        for c in self.cells:
            out[c.resolved_class] += 1
        return out

    def indeterminate_indices(self) -> Tuple[Tuple[int, int], ...]:
        return tuple((c.i, c.j) for c in self.cells if c.edge is None
                     and c.pass1_class == CLS_VALID)

    def sample_id_for(self, i: int, j: int) -> str:
        """Canonical identity of one cell of THIS grid (§1.4)."""
        return sample_id(self.k, i, j, self.sample_region_shape)

    def sample_ids(self) -> Tuple[str, ...]:
        """Every cell's identity, in canonical order — same order as ``cells``.

        Deliberately NOT a field on ``CellResult``: a cell does not know ``k``,
        and copying ``k`` into every cell is a second place for it to drift.
        """
        return tuple(self.sample_id_for(c.i, c.j) for c in self.cells)


def _normals_exceed_tau_n(a: Sequence[float], b: Sequence[float],
                          tol: SupportTolerances) -> bool:
    """arccos(clamp(n_a . n_b, -1, 1)) > tau_n, evaluated WITHOUT acos.

    For tau_n in [0, 180], arccos(d) > tau_n  <=>  d < cos(tau_n), because
    arccos is strictly decreasing. Comparing the dot product against
    cos(tau_n) avoids the acos/degrees round-trip entirely.

    Raises ``UndeclaredToleranceError`` while tau_n has no value.
    """
    cos_tau_n = tol.cos_tau_n  # raises if undeclared — deliberately not guarded
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    d = max(-1.0, min(1.0, d))
    return d < cos_tau_n


def derive_edges(pass1: Sequence[Pass1Result], k: int,
                 tol: SupportTolerances = CONTRACT_TOLERANCES,
                 refuse_undeclared_tau_n: bool = True
                 ) -> Tuple[Tuple[CellResult, ...], bool]:
    """Pass 2. Returns (cells in canonical order, tau_n_evaluated).

        E_ij = S_ij AND exists q in N(i,j):
                   NOT S_q
                OR |z_ij - z_q| > tau_h
                OR arccos(n_ij . n_q) > tau_n

    Reads ONLY pass-1 support values. Never reads its own output, so the result
    does not depend on iteration order (contract §5.3).

    Boundary rule (contract §5.1): an off-grid neighbour is skipped — absence is
    NOT evidence of an edge. The opposite convention would paint the whole grid
    perimeter as edge, which is an artifact of the sampling window rather than
    an observation about the world.

    ``NOT S_q`` is satisfied by ``S_q is False`` AND by ``S_q is None``. That is
    the declared fail-closed rule (§4.1: unknown is never support) applied
    consistently, not a Kleene-logic choice: an unknown neighbour is not known
    support, so a supported cell beside it is on a known boundary of knowledge.

    tau_n: while undeclared, the third disjunct cannot be evaluated. A cell with
    an evaluable neighbour therefore cannot be proved NOT to be an edge, and
    gets ``edge=None``. Only a cell with no evaluable neighbours at all (k=0)
    can be proved ``edge=False``.
    """
    by_index: Dict[Tuple[int, int], Pass1Result] = {}
    for p in pass1:
        key = (p.i, p.j)
        if key in by_index:
            raise ContractViolation("duplicate pass-1 entry for {}".format(key))
        if abs(p.i) > k or abs(p.j) > k:
            raise ContractViolation(
                "pass-1 entry {} lies outside the requested half-extent (k={}). "
                "A collector must not sample outside the region it was handed."
                .format(key, k))
        by_index[key] = p

    tau_n_ok = tol.tau_n_declared
    if not tau_n_ok and not refuse_undeclared_tau_n:
        raise UndeclaredToleranceError(
            "refuse_undeclared_tau_n=False requires a declared tau_n; there is "
            "no default and one must not be invented")

    out: List[CellResult] = []
    for (i, j) in sample_indices(k):
        p = by_index.get((i, j))
        if p is None:
            # No observation at all for a cell inside the region. Not a miss,
            # not a trace error — simply unclassified. Fail-closed: unknown.
            out.append(CellResult(i, j, None, CLS_UNKNOWN, edge=False,
                                  reason="no_observation_recorded"))
            continue

        if p.supported is not True:
            # Edge is a re-classification of SUPPORTED cells only. An
            # unsupported / blocked / trace_error cell keeps its own class.
            out.append(CellResult(i, j, p.supported, p.pass1_class, edge=False,
                                  z=p.z, unit_normal=p.unit_normal,
                                  reason=p.reason))
            continue

        fired: List[str] = []
        evaluable_neighbours = 0
        for (di, dj) in NEIGHBOUR_DELTAS:
            q = by_index.get((i + di, j + dj))
            if q is None:
                continue  # off-grid (or unrecorded): NOT evidence of an edge
            evaluable_neighbours += 1

            if q.supported is not True:
                if TERM_NEIGHBOUR_UNSUPPORTED not in fired:
                    fired.append(TERM_NEIGHBOUR_UNSUPPORTED)
                continue

            if (p.z is not None and q.z is not None
                    and abs(p.z - q.z) > tol.tau_h_cm):
                if TERM_HEIGHT_DISCONTINUITY not in fired:
                    fired.append(TERM_HEIGHT_DISCONTINUITY)
                continue

            if tau_n_ok and p.unit_normal is not None and q.unit_normal is not None:
                if _normals_exceed_tau_n(p.unit_normal, q.unit_normal, tol):
                    if TERM_NORMAL_DISCONTINUITY not in fired:
                        fired.append(TERM_NORMAL_DISCONTINUITY)

        if fired:
            edge: Optional[bool] = True
        elif tau_n_ok or evaluable_neighbours == 0:
            edge = False
        else:
            # No declared term fired, but the tau_n term was refused. We cannot
            # prove this cell is not an edge.
            edge = None

        out.append(CellResult(i, j, True, CLS_VALID, edge=edge,
                              edge_terms=tuple(fired), z=p.z,
                              unit_normal=p.unit_normal, reason=p.reason))

    return tuple(out), tau_n_ok


def derive_grid(observations: Iterable[RawCell],
                anchor_xy: Tuple[float, float],
                radius_cm: float,
                step_cm: float,
                tol: SupportTolerances = CONTRACT_TOLERANCES,
                sample_region_shape: str = SHAPE_SQUARE) -> GridResult:
    """Full two-pass derivation from raw observations. The entry point.

    Raises ``ContractViolation`` if the collector handed back a sample outside
    the requested half-extent — which is exactly the ``R < s`` over-extension
    the old ``max(1, floor(R/s))`` produced.
    """
    if sample_region_shape not in IMPLEMENTED_SAMPLE_REGION_SHAPES:
        raise ContractViolation(
            "sample_region_shape={!r} is not implemented; implemented modes are {}. "
            "A radial region is a SEPARATE declared mode (i*i + j*j <= (R/s)^2), "
            "never a silent substitution for the square one."
            .format(sample_region_shape, IMPLEMENTED_SAMPLE_REGION_SHAPES))

    k = grid_extent_k(radius_cm, step_cm)
    cells = sorted(observations, key=lambda c: canonical_sort_key((c.i, c.j)))
    pass1 = [classify_support(c, tol) for c in cells]
    results, tau_n_evaluated = derive_edges(pass1, k, tol)
    return GridResult(k=k, anchor_xy=anchor_xy, radius_cm=radius_cm,
                      step_cm=step_cm, tolerances=tol, cells=results,
                      tau_n_evaluated=tau_n_evaluated,
                      sample_region_shape=sample_region_shape)


# --------------------------------------------------------------------------- #
# Self-description
# --------------------------------------------------------------------------- #
def describe() -> str:
    t = CONTRACT_TOLERANCES
    lines = [
        "support_grid_canonical — declared contract values",
        "  sample_region_shape   = {} (radius_cm is the HALF-EXTENT)".format(SHAPE_SQUARE),
        "  k                     = floor(R / s);  N = (2k+1)^2;  R < s -> 1 sample",
        "  neighbourhood         = 4-connected {}".format(NEIGHBOUR_DELTAS),
        "  theta_max             = {} deg   (cos = {!r})".format(
            t.max_slope_deg, t.cos_max_slope),
        "  h_step                = {} cm".format(t.max_step_h_cm),
        "  tau_h                 = {} cm  (= 2 * h_step)".format(t.tau_h_cm),
        "  head clearance window = [{}, {}] cm above impact".format(
            t.head_clear_lo_cm, t.head_clear_hi_cm),
        "  tau_n                 = {} deg  (= {} * theta_max, DERIVED)".format(
            t.tau_n_deg, TAU_N_MULTIPLIER),
        "    ceiling             = {} deg  (2 * theta_max; at/above this tau_n".format(
            t.tau_n_ceiling_deg),
        "                          is VACUOUS — two supported normals can never",
        "                          be further apart). vacuous = {}".format(
            t.tau_n_is_vacuous),
        "    comparison          = dot(n_i, n_q) < cos(tau_n)   [strict, no acos]",
        "",
        "  sample identity (§1.4)",
        "    contract version    = {}".format(SUPPORT_GRID_CONTRACT_VERSION),
        "    form                = {}".format(sample_id(1, -1, 0)),
        "    determinism         = pure function of (version, shape, k, i, j);",
        "                          no float, no anchor, no spacing, no clock,",
        "                          no process order. Operation-local scope.",
        "",
        "  The tau_n REFUSAL path is still live for any SupportTolerances built",
        "  with tau_n_deg=None (TOLERANCES_TAU_N_REFUSED): reading cos(tau_n)",
        "  raises, and E_ij is True or None — never False — for a supported cell",
        "  with an on-grid neighbour.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
    sys.exit(0)
