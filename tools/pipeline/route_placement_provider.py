#!/usr/bin/env python3
"""route_placement_provider -- turn a bounded plan step into CONCRETE mutations.

THE GAP THIS FILLS
------------------
``wfcore.providers`` says of itself: *"This lane declares and ranks capability.
It executes nothing."* That is true and correct -- and it means a plan step,
which declares ``mutation_kinds``, a bound, a rollback mode and a postcondition,
never says WHAT TO PLACE OR WHERE. The transaction sink wants
``{operation_id, bounds, mutations, evidence_refs}`` with real target paths and
real transforms. Nothing produced them, so the sink had nothing to run and the
loop stayed open at the compile->materialize seam.

This module is the smallest honest generator that closes that seam: given
anchors that were OBSERVED, a planar bound, and a count, it computes evenly
spaced placements along the path through those anchors and emits a validated
transaction request.

WHAT IT REFUSES TO DO, AND WHY THAT IS THE POINT
------------------------------------------------
It will not invent an anchor. Anchor locations arrive as MEASURED input or the
plan is refused (``WF1292``). The alternative -- defaulting to an origin, a
bounding-box centre, or any other plausible coordinate -- is the exact failure
this platform exists to prevent: the capability layer choosing a subject, then
producing flawless evidence about a place nobody asked for. A refusal naming the
missing anchor is worth more than a placement nobody requested.

It also does not decide how many markers a route deserves, what they mean, or
whether they look right. Those are the caller's. This module owns spacing,
containment and reproducibility -- mechanical properties with mechanical proofs.

SPATIAL CONTAINMENT IS PROVED, NOT ASSUMED
------------------------------------------
Every emitted placement carries a containment result computed from COORDINATES:
the point is tested against the resolved planar extent. This is deliberate and
it is the one thing here worth reading twice. The transaction layer's
``classify_target`` decides in-bound by exact string containment over path
lists -- which is the right check for "may this provider touch this asset" and
is NOT a statement about geometry. A generator that emitted a transform two
kilometres outside the requested region would pass that check cleanly, because
the path it wrote to was on the allowed list. Path authority and spatial extent
are different claims; conflating them lets a bound look enforced while the world
says otherwise.

DETERMINISM IS ARITHMETIC, NOT A SEED
-------------------------------------
There is no RNG here at all. Output is a pure function of (anchors, count,
bound, exclusions, spacing policy), so the same request yields byte-identical
placements on any machine, in any order, forever. The declaration claims
``deterministic_given_seed`` because that is the strongest term the vocabulary
offers, and ``determinism_evidence`` points at the suite that re-runs the
planner and compares serialised output rather than trusting the claim.

House style: stdlib only; ``validate_X(...) -> List[Check]`` where
``Check = (check_name, ok, detail, failure_code)``.
"""

import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.failure import FailureCode as C     # noqa: E402
from wfcore.providers import base as PB         # noqa: E402
from wfcore.transaction import delta as TD      # noqa: E402

PROVIDER_ID = "route_placement_planner"
RT_PLACEMENT_PLAN = "wf.core.route_placement_plan.v1"

_P = "route_placement."

# Placement geometry is rounded to this many decimals on every path that
# produces a coordinate. Determinism across machines is worth more than the
# sub-micron precision being discarded, and an unrounded float is exactly how
# two "identical" runs come to differ in their last bit.
_COORD_DECIMALS = 3

# How far a placement may be slid along the route to escape an exclusion before
# the plan is refused outright. A bounded mechanical adjustment is repair; an
# unbounded one is the generator quietly relocating the caller's intent.
DEFAULT_MAX_SLIDE_CM = 400.0
_SLIDE_STEP_CM = 25.0


# --------------------------------------------------------------------------- #
# small geometry -- pure, no engine, no dependencies
# --------------------------------------------------------------------------- #
def _r(v):
    return round(float(v) + 0.0, _COORD_DECIMALS)


def _is_xyz(p):
    return (isinstance(p, (list, tuple)) and len(p) == 3
            and all(isinstance(c, (int, float)) and not isinstance(c, bool)
                    and math.isfinite(c) for c in p))


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def polyline_length(points):
    return sum(_dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def point_at_arclength(points, s):
    """The point ``s`` centimetres along the polyline. Clamped at both ends."""
    if s <= 0:
        return [_r(c) for c in points[0]]
    total = 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = _dist(a, b)
        if seg <= 0:
            continue
        if total + seg >= s:
            t = (s - total) / seg
            return [_r(a[k] + (b[k] - a[k]) * t) for k in range(3)]
        total += seg
    return [_r(c) for c in points[-1]]


def within_planar_bound(point, bound):
    """(inside, detail). Coordinate math -- never a path-string comparison."""
    ox = float(bound["origin_x_cm"])
    oy = float(bound["origin_y_cm"])
    ex = float(bound["extent_x_cm"])
    ey = float(bound["extent_y_cm"])
    half_x, half_y = ex / 2.0, ey / 2.0
    dx, dy = point[0] - ox, point[1] - oy
    inside = abs(dx) <= half_x and abs(dy) <= half_y
    return inside, ("|dx|={:.1f} vs half_extent_x={:.1f}; |dy|={:.1f} vs "
                    "half_extent_y={:.1f}".format(abs(dx), half_x,
                                                  abs(dy), half_y))


def _in_exclusion(point, exclusions):
    for ex in exclusions or []:
        c = ex.get("center_cm")
        r = ex.get("radius_cm")
        if not (_is_xyz(c) and isinstance(r, (int, float))):
            continue
        if _dist(point, c) <= float(r):
            return ex
    return None


# --------------------------------------------------------------------------- #
# the planner
# --------------------------------------------------------------------------- #
def plan_route_placements(anchors, count, bound, exclusions=None,
                          max_slide_cm=DEFAULT_MAX_SLIDE_CM):
    """Deterministic placements along the route through ``anchors``.

    ``anchors`` is an ordered list of ``{"anchor_id": str, "location_cm":
    [x,y,z]}`` whose locations were OBSERVED. A missing or non-finite location
    refuses the plan rather than defaulting: see the module docstring.

    Returns a ``wf.core.route_placement_plan.v1`` record. It always returns a
    record -- refusal is a result with a reason, never an exception and never an
    empty list that a caller could mistake for "nothing needed placing".
    """
    exclusions = list(exclusions or [])
    plan = {
        "schema_version": RT_PLACEMENT_PLAN,
        "report_type": RT_PLACEMENT_PLAN,
        "provider_id": PROVIDER_ID,
        "requested_count": count,
        "anchor_ids": [a.get("anchor_id") for a in (anchors or [])],
        "route_length_cm": None,
        "placements": [],
        "refused": False,
        "refusal_reason": None,
        "failure_codes": [],
    }

    def refuse(reason, code):
        plan["refused"] = True
        plan["refusal_reason"] = reason
        plan["placements"] = []
        if code not in plan["failure_codes"]:
            plan["failure_codes"].append(code)
        return plan

    if not isinstance(anchors, list) or len(anchors) < 2:
        return refuse(
            "a route needs at least two anchors; got {}. WorldForge will not "
            "synthesise a second one".format(
                len(anchors) if isinstance(anchors, list) else anchors),
            C.CORE_PLACEMENT_ANCHOR_UNOBSERVED)

    pts = []
    for a in anchors:
        loc = a.get("location_cm") if isinstance(a, dict) else None
        if not _is_xyz(loc):
            return refuse(
                "anchor {!r} has no observed location (got {!r}). An anchor "
                "WorldForge did not measure is not an anchor it may invent: "
                "supply an observation or accept the refusal".format(
                    (a or {}).get("anchor_id"), loc),
                C.CORE_PLACEMENT_ANCHOR_UNOBSERVED)
        pts.append([float(c) for c in loc])

    if not isinstance(count, int) or count < 1:
        return refuse("count must be a positive integer; got {!r}".format(count),
                      C.CORE_PLACEMENT_PLAN_INVALID)

    for fld in ("origin_x_cm", "origin_y_cm", "extent_x_cm", "extent_y_cm"):
        v = (bound or {}).get(fld)
        if not (isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v)):
            return refuse(
                "planar bound field {!r} must be a finite number; got {!r}. An "
                "unresolved extent cannot be tested against, and a containment "
                "claim nobody could evaluate is worse than none".format(fld, v),
                C.CORE_PLACEMENT_PLAN_INVALID)
    if float(bound["extent_x_cm"]) <= 0 or float(bound["extent_y_cm"]) <= 0:
        return refuse("planar bound extents must be positive",
                      C.CORE_PLACEMENT_PLAN_INVALID)

    length = polyline_length(pts)
    plan["route_length_cm"] = _r(length)
    if length <= 0:
        return refuse(
            "the anchors are coincident, so the route has zero length and "
            "'evenly spaced along it' has no meaning",
            C.CORE_PLACEMENT_PLAN_INVALID)

    # Interior spacing: N markers at i/(N+1) of the route. The endpoints are the
    # caller's own landmarks -- placing a marker on top of one would be marking
    # the thing the player can already see.
    for i in range(1, count + 1):
        nominal_s = length * (float(i) / float(count + 1))
        point = point_at_arclength(pts, nominal_s)
        slid = 0.0
        hit = _in_exclusion(point, exclusions)
        blocking = hit

        # Bounded, deterministic escape: forward first, then backward, in fixed
        # steps. Direction order is fixed so two runs cannot disagree.
        while blocking is not None and slid < max_slide_cm:
            slid += _SLIDE_STEP_CM
            for signed in (nominal_s + slid, nominal_s - slid):
                if signed < 0 or signed > length:
                    continue
                cand = point_at_arclength(pts, signed)
                if _in_exclusion(cand, exclusions) is None:
                    point, blocking = cand, None
                    break

        if blocking is not None:
            return refuse(
                "placement {} of {} falls inside exclusion {!r} and could not "
                "be moved clear within {}cm along the route. Widening that "
                "budget is a decision about the caller's world, not a detail "
                "this planner may settle".format(
                    i, count, blocking.get("exclusion_id"), max_slide_cm),
                C.CORE_PLACEMENT_EXCLUSION_UNSATISFIABLE)

        inside, detail = within_planar_bound(point, bound)
        if not inside:
            return refuse(
                "placement {} of {} resolves to {} which lies OUTSIDE the "
                "declared planar extent ({}). Path-list containment would not "
                "have caught this: the asset path is permitted, the location is "
                "not".format(i, count, point, detail),
                C.CORE_PLACEMENT_OUT_OF_BOUNDS)

        plan["placements"].append({
            "index": i,
            "nominal_arclength_cm": _r(nominal_s),
            "slid_cm": _r(slid),
            "location_cm": point,
            "rotation_pyr": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "containment": {
                "tested_against": "resolved_planar_extent",
                "method": "coordinate_comparison",
                "inside": True,
                "detail": detail,
            },
        })

    return plan


# --------------------------------------------------------------------------- #
# the transaction request
# --------------------------------------------------------------------------- #
def build_transaction_request(plan, operation_id, step_id, target_package,
                              actor_prefix, actor_class=None,
                              static_mesh=None, material=None,
                              evidence_refs=None):
    """Turn an accepted placement plan into the sink's request shape.

    ``actor_class`` is REQUIRED and has no default. WorldForge decides WHERE
    things go; WHAT goes there is the caller's -- it comes from the approved
    catalog the caller declared. A default here would look like a convenience
    and would in fact be the capability layer choosing the game's content, which
    is the one thing this architecture exists to prevent. Absent, the request is
    refused rather than filled in.

    Refuses to build anything from a refused plan. A transaction request derived
    from a refusal would be a mutation list nobody's plan authorised.
    """
    if plan.get("refused"):
        return None, ["plan was refused ({}); no transaction request is "
                      "derivable from it".format(plan.get("refusal_reason"))]

    if not (isinstance(actor_class, str) and actor_class.strip()):
        return None, ["actor_class is required and has no default: WorldForge "
                      "places things, it does not choose what to place. Supply "
                      "the class from the caller's approved catalog"]

    errors = []
    if not plan.get("placements"):
        errors.append("plan contains no placements; there is nothing to run")

    # ``<map_package>:<actor_label>`` -- the sink's address grammar, exactly one
    # colon (``run_wfcore_transaction.parse_actor_address``). This was originally
    # written with a slash, which every schema validator accepted and the sink
    # rejected at request-validation time: the delta validators check the shape
    # of a mutation record, not the grammar of an address inside it. Generating
    # an address the executor cannot parse is not a schema question.
    actors = ["{}:{}_{:03d}".format(target_package.rstrip("/"),
                                    actor_prefix, p["index"])
              for p in plan.get("placements", [])]

    bound = {
        "step_id": step_id,
        "allowed_packages": [target_package],
        "allowed_actors": list(actors),
        "schema_version": TD.RT_MUTATION_BOUND,
    }

    mutations = []
    for p, path in zip(plan.get("placements", []), actors):
        mutations.append({
            "mutation_id": "mut_{}_{:03d}".format(actor_prefix, p["index"]),
            "step_id": step_id,
            "provider_id": PROVIDER_ID,
            "target_kind": TD.TARGET_ACTOR,
            "target_path": path,
            "operation": TD.OP_CREATE,
            # The actor does not exist yet, and that is a MEASURED expectation
            # about this specific path rather than an assumption: a create whose
            # before_state was 'present' would be an overwrite wearing a
            # creation's name.
            "before_state": TD.absent_state(),
            "status": TD.MUT_PLANNED,
            "rollback_mode": PB.ROLLBACK_COMPENSATING,
            "schema_version": TD.RT_MUTATION,
            # The sink's OWN payload grammar (actor_class + finite
            # location/rotation/scale). Originally written with this module's
            # internal key names, which every schema validator accepted and the
            # editor rejected at apply time with WF1278. Found by running it.
            "expected_after_state": TD.present_state(dict(
                {"actor_class": actor_class,
                 "location": list(p["location_cm"]),
                 "rotation": list(p["rotation_pyr"]),
                 "scale": list(p["scale"])},
                # Omitted entirely when the caller named no mesh, so the payload
                # keeps the shape every existing comparison expects. Supplied,
                # it is what turns a zero-extent shell into geometry the scene
                # survey can actually measure.
                **({"static_mesh": static_mesh} if static_mesh else {}),
                **({"material": material} if material else {}))),
            "detail": "route placement {} of {} at {} (slid {}cm to clear an "
                      "exclusion)".format(p["index"], len(actors),
                                          p["location_cm"], p["slid_cm"]),
        })

    request = {
        "operation_id": operation_id,
        "bounds": [bound],
        "mutations": mutations,
        "evidence_refs": list(evidence_refs or ["route_placement_plan"]),
    }
    return request, errors


# --------------------------------------------------------------------------- #
# the provider declaration
# --------------------------------------------------------------------------- #
def declaration():
    """``wf.core.provider_declaration.v1`` for this planner."""
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_ID,
        capabilities=[PB.CAP_PROCEDURAL_SCATTER],
        requirements=[],
        side_effects=[PB._example_side_effect(
            effect_id="eff_placement_plan_only",
            effect_kind=PB.EFFECT_EVIDENCE_ONLY,
            scope="evidence.placement_plan",
            reversible=True,
            detail="computes placements and emits a plan document; it writes "
                   "nothing into the world. Materialisation is a separate "
                   "provider with its own bound and its own rollback")],
        determinism=PB.DET_SEEDED,
        rollback=PB.ROLLBACK_NONE,   # nothing was changed; nothing to undo
        outputs=["placement_plan", "transaction_request"],
        evidence=["route_placement_plan"],
        limitations=[
            PB._example_limitation(
                limitation_id="lim_requires_observed_anchors",
                limitation_kind="input_shape",
                detail="anchor locations must be supplied as measurements. "
                       "This planner refuses rather than defaulting, so it "
                       "cannot be used before an observation pass exists"),
            PB._example_limitation(
                limitation_id="lim_planar_containment_only",
                limitation_kind="coverage_unknown",
                detail="containment is tested against a planar extent in X/Y. "
                       "Vertical placement is carried through from the anchors "
                       "and is NOT independently validated against terrain"),
        ],
        description="evenly spaced placements along the route through observed "
                    "anchors, with coordinate-proved containment",
    )
    # A list of strings, not a prose blob: the rail accepts either, and a list
    # forces each claim to stand as its own sentence somebody can go and check.
    d["determinism_evidence"] = [
        "no RNG: output is a pure function of (anchors, count, bound, "
        "exclusions, slide policy) -- there is no random import in this module",
        "every emitted coordinate is rounded to {} decimals, so two runs cannot "
        "differ in a trailing bit".format(_COORD_DECIMALS),
        "pipeline/test_route_placement_provider.py re-runs the planner and "
        "compares canonical JSON byte-for-byte",
        "the same suite re-runs it with inputs rebuilt from scratch, so an "
        "accidental dependence on object identity or input mutation would show",
    ]
    return d


def validate_placement_plan(plan, strict=False):
    """Rails over a produced plan. Cheap to run, and it catches a lying plan."""
    code = C.CORE_PLACEMENT_PLAN_INVALID
    out = []
    is_obj = isinstance(plan, dict)
    out.append((_P + "plan_is_object", is_obj,
                "plan must be an object (got {})".format(type(plan).__name__),
                None if is_obj else code))
    if not is_obj:
        return out

    sv = plan.get("schema_version")
    out.append((_P + "schema_version", sv == RT_PLACEMENT_PLAN,
                "schema_version must be {!r} (got {!r})".format(
                    RT_PLACEMENT_PLAN, sv),
                None if sv == RT_PLACEMENT_PLAN else code))

    refused = bool(plan.get("refused"))
    placements = plan.get("placements") or []

    # A refusal that still carries placements is the dangerous shape: a reader
    # taking the list and ignoring the flag would materialise a plan that was
    # never accepted.
    out.append((_P + "refusal_carries_no_placements",
                not (refused and placements),
                "a refused plan must carry ZERO placements; this one is refused "
                "({!r}) and carries {}".format(
                    plan.get("refusal_reason"), len(placements)),
                None if not (refused and placements) else code))
    out.append((_P + "refusal_names_a_code",
                not refused or bool(plan.get("failure_codes")),
                "a refused plan must name at least one failure code; a refusal "
                "with no code cannot be routed to anyone",
                None if (not refused or plan.get("failure_codes")) else code))

    if refused:
        return out

    want = plan.get("requested_count")
    got = len(placements)
    out.append((_P + "count_matches_request", want == got,
                "an accepted plan must contain exactly the requested count "
                "({} asked, {} produced). Silently producing fewer would "
                "satisfy a budget constraint while under-serving the "
                "request".format(want, got),
                None if want == got else code))

    for p in placements:
        ok = _is_xyz(p.get("location_cm"))
        out.append((_P + "placement_{}_location_finite".format(p.get("index")),
                    ok, "every placement needs a finite xyz (got {!r})".format(
                        p.get("location_cm")), None if ok else code))
        cont = p.get("containment") or {}
        proved = (cont.get("inside") is True
                  and cont.get("method") == "coordinate_comparison")
        out.append((_P + "placement_{}_containment_proved".format(p.get("index")),
                    proved,
                    "every accepted placement must carry a containment result "
                    "computed from COORDINATES, not inherited from path-list "
                    "membership (got {!r})".format(cont),
                    None if proved else C.CORE_PLACEMENT_OUT_OF_BOUNDS))
    return out


def canonical(plan):
    """Stable serialisation, for determinism comparison."""
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))
