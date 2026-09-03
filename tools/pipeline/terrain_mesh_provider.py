#!/usr/bin/env python3
"""terrain_mesh_provider -- a heightfield, and the mesh that realises it.

WHY ASSET SYNTHESIS IS A SEPARATE STEP FROM WORLD MUTATION
-----------------------------------------------------------
The three providers before this all produced ACTORS: things placed in a level,
bounded by a level, undone by removing them from a level. Terrain is not that. A
terrain mesh is an ASSET -- it is created once, lives in the content tree, and is
then placed like any other mesh. Those are different lifecycles with different
restore points, and folding asset creation into the world-mutation transaction
would have given the sink a compensation problem it cannot honestly solve: an
actor can be un-spawned, but "un-creating" an asset something else already
references is not a rollback, it is a break.

So this emits a synthesis SPEC. A separate editor step builds the asset from it,
and the placement providers that already exist put it in the world. Nothing about
the transaction rails changes, which is the same result the previous two
providers produced and the reason to trust the seam.

THE HEIGHTFIELD IS DETERMINISTIC AND SEEDED BY VALUE
-----------------------------------------------------
Fractal Brownian motion over a value-noise lattice, where the lattice value at
(x, y) is a pure hash of (x, y, seed). No RNG, no state, no ordering dependency:
the height at any coordinate can be computed alone and will agree with a run that
computed it in a different order on a different machine. The seed is the
caller's, because how rough a world should be is the game's decision.

WHAT IS DELIBERATELY NOT HERE
------------------------------
No erosion, no biome-driven material blending, no LOD generation. Those are real
parts of terrain production and their absence is stated rather than implied by
silence -- a "terrain provider" that quietly produced only a displaced grid while
sounding like it produced terrain would be the overclaim this session has already
had to correct once.
"""

import argparse
import hashlib
import json
import math
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.failure import FailureCode as C     # noqa: E402
from wfcore.providers import base as PB         # noqa: E402

PROVIDER_ID = "terrain_mesh_planner"
RT_TERRAIN_PLAN = "wf.core.terrain_mesh_plan.v1"

_P = "terrain_mesh."
_COORD_DECIMALS = 3

# A grid this size already costs (N+1)^2 vertices and 2*N^2 triangles. The cap
# is declared rather than discovered as a hang: a caller asking for 4096 should
# be told no, not left waiting.
MAX_RESOLUTION = 256


def _hash01(ix, iy, seed):
    """Deterministic value in [0,1) from integer lattice coords and a seed.

    A hash rather than an RNG: the value at a lattice point depends on nothing
    but that point, so no traversal order can change the terrain.
    """
    blob = struct.pack("<qqq", int(ix), int(iy), int(seed))
    digest = hashlib.blake2b(blob, digest_size=8).digest()
    return struct.unpack("<Q", digest)[0] / float(1 << 64)


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def _value_noise(x, y, seed):
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = _smooth(x - x0), _smooth(y - y0)
    v00 = _hash01(x0, y0, seed)
    v10 = _hash01(x0 + 1, y0, seed)
    v01 = _hash01(x0, y0 + 1, seed)
    v11 = _hash01(x0 + 1, y0 + 1, seed)
    return (v00 * (1 - fx) * (1 - fy) + v10 * fx * (1 - fy)
            + v01 * (1 - fx) * fy + v11 * fx * fy)


def heightfield(resolution, seed, octaves, lacunarity, gain, frequency):
    """(resolution+1)^2 normalised heights in [0,1]. Pure arithmetic."""
    rows = []
    for j in range(resolution + 1):
        row = []
        for i in range(resolution + 1):
            amp, freq, total, norm = 1.0, float(frequency), 0.0, 0.0
            u = i / float(resolution)
            v = j / float(resolution)
            for _o in range(octaves):
                total += amp * _value_noise(u * freq, v * freq, seed)
                norm += amp
                amp *= gain
                freq *= lacunarity
            row.append(total / norm if norm else 0.0)
        rows.append(row)
    return rows


def plan_terrain_mesh(terrain):
    """A terrain synthesis spec. Refusal is a result with a reason."""
    plan = {"schema_version": RT_TERRAIN_PLAN, "report_type": RT_TERRAIN_PLAN,
            "provider_id": PROVIDER_ID,
            "terrain_id": (terrain or {}).get("terrain_id"),
            "refused": False, "refusal_reason": None, "failure_codes": []}

    def refuse(reason, code=C.CORE_PLACEMENT_PLAN_INVALID):
        plan.update({"refused": True, "refusal_reason": reason})
        if code not in plan["failure_codes"]:
            plan["failure_codes"].append(code)
        return plan

    if not isinstance(terrain, dict):
        return refuse("terrain spec must be an object")
    for f in ("terrain_id", "asset_path", "resolution", "size_cm",
              "height_cm", "seed"):
        if terrain.get(f) is None:
            return refuse("terrain spec is missing required field {!r}; "
                          "WorldForge will not choose a world's scale, "
                          "roughness or seed for it".format(f))

    res = terrain["resolution"]
    if not isinstance(res, int) or not (1 <= res <= MAX_RESOLUTION):
        return refuse("resolution must be an integer in 1..{} (got {!r}); a "
                      "larger grid is refused rather than silently costing "
                      "minutes".format(MAX_RESOLUTION, res))
    for f in ("size_cm", "height_cm"):
        v = terrain[f]
        if not (isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) and v > 0):
            return refuse("{} must be a positive finite number (got {!r})"
                          .format(f, v))
    if not isinstance(terrain["seed"], int):
        return refuse("seed must be an integer so the terrain is reproducible "
                      "(got {!r})".format(terrain["seed"]))

    octaves = terrain.get("octaves", 4)
    lacunarity = terrain.get("lacunarity", 2.0)
    gain = terrain.get("gain", 0.5)
    frequency = terrain.get("frequency", 4.0)
    if not isinstance(octaves, int) or not (1 <= octaves <= 12):
        return refuse("octaves must be an integer in 1..12 (got {!r})".format(
            octaves))

    size = float(terrain["size_cm"])
    height = float(terrain["height_cm"])
    hf = heightfield(res, int(terrain["seed"]), octaves, float(lacunarity),
                     float(gain), float(frequency))

    verts, half = [], size / 2.0
    for j in range(res + 1):
        for i in range(res + 1):
            x = -half + size * (i / float(res))
            y = -half + size * (j / float(res))
            z = hf[j][i] * height
            verts.append([round(x, _COORD_DECIMALS), round(y, _COORD_DECIMALS),
                          round(z, _COORD_DECIMALS)])

    tris = []
    stride = res + 1
    for j in range(res):
        for i in range(res):
            a = j * stride + i
            b = a + 1
            c = a + stride
            d = c + 1
            # Consistent winding across the whole sheet; a flipped quad would
            # render as a hole from above and nothing would report it.
            tris.append([a, c, b])
            tris.append([b, c, d])

    zs = [v[2] for v in verts]
    plan.update({
        "asset_path": terrain["asset_path"],
        "resolution": res, "size_cm": size, "height_cm": height,
        "seed": int(terrain["seed"]), "octaves": octaves,
        "lacunarity": float(lacunarity), "gain": float(gain),
        "frequency": float(frequency),
        "vertices": verts, "triangles": tris,
        "vertex_count": len(verts), "triangle_count": len(tris),
        "observed_height_range_cm": [round(min(zs), _COORD_DECIMALS),
                                     round(max(zs), _COORD_DECIMALS)],
    })
    return plan


def validate_terrain_plan(plan, strict=False):
    code = C.CORE_PLACEMENT_PLAN_INVALID
    out = []
    is_obj = isinstance(plan, dict)
    out.append((_P + "plan_is_object", is_obj, "plan must be an object",
                None if is_obj else code))
    if not is_obj:
        return out
    if plan.get("refused"):
        out.append((_P + "refusal_names_a_code", bool(plan.get("failure_codes")),
                    "a refusal must name a code",
                    None if plan.get("failure_codes") else code))
        return out

    res = plan.get("resolution")
    want_v = (res + 1) ** 2
    want_t = 2 * res * res
    out.append((_P + "vertex_count_matches_grid", plan.get("vertex_count") == want_v,
                "a {0}x{0} grid needs {1} vertices, plan has {2}".format(
                    res, want_v, plan.get("vertex_count")),
                None if plan.get("vertex_count") == want_v else code))
    out.append((_P + "triangle_count_matches_grid",
                plan.get("triangle_count") == want_t,
                "a {0}x{0} grid needs {1} triangles, plan has {2}".format(
                    res, want_t, plan.get("triangle_count")),
                None if plan.get("triangle_count") == want_t else code))

    verts = plan.get("vertices") or []
    tris = plan.get("triangles") or []
    bad_idx = [t for t in tris
               if any((not isinstance(i, int)) or i < 0 or i >= len(verts)
                      for i in t)]
    out.append((_P + "every_triangle_indexes_a_real_vertex", not bad_idx,
                "{} triangle(s) reference a vertex that does not exist; a mesh "
                "built from these would be undefined geometry".format(
                    len(bad_idx)), None if not bad_idx else code))

    degenerate = [t for t in tris if len(set(t)) != 3]
    out.append((_P + "no_degenerate_triangles", not degenerate,
                "{} triangle(s) repeat a vertex and have zero area".format(
                    len(degenerate)), None if not degenerate else code))

    lo, hi = (plan.get("observed_height_range_cm") or [0, 0])[:2]
    within = 0 <= lo <= hi <= plan.get("height_cm", 0) + 1e-6
    out.append((_P + "heights_within_declared_range", within,
                "observed height range {}..{} must sit inside 0..{} -- the "
                "displacement is re-measured from the emitted vertices, not "
                "taken from the generator's word".format(
                    lo, hi, plan.get("height_cm")), None if within else code))
    return out


def declaration():
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_ID,
        capabilities=[PB.CAP_TERRAIN_SHAPING, PB.CAP_MESH_SYNTHESIS],
        requirements=[],
        side_effects=[PB._example_side_effect(
            effect_id="eff_terrain_spec_only",
            effect_kind=PB.EFFECT_EVIDENCE_ONLY,
            scope="evidence.terrain_mesh_plan",
            reversible=True,
            detail="computes a heightfield and emits a mesh synthesis spec; it "
                   "creates no asset and touches no world")],
        determinism=PB.DET_SEEDED,
        rollback=PB.ROLLBACK_NONE,
        outputs=["terrain_mesh_plan"],
        evidence=["terrain_mesh_plan"],
        limitations=[
            PB._example_limitation(
                limitation_id="lim_displaced_grid_only",
                limitation_kind="fidelity",
                detail="produces a displaced grid. No erosion, no biome-driven "
                       "material blending, no LOD generation -- real parts of "
                       "terrain production that this does not do"),
            PB._example_limitation(
                limitation_id="lim_resolution_cap",
                limitation_kind="scale",
                detail="resolution is capped at {}; a larger grid is refused "
                       "rather than silently costing minutes".format(
                           MAX_RESOLUTION)),
        ],
        description="deterministic fBm heightfield as a static mesh synthesis "
                    "spec")
    d["determinism_evidence"] = [
        "no RNG: lattice values are a blake2b hash of (x, y, seed), so a height "
        "depends on its coordinate alone and no traversal order can change it",
        "coordinates rounded to {} decimals".format(_COORD_DECIMALS),
        "pipeline/test_terrain_mesh_provider.py re-plans and compares canonical "
        "JSON, and asserts a different seed produces different terrain",
    ]
    return d


def canonical(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--terrain-id", required=True)
    ap.add_argument("--asset-path", required=True)
    ap.add_argument("--resolution", type=int, required=True)
    ap.add_argument("--size-cm", type=float, required=True)
    ap.add_argument("--height-cm", type=float, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--octaves", type=int, default=4)
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    plan = plan_terrain_mesh({
        "terrain_id": args.terrain_id, "asset_path": args.asset_path,
        "resolution": args.resolution, "size_cm": args.size_cm,
        "height_cm": args.height_cm, "seed": args.seed,
        "octaves": args.octaves})
    bad = [c[0] for c in validate_terrain_plan(plan, strict=True) if not c[1]]
    print("terrain mesh -- {}".format(plan.get("terrain_id")))
    print("  refused : {}".format(plan["refused"]))
    if plan["refused"]:
        print("  reason  : {}".format(plan["refusal_reason"][:220])); return 1
    print("  grid    : {0}x{0}  vertices={1}  triangles={2}".format(
        plan["resolution"], plan["vertex_count"], plan["triangle_count"]))
    print("  heights : {}..{} cm of a declared {}".format(
        *plan["observed_height_range_cm"], plan["height_cm"]))
    print("  validator: {}".format(bad or "clean"))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2, sort_keys=True)
        print("  spec -> {}".format(args.out))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
