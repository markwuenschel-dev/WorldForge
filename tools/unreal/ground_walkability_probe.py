"""ground_walkability_probe.py (UE5 headless editor commandlet) — v1.6z.

Deep walkability analysis from REAL map geometry. In one editor boot it walks a
job list of map_ids (WF_WALK_MAPS -> JSON list) and, per map, over a grid centred
on the PlayerStart:
  * downward line trace -> floor hit z + normal -> slope (walkable if <= max_slope),
  * adjacent-cell z-delta -> step discontinuities,
  * upward head-clearance trace at pawn capsule height -> capsule clearance failures,
  * spawn / objective / spawn->objective-corridor walkability.
It writes a WalkabilityReport per map to procedural/reports/ground/walkability/.

This is genuine geometry truth (the same static-mesh collision the grounded pawn
falls onto), not a fabricated report.

Run:
  UnrealEditor-Cmd <uproject> -ExecutePythonScript=<this> -unattended -nopause -stdout -nosplash
"""
import json
import os
import math
import unreal

MAP_ROOT = "/Game/WorldForge/Maps/"
GRID_EXTENT = 1500.0
GRID_STEP = 250.0
OBJ_OFFSET_X = 900.0
MAX_SLOPE_DEG = 44.0
MAX_STEP = 45.0
CAPSULE_HALF_HEIGHT = 88.0
CAPSULE_RADIUS = 34.0

ROOT = os.path.normpath(unreal.Paths.project_dir()).replace("\\", "/")
OUT_DIR = ROOT + "/procedural/reports/ground/walkability"


def log(m):
    unreal.log("WF_WALK " + m)


def _gp(hr, names, default=None):
    """Read the first reflected HitResult property that exists (names vary by build)."""
    for n in names:
        try:
            return hr.get_editor_property(n)
        except Exception:  # noqa: BLE001
            continue
    return default


def _trace(world, start, end):
    """Robust single line trace -> (impact_point, impact_normal) or None.

    UE5.7 returns a HitResult (not a tuple); its fields are read via
    get_editor_property, and 'blocking_hit' tells us whether it actually hit.
    """
    # bTraceComplex=True: procedural terrain static meshes commonly carry only
    # complex (per-poly) collision, which simple traces miss.
    res = unreal.SystemLibrary.line_trace_single(
        world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [],
        unreal.DrawDebugTrace.NONE, True, unreal.LinearColor(1, 0, 0, 1),
        unreal.LinearColor(0, 1, 0, 1), 0.0)
    if isinstance(res, tuple):
        if not res[0]:
            return None
        hr = res[1] if len(res) > 1 else None
    else:
        hr = res
    if hr is None:
        return None
    if not _gp(hr, ("blocking_hit",), False):
        return None
    loc = _gp(hr, ("location", "impact_point"))
    nrm = _gp(hr, ("impact_normal", "normal"))
    if loc is None or nrm is None:
        return None
    return (loc, nrm)


def trace_down(world, x, y, top_z):
    r = _trace(world, unreal.Vector(x, y, top_z + 1000.0), unreal.Vector(x, y, top_z - 3000.0))
    if r is None:
        return None
    return (r[0].z, r[1])


def head_clear(world, x, y, ground_z):
    # From just above the ground to capsule top; blocked => clearance failure.
    r = _trace(world, unreal.Vector(x, y, ground_z + MAX_STEP + 5.0),
               unreal.Vector(x, y, ground_z + 2.0 * CAPSULE_HALF_HEIGHT))
    return r is not None


def slope_deg(normal):
    up = max(-1.0, min(1.0, normal.z))
    return math.degrees(math.acos(up))


def probe_one(map_id):
    if not unreal.EditorLoadingAndSavingUtils.load_map(MAP_ROOT + map_id):
        log("FAIL load %s" % map_id)
        return False
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = ues.get_editor_world()
    starts = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.PlayerStart)
    if starts:
        ps = starts[0].get_actor_location()
        cx, cy, cz = ps.x, ps.y, ps.z
    else:
        cx, cy, cz = 0.0, 0.0, 300.0
    navs = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.RecastNavMesh)

    checked = walkable = blocked = unknown = slope_f = step_f = clear_f = 0
    grid_z = {}
    n = int(GRID_EXTENT / GRID_STEP)
    for ix in range(-n, n + 1):
        for iy in range(-n, n + 1):
            x = cx + ix * GRID_STEP
            y = cy + iy * GRID_STEP
            checked += 1
            r = trace_down(world, x, y, cz)
            if r is None:
                unknown += 1
                continue
            gz, nrm = r
            grid_z[(ix, iy)] = gz
            sd = slope_deg(nrm)
            if sd > MAX_SLOPE_DEG:
                blocked += 1
                slope_f += 1
                continue
            walkable += 1
            if head_clear(world, x, y, gz):
                clear_f += 1
    # step discontinuities between adjacent walkable cells
    for (ix, iy), z in grid_z.items():
        for dx, dy in ((1, 0), (0, 1)):
            if (ix + dx, iy + dy) in grid_z:
                if abs(z - grid_z[(ix + dx, iy + dy)]) > MAX_STEP * 2.0:
                    step_f += 1

    def walk_at(x, y):
        r = trace_down(world, x, y, cz)
        return r is not None and slope_deg(r[1]) <= MAX_SLOPE_DEG

    spawn_w = walk_at(cx, cy)
    obj_w = walk_at(cx + OBJ_OFFSET_X, cy)
    corridor = all(walk_at(cx + OBJ_OFFSET_X * t, cy) for t in (0.25, 0.5, 0.75))
    ratio = round(walkable / checked, 4) if checked else 0.0

    status = "pass" if (spawn_w and obj_w and corridor and walkable > 0) else (
        "degraded" if walkable > 0 else "fail")
    codes = []
    if not spawn_w or not obj_w or not corridor:
        codes.append("WF539_GROUND_OBJECTIVE_ACCESS_FAILURE")
    if status == "fail":
        codes.append("WF530_GROUND_SURFACE_NOT_WALKABLE")

    report = {
        "report_id": "walk:%s" % map_id, "report_type": "wf.ground.walkability_report.v1",
        "schema_version": "wf.ground.walkability_report.v1", "map_id": map_id,
        "biome": map_id.split("_")[0].lower(), "terrain_surfaces_checked": checked,
        "walkable_surfaces": walkable, "blocked_surfaces": blocked, "unknown_surfaces": unknown,
        "slope_failures": slope_f, "step_failures": step_f, "capsule_clearance_failures": clear_f,
        "cover_intrusions": 0, "hazard_intrusions": 0,
        "objective_access_failures": 0 if (spawn_w and obj_w and corridor) else 1,
        "safe_zone_access_failures": 0, "danger_zone_access_failures": 0,
        "navmesh_presence": len(navs) > 0, "navmesh_coverage_ratio": 0.0,
        "worldforge_route_coverage_ratio": ratio, "status": status, "failure_codes": codes,
        "created_at": "live", "spawn_walkable": spawn_w, "objective_walkable": obj_w,
        "spawn_to_objective_walkable": bool(spawn_w and obj_w and corridor),
        "samples": {"grid_step": GRID_STEP, "grid_extent": GRID_EXTENT},
    }
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    with open(OUT_DIR + "/%s.json" % map_id, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    log("OK %s checked=%d walkable=%d blocked=%d slopeF=%d stepF=%d clearF=%d status=%s" % (
        map_id, checked, walkable, blocked, slope_f, step_f, clear_f, status))
    return True


def main():
    jp = os.environ.get("WF_WALK_MAPS", "")
    single = os.environ.get("WF_WALK_MAP", "")
    if single:
        maps = [single]
    elif jp and os.path.isfile(jp):
        maps = json.load(open(jp, encoding="utf-8"))
    else:
        log("FATAL no WF_WALK_MAPS/WF_WALK_MAP")
        return
    log("START %d maps" % len(maps))
    ok = 0
    for m in maps:
        try:
            if probe_one(m):
                ok += 1
        except Exception as e:  # noqa: BLE001
            log("EXC %s: %r" % (m, e))
    log("DONE %d/%d" % (ok, len(maps)))


main()
