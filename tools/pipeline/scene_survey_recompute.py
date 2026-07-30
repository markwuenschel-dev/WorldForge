#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_survey_recompute.py — the VALIDATOR's independent re-derivation.

Pure and I/O-free. This module exists so that ``validate_scene_survey_runtime.py``
can answer "does the reported value follow from the raw evidence?" WITHOUT calling
the function that produced the value. It is deliberately a SECOND implementation,
not a shared one.

WHY A SECOND IMPLEMENTATION
---------------------------
``scene_survey_evidence.py`` argues (:26-46) that sharing its derivation functions
between assembler and validator is not circular, because the independent input is
the raw evidence. That argument is sound for the case it addresses — an assembler
that writes a value its own raw does not support. It does NOT cover the case where
the derivation function is itself wrong, or where the assembler bypasses the
derivation entirely and writes a literal. Both are live in this codebase today:

  * ``run_scene_survey_probe.py:323`` sets ``actor_bounds_valid`` from an actor
    COUNT (``en.get("actors", 0) > 0 and not far.get("error")``) — the exact defect
    ``scene_survey_evidence.py:15-17`` says was fixed.
  * ``run_scene_survey_probe.py:333`` sets ``cleanup_verified = True`` as a literal.
  * ``run_scene_survey_probe.py:266`` names the ACCEPTED count
    ``temporary_placements_grounded`` — the substitution
    ``scene_survey_evidence.py:310-313`` explicitly forbids.
  * ``run_scene_survey_probe.py:268`` still computes ``player_clearance_valid`` as
    ``all((not accepted) or clearance)`` — the tautology
    ``scene_survey_evidence.py:339-343`` says was removed.

Calling ``scene_survey_evidence.derive()`` would not have caught the fourth of
those, because the assembler never called it. So this module re-derives from the
raw ATOMS, one level BELOW the level the evidence model reads.

THE ATOM / RESTATEMENT SPLIT
----------------------------
``tools/bridge/scene_survey_far_side.py`` emits, per marker, both

    ATOMS         ground_trace_ref -> trace record with .hit/.impact_point/
                  .impact_normal; footprint_trace_hits[]; capsule_center;
                  capsule_overlap_static_actor_paths; capsule_overlap_dynamic_...
    RESTATEMENTS  grounded / footprint / overlap / capsule_clear   (nullable)

and says so at ``scene_survey_far_side.py:69-77``. ``scene_survey_evidence.py``'s
derivations read the RESTATEMENTS (``:316``, ``:322``, ``:333``, ``:346``). This
module reads the ATOMS and then asserts the restatement agrees. A restatement that
contradicts its own atom is a CONTRADICTORY ATOM and a hard failure — a class of
defect neither side can currently see, because neither side compares the two.

DELIBERATE SHARING WITH THE ASSEMBLER (and why each is not circular)
--------------------------------------------------------------------
Shared, from ``scene_survey_evidence``:

  * ``STAGES`` / ``STAGE_ORDER``            — vocabulary, not a verdict. If the two
    sides disagreed about the name of a stage, every stage-ordered rail would
    silently pass on a typo. Sharing the enum makes disagreement impossible;
    sharing a verdict would make agreement guaranteed. Those are opposites.
  * ``CLASSIFICATIONS`` and its members     — same argument. The provenance taxonomy
    is a closed vocabulary the report is written against.
  * ``ACCEPTANCE_CLASSIFICATIONS``          — the definition of "may satisfy a rail".

NOT shared, on purpose — re-implemented here:

  * every ``derive_*`` / ``sufficiency_*`` in ``DERIVATIONS``
    (``scene_survey_evidence.py:2048-2063``)
  * ``derive()``, ``rederive_and_compare()``, ``derived_record()``
  * ``validate_scene_survey_report()`` field verdicts
  * ACCEPTANCE ELIGIBILITY. Until 2026-07-30 this list claimed
    ``evaluate_acceptance_eligibility()`` was re-implemented here. It was not:
    no such function existed in this module and ``acceptance_eligible`` was absent
    from ``COMPARED_FIELDS``, so the only path to an eligibility verdict was
    ``validate_scene_survey_runtime.py:415`` -> ``SS.validate_subject_binding`` ->
    ``scene_survey_contracts.evaluate_acceptance_eligibility`` — the SAME predicate
    the assembler calls at ``run_scene_survey_probe.py:795``. The docstring
    asserted a check that had never been written. It is written now, under
    ``ACCEPTANCE ELIGIBILITY`` below: six terms M∧W∧P∧T∧B∧E derived from
    ``raw["world"]`` / ``raw["actor"]`` / ``raw["marker"]``, which is one level
    BELOW the shared predicate — that one reads a ``binding`` bundle projected out
    of the (subject, report) pair (``scene_survey_evidence.acceptance_raw
    :1915-1964``) and never opens the far-side bundle at all.
  * ``resolve_raw()`` — five lines, and it is the mechanism by which a MISSING
    record is detected. A shared bug there would hide the very thing the ref rail
    exists to find, so it is re-implemented and cross-checked against the shared
    one in ``_dogfood``.
  * package-path canonicalisation (``run_scene_survey_probe._canon_package`` /
    ``_norm_package``, :215-249) — re-implemented and cross-checked on a fixture
    table, so a drift between the two is reported rather than assumed away.

THE MATH
--------
Observability / sufficiency / verdict, per boolean field x over n records::

    O_x = Σ 1[x_i ∈ {true,false}]
    S_x = (n > 0) ∧ (O_x = n)
    V_x = ⋀ x_i   if S_x   else UNKNOWN

``UNKNOWN`` is a first-class value here and never collapses to False or to 0. A
report that presents a decided value where this module computes UNKNOWN has
presented an unknown as a fact, which is a hard failure distinct from a wrong
value.

Bounds, per actor i, from ``bounds_origin`` o and ``bounds_extent`` e::

    min = o - e ;  max = o + e
    B_i = finite(min) ∧ finite(max) ∧ ⋀_{a∈{x,y,z}} min_a ≤ max_a ∧ ¬degenerate(e)

    ActorBoundsValid = (n > 0) ∧ ⋀ B_i          — NEVER from an actor count.

The ``¬degenerate`` conjunct (all-zero extent) is carried over from
``scene_survey_evidence.derive_actor_bounds_valid:292-293`` so this module cannot
be used to WEAKEN that rail. The ``min_a ≤ max_a`` conjunct is stronger than the
evidence model, which never checks extent sign: a negative extent means min > max
and is a real defect the shared derivation would accept.

Grounding, per marker m::

    G_m = contact ∧ (A_supported/A_required ≥ τ_s) ∧ |Δz| ≤ τ_z ∧ (n̂·ẑ ≥ cos θ_max)

Cleanup, over the pre (i) and post (f) inventories::

    CleanupVerified = (D_f = D_i) ∧ (T_f = T_i) ∧ (M_f = M_i)

where D = dirty_packages, T = operation_owned_actor_paths, M = actor_paths. The
T conjunct is NOT in ``scene_survey_evidence.derive_cleanup_verified:374-388``,
which compares only M and D; ``operation_owned_actor_paths`` is read there only by
``derive_temporary_actor_count:391-396`` and never folded into the cleanup verdict.
An operation that spawned and failed to destroy a transient actor that was already
in the level's actor set would satisfy the shared derivation and fail this one.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/scene_survey_recompute.py
"""

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

# VOCABULARY ONLY — see the module docstring for why each of these is safe to
# share and why no derivation is.
from scene_survey_evidence import (  # noqa: E402
    ACCEPTANCE_CLASSIFICATIONS, CALLER_SUPPLIED, CLASSIFICATIONS, DERIVED,
    OBSERVED, STAGE_ORDER, STAGES,
)

SCHEMA_VERSION = "wf.scene_survey.recompute.v1"


# --------------------------------------------------------------------------- #
# Ternary logic. UNKNOWN is a value, not a missing one.
# --------------------------------------------------------------------------- #
class _Unknown(object):
    """Sentinel. Deliberately falsy-hostile: ``bool(UNKNOWN)`` raises.

    An UNKNOWN that can be tested with ``if v:`` will eventually be tested with
    ``if v:``, and will read as False. Raising turns that mistake into a stack
    trace at author time instead of a silent verdict at gate time.
    """

    __slots__ = ()

    def __repr__(self):
        return "UNKNOWN"

    def __bool__(self):
        raise TypeError(
            "UNKNOWN has no truth value — an unknown verdict must be handled "
            "explicitly, never allowed to read as False")

    __nonzero__ = __bool__  # py2-style guard, harmless


UNKNOWN = _Unknown()

TRI = (True, False, UNKNOWN)


def tri(value):
    """Coerce a raw nullable observation to a tri-state. None -> UNKNOWN."""
    if value is True:
        return True
    if value is False:
        return False
    return UNKNOWN


def tri_and(*values):
    """Kleene conjunction: False dominates, then UNKNOWN, else True."""
    vals = list(values)
    if any(v is False for v in vals):
        return False
    if any(v is UNKNOWN for v in vals):
        return UNKNOWN
    return True


def tri_not(value):
    if value is UNKNOWN:
        return UNKNOWN
    return not value


def is_decided(value):
    return value is True or value is False


def observability(values):
    """The O / S / V triple for one boolean field over n records.

    Returns ``{"n", "observed", "sufficient", "verdict", "undecided_index"}``.
    ``verdict`` is UNKNOWN whenever the field was not observed on every record,
    including the n == 0 case — an ``all()`` over an empty list is a confident
    answer about nothing (``scene_survey_evidence.py:266-269``).
    """
    vals = list(values)
    n = len(vals)
    decided = [v for v in vals if is_decided(v)]
    o = len(decided)
    sufficient = (n > 0) and (o == n)
    verdict = all(decided) if sufficient else UNKNOWN
    return {
        "n": n,
        "observed": o,
        "sufficient": sufficient,
        "verdict": verdict,
        "undecided_index": [i for i, v in enumerate(vals) if not is_decided(v)],
    }


def counted(values):
    """A COUNT over a tri-state population.

    The count is decided only when every element is decided; otherwise the count
    is UNKNOWN. "3 of the 5 I could read were true" is not a count of true things.
    """
    vals = list(values)
    n = len(vals)
    if n == 0 or not all(is_decided(v) for v in vals):
        return {"n": n, "sufficient": False, "verdict": UNKNOWN,
                "undecided_index": [i for i, v in enumerate(vals)
                                    if not is_decided(v)]}
    return {"n": n, "sufficient": True, "verdict": sum(1 for v in vals if v),
            "undecided_index": []}


# --------------------------------------------------------------------------- #
# Tolerances. Every one is a stated number with a stated provenance, and every one
# is overridable by the caller — a hidden constant is a law nobody voted on.
# --------------------------------------------------------------------------- #
# [verified] The far side requires ALL four footprint corner traces to hit:
# `all(bool(h) for h in hits)` at scene_survey_far_side.py:930. τ_s = 1.0 is that
# rule expressed as a fraction, not a new policy.
TAU_SUPPORTED_FRACTION = 1.0

# [assumed] No ground-contact Δz tolerance exists anywhere in the repo (grepped:
# no TAU/_TOL/TOLERANCE/slope constant in tools/pipeline or tools/bridge outside
# validate_subject_binding's tolerance_cm=1.0). 100.0 cm is taken from the probe's
# OWN declared near-band: the ground trace starts at location_z + 100.0
# (scene_survey_far_side.py:903-904) and runs to location_z - 3000.0, so a contact
# further than 100 cm from the candidate is a hit the probe would still report
# while the candidate floats. Stated as an assumption, not smuggled as a fact.
TAU_GROUND_DZ_CM = 100.0

# [assumed] Unreal's default UCharacterMovementComponent walkable floor angle.
# Again: no repo constant exists to inherit.
THETA_MAX_DEG = 44.0

# Fields whose value is CALLER VOCABULARY by nature. WorldForge has no channel
# that could observe either — run_scene_survey_probe.py:311-316 says so in the
# assembler itself, and scene_survey_evidence.py:517-522 classifies both as
# CALLER_SUPPLIED. A record presenting one of these as OBSERVED (or DERIVED from
# observation) is a forged provenance claim, not a stronger one.
REQUEST_DERIVED_FIELDS = ("subject_id", "subject_resolved_by")

# The raw-bundle kinds the far side emits (scene_survey_far_side.py:989-999).
BUNDLE_KINDS = ("world", "actor", "component", "trace", "marker", "proxy",
                "temporary_placement", "inventory")

# Ref-bearing keys on far-side raw records, and the kind each must resolve into.
# Every one of these is a pointer that can dangle; a dangling pointer is a missing
# referenced record, which is a hard failure rather than an absent optional.
REF_FIELDS = (
    ("marker", "ground_trace_ref", "trace", False),
    ("marker", "footprint_trace_refs", "trace", True),
    ("actor", "component_refs", "component", True),
    ("component", "actor_ref", "actor", False),
)


# --------------------------------------------------------------------------- #
# Parsing. Duplicate keys are invisible to json.loads (last one wins) and are a
# textbook way to ship two answers and have the reader pick the convenient one.
# --------------------------------------------------------------------------- #
def parse_json_no_duplicates(text):
    """Parse JSON text, returning ``(obj, duplicate_keys)``.

    ``json.loads`` silently keeps the LAST value for a repeated key. A raw bundle
    is addressed by object key (``{kind: {ident: record}}``,
    ``scene_survey_evidence.py:243-244``), so a repeated key IS a duplicate
    record_id — one that no post-parse inspection can ever see. It has to be
    caught at parse time or not at all.
    """
    duplicates = []

    def _hook(pairs):
        seen = set()
        out = {}
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
            out[key] = value
        return out

    obj = json.loads(text, object_pairs_hook=_hook)
    return obj, sorted(set(duplicates))


# --------------------------------------------------------------------------- #
# Numeric helpers. Non-finite is never "close enough"; bool is never a number.
# --------------------------------------------------------------------------- #
def is_finite_number(x):
    if isinstance(x, bool):
        return False
    if not isinstance(x, (int, float)):
        return False
    return not (math.isnan(x) or math.isinf(x))


def is_finite_vec(v, n=3):
    return isinstance(v, list) and len(v) == n and all(is_finite_number(x) for x in v)


def parse_iso_epoch(text):
    """ISO-8601 -> epoch seconds, or None. Accepts a trailing ``Z``; assumes UTC.

    Local to this module rather than borrowed from ``scene_survey_operation._parse_iso``
    because that is a private symbol of a file under active edit, and a freshness rail
    that silently stops parsing is a freshness rail that silently stops firing.
    """
    import datetime
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def nonfinite_numerics(obj, path="$"):
    """Every JSON location holding a non-finite float. Fail-closed input hygiene.

    ``json.loads`` accepts ``NaN`` / ``Infinity`` by default, so a report can carry
    a number that compares False against everything including itself.
    """
    out = []
    if isinstance(obj, dict):
        for k, v in sorted(obj.items()):
            out.extend(nonfinite_numerics(v, "{}.{}".format(path, k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(nonfinite_numerics(v, "{}[{}]".format(path, i)))
    elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        out.append(path)
    return out


# --------------------------------------------------------------------------- #
# Package-path identity. Re-implemented; cross-checked against the assembler's in
# _dogfood so a drift between the two is a reported failure, not an assumption.
# --------------------------------------------------------------------------- #
def canon_package(p):
    """``/Game/Maps/Foo.Foo`` and ``/Game/Maps/Foo`` denote one package. Case kept."""
    if not isinstance(p, str):
        return None
    s = p.strip().rstrip("/")
    if not s:
        return None
    head, sep, tail = s.rpartition("/")
    if sep and "." in tail:
        s = head + "/" + tail.split(".", 1)[0]
    return s or None


def norm_package(p):
    """Comparison key for package identity: canonical form, case-folded."""
    c = canon_package(p)
    return c.lower() if c is not None else None


# --------------------------------------------------------------------------- #
# Ref resolution. Mine, not the shared one — see the module docstring.
# --------------------------------------------------------------------------- #
def resolve_ref(bundle, ref):
    """Resolve one ``"<kind>#<ident>"`` ref against a bundle, or None."""
    if not isinstance(ref, str) or "#" not in ref:
        return None
    kind, _, ident = ref.partition("#")
    kinds = bundle if isinstance(bundle, dict) else {}
    container = kinds.get(kind)
    if not isinstance(container, dict):
        return None
    return container.get(ident)


def dangling_refs(bundle):
    """Every declared ref in the bundle that does not resolve, with its source.

    Returns a sorted list of ``"<kind>#<ident>.<field> -> <ref>"`` strings.
    """
    out = []
    kinds = bundle if isinstance(bundle, dict) else {}
    for kind, field, want_kind, is_list in REF_FIELDS:
        records = kinds.get(kind)
        if not isinstance(records, dict):
            continue
        for ident, rec in sorted(records.items()):
            if not isinstance(rec, dict) or field not in rec:
                continue
            raw = rec.get(field)
            refs = raw if is_list else [raw]
            if not isinstance(refs, list):
                out.append("{}#{}.{} -> not a list: {!r}".format(
                    kind, ident, field, raw))
                continue
            for ref in refs:
                if ref is None:
                    continue
                if not isinstance(ref, str) or not ref.startswith(want_kind + "#"):
                    out.append("{}#{}.{} -> not a {} ref: {!r}".format(
                        kind, ident, field, want_kind, ref))
                    continue
                if resolve_ref(bundle, ref) is None:
                    out.append("{}#{}.{} -> {} (unresolved)".format(
                        kind, ident, field, ref))
    # Generic evidence-record raw_refs, wherever they appear in the bundle.
    for kind in sorted(kinds):
        records = kinds.get(kind)
        if not isinstance(records, dict):
            continue
        for ident, rec in sorted(records.items()):
            if not isinstance(rec, dict):
                continue
            for ref in rec.get("raw_refs") or []:
                if resolve_ref(bundle, ref) is None:
                    out.append("{}#{}.raw_refs -> {!r} (unresolved)".format(
                        kind, ident, ref))
    return sorted(set(out))


# --------------------------------------------------------------------------- #
# ACTOR BOUNDS.  B_i and ActorBoundsValid.
# --------------------------------------------------------------------------- #
def bounds_valid(actor):
    """B_i for one actor record. Returns ``(tri_verdict, reason)``.

    UNKNOWN — the bounds were not collected at all. That is not a False: an actor
    whose bounds could not be read has not been shown to have INVALID bounds, and
    reporting it as invalid would be as dishonest as reporting it as valid. It
    makes the AGGREGATE unknown, which is the honest consequence.
    """
    if not isinstance(actor, dict):
        return UNKNOWN, "actor record is not an object"
    origin = actor.get("bounds_origin")
    extent = actor.get("bounds_extent")
    if origin is None and extent is None:
        return UNKNOWN, "no bounds were collected for this actor"
    if not is_finite_vec(extent):
        if extent is None:
            return UNKNOWN, "bounds_extent absent: {!r}".format(extent)
        return False, "bounds_extent is not a finite vec3: {!r}".format(extent)
    if not is_finite_vec(origin):
        if origin is None:
            return UNKNOWN, "bounds_origin absent; min/max cannot be formed"
        return False, "bounds_origin is not a finite vec3: {!r}".format(origin)
    lo = [float(origin[a]) - float(extent[a]) for a in range(3)]
    hi = [float(origin[a]) + float(extent[a]) for a in range(3)]
    if not (is_finite_vec(lo) and is_finite_vec(hi)):
        return False, "min/max overflowed to non-finite: min={!r} max={!r}".format(lo, hi)
    bad_axis = [a for a in range(3) if not lo[a] <= hi[a]]
    if bad_axis:
        return False, "min > max on axis/axes {} (negative extent {!r})".format(
            bad_axis, extent)
    if all(float(v) == 0.0 for v in extent):
        return False, "degenerate zero extent"
    return True, "finite bounds, min<=max on all axes, non-degenerate"


def actor_bounds_valid(raw):
    """ActorBoundsValid = (n > 0) ∧ ⋀ B_i. NEVER from an actor count."""
    actors = (raw or {}).get("actor")
    actors = actors if isinstance(actors, dict) else {}
    per = []
    reasons = {}
    for ident in sorted(actors):
        verdict, reason = bounds_valid(actors[ident])
        per.append(verdict)
        if verdict is not True:
            reasons[ident] = reason
    obs = observability(per)
    obs["rejected"] = sorted(k for k in reasons if reasons[k] and
                             not reasons[k].startswith("no bounds") and
                             not reasons[k].endswith("absent"))
    obs["reasons"] = dict(sorted(reasons.items())[:8])
    obs["detail"] = ("{} actor record(s); {} with a decided bounds verdict"
                     .format(obs["n"], obs["observed"]))
    if obs["n"] == 0:
        obs["detail"] = ("no per-actor records were collected — an actor COUNT "
                         "cannot answer whether bounds are valid")
    return obs


# --------------------------------------------------------------------------- #
# MARKERS.  Derived from ATOMS, then compared against the far side's restatements.
# --------------------------------------------------------------------------- #
def marker_atoms(bundle, marker):
    """Re-derive one marker's four booleans from its ATOMS.

    Returns a dict of tri-states plus the atom values used. Nothing here reads
    ``grounded`` / ``footprint`` / ``overlap`` / ``capsule_clear`` — those are the
    restatements this is checked against.
    """
    out = {"contact": UNKNOWN, "footprint": UNKNOWN, "overlap": UNKNOWN,
           "capsule_clear": UNKNOWN, "supported_fraction": None,
           "delta_z": None, "normal_z": None, "atoms": {}}
    if not isinstance(marker, dict):
        return out

    # --- contact: the ground trace's own hit answer -------------------------- #
    ground = resolve_ref(bundle, marker.get("ground_trace_ref"))
    out["atoms"]["ground_trace"] = marker.get("ground_trace_ref")
    if isinstance(ground, dict):
        out["contact"] = tri(ground.get("hit"))
        normal = ground.get("impact_normal")
        if is_finite_vec(normal):
            length = math.sqrt(sum(float(c) ** 2 for c in normal))
            if length > 0.0:
                out["normal_z"] = float(normal[2]) / length

    # --- supported fraction: A_supported / A_required ------------------------ #
    hits = marker.get("footprint_trace_hits")
    if isinstance(hits, list) and hits:
        out["atoms"]["footprint_hits"] = list(hits)
        if all(h is True or h is False for h in hits):
            out["supported_fraction"] = sum(1 for h in hits if h) / float(len(hits))

    # --- |Δz| between the candidate and the surface it contacted ------------- #
    loc = marker.get("location")
    gz = marker.get("ground_impact_z")
    if is_finite_vec(loc) and is_finite_number(gz):
        out["delta_z"] = float(gz) - float(loc[2])

    # --- overlap: the two capsule overlap lists ------------------------------ #
    static = marker.get("capsule_overlap_static_actor_paths")
    dynamic = marker.get("capsule_overlap_dynamic_actor_paths")
    out["atoms"]["overlap_static"] = static
    out["atoms"]["overlap_dynamic"] = dynamic
    if isinstance(static, list) and isinstance(dynamic, list):
        out["overlap"] = bool(static) or bool(dynamic)
        out["capsule_clear"] = not out["overlap"]

    # --- footprint restated from atoms (all corners hit AND ground contact) --- #
    if out["supported_fraction"] is not None and is_decided(out["contact"]):
        out["footprint"] = (out["supported_fraction"] >= TAU_SUPPORTED_FRACTION
                            and out["contact"] is True)
    return out


def grounded_verdict(atoms, tau_supported=TAU_SUPPORTED_FRACTION,
                     tau_z_cm=TAU_GROUND_DZ_CM, theta_max_deg=THETA_MAX_DEG):
    """G_m = contact ∧ (A_s/A_r ≥ τ_s) ∧ |Δz| ≤ τ_z ∧ (n̂·ẑ ≥ cos θ_max).

    Returns ``(tri_verdict, conjuncts)``. Any conjunct whose atom was not
    collected is UNKNOWN, and Kleene conjunction carries that up — so a marker
    whose surface normal was never read yields an UNKNOWN grounding verdict, not a
    quietly-dropped conjunct.
    """
    contact = atoms.get("contact", UNKNOWN)

    frac = atoms.get("supported_fraction")
    support = UNKNOWN if frac is None else (frac >= tau_supported)

    dz = atoms.get("delta_z")
    near = UNKNOWN if dz is None else (abs(dz) <= tau_z_cm)

    nz = atoms.get("normal_z")
    cos_max = math.cos(math.radians(theta_max_deg))
    slope = UNKNOWN if nz is None else (nz >= cos_max)

    conj = {"contact": contact, "footprint_supported": support,
            "ground_distance_within_tau_z": near, "slope_within_theta_max": slope,
            "supported_fraction": frac, "delta_z": dz, "normal_z": nz,
            "tau_supported": tau_supported, "tau_z_cm": tau_z_cm,
            "theta_max_deg": theta_max_deg, "cos_theta_max": cos_max}
    return tri_and(contact, support, near, slope), conj


def marker_contradictions(bundle, raw):
    """Restatements that disagree with the atoms they claim to restate.

    ``scene_survey_far_side.py:69-77`` states that ``grounded`` / ``footprint`` /
    ``overlap`` / ``capsule_clear`` are nullable RESTATEMENTS of atoms emitted
    alongside them. Nothing in the pipeline currently checks that claim. A
    restatement that contradicts its atom is not a smaller lie than a fabricated
    value — it is the same lie with a citation attached.
    """
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    out = []
    for ident in sorted(markers):
        m = markers[ident]
        if not isinstance(m, dict):
            out.append("marker#{}: record is not an object".format(ident))
            continue
        atoms = marker_atoms(bundle, m)
        for field, derived in (("grounded", atoms["contact"]),
                               ("footprint", atoms["footprint"]),
                               ("overlap", atoms["overlap"]),
                               ("capsule_clear", atoms["capsule_clear"])):
            stated = tri(m.get(field))
            if is_decided(stated) and is_decided(derived) and stated != derived:
                out.append("marker#{}.{}: restated {!r} but its atoms derive {!r}"
                           .format(ident, field, stated, derived))
            if is_decided(stated) and derived is UNKNOWN:
                out.append("marker#{}.{}: restated {!r} with no atom to restate"
                           .format(ident, field, stated))
        # capsule_clear must be the negation of overlap, by its own definition.
        so, sc = tri(m.get("overlap")), tri(m.get("capsule_clear"))
        if is_decided(so) and is_decided(sc) and sc == so:
            out.append("marker#{}: overlap={!r} and capsule_clear={!r} are not "
                       "negations".format(ident, so, sc))
        # accepted is the compiled primitive's return; it may not exceed its parts.
        acc = tri(m.get("accepted"))
        if acc is True:
            for field, derived in (("grounded", atoms["contact"]),
                                   ("footprint", atoms["footprint"]),
                                   ("capsule_clear", atoms["capsule_clear"])):
                if derived is False:
                    out.append("marker#{}: accepted=True but its atoms derive "
                               "{}=False".format(ident, field))
    return out


def marker_verdicts(bundle, raw, **taus):
    """Per-marker G_m, overlap and clearance, plus the aggregates over them."""
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    idents = sorted(markers)
    grounded, overlaps, clears, detail = [], [], [], {}
    for ident in idents:
        atoms = marker_atoms(bundle, markers[ident] if isinstance(markers[ident], dict) else {})
        g, conj = grounded_verdict(atoms, **taus)
        grounded.append(g)
        overlaps.append(atoms["overlap"])
        clears.append(atoms["capsule_clear"])
        detail[ident] = {"grounded": repr(g), "conjuncts": {
            k: (repr(v) if v in (True, False, UNKNOWN) else v)
            for k, v in conj.items()}}
    return {
        "idents": idents,
        "per_marker": detail,
        "temporary_placements_grounded": counted(grounded),
        "overlap_count": counted(overlaps),
        "player_clearance_valid": observability(clears),
    }


# --------------------------------------------------------------------------- #
# CLEANUP.  (D_f = D_i) ∧ (T_f = T_i) ∧ (M_f = M_i)
# --------------------------------------------------------------------------- #
def cleanup_sufficiency(raw):
    """Both inventories, both collected, and the post one strictly after cleanup."""
    inv = (raw or {}).get("inventory")
    inv = inv if isinstance(inv, dict) else {}
    pre, post = inv.get("pre"), inv.get("post")
    if not isinstance(pre, dict) or not isinstance(post, dict):
        return False, ("cleanup requires both a pre and a post inventory (have "
                       "pre={}, post={})".format(isinstance(pre, dict),
                                                 isinstance(post, dict)))
    if pre.get("stage") not in STAGES or post.get("stage") not in STAGES:
        return False, "inventory records must name a known stage (pre={!r} post={!r})".format(
            pre.get("stage"), post.get("stage"))
    if STAGE_ORDER[post["stage"]] < STAGE_ORDER["cleanup"]:
        return False, ("the post inventory was taken at stage {!r}, before cleanup "
                       "ran — it cannot witness cleanup".format(post["stage"]))
    if STAGE_ORDER[post["stage"]] <= STAGE_ORDER[pre["stage"]]:
        return False, ("the post inventory stage {!r} does not strictly follow the "
                       "pre inventory stage {!r}".format(post["stage"], pre["stage"]))
    if pre.get("collection_ok") is not True or post.get("collection_ok") is not True:
        return False, "an inventory whose collection failed proves nothing"
    for side, rec in (("pre", pre), ("post", post)):
        for key in ("actor_paths", "dirty_packages", "operation_owned_actor_paths"):
            if not isinstance(rec.get(key), list):
                return False, ("inventory.{}.{} was not collected (got {!r}) — the "
                               "corresponding cleanup conjunct is unaskable".format(
                                   side, key, rec.get(key)))
    return True, "pre@{} post@{}".format(pre["stage"], post["stage"])


def cleanup_verified(raw):
    """The three-conjunct cleanup verdict. UNKNOWN when the raw cannot answer."""
    enough, detail = cleanup_sufficiency(raw)
    if not enough:
        return {"sufficient": False, "verdict": UNKNOWN, "detail": detail}
    inv = raw["inventory"]
    pre, post = inv["pre"], inv["post"]

    def _sets(key):
        return set(pre.get(key) or []), set(post.get(key) or [])

    m_i, m_f = _sets("actor_paths")
    d_i, d_f = _sets("dirty_packages")
    t_i, t_f = _sets("operation_owned_actor_paths")
    conj = {
        "actors_unchanged": m_f == m_i,
        "dirty_packages_unchanged": d_f == d_i,
        "operation_owned_unchanged": t_f == t_i,
    }
    return {
        "sufficient": True,
        "verdict": all(conj.values()),
        "conjuncts": conj,
        "leaked_actors": sorted(m_f - m_i),
        "vanished_actors": sorted(m_i - m_f),
        "newly_dirty_packages": sorted(d_f - d_i),
        "residual_operation_owned": sorted(t_f - t_i),
        "released_operation_owned": sorted(t_i - t_f),
        "detail": detail,
    }


# --------------------------------------------------------------------------- #
# WORLD IDENTITY.  Measured package vs the CALLER's requested package.
# --------------------------------------------------------------------------- #
def world_identity_ok(raw, requested_map):
    """The one binding input that is not a copy of the request.

    Read from ``raw["world"]["observed"]["package_name"]`` — the far side's
    measurement of the world that is actually open
    (``scene_survey_far_side.py:_record_world``) — and NEVER from the report's own
    ``map_asset_path``, which the assembler already set from that same observation
    (``run_scene_survey_probe.py:293``). Comparing the report's field to the
    request would compare a value to a copy of itself one hop later.
    """
    world = ((raw or {}).get("world") or {}).get("observed")
    if not isinstance(world, dict):
        return {"sufficient": False, "verdict": UNKNOWN,
                "detail": "no observed world record in the raw bundle"}
    if world.get("collection_ok") is not True:
        return {"sufficient": False, "verdict": UNKNOWN,
                "detail": "the observed world record reports collection_ok={!r}".format(
                    world.get("collection_ok"))}
    observed = norm_package(world.get("package_name"))
    wanted = norm_package(requested_map)
    if observed is None or wanted is None:
        return {"sufficient": False, "verdict": UNKNOWN,
                "detail": "observed={!r} requested={!r} — one side is unstatable".format(
                    world.get("package_name"), requested_map)}
    return {"sufficient": True, "verdict": observed == wanted,
            "observed_package": world.get("package_name"),
            "requested_package": requested_map,
            "detail": "observed {!r} vs requested {!r}".format(observed, wanted)}


# --------------------------------------------------------------------------- #
# ACCEPTANCE ELIGIBILITY.  A(o) = M ∧ W ∧ P ∧ T ∧ B ∧ E, from the RAW atoms.
#
# WHY THIS EXISTS AT ALL — THE CIRCLE THIS BREAKS
# -----------------------------------------------
# [verified] ``scene_survey_contracts.evaluate_acceptance_eligibility:993-1065``
# is the ONE shared predicate. The assembler calls it at
# ``run_scene_survey_probe.py:795`` and writes its verdict into the report; the
# validator reached the same predicate through ``SS.validate_subject_binding``
# (``scene_survey_contracts.py:1154``) at
# ``validate_scene_survey_runtime.py:415``. Producer and checker therefore agreed
# BY CONSTRUCTION.
#
# Worse, the predicate's "raw" is not raw. ``scene_survey_evidence.acceptance_raw
# :1915-1964`` PROJECTS a three-record ``binding`` bundle out of the (subject,
# report) PAIR: ``binding#observed.world_package`` is ``report["map_asset_path"]``
# (:1943), ``actor_object_path`` is ``report["observed_anchor_object_path"]``
# (:1944), ``actor_location`` is ``report["observed_anchor_location"]`` (:1945).
# Those are the report's own restatements of the far-side document, so every
# "observed" coordinate the shared predicate compares is a value the report chose.
# The far side's actual measurements — ``raw["world"]["observed"]["package_name"]``
# (``scene_survey_far_side.py:2229``) and the per-actor ``location`` /
# ``distance_to_anchor_cm`` records (``:1889``, ``:1905``) — are never consulted by
# it. [verified] ``scene_survey_evidence.py:638`` even exempts the ``binding`` kind
# from the raw-observation kinds, because it is not one.
#
# So this section re-derives eligibility one level BELOW the shared predicate:
# from ``raw["world"]``, ``raw["actor"]`` and ``raw["marker"]`` — records the
# report cannot author, only restate.
#
#   M  anchor_mode is exactly "actor_object_path"        <- caller vocabulary
#   W  requested map == independently observed world     <- raw world record
#   P  requested actor path == independently resolved    <- raw actor population
#   T  stated transform == measured actor transform      <- raw actor.location
#   B  survey origin and measurements bound to that actor<- raw distances/markers
#   E  required raw observations complete, operation-bound, finite, consistent
#
# A(o) = Kleene ⋀ of the six. UNKNOWN is a value: a term the raw cannot answer is
# UNKNOWN, never False and never True, and a report presenting a decided
# acceptance claim over an UNKNOWN re-derivation has invented one.
# --------------------------------------------------------------------------- #
#: The one mode under which the subject's anchor is independently observable.
#: Re-stated here rather than imported so a change to the shared vocabulary shows
#: up as a DISAGREEMENT in ``_dogfood`` instead of propagating silently into both
#: sides at once. Cross-checked against ``scene_survey_evidence
#: .OBSERVABLE_ANCHOR_MODE`` and ``scene_survey_contracts.ANCHOR_MODES`` there.
OBSERVABLE_ANCHOR_MODE = "actor_object_path"
ANCHOR_MODES = ("explicit_transform", "actor_object_path")

# [verified] τ_T — the ONE transform tolerance, in CENTIMETRES (Unreal world units
# are cm; ``scene_survey_far_side.py:1650`` names its own distance field
# ``distance_to_anchor_cm``). 1.0 cm is not invented here: it is the tolerance the
# existing pair-validator already declares — ``scene_survey_contracts
# .validate_subject_binding(..., tolerance_cm=1.0)`` at :1085, applied at :1124.
# Adopting it means this rail cannot be accused of being a NEW policy, and it
# cannot be looser than the rail it is meant to backstop. It is a named constant
# in exactly one place and is threaded through every call site as a parameter, so
# no comparison site may type a literal.
TAU_ANCHOR_TRANSFORM_CM = 1.0

# [assumed] ε_B — NOT a physical tolerance. B compares two numbers that must be
# EQUAL by construction (a distance the far side computed at
# ``scene_survey_far_side.py:1878`` against the same distance recomputed here from
# the same two locations), so the only slack needed is float round-trip through
# JSON. 0.05 cm is four orders of magnitude below τ_T and exists solely so a
# decimal-representation difference is not reported as a survey defect.
TAU_ORIGIN_CONSISTENCY_CM = 0.05

#: The six components, in the order they are conjoined, as they appear in the
#: comparison surface. Names are deliberately NOT the shared predicate's names —
#: these are different terms computed from different inputs, and giving them the
#: same names would invite a later reader to "deduplicate" them back together.
ACCEPTANCE_COMPONENT_FIELDS = (
    "acceptance_anchor_mode_observable",        # M
    "acceptance_world_identity_bound",          # W
    "acceptance_actor_identity_bound",          # P
    "acceptance_actor_transform_bound",         # T
    "acceptance_survey_bound_to_actor",         # B
    "acceptance_raw_observations_complete",     # E
)

#: Where a report STATES each recomputed field, if it states it at all. Only used
#: to locate the claim for comparison — never as an input to a derivation.
#: ``run_scene_survey_probe.py:796-799`` writes ``acceptance_eligible`` at the top
#: level and the shared predicate's per-component verdicts under
#: ``meta.acceptance_components``.
CLAIM_PATHS = {
    "acceptance_eligible": ("acceptance_eligible",),
    "acceptance_anchor_mode_observable":
        ("meta", "acceptance_components", "anchor_mode_observable"),
    "acceptance_world_identity_bound":
        ("meta", "acceptance_components", "observed_world_identity_valid"),
    "acceptance_actor_identity_bound":
        ("meta", "acceptance_components", "observed_actor_identity_valid"),
    "acceptance_actor_transform_bound":
        ("meta", "acceptance_components", "observed_actor_transform_valid"),
    "acceptance_survey_bound_to_actor":
        ("meta", "acceptance_components", "survey_bound_to_observed_actor"),
    "acceptance_raw_observations_complete":
        ("meta", "acceptance_components", "raw_observations_complete"),
}

#: Fields a report is NOT required to state. An ABSENT claim here is not a
#: mismatch — but a STATED one that disagrees is, and a stated one over an
#: undecidable re-derivation is an invention. ``acceptance_eligible`` is
#: deliberately NOT in this set: it is REPORT_REQUIRED
#: (``scene_survey_contracts.py:677``), so omitting it IS a defect. E has no
#: counterpart in the shared predicate at all — it is a term this module adds.
OPTIONAL_CLAIM_FIELDS = frozenset(ACCEPTANCE_COMPONENT_FIELDS)

#: Sentinel for "the report does not carry this key at all", which is a different
#: fact from "the report carries it as null".
_NO_CLAIM = object()

# Raw-record envelope vocabulary (scene_survey_far_side.py:549-568, :268-290).
# Vocabulary only: these are the names the far side writes, and disagreeing about
# a NAME would make every rail below silently pass. No verdict is shared.
CS_COLLECTED = "collected"
CS_PARTIAL = "partial"
SATISFYING_COLLECTION_STATUS = (CS_COLLECTED, CS_PARTIAL)


def _verdict(value, detail, **extra):
    """A tri-state result in the shape ``compare`` reads.

    ``sufficient`` is derived from the verdict rather than passed separately, so
    the two can never drift into "sufficient, but UNKNOWN" — a state whose meaning
    nobody would agree on.
    """
    out = {"sufficient": is_decided(value), "verdict": value, "detail": detail}
    out.update(extra)
    return out


def _distance_cm(a, b):
    """Euclidean distance between two finite vec3s, or None."""
    if not (is_finite_vec(a) and is_finite_vec(b)):
        return None
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))


def _actor_records(raw):
    actors = (raw or {}).get("actor")
    return actors if isinstance(actors, dict) else {}


# --- M ---------------------------------------------------------------------- #
def anchor_mode_observable(subject):
    """M — is the subject's anchor observable AT ALL under the declared mode?

    Read from the CALLER's subject, which is the only place a mode can honestly
    come from. NOT from the report: ``run_scene_survey_probe.py`` never echoes the
    mode into the report, and a mode taken from the produced artifact would be the
    producer certifying its own admissibility.
    """
    if not isinstance(subject, dict) or not subject:
        return _verdict(UNKNOWN, "no caller-resolved subject was supplied, so the "
                                 "anchor mode is unstated and unaskable")
    mode = subject.get("anchor_mode")
    if not isinstance(mode, str) or mode not in ANCHOR_MODES:
        return _verdict(UNKNOWN, "subject states anchor_mode={!r}, which is outside "
                                 "the closed vocabulary {} — an unrecognised mode is "
                                 "not a mode this module may rule on".format(
                                     mode, list(ANCHOR_MODES)),
                        anchor_mode=mode)
    return _verdict(mode == OBSERVABLE_ANCHOR_MODE,
                    "subject anchor_mode={!r}; only {!r} makes the subject's own "
                    "coordinates independently observable".format(
                        mode, OBSERVABLE_ANCHOR_MODE),
                    anchor_mode=mode)


# --- P ---------------------------------------------------------------------- #
def anchor_actor_resolution(raw, requested_path, stated_path=_NO_CLAIM):
    """P — does the caller's actor path resolve in the RAW actor population?

    The far side resolves the anchor by exact ``get_path_name()`` equality
    (``scene_survey_far_side.py:2434-2462``) and then sweeps every level actor
    within the radius, filing one record per actor keyed by that same path
    (``:1601-1658``). The anchor actor is at distance 0 from its own location, so
    if the sweep ran at all the anchor MUST be in the population. An actor set
    that is non-empty and does not contain the requested path therefore did not
    survey the requested actor — that is a decided False, not an unknown.

    ``stated_path`` is the report's ``observed_anchor_object_path`` — the pipeline's
    RESTATEMENT of what it resolved. It is held to the raw record exactly the way T
    holds the stated location to the measured one, and for the same reason: the
    shared predicate compares that restatement to the REQUEST
    (``scene_survey_evidence.py:2014-2016``), which cannot see a report and a
    request that agree with each other while the raw disagrees with both.

    Returns the usual tri-state plus ``record``/``ident`` for the resolved actor,
    so T and B can be measured against the same record P accepted.
    """
    out_extra = {"record": None, "ident": None}
    if not isinstance(requested_path, str) or not requested_path.strip():
        return _verdict(UNKNOWN, "the caller named no anchor_object_path, so there "
                                 "is no actor identity to resolve", **out_extra)
    actors = _actor_records(raw)
    if not actors:
        return _verdict(UNKNOWN, "the raw bundle carries no per-actor records, so "
                                 "the requested actor can be neither found nor ruled "
                                 "out — an absent population is not a negative "
                                 "result", **out_extra)
    matches = sorted(ident for ident, rec in actors.items()
                     if isinstance(rec, dict) and rec.get("path_name") == requested_path)
    if len(matches) > 1:
        return _verdict(False, "{} raw actor records claim path_name {!r} — an "
                               "ambiguous identity is not a resolved one: {}".format(
                                   len(matches), requested_path, matches[:4]),
                        **out_extra)
    if not matches:
        stated = sorted(str(rec.get("path_name")) for rec in actors.values()
                        if isinstance(rec, dict))
        return _verdict(False, "the requested anchor actor {!r} is absent from the "
                               "{} raw actor record(s) the survey collected — the "
                               "survey resolved something else. Present: {}".format(
                                   requested_path, len(actors), stated[:4]),
                        **out_extra)
    ident = matches[0]
    record = actors[ident]
    out_extra = {"record": record, "ident": ident}
    if ident != requested_path:
        # scene_survey_far_side.py:1603 keys the record BY the path. A record whose
        # key and whose measured path disagree is two identities in one record.
        return _verdict(False, "the raw actor record keyed {!r} states path_name "
                               "{!r} — key and measurement name different actors"
                               .format(ident, requested_path), **out_extra)
    if record.get("collection_ok") is not True:
        return _verdict(UNKNOWN, "the raw record for {!r} reports collection_ok={!r} "
                                 "— the actor was named but not successfully "
                                 "observed, so its identity is unestablished, not "
                                 "wrong".format(requested_path,
                                                record.get("collection_ok")),
                        **out_extra)
    if stated_path is not _NO_CLAIM and stated_path is not None \
            and stated_path != record.get("path_name"):
        return _verdict(False, "the report states it anchored on {!r}, but the raw "
                               "record for the requested actor measures path_name "
                               "{!r} — the restatement names a different object "
                               "than the measurement".format(
                                   stated_path, record.get("path_name")),
                        **out_extra)
    return _verdict(True, "the requested anchor actor {!r} resolves to exactly one "
                          "successfully-collected raw actor record{}".format(
                              requested_path,
                              "" if stated_path is _NO_CLAIM
                              else ", and the report restates that same path"),
                    **out_extra)


# --- T ---------------------------------------------------------------------- #
def stated_anchor_transform(subject, report):
    """The transform the pipeline CLAIMS it anchored at, and where the claim came from.

    Precedence, and why: the caller's own ``anchor_location`` wins when it exists,
    because holding a measurement to the REQUEST is strictly stronger than holding
    it to the producer's restatement. Under ``actor_object_path`` the caller
    supplies none by contract (``scene_survey_contracts.py:255-256``), so the
    report's ``observed_anchor_location`` is the only statement available — and
    that is precisely the value this term exists to hold to the raw measurement.
    """
    s = subject if isinstance(subject, dict) else {}
    r = report if isinstance(report, dict) else {}
    want = s.get("anchor_location")
    if is_finite_vec(want):
        return list(want), "subject.anchor_location"
    got = r.get("observed_anchor_location")
    if is_finite_vec(got):
        return list(got), "report.observed_anchor_location"
    return None, "neither the subject nor the report states a finite anchor transform"


def anchor_transform_bound(actor_record, stated, source, tau_cm=TAU_ANCHOR_TRANSFORM_CM):
    """T — does the stated anchor transform agree with the MEASURED actor transform?

    The measured side is ``actor.location``, read off the live object at
    ``scene_survey_far_side.py:1889``; the far side reads the same call to produce
    the anchor it reports (``:2492``). Nothing else in the pipeline compares the
    two, so a report free-typing an ``observed_anchor_location`` that is not where
    the actor is has, until now, been invisible.
    """
    if not isinstance(actor_record, dict):
        return _verdict(UNKNOWN, "no resolved actor record to measure a transform on",
                        tau_cm=tau_cm)
    observed = actor_record.get("location")
    if not is_finite_vec(observed):
        return _verdict(UNKNOWN, "the resolved actor's location was not measured "
                                 "(got {!r}) — an unread transform is not a wrong "
                                 "one".format(observed), tau_cm=tau_cm)
    if not is_finite_vec(stated):
        return _verdict(UNKNOWN, "{} — nothing to compare the measurement against"
                        .format(source), tau_cm=tau_cm,
                        observed_location=list(observed))
    dist = _distance_cm(stated, observed)
    return _verdict(dist <= tau_cm,
                    "stated anchor ({}) {!r} is {:.4f}cm from the measured actor "
                    "location {!r}; tolerance is {}cm".format(
                        source, stated, dist, list(observed), tau_cm),
                    tau_cm=tau_cm, distance_cm=dist, stated_source=source,
                    stated_location=list(stated), observed_location=list(observed))


# --- B ---------------------------------------------------------------------- #
def survey_bound_to_anchor(raw, anchor_location, anchor_ident=None,
                           eps_cm=TAU_ORIGIN_CONSISTENCY_CM):
    """B — were the survey's own measurements taken about THAT actor?

    P and T establish that the right actor exists and that the reported anchor is
    its transform. Neither says the SURVEY used it. This does, from three raw
    facts that only hold if the sweep was centred on the resolved actor:

      b1 the resolved actor's own ``distance_to_anchor_cm`` is ~0. It is measured
         against the sweep centre (``scene_survey_far_side.py:1878``,
         ``center=loc`` at ``:2699``), so a non-zero value means the centre was
         somewhere else.
      b2 every other actor's ``distance_to_anchor_cm`` equals |actor − anchor|
         recomputed here. This is over-determined on purpose: one actor could be
         coincidence, a whole population agreeing cannot be.
      b3 the marker candidates lie on the anchor's own y/z with x offsets in
         constant (index+1) steps — the exact placement law at
         ``scene_survey_far_side.py:2705`` (``ctr.x + (i+1)*STEP, ctr.y, ctr.z``).
         STEP is far-side policy this module is not told, so the LAW is checked
         rather than the value: proportional offsets, shared y and z.

    Kleene conjunction over the three, so a conjunct whose atoms were not
    collected makes B unknown instead of quietly dropping out.
    """
    detail = {}
    if not is_finite_vec(anchor_location):
        return _verdict(UNKNOWN, "no measured anchor location, so nothing can be "
                                 "shown to be bound to it", conjuncts=detail)

    actors = _actor_records(raw)

    # b1 — the anchor actor's own distance to the sweep centre.
    b1 = UNKNOWN
    rec = actors.get(anchor_ident) if anchor_ident is not None else None
    if isinstance(rec, dict) and is_finite_number(rec.get("distance_to_anchor_cm")):
        b1 = abs(float(rec["distance_to_anchor_cm"])) <= eps_cm
        detail["anchor_self_distance_cm"] = float(rec["distance_to_anchor_cm"])
    detail["anchor_is_survey_origin"] = repr(b1)

    # b2 — the whole population's distances, recomputed.
    checked, disagreeing = 0, []
    for ident in sorted(actors):
        arec = actors[ident]
        if not isinstance(arec, dict):
            continue
        loc, dist = arec.get("location"), arec.get("distance_to_anchor_cm")
        if not (is_finite_vec(loc) and is_finite_number(dist)):
            continue
        checked += 1
        mine = _distance_cm(loc, anchor_location)
        if abs(mine - float(dist)) > eps_cm:
            disagreeing.append("{}: states {:.4f}cm, recomputes {:.4f}cm".format(
                ident, float(dist), mine))
    b2 = UNKNOWN if checked == 0 else (not disagreeing)
    detail["actor_distances_checked"] = checked
    detail["actor_distances_disagreeing"] = disagreeing[:4]
    detail["actor_distances_consistent"] = repr(b2)

    # b3 — the marker placement law about the anchor.
    markers = (raw or {}).get("marker")
    markers = markers if isinstance(markers, dict) else {}
    placed = []
    for ident in sorted(markers):
        mrec = markers[ident]
        if not isinstance(mrec, dict):
            continue
        loc, index = mrec.get("location"), mrec.get("index")
        if is_finite_vec(loc) and isinstance(index, int) and not isinstance(index, bool):
            placed.append((index, ident, [float(c) for c in loc]))
    b3, offending = UNKNOWN, []
    if placed:
        placed.sort()
        step = None
        for index, ident, loc in placed:
            if abs(loc[1] - float(anchor_location[1])) > eps_cm \
                    or abs(loc[2] - float(anchor_location[2])) > eps_cm:
                offending.append("{}: y/z {!r} is off the anchor's own y/z {!r}".format(
                    ident, loc[1:], list(anchor_location)[1:]))
                continue
            n = index + 1
            if n <= 0:
                offending.append("{}: index {!r} is not a placement ordinal".format(
                    ident, index))
                continue
            this_step = (loc[0] - float(anchor_location[0])) / float(n)
            if step is None:
                step = this_step
                if abs(step) <= eps_cm:
                    offending.append("{}: derived step {:.4f}cm is degenerate — the "
                                     "candidates are not laid out from the anchor"
                                     .format(ident, step))
            elif abs(this_step - step) > eps_cm:
                offending.append("{}: implies step {:.4f}cm, the first candidate "
                                 "implies {:.4f}cm".format(ident, this_step, step))
        b3 = not offending
        detail["marker_step_cm"] = step
    detail["markers_placed_from_anchor"] = repr(b3)
    detail["marker_offenders"] = offending[:4]

    verdict = tri_and(b1, b2, b3)
    return _verdict(verdict,
                    "anchor_self={} population={} ({} distance(s) recomputed) "
                    "markers={} ({} candidate(s))".format(
                        repr(b1), repr(b2), checked, repr(b3), len(placed)),
                    conjuncts=detail)


# --- E ---------------------------------------------------------------------- #
def raw_observations_complete(raw, bundle=None, operation_id=None,
                              anchor_ident=None):
    """E — is the raw itself complete, operation-bound, finite and self-consistent?

    The other five terms all read values OUT of the raw. E asks whether the raw is
    entitled to be read at all. Four conjuncts, each tri-state:

      e1 COMPLETE      — the world record and (when one was resolved) the anchor
                         actor record collected successfully, and their
                         collection_status / evidence_class are satisfying ones.
      e2 OPERATION-BOUND — every record that names an operation names the SAME one,
                         and it is the operation being graded. A bundle whose
                         records come from two runs is two surveys wearing one name.
      e3 FINITE        — no NaN/Infinity anywhere. A non-finite number compares
                         False against everything including itself, so every
                         threshold above it is decided by accident.
      e4 CONSISTENT    — no dangling refs, no restatement that contradicts its own
                         atom, and the world record's cached ``world_identity``
                         agrees with the ``package_name`` it was cached from
                         (``scene_survey_far_side.py:2238``).

    A conjunct whose evidence is simply absent is UNKNOWN, never False: a bundle
    that predates the envelope fields cannot be convicted of failing them.
    """
    bundle = bundle if bundle is not None else raw
    detail = {}

    # e1 — completeness of the two records acceptance actually stands on.
    world = ((raw or {}).get("world") or {}).get("observed")
    if not isinstance(world, dict):
        e1 = UNKNOWN
        detail["complete"] = "no observed world record"
    else:
        parts = [tri(world.get("collection_ok"))]
        why = []
        if world.get("collection_ok") is not True:
            why.append("world#observed.collection_ok={!r}".format(
                world.get("collection_ok")))
        for label, rec in (("world#observed", world),) + (
                (("actor#" + str(anchor_ident), _actor_records(raw).get(anchor_ident)),)
                if anchor_ident is not None else ()):
            if not isinstance(rec, dict):
                parts.append(UNKNOWN)
                why.append("{} is absent".format(label))
                continue
            status = rec.get("collection_status")
            if status is None:
                parts.append(UNKNOWN)
            elif status not in SATISFYING_COLLECTION_STATUS:
                parts.append(False)
                why.append("{}.collection_status={!r}".format(label, status))
            cls = rec.get("evidence_class")
            if cls is None:
                parts.append(UNKNOWN)
            elif cls not in ACCEPTANCE_CLASSIFICATIONS:
                parts.append(False)
                why.append("{}.evidence_class={!r} cannot satisfy a rail".format(
                    label, cls))
            if label.startswith("actor#") and rec.get("collection_ok") is not True:
                parts.append(False)
                why.append("{}.collection_ok={!r}".format(label,
                                                          rec.get("collection_ok")))
        e1 = tri_and(*parts)
        detail["complete"] = "; ".join(why) or "required records collected"
    detail["complete_verdict"] = repr(e1)

    # e2 — one operation, and the right one.
    stated = set()
    for kind in sorted((raw or {}) if isinstance(raw, dict) else {}):
        records = raw.get(kind)
        if not isinstance(records, dict):
            continue
        for rec in records.values():
            if isinstance(rec, dict) and isinstance(rec.get("operation_id"), str) \
                    and rec["operation_id"].strip():
                stated.add(rec["operation_id"])
    if not stated:
        e2 = UNKNOWN
        detail["operation_bound"] = ("no raw record states an operation_id — the "
                                     "bundle cannot be shown to belong to this run")
    elif len(stated) > 1:
        e2 = False
        detail["operation_bound"] = ("raw records name {} different operations {} — "
                                     "one bundle, two runs".format(len(stated),
                                                                   sorted(stated)))
    elif operation_id is not None and stated != {operation_id}:
        e2 = False
        detail["operation_bound"] = ("raw records name operation {!r}, but the "
                                     "operation being graded is {!r}".format(
                                         sorted(stated)[0], operation_id))
    else:
        e2 = True
        detail["operation_bound"] = "every record names {!r}".format(sorted(stated)[0])
    detail["operation_bound_verdict"] = repr(e2)

    # e3 — finiteness.
    nonfinite = nonfinite_numerics(raw)
    e3 = not nonfinite
    detail["nonfinite"] = nonfinite[:4]

    # e4 — internal consistency.
    dangling = dangling_refs(bundle)
    contradictions = marker_contradictions(bundle, raw)
    identity_drift = []
    if isinstance(world, dict) and "world_identity" in world:
        if norm_package(world.get("world_identity")) != norm_package(
                world.get("package_name")):
            identity_drift.append(
                "world#observed.world_identity={!r} but package_name={!r}".format(
                    world.get("world_identity"), world.get("package_name")))
    e4 = not (dangling or contradictions or identity_drift)
    detail["dangling_refs"] = dangling[:3]
    detail["contradictions"] = contradictions[:3]
    detail["identity_drift"] = identity_drift

    verdict = tri_and(e1, e2, e3, e4)
    return _verdict(verdict,
                    "complete={} operation_bound={} finite={} consistent={}".format(
                        repr(e1), repr(e2), e3, e4),
                    conjuncts=detail)


def acceptance_eligibility(raw, subject=None, report=None, bundle=None,
                           requested_map=None, operation_id=None,
                           tau_anchor_transform_cm=TAU_ANCHOR_TRANSFORM_CM,
                           tau_origin_consistency_cm=TAU_ORIGIN_CONSISTENCY_CM,
                           world=None):
    """A(o) = M ∧ W ∧ P ∧ T ∧ B ∧ E, over the raw atoms. Returns the six + the whole.

    ``report`` is read for exactly one purpose — the transform it STATES, so T can
    hold that statement against the measurement. Its ``acceptance_eligible``, its
    ``meta.acceptance_components`` and its failed-rail list are never inputs here;
    ``compare`` reads them afterwards, to grade this result against, which is the
    opposite direction.
    """
    bundle = bundle if bundle is not None else raw
    s = subject if isinstance(subject, dict) else {}
    if requested_map is None:
        requested_map = s.get("map_asset_path")

    m = anchor_mode_observable(subject)
    w = dict(world) if isinstance(world, dict) else world_identity_ok(raw, requested_map)
    p = anchor_actor_resolution(
        raw, s.get("anchor_object_path"),
        stated_path=(report.get("observed_anchor_object_path", _NO_CLAIM)
                     if isinstance(report, dict) else _NO_CLAIM))

    stated, source = stated_anchor_transform(subject, report)
    anchor_record = p.get("record") if p.get("verdict") is True else None
    t = anchor_transform_bound(anchor_record, stated, source,
                               tau_cm=tau_anchor_transform_cm)

    measured_anchor = (anchor_record or {}).get("location") if anchor_record else None
    b = survey_bound_to_anchor(raw, measured_anchor, anchor_ident=p.get("ident"),
                               eps_cm=tau_origin_consistency_cm)
    e = raw_observations_complete(raw, bundle=bundle, operation_id=operation_id,
                                  anchor_ident=(p.get("ident")
                                                if p.get("verdict") is True else None))

    components = {
        "acceptance_anchor_mode_observable": m,
        "acceptance_world_identity_bound": w,
        "acceptance_actor_identity_bound": p,
        "acceptance_actor_transform_bound": t,
        "acceptance_survey_bound_to_actor": b,
        "acceptance_raw_observations_complete": e,
    }
    verdict = tri_and(*[components[f]["verdict"] for f in ACCEPTANCE_COMPONENT_FIELDS])
    denied = [f for f in ACCEPTANCE_COMPONENT_FIELDS
              if components[f]["verdict"] is False]
    undecided = [f for f in ACCEPTANCE_COMPONENT_FIELDS
                 if components[f]["verdict"] is UNKNOWN]
    overall = _verdict(
        verdict,
        "M∧W∧P∧T∧B∧E = {}; denied by {}; undecidable {}".format(
            repr(verdict), denied or "nothing", undecided or "nothing"),
        denied_components=denied, undecided_components=undecided,
        tau_anchor_transform_cm=tau_anchor_transform_cm,
        tau_origin_consistency_cm=tau_origin_consistency_cm)
    out = {"acceptance_eligible": overall}
    out.update(components)
    return out


# --------------------------------------------------------------------------- #
# PROVENANCE.  A request-derived field labelled `observed` is a forgery.
# --------------------------------------------------------------------------- #
def forged_provenance(container):
    """Request-derived fields presented with an acceptance classification.

    ``container`` is any mapping whose values may be evidence records. A record
    for ``subject_id`` or ``subject_resolved_by`` classified OBSERVED or
    DERIVED claims WorldForge measured the caller's own vocabulary. It has no
    such channel (``run_scene_survey_probe.py:311-316``), so the claim is not
    merely unsupported — it is impossible, and it is the one shape that would let
    a report satisfy the subject rails without a caller.
    """
    out = []
    if not isinstance(container, dict):
        return out
    for field in REQUEST_DERIVED_FIELDS:
        rec = container.get(field)
        if not isinstance(rec, dict):
            continue
        cls = rec.get("classification")
        if cls in ACCEPTANCE_CLASSIFICATIONS:
            out.append("{}: classified {!r}, but it is caller vocabulary "
                       "(only {!r} is honest here)".format(field, cls, CALLER_SUPPLIED))
        elif cls is not None and cls not in CLASSIFICATIONS:
            out.append("{}: classification {!r} is outside the closed taxonomy"
                       .format(field, cls))
    return out


# --------------------------------------------------------------------------- #
# THE COMPARISON.  r_reported = f(E_raw), or it is a hard failure.
# --------------------------------------------------------------------------- #
#: reported field -> (recompute key). Every one of these is a value the report
#: presents as decided and this module derives from raw.
COMPARED_FIELDS = (
    "actor_bounds_valid",
    "temporary_placements_grounded",
    "overlap_count",
    "player_clearance_valid",
    "cleanup_verified",
    # Acceptance eligibility and every term it is conjoined from. The whole point
    # of listing the COMPONENTS and not just the verdict: an eligibility claim that
    # happens to agree while its parts disagree is agreement by luck, and the
    # per-component rows are what say WHICH term the raw denied.
    "acceptance_eligible",
) + ACCEPTANCE_COMPONENT_FIELDS


def recompute_all(raw, requested_map=None, bundle=None, subject=None, report=None,
                  operation_id=None,
                  tau_anchor_transform_cm=TAU_ANCHOR_TRANSFORM_CM,
                  tau_origin_consistency_cm=TAU_ORIGIN_CONSISTENCY_CM, **taus):
    """Every recomputable aggregate, from raw only.

    ``report`` is consulted for exactly one value — the anchor transform it STATES,
    which term T holds against the raw measurement (see ``acceptance_eligibility``).
    Nothing else in the report is an input to anything computed here.
    """
    bundle = bundle if bundle is not None else raw
    mk = marker_verdicts(bundle, raw, **taus)
    world = world_identity_ok(raw, requested_map)
    out = {
        "schema_version": SCHEMA_VERSION,
        "actor_bounds_valid": actor_bounds_valid(raw),
        "temporary_placements_grounded": mk["temporary_placements_grounded"],
        "overlap_count": mk["overlap_count"],
        "player_clearance_valid": mk["player_clearance_valid"],
        "cleanup_verified": cleanup_verified(raw),
        "world_identity_ok": world,
        "_markers": mk,
        "_contradictions": marker_contradictions(bundle, raw),
        "_dangling_refs": dangling_refs(bundle),
    }
    out.update(acceptance_eligibility(
        raw, subject=subject, report=report, bundle=bundle,
        requested_map=requested_map, operation_id=operation_id,
        tau_anchor_transform_cm=tau_anchor_transform_cm,
        tau_origin_consistency_cm=tau_origin_consistency_cm,
        world=world))
    return out


def claimed_value(reported, field):
    """What the report STATES for ``field``, or ``_NO_CLAIM`` if it states nothing.

    Most compared fields are top-level report keys. The acceptance components are
    not: ``run_scene_survey_probe.py:798`` files them under
    ``meta.acceptance_components`` under the SHARED predicate's names. Locating a
    claim is not the same as trusting it — the located value is only ever used as
    the right-hand side of a comparison against this module's own derivation.

    ``_NO_CLAIM`` and ``None`` are kept apart because "the report has no such key"
    and "the report says null" are different facts about a document.
    """
    path = CLAIM_PATHS.get(field, (field,))
    cur = reported
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return _NO_CLAIM
        cur = cur[key]
    return cur


def compare(reported, recomputed, fields=COMPARED_FIELDS):
    """``(mismatches, unknown_presented_as_decided)`` for the compared fields.

    Two distinct failure kinds, deliberately not merged:

      * MISMATCH — the raw was sufficient and re-derives to a different value.
        The report does not follow from its own evidence. This is SYMMETRIC:
        claimed True over a re-derived False and claimed False over a re-derived
        True are both mismatches. ``scene_survey_contracts.py:1144-1153``
        deliberately installed only the over-claim direction, because the
        symmetric rail would red a fixture that file's owner could not change;
        this module is not bound by that compromise, and an under-claim is still a
        report that does not follow from its evidence.
      * UNKNOWN-AS-DECIDED — the raw was NOT sufficient, and the report presented
        a decided value anyway. Nothing is being contradicted; something is being
        invented. Collapsing this into "mismatch" would let it be read as a
        rounding disagreement.

    A field in ``OPTIONAL_CLAIM_FIELDS`` that the report does not state at all is
    neither: silence is not a claim. A field outside that set is REQUIRED by the
    report contract, so its absence IS a mismatch.
    """
    reported = reported if isinstance(reported, dict) else {}
    mismatches, invented = [], []
    for field in fields:
        got = recomputed.get(field) or {}
        claimed = claimed_value(reported, field)
        unstated = claimed is _NO_CLAIM or (claimed is None
                                            and field in OPTIONAL_CLAIM_FIELDS)
        verdict = got.get("verdict", UNKNOWN)
        if not got.get("sufficient"):
            if not unstated and claimed is not None:
                invented.append(
                    "{}: report states {!r} but the raw evidence is insufficient "
                    "to decide it ({})".format(field, claimed,
                                               got.get("detail") or got))
            continue
        if verdict is UNKNOWN:
            if not unstated and claimed is not None:
                invented.append("{}: report states {!r}; re-derivation is UNKNOWN"
                                .format(field, claimed))
            continue
        if unstated:
            if field in OPTIONAL_CLAIM_FIELDS:
                continue
            mismatches.append("{}: report omits the field; raw re-derives {!r}"
                              .format(field, verdict))
            continue
        if claimed is None:
            mismatches.append("{}: report omits the field; raw re-derives {!r}"
                              .format(field, verdict))
            continue
        # Strict identity for booleans and strict type-matched equality for counts.
        # `1 == True` in Python, and the report contract requires an explicit bool
        # for the boolean fields (scene_survey_contracts.py:707-709), so a loose
        # comparison here would accept a report that satisfied the rail with the
        # wrong type — exactly the "populate the expected keys" move.
        if isinstance(verdict, bool):
            agrees = claimed is verdict
        else:
            agrees = (not isinstance(claimed, bool)) and claimed == verdict
        if not agrees:
            mismatches.append("{}: report states {!r} ({}) but raw re-derives {!r} ({})"
                              .format(field, claimed, type(claimed).__name__,
                                      verdict, type(verdict).__name__))
    return mismatches, invented


# --------------------------------------------------------------------------- #
# self-dogfood
# --------------------------------------------------------------------------- #
def _clean_bundle():
    """A synthetic raw bundle whose atoms support every claim exactly once."""
    return {
        "schema_version": "wf.scene_survey.raw_evidence_bundle.v1",
        "world": {"observed": {"package_name": "/Game/Fixture/Lvl_Fixture",
                               "collection_ok": True}},
        "actor": {"/Game/A.A:PersistentLevel.A_0": {
            "bounds_origin": [0.0, 0.0, 50.0], "bounds_extent": [100.0, 100.0, 50.0],
            "component_refs": [], "collection_ok": True}},
        "component": {},
        "trace": {
            "marker_000::ground": {"hit": True, "impact_point": [0.0, 0.0, 10.0],
                                   "impact_normal": [0.0, 0.0, 1.0],
                                   "collection_ok": True},
        },
        "marker": {"marker_000": {
            "index": 0, "location": [0.0, 0.0, 10.0],
            "ground_trace_ref": "trace#marker_000::ground",
            "ground_impact_z": 10.0,
            "footprint_trace_refs": [], "footprint_trace_hits": [True, True, True, True],
            "capsule_overlap_static_actor_paths": [],
            "capsule_overlap_dynamic_actor_paths": [],
            "grounded": True, "footprint": True, "overlap": False,
            "capsule_clear": True, "accepted": True, "collection_ok": True}},
        "proxy": {},
        "temporary_placement": {},
        "inventory": {
            "pre": {"stage": "anchor_bind", "collection_ok": True,
                    "actor_paths": ["/A"], "dirty_packages": [],
                    "operation_owned_actor_paths": []},
            "post": {"stage": "cleanup", "collection_ok": True,
                     "actor_paths": ["/A"], "dirty_packages": [],
                     "operation_owned_actor_paths": []}},
    }


#: The one acceptance fixture. Every acceptance negative below is this case with
#: exactly ONE atom changed, so a rail that reds can only be reading that atom.
_ACC_OP = "op_acceptance_fixture_0001"
_ACC_MAP = "/Game/Fixture/Lvl_Fixture"
_ACC_PATH = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.AnchorActor_0"
_ACC_OTHER = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.Bystander_0"
_ACC_ANCHOR = [1200.0, -450.0, 92.5]
_ACC_STEP = 250.0


def _acc_envelope(record_type, ident, stage, **over):
    """The raw-record envelope shape the far side writes (far_side.py:548-567)."""
    rec = {"record_schema": "wf.scene_survey.raw_evidence_record.v1",
           "operation_id": _ACC_OP, "record_id": "{}#{}".format(record_type, ident),
           "record_type": record_type, "record_ident": ident, "stage": stage,
           "collection_status": CS_COLLECTED, "evidence_class": OBSERVED,
           "world_identity": _ACC_MAP, "collection_ok": True, "errors": []}
    rec.update(over)
    return rec


def _clean_acceptance_case():
    """``(subject, report, raw)`` for a survey that IS acceptance-eligible.

    Built so all six terms are decidedly True: an ``actor_object_path`` subject
    (M), a world record naming the requested map (W), exactly one actor record
    carrying the requested path (P), whose measured location is the anchor the
    report states (T), with a population whose distances and a marker sweep whose
    placement law both resolve about that location (B), over records that are
    complete, singly-operation-bound, finite and self-consistent (E).
    """
    subject = {
        "subject_id": "subject_acceptance_alpha",
        "subject_kind": "actor",
        "map_asset_path": _ACC_MAP,
        "anchor_mode": "actor_object_path",
        "anchor_location": None,
        "anchor_rotation": None,
        "anchor_object_path": _ACC_PATH,
        "resolved_by": "caller",
        "schema_version": "wf.scene_survey.survey_subject.v1",
    }
    report = {
        "subject_id": "subject_acceptance_alpha",
        "subject_resolved_by": "caller",
        "map_asset_path": _ACC_MAP,
        "observed_anchor_location": list(_ACC_ANCHOR),
        "observed_anchor_object_path": _ACC_PATH,
        "runtime_executed": True,
        "acceptance_eligible": True,
        "acceptance_ineligibility_reason": None,
        # The five pre-existing compared aggregates, stated as the raw re-derives
        # them, so an acceptance negative can never be confused with one of those
        # rails firing on an incomplete fixture.
        "actor_bounds_valid": True,
        "temporary_placements_grounded": 2,
        "overlap_count": 0,
        "player_clearance_valid": True,
        "cleanup_verified": True,
        "meta": {"acceptance_components": {
            "anchor_mode_observable": True,
            "observed_world_identity_valid": True,
            "observed_actor_identity_valid": True,
            "observed_actor_transform_valid": True,
            "survey_bound_to_observed_actor": True,
        }},
    }
    other = [_ACC_ANCHOR[0] + 200.0, _ACC_ANCHOR[1], _ACC_ANCHOR[2]]
    raw = {
        "schema_version": "wf.scene_survey.raw_evidence_bundle.v1",
        "world": {"observed": _acc_envelope(
            "world", "observed", "world_identity",
            package_name=_ACC_MAP, world_identity=_ACC_MAP,
            world_object_path=_ACC_MAP + ".Lvl_Fixture")},
        "actor": {
            _ACC_PATH: _acc_envelope(
                "actor", _ACC_PATH, "observe", actor_object_path=_ACC_PATH,
                path_name=_ACC_PATH, class_name="AAnchorActor",
                location=list(_ACC_ANCHOR), rotation=[0.0, 0.0, 0.0],
                scale=[1.0, 1.0, 1.0], bounds_origin=list(_ACC_ANCHOR),
                bounds_extent=[50.0, 50.0, 92.5], distance_to_anchor_cm=0.0,
                component_refs=[]),
            _ACC_OTHER: _acc_envelope(
                "actor", _ACC_OTHER, "observe", actor_object_path=_ACC_OTHER,
                path_name=_ACC_OTHER, class_name="AStaticMeshActor",
                location=other, rotation=[0.0, 0.0, 0.0], scale=[1.0, 1.0, 1.0],
                bounds_origin=other, bounds_extent=[25.0, 25.0, 25.0],
                distance_to_anchor_cm=200.0, component_refs=[]),
        },
        "component": {},
        "trace": {},
        "marker": {},
        "proxy": {},
        "temporary_placement": {},
        "inventory": {
            "pre": _acc_envelope("inventory", "pre", "anchor_bind",
                                 actor_paths=[_ACC_PATH, _ACC_OTHER],
                                 dirty_packages=[],
                                 operation_owned_actor_paths=[]),
            "post": _acc_envelope("inventory", "post", "cleanup",
                                  actor_paths=[_ACC_PATH, _ACC_OTHER],
                                  dirty_packages=[],
                                  operation_owned_actor_paths=[]),
        },
    }
    for i in range(2):
        ident = "marker_{:03d}".format(i)
        tref = "trace#{}::ground".format(ident)
        raw["trace"][ident + "::ground"] = _acc_envelope(
            "trace", ident + "::ground", "classify", hit=True,
            impact_point=[_ACC_ANCHOR[0] + (i + 1) * _ACC_STEP, _ACC_ANCHOR[1],
                          _ACC_ANCHOR[2]],
            impact_normal=[0.0, 0.0, 1.0])
        raw["marker"][ident] = _acc_envelope(
            "marker", ident, "classify", index=i,
            location=[_ACC_ANCHOR[0] + (i + 1) * _ACC_STEP, _ACC_ANCHOR[1],
                      _ACC_ANCHOR[2]],
            ground_trace_ref=tref, ground_impact_z=_ACC_ANCHOR[2],
            footprint_trace_refs=[], footprint_trace_hits=[True] * 4,
            capsule_overlap_static_actor_paths=[],
            capsule_overlap_dynamic_actor_paths=[],
            grounded=True, footprint=True, overlap=False, capsule_clear=True,
            accepted=True)
    return subject, report, raw


def _acceptance_dogfood(t):
    """Every acceptance term gets a positive control AND its own negative.

    A rail observed only failing is indistinguishable from a rail that always
    fails, and a rail observed only passing proves nothing at all — so each of the
    six terms is driven both ways from the SAME fixture.
    """
    def rc(subject, report, raw):
        return recompute_all(raw, requested_map=subject.get("map_asset_path"),
                             subject=subject, report=report, operation_id=_ACC_OP)

    # ---- POSITIVE CONTROL: all six decided True, and the claim is accepted ---- #
    s, r, raw = _clean_acceptance_case()
    got = rc(s, r, raw)
    for field in ACCEPTANCE_COMPONENT_FIELDS + ("acceptance_eligible",):
        t("acc_pos_" + field, got[field]["verdict"] is True,
          "{}: {}".format(field, got[field].get("detail")))
    mis, inv = compare(r, got)
    t("acc_pos_report_accepted", mis == [] and inv == [], (mis, inv))

    # ---- M: the mode is the caller's, and explicit_transform is never eligible - #
    s, r, raw = _clean_acceptance_case()
    s["anchor_mode"] = "explicit_transform"
    s["anchor_object_path"] = None
    s["anchor_location"] = list(_ACC_ANCHOR)
    got = rc(s, r, raw)
    t("acc_neg_M_explicit_transform",
      got["acceptance_anchor_mode_observable"]["verdict"] is False
      and got["acceptance_eligible"]["verdict"] is False, got["acceptance_eligible"])
    mis, _i = compare(r, got, ("acceptance_eligible",))
    t("acc_neg_M_overclaim_flagged", len(mis) == 1, mis)
    s, r, raw = _clean_acceptance_case()
    s["anchor_mode"] = "telepathy"
    got = rc(s, r, raw)
    t("acc_neg_M_unknown_mode_is_unknown",
      got["acceptance_anchor_mode_observable"]["verdict"] is UNKNOWN,
      got["acceptance_anchor_mode_observable"])

    # ---- W: measured world package, never the report's echo ------------------- #
    s, r, raw = _clean_acceptance_case()
    raw["world"]["observed"]["package_name"] = "/Game/Fixture/Lvl_Elsewhere"
    got = rc(s, r, raw)
    t("acc_neg_W_other_world",
      got["acceptance_world_identity_bound"]["verdict"] is False
      and got["acceptance_eligible"]["verdict"] is False,
      got["acceptance_world_identity_bound"])
    # ...and the report echoing the RIGHT map does not rescue it.
    t("acc_neg_W_report_echo_does_not_rescue",
      r["map_asset_path"] == _ACC_MAP
      and got["acceptance_eligible"]["verdict"] is False,
      "the report still names the requested map; the raw does not")

    # ---- P: the actor population, not the report's observed_anchor_object_path - #
    s, r, raw = _clean_acceptance_case()
    substituted = raw["actor"].pop(_ACC_PATH)
    substituted["path_name"] = _ACC_OTHER + "_substitute"
    substituted["actor_object_path"] = substituted["path_name"]
    raw["actor"][substituted["path_name"]] = substituted
    got = rc(s, r, raw)
    t("acc_neg_P_substituted_actor",
      got["acceptance_actor_identity_bound"]["verdict"] is False
      and got["acceptance_eligible"]["verdict"] is False,
      got["acceptance_actor_identity_bound"])
    s, r, raw = _clean_acceptance_case()
    raw["actor"] = {}
    got = rc(s, r, raw)
    t("acc_neg_P_no_population_is_unknown",
      got["acceptance_actor_identity_bound"]["verdict"] is UNKNOWN
      and got["acceptance_eligible"]["verdict"] is UNKNOWN,
      got["acceptance_actor_identity_bound"])
    _m, inv = compare(r, got, ("acceptance_eligible",))
    t("acc_neg_P_unknown_presented_as_decided", len(inv) == 1, inv)
    s, r, raw = _clean_acceptance_case()
    raw["actor"][_ACC_PATH]["collection_ok"] = False
    got = rc(s, r, raw)
    t("acc_neg_P_uncollected_actor_is_unknown",
      got["acceptance_actor_identity_bound"]["verdict"] is UNKNOWN,
      got["acceptance_actor_identity_bound"])
    # ...and the report's own restatement of what it anchored on is held to the raw.
    s, r, raw = _clean_acceptance_case()
    r["observed_anchor_object_path"] = _ACC_OTHER
    got = rc(s, r, raw)
    t("acc_neg_P_restated_path_contradicts_raw",
      got["acceptance_actor_identity_bound"]["verdict"] is False
      and got["acceptance_eligible"]["verdict"] is False,
      got["acceptance_actor_identity_bound"])

    # ---- T: the stated transform vs the measured one -------------------------- #
    s, r, raw = _clean_acceptance_case()
    r["observed_anchor_location"] = [_ACC_ANCHOR[0] + 500.0, _ACC_ANCHOR[1],
                                     _ACC_ANCHOR[2]]
    got = rc(s, r, raw)
    t("acc_neg_T_drifted_transform",
      got["acceptance_actor_transform_bound"]["verdict"] is False
      and got["acceptance_eligible"]["verdict"] is False,
      got["acceptance_actor_transform_bound"])
    # ...and the tolerance is the named contract value, honoured at the boundary.
    s, r, raw = _clean_acceptance_case()
    r["observed_anchor_location"] = [_ACC_ANCHOR[0] + TAU_ANCHOR_TRANSFORM_CM * 0.5,
                                     _ACC_ANCHOR[1], _ACC_ANCHOR[2]]
    t("acc_pos_T_within_tau",
      rc(s, r, raw)["acceptance_actor_transform_bound"]["verdict"] is True)
    s, r, raw = _clean_acceptance_case()
    r["observed_anchor_location"] = [_ACC_ANCHOR[0] + TAU_ANCHOR_TRANSFORM_CM * 2.0,
                                     _ACC_ANCHOR[1], _ACC_ANCHOR[2]]
    t("acc_neg_T_beyond_tau",
      rc(s, r, raw)["acceptance_actor_transform_bound"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    raw["actor"][_ACC_PATH]["location"] = None
    got = rc(s, r, raw)
    t("acc_neg_T_unmeasured_is_unknown",
      got["acceptance_actor_transform_bound"]["verdict"] is UNKNOWN,
      got["acceptance_actor_transform_bound"])

    # ---- B: the survey origin actually used ----------------------------------- #
    s, r, raw = _clean_acceptance_case()
    raw["actor"][_ACC_OTHER]["distance_to_anchor_cm"] = 999.0
    got = rc(s, r, raw)
    t("acc_neg_B_population_distance_disagrees",
      got["acceptance_survey_bound_to_actor"]["verdict"] is False
      and got["acceptance_eligible"]["verdict"] is False,
      got["acceptance_survey_bound_to_actor"])
    s, r, raw = _clean_acceptance_case()
    raw["actor"][_ACC_PATH]["distance_to_anchor_cm"] = 700.0
    t("acc_neg_B_anchor_is_not_the_origin",
      rc(s, r, raw)["acceptance_survey_bound_to_actor"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    raw["marker"]["marker_001"]["location"] = [_ACC_ANCHOR[0] + 3.0 * _ACC_STEP,
                                               _ACC_ANCHOR[1], _ACC_ANCHOR[2]]
    t("acc_neg_B_marker_step_breaks",
      rc(s, r, raw)["acceptance_survey_bound_to_actor"]["verdict"] is False,
      "candidate 1 must sit at 2 steps from the anchor, not 3")
    s, r, raw = _clean_acceptance_case()
    raw["marker"]["marker_000"]["location"] = [_ACC_ANCHOR[0] + _ACC_STEP,
                                               _ACC_ANCHOR[1] + 400.0, _ACC_ANCHOR[2]]
    t("acc_neg_B_marker_off_anchor_axis",
      rc(s, r, raw)["acceptance_survey_bound_to_actor"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    for ident in list(raw["actor"]):
        raw["actor"][ident].pop("distance_to_anchor_cm", None)
    raw["marker"] = {}
    got = rc(s, r, raw)
    t("acc_neg_B_no_binding_atoms_is_unknown",
      got["acceptance_survey_bound_to_actor"]["verdict"] is UNKNOWN,
      got["acceptance_survey_bound_to_actor"])

    # ---- E: the raw's own right to be read ------------------------------------ #
    s, r, raw = _clean_acceptance_case()
    raw["actor"][_ACC_OTHER]["operation_id"] = "op_some_other_run"
    got = rc(s, r, raw)
    t("acc_neg_E_two_operations_in_one_bundle",
      got["acceptance_raw_observations_complete"]["verdict"] is False
      and got["acceptance_eligible"]["verdict"] is False,
      got["acceptance_raw_observations_complete"])
    s, r, raw = _clean_acceptance_case()
    got = recompute_all(raw, requested_map=_ACC_MAP, subject=s, report=r,
                        operation_id="op_the_one_being_graded")
    t("acc_neg_E_bundle_from_another_operation",
      got["acceptance_raw_observations_complete"]["verdict"] is False,
      got["acceptance_raw_observations_complete"])
    s, r, raw = _clean_acceptance_case()
    raw["world"]["observed"]["collection_status"] = "failed"
    t("acc_neg_E_failed_world_record",
      rc(s, r, raw)["acceptance_raw_observations_complete"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    raw["world"]["observed"]["evidence_class"] = "unsupported"
    t("acc_neg_E_unsatisfying_evidence_class",
      rc(s, r, raw)["acceptance_raw_observations_complete"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    raw["world"]["observed"]["world_identity"] = "/Game/Fixture/Lvl_Elsewhere"
    t("acc_neg_E_world_identity_drift",
      rc(s, r, raw)["acceptance_raw_observations_complete"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    raw["actor"][_ACC_OTHER]["location"] = [float("nan"), 0.0, 0.0]
    t("acc_neg_E_nonfinite_atom",
      rc(s, r, raw)["acceptance_raw_observations_complete"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    raw["marker"]["marker_000"]["ground_trace_ref"] = "trace#gone"
    t("acc_neg_E_dangling_ref",
      rc(s, r, raw)["acceptance_raw_observations_complete"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    raw["marker"]["marker_000"]["grounded"] = False
    t("acc_neg_E_contradictory_restatement",
      rc(s, r, raw)["acceptance_raw_observations_complete"]["verdict"] is False)
    s, r, raw = _clean_acceptance_case()
    for kind in ("world", "actor", "marker", "trace", "inventory"):
        for rec in raw[kind].values():
            rec.pop("operation_id", None)
    got = rc(s, r, raw)
    t("acc_neg_E_unbound_bundle_is_unknown",
      got["acceptance_raw_observations_complete"]["verdict"] is UNKNOWN,
      got["acceptance_raw_observations_complete"])

    # ---- the SYMMETRIC direction contracts:1144-1153 declined to install ------ #
    s, r, raw = _clean_acceptance_case()
    r["acceptance_eligible"] = False
    mis, _i = compare(r, rc(s, r, raw), ("acceptance_eligible",))
    t("acc_neg_underclaim_is_also_a_mismatch", len(mis) == 1,
      "a report claiming ineligible over raw that re-derives eligible must FAIL "
      "too, or the rail only polices one direction: {}".format(mis))

    # ---- a component claim that disagrees with its own raw -------------------- #
    s, r, raw = _clean_acceptance_case()
    raw["actor"][_ACC_OTHER]["distance_to_anchor_cm"] = 999.0
    r["meta"]["acceptance_components"]["survey_bound_to_observed_actor"] = True
    mis, _i = compare(r, rc(s, r, raw), ("acceptance_survey_bound_to_actor",))
    t("acc_neg_component_claim_mismatch", len(mis) == 1, mis)

    # ---- an UNSTATED optional component is silence, not a mismatch ------------ #
    s, r, raw = _clean_acceptance_case()
    r.pop("meta")
    mis, inv = compare(r, rc(s, r, raw))
    t("acc_pos_unstated_components_are_not_mismatches", mis == [] and inv == [],
      (mis, inv))

    # ---- anti-circularity, asserted STRUCTURALLY over this module's own AST ---- #
    # A comment promising independence is what this module had before, and it was
    # false for two months. So the promise is now a test: parse this file and
    # assert that no CALL anywhere in it names the shared acceptance predicate or
    # any of the functions that reach it. Prose in a docstring cannot satisfy this,
    # and a future edit that quietly re-shares the predicate cannot pass it.
    import ast
    banned = ("evaluate_acceptance_eligibility", "validate_subject_binding",
              "acceptance_eligibility_record", "acceptance_raw",
              "derive_acceptance_eligibility", "sufficiency_acceptance_eligibility",
              "rederive_and_compare", "derived_record")
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    called = set()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                called.add(fn.attr)
            elif isinstance(fn, ast.Name):
                called.add(fn.id)
        elif isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
    reached = sorted(set(banned) & (called | imported))
    t("acc_no_shared_predicate_reached", reached == [],
      "this module must never call or import the shared acceptance predicate; "
      "its AST names {}".format(reached))
    # ...and `derive` itself, the generic entry point into the shared DERIVATIONS
    # table, must not be reachable under any alias either.
    t("acc_no_shared_derive_call", "derive" not in called,
      "a call to the shared scene_survey_evidence.derive() would make this "
      "module's verdict the assembler's verdict wearing a different name")

    # ---- the shared vocabulary must not drift out from under the local copy --- #
    try:
        import scene_survey_evidence as SE
        t("acc_vocab_anchor_mode_agrees",
          OBSERVABLE_ANCHOR_MODE == SE.OBSERVABLE_ANCHOR_MODE,
          "mine={!r} theirs={!r}".format(OBSERVABLE_ANCHOR_MODE,
                                         SE.OBSERVABLE_ANCHOR_MODE))
    except Exception as exc:  # noqa: BLE001
        print("[recompute] NOTE — anchor-mode vocabulary cross-check skipped: "
              "{}".format(exc))
    try:
        import scene_survey_contracts as SC
        t("acc_vocab_anchor_modes_agree",
          tuple(ANCHOR_MODES) == tuple(SC.ANCHOR_MODES),
          "mine={} theirs={}".format(ANCHOR_MODES, SC.ANCHOR_MODES))
    except Exception as exc:  # noqa: BLE001
        print("[recompute] NOTE — anchor-modes vocabulary cross-check skipped: "
              "{}".format(exc))


def _main():
    failures = []

    def t(label, cond, detail=""):
        if not cond:
            failures.append("{}: {}".format(label, detail))

    raw = _clean_bundle()

    # ---- POSITIVE control: the clean bundle decides every field ------------- #
    rc = recompute_all(raw, requested_map="/Game/Fixture/Lvl_Fixture")
    t("clean_bounds", rc["actor_bounds_valid"]["verdict"] is True, rc["actor_bounds_valid"])
    t("clean_grounded", rc["temporary_placements_grounded"]["verdict"] == 1,
      rc["temporary_placements_grounded"])
    t("clean_overlap", rc["overlap_count"]["verdict"] == 0, rc["overlap_count"])
    t("clean_clearance", rc["player_clearance_valid"]["verdict"] is True,
      rc["player_clearance_valid"])
    t("clean_cleanup", rc["cleanup_verified"]["verdict"] is True, rc["cleanup_verified"])
    t("clean_world", rc["world_identity_ok"]["verdict"] is True, rc["world_identity_ok"])
    t("clean_no_contradictions", rc["_contradictions"] == [], rc["_contradictions"])
    t("clean_no_dangling", rc["_dangling_refs"] == [], rc["_dangling_refs"])
    honest = {"actor_bounds_valid": True, "temporary_placements_grounded": 1,
              "overlap_count": 0, "player_clearance_valid": True,
              "cleanup_verified": True}
    mis, inv = compare(honest, rc)
    t("clean_report_accepted", mis == [] and inv == [], (mis, inv))

    # ---- NEGATIVE per rail -------------------------------------------------- #
    # 1. bounds from a count: actors present, no bounds -> UNKNOWN, never True.
    b = _clean_bundle()
    b["actor"] = {"a": {"path_name": "/A", "collection_ok": False}}
    rc_b = recompute_all(b, requested_map="/Game/Fixture/Lvl_Fixture")
    t("neg_bounds_unknown", rc_b["actor_bounds_valid"]["verdict"] is UNKNOWN,
      rc_b["actor_bounds_valid"])
    _m, _i = compare({"actor_bounds_valid": True}, rc_b, ("actor_bounds_valid",))
    t("neg_bounds_invented_flagged", len(_i) == 1 and _m == [], (_m, _i))

    # 2. negative extent -> min > max -> False (the shared derivation accepts it).
    b = _clean_bundle()
    b["actor"]["/Game/A.A:PersistentLevel.A_0"]["bounds_extent"] = [-1.0, 5.0, 5.0]
    v, why = bounds_valid(b["actor"]["/Game/A.A:PersistentLevel.A_0"])
    t("neg_negative_extent_rejected", v is False and "min > max" in why, why)

    # 2b. and the degenerate case the evidence model rejects must stay rejected.
    b["actor"]["/Game/A.A:PersistentLevel.A_0"]["bounds_extent"] = [0.0, 0.0, 0.0]
    v, why = bounds_valid(b["actor"]["/Game/A.A:PersistentLevel.A_0"])
    t("neg_degenerate_extent_rejected", v is False and "degenerate" in why, why)

    # 3. grounded must not be satisfiable by `accepted`.
    b = _clean_bundle()
    b["trace"]["marker_000::ground"]["hit"] = False
    b["marker"]["marker_000"]["grounded"] = False
    rc_g = recompute_all(b, requested_map="/Game/Fixture/Lvl_Fixture")
    t("neg_grounded_zero", rc_g["temporary_placements_grounded"]["verdict"] == 0,
      rc_g["temporary_placements_grounded"])
    _m, _i = compare({"temporary_placements_grounded": 1}, rc_g,
                     ("temporary_placements_grounded",))
    t("neg_grounded_mismatch_flagged", len(_m) == 1, (_m, _i))

    # 4. slope: a wall normal fails θ_max even with contact and full footprint.
    b = _clean_bundle()
    b["trace"]["marker_000::ground"]["impact_normal"] = [1.0, 0.0, 0.0]
    atoms = marker_atoms(b, b["marker"]["marker_000"])
    g, conj = grounded_verdict(atoms)
    t("neg_slope_rejects", g is False and conj["slope_within_theta_max"] is False, conj)

    # 5. Δz: a candidate floating far above its contact fails τ_z.
    b = _clean_bundle()
    b["marker"]["marker_000"]["location"] = [0.0, 0.0, 5000.0]
    b["marker"]["marker_000"]["ground_impact_z"] = 10.0
    atoms = marker_atoms(b, b["marker"]["marker_000"])
    g, conj = grounded_verdict(atoms)
    t("neg_delta_z_rejects", g is False and conj["ground_distance_within_tau_z"] is False,
      conj)

    # 6. a missing normal makes grounding UNKNOWN, not True.
    b = _clean_bundle()
    del b["trace"]["marker_000::ground"]["impact_normal"]
    atoms = marker_atoms(b, b["marker"]["marker_000"])
    g, _c = grounded_verdict(atoms)
    t("neg_missing_normal_unknown", g is UNKNOWN, g)

    # 7. overlap observed -> clearance is False, and the count rises.
    b = _clean_bundle()
    b["marker"]["marker_000"]["capsule_overlap_static_actor_paths"] = ["/Game/X"]
    b["marker"]["marker_000"]["overlap"] = True
    b["marker"]["marker_000"]["capsule_clear"] = False
    b["marker"]["marker_000"]["accepted"] = False
    rc_o = recompute_all(b, requested_map="/Game/Fixture/Lvl_Fixture")
    t("neg_overlap_counted", rc_o["overlap_count"]["verdict"] == 1, rc_o["overlap_count"])
    t("neg_clearance_false", rc_o["player_clearance_valid"]["verdict"] is False,
      rc_o["player_clearance_valid"])

    # 8. an uncollected overlap list makes clearance UNKNOWN, never True.
    b = _clean_bundle()
    b["marker"]["marker_000"]["capsule_overlap_dynamic_actor_paths"] = None
    b["marker"]["marker_000"]["overlap"] = None
    b["marker"]["marker_000"]["capsule_clear"] = None
    rc_u = recompute_all(b, requested_map="/Game/Fixture/Lvl_Fixture")
    t("neg_clearance_unknown", rc_u["player_clearance_valid"]["verdict"] is UNKNOWN,
      rc_u["player_clearance_valid"])
    _m, _i = compare({"player_clearance_valid": True}, rc_u, ("player_clearance_valid",))
    t("neg_clearance_invented_flagged", len(_i) == 1, (_m, _i))

    # 9. cleanup: each of the three conjuncts must be able to fail alone.
    for label, key, mutate in (
            ("actors", "actor_paths", ["/A", "/LEAKED"]),
            ("dirty", "dirty_packages", ["/Game/Maps/M"]),
            ("owned", "operation_owned_actor_paths", ["/Game/Temp_0"])):
        b = _clean_bundle()
        b["inventory"]["post"][key] = mutate
        cv = cleanup_verified(b)
        t("neg_cleanup_" + label, cv["sufficient"] and cv["verdict"] is False, cv)
    # ...and a residual operation-owned actor that is ALSO in the pre actor set is
    # invisible to the shared derivation but not to this one.
    b = _clean_bundle()
    b["inventory"]["pre"]["actor_paths"] = ["/A", "/Game/Temp_0"]
    b["inventory"]["post"]["actor_paths"] = ["/A", "/Game/Temp_0"]
    b["inventory"]["post"]["operation_owned_actor_paths"] = ["/Game/Temp_0"]
    cv = cleanup_verified(b)
    t("neg_cleanup_residual_owned_only", cv["verdict"] is False,
      "T conjunct must catch what M and D cannot: {}".format(cv))

    # 10. cleanup with a pre-cleanup post inventory is INSUFFICIENT, not False.
    b = _clean_bundle()
    b["inventory"]["post"]["stage"] = "observe"
    cv = cleanup_verified(b)
    t("neg_cleanup_stage_inversion", not cv["sufficient"] and cv["verdict"] is UNKNOWN, cv)

    # 11. cleanup literal True with no inventories at all -> invented.
    rc_n = recompute_all({"marker": {}, "actor": {}}, requested_map="/M")
    _m, _i = compare({"cleanup_verified": True}, rc_n, ("cleanup_verified",))
    t("neg_cleanup_literal_flagged", len(_i) == 1 and _m == [], (_m, _i))

    # 12. world identity: a different world is False; an unread one is UNKNOWN.
    b = _clean_bundle()
    b["world"]["observed"]["package_name"] = "/Game/Fixture/Lvl_Other"
    t("neg_world_mismatch",
      world_identity_ok(b, "/Game/Fixture/Lvl_Fixture")["verdict"] is False)
    b["world"]["observed"]["collection_ok"] = False
    t("neg_world_unread",
      world_identity_ok(b, "/Game/Fixture/Lvl_Fixture")["verdict"] is UNKNOWN)
    # ...and case/object-path forms of the SAME package still bind.
    b = _clean_bundle()
    b["world"]["observed"]["package_name"] = "/Game/Fixture/lvl_fixture.Lvl_Fixture"
    t("pos_world_canonical_forms_bind",
      world_identity_ok(b, "/Game/Fixture/Lvl_Fixture")["verdict"] is True)

    # 13. contradictory atoms: restatement disagrees with the atom.
    b = _clean_bundle()
    b["marker"]["marker_000"]["grounded"] = False       # atom says the trace hit
    c = marker_contradictions(b, b)
    t("neg_contradiction_detected", any("grounded" in x for x in c), c)
    b = _clean_bundle()
    b["marker"]["marker_000"]["capsule_clear"] = False  # not the negation of overlap
    c = marker_contradictions(b, b)
    t("neg_non_negation_detected", any("negations" in x for x in c), c)
    b = _clean_bundle()
    b["marker"]["marker_000"]["capsule_overlap_static_actor_paths"] = ["/X"]
    c = marker_contradictions(b, b)
    t("neg_accepted_exceeds_parts", any("accepted=True" in x for x in c), c)

    # 14. dangling refs.
    b = _clean_bundle()
    b["marker"]["marker_000"]["ground_trace_ref"] = "trace#nope"
    t("neg_dangling_ref_detected",
      any("unresolved" in x for x in dangling_refs(b)), dangling_refs(b))
    b = _clean_bundle()
    b["marker"]["marker_000"]["ground_trace_ref"] = "marker#marker_000"
    t("neg_wrong_kind_ref_detected",
      any("not a trace ref" in x for x in dangling_refs(b)), dangling_refs(b))

    # 15. duplicate record ids are invisible after json.loads — catch them at parse.
    obj, dups = parse_json_no_duplicates(
        '{"marker": {"m0": {"grounded": true}, "m0": {"grounded": false}}}')
    t("neg_duplicate_key_detected", dups == ["m0"], dups)
    t("neg_duplicate_key_last_wins_silently",
      obj["marker"]["m0"]["grounded"] is False,
      "json.loads keeps the last value; only the hook can see the first")
    _o, clean_dups = parse_json_no_duplicates('{"a": 1, "b": {"c": 2}}')
    t("pos_no_false_duplicate", clean_dups == [], clean_dups)

    # 15b. ISO parsing, including the forms the house actually emits.
    t("iso_z_form", parse_iso_epoch("2026-07-19T00:00:00Z") is not None)
    t("iso_offset_form", parse_iso_epoch("2026-07-19T20:17:01.803651+00:00") is not None)
    t("iso_naive_is_utc",
      parse_iso_epoch("2026-07-19T00:00:00") == parse_iso_epoch("2026-07-19T00:00:00Z"))
    t("iso_rejects_garbage", parse_iso_epoch("not a time") is None)
    t("iso_rejects_none", parse_iso_epoch(None) is None)
    t("iso_ordering",
      parse_iso_epoch("2026-07-19T00:00:00Z") < parse_iso_epoch("2026-07-27T00:00:00Z"))

    # 16. non-finite numerics anywhere in the document.
    t("neg_nonfinite_detected",
      nonfinite_numerics({"a": [1.0, float("nan")]}) == ["$.a[1]"],
      nonfinite_numerics({"a": [1.0, float("nan")]}))
    t("pos_finite_clean", nonfinite_numerics({"a": [1.0, 2.0]}) == [])

    # 17. forged provenance on a request-derived field.
    t("neg_forged_observed",
      len(forged_provenance({"subject_id": {"classification": OBSERVED}})) == 1)
    t("neg_forged_derived",
      len(forged_provenance({"subject_resolved_by": {"classification": DERIVED}})) == 1)
    t("pos_caller_supplied_ok",
      forged_provenance({"subject_id": {"classification": CALLER_SUPPLIED}}) == [])

    # 18. UNKNOWN must never be usable as a boolean.
    try:
        bool(UNKNOWN)
        t("neg_unknown_not_falsy", False, "bool(UNKNOWN) did not raise")
    except TypeError:
        pass

    # 18b. a boolean rail must not be satisfiable with the wrong type.
    _m, _i = compare({"actor_bounds_valid": 1}, rc, ("actor_bounds_valid",))
    t("neg_bool_rail_rejects_int_one", len(_m) == 1, (_m, _i))
    _m, _i = compare({"overlap_count": False}, rc, ("overlap_count",))
    t("neg_count_rail_rejects_false_for_zero", len(_m) == 1, (_m, _i))

    # 19. observability math, straight from the definition.
    t("math_S_requires_all_observed",
      observability([True, UNKNOWN])["sufficient"] is False)
    t("math_V_is_conjunction", observability([True, True])["verdict"] is True)
    t("math_V_false_on_any_false", observability([True, False])["verdict"] is False)
    t("math_empty_is_unknown", observability([])["verdict"] is UNKNOWN)
    t("math_count_needs_all_decided", counted([True, UNKNOWN])["verdict"] is UNKNOWN)
    t("math_count_counts", counted([True, False, True])["verdict"] == 2)

    # 20. package canonicalisation must agree with the assembler's, or say so.
    table = ["/Game/Maps/Foo", "/Game/Maps/Foo.Foo", "/Game/Maps/foo",
             "/Game/Maps/Foo/", "", None, "Foo"]
    try:
        import run_scene_survey_probe as PROBE
        mine = [norm_package(p) for p in table]
        theirs = [PROBE._norm_package(p) for p in table]
        t("assembler_norm_package_agrees", mine == theirs,
          "mine={} theirs={}".format(mine, theirs))
        mine_c = [canon_package(p) for p in table]
        theirs_c = [PROBE._canon_package(p) for p in table]
        t("assembler_canon_package_agrees", mine_c == theirs_c,
          "mine={} theirs={}".format(mine_c, theirs_c))
    except Exception as exc:  # noqa: BLE001
        print("[recompute] NOTE — assembler cross-check skipped: {}: {}".format(
            type(exc).__name__, exc))

    # 21. the shared ref resolver and mine must agree (the one shared-ish helper).
    try:
        import scene_survey_evidence as SE
        b = _clean_bundle()
        probes = ["trace#marker_000::ground", "trace#nope", "notaref", None,
                  "marker#marker_000"]
        t("shared_resolve_raw_agrees",
          [resolve_ref(b, r) for r in probes] == [SE.resolve_raw(b, r) for r in probes])
    except Exception as exc:  # noqa: BLE001
        print("[recompute] NOTE — evidence resolver cross-check skipped: {}".format(exc))

    # 22. ACCEPTANCE ELIGIBILITY — six terms, each driven both ways.
    _acceptance_dogfood(t)

    for line in failures:
        print("FAIL {}".format(line))
    print("SCENE-SURVEY RECOMPUTE SELF-DOGFOOD: {} ({} negative(s) + positives)".format(
        "PASS" if not failures else "FAIL", 22))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(_main())
