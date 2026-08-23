#!/usr/bin/env python3
"""environment_rig_provider -- the second provider, and the point is that it is.

WHY THIS EXISTS AT ALL
----------------------
Until now the loop had exactly one generator: a route-placement planner. A
platform with one provider is indistinguishable from a pipeline with a hard-coded
step -- the seam is only real if something structurally different can sit in it
without the seam changing. An environment rig is that different thing: it is not
a route, it has no anchors, it is not spaced along anything, and its content is
mostly PROPERTIES rather than positions.

So this exists to answer a question about the architecture, not only to add a
category. If wiring it had required editing the transaction shape, the manifest,
the bound rails, or the loop, that would have been the finding.

WHAT AN ENVIRONMENT RIG IS HERE
--------------------------------
A caller-declared set of elements -- a sun, a sky light, fog, an atmosphere --
each naming its actor class, its transform, and the scalar properties the game
wants set on it. Every one of those is the caller's: WorldForge does not know
what a night should look like, and a default sun angle invented here would be
exactly the invented meaning the boundary forbids. There is no default rig.

WHAT IT DELIBERATELY DOES NOT DO
---------------------------------
It does not compose, balance, or art-direct. Lighting is art direction, which the
mission assigns to the game in the same sentence that assigns production to
WorldForge. This places what it is told to place, sets what it is told to set,
and refuses anything it was not told.
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.failure import FailureCode as C     # noqa: E402
from wfcore.providers import base as PB         # noqa: E402
from wfcore.transaction import delta as TD      # noqa: E402

PROVIDER_ID = "environment_rig_planner"
RT_RIG_PLAN = "wf.core.environment_rig_plan.v1"

_P = "environment_rig."

ELEMENT_REQUIRED = ("element_id", "actor_class")
ELEMENT_ALLOWED = ELEMENT_REQUIRED + ("location_cm", "rotation_pyr", "scale",
                                      "properties", "detail")

_SCALARS = (bool, int, float, str)


def _is_triple(v):
    return (isinstance(v, (list, tuple)) and len(v) == 3
            and all(isinstance(c, (int, float)) and not isinstance(c, bool)
                    for c in v))


def validate_rig(rig, strict=False):
    """Rails over a caller-declared rig. Cheap, and it refuses before an editor."""
    code = C.CORE_PLACEMENT_PLAN_INVALID
    out = []
    is_obj = isinstance(rig, dict)
    out.append((_P + "rig_is_object", is_obj,
                "rig must be an object (got {})".format(type(rig).__name__),
                None if is_obj else code))
    if not is_obj:
        return out

    els = rig.get("elements")
    ok = isinstance(els, list) and len(els) >= 1
    out.append((_P + "has_elements", ok,
                "a rig must declare at least one element; an empty rig is not a "
                "lighting decision, it is an absent one", None if ok else code))
    if not ok:
        return out

    seen = set()
    for i, e in enumerate(els):
        pfx = _P + "element[{}].".format(i)
        if not isinstance(e, dict):
            out.append((pfx + "is_object", False, "element must be an object",
                        code))
            continue
        for f in ELEMENT_REQUIRED:
            has = bool(e.get(f))
            out.append((pfx + "has_" + f, has,
                        "element missing required {!r}; WorldForge will not "
                        "choose an actor class for a rig it did not "
                        "design".format(f), None if has else code))
        extra = sorted(set(e) - set(ELEMENT_ALLOWED))
        out.append((pfx + "no_unknown_keys", not extra,
                    "unknown element keys {}".format(extra),
                    None if not extra else code))

        eid = e.get("element_id")
        dupe = eid in seen
        seen.add(eid)
        out.append((pfx + "element_id_unique", not dupe,
                    "element_id {!r} appears twice; two elements sharing an id "
                    "cannot be told apart in the world or in the "
                    "manifest".format(eid), None if not dupe else code))

        for fld in ("location_cm", "rotation_pyr", "scale"):
            if fld in e:
                good = _is_triple(e[fld])
                out.append((pfx + fld + "_is_triple", good,
                            "{} must be three finite numbers (got {!r})".format(
                                fld, e[fld]), None if good else code))

        props = e.get("properties")
        if props is not None:
            good = isinstance(props, dict) and all(
                isinstance(k, str) and isinstance(v, _SCALARS)
                and not isinstance(v, bytes) for k, v in props.items())
            out.append((pfx + "properties_are_scalars", good,
                        "properties must be a flat map of scalars: anything else "
                        "cannot be read back, and a value that cannot be observed "
                        "cannot be verified (got {!r})".format(props),
                        None if good else code))
    return out


def plan_rig(rig):
    """A rig plan. Refusal is a result with a reason, never an exception."""
    plan = {"schema_version": RT_RIG_PLAN, "report_type": RT_RIG_PLAN,
            "provider_id": PROVIDER_ID, "rig_id": (rig or {}).get("rig_id"),
            "elements": [], "refused": False, "refusal_reason": None,
            "failure_codes": []}
    bad = [c for c in validate_rig(rig, strict=True) if not c[1]]
    if bad:
        plan.update({"refused": True,
                     "refusal_reason": "; ".join(c[2] for c in bad[:3]),
                     "failure_codes": sorted({c[3] for c in bad if c[3]})})
        return plan

    for e in rig["elements"]:
        plan["elements"].append({
            "element_id": e["element_id"],
            "actor_class": e["actor_class"],
            # Absent transform components default to the world origin and
            # identity -- and that is stated, not silent. A sun's ROTATION is
            # meaningful and the caller must give it; its location is not, and
            # pretending otherwise would demand a number nobody has an opinion
            # about.
            "location_cm": list(e.get("location_cm") or [0.0, 0.0, 0.0]),
            "rotation_pyr": list(e.get("rotation_pyr") or [0.0, 0.0, 0.0]),
            "scale": list(e.get("scale") or [1.0, 1.0, 1.0]),
            "properties": dict(e.get("properties") or {}),
        })
    return plan


def build_transaction_request(plan, operation_id, step_id, target_package,
                              evidence_refs=None):
    """The SAME request shape the placement provider emits.

    Not a similar one -- the same. If a second provider needed its own transport
    the seam would be a story rather than a seam.
    """
    if plan.get("refused"):
        return None, ["rig plan was refused ({}); no transaction request is "
                      "derivable".format(plan.get("refusal_reason"))]
    if not plan.get("elements"):
        return None, ["rig plan contains no elements"]

    actors, muts = [], []
    for i, el in enumerate(plan["elements"]):
        path = "{}:{}".format(target_package.rstrip("/"), el["element_id"])
        actors.append(path)
        muts.append({
            "mutation_id": "mut_rig_{}_{:03d}".format(el["element_id"], i),
            "step_id": step_id, "provider_id": PROVIDER_ID,
            "target_kind": TD.TARGET_ACTOR, "target_path": path,
            "operation": TD.OP_CREATE,
            "before_state": TD.absent_state(),
            "status": TD.MUT_PLANNED,
            "rollback_mode": PB.ROLLBACK_COMPENSATING,
            "schema_version": TD.RT_MUTATION,
            "expected_after_state": TD.present_state(dict(
                {"actor_class": el["actor_class"],
                 "location": list(el["location_cm"]),
                 "rotation": list(el["rotation_pyr"]),
                 "scale": list(el["scale"])},
                **({"properties": el["properties"]} if el["properties"] else {}))),
            "detail": "environment rig element {!r}".format(el["element_id"]),
        })

    bound = {"step_id": step_id, "allowed_packages": [target_package],
             "allowed_actors": sorted(actors),
             "schema_version": TD.RT_MUTATION_BOUND}
    return {"operation_id": operation_id, "bounds": [bound],
            "mutations": muts,
            "evidence_refs": list(evidence_refs or ["environment_rig_plan"])}, []


def declaration():
    """``wf.core.provider_declaration.v1`` for this planner."""
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_ID,
        capabilities=[PB.CAP_ENVIRONMENT_AUTHORING],
        requirements=[],
        side_effects=[PB._example_side_effect(
            effect_id="eff_rig_plan_only",
            effect_kind=PB.EFFECT_EVIDENCE_ONLY,
            scope="evidence.environment_rig_plan",
            reversible=True,
            detail="computes a rig plan and emits a document; it writes nothing "
                   "into the world. Materialisation is the sink's job, under its "
                   "own bound and its own rollback")],
        determinism=PB.DET_SEEDED,
        rollback=PB.ROLLBACK_NONE,
        outputs=["environment_rig_plan", "transaction_request"],
        evidence=["environment_rig_plan"],
        limitations=[
            PB._example_limitation(
                limitation_id="lim_no_art_direction",
                limitation_kind="coverage_unknown",
                detail="places and configures exactly what the caller declared. "
                       "Whether the result LOOKS right is art direction, which "
                       "belongs to the game"),
            PB._example_limitation(
                limitation_id="lim_scalar_properties_only",
                limitation_kind="input_shape",
                detail="properties must be scalars, because anything else cannot "
                       "be read back and so could never be verified"),
        ],
        description="caller-declared environment rig elements as bounded "
                    "mutations")
    d["determinism_evidence"] = [
        "no RNG: the plan is a direct transcription of the caller's declaration",
        "element order follows the caller's list; nothing is sorted or shuffled",
        "pipeline/test_environment_rig_provider.py re-plans and compares "
        "canonical JSON",
    ]
    return d


def canonical(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rig", required=True, help="caller-declared rig JSON")
    ap.add_argument("--operation-id", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    with open(args.rig, encoding="utf-8") as fh:
        rig = json.load(fh)
    plan = plan_rig(rig)
    req, errs = build_transaction_request(
        plan, args.operation_id, "step_environment_rig", args.map)
    if args.out and req:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(req, fh, indent=2, sort_keys=True)
    print("environment rig -- {}".format(plan.get("rig_id")))
    print("  refused : {}".format(plan["refused"]))
    if plan["refused"]:
        print("  reason  : {}".format(plan["refusal_reason"][:200])); return 1
    print("  elements: {}".format(len(plan["elements"])))
    for el in plan["elements"]:
        print("    {:20} {:24} props={}".format(
            el["element_id"], el["actor_class"], sorted(el["properties"])))
    print("  request : {}".format("built" if req else errs))
    return 0 if req else 1


if __name__ == "__main__":
    raise SystemExit(main())
