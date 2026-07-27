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

  * every ``derive_*`` / ``sufficiency_*`` in ``DERIVATIONS`` (evidence.py:608-618)
  * ``derive()``, ``rederive_and_compare()``, ``derived_record()``
  * ``validate_scene_survey_report()`` field verdicts
  * ``evaluate_acceptance_eligibility()``
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
)


def recompute_all(raw, requested_map=None, bundle=None, **taus):
    """Every recomputable aggregate, from raw only. No report is consulted."""
    bundle = bundle if bundle is not None else raw
    mk = marker_verdicts(bundle, raw, **taus)
    out = {
        "schema_version": SCHEMA_VERSION,
        "actor_bounds_valid": actor_bounds_valid(raw),
        "temporary_placements_grounded": mk["temporary_placements_grounded"],
        "overlap_count": mk["overlap_count"],
        "player_clearance_valid": mk["player_clearance_valid"],
        "cleanup_verified": cleanup_verified(raw),
        "world_identity_ok": world_identity_ok(raw, requested_map),
        "_markers": mk,
        "_contradictions": marker_contradictions(bundle, raw),
        "_dangling_refs": dangling_refs(bundle),
    }
    return out


def compare(reported, recomputed, fields=COMPARED_FIELDS):
    """``(mismatches, unknown_presented_as_decided)`` for the compared fields.

    Two distinct failure kinds, deliberately not merged:

      * MISMATCH — the raw was sufficient and re-derives to a different value.
        The report does not follow from its own evidence.
      * UNKNOWN-AS-DECIDED — the raw was NOT sufficient, and the report presented
        a decided value anyway. Nothing is being contradicted; something is being
        invented. Collapsing this into "mismatch" would let it be read as a
        rounding disagreement.
    """
    reported = reported if isinstance(reported, dict) else {}
    mismatches, invented = [], []
    for field in fields:
        got = recomputed.get(field) or {}
        claimed = reported.get(field)
        verdict = got.get("verdict", UNKNOWN)
        if not got.get("sufficient"):
            if claimed is not None:
                invented.append(
                    "{}: report states {!r} but the raw evidence is insufficient "
                    "to decide it ({})".format(field, claimed,
                                               got.get("detail") or got))
            continue
        if verdict is UNKNOWN:
            if claimed is not None:
                invented.append("{}: report states {!r}; re-derivation is UNKNOWN"
                                .format(field, claimed))
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

    for line in failures:
        print("FAIL {}".format(line))
    print("SCENE-SURVEY RECOMPUTE SELF-DOGFOOD: {} ({} negative(s) + positives)".format(
        "PASS" if not failures else "FAIL", 21))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(_main())
