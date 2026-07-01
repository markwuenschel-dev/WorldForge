#!/usr/bin/env python3
"""generate_entity_anchors.py — WorldForge v1.0x entity-anchor substrate generator.

Emits a deterministic *entity-anchor overlay* per map in a world pack. The overlay
is the validated substrate a future NPCForge / EncounterForge can consume WITHOUT
scraping geometry: spawn zones, patrol/idle/interaction/encounter anchors, faction
ownership, and safe/danger zones — all with positions, bounds, reachability,
collision-safety, budget class, and provenance.

This generator does NOT build NPC AI or encounters. It lays down deterministic
*slots and tags* (archetype/faction/difficulty/encounter tags) that downstream
systems fill in. It never modifies the map specs (green baseline preserved); it
writes only its own overlay files under::

    procedural/generated/entity_anchors/<slice_id>.json     (generated-owned)

Positions are derived from the map spec's ``poi_forge.anchors`` (offset_cm) plus a
deterministic model seeded by the spec seed. If Agent 4's level-design overlay
exists at ``procedural/generated/level_design/<slice_id>.json`` it is consumed as
a SOFT dependency (player_start / POI world origin / safe zones), otherwise those
are derived here. A missing level-design overlay is never fatal.

This module also exposes the constants and pure geometry helpers that the sibling
validators import, so the substrate has a single source of truth.

Usage:
    PYTHONUTF8=1 python tools/pipeline/generate_entity_anchors.py --pack desert_mvp_world
"""

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from world_pack_maps import enumerate_maps
from report_meta import hash_obj, utc_now_iso

# ---------------------------------------------------------------------------
# Substrate vocabulary — the single source of truth shared with the validators.
# ---------------------------------------------------------------------------
GENERATOR_NAME = "generate_entity_anchors"
GENERATOR_VERSION = "1.0.0"
SCHEMA_VERSION = "wf.entity_anchors.v1"

ANCHOR_TYPES = (
    "entity_anchor",
    "npc_spawn_zone",
    "enemy_spawn_zone",
    "neutral_spawn_zone",
    "patrol_anchor",
    "idle_anchor",
    "interaction_anchor",
    "encounter_anchor",
    "faction_ownership_anchor",
    "safe_zone_anchor",
    "danger_zone_anchor",
)
SPAWN_ZONE_TYPES = frozenset({"npc_spawn_zone", "enemy_spawn_zone", "neutral_spawn_zone"})

# Archetype *slots* (tags only — never behavior).
ARCHETYPES = frozenset({
    "scavenger", "guard", "worker", "drone", "raider",
    "neutral_trader_placeholder", "ambient_creature_placeholder",
})

VALID_FACTIONS = frozenset({
    "raiders", "scavengers", "guards", "workers", "drones",
    "neutral_traders", "ambient", "unaligned",
})

VALID_ENCOUNTER_TAGS = frozenset({
    "ambush", "patrol_clash", "defensive_hold", "scavenge_contested",
    "raider_assault", "none",
})

VALID_DIFFICULTY_TAGS = frozenset({"trivial", "low", "standard", "hard", "severe"})

BUDGET_CLASSES = frozenset({"core", "ambient", "optional"})

REQUIRED_ANCHOR_FIELDS = (
    "id", "type", "map_id", "position", "bounds", "owning_poi",
    "reachable", "collision_safe", "budget_class", "provenance",
)

# Density budget (per map). Kept generous but real; the substrate stays well under.
DENSITY_BUDGET = {
    "max_anchors_per_map": 40,
    "max_spawn_zones_per_map": 12,
    "max_enemy_spawn_zones_per_map": 4,
    "max_capacity_per_zone": 8,
    "max_total_spawn_capacity": 30,
}

# Geometry model tolerances (cm / deg). Shared with validators for recomputation.
GROUND_FLOAT_TOL_CM = 50
GROUND_BURY_TOL_CM = 50
MAX_SLOPE_DEG = 35
PLAYER_START_OFFSET_CM = 3000
PLAYER_START_RADIUS_CM = 500
SAFE_ZONE_RADIUS_CM = 2500
DANGER_ZONE_RADIUS_CM = 2000
EDGE_MAX_DIST_CM = 4000
ROUTE_CORRIDOR_RADIUS_CM = 800
PATROL_RING_RADIUS_CM = 1500
# Local player-start radius from POI center when oriented by a consumed approach
# bearing. Must sit inside (SAFE_ZONE_RADIUS_CM, EDGE_MAX_DIST_CM): far enough
# that the center/enemy is outside the safe zone, near enough to stay connected.
PLAYER_START_LOCAL_RADIUS_CM = 3500

# Role classification of poi_forge anchors.
_ENTRY_ROLES = frozenset({"entry", "approach"})
_CENTER_ROLES = frozenset({"primary_interaction", "resource_core", "lookout"})

_ENCOUNTER_BY_POI = {
    "industrial_yard": "defensive_hold",
    "debris_checkpoint": "ambush",
    "abandoned_mining_camp": "scavenge_contested",
    "scrubland_resource_node": "scavenge_contested",
    "cracked_ridge_lookout": "patrol_clash",
    "ash_shrine_ruin": "ambush",
}


# ---------------------------------------------------------------------------
# Pure geometry helpers (imported by validators — single source of truth).
# ---------------------------------------------------------------------------
def dist3(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def dist_xy(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def point_seg_dist_xy(p, a, b):
    """Distance in the XY plane from point p to segment a-b."""
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    px, py = p[0], p[1]
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 <= 1e-9:
        return dist_xy(p, a)
    t = ((px - ax) * dx + (py - ay) * dy) / seg2
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.sqrt((px - cx) ** 2 + (py - cy) ** 2)


def compute_reachable_indices(seed_pos, positions, edge_max=EDGE_MAX_DIST_CM):
    """BFS reachability over a proximity graph.

    Node 0 is ``seed_pos`` (the player start); nodes 1..n are ``positions``.
    An edge connects two nodes within ``edge_max``. Returns the set of node
    indices reachable from node 0. A position index i maps to node i+1.
    """
    nodes = [seed_pos] + list(positions)
    n = len(nodes)
    adj = {i: [] for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if dist3(nodes[i], nodes[j]) <= edge_max:
                adj[i].append(j)
                adj[j].append(i)
    seen = set()
    stack = [0]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj[cur])
    return seen


def point_in_box(p, box):
    """True if point p is inside an axis-aligned box {center, half_extent}."""
    c = box["center"]
    h = box["half_extent"]
    return all(abs(p[k] - c[k]) <= h[k] for k in range(3))


# ---------------------------------------------------------------------------
# Paths / IO.
# ---------------------------------------------------------------------------
def entity_anchors_dir():
    d = REPO_ROOT / "procedural" / "generated" / "entity_anchors"
    return d


def overlay_path(slice_id):
    return entity_anchors_dir() / (slice_id + ".json")


def load_overlay(slice_id, overlay_dir=None):
    """Load a generated overlay by slice_id (or None if absent/unparseable)."""
    base = Path(overlay_dir) if overlay_dir else entity_anchors_dir()
    p = base / (slice_id + ".json")
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def level_design_overlay_path(slice_id):
    return REPO_ROOT / "procedural" / "generated" / "level_design" / (slice_id + ".json")


def load_level_design_overlay(slice_id):
    """Soft dependency: Agent 4's level-design overlay, or None if absent."""
    p = level_design_overlay_path(slice_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Deterministic model derivation.
# ---------------------------------------------------------------------------
def _difficulty_for(variant):
    v = (variant or "").lower()
    if "heavy" in v:
        return "hard"
    if "survey" in v or "clean" in v:
        return "low"
    if "light" in v:
        return "low"
    if "ruined" in v or "ind" in v:
        return "standard"
    return "standard"


def _slope_for(seed, key):
    """Deterministic valid ground slope in [0, 12] degrees for a given anchor key.

    Uses a stable digest (NOT Python's per-process-randomized ``hash()``) so the
    overlay is byte-for-byte identical across runs for a fixed seed.
    """
    digest = hashlib.sha256("{}|{}|slope".format(seed, key).encode("utf-8")).hexdigest()
    return int(digest, 16) % 13


def _classify_poi_anchors(pf_anchors):
    """Return (entry, center, supports) as (id, [x,y,z]) tuples from poi_forge anchors."""
    pts = [(a.get("id"), [int(a["offset_cm"][0]), int(a["offset_cm"][1]), int(a["offset_cm"][2])])
           for a in pf_anchors if a.get("offset_cm")]
    if not pts:
        return ("origin", [0, 0, 0]), ("origin", [0, 0, 0]), []

    roles = {a.get("id"): a.get("role") for a in pf_anchors}

    def first_with_role(role_set):
        for pid, pos in pts:
            if roles.get(pid) in role_set:
                return (pid, pos)
        return None

    entry = first_with_role({"entry"}) or first_with_role({"approach"}) or pts[0]
    center = first_with_role(_CENTER_ROLES)
    if center is None:
        # Fall back to the anchor closest to the POI origin horizontally.
        center = min(pts, key=lambda kp: dist_xy(kp[1], [0, 0, 0]))
    supports = [(pid, pos) for pid, pos in pts if pid not in (entry[0], center[0])]
    return entry, center, supports


def _ld_world_pos(entry):
    """Extract a world position from a level-design node (dict or list)."""
    if isinstance(entry, dict):
        wp = entry.get("world_position") or entry.get("position")
        if isinstance(wp, (list, tuple)) and len(wp) >= 2:
            return [float(wp[0]), float(wp[1]), float(wp[2]) if len(wp) > 2 else 0.0]
    elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return [float(entry[0]), float(entry[1]), float(entry[2]) if len(entry) > 2 else 0.0]
    return None


def _consume_level_design(ld, poi_type):
    """Read Agent 4's level-design overlay into a cross-reference block (SOFT dep).

    Returns a dict carrying the real POI world origin, player_start, safe/danger
    zones, the approach bearing (player_start -> POI, unit XY), and the overlay's
    content hash for provenance cross-reference. Never raises on shape drift.
    """
    ref = {"source": "generate_level_design", "consumed": True}
    ps = _ld_world_pos(ld.get("player_start"))
    ref["player_start_world"] = ps

    pois = ld.get("pois") or []
    poi_origin = None
    if isinstance(pois, list):
        primary = None
        for p in pois:
            if isinstance(p, dict) and p.get("id") == "primary_poi":
                primary = p
                break
        if primary is None:
            for p in pois:
                if isinstance(p, dict) and p.get("poi_type") == poi_type:
                    primary = p
                    break
        if primary is None and pois:
            primary = pois[0]
        poi_origin = _ld_world_pos(primary) if primary else None
    ref["poi_origin_world"] = poi_origin

    def _zones(key):
        out = []
        for z in (ld.get(key) or []):
            wp = _ld_world_pos(z)
            if wp is None:
                continue
            r = None
            if isinstance(z, dict):
                r = z.get("radius") or z.get("radius_cm")
            out.append({"center_world": wp, "radius_cm": int(r) if r else None,
                        "id": z.get("id") if isinstance(z, dict) else None})
        return out

    ref["safe_zones_world"] = _zones("safe_zones")
    ref["danger_zones_world"] = _zones("danger_zones")
    ref["level_design_content_hash"] = ld.get("content_hash")
    ref["slice_id"] = ld.get("slice_id")

    # Approach bearing (unit XY) from player_start toward the POI origin.
    bearing = None
    if ps is not None and poi_origin is not None:
        dx, dy = poi_origin[0] - ps[0], poi_origin[1] - ps[1]
        mag = math.sqrt(dx * dx + dy * dy)
        if mag > 1e-6:
            # Local approach points FROM the player TOWARD the POI, so the local
            # player start sits on the opposite side: negate to face outward.
            bearing = [-dx / mag, -dy / mag]
    ref["approach_bearing_xy"] = bearing
    return ref


def _anchor_prov(spec_hash):
    return {
        "generator": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "owned_by": "generated",
        "source_spec_hash": spec_hash,
    }


def build_overlay(map_record, level_design=None):
    """Build a deterministic entity-anchor overlay dict for one map. Pure."""
    spec = map_record.spec
    slice_id = map_record.slice_id
    seed = spec.get("seed")
    pf = spec.get("poi_forge", {}) or {}
    poi_name = pf.get("poi_name") or (slice_id + "_poi")
    poi_type = pf.get("poi_type") or "unknown"
    variant = spec.get("variant")
    spec_hash = hash_obj(spec)
    prov = _anchor_prov(spec_hash)

    difficulty = _difficulty_for(variant)
    encounter_tag = _ENCOUNTER_BY_POI.get(poi_type, "raider_assault")

    entry, center, supports = _classify_poi_anchors(pf.get("anchors", []))
    entry_pos = entry[1]
    center_pos = center[1]

    # --- Level-design overlay (SOFT dependency) ---------------------------
    # Agent 4's overlay is a full multi-POI WORLD-frame layout (player_start far
    # from the POI, reachability expressed macro POI-to-POI via its own graph).
    # That is a different granularity than our within-POI micro-anchors, so we do
    # NOT graft its coordinates directly onto our local proximity graph (that
    # would strand every spawn zone as "unreachable"). Instead we keep our
    # anchors in a self-consistent POI-LOCAL frame AND genuinely consume the
    # overlay by carrying the real POI world origin, player_start, and
    # safe/danger zones plus a content-hash cross-reference, so a downstream
    # consumer can transform local->world and honor the real level layout. The
    # player-approach BEARING from Agent 4 is used to orient our local player
    # start. A missing overlay is not fatal; we derive everything ourselves.
    ld_ref = None
    approach_bearing = None
    if level_design:
        ld_ref = _consume_level_design(level_design, poi_type)
        approach_bearing = ld_ref.get("approach_bearing_xy")
    ld_consumed = ld_ref is not None

    # --- Player start (POI-local; oriented by Agent 4's approach if present) --
    if approach_bearing is not None:
        ux, uy = approach_bearing
    else:
        dx = entry_pos[0] - center_pos[0]
        dy = entry_pos[1] - center_pos[1]
        mag = math.sqrt(dx * dx + dy * dy)
        ux, uy = (0.0, -1.0) if mag < 1e-6 else (dx / mag, dy / mag)
    if approach_bearing is None:
        # Derived: entry->outward. player_start = entry + dir*offset (dir==entry
        # bearing), so player_start->entry == offset (connected) and center sits
        # outside the safe zone.
        player_start = [
            int(round(entry_pos[0] + ux * PLAYER_START_OFFSET_CM)),
            int(round(entry_pos[1] + uy * PLAYER_START_OFFSET_CM)),
            entry_pos[2],
        ]
    else:
        # Consumed bearing: place the local player start along Agent 4's approach
        # bearing, at a radius from the POI center inside the band
        # (safe_radius, edge_max) so enemies at the center stay out of the safe
        # zone AND the player start stays graph-connected to the center.
        r = PLAYER_START_LOCAL_RADIUS_CM
        player_start = [
            int(round(center_pos[0] + ux * r)),
            int(round(center_pos[1] + uy * r)),
            entry_pos[2],
        ]

    safe_center = player_start
    danger_center = center_pos

    anchors = []

    def add(anchor_id, atype, pos, budget_class, ground_z, *, faction_tag=None,
            difficulty_tag=None, encounter_tag_v=None, archetypes=None, capacity=None,
            allow_in_safe_zone=None, radius=None, role=None):
        rec = {
            "id": anchor_id,
            "type": atype,
            "map_id": slice_id,
            "position": [int(pos[0]), int(pos[1]), int(pos[2])],
            "bounds": {"shape": "sphere", "radius_cm": int(radius if radius is not None else 600)},
            "ground_z": int(ground_z),
            "slope_deg": _slope_for(seed, anchor_id),
            "owning_poi": poi_name,
            "reachable": True,       # recomputed/validated below and by validators
            "collision_safe": True,  # recomputed below
            "budget_class": budget_class,
            "provenance": dict(prov),
        }
        if role is not None:
            rec["role"] = role
        if faction_tag is not None:
            rec["faction_tag"] = faction_tag
        if difficulty_tag is not None:
            rec["difficulty_tag"] = difficulty_tag
        if encounter_tag_v is not None:
            rec["encounter_tag"] = encounter_tag_v
        if archetypes is not None:
            rec["archetypes"] = list(archetypes)
        if capacity is not None:
            rec["capacity"] = int(capacity)
        if allow_in_safe_zone is not None:
            rec["allow_in_safe_zone"] = bool(allow_in_safe_zone)
        anchors.append(rec)
        return rec

    # --- Safe / danger zones ---------------------------------------------
    add("safe_zone_center", "safe_zone_anchor", safe_center, "core", safe_center[2],
        radius=SAFE_ZONE_RADIUS_CM)
    add("danger_zone_core", "danger_zone_anchor", danger_center, "core", danger_center[2],
        radius=DANGER_ZONE_RADIUS_CM, difficulty_tag=difficulty)

    # --- Entry cluster: friendly/neutral presence + interaction ----------
    add("entity_marker_entry", "entity_anchor", entry_pos, "core", entry_pos[2], role="entry")
    add("interaction_entry", "interaction_anchor", entry_pos, "core", entry_pos[2], role="entry")
    add("npc_spawn_entry", "npc_spawn_zone", entry_pos, "core", entry_pos[2],
        faction_tag="neutral_traders",
        archetypes=["neutral_trader_placeholder", "worker"], capacity=3)

    # --- Center cluster: the encounter core ------------------------------
    add("interaction_center", "interaction_anchor", center_pos, "core", center_pos[2],
        role="primary")
    add("encounter_core", "encounter_anchor", center_pos, "core", center_pos[2],
        faction_tag="raiders", difficulty_tag=difficulty, encounter_tag_v=encounter_tag)
    add("enemy_spawn_core", "enemy_spawn_zone", center_pos, "core", center_pos[2],
        faction_tag="raiders", archetypes=["raider", "guard"], capacity=4,
        difficulty_tag=difficulty, encounter_tag_v=encounter_tag, allow_in_safe_zone=False)
    add("faction_ownership_core", "faction_ownership_anchor", center_pos, "core", center_pos[2],
        faction_tag="raiders")

    # --- Support anchors: scavenger presence, idle life, patrol ----------
    if supports:
        s0 = supports[0][1]
        add("neutral_spawn_support", "neutral_spawn_zone", s0, "ambient", s0[2],
            faction_tag="scavengers", archetypes=["scavenger", "worker"], capacity=3)
        # Idle anchor — pushed clear of the critical route if needed.
        idle_pos = _clear_of_route(list(s0), player_start, center_pos)
        add("idle_support", "idle_anchor", idle_pos, "ambient", s0[2],
            faction_tag="ambient", archetypes=["ambient_creature_placeholder"])
    else:
        # No support anchor — synthesize a neutral zone off-route from the center.
        s0 = [center_pos[0] + 1200, center_pos[1] - 1200, center_pos[2]]
        s0 = _clear_of_route(s0, player_start, center_pos)
        add("neutral_spawn_support", "neutral_spawn_zone", s0, "ambient", center_pos[2],
            faction_tag="scavengers", archetypes=["scavenger", "worker"], capacity=3)
        add("idle_support", "idle_anchor",
            _clear_of_route([center_pos[0] - 1200, center_pos[1] - 1200, center_pos[2]],
                            player_start, center_pos),
            "ambient", center_pos[2], faction_tag="ambient",
            archetypes=["ambient_creature_placeholder"])

    # --- Patrol ring: always >= 2 connected patrol anchors ---------------
    patrol_bases = [pos for _pid, pos in supports[:2]]
    while len(patrol_bases) < 2:
        idx = len(patrol_bases)
        ang = (math.pi / 2) * (idx + 1)
        patrol_bases.append([
            int(round(center_pos[0] + PATROL_RING_RADIUS_CM * math.cos(ang))),
            int(round(center_pos[1] + PATROL_RING_RADIUS_CM * math.sin(ang))),
            center_pos[2],
        ])
    for i, pb in enumerate(patrol_bases):
        add("patrol_{}".format(i), "patrol_anchor", pb, "optional", pb[2],
            faction_tag="guards", archetypes=["guard", "drone"])

    # --- Reachability: genuine graph BFS from player_start ---------------
    positions = [a["position"] for a in anchors]
    reachable_idx = compute_reachable_indices(player_start, positions)
    for i, a in enumerate(anchors):
        a["reachable"] = (i + 1) in reachable_idx

    # --- Collision safety: on-ground, in-tolerance, valid slope ----------
    blocking_volumes = []  # open desert — no solid blocking volumes in the good overlay
    for a in anchors:
        z, gz = a["position"][2], a["ground_z"]
        floating = z > gz + GROUND_FLOAT_TOL_CM
        buried = z < gz - GROUND_BURY_TOL_CM
        bad_slope = a["slope_deg"] > MAX_SLOPE_DEG
        inside = any(point_in_box(a["position"], b) for b in blocking_volumes)
        a["collision_safe"] = not (floating or buried or bad_slope or inside)

    poi_origin_world = ld_ref.get("poi_origin_world") if ld_ref else None
    world_model = {
        "ground_z": center_pos[2],
        "player_start": player_start,
        "player_start_radius_cm": PLAYER_START_RADIUS_CM,
        "poi_origin": [0, 0, 0],
        "poi_origin_world": poi_origin_world,
        "critical_route": [player_start, center_pos],
        "route_corridor_radius_cm": ROUTE_CORRIDOR_RADIUS_CM,
        "safe_zones": [{"center": safe_center, "radius_cm": SAFE_ZONE_RADIUS_CM}],
        "danger_zones": [{"center": danger_center, "radius_cm": DANGER_ZONE_RADIUS_CM}],
        "blocking_volumes": blocking_volumes,
        "max_slope_deg": MAX_SLOPE_DEG,
        "float_tolerance_cm": GROUND_FLOAT_TOL_CM,
        "bury_tolerance_cm": GROUND_BURY_TOL_CM,
        "edge_max_dist_cm": EDGE_MAX_DIST_CM,
    }

    overlay = {
        "schema_version": SCHEMA_VERSION,
        "slice_id": slice_id,
        "map_id": slice_id,
        "world_pack_map": spec.get("map"),
        "biome": map_record.get("biome"),
        "variant": variant,
        "seed": seed,
        "poi": {"name": poi_name, "type": poi_type},
        "owned_by": "generated",
        "destroyable": True,
        "level_design_consumed": ld_consumed,
        "level_design_ref": ld_ref,
        "density_budget": dict(DENSITY_BUDGET),
        "world_model": world_model,
        "anchors": anchors,
        "provenance": {
            "generator": GENERATOR_NAME,
            "generator_version": GENERATOR_VERSION,
            "generated_at_utc": utc_now_iso(),
            "source_spec_hash": spec_hash,
            "source_spec_path": map_record.spec_path,
            "seed": seed,
            "owned_by": "generated",
            "destroyable": True,
        },
    }
    overlay["content_hash"] = content_hash(overlay)
    return overlay


def _nearest_on_seg_xy(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 <= 1e-9:
        return [ax, ay]
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / seg2
    t = max(0.0, min(1.0, t))
    return [ax + t * dx, ay + t * dy]


def _clear_of_route(pos, player_start, center_pos, corridor=ROUTE_CORRIDOR_RADIUS_CM):
    """Push a point radially away from the nearest point on the player_start->center
    route until it is clear of the corridor.

    Radial-from-nearest (not perpendicular-to-segment) is required: when the
    closest feature is a route endpoint, a purely perpendicular push does not
    increase the distance to that endpoint.
    """
    x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
    for _ in range(6):
        if point_seg_dist_xy([x, y], player_start, center_pos) > corridor:
            break
        c = _nearest_on_seg_xy([x, y], player_start, center_pos)
        dx, dy = x - c[0], y - c[1]
        mag = math.sqrt(dx * dx + dy * dy)
        if mag < 1e-6:
            # On the route: pick the segment's perpendicular as the escape axis.
            rx, ry = center_pos[0] - player_start[0], center_pos[1] - player_start[1]
            rmag = math.sqrt(rx * rx + ry * ry) or 1.0
            dx, dy, mag = -ry / rmag, rx / rmag, 1.0
        target = corridor + 600
        x = c[0] + dx / mag * target
        y = c[1] + dy / mag * target
    return [int(round(x)), int(round(y)), int(round(z))]


def content_hash(overlay):
    """Deterministic hash of overlay content, excluding runtime provenance stamps."""
    stripped = _strip_runtime(overlay)
    return hash_obj(stripped)


def _strip_runtime(obj):
    """Deep copy with all ``generated_at_utc`` and ``content_hash`` keys removed."""
    clone = copy.deepcopy(obj)

    def _walk(o):
        if isinstance(o, dict):
            o.pop("generated_at_utc", None)
            o.pop("content_hash", None)
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)
    _walk(clone)
    return clone


# ---------------------------------------------------------------------------
# Pack generation.
# ---------------------------------------------------------------------------
def generate_pack(pack, write=True):
    """Generate overlays for every map in a pack. Returns (world_pack_id, overlays)."""
    world_pack_id, maps = enumerate_maps(pack)
    out_dir = entity_anchors_dir()
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
    overlays = []
    missing = []
    for m in maps:
        if not m.spec_exists:
            missing.append(m.slice_id or m.get("spec_error"))
            continue
        ld = load_level_design_overlay(m.slice_id)
        overlay = build_overlay(m, level_design=ld)
        overlays.append(overlay)
        if write:
            p = out_dir / (m.slice_id + ".json")
            with p.open("w", encoding="utf-8") as fh:
                json.dump(overlay, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
    return world_pack_id, overlays, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate entity-anchor overlays for a world pack.")
    ap.add_argument("--pack", default="desert_mvp_world", help="World pack id.")
    ap.add_argument("--strict", action="store_true", help="Fail on any missing spec.")
    args = ap.parse_args(argv)

    world_pack_id, overlays, missing = generate_pack(args.pack, write=True)
    ld_count = sum(1 for o in overlays if o.get("level_design_consumed"))
    total_anchors = sum(len(o["anchors"]) for o in overlays)
    print("[generate-entity-anchors] pack={} maps_written={} anchors={} "
          "level_design_consumed={}/{} missing_specs={}".format(
              world_pack_id, len(overlays), total_anchors, ld_count, len(overlays),
              len(missing)))
    print("[generate-entity-anchors] output -> {}".format(
        entity_anchors_dir().relative_to(REPO_ROOT).as_posix()))
    if missing:
        for mid in missing:
            print("[generate-entity-anchors]   MISSING SPEC: {}".format(mid))
        if args.strict:
            print("[generate-entity-anchors] FAIL — coverage shortfall under strict")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
