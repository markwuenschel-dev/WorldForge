#!/usr/bin/env python3
"""poi_distribution_provider -- points of interest spread over a region.

WHY THIS IS NOT THE ROUTE PLANNER WITH A DIFFERENT LABEL
---------------------------------------------------------
It would be easy to add a "category" that is the existing placement mechanism
wearing a new name, and it would pad a coverage count without proving anything.
This is genuinely different work: a route interpolates along a line between two
measured anchors, and a POI field DISTRIBUTES over a two-dimensional region under
a minimum-separation constraint. Different inputs, different geometry, different
failure modes -- a route can always fit N markers on a long enough line, whereas
a region can be too small or too crowded to hold what was asked for, and that has
to be refused rather than fudged.

DETERMINISTIC WITHOUT A SEED, AND WITHOUT AN RNG
------------------------------------------------
Scatter usually reaches for a seeded random generator, which then has to be
threaded, stored and trusted. A Halton sequence needs none of that: the i-th
point is a pure function of i, so the hundredth POI is the same on any machine,
in any order, with no state to carry and nothing to get out of step. Determinism
here is a property of the arithmetic rather than a promise about bookkeeping.

WHAT REMAINS THE CALLER'S
-------------------------
What a POI IS -- its kind, what actor represents it, how far apart they must
stand, how many there should be. This module owns only where they land and the
proof that each one is inside the declared region. A default POI kind or an
invented separation would be WorldForge deciding what the game's world contains.
"""

import argparse
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import route_placement_provider as RP    # noqa: E402
from wfcore.failure import FailureCode as C            # noqa: E402
from wfcore.providers import base as PB                # noqa: E402
from wfcore.transaction import delta as TD             # noqa: E402

PROVIDER_ID = "poi_distribution_planner"
RT_POI_PLAN = "wf.core.poi_distribution_plan.v1"

_P = "poi_distribution."
_COORD_DECIMALS = 3

# How many sequence positions may be examined per accepted point before the
# region is declared too crowded. A bound, not a timeout: an unbounded search
# would spin on an impossible request instead of reporting one.
_CANDIDATES_PER_POINT = 400


def _halton(index, base):
    """The index-th value of the Halton sequence in [0,1). Pure arithmetic."""
    f, result, i = 1.0, 0.0, index + 1
    while i > 0:
        f /= base
        result += f * (i % base)
        i //= base
    return result


def _r(v):
    return round(float(v) + 0.0, _COORD_DECIMALS)


def plan_poi_field(kinds, count, bound, min_separation_cm, z_cm=0.0,
                   exclusions=None):
    """Distribute ``count`` POIs over ``bound``, honouring separation.

    ``kinds`` is the caller's list of POI kinds, cycled in declaration order so
    the mix is the caller's and the assignment is reproducible. Refusal is a
    result with a reason.
    """
    plan = {"schema_version": RT_POI_PLAN, "report_type": RT_POI_PLAN,
            "provider_id": PROVIDER_ID, "requested_count": count,
            "kinds": list(kinds or []), "min_separation_cm": min_separation_cm,
            "pois": [], "refused": False, "refusal_reason": None,
            "failure_codes": []}

    def refuse(reason, code):
        plan.update({"refused": True, "refusal_reason": reason, "pois": []})
        if code not in plan["failure_codes"]:
            plan["failure_codes"].append(code)
        return plan

    if not kinds:
        return refuse("no POI kinds declared; WorldForge will not invent what a "
                      "point of interest is in this game",
                      C.CORE_PLACEMENT_PLAN_INVALID)
    if not isinstance(count, int) or count < 1:
        return refuse("count must be a positive integer (got {!r})".format(count),
                      C.CORE_PLACEMENT_PLAN_INVALID)
    for fld in ("origin_x_cm", "origin_y_cm", "extent_x_cm", "extent_y_cm"):
        v = (bound or {}).get(fld)
        if not (isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v)):
            return refuse("planar bound field {!r} must be finite (got {!r})"
                          .format(fld, v), C.CORE_PLACEMENT_PLAN_INVALID)
    if float(bound["extent_x_cm"]) <= 0 or float(bound["extent_y_cm"]) <= 0:
        return refuse("planar bound extents must be positive",
                      C.CORE_PLACEMENT_PLAN_INVALID)
    if not (isinstance(min_separation_cm, (int, float))
            and min_separation_cm >= 0):
        return refuse("min_separation_cm must be a non-negative number (got {!r})"
                      .format(min_separation_cm), C.CORE_PLACEMENT_PLAN_INVALID)

    ox, oy = float(bound["origin_x_cm"]), float(bound["origin_y_cm"])
    ex, ey = float(bound["extent_x_cm"]), float(bound["extent_y_cm"])
    sep = float(min_separation_cm)
    accepted, i, examined = [], 0, 0

    while len(accepted) < count:
        if examined >= count * _CANDIDATES_PER_POINT:
            return refuse(
                "placed {} of {} POI(s) before exhausting {} candidate positions. "
                "The region is too small or too crowded for {} points at {}cm "
                "separation -- widen the extent, lower the count, or reduce the "
                "separation. Packing them closer than asked would silently "
                "violate the constraint that was stated".format(
                    len(accepted), count, examined, count, sep),
                C.CORE_PLACEMENT_EXCLUSION_UNSATISFIABLE)
        x = ox + (_halton(i, 2) - 0.5) * ex
        y = oy + (_halton(i, 3) - 0.5) * ey
        i += 1
        examined += 1
        pt = [_r(x), _r(y), _r(z_cm)]

        if RP._in_exclusion(pt, exclusions) is not None:
            continue
        if sep > 0 and any(
                math.hypot(pt[0] - p["location_cm"][0],
                           pt[1] - p["location_cm"][1]) < sep
                for p in accepted):
            continue

        inside, detail = RP.within_planar_bound(pt, bound)
        if not inside:
            # Should be unreachable given how x/y are derived, so it is an
            # assertion about the derivation rather than an expected branch.
            return refuse(
                "derived POI {} fell outside the region it was derived from "
                "({}); the distribution math disagrees with the containment "
                "test and one of them is wrong".format(pt, detail),
                C.CORE_PLACEMENT_OUT_OF_BOUNDS)

        accepted.append({
            "index": len(accepted) + 1,
            "poi_kind": kinds[len(accepted) % len(kinds)],
            "location_cm": pt,
            "rotation_pyr": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "sequence_index": i - 1,
            "containment": {"tested_against": "resolved_planar_extent",
                            "method": "coordinate_comparison",
                            "inside": True, "detail": detail},
        })

    plan["candidates_examined"] = examined
    plan["pois"] = accepted
    return plan


def build_transaction_request(plan, operation_id, step_id, target_package,
                              actor_class=None, static_mesh=None,
                              actor_prefix="wfpoi", evidence_refs=None):
    """The same request shape every other provider emits."""
    if plan.get("refused"):
        return None, ["POI plan was refused ({})".format(
            plan.get("refusal_reason"))]
    if not (isinstance(actor_class, str) and actor_class.strip()):
        return None, ["actor_class is required and has no default: what "
                      "represents a POI in this game is the game's decision"]

    actors, muts = [], []
    for p in plan.get("pois", []):
        path = "{}:{}_{}_{:03d}".format(target_package.rstrip("/"), actor_prefix,
                                        p["poi_kind"], p["index"])
        actors.append(path)
        payload = {"actor_class": actor_class,
                   "location": list(p["location_cm"]),
                   "rotation": list(p["rotation_pyr"]),
                   "scale": list(p["scale"])}
        if static_mesh:
            payload["static_mesh"] = static_mesh
        muts.append({
            "mutation_id": "mut_{}_{:03d}".format(actor_prefix, p["index"]),
            "step_id": step_id, "provider_id": PROVIDER_ID,
            "target_kind": TD.TARGET_ACTOR, "target_path": path,
            "operation": TD.OP_CREATE, "before_state": TD.absent_state(),
            "status": TD.MUT_PLANNED,
            "rollback_mode": PB.ROLLBACK_COMPENSATING,
            "schema_version": TD.RT_MUTATION,
            "expected_after_state": TD.present_state(payload),
            "detail": "POI {} of kind {!r}".format(p["index"], p["poi_kind"]),
        })

    bound = {"step_id": step_id, "allowed_packages": [target_package],
             "allowed_actors": sorted(actors),
             "schema_version": TD.RT_MUTATION_BOUND}
    return {"operation_id": operation_id, "bounds": [bound], "mutations": muts,
            "evidence_refs": list(evidence_refs or ["poi_distribution_plan"])}, []


def validate_poi_plan(plan, strict=False):
    code = C.CORE_PLACEMENT_PLAN_INVALID
    out = []
    is_obj = isinstance(plan, dict)
    out.append((_P + "plan_is_object", is_obj, "plan must be an object",
                None if is_obj else code))
    if not is_obj:
        return out

    refused = bool(plan.get("refused"))
    pois = plan.get("pois") or []
    out.append((_P + "refusal_carries_no_pois", not (refused and pois),
                "a refused plan must carry zero POIs",
                None if not (refused and pois) else code))
    if refused:
        out.append((_P + "refusal_names_a_code", bool(plan.get("failure_codes")),
                    "a refusal must name a code",
                    None if plan.get("failure_codes") else code))
        return out

    want, got = plan.get("requested_count"), len(pois)
    out.append((_P + "count_matches_request", want == got,
                "{} POI(s) asked for, {} produced. Producing fewer silently "
                "would satisfy a budget while under-serving the request".format(
                    want, got), None if want == got else code))

    sep = plan.get("min_separation_cm") or 0
    worst = None
    for a in range(len(pois)):
        for b in range(a + 1, len(pois)):
            d = math.hypot(
                pois[a]["location_cm"][0] - pois[b]["location_cm"][0],
                pois[a]["location_cm"][1] - pois[b]["location_cm"][1])
            worst = d if worst is None else min(worst, d)
    ok = worst is None or sep <= 0 or worst >= sep - 1e-6
    out.append((_P + "separation_actually_holds", ok,
                "closest pair is {}cm apart against a declared minimum of {}cm. "
                "This is re-measured from the emitted coordinates rather than "
                "trusted from the algorithm that produced them".format(
                    None if worst is None else round(worst, 2), sep),
                None if ok else code))

    for p in pois:
        cont = p.get("containment") or {}
        proved = (cont.get("inside") is True
                  and cont.get("method") == "coordinate_comparison")
        out.append((_P + "poi_{}_containment_proved".format(p.get("index")),
                    proved, "each POI needs a coordinate-computed containment "
                            "result (got {!r})".format(cont),
                    None if proved else C.CORE_PLACEMENT_OUT_OF_BOUNDS))
    return out


def declaration():
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_ID,
        capabilities=[PB.CAP_PROCEDURAL_SCATTER],
        requirements=[],
        side_effects=[PB._example_side_effect(
            effect_id="eff_poi_plan_only",
            effect_kind=PB.EFFECT_EVIDENCE_ONLY,
            scope="evidence.poi_distribution_plan",
            reversible=True,
            detail="computes a distribution and emits a plan; writes nothing")],
        determinism=PB.DET_SEEDED,
        rollback=PB.ROLLBACK_NONE,
        outputs=["poi_distribution_plan", "transaction_request"],
        evidence=["poi_distribution_plan"],
        limitations=[
            PB._example_limitation(
                limitation_id="lim_planar_distribution",
                limitation_kind="coverage_unknown",
                detail="distributes in X/Y at a single declared Z. It does not "
                       "conform POIs to terrain, because nothing here has "
                       "measured the ground"),
            PB._example_limitation(
                limitation_id="lim_separation_is_best_effort_then_refuses",
                limitation_kind="scale",
                detail="a region too crowded for the requested count at the "
                       "requested separation is refused, never packed tighter"),
        ],
        description="deterministic Halton distribution of caller-declared POI "
                    "kinds over a bounded region")
    d["determinism_evidence"] = [
        "no RNG and no seed state: the i-th point is a pure function of i via "
        "Halton bases 2 and 3",
        "coordinates rounded to {} decimals so two runs cannot differ in a "
        "trailing bit".format(_COORD_DECIMALS),
        "pipeline/test_poi_distribution_provider.py re-plans and compares "
        "canonical JSON",
    ]
    return d


def canonical(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kinds", required=True, help="comma-separated POI kinds")
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--extent-cm", type=float, required=True)
    ap.add_argument("--separation-cm", type=float, required=True)
    ap.add_argument("--z-cm", type=float, default=0.0)
    ap.add_argument("--map", required=True)
    ap.add_argument("--actor-class", required=True)
    ap.add_argument("--static-mesh")
    ap.add_argument("--operation-id", default="op_poi")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    bound = {"origin_x_cm": 0.0, "origin_y_cm": 0.0,
             "extent_x_cm": args.extent_cm, "extent_y_cm": args.extent_cm}
    plan = plan_poi_field([k.strip() for k in args.kinds.split(",") if k.strip()],
                          args.count, bound, args.separation_cm, z_cm=args.z_cm)
    bad = [c[0] for c in validate_poi_plan(plan, strict=True) if not c[1]]
    print("poi distribution -- {} kind(s)".format(len(plan["kinds"])))
    print("  refused : {}".format(plan["refused"]))
    if plan["refused"]:
        print("  reason  : {}".format(plan["refusal_reason"][:220])); return 1
    print("  placed  : {} (examined {} candidates)".format(
        len(plan["pois"]), plan.get("candidates_examined")))
    print("  validator: {}".format(bad or "clean"))
    req, errs = build_transaction_request(
        plan, args.operation_id, "step_poi", args.map,
        actor_class=args.actor_class, static_mesh=args.static_mesh)
    if args.out and req:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(req, fh, indent=2, sort_keys=True)
    print("  request : {}".format(
        "{} mutation(s)".format(len(req["mutations"])) if req else errs))
    return 0 if req and not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
