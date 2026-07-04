#!/usr/bin/env python3
"""create_visual_dressing.py — WorldForge v1.3.5 VisualFidelity dressing generator (Agent 2 lane).

Materializes the surface + world-dressing layer for every mission map: for each of
the 60 mission_loop_world maps this composes a dressing PLAN that binds a
biome-compatible ground surface and cliff/rock surface (a real Megascans external
asset when one exists for the biome, otherwise a declared generated fallback from
the v1.2 mesh catalog) and places the mission's mesh dependencies as world
dressing NEAR the primary POI and ALONG the required route — always OFFSET off the
route so fidelity never breaks playability (brief Pillar 6: readability).

Ownership is source-safe (brief §3 / v1.2 model): the dressing plan and generated
fallbacks are generated_owned; every referenced Megascans asset stays
third_party_owned and is never rewritten to generated.

Deterministic; no UE. Writes procedural/generated/visual/dressing/<slice_id>.json,
updates the visual catalog (surface_status/dressing_status -> materialized), and
emits a report.

Usage:
    python tools/pipeline/create_visual_dressing.py --pack mission_loop_world
    STRICT=1 python tools/pipeline/create_visual_dressing.py --pack mission_loop_world --strict
"""

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_catalog import load_visual_catalog, save_visual_catalog, upsert_map
from mission_catalog import load_mission_catalog
import mission_contract as MC
from mesh_catalog import load_mesh_catalog
from external_asset_contract import load_external_catalog
from report_meta import build_meta, hash_obj, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GENERATOR = "create_visual_dressing"
GENERATOR_VERSION = "1.3.5"

# The scanned/classified visual asset catalog Agent 1 writes concurrently; we
# fall back to the external + mesh catalogs directly when it is absent.
VISUAL_ASSET_CATALOG_PATH = REPO_ROOT / VC.VISUAL_ASSET_CATALOG_REL

# --- Readability geometry (Pillar 6) -----------------------------------------
# Validator clearance threshold is > 200 cm from every waypoint + start; the
# generator targets a much larger clearance so there is never a boundary case.
GEN_SAFE_CLEARANCE_CM = 450.0
POI_OFFSET_BASE_CM = 650.0
OFFSET_STEP_CM = 200.0
OFFSET_CAP_CM = 6000.0
# A dressing asset within this of the POI counts as "near the primary POI".
NEAR_POI_MAX_CM = 4000.0
# The validator's hard clearance floor: dressing must be strictly > this from
# every route waypoint and the player start.
CLEARANCE_MIN_CM = 200.0

# mesh_family / external asset_type -> dressing role (brief: landmark/cover/rock/debris)
MESH_FAMILY_ROLE = {
    "rock_outcrop": "rock",
    "industrial_debris": "debris",
    "encounter_cover": "cover",
    "biome_landmark": "landmark",
    "traversal_marker": "landmark",
    "resource_node": "landmark",
}
EXTERNAL_TYPE_ROLE = {
    "rock": "rock", "debris": "debris", "vegetation": "landmark", "surface": "debris",
}

# Preferred generated-fallback mesh families by surface class (else any biome match).
GROUND_FALLBACK_FAMILIES = ("biome_landmark", "traversal_marker", "resource_node")
CLIFF_FALLBACK_FAMILIES = ("rock_outcrop",)


def _source_hash(*parts):
    return "sha256:" + hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# geometry helpers (2D navigation — no UE)
# ---------------------------------------------------------------------------
def _dist2d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _midpoint(a, b):
    return [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0 if len(a) > 2 and len(b) > 2 else 0.0]


def _unit_perp(a, b):
    """Unit vector perpendicular (in XY) to the direction a->b. Defaults to +X
    when the segment is degenerate."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-6:
        return (1.0, 0.0)
    return (-dy / length, dx / length)


def _min_clearance(pos, waypoints, start):
    pts = list(waypoints) + [start]
    return min(_dist2d(pos, p) for p in pts) if pts else float("inf")


def _place_offset(anchor, perp, side, base_mag, waypoints, start):
    """Offset `anchor` perpendicular to the route by an increasing magnitude until
    it clears every waypoint + start by GEN_SAFE_CLEARANCE_CM. Monotonic push, so
    it always terminates well before the cap on these map scales."""
    mag = base_mag
    while mag <= OFFSET_CAP_CM:
        pos = [round(anchor[0] + perp[0] * side * mag, 2),
               round(anchor[1] + perp[1] * side * mag, 2),
               round(anchor[2] if len(anchor) > 2 else 0.0, 2)]
        if _min_clearance(pos, waypoints, start) > GEN_SAFE_CLEARANCE_CM:
            return pos
        mag += OFFSET_STEP_CM
    # Degenerate fallback (should never trigger at these scales): last computed.
    return pos


# ---------------------------------------------------------------------------
# surface resolution
# ---------------------------------------------------------------------------
def _external_surface(ext_catalog, biome, asset_type):
    """First biome-compatible external asset of the given asset_type (deterministic)."""
    for aid, e in sorted((ext_catalog.get("assets") or {}).items()):
        if e.get("asset_type") != asset_type:
            continue
        if biome in (e.get("biome_compatibility") or []):
            return aid, e
    return None, None


def _mesh_fallback(mesh_catalog, biome, preferred_families):
    """A biome-compatible generated mesh asset to serve as a fallback surface
    marker. Prefers the given families, else any biome-compatible mesh."""
    assets = mesh_catalog.get("assets") or {}
    for aid, e in sorted(assets.items()):
        if e.get("mesh_family") in preferred_families and biome in (e.get("biome_compatibility") or []):
            return aid, e
    for aid, e in sorted(assets.items()):
        if biome in (e.get("biome_compatibility") or []):
            return aid, e
    return None, None


def _resolve_surface(surface_class, external_type, fallback_families,
                     biome, ext_catalog, mesh_catalog):
    """Resolve a ground/cliff surface: prefer a real biome-compatible Megascans
    external asset (third_party_owned); else a declared generated fallback from
    the mesh catalog (generated_owned)."""
    aid, e = _external_surface(ext_catalog, biome, external_type)
    if aid is not None:
        return {
            "asset_class": surface_class,
            "asset_id": aid,
            "external_asset_id": aid,
            "source": "external",
            "ownership_class": VC.OWNERSHIP_THIRD_PARTY,
            "asset_type": e.get("asset_type"),
            "biome_compatibility": list(e.get("biome_compatibility") or []),
        }
    aid, e = _mesh_fallback(mesh_catalog, biome, fallback_families)
    if aid is not None:
        return {
            "asset_class": surface_class,
            "asset_id": aid,
            "external_asset_id": None,
            "source": "generated_fallback",
            "ownership_class": VC.OWNERSHIP_GENERATED,
            "mesh_family": e.get("mesh_family"),
            "biome_compatibility": list(e.get("biome_compatibility") or []),
        }
    # Last-resort marker (no real asset for the biome at all).
    return {
        "asset_class": surface_class,
        "asset_id": "generated_surface_{}_{}".format(surface_class, biome),
        "external_asset_id": None,
        "source": "generated_marker",
        "ownership_class": VC.OWNERSHIP_GENERATED,
        "biome_compatibility": [biome],
    }


# ---------------------------------------------------------------------------
# dressing placement
# ---------------------------------------------------------------------------
def _role_for(aid, source, mesh_catalog, ext_catalog):
    if source == "mesh":
        fam = ((mesh_catalog.get("assets") or {}).get(aid) or {}).get("mesh_family")
        return MESH_FAMILY_ROLE.get(fam, "landmark")
    e = (ext_catalog.get("assets") or {}).get(aid) or {}
    return EXTERNAL_TYPE_ROLE.get(e.get("asset_type"), "landmark")


def _build_dressing_assets(mission, mesh_catalog, ext_catalog):
    """Place mesh dependencies + optional Megascans dressing near the POI and along
    the route, offset perpendicular so nothing lands on the route or player start."""
    start = mission["start_anchor"]["world_position"]
    poi = mission["primary_poi"]["gameplay_anchor"]
    waypoints = (mission.get("required_route") or {}).get("waypoints") or [start, poi]
    md = mission.get("mesh_dependencies") or {}

    sources = [(aid, "mesh") for aid in (md.get("resolved_mesh_assets") or [])]
    meg = md.get("megascans_dressing")
    if meg:
        sources.append((meg, "external"))

    # Route segment midpoints = the "along route" anchors.
    seg_mids = [(_midpoint(waypoints[i], waypoints[i + 1]),
                 _unit_perp(waypoints[i], waypoints[i + 1]), i)
                for i in range(len(waypoints) - 1)]
    # Perp of the final approach segment (for the POI-anchored landmark).
    poi_perp = _unit_perp(waypoints[-2], waypoints[-1]) if len(waypoints) >= 2 else (1.0, 0.0)

    dressing = []
    for j, (aid, source) in enumerate(sources):
        ownership = VC.OWNERSHIP_GENERATED if source == "mesh" else VC.OWNERSHIP_THIRD_PARTY
        side = 1.0 if (j % 2 == 0) else -1.0
        base = POI_OFFSET_BASE_CM + j * OFFSET_STEP_CM
        if j == 0 or not seg_mids:
            # anchor at the primary POI so at least one dressing asset is near it.
            anchor, perp, near_node = poi, poi_perp, MC.NODE_PRIMARY_POI
        else:
            mid, perp, seg_i = seg_mids[(j - 1) % len(seg_mids)]
            anchor, near_node = mid, "route_segment_{}".format(seg_i)
        pos = _place_offset(anchor, perp, side, base, waypoints, start)
        dressing.append({
            "asset_id": aid,
            "ownership_class": ownership,
            "source": "mesh_catalog" if source == "mesh" else "external_catalog",
            "world_position": pos,
            "role": _role_for(aid, source, mesh_catalog, ext_catalog),
            "near_node": near_node,
        })
    return dressing, start, poi, waypoints


# ---------------------------------------------------------------------------
# per-map plan
# ---------------------------------------------------------------------------
def build_dressing_plan(mission, biome, mesh_catalog, ext_catalog):
    slice_id = mission["source_map"]["slice_id"]
    ground = _resolve_surface("ground_surface", "surface", GROUND_FALLBACK_FAMILIES,
                              biome, ext_catalog, mesh_catalog)
    cliff = _resolve_surface("cliff_surface", "rock", CLIFF_FALLBACK_FAMILIES,
                             biome, ext_catalog, mesh_catalog)
    dressing, start, poi, waypoints = _build_dressing_assets(mission, mesh_catalog, ext_catalog)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    plan = {
        "schema_version": VC.VISUAL_SCHEMA_VERSION,
        "slice_id": slice_id,
        "biome": biome,
        "world_pack_id": mission["source_map"].get("world_pack_id"),
        "mission_id": mission["mission_id"],
        "ground_surface": ground,
        "cliff_surface": cliff,
        "dressing_assets": dressing,
        "ownership_class": VC.OWNERSHIP_GENERATED,
        "provenance": {
            "generator": GENERATOR, "generator_version": GENERATOR_VERSION,
            "generated_at_utc": now,
            "source_hash": _source_hash(slice_id, biome, mission["mission_id"]),
        },
    }
    return plan, (start, poi, waypoints)


def write_plan(plan, repo_root):
    out_dir = Path(repo_root) / VC.DRESSING_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (plan["slice_id"] + ".json")
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    import os
    os.replace(str(tmp), str(path))
    return path


def _self_check_offset(dressing, start, waypoints):
    """Generator-side guarantee: no dressing asset lands on the route/start."""
    for d in dressing:
        if _min_clearance(d["world_position"], waypoints, start) <= CLEARANCE_MIN_CM:
            return False, d["asset_id"]
    return True, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.3.5 visual dressing generator.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mission_catalog = load_mission_catalog(REPO_ROOT)
    mesh_catalog = load_mesh_catalog(REPO_ROOT)
    ext_catalog = load_external_catalog(REPO_ROOT)
    visual_catalog = load_visual_catalog(REPO_ROOT)

    mids = sorted((mission_catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")
        rep.finalize()
        rep.set_meta(build_meta(command="create-visual-dressing", pack=args.pack,
                                strict=strict, status=rep.status, record_count=0))
        rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "create_visual_dressing",
                  "create_visual_dressing_report.json")
        rep.print_summary("create-visual-dressing")
        sys.exit(rep.exit_code)

    dressed, offset_ok = [], True
    for mid in mids:
        mission, err = MC.load_mission(mid)
        if mission is None:
            rep.check("{}::mission_loads".format(mid), False, err,
                      code=FailureCode.WORLD_DRESSING_FAILURE)
            continue
        slice_id = mission["source_map"]["slice_id"]
        biome = mission["biome_family"]

        plan, (start, poi, waypoints) = build_dressing_plan(mission, biome, mesh_catalog, ext_catalog)
        write_plan(plan, REPO_ROOT)

        # readability self-guarantee (this is the intended design).
        ok, bad = _self_check_offset(plan["dressing_assets"], start, waypoints)
        if not ok:
            offset_ok = False
            rep.check("{}::dressing_offset_off_route".format(slice_id), False,
                      "asset {} too close to route/start".format(bad),
                      code=FailureCode.WORLD_DRESSING_FAILURE)

        # per-map materialization checks.
        rep.check("{}::surfaces_bound".format(slice_id),
                  bool(plan["ground_surface"].get("asset_id")) and bool(plan["cliff_surface"].get("asset_id")),
                  "ground={} cliff={}".format(plan["ground_surface"].get("asset_id"),
                                              plan["cliff_surface"].get("asset_id")),
                  code=FailureCode.SURFACE_MATERIALIZATION_FAILURE)
        rep.check("{}::dressing_non_empty".format(slice_id),
                  len(plan["dressing_assets"]) >= 1,
                  "{} dressing assets".format(len(plan["dressing_assets"])),
                  code=FailureCode.WORLD_DRESSING_FAILURE)

        # update the visual catalog entry, preserving existing fields.
        entry = dict((visual_catalog.get("maps") or {}).get(slice_id) or {})
        entry["slice_id"] = slice_id
        entry.setdefault("biome", biome)
        entry["surface_status"] = "materialized"
        entry["dressing_status"] = "materialized"
        entry["dressing_path"] = (Path(VC.DRESSING_REL) / (slice_id + ".json")).as_posix()
        entry.setdefault("ownership_class", VC.OWNERSHIP_GENERATED)
        visual_catalog = upsert_map(visual_catalog, entry)
        dressed.append(slice_id)

    save_visual_catalog(REPO_ROOT, visual_catalog)

    rep.check("all_60_maps_dressed", len(dressed) == 60,
              "dressed {} maps".format(len(dressed)),
              code=FailureCode.WORLD_DRESSING_FAILURE)
    rep.check("dressing_offset_off_routes", offset_ok,
              "every dressing asset offset off route + start (readability preserved)",
              code=FailureCode.VISUAL_READABILITY_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="create-visual-dressing", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(dressed),
                            output_manifest_hash=hash_obj(sorted(dressed))))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "create_visual_dressing",
              "create_visual_dressing_report.json")
    rep.print_summary("create-visual-dressing")
    print("[create-visual-dressing] dressed {} maps (offset off routes: {})".format(
        len(dressed), offset_ok))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
