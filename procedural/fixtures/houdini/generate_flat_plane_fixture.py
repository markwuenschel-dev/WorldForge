#!/usr/bin/env hython
"""generate_flat_plane_fixture.py — Houdini-generated support-grid TEST INPUT.

WHAT THIS IS
------------
The simplest possible support-grid case: one flat, level, infinite-relative-to-
the-grid plane. Houdini builds the geometry and performs the ground and head
ray casts; the resulting RAW OBSERVATIONS are handed to the repo's own semantic
authority, ``tools/pipeline/support_grid_canonical.py``, which derives the
expected support classes, edges, and counts.

WHAT THIS IS NOT
----------------
**TEST INPUT ONLY.** Nothing here is acceptance evidence and nothing here may be
wired into a shield, gate, or acceptance path. Houdini is not an authority on
WorldForge report truth; it is a geometry source that lets a support-grid test
have a world whose right answer is known in advance.

The support mathematics is NOT re-implemented here. This script only observes
(Houdini) and then calls ``derive_grid`` (canonical authority). If the two ever
need to disagree, that is a contract change, not an edit to this file.

Run:
    & "D:\\Side Effects Software\\Houdini 21.0.729\\bin\\hython.exe" \\
        procedural/fixtures/houdini/generate_flat_plane_fixture.py

Writes: procedural/fixtures/houdini/flat_plane_v1.json
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import hou  # noqa: E402  (Houdini only; this script is hython-only by design)

import support_grid_canonical as SG  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent / "flat_plane_v1.json"

FIXTURE_ID = "houdini_flat_plane"
FIXTURE_VERSION = "1.0.0"
SCHEMA_ID = "worldforge.houdini.support_fixture/1"

# --------------------------------------------------------------------------- #
# Declared geometry + survey request. Every number here is an INPUT; nothing in
# this block is derived.
# --------------------------------------------------------------------------- #
PLANE_SIZE_CM = 1000.0          # square plane edge length, centred on origin
PLANE_ROWS = 2                  # 2x2 points -> one quad; a plane needs no tessellation
PLANE_COLS = 2
PLANE_Z_CM = 0.0                # the plane sits exactly on the world XY plane
GRID_ORIENT_XY = 0              # Grid SOP `orient`: 0 = XY plane, normal +Z

ANCHOR_XYZ = (0.0, 0.0, 0.0)    # survey anchor (a_x, a_y, a_z)
RADIUS_CM = 100.0               # HALF-EXTENT of the axis-aligned square region
STEP_CM = 50.0                  # sample spacing  ->  k = floor(100/50) = 2, N = 25

# Trace windows, contract §2.1. Read from the canonical tolerance declaration
# where one exists; the ground window offsets have no canonical Python symbol and
# are quoted from the contract table with their C++ source cited in the manifest.
GROUND_START_DZ_CM = 1000.0     # SceneSurvey.cpp:117  a_z + 1000
GROUND_END_DZ_CM = -3000.0      # SceneSurvey.cpp:117  a_z - 3000

#: Decimal places every emitted float is rounded to. Declared so the content
#: hash is stable across runs and machines rather than carrying raycast noise.
ROUND_DP = 9


def r(x):
    """Round a float to the declared quantum; keep -0.0 from appearing."""
    v = round(float(x), ROUND_DP)
    return 0.0 if v == 0.0 else v


def rvec(v):
    return [r(v[0]), r(v[1]), r(v[2])]


# --------------------------------------------------------------------------- #
# Houdini: build the plane
# --------------------------------------------------------------------------- #
def build_plane():
    """Create the flat plane in Houdini, authored directly in the Unreal frame.

    The Grid SOP is set to the XY plane so the plane lies in world XY at fixed
    Z, and no axis conversion is applied anywhere in this script: Houdini's raw
    numbers ARE the Unreal-convention numbers. Houdini's own default (ZX plane,
    +Y up) is deliberately not used, because a conversion applied here would be
    a second place the fixture could be wrong.

    A Grid SOP at ``orient=0`` winds so that its geometric normal is **-Z** —
    i.e. it is a downward-facing surface, which no character can stand on.
    ``hou.Geometry.intersect`` returns the true geometric normal and does NOT
    flip it toward the ray, so that -Z would propagate into the observation and
    the canonical authority would (correctly) classify all 25 cells ``blocked``.

    The fix is a Reverse SOP: the plane is genuinely authored FACING UP. This is
    deliberately a change to the geometry, not a sign flip applied to the
    observed normal. Negating a measured normal in the observation path is the
    exact category of hidden per-fixture conversion that makes a fixture agree
    with an implementation for the wrong reason.
    """
    geo_node = hou.node("/obj").createNode("geo", "wf_flat_plane")
    grid = geo_node.createNode("grid", "wf_plane")
    grid.parm("orient").set(GRID_ORIENT_XY)
    grid.parm("sizex").set(PLANE_SIZE_CM)
    grid.parm("sizey").set(PLANE_SIZE_CM)
    grid.parm("rows").set(PLANE_ROWS)
    grid.parm("cols").set(PLANE_COLS)
    grid.parm("tz").set(PLANE_Z_CM)

    up = geo_node.createNode("reverse", "wf_plane_face_up")
    up.setFirstInput(grid)
    up.setDisplayFlag(True)

    geometry = up.geometry()

    # Assert the authored surface really faces up. If a future Houdini build
    # changes the Grid SOP winding, this fixture must FAIL to generate rather
    # than quietly emit a plane that classifies as `blocked`.
    prim_n = tuple(geometry.prims()[0].normal())
    if not (abs(prim_n[0]) < 1e-6 and abs(prim_n[1]) < 1e-6
            and prim_n[2] > 0.999999):
        raise RuntimeError(
            "authored plane normal is {!r}, expected +Z. The flat-plane fixture "
            "requires an upward-facing surface; refusing to emit a manifest "
            "whose geometry does not match its own description.".format(prim_n))

    return up, geometry


def cast(geometry, origin, direction, max_hit):
    """One ray cast. Returns (prim, position, normal) with prim == -1 on a miss."""
    pos = hou.Vector3()
    nrm = hou.Vector3()
    uvw = hou.Vector3()
    prim = geometry.intersect(hou.Vector3(*origin), hou.Vector3(*direction),
                              pos, nrm, uvw, max_hit=max_hit)
    return prim, pos, nrm


# --------------------------------------------------------------------------- #
# Observe: one ground trace and (when warranted) one head trace per cell
# --------------------------------------------------------------------------- #
def observe(geometry):
    """Produce (raw_json_records, canonical RawCell list) for the whole grid.

    Trace geometry mirrors the support-grid contract §2.1: the ground trace is
    anchored to the grid CENTRE's Z for every column, not to each cell.
    """
    raw_json = []
    cells = []

    a_x, a_y, a_z = ANCHOR_XYZ
    g_start_z = a_z + GROUND_START_DZ_CM
    g_end_z = a_z + GROUND_END_DZ_CM
    g_len = g_start_z - g_end_z

    for (i, j, x, y) in SG.sample_points((a_x, a_y), RADIUS_CM, STEP_CM):
        g_start = (x, y, g_start_z)
        g_end = (x, y, g_end_z)
        prim, pos, nrm = cast(geometry, g_start, (0.0, 0.0, -1.0), g_len)

        if prim < 0:
            ground = SG.RawTrace(trace_start=g_start, trace_end=g_end, hit=False)
            g_json = {"trace_start": rvec(g_start), "trace_end": rvec(g_end),
                      "hit": False, "impact_point": None, "normal": None,
                      "prim": -1}
            head_json = None
            head = None
        else:
            impact = (pos[0], pos[1], pos[2])
            normal = (nrm[0], nrm[1], nrm[2])
            ground = SG.RawTrace(trace_start=g_start, trace_end=g_end, hit=True,
                                 impact_point=impact, normal=normal,
                                 actor_path="/Fixture/houdini_flat_plane",
                                 component_path="/Fixture/houdini_flat_plane.Plane")
            g_json = {"trace_start": rvec(g_start), "trace_end": rvec(g_end),
                      "hit": True, "impact_point": rvec(impact),
                      "normal": rvec(normal), "prim": int(prim),
                      "actor_path": "/Fixture/houdini_flat_plane",
                      "component_path": "/Fixture/houdini_flat_plane.Plane"}

            lo_z, hi_z = SG.head_trace_window(impact[2])
            h_start = (x, y, lo_z)
            h_end = (x, y, hi_z)
            h_prim, h_pos, h_nrm = cast(geometry, h_start, (0.0, 0.0, 1.0),
                                        hi_z - lo_z)
            if h_prim < 0:
                head = SG.RawTrace(trace_start=h_start, trace_end=h_end, hit=False)
                head_json = {"trace_start": rvec(h_start), "trace_end": rvec(h_end),
                             "hit": False, "impact_point": None, "normal": None,
                             "prim": -1}
            else:
                h_impact = (h_pos[0], h_pos[1], h_pos[2])
                h_normal = (h_nrm[0], h_nrm[1], h_nrm[2])
                head = SG.RawTrace(trace_start=h_start, trace_end=h_end, hit=True,
                                   impact_point=h_impact, normal=h_normal)
                head_json = {"trace_start": rvec(h_start), "trace_end": rvec(h_end),
                             "hit": True, "impact_point": rvec(h_impact),
                             "normal": rvec(h_normal), "prim": int(h_prim)}

        raw_json.append({"i": i, "j": j, "x": r(x), "y": r(y),
                         "ground": g_json, "head": head_json})
        cells.append(SG.RawCell(i=i, j=j, ground=ground, head=head))

    return raw_json, cells


# --------------------------------------------------------------------------- #
# Manifest assembly
# --------------------------------------------------------------------------- #
def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expectation_note(result, tol):
    """State the expected outcome AND why, from the live tau_n state.

    This is deliberately derived rather than written as a constant: the flat
    plane's resolved classes flip entirely on whether tau_n is declared
    (contract §5.2), and a hardcoded note would silently become a lie the moment
    the authority declares one — which is exactly what happened during this
    fixture's first authoring.
    """
    if result.tau_n_evaluated:
        return (
            "tau_n IS declared ({} deg), so the normal-discontinuity term was "
            "evaluated. On a perfectly flat plane no neighbour differs in "
            "support, height, or normal, so no edge term fires and every cell is "
            "PROVED a non-edge (edge=False) and resolves to 'valid_support'. "
            "This is the fully-determined flat-plane baseline."
            .format(tol.tau_n_deg))
    return (
        "tau_n is UNDECLARED, so the normal-discontinuity term is REFUSED "
        "(contract §5.2): a non-edge cannot be PROVED. Every supported cell with "
        "at least one on-grid neighbour therefore resolves fail-closed to "
        "'unknown' rather than 'valid_support'. A flat plane reporting entirely "
        "'unknown' is the contract's declared honest cost of an undeclared "
        "tau_n, not a fixture defect.")


def canonical_json(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def build_manifest():
    grid_node, geometry = build_plane()
    raw_json, cells = observe(geometry)

    result = SG.derive_grid(cells, (ANCHOR_XYZ[0], ANCHOR_XYZ[1]),
                            RADIUS_CM, STEP_CM,
                            sample_region_shape=SG.SHAPE_SQUARE)

    tol = SG.CONTRACT_TOLERANCES

    per_cell = []
    heights = []
    normals = []
    edge_cells = []
    indeterminate = []
    unsupported = []
    for c in result.cells:
        per_cell.append({
            "i": c.i, "j": c.j,
            "supported": c.supported,
            "pass1_class": c.pass1_class,
            "edge": c.edge,
            "edge_terms": list(c.edge_terms),
            "resolved_class": c.resolved_class,
            "reason": c.reason,
        })
        heights.append({"i": c.i, "j": c.j,
                        "z_cm": None if c.z is None else r(c.z)})
        normals.append({"i": c.i, "j": c.j,
                        "unit_normal": None if c.unit_normal is None
                        else rvec(c.unit_normal)})
        if c.edge is True:
            edge_cells.append([c.i, c.j])
        if c.edge is None and c.pass1_class == SG.CLS_VALID:
            indeterminate.append([c.i, c.j])
        if c.supported is False:
            unsupported.append([c.i, c.j])

    doc = {
        "schema": SCHEMA_ID,
        "fixture_id": FIXTURE_ID,
        "fixture_version": FIXTURE_VERSION,
        "role": "test_input_only",
        "role_note": (
            "TEST INPUT ONLY. Houdini is a geometry source, never acceptance "
            "evidence. This manifest must not be consumed by any shield, gate, "
            "or acceptance path."),
        "governing_contract": "docs/contracts/v2_6_support_grid_contract.md",
        "derivation_authority": "tools/pipeline/support_grid_canonical.py",
        "derivation_note": (
            "The expected block is NOT hand-authored and NOT re-implemented "
            "here. Houdini produced the raw_observations; support_grid_canonical"
            ".derive_grid produced every expected value from them."),

        "generator": {
            "kind": "houdini_live",
            "script": "procedural/fixtures/houdini/generate_flat_plane_fixture.py",
            "hython": hou.getenv("HFS") + "/bin/hython",
            "houdini_version": hou.applicationVersionString(),
            "houdini_version_tuple": list(hou.applicationVersion()),
            "houdini_product": hou.applicationName(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "authority_module_sha256": sha256_file(
                REPO_ROOT / "tools" / "pipeline" / "support_grid_canonical.py"),
            "float_round_decimals": ROUND_DP,
        },

        "coordinate_frame": {
            "name": "unreal_world_cm",
            "units": "centimetres",
            "up_axis": "+Z",
            "handedness": "left_handed",
            "authored_natively": True,
            "axis_conversion_applied": "none",
            "note": (
                "The Grid SOP is set to orient=0 (XY plane) so Houdini authors "
                "the plane with a +Z normal in centimetre-scale units. Houdini's "
                "default ZX/+Y-up orientation is deliberately unused so that no "
                "axis conversion exists anywhere in this fixture."),
            "grid_alignment": "axis_aligned_to_world_XY, not rotated to subject yaw",
        },

        "geometry": {
            "primitive": "flat_plane",
            "source": "houdini_grid_sop -> reverse_sop",
            "facing": "+Z",
            "facing_note": (
                "A Grid SOP at orient=0 winds -Z (downward-facing). A Reverse "
                "SOP authors the plane genuinely facing up; the observed normal "
                "is never sign-flipped in the observation path. "
                "hou.Geometry.intersect returns the true geometric normal and "
                "does not orient it toward the ray (verified)."),
            "grid_sop_parms": {
                "orient": GRID_ORIENT_XY,
                "sizex": PLANE_SIZE_CM,
                "sizey": PLANE_SIZE_CM,
                "rows": PLANE_ROWS,
                "cols": PLANE_COLS,
                "tz": PLANE_Z_CM,
            },
            "plane_z_cm": PLANE_Z_CM,
            "extent_min_xy_cm": [-PLANE_SIZE_CM / 2.0, -PLANE_SIZE_CM / 2.0],
            "extent_max_xy_cm": [PLANE_SIZE_CM / 2.0, PLANE_SIZE_CM / 2.0],
            "point_count": len(geometry.points()),
            "prim_count": len(geometry.prims()),
            "slope_deg": 0.0,
            "covers_entire_sample_region": True,
        },

        "survey_request": {
            "anchor_xyz_cm": list(ANCHOR_XYZ),
            "radius_cm": RADIUS_CM,
            "radius_semantics": "half_extent",
            "step_cm": STEP_CM,
            "sample_region_shape": result.sample_region_shape,
        },

        "trace_setup": {
            "ground_start_z_cm": ANCHOR_XYZ[2] + GROUND_START_DZ_CM,
            "ground_end_z_cm": ANCHOR_XYZ[2] + GROUND_END_DZ_CM,
            "ground_anchored_to": "grid_centre_z",
            "head_window_cm_above_impact": [tol.head_clear_lo_cm,
                                            tol.head_clear_hi_cm],
            "contract_source": "v2_6_support_grid_contract.md §2.1 (SceneSurvey.cpp:117,147,148)",
        },

        "tolerances": {
            "max_slope_deg": tol.max_slope_deg,
            "cos_max_slope": tol.cos_max_slope,
            "max_step_h_cm": tol.max_step_h_cm,
            "tau_h_cm": tol.tau_h_cm,
            "head_clear_lo_cm": tol.head_clear_lo_cm,
            "head_clear_hi_cm": tol.head_clear_hi_cm,
            "unit_normal_tol": tol.unit_normal_tol,
            "tau_n_deg": tol.tau_n_deg,
            "tau_n_declared": tol.tau_n_declared,
            "source": "support_grid_canonical.CONTRACT_TOLERANCES",
        },

        "comparison_tolerances": {
            "position_abs_tol_cm": 1.0e-4,
            "normal_abs_tol": 1.0e-6,
            "note": ("A consumer comparing its own collector against this "
                     "fixture compares positions and normals within these; "
                     "classes, counts, and index sets compare exactly."),
        },

        "raw_observations": raw_json,

        "expected": {
            "k": result.k,
            "nominal_sample_count": result.nominal_count,
            "observed_sample_count": len(result.cells),
            "tau_n_evaluated": result.tau_n_evaluated,
            "class_counts": result.counts(),
            "support_classes": per_cell,
            "heights": heights,
            "normals": normals,
            "edge_cells": edge_cells,
            "indeterminate_edge_cells": indeterminate,
            "unsupported_regions": unsupported,
            "unsupported_regions_note": (
                "Empty by construction: the plane covers the entire sample "
                "region, so no ground trace misses."),
            "expectation_note": expectation_note(result, tol),
            "expectation_depends_on_tau_n": True,
            "expectation_depends_on_tau_n_note": (
                "The resolved classes of this fixture are a function of whether "
                "tau_n is declared in the authority module, NOT of the geometry "
                "alone. generator.authority_module_sha256 pins which version of "
                "support_grid_canonical.py produced this expected block. If that "
                "hash does not match the authority a consumer is testing "
                "against, REGENERATE this fixture — do not reconcile by hand."),
        },

        "content_hash": {
            "algorithm": "sha256",
            "covers": ("canonical JSON of this whole document, sort_keys=True, "
                       "separators=(',',':'), with content_hash.value set to \"\""),
            "value": "",
        },
    }

    payload = canonical_json(doc)
    doc["content_hash"]["value"] = hashlib.sha256(
        payload.encode("utf-8")).hexdigest()
    return doc


def main():
    doc = build_manifest()
    OUT_PATH.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print("wrote {}".format(OUT_PATH))
    print("houdini      {}".format(doc["generator"]["houdini_version"]))
    print("k            {}".format(doc["expected"]["k"]))
    print("class_counts {}".format(doc["expected"]["class_counts"]))
    print("edge_cells   {}".format(doc["expected"]["edge_cells"]))
    print("unsupported  {}".format(doc["expected"]["unsupported_regions"]))
    print("content_hash {}".format(doc["content_hash"]["value"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
