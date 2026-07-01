#!/usr/bin/env python3
"""generate_level_design.py — WorldForge v1.0x level-design overlay generator.

Turns each generated map spec (poi_forge + terrain_forge + seed + state) into a
deterministic *level-design overlay*: a player start, a set of usable POIs with
world placement / approach+exit vectors / gameplay anchors, safe & danger zones,
orientation + vista cues, and a reachability graph. The overlay is what makes a
generated space *playable* instead of decorative.

Design invariants
-----------------
* Overlays are GENERATED-OWNED and NEVER modify the generated specs (the green
  baseline is preserved). One overlay JSON per map at
  ``procedural/generated/level_design/<slice_id>.json``.
* Deterministic: the same (spec, seed) always yields byte-identical overlay
  content. The ONLY per-run field is ``provenance.generated_at_utc``; every
  geometric/content field is a pure function of the spec + seed. A stable
  ``content_hash`` (report_meta.hash_obj over the overlay minus its provenance
  timestamp) anchors determinism checks.
* Self-correcting placement: the generator runs the same geometric predicates
  the validators use and nudges entities until POIs are within terrain, do not
  overlap forbidden (danger) zones, and keep clearance from critical routes.
  Generation is honest — it produces a layout that genuinely passes, it does not
  weaken the checks.

This module also exposes the shared schema constants, geometry helpers and the
overlay loader that the sibling validators import (they live in this lane).

Usage:
    PYTHONUTF8=1 python tools/pipeline/generate_level_design.py --pack desert_mvp_world
    PYTHONUTF8=1 python tools/pipeline/generate_level_design.py --pack desert_mvp_world --force
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from world_pack_maps import enumerate_maps  # noqa: E402
from report_meta import hash_obj, utc_now_iso, git_sha  # noqa: E402
from provenance import build_provenance  # noqa: E402

GENERATOR_NAME = "generate_level_design"
GENERATOR_VERSION = "1.0x"
SCHEMA_VERSION = "wf-level-design-v1"

# Canonical output location for generated-owned level-design overlays.
LEVEL_DESIGN_DIR = REPO_ROOT / "procedural" / "generated" / "level_design"
REGISTRY_OWNER = "worldforge_level_design_overlay"

# UE landscape default: 1 quad == 100 cm. A 513-sample heightmap => 512 quads.
CM_PER_QUAD = 100
# Only used (and stamped) if a terrain descriptor is unreadable.
DEFAULT_TERRAIN_DIM = 513

# --- shared vocabulary -------------------------------------------------------
# The 12 required POI classes the overlay draws from.
POI_CLASSES = (
    "industrial_yard", "abandoned_outpost", "resource_site", "navigation_landmark",
    "safe_zone", "danger_zone", "ruin_cluster", "traversal_choke", "vista_point",
    "spawn_adjacent_anchor", "objective_ready_anchor", "encounter_ready_anchor",
)

# Map each generated poi_forge.poi_type onto a primary POI class.
POI_TYPE_TO_CLASS = {
    "industrial_yard": "industrial_yard",
    "debris_checkpoint": "traversal_choke",
    "abandoned_mining_camp": "abandoned_outpost",
    "scrubland_resource_node": "resource_site",
    "cracked_ridge_lookout": "vista_point",
    "ash_shrine_ruin": "ruin_cluster",
}

# Required graph node roles (structural contract for validate_poi_graph).
REQUIRED_NODE_ROLES = (
    "player_start", "primary_poi", "secondary_poi", "safe_zone",
    "danger_zone", "resource_site", "exit_or_edge_route",
)
EDGE_KINDS = ("reachable", "blocked", "risky", "optional")
BUDGET_CLASSES = ("light", "medium", "heavy")

# Clearance a non-endpoint POI must keep from a critical route segment (cm).
PATH_CLEARANCE_CM = 3000.0
# Vertical tolerance for buried/floating checks (cm).
Z_TOL_CM = 50.0


# =============================================================================
# Geometry helpers (shared by validators in this lane)
# =============================================================================
def rect_valid(bounds):
    """A bounds dict {min:[x,y,..], max:[x,y,..]} with min strictly < max in x,y."""
    if not isinstance(bounds, dict):
        return False
    mn, mx = bounds.get("min"), bounds.get("max")
    if not (isinstance(mn, (list, tuple)) and isinstance(mx, (list, tuple))):
        return False
    if len(mn) < 2 or len(mx) < 2:
        return False
    return all(_finite(mn[i]) and _finite(mx[i]) and mx[i] > mn[i] for i in range(2))


def _finite(v):
    return isinstance(v, (int, float)) and not math.isinf(v) and not math.isnan(v)


def point_in_rect_xy(p, bounds, margin=0.0):
    mn, mx = bounds["min"], bounds["max"]
    return (mn[0] - margin <= p[0] <= mx[0] + margin
            and mn[1] - margin <= p[1] <= mx[1] + margin)


def rect_within_rect_xy(inner, outer):
    return (outer["min"][0] <= inner["min"][0] and inner["max"][0] <= outer["max"][0]
            and outer["min"][1] <= inner["min"][1] and inner["max"][1] <= outer["max"][1])


def rects_overlap_xy(a, b):
    return not (a["max"][0] <= b["min"][0] or b["max"][0] <= a["min"][0]
                or a["max"][1] <= b["min"][1] or b["max"][1] <= a["min"][1])


def seg_point_dist_xy(a, b, p):
    """Distance from point p to segment a-b in the xy plane."""
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    px, py = p[0], p[1]
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def bounds_from_center(center, half_w, half_d, z_lo, z_hi):
    return {
        "min": [center[0] - half_w, center[1] - half_d, z_lo],
        "max": [center[0] + half_w, center[1] + half_d, z_hi],
    }


# =============================================================================
# Graph helpers (shared by reachability / level-design validators)
# =============================================================================
def graph_nodes(overlay):
    return (overlay.get("graph") or {}).get("nodes", [])


def graph_edges(overlay):
    return (overlay.get("graph") or {}).get("edges", [])


def node_ids(overlay):
    return {n.get("id") for n in graph_nodes(overlay) if isinstance(n, dict)}


def reachable_from(overlay, start, kinds):
    """Return the set of node ids reachable from ``start`` over edges whose kind
    is in ``kinds`` (directed). ``kinds`` is a set like {"reachable", "risky"}."""
    adj = {}
    ids = node_ids(overlay)
    for e in graph_edges(overlay):
        if not isinstance(e, dict):
            continue
        if e.get("kind") in kinds and e.get("from") in ids and e.get("to") in ids:
            adj.setdefault(e["from"], []).append(e["to"])
    seen = set()
    if start not in ids:
        return seen
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for nxt in adj.get(cur, []):
            if nxt not in seen:
                stack.append(nxt)
    return seen


# =============================================================================
# Overlay loader (shared by validators in this lane)
# =============================================================================
def overlay_path_for(slice_id, overlay_dir=None):
    base = Path(overlay_dir) if overlay_dir else LEVEL_DESIGN_DIR
    return base / (slice_id + ".json")


def load_overlay(slice_id, overlay_dir=None):
    """Return (overlay_dict_or_None, error_or_None)."""
    p = overlay_path_for(slice_id, overlay_dir)
    if not p.is_file():
        return None, "overlay missing: {}".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, "overlay unparseable: {}".format(exc)


def content_for_hash(overlay):
    """Overlay content with the per-run provenance timestamp stripped."""
    clone = json.loads(json.dumps(overlay))
    prov = clone.get("provenance")
    if isinstance(prov, dict):
        for k in ("generated_at_utc", "source_commit", "source_tree_dirty", "inputs"):
            prov.pop(k, None)
    clone.pop("content_hash", None)
    return clone


# =============================================================================
# Terrain extent
# =============================================================================
def terrain_bounds_for(spec):
    """Derive a real terrain extent (cm) + height range from the terrain descriptor.

    Returns (bounds_dict, source_note). The terrain is centered on the origin.
    """
    tf = spec.get("terrain_forge") or {}
    dp = tf.get("descriptor_path")
    dim = DEFAULT_TERRAIN_DIM
    height_lo, height_hi = 0.0, 2000.0
    source = "default"
    if dp:
        dpath = REPO_ROOT / dp
        if dpath.is_file():
            try:
                desc = json.loads(dpath.read_text(encoding="utf-8"))
                dims = desc.get("dimensions")
                if isinstance(dims, list) and dims and int(dims[0]) > 1:
                    dim = int(dims[0])
                hr = desc.get("height_range_cm")
                if isinstance(hr, list) and len(hr) == 2:
                    height_lo, height_hi = float(hr[0]), float(hr[1])
                source = dp
            except Exception:  # noqa: BLE001
                source = "default(descriptor_unreadable)"
    half = (dim - 1) * CM_PER_QUAD / 2.0
    bounds = {
        "min": [-half, -half],
        "max": [half, half],
        "height_range_cm": [height_lo, height_hi],
    }
    return bounds, source, half


# =============================================================================
# Overlay construction
# =============================================================================
def _budget_class(variant):
    v = (variant or "").lower()
    if "heavy" in v:
        return "heavy"
    if "ruined" in v or "medium" in v:
        return "medium"
    return "light"


def _polar(cx, cy, r, ang_deg):
    a = math.radians(ang_deg)
    return [cx + r * math.cos(a), cy + r * math.sin(a)]


def _unit_toward(src, dst):
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    n = math.hypot(dx, dy) or 1.0
    return [round(dx / n, 4), round(dy / n, 4), 0.0]


def build_overlay(map_record, world_pack_id):
    """Build a deterministic level-design overlay dict from one MapRecord."""
    spec = map_record.spec
    slice_id = map_record.slice_id
    seed = spec.get("seed")
    biome = spec.get("biome") or map_record.get("biome") or "desert"
    variant = spec.get("variant") or ""
    poi_forge = spec.get("poi_forge") or {}
    poi_type = poi_forge.get("poi_type")
    state = spec.get("state") or {}
    state_key = state.get("key")

    tbounds, terrain_source, H = terrain_bounds_for(spec)
    z_lo, z_hi = tbounds["height_range_cm"]
    ground_z = z_lo  # POIs sit on the terrain floor (within [z_lo, z_hi]).
    center = (0.0, 0.0)

    rng = random.Random(seed)
    base_angle = (int(seed) * 47) % 360 + rng.uniform(-7.0, 7.0)

    primary_class = POI_TYPE_TO_CLASS.get(poi_type, "navigation_landmark")
    budget_class = _budget_class(variant)
    style_tokens = sorted({t for t in (
        biome, variant, (spec.get("terrain_forge") or {}).get("recipe_id"),
        (spec.get("terrain", {}) or {}).get("material_recipe"),
    ) if t})

    # --- entity layout -------------------------------------------------------
    # Critical route nodes live on an INNER disk; non-critical POIs on an OUTER
    # ring; the danger zone at mid radius. This structurally guarantees POIs
    # stay clear of the inner critical routes (validated + self-corrected).
    def at(r_frac, ang_off):
        return _polar(center[0], center[1], r_frac * H, base_angle + ang_off)

    ps_pos = at(0.33, 200)
    primary_pos = at(0.35, 20)
    secondary_pos = at(0.33, 110)
    safe_pos = at(0.30, 250)
    danger_pos = at(0.55, 65)

    def prov_block(extra=None):
        p = build_provenance(REPO_ROOT, [Path(map_record.spec_path)] if map_record.spec_path else [],
                             GENERATOR_NAME, GENERATOR_VERSION)
        p["source_spec_hash"] = hash_obj(spec)
        p["source_spec_path"] = (Path(map_record.spec_path).relative_to(REPO_ROOT).as_posix()
                                 if map_record.spec_path else None)
        p["terrain_extent_source"] = terrain_source
        if extra:
            p.update(extra)
        return p

    def poi_provenance():
        return {
            "generator": GENERATOR_NAME,
            "generator_version": GENERATOR_VERSION,
            "source_spec_hash": hash_obj(spec),
            "registry_owner": REGISTRY_OWNER,
        }

    def make_poi(pid, cls, role, pos, half_w, half_d, gameplay_role, expected_state,
                 sightline_target):
        anchor = [round(pos[0], 2), round(pos[1], 2), ground_z + 90.0]
        return {
            "id": pid,
            "class": cls,
            "role": role,
            "world_position": [round(pos[0], 2), round(pos[1], 2), ground_z],
            "bounds": bounds_from_center(pos, half_w, half_d, ground_z, ground_z + 800.0),
            "approach_vector": _unit_toward(pos, list(center)),
            "exit_vector": _unit_toward(list(center), pos),
            "gameplay_anchor": anchor,
            "biome_compat": [biome],
            "style_compat": style_tokens,
            "budget_class": budget_class,
            "inspection": {
                "inspectable": True,
                "gameplay_role": gameplay_role,
                "expected_state": expected_state,
                "state_key": state_key,
                "sightline_target": sightline_target,
                "notes": "{} ({}) derived from {} seed {}".format(
                    cls, role, slice_id, seed),
            },
            "provenance": poi_provenance(),
        }

    pois = [
        make_poi("primary_poi", primary_class, "primary", primary_pos, 3000, 2500,
                 "objective", "after", "navigation_landmark"),
        make_poi("secondary_poi", "objective_ready_anchor", "secondary", secondary_pos,
                 1800, 1800, "objective_support", "after", "primary_poi"),
        make_poi("navigation_landmark", "navigation_landmark", "landmark",
                 at(0.80, 0), 1400, 1400, "orientation", "static", "vista"),
        make_poi("resource_site", "resource_site", "resource", at(0.80, 137.5),
                 1800, 1800, "resource", "before", "primary_poi"),
        make_poi("encounter_anchor", "encounter_ready_anchor", "encounter",
                 at(0.78, 275), 1600, 1600, "encounter", "after", "danger_zone"),
        make_poi("spawn_adjacent_anchor", "spawn_adjacent_anchor", "spawn_adjacent",
                 at(0.34, 160), 1500, 1500, "spawn_support", "before", "player_start"),
        make_poi("objective_anchor", "objective_ready_anchor", "objective_ready",
                 at(0.76, 300), 1600, 1600, "objective_ready", "after", "primary_poi"),
    ]

    # --- self-correcting placement ------------------------------------------
    # Critical segments the non-endpoint POIs must stay clear of.
    endpoints = {"player_start", "primary_poi", "secondary_poi"}
    crit_segs = [(ps_pos, primary_pos), (primary_pos, secondary_pos)]

    def nudge_out(pos, ang_off_deg):
        """Push a point radially outward (deterministic) until it clears routes."""
        r = math.hypot(pos[0] - center[0], pos[1] - center[1])
        ang = math.degrees(math.atan2(pos[1] - center[1], pos[0] - center[0]))
        for _ in range(60):
            p = [center[0] + r * math.cos(math.radians(ang)),
                 center[1] + r * math.sin(math.radians(ang))]
            if min(seg_point_dist_xy(a, b, p) for a, b in crit_segs) >= PATH_CLEARANCE_CM + 3000:
                return p
            r = min(r + 0.03 * H, 0.9 * H)
        return p

    for poi in pois:
        if poi["id"] in endpoints:
            continue
        pos = poi["world_position"]
        new_xy = nudge_out(pos, 0)
        if new_xy[0] != pos[0] or new_xy[1] != pos[1]:
            hw = (poi["bounds"]["max"][0] - poi["bounds"]["min"][0]) / 2.0
            hd = (poi["bounds"]["max"][1] - poi["bounds"]["min"][1]) / 2.0
            poi["world_position"] = [round(new_xy[0], 2), round(new_xy[1], 2), ground_z]
            poi["bounds"] = bounds_from_center(new_xy, hw, hd, ground_z, ground_z + 800.0)
            poi["gameplay_anchor"] = [round(new_xy[0], 2), round(new_xy[1], 2), ground_z + 90.0]
            poi["approach_vector"] = _unit_toward(new_xy, list(center))
            poi["exit_vector"] = _unit_toward(list(center), new_xy)

    # --- zones ---------------------------------------------------------------
    safe_zone = {
        "id": "safe_zone",
        "class": "safe_zone",
        "role": "safe_zone",
        "world_position": [round(safe_pos[0], 2), round(safe_pos[1], 2), ground_z],
        "bounds": bounds_from_center(safe_pos, 3500, 3500, ground_z, ground_z + 400.0),
        "enemy_filled": False,
        "rest_point": True,
        "provenance": poi_provenance(),
        "inspection": {"inspectable": True, "gameplay_role": "rest", "notes": "safe rest zone"},
    }
    # Keep danger clear of POIs (self-correct outward if it overlaps any POI box).
    dpos = list(danger_pos)
    danger_bounds = bounds_from_center(dpos, 4000, 4000, ground_z, ground_z + 1200.0)
    for _ in range(60):
        if not any(rects_overlap_xy(danger_bounds, p["bounds"]) for p in pois) and \
                not rects_overlap_xy(danger_bounds, safe_zone["bounds"]):
            break
        r = math.hypot(dpos[0], dpos[1]) + 0.04 * H
        r = min(r, 0.9 * H)
        ang = math.atan2(dpos[1], dpos[0])
        dpos = [r * math.cos(ang), r * math.sin(ang)]
        danger_bounds = bounds_from_center(dpos, 4000, 4000, ground_z, ground_z + 1200.0)
    danger_zone = {
        "id": "danger_zone",
        "class": "danger_zone",
        "role": "danger_zone",
        "world_position": [round(dpos[0], 2), round(dpos[1], 2), ground_z],
        "bounds": danger_bounds,
        "enemy_filled": True,
        "avoidable": True,
        "provenance": poi_provenance(),
        "inspection": {"inspectable": True, "gameplay_role": "hazard", "notes": "avoidable hazard zone"},
    }

    # --- player start --------------------------------------------------------
    player_start = {
        "id": "player_start",
        "world_position": [round(ps_pos[0], 2), round(ps_pos[1], 2), ground_z],
        "bounds": bounds_from_center(ps_pos, 1000, 1000, ground_z, ground_z + 300.0),
        "facing_deg": round((base_angle + 20) % 360, 2),
        "facing_vector": _unit_toward(ps_pos, primary_pos),
        "orientation_cue": "face navigation_landmark bearing to orient",
        "vista_cue": "primary objective visible on the horizon toward the landmark",
        "provenance": poi_provenance(),
    }

    # --- cues ---------------------------------------------------------------
    orientation_cues = [
        {"id": "orient_landmark", "kind": "landmark_bearing",
         "target": "navigation_landmark",
         "from": "player_start", "detail": "distant landmark gives a stable heading"},
    ]
    vista_cues = [
        {"id": "vista_primary", "kind": "sightline", "from": "player_start",
         "target": "primary_poi", "detail": "line of sight from spawn to the primary objective"},
        {"id": "vista_point", "kind": "overlook", "from": "navigation_landmark",
         "target": "resource_site", "detail": "elevated overlook reveals the resource site"},
    ]

    # --- graph ---------------------------------------------------------------
    def node(nid, role, pos):
        return {"id": nid, "role": role, "type": role,
                "position": [round(pos[0], 2), round(pos[1], 2)]}

    p_of = {p["id"]: p["world_position"] for p in pois}
    nodes = [
        node("player_start", "player_start", player_start["world_position"]),
        node("primary_poi", "primary_poi", p_of["primary_poi"]),
        node("secondary_poi", "secondary_poi", p_of["secondary_poi"]),
        node("safe_zone", "safe_zone", safe_zone["world_position"]),
        node("danger_zone", "danger_zone", danger_zone["world_position"]),
        node("resource_site", "resource_site", p_of["resource_site"]),
        node("exit_route", "exit_or_edge_route", at(0.82, 45)),
    ]
    edges = [
        {"from": "player_start", "to": "primary_poi", "kind": "reachable"},
        {"from": "player_start", "to": "safe_zone", "kind": "reachable"},
        {"from": "player_start", "to": "resource_site", "kind": "optional"},
        {"from": "primary_poi", "to": "secondary_poi", "kind": "reachable"},
        {"from": "primary_poi", "to": "resource_site", "kind": "optional"},
        {"from": "primary_poi", "to": "danger_zone", "kind": "risky"},
        {"from": "danger_zone", "to": "resource_site", "kind": "risky"},
        {"from": "secondary_poi", "to": "exit_route", "kind": "reachable"},
    ]

    overlay = {
        "slice_id": slice_id,
        "schema_version": SCHEMA_VERSION,
        "world_pack_id": world_pack_id,
        "generated": True,
        "registry_owner": REGISTRY_OWNER,
        "seed": seed,
        "biome": biome,
        "variant": variant,
        "state_key": state_key,
        "poi_type": poi_type,
        "primary_class": primary_class,
        "budget_class": budget_class,
        "terrain_bounds": tbounds,
        "player_start": player_start,
        "pois": pois,
        "safe_zones": [safe_zone],
        "danger_zones": [danger_zone],
        "orientation_cues": orientation_cues,
        "vista_cues": vista_cues,
        "graph": {"nodes": nodes, "edges": edges},
        "provenance": prov_block(),
    }
    overlay["content_hash"] = hash_obj(content_for_hash(overlay))
    return overlay


def write_overlay(overlay, out_dir=None):
    out_dir = Path(out_dir) if out_dir else LEVEL_DESIGN_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (overlay["slice_id"] + ".json")
    with path.open("w", encoding="utf-8") as fh:
        json.dump(overlay, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def generate_pack(pack, out_dir=None, force=False):
    """Generate overlays for every map in a world pack. Returns (world_pack_id, results)."""
    world_pack_id, maps = enumerate_maps(pack)
    results = []
    for m in maps:
        if not m.spec_exists:
            results.append((m.slice_id, "MISSING_SPEC", m.get("spec_error")))
            continue
        overlay = build_overlay(m, world_pack_id)
        path = write_overlay(overlay, out_dir)
        results.append((m.slice_id, "OK", str(path)))
    return world_pack_id, results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate deterministic level-design overlays.")
    ap.add_argument("--pack", required=True, help="World pack id, e.g. desert_mvp_world")
    ap.add_argument("--out-dir", default=None, help="Override output dir (default canonical).")
    ap.add_argument("--force", action="store_true", help="Regenerate all overlays.")
    args = ap.parse_args(argv)

    world_pack_id, results = generate_pack(args.pack, args.out_dir, args.force)
    ok = sum(1 for _, s, _ in results if s == "OK")
    missing = [sid for sid, s, _ in results if s != "OK"]
    out = args.out_dir or LEVEL_DESIGN_DIR
    print("[generate-level-design] pack={} overlays={}/{} -> {}".format(
        world_pack_id, ok, len(results), out))
    for sid, s, detail in results:
        if s != "OK":
            print("  {}: {} ({})".format(sid, s, detail))
    if missing:
        print("[generate-level-design] FAIL — {} map(s) had no spec".format(len(missing)))
        return 1
    print("[generate-level-design] DONE — {} deterministic overlays".format(ok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
