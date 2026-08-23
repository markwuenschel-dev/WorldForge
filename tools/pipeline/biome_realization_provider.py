#!/usr/bin/env python3
"""biome_realization_provider -- compose the other providers into one biome.

WHAT MAKES THIS THE SEVENTH CATEGORY RATHER THAN A SEVENTH COPY
----------------------------------------------------------------
The four providers before this are leaves: each computes one kind of thing from
its own inputs and knows nothing about the others. A biome is not another leaf.
It is the claim that a ground surface, the things scattered on it, and the light
falling across them belong together -- and realising one means composing those
producers into a single bounded change that succeeds or fails as a unit.

So this provider's job is orchestration, and its real test is whether the leaves
compose without any of them being modified to accommodate it. If wiring a biome
had required editing the terrain, POI or rig providers, that would have been the
finding: four generators that only work alone are not a production system.

WHAT A BIOME IS HERE, AND WHOSE DECISION THAT IS
-------------------------------------------------
The caller declares it: which ground, which surface material, which scatter
kinds at what density and separation, which lighting elements. Every one of
those is ecology and art direction, which the mission assigns to the game in the
same breath that assigns production to WorldForge. There is no default biome, no
inferred palette, and no "temperate forest" preset -- a preset here would be
WorldForge deciding what the game's world is made of.

ALL OR NOTHING, AND WHY
------------------------
If any component refuses, the whole biome refuses and names which part and why.
A half-realised biome -- ground with no scatter, or scatter under no light -- is
not a partial success, it is a world that misrepresents what was asked for. The
composed request is one transaction with one bound, so the sink's existing
rollback covers the whole composition rather than leaving fragments behind.
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import environment_rig_provider as ER    # noqa: E402
from pipeline import poi_distribution_provider as PP    # noqa: E402
from pipeline import terrain_mesh_provider as TM        # noqa: E402
from wfcore.failure import FailureCode as C             # noqa: E402
from wfcore.providers import base as PB                 # noqa: E402

PROVIDER_ID = "biome_realization_planner"
RT_BIOME_PLAN = "wf.core.biome_realization_plan.v1"

_P = "biome_realization."

# A biome must declare at least one component. Which ones are optional is the
# caller's call -- a biome of pure lighting is odd but not incoherent, and
# refusing it would be WorldForge having an opinion about ecology.
COMPONENTS = ("ground", "scatter", "environment")

BIOME_REQUIRED = ("biome_id", "subject_map")
BIOME_ALLOWED = BIOME_REQUIRED + COMPONENTS + ("created_by", "detail",
                                               "schema_version", "report_type")


def validate_biome(biome, strict=False):
    code = C.CORE_PLACEMENT_PLAN_INVALID
    out = []
    is_obj = isinstance(biome, dict)
    out.append((_P + "biome_is_object", is_obj,
                "biome must be an object (got {})".format(type(biome).__name__),
                None if is_obj else code))
    if not is_obj:
        return out

    for f in BIOME_REQUIRED:
        ok = bool(biome.get(f))
        out.append((_P + "has_" + f, ok,
                    "biome is missing required {!r}".format(f),
                    None if ok else code))

    extra = sorted(set(biome) - set(BIOME_ALLOWED))
    out.append((_P + "no_unknown_keys", not extra,
                "unknown biome keys {}; the vocabulary is closed so a caller "
                "cannot describe a component nothing realises".format(extra),
                None if not extra else code))

    present = [c for c in COMPONENTS if biome.get(c)]
    out.append((_P + "declares_a_component", bool(present),
                "a biome declaring none of {} realises nothing. An empty biome "
                "is not a minimal world, it is an absent decision".format(
                    list(COMPONENTS)), None if present else code))
    return out


def plan_biome(biome):
    """Compose sub-plans. Any component refusing refuses the whole biome."""
    plan = {"schema_version": RT_BIOME_PLAN, "report_type": RT_BIOME_PLAN,
            "provider_id": PROVIDER_ID,
            "biome_id": (biome or {}).get("biome_id"),
            "subject_map": (biome or {}).get("subject_map"),
            "components": {}, "contributing_providers": [],
            "refused": False, "refusal_reason": None, "failure_codes": []}

    def refuse(reason, codes=None):
        plan.update({"refused": True, "refusal_reason": reason,
                     "components": {}})
        for c in (codes or [C.CORE_PLACEMENT_PLAN_INVALID]):
            if c and c not in plan["failure_codes"]:
                plan["failure_codes"].append(c)
        return plan

    bad = [c for c in validate_biome(biome, strict=True) if not c[1]]
    if bad:
        return refuse("; ".join(c[2] for c in bad[:3]),
                      [c[3] for c in bad if c[3]])

    # -- ground: terrain mesh + the surface it wears ------------------------- #
    ground = biome.get("ground")
    if ground:
        tplan = TM.plan_terrain_mesh(ground.get("terrain") or {})
        if tplan["refused"]:
            return refuse("ground refused by {}: {}".format(
                TM.PROVIDER_ID, tplan["refusal_reason"]),
                tplan.get("failure_codes"))
        tbad = [c[0] for c in TM.validate_terrain_plan(tplan, strict=True)
                if not c[1]]
        if tbad:
            return refuse("ground plan failed its own validator: {}".format(tbad))
        plan["components"]["ground"] = {
            "terrain_plan": tplan,
            "surface_material": ground.get("surface_material"),
            "actor_class": ground.get("actor_class"),
        }
        plan["contributing_providers"].append(TM.PROVIDER_ID)

    # -- scatter: POIs distributed over the biome's own region --------------- #
    scatter = biome.get("scatter")
    if scatter:
        pplan = PP.plan_poi_field(
            scatter.get("kinds") or [], scatter.get("count"),
            scatter.get("bound") or {}, scatter.get("min_separation_cm"),
            z_cm=scatter.get("z_cm", 0.0),
            exclusions=scatter.get("exclusions"))
        if pplan["refused"]:
            return refuse("scatter refused by {}: {}".format(
                PP.PROVIDER_ID, pplan["refusal_reason"]),
                pplan.get("failure_codes"))
        pbad = [c[0] for c in PP.validate_poi_plan(pplan, strict=True)
                if not c[1]]
        if pbad:
            return refuse("scatter plan failed its own validator: {}".format(pbad))
        plan["components"]["scatter"] = {
            "poi_plan": pplan,
            "actor_class": scatter.get("actor_class"),
            "static_mesh": scatter.get("static_mesh"),
            "material": scatter.get("material"),
        }
        plan["contributing_providers"].append(PP.PROVIDER_ID)

    # -- environment: the light this biome is seen under --------------------- #
    env = biome.get("environment")
    if env:
        eplan = ER.plan_rig(env)
        if eplan["refused"]:
            return refuse("environment refused by {}: {}".format(
                ER.PROVIDER_ID, eplan["refusal_reason"]),
                eplan.get("failure_codes"))
        plan["components"]["environment"] = {"rig_plan": eplan}
        plan["contributing_providers"].append(ER.PROVIDER_ID)

    return plan


def build_transaction_request(plan, operation_id, step_id,
                              evidence_refs=None):
    """One request, one bound, covering every component.

    Composed rather than concatenated: the bound is the union of what the
    components will touch, so the sink's rollback covers the whole biome. Three
    separate transactions could each succeed and still leave a world with ground
    and no scatter if the second failed.
    """
    if plan.get("refused"):
        return None, ["biome plan was refused ({})".format(
            plan.get("refusal_reason"))]
    comps = plan.get("components") or {}
    if not comps:
        return None, ["biome plan realises no components"]

    target_map = plan.get("subject_map")
    muts, actors, sources = [], [], []

    ground = comps.get("ground")
    if ground:
        tp = ground["terrain_plan"]
        if not ground.get("actor_class"):
            return None, ["ground declares no actor_class; what carries the "
                          "terrain mesh in this game is the game's decision"]
        from wfcore.transaction import delta as TD
        path = "{}:wfbiome_ground_{}".format(target_map.rstrip("/"),
                                             plan["biome_id"])
        payload = {"actor_class": ground["actor_class"],
                   "location": [0.0, 0.0, 0.0],
                   "rotation": [0.0, 0.0, 0.0],
                   "scale": [1.0, 1.0, 1.0],
                   "static_mesh": tp["asset_path"]}
        if ground.get("surface_material"):
            payload["material"] = ground["surface_material"]
        muts.append({
            "mutation_id": "mut_biome_ground",
            "step_id": step_id, "provider_id": PROVIDER_ID,
            "target_kind": TD.TARGET_ACTOR, "target_path": path,
            "operation": TD.OP_CREATE, "before_state": TD.absent_state(),
            "status": TD.MUT_PLANNED,
            "rollback_mode": PB.ROLLBACK_COMPENSATING,
            "schema_version": TD.RT_MUTATION,
            "expected_after_state": TD.present_state(payload),
            "detail": "biome ground from {}".format(TM.PROVIDER_ID),
        })
        actors.append(path)
        sources.append("terrain_mesh_plan")

    scatter = comps.get("scatter")
    if scatter:
        sreq, serr = PP.build_transaction_request(
            scatter["poi_plan"], operation_id, step_id, target_map,
            actor_class=scatter.get("actor_class"),
            static_mesh=scatter.get("static_mesh"),
            actor_prefix="wfbiome_{}".format(plan["biome_id"]))
        if sreq is None:
            return None, ["scatter: {}".format(serr)]
        muts.extend(sreq["mutations"])
        actors.extend(sreq["bounds"][0]["allowed_actors"])
        sources.append("poi_distribution_plan")

    env = comps.get("environment")
    if env:
        ereq, eerr = ER.build_transaction_request(
            env["rig_plan"], operation_id, step_id, target_map)
        if ereq is None:
            return None, ["environment: {}".format(eerr)]
        muts.extend(ereq["mutations"])
        actors.extend(ereq["bounds"][0]["allowed_actors"])
        sources.append("environment_rig_plan")

    from wfcore.transaction import delta as TD
    bound = {"step_id": step_id, "allowed_packages": [target_map],
             "allowed_actors": sorted(set(actors)),
             "schema_version": TD.RT_MUTATION_BOUND}
    # Re-stamp every borrowed mutation onto this step, so the bound above is the
    # one they are checked against rather than the sub-provider's.
    for m in muts:
        m["step_id"] = step_id
    return {"operation_id": operation_id, "bounds": [bound], "mutations": muts,
            "evidence_refs": list(evidence_refs or sources)}, []


def validate_biome_plan(plan, strict=False):
    code = C.CORE_PLACEMENT_PLAN_INVALID
    out = []
    if not isinstance(plan, dict):
        return [(_P + "plan_is_object", False, "plan must be an object", code)]

    if plan.get("refused"):
        out.append((_P + "refusal_names_a_code", bool(plan.get("failure_codes")),
                    "a refusal must name a code",
                    None if plan.get("failure_codes") else code))
        out.append((_P + "refusal_realises_nothing", not plan.get("components"),
                    "a refused biome must carry no realised components",
                    None if not plan.get("components") else code))
        out.append((_P + "refusal_names_the_component",
                    bool(plan.get("refusal_reason")),
                    "a composed refusal must say WHICH component refused and "
                    "why -- 'the biome failed' sends nobody anywhere",
                    None if plan.get("refusal_reason") else code))
        return out

    comps = plan.get("components") or {}
    out.append((_P + "realises_something", bool(comps),
                "an accepted biome plan must realise at least one component",
                None if comps else code))

    # A composed plan must credit the providers it actually used, so a reader
    # can go and check each sub-plan under its own validator.
    named = set(plan.get("contributing_providers") or [])
    expect = set()
    if comps.get("ground"):
        expect.add(TM.PROVIDER_ID)
    if comps.get("scatter"):
        expect.add(PP.PROVIDER_ID)
    if comps.get("environment"):
        expect.add(ER.PROVIDER_ID)
    out.append((_P + "credits_its_providers", named == expect,
                "components {} were realised but contributing_providers says "
                "{}; a composition that misreports its sources cannot be "
                "audited component by component".format(
                    sorted(comps), sorted(named)),
                None if named == expect else code))

    # Each sub-plan must still pass ITS OWN validator inside the composition.
    # Composition must not become a place where a component's rails stop
    # applying.
    if comps.get("ground"):
        sub = [c[0] for c in TM.validate_terrain_plan(
            comps["ground"]["terrain_plan"], strict=True) if not c[1]]
        out.append((_P + "ground_subplan_still_valid", not sub,
                    "terrain sub-plan fails its own validator inside the "
                    "composition: {}".format(sub), None if not sub else code))
    if comps.get("scatter"):
        sub = [c[0] for c in PP.validate_poi_plan(
            comps["scatter"]["poi_plan"], strict=True) if not c[1]]
        out.append((_P + "scatter_subplan_still_valid", not sub,
                    "POI sub-plan fails its own validator inside the "
                    "composition: {}".format(sub), None if not sub else code))
    return out


def declaration():
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_ID,
        capabilities=[PB.CAP_ENVIRONMENT_AUTHORING, PB.CAP_PROCEDURAL_SCATTER,
                      PB.CAP_TERRAIN_SHAPING],
        requirements=[],
        side_effects=[PB._example_side_effect(
            effect_id="eff_biome_plan_only",
            effect_kind=PB.EFFECT_EVIDENCE_ONLY,
            scope="evidence.biome_realization_plan",
            reversible=True,
            detail="composes sub-plans and emits one request; it writes "
                   "nothing and delegates every computation to the leaf "
                   "providers it credits")],
        determinism=PB.DET_SEEDED,
        rollback=PB.ROLLBACK_NONE,
        outputs=["biome_realization_plan", "transaction_request"],
        evidence=["biome_realization_plan"],
        limitations=[
            PB._example_limitation(
                limitation_id="lim_composes_only",
                limitation_kind="coverage_unknown",
                detail="decides nothing about ecology. Which ground, which "
                       "scatter, which light are all the caller's; this only "
                       "makes them one bounded change"),
            PB._example_limitation(
                limitation_id="lim_all_or_nothing",
                limitation_kind="input_shape",
                detail="any component refusing refuses the whole biome. A "
                       "half-realised biome misrepresents what was asked for"),
        ],
        description="composes terrain, scatter and environment providers into "
                    "one bounded biome")
    d["determinism_evidence"] = [
        "introduces no arithmetic of its own: every coordinate comes from a leaf "
        "provider that is itself deterministic",
        "component order is fixed (ground, scatter, environment), so the emitted "
        "mutation list is stable",
        "pipeline/test_biome_realization_provider.py re-plans and compares "
        "canonical JSON",
    ]
    return d


def canonical(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--biome", required=True, help="caller-declared biome JSON")
    ap.add_argument("--operation-id", required=True)
    ap.add_argument("--out")
    ap.add_argument("--terrain-spec-out",
                    help="write the ground's mesh synthesis spec here")
    args = ap.parse_args(argv)

    with open(args.biome, encoding="utf-8") as fh:
        biome = json.load(fh)
    plan = plan_biome(biome)
    bad = [c[0] for c in validate_biome_plan(plan, strict=True) if not c[1]]

    print("biome -- {}".format(plan.get("biome_id")))
    print("  refused : {}".format(plan["refused"]))
    if plan["refused"]:
        print("  reason  : {}".format(plan["refusal_reason"][:240]))
        print("  codes   : {}".format(plan["failure_codes"]))
        return 1
    print("  realises: {}".format(sorted(plan["components"])))
    print("  from    : {}".format(plan["contributing_providers"]))
    print("  validator: {}".format(bad or "clean"))

    req, errs = build_transaction_request(
        plan, args.operation_id, "step_biome_realization")
    if req:
        print("  request : {} mutation(s), {} actor(s) in one bound".format(
            len(req["mutations"]), len(req["bounds"][0]["allowed_actors"])))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(req, fh, indent=2, sort_keys=True)
    else:
        print("  request : {}".format(errs)); return 1

    ground = (plan.get("components") or {}).get("ground")
    if args.terrain_spec_out and ground:
        with open(args.terrain_spec_out, "w", encoding="utf-8") as fh:
            json.dump(ground["terrain_plan"], fh, indent=2, sort_keys=True)
        print("  ground spec -> {}".format(args.terrain_spec_out))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
