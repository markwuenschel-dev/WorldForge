#!/usr/bin/env python3
"""landscape_provider.py -- a real Unreal Landscape as a BOUNDED world mutation.

WHY REIMPLEMENTED, NOT ADAPTED
------------------------------
``ALandscape`` is an ACTOR. The transaction sink can un-spawn an actor, so this
lane can carry a genuine compensating rollback -- which is the whole basis of
the split: adapt what cannot be undone (assets, via ``asset_lane_provider``),
reimplement what can (world mutations, through the sink).

WHAT THIS IS NOT
----------------
``terrain_mesh_provider`` already produces terrain, and says plainly what it is:
a displaced StaticMesh grid, "No erosion, no biome-driven material blending, no
LOD, and NOT a real Landscape". This module is the landscape lane that named
gap refers to. It fills ``terrain_shaping``, the capability the vocabulary has
reserved since the beginning with nothing offering it.

The heightfield mathematics is IMPORTED from ``terrain_mesh_provider``, not
rewritten. A second implementation of the same noise would be a second authority
on what the terrain is, and the two would drift.

THE ENGINE'S SIZING INVARIANT IS A RAIL, NOT A SUGGESTION
---------------------------------------------------------
An Unreal landscape is not a free-form grid. Vertices per side must be exactly

    section_size * sections_per_component * component_count + 1

with ``section_size`` one of the supported quad counts and
``sections_per_component`` either 1 or 4. A grid that violates this is not a
smaller landscape -- it is one the engine rejects or silently reshapes, and
"silently reshaped" is the outcome that would leave a plan describing a world
nobody built. So it is refused at plan time (WF1274), where the number is still
checkable and no editor boot has been spent.

Heights are emitted as uint16 in the engine's own convention: 0..65535 with
32768 as zero elevation. Converting at the boundary means the plan carries what
the engine consumes, rather than a normalised float somebody must remember to
scale later.

WHAT A LIVE RUN ESTABLISHED -- op_landscape_live_0001, and it FAILED
--------------------------------------------------------------------
Run against a real editor, this plan does NOT produce a landscape, and the
failure is structural rather than a defect in the plan:

    spawned Landscape as ...PersistentLevel.LandscapePlaceholder_0
      via getattr(unreal, 'Landscape')
    outcome=rolled_back verification=violated codes=['WF1246_CORE_DELTA_INVALID']

Asking the engine to spawn ``Landscape`` as a plain actor yields a
``LandscapePlaceholder``, not an ``ALandscape``. A real landscape cannot be
created by actor spawning at all -- it needs the landscape creation pipeline
(heightmap import plus component construction), which is not something the
mutation sink can express. The verification rail caught the class mismatch, the
delta was refused, and rollback destroyed the placeholder.

That is the rails working, and it is a more useful result than a green run would
have been: it proves the sink's actor path cannot build this capability, rather
than leaving that to be assumed. This provider therefore stops at
shield_integrated on the evidence ladder, blocked from runtime_qualified for a
reason that is named rather than hidden behind a ceiling.

WHY IT FAILED -- ANSWERED BY PROBING THE ENGINE, NOT BY INFERENCE
-----------------------------------------------------------------
Rather than guess which API should have been used, the engine was asked.
``tools/unreal/_probe_landscape_api.py`` enumerates the live 5.8 bindings; its
stamped report is committed at
``procedural/reports/core/landscape_probe/landscape_api_probe.json``. What it
establishes:

* ``LandscapeSubsystem`` and ``LandscapeEditorSubsystem`` DO NOT EXIST in the
  Python bindings at all.
* There is no module-level landscape create/new/import function.
* ``Landscape`` and ``LandscapeProxy`` DO expose
  ``landscape_import_heightmap_from_render_target`` -- but those are methods on
  an ALREADY-CREATED landscape, and they take a render target rather than a
  height array.
* ``LandscapePlaceholder``, which is exactly what actor spawning produced,
  carries none of those methods.

So a real ``ALandscape`` cannot be constructed from Python in UE 5.8. The sink
failing on it was the engine behaving correctly, not a defect in the sink or in
this plan. Creating one needs the editor's Landscape mode or C++ -- which is
what the D19 engine-substrate milestone is for, and is out of scope here.

This is why the ladder shows this provider blocked at shield_integrated with a
named reason rather than at a ceiling: a ceiling would say "inapplicable", and
this is applicable, unbuilt, and blocked on something specific.

NOTE the capability is NOT unserved. ``terrain_shaping`` is also declared by
``terrain_mesh_planner``, which IS runtime_qualified -- it built a real
StaticMesh terrain asset in a live editor. Terrain shaping as a capability has a
proven provider; ``ALandscape`` specifically does not.

HONEST LIMIT -- READ THIS BEFORE TRUSTING A GREEN RUN
-----------------------------------------------------
The sink's payload vocabulary is {actor_class, location, rotation, scale} plus
optional static_mesh and material. There is NO key that carries heightmap data.
So a landscape materialised through the sink today arrives as a bare actor with
this plan's height data NOT imported -- exactly the same structural gap
``pcg_scatter_provider`` hit with graph binding. The two together say something
about the sink rather than about either provider: it places actors, it does not
configure them. That is stated here, and declared as a limitation, so a
committed transaction is never read as a built landscape.

Usage:
    cd tools && PYTHONUTF8=1 python pipeline/landscape_provider.py --demo
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.failure import FailureCode as C          # noqa: E402
from wfcore.providers import base as PB              # noqa: E402
from wfcore.transaction import delta as TD           # noqa: E402
from pipeline import terrain_mesh_provider as TMP    # noqa: E402

PROVIDER_ID = "landscape_planner"
RT_LANDSCAPE_PLAN = "wf.core.landscape_plan.v1"

LANDSCAPE_CLASS = "Landscape"

# Engine-supported section sizes, in QUADS. Not a stylistic choice: the
# landscape renderer's LOD chain is built around these.
SECTION_SIZES = (7, 15, 31, 63, 127, 255)
SECTIONS_PER_COMPONENT = (1, 4)

# uint16 height encoding. 32768 is zero elevation; full scale spans +/- 256m at
# the default Z scale of 100.
HEIGHT_MID = 32768
HEIGHT_MAX = 65535

# A component count beyond this is minutes of editor time and gigabytes of
# heightmap. Declared as a cap rather than discovered as a hang.
MAX_COMPONENT_COUNT = 32

_COORD_DECIMALS = 3


def _r(v):
    return round(float(v) + 0.0, _COORD_DECIMALS)


def vertices_per_side(section_size, sections_per_component, component_count):
    """The engine's sizing invariant, in one place."""
    return section_size * sections_per_component * component_count + 1


def plan_landscape(region, seed, section_size=63, sections_per_component=1,
                   component_count=1, height_scale_cm=25600.0,
                   octaves=4, lacunarity=2.0, gain=0.5, frequency=2.0):
    """Plan one landscape over ``region`` ({min:[x,y,z], max:[x,y,z]} in cm).

    Returns a plan document; never raises. A refusal is a value.
    """
    plan = {
        "schema_version": RT_LANDSCAPE_PLAN,
        "report_type": RT_LANDSCAPE_PLAN,
        "provider_id": PROVIDER_ID,
        "seed": seed,
        "section_size": section_size,
        "sections_per_component": sections_per_component,
        "component_count": component_count,
        "vertices_per_side": None,
        "actor": None,
        "heightmap_uint16": [],
        "observed_height_range_cm": None,
        "refused": False,
        "refusal_reason": None,
        "failure_codes": [],
    }

    def refuse(reason, code=C.CORE_LANDSCAPE_GRID_INVALID):
        plan.update({"refused": True, "refusal_reason": reason, "actor": None,
                     "heightmap_uint16": [], "vertices_per_side": None,
                     "observed_height_range_cm": None})
        if code not in plan["failure_codes"]:
            plan["failure_codes"].append(code)
        return plan

    # -- the engine's invariant, checked before anything expensive ----------
    if section_size not in SECTION_SIZES:
        return refuse("section_size {} is not an engine-supported quad count "
                      "{}; the landscape LOD chain is built around these"
                      .format(section_size, list(SECTION_SIZES)))
    if sections_per_component not in SECTIONS_PER_COMPONENT:
        return refuse("sections_per_component {} must be one of {}"
                      .format(sections_per_component,
                              list(SECTIONS_PER_COMPONENT)))
    if not isinstance(component_count, int) or component_count < 1:
        return refuse("component_count must be a positive integer, got {!r}"
                      .format(component_count))
    if component_count > MAX_COMPONENT_COUNT:
        return refuse("component_count {} exceeds the declared cap of {}; a "
                      "larger landscape is refused rather than silently costing "
                      "minutes of editor time".format(component_count,
                                                      MAX_COMPONENT_COUNT))

    n = vertices_per_side(section_size, sections_per_component, component_count)
    plan["vertices_per_side"] = n

    # -- region ------------------------------------------------------------
    if not isinstance(region, dict):
        return refuse("region must be an object with min and max",
                      C.CORE_PLACEMENT_PLAN_INVALID)
    lo, hi = region.get("min"), region.get("max")
    if not (isinstance(lo, (list, tuple)) and isinstance(hi, (list, tuple))
            and len(lo) == 3 and len(hi) == 3):
        return refuse("region.min and region.max must each be three numbers",
                      C.CORE_PLACEMENT_PLAN_INVALID)
    try:
        lo = [float(v) for v in lo]
        hi = [float(v) for v in hi]
    except (TypeError, ValueError):
        return refuse("region bounds must be numeric", C.CORE_PLACEMENT_PLAN_INVALID)
    extent = [hi[i] - lo[i] for i in range(2)]
    if any(e <= 0 for e in extent):
        return refuse("region.max must exceed region.min in X and Y; got {}"
                      .format(extent), C.CORE_PLACEMENT_PLAN_INVALID)

    if not isinstance(seed, int):
        return refuse("seed must be an integer; a landscape that cannot be "
                      "regenerated identically cannot be rebuilt",
                      C.CORE_PLACEMENT_PLAN_INVALID)
    if height_scale_cm <= 0:
        return refuse("height_scale_cm must be positive, got {!r}"
                      .format(height_scale_cm), C.CORE_PLACEMENT_PLAN_INVALID)

    # -- heights: the SAME mathematics the mesh lane uses -------------------
    # resolution is quads per side; heightfield returns (resolution+1)^2.
    rows = TMP.heightfield(n - 1, seed, octaves, lacunarity, gain, frequency)

    flat = []
    lo_cm, hi_cm = None, None
    for row in rows:
        for h in row:
            cm = (h - 0.5) * height_scale_cm
            lo_cm = cm if lo_cm is None else min(lo_cm, cm)
            hi_cm = cm if hi_cm is None else max(hi_cm, cm)
            # engine convention: uint16, 32768 == zero elevation
            u = int(round(HEIGHT_MID + (h - 0.5) * HEIGHT_MAX))
            flat.append(max(0, min(HEIGHT_MAX, u)))

    if len(flat) != n * n:
        return refuse("heightmap has {} samples, expected {} for a {}x{} grid; "
                      "the generator and the invariant disagree"
                      .format(len(flat), n * n, n, n))

    plan["heightmap_uint16"] = flat
    # RE-MEASURED from the emitted samples, not carried from the request.
    plan["observed_height_range_cm"] = [_r(lo_cm), _r(hi_cm)]

    # Landscape scale: X/Y so the grid spans the region, Z from the height range.
    plan["actor"] = {
        "actor_class": LANDSCAPE_CLASS,
        "location": [_r(lo[0]), _r(lo[1]), _r((lo[2] + hi[2]) / 2.0)],
        "rotation": [0.0, 0.0, 0.0],
        "scale": [_r(extent[0] / float(n - 1)), _r(extent[1] / float(n - 1)),
                  _r(height_scale_cm / 25600.0 * 100.0)],
    }
    return plan


def build_transaction_request(plan, operation_id, step_id, target_package,
                              actor_label, evidence_refs=None):
    """(request_or_None, errors). The sink places the actor; see the honest limit."""
    if not isinstance(plan, dict):
        return None, ["plan must be an object"]
    if plan.get("refused"):
        return None, ["plan is refused ({}); nothing to run".format(
            plan.get("refusal_reason"))]
    if not plan.get("actor"):
        return None, ["plan carries no actor"]

    actor_path = "{}:{}".format(target_package.rstrip("/"), actor_label)
    bound = {
        "step_id": step_id,
        "allowed_packages": [target_package],
        "allowed_actors": [actor_path],
        "schema_version": TD.RT_MUTATION_BOUND,
    }
    a = plan["actor"]
    payload = {
        "actor_class": a["actor_class"],
        "location": list(a["location"]),
        "rotation": list(a["rotation"]),
        "scale": list(a["scale"]),
    }
    mutation = {
        "mutation_id": "mut_{}".format(actor_label),
        "step_id": step_id,
        "provider_id": PROVIDER_ID,
        "target_kind": TD.TARGET_ACTOR,
        "target_path": actor_path,
        "operation": TD.OP_CREATE,
        "before_state": TD.absent_state(),
        "expected_after_state": TD.present_state(payload),
        "status": TD.MUT_PLANNED,
        "rollback_mode": PB.ROLLBACK_COMPENSATING,
        "schema_version": TD.RT_MUTATION,
        "detail": "landscape {n}x{n} vertices ({s} quads x {spc} x {cc}); "
                  "heightmap of {h} uint16 samples is NOT carried by this "
                  "request -- the sink payload has no key for it".format(
                      n=plan["vertices_per_side"], s=plan["section_size"],
                      spc=plan["sections_per_component"],
                      cc=plan["component_count"],
                      h=len(plan["heightmap_uint16"])),
    }
    return {
        "operation_id": operation_id,
        "bounds": [bound],
        "mutations": [mutation],
        "evidence_refs": list(evidence_refs or ["landscape_plan"]),
    }, []


def validate_landscape_plan(plan, strict=False):
    checks = []

    def c(name, ok, detail="", code=C.CORE_LANDSCAPE_GRID_INVALID):
        checks.append((name, bool(ok), detail, None if ok else code))
        return ok

    if not isinstance(plan, dict):
        c("landscape_plan_is_object", False, "plan must be an object")
        return checks
    c("landscape_schema_version", plan.get("schema_version") == RT_LANDSCAPE_PLAN,
      "schema_version must be {}".format(RT_LANDSCAPE_PLAN))

    if plan.get("refused"):
        c("refusal_carries_no_actor", plan.get("actor") is None,
          "a refused plan must carry no actor")
        c("refusal_carries_no_heightmap", not plan.get("heightmap_uint16"),
          "a refused plan must carry no height data")
        c("refusal_names_a_code", bool(plan.get("failure_codes")),
          "a refusal must name why")
        return checks

    n = plan.get("vertices_per_side")
    c("grid_matches_engine_invariant",
      n == vertices_per_side(plan.get("section_size"),
                             plan.get("sections_per_component"),
                             plan.get("component_count")),
      "vertices_per_side {} does not satisfy section*spc*cc+1".format(n))
    hm = plan.get("heightmap_uint16") or []
    c("heightmap_length_matches_grid", isinstance(n, int) and len(hm) == n * n,
      "heightmap has {} samples, expected {}".format(
          len(hm), (n * n) if isinstance(n, int) else "?"))
    c("heightmap_in_uint16_range",
      all(isinstance(v, int) and 0 <= v <= HEIGHT_MAX for v in hm),
      "every height must be a uint16; the engine reads this range and nothing else")
    rng = plan.get("observed_height_range_cm")
    c("height_range_remeasured",
      isinstance(rng, list) and len(rng) == 2 and rng[0] <= rng[1],
      "observed_height_range_cm must be [lo, hi] re-measured from the emitted "
      "samples, got {!r}".format(rng))
    a = plan.get("actor") or {}
    c("actor_class_is_landscape", a.get("actor_class") == LANDSCAPE_CLASS,
      "actor_class must be {}".format(LANDSCAPE_CLASS))
    c("actor_scale_positive",
      all(isinstance(v, float) and v > 0 for v in a.get("scale", [])),
      "scale must be positive on every axis, got {}".format(a.get("scale")))
    return checks


def declaration():
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_ID,
        capabilities=[PB.CAP_TERRAIN_SHAPING],
        requirements=[],
        side_effects=[PB._example_side_effect(
            effect_id="eff_landscape_plan_only",
            effect_kind=PB.EFFECT_EVIDENCE_ONLY,
            scope="evidence.landscape_plan",
            reversible=True,
            detail="computes a heightfield and emits a landscape plan plus a "
                   "transaction request. It writes nothing into the world; the "
                   "sink does, under its own bound and its own rollback")],
        determinism=PB.DET_SEEDED,
        rollback=PB.ROLLBACK_NONE,
        outputs=["landscape_plan", "transaction_request"],
        evidence=["landscape_plan"],
        limitations=[
            PB._example_limitation(
                limitation_id="lim_heightmap_not_carried_by_the_sink",
                limitation_kind="coverage_unknown",
                detail="the sink payload is {actor_class, location, rotation, "
                       "scale} plus optional static_mesh and material -- there "
                       "is no key carrying heightmap data. A landscape placed "
                       "through the sink today therefore arrives BARE, with "
                       "this plan's heights not imported. The identical gap "
                       "stops pcg_scatter_provider binding a graph, so the two "
                       "together are a statement about the sink: it places "
                       "actors, it does not configure them. Declared so a "
                       "committed transaction is never read as a built landscape"),
            PB._example_limitation(
                limitation_id="lim_sink_cannot_construct_a_landscape",
                limitation_kind="platform",
                detail="PROVEN BY op_landscape_live_0001 (which failed) and "
                       "then EXPLAINED by _probe_landscape_api: UE 5.8 exposes "
                       "no landscape creation API to Python -- no "
                       "LandscapeSubsystem, no LandscapeEditorSubsystem, no "
                       "module-level create function; the probe report is "
                       "committed at procedural/reports/core/landscape_probe/. "
                       "getattr(unreal, 'Landscape') spawned as an actor yields "
                       "a LandscapePlaceholder, not an ALandscape: a landscape "
                       "needs the engine's creation pipeline (heightmap import "
                       "plus component construction), which the mutation sink "
                       "cannot express. Verification caught the class mismatch "
                       "(WF1246) and rollback removed it. This plan is therefore "
                       "correct and unmaterialisable by the sink path, and the "
                       "gap is in the far side, not in the planning"),
            PB._example_limitation(
                limitation_id="lim_no_erosion_or_layers",
                limitation_kind="fidelity",
                detail="fBm heights only. No hydraulic or thermal erosion, no "
                       "layer/weightmap painting, no foliage, no material "
                       "layers -- all real parts of landscape production that "
                       "this does not do"),
            PB._example_limitation(
                limitation_id="lim_component_cap",
                limitation_kind="scale",
                detail="component_count is capped at {}; a larger landscape is "
                       "refused rather than silently costing minutes of editor "
                       "time and gigabytes of heightmap".format(
                           MAX_COMPONENT_COUNT)),
        ],
        description="a deterministic fBm landscape sized to the engine's own "
                    "section/component invariant")
    d["determinism_evidence"] = [
        "heights come from terrain_mesh_provider.heightfield, which is a "
        "blake2b hash of (x, y, seed) with no RNG and no traversal-order "
        "dependence -- imported, not reimplemented, so the two lanes cannot "
        "disagree about what the terrain is",
        "the uint16 conversion is pure arithmetic on that value",
        "pipeline/test_landscape_provider.py re-plans and compares canonical "
        "JSON byte-for-byte, and asserts a different seed changes the heights",
    ]
    d["cost_profile"] = {"wall_seconds": 2.0, "operator_attention": 0.0}
    return d


def canonical(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan a bounded Unreal landscape.")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args(argv)
    if not args.demo:
        ap.print_help()
        return 0
    plan = plan_landscape(
        region={"min": [-6300.0, -6300.0, 0.0], "max": [6300.0, 6300.0, 0.0]},
        seed=1337, section_size=63, sections_per_component=1, component_count=1)
    summary = {k: v for k, v in plan.items() if k != "heightmap_uint16"}
    summary["heightmap_samples"] = len(plan["heightmap_uint16"])
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
