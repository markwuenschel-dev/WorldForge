#!/usr/bin/env python3
"""streaming_contracts.py — WorldForge v2.3 StreamingForge / WorldScaleForge spine.

v2.3 adds the first cross-tile generated-region substrate for WorldForge on top of
the v2.0 slice + v2.2 quest/faction stack. It is NOT a full open world, multiplayer
streaming, or a final World Partition implementation — it is the bounded production
substrate for generated regions composed of STREAMABLE TILES.

Core design principle (handoff §5):
    A streamed region is a validated GRAPH of generated tiles connected by stable
    cross-tile anchors + routes, with bounded runtime lifecycle, cross-tile save/load
    continuity, and inspectable evidence. Every tile boundary must be explainable;
    every cross-tile claim must have proof.

This module holds the strict, schema-only contracts that define those streaming
artifacts and prove — at authoring time, before any generated region or runtime
report exists — that their *shape* is coherent and cannot launder a disconnected
region graph, a non-reciprocal neighbor, a broken anchor/route link, a navmesh
OVERCLAIM (headless path_missing dressed up as proved navmesh), a scenario that
"completes" with no stream transition, a tile whose reload silently lost state, a
save/load claim with no tile hashes, an NPC claiming pressure in an unloaded tile,
or a budget overrun reported as a pass, into a green view.

Design mirrors quest_faction_contracts.py / operator_contracts.py exactly:
    * frozen tuple enums (bounded taxonomy, one source of truth)
    * ``X_REQUIRED`` / ``X_ALLOWED`` field-name tuples
    * ``validate_X(obj, strict=False)`` returning (check, ok, detail, code) tuples
      built from shared runtime_schema (RS) helpers + domain honesty checks
    * ``_example_X(**over)`` canonical-valid factories (``d.update(over)`` spawns
      known-bad variants for the negatives/fuzz suites)
    * a ``CONTRACTS`` registry pairing each validator with a valid + known-bad
      example, ``CONTRACT_GROUPS`` partitioning it, and ``KNOWN_BAD_OWNING_CODE``
      naming the code each known-bad must be rejected FOR

Schema-only: cross-record resolution (does a neighbor reciprocate? does a tile_id
resolve to a real generated tile? does a route path exist on disk?) is the job of
the Wave-2 authoring validators and Wave-3/4 runtime validators, which have the
datasets + filesystem in hand. Stdlib only; no jsonschema.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_schema as RS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402

# --------------------------------------------------------------------------- #
# schema_version / report_type dotted namespaces (wf.streaming.<type>.v1)
# --------------------------------------------------------------------------- #
RT_REGION = "wf.streaming.region_definition.v1"
RT_TILE = "wf.streaming.tile_definition.v1"
RT_ANCHOR = "wf.streaming.cross_tile_anchor.v1"
RT_ROUTE = "wf.streaming.cross_tile_route.v1"
RT_MISSION_BINDING = "wf.streaming.streamed_mission_binding.v1"
RT_NPC_BINDING = "wf.streaming.streamed_npc_binding.v1"
RT_BUDGET_PROFILE = "wf.streaming.budget_profile.v1"
RT_TILE_LIFECYCLE = "wf.streaming.tile_lifecycle_report.v1"
RT_RUNTIME_REPORT = "wf.streaming.runtime_report.v1"
RT_SAVE_STATE = "wf.streaming.cross_tile_save_state.v1"
RT_EVIDENCE_INDEX = "wf.streaming.evidence_index.v1"
RT_OPERATOR_REGION_VIEW = "wf.streaming.operator_region_view.v1"
RT_OPERATOR_TILE_VIEW = "wf.streaming.operator_tile_view.v1"

# --------------------------------------------------------------------------- #
# Bounded taxonomy (one source of truth).
# --------------------------------------------------------------------------- #
# Region layout types (handoff §7). Bounded — no arbitrary open-world grid.
REGION_LAYOUT_TYPES = ("hub_spoke", "linear_chain", "adjacent_cluster")
# Streaming profiles (handoff §6). three_tile_chain is the optional stretch.
STREAMING_PROFILES = ("adjacent_tile_crossing", "hub_to_spoke_transition",
                      "three_tile_chain")
# Tile roles (handoff §8.2).
TILE_ROLES = ("entry", "hub", "route", "objective", "hazard", "exit")
# Cross-tile anchor types (handoff §8.3).
ANCHOR_TYPES = ("entry", "exit", "transition", "mission_objective", "npc_spawn",
                "quest_marker", "save_checkpoint", "handoff")
# Which anchor types a given tile role may legitimately host (honesty §8.3:
# "anchor type compatible with tile role").
ROLE_ANCHOR_COMPAT = {
    "entry": ("entry", "transition", "save_checkpoint", "handoff", "npc_spawn"),
    "hub": ("entry", "exit", "transition", "mission_objective", "npc_spawn",
            "quest_marker", "save_checkpoint", "handoff"),
    "route": ("transition", "handoff", "npc_spawn", "save_checkpoint"),
    "objective": ("mission_objective", "quest_marker", "transition", "npc_spawn",
                  "save_checkpoint", "handoff"),
    "hazard": ("transition", "npc_spawn", "handoff"),
    "exit": ("exit", "transition", "save_checkpoint", "handoff"),
}
# Traversal modes for a cross-tile route (handoff §8.4). grounded_navmesh may
# appear only if actually proved — headless remains an honest path_missing limit,
# so it is NOT a proved objective-access mode. flight/teleport are not modes here.
TRAVERSAL_MODES = ("grounded_worldforge_route", "grounded_manual_waypoint",
                   "grounded_navmesh", "failed")
PROVED_TRAVERSAL_MODES = ("grounded_worldforge_route", "grounded_manual_waypoint")
# Tile load / unload policies (handoff §8.2).
LOAD_POLICIES = ("preload", "on_demand", "adjacent_prefetch")
UNLOAD_POLICIES = ("keep_resident", "unload_on_exit", "distance_unload")
# NPC stream-in / stream-out policies (handoff §8.6).
STREAM_IN_POLICIES = ("spawn_on_tile_load", "spawn_on_region_enter", "persist_resident")
STREAM_OUT_POLICIES = ("despawn_on_tile_unload", "persist_across_tiles",
                       "freeze_and_preserve")
# Route / objective facet status.
ROUTE_STATUS = ("pass", "fail", "blocked", "absent", "not_run")
# Budget classification (handoff §8.7). "advisory" = over a soft target but not a
# hard cap; "exceeded" = a hard-cap overrun that blocks a runtime pass.
BUDGET_RESULTS = ("pass", "advisory", "exceeded")
# Save/load roundtrip vocabulary.
SAVE_LOAD_RESULTS = ("roundtrip_ok", "roundtrip_failed", "not_run", "missing")
# Evidence-index integrity verdicts.
INTEGRITY_RESULTS = ("pass", "fail", "blocked")
# Honest runtime-mode labels (handoff §12 Agent 5): the alpha must NOT label a
# simulated / process-isolated lifecycle as full UE streaming.
RUNTIME_MODES = ("simulated_streaming_lifecycle", "process_isolated_tile_sequence",
                 "full_ue_streaming")
PROVED_UE_STREAMING = ("full_ue_streaming",)
# Machine-checkable runtime-claim categories a mission binding may require.
STREAM_CLAIM_CATEGORIES = (
    "tile_load", "transition", "anchor", "route", "mission", "npc", "combat",
    "reward", "quest", "faction", "save_load", "budget",
)

# The bounded v2.3 matrix (handoff §3/§11): 2 regions × 3 archetypes × 2 profiles
# × 2 seeds = 24 streaming scenarios (no new 120 matrix).
EXPECTED_SCENARIO_COUNT = 24
EXPECTED_REGION_COUNT = 2
MIN_TILES_PER_REGION = 3
MAX_TILES_PER_REGION = 5

# The shared deterministic authoring timestamp (NOT wall-clock).
AUTHORING_TS = "2026-07-11T00:00:00+00:00"

# Generated / report roots (repo-relative).
REGIONS_REL = "procedural/generated/regions"
TILES_REL = "procedural/generated/tiles"
ANCHORS_REL = "procedural/generated/anchors"
ROUTES_REL = "procedural/generated/routes"
STREAMING_REL = "procedural/generated/streaming"
STREAM_REPORTS_REL = "procedural/reports/streaming"

_WF_CODE_RE = re.compile(r"^WF\d{3}_[A-Z0-9_]+$")


# --------------------------------------------------------------------------- #
# small local helpers (mirror quest_faction_contracts.py)
# --------------------------------------------------------------------------- #
def _str(obj, field, code, prefix):
    ch = RS.check_type(obj, field, str, code, prefix=prefix)
    v = obj.get(field) if isinstance(obj, dict) else None
    ch.append(("{}{}_nonempty".format(prefix, field),
               isinstance(v, str) and bool(v.strip()),
               "{} must be a non-empty string".format(field), code))
    return ch


def _bool(obj, field, code, prefix):
    v = obj.get(field) if isinstance(obj, dict) else None
    return [("{}{}_bool".format(prefix, field), isinstance(v, bool),
             "{} must be an explicit boolean (got {!r})".format(field, v), code)]


def _int(obj, field, code, prefix, allow_zero=True):
    ch = RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)
    v = obj.get(field) if isinstance(obj, dict) else None
    is_int = RS.is_number(v) and float(v).is_integer()
    ch.append(("{}{}_integer".format(prefix, field), is_int,
               "{} must be an integer (got {!r})".format(field, v), code))
    return ch


def _list_of_str(obj, field, code, prefix, min_len=0, max_len=None):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) >= min_len and all(isinstance(x, str) for x in v)
    if ok and max_len is not None:
        ok = len(v) <= max_len
    return [("{}{}_str_list".format(prefix, field), ok,
             "{} must be a list of {}..{} strings".format(field, min_len, max_len or "N"),
             code)]


def _is_list(obj, field):
    return isinstance(obj.get(field), list) if isinstance(obj, dict) else False


def _is_dict(obj, field):
    return isinstance(obj.get(field), dict) if isinstance(obj, dict) else False


def _finite_vec(v, n=3):
    return isinstance(v, list) and len(v) == n and all(RS.is_number(x) for x in v)


def _predicate_machine_checkable(pred):
    if not isinstance(pred, dict):
        return False
    return (pred.get("claim") in STREAM_CLAIM_CATEGORIES
            and pred.get("op") in ("==", ">=", "<=", ">", "<", "true", "false")
            and "value" in pred)


def _schema_version(obj, expected, code, prefix):
    sv = obj.get("schema_version") if isinstance(obj, dict) else None
    return [("{}schema_version".format(prefix), sv == expected,
             "schema_version must be {!r} (got {!r})".format(expected, sv), code)]


# =========================================================================== #
# 1. RegionDefinition (WF851)
# =========================================================================== #
REGION_REQUIRED = (
    "region_id", "region_name", "source_pack_id", "region_layout_type", "tile_ids",
    "entry_tile_id", "exit_tile_ids", "region_seed", "biome_set",
    "mission_archetypes", "streaming_profile", "budget_profile_id", "schema_version",
)
REGION_ALLOWED = REGION_REQUIRED + ("meta", "report_type", "created_by", "created_at",
                                    "notes", "seed")


def validate_region_definition(obj, strict=False):
    code = C.STREAMING_REGION_CONTRACT_INVALID
    ch = RS.check_required(obj, REGION_REQUIRED, code)
    ch += RS.check_no_unknown(obj, REGION_ALLOWED, code, strict)
    for f in ("region_id", "region_name", "source_pack_id", "entry_tile_id",
              "budget_profile_id"):
        ch += _str(obj, f, code, "rd::")
    ch += RS.check_enum(obj, "region_layout_type", REGION_LAYOUT_TYPES, code, prefix="rd::")
    ch += RS.check_enum(obj, "streaming_profile", STREAMING_PROFILES, code, prefix="rd::")
    ch += _int(obj, "region_seed", code, "rd::", allow_zero=True)
    ch += _list_of_str(obj, "tile_ids", code, "rd::", min_len=MIN_TILES_PER_REGION,
                       max_len=MAX_TILES_PER_REGION)
    ch += _list_of_str(obj, "exit_tile_ids", code, "rd::", min_len=1)
    ch += _list_of_str(obj, "biome_set", code, "rd::", min_len=1)
    ch += _list_of_str(obj, "mission_archetypes", code, "rd::", min_len=1)
    # honesty: entry + exits must be members of tile_ids (a region can't enter/exit
    # a tile it doesn't contain).
    tiles = obj.get("tile_ids") if _is_list(obj, "tile_ids") else []
    ch.append(("rd::entry_in_tiles", obj.get("entry_tile_id") in tiles,
               "entry_tile_id must be one of tile_ids", C.STREAMING_TILE_GRAPH_DISCONNECTED))
    exits = obj.get("exit_tile_ids") if _is_list(obj, "exit_tile_ids") else []
    ch.append(("rd::exits_in_tiles", bool(exits) and all(t in tiles for t in exits),
               "every exit_tile_id must be one of tile_ids",
               C.STREAMING_TILE_GRAPH_DISCONNECTED))
    ch += _schema_version(obj, RT_REGION, code, "rd::")
    return ch


def _example_region_definition(**over):
    d = {
        "region_id": "region_alpine_hub",
        "region_name": "Alpine Glacial Hub",
        "source_pack_id": "worldforge_vertical_slice",
        "region_layout_type": "hub_spoke",
        "tile_ids": ["tile_alpine_hub_entry", "tile_alpine_objective_a",
                     "tile_alpine_objective_b"],
        "entry_tile_id": "tile_alpine_hub_entry",
        "exit_tile_ids": ["tile_alpine_objective_b"],
        "region_seed": 1,
        "biome_set": ["alpine_snow"],
        "mission_archetypes": ["survey_landmark", "recover_resource", "clear_hazard"],
        "streaming_profile": "hub_to_spoke_transition",
        "budget_profile_id": "budget_standard",
        "created_by": "worldforge.v2.3",
        "created_at": AUTHORING_TS,
        "schema_version": RT_REGION,
        "report_type": RT_REGION,
    }
    d.update(over)
    return d


# =========================================================================== #
# 2. StreamingTileDefinition (WF852)
# =========================================================================== #
TILE_REQUIRED = (
    "tile_id", "region_id", "map_id", "source_scenario_ids", "biome", "tile_role",
    "tile_bounds", "neighbor_tile_ids", "load_policy", "unload_policy", "anchor_ids",
    "budget_profile_id", "ownership_manifest_path", "schema_version",
)
TILE_ALLOWED = TILE_REQUIRED + ("meta", "report_type", "created_by", "created_at", "notes")


def _tile_bounds_finite(b):
    return (isinstance(b, dict) and _finite_vec(b.get("origin"), 3)
            and _finite_vec(b.get("size"), 3)
            and all(x > 0 for x in b["size"]))


def validate_tile_definition(obj, strict=False):
    code = C.STREAMING_TILE_CONTRACT_INVALID
    ch = RS.check_required(obj, TILE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, TILE_ALLOWED, code, strict)
    for f in ("tile_id", "region_id", "map_id", "biome", "budget_profile_id",
              "ownership_manifest_path"):
        ch += _str(obj, f, code, "td::")
    ch += RS.check_enum(obj, "tile_role", TILE_ROLES, code, prefix="td::")
    ch += RS.check_enum(obj, "load_policy", LOAD_POLICIES, code, prefix="td::")
    ch += RS.check_enum(obj, "unload_policy", UNLOAD_POLICIES, code, prefix="td::")
    ch += _list_of_str(obj, "source_scenario_ids", code, "td::", min_len=1)
    ch += _list_of_str(obj, "neighbor_tile_ids", code, "td::", min_len=1)
    ch += _list_of_str(obj, "anchor_ids", code, "td::", min_len=1)
    ch.append(("td::tile_bounds_finite", _tile_bounds_finite(obj.get("tile_bounds")),
               "tile_bounds must be {origin:[x,y,z], size:[w,h,d]>0}",
               C.STREAMING_TILE_CONTRACT_INVALID))
    # honesty: a tile cannot list itself as a neighbor.
    nb = obj.get("neighbor_tile_ids") if _is_list(obj, "neighbor_tile_ids") else []
    ch.append(("td::no_self_neighbor", obj.get("tile_id") not in nb,
               "tile must not list itself as a neighbor", C.STREAMING_NEIGHBOR_NOT_RECIPROCAL))
    ch += _schema_version(obj, RT_TILE, code, "td::")
    return ch


def _example_tile_definition(**over):
    d = {
        "tile_id": "tile_alpine_hub_entry",
        "region_id": "region_alpine_hub",
        "map_id": "Alpine_GlacialBasin_Debris_Photoreal_01",
        "source_scenario_ids": ["vs_alpine_snow_survey_landmark_baseline_s1"],
        "biome": "alpine_snow",
        "tile_role": "hub",
        "tile_bounds": {"origin": [0.0, 0.0, 0.0], "size": [25600.0, 25600.0, 8192.0]},
        "neighbor_tile_ids": ["tile_alpine_objective_a", "tile_alpine_objective_b"],
        "load_policy": "preload",
        "unload_policy": "keep_resident",
        "anchor_ids": ["anchor_alpine_hub_entry", "anchor_alpine_hub_to_a"],
        "budget_profile_id": "budget_standard",
        "ownership_manifest_path":
            "procedural/reports/operator/index/asset_ownership_views.json",
        "created_by": "worldforge.v2.3",
        "created_at": AUTHORING_TS,
        "schema_version": RT_TILE,
        "report_type": RT_TILE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 3. CrossTileAnchor (WF855)
# =========================================================================== #
ANCHOR_REQUIRED = (
    "anchor_id", "region_id", "tile_id", "anchor_type", "world_location",
    "linked_anchor_ids", "route_role", "mission_role", "npc_role", "save_load_key",
    "schema_version",
)
ANCHOR_ALLOWED = ANCHOR_REQUIRED + ("meta", "report_type", "created_by", "created_at",
                                    "notes", "tile_role")


def validate_cross_tile_anchor(obj, strict=False):
    code = C.STREAMING_ANCHOR_INVALID
    ch = RS.check_required(obj, ANCHOR_REQUIRED, code)
    ch += RS.check_no_unknown(obj, ANCHOR_ALLOWED, code, strict)
    for f in ("anchor_id", "region_id", "tile_id", "route_role", "mission_role",
              "npc_role", "save_load_key"):
        ch += _str(obj, f, code, "an::")
    ch += RS.check_enum(obj, "anchor_type", ANCHOR_TYPES, code, prefix="an::")
    ch.append(("an::world_location_finite", _finite_vec(obj.get("world_location"), 3),
               "world_location must be a finite [x,y,z]", C.STREAMING_ANCHOR_INVALID))
    ch.append(("an::linked_anchor_ids_list", _is_list(obj, "linked_anchor_ids"),
               "linked_anchor_ids must be a list", C.STREAMING_ANCHOR_LINK_BROKEN))
    # honesty: an INTERNAL boundary-crossing anchor (transition/handoff) MUST link at
    # least one partner anchor across the tile boundary. entry/exit are region
    # termini and may legitimately have no partner. An anchor may not link itself.
    linked = obj.get("linked_anchor_ids") if _is_list(obj, "linked_anchor_ids") else []
    if obj.get("anchor_type") in ("transition", "handoff"):
        ch.append(("an::boundary_anchor_links",
                   isinstance(linked, list) and len(linked) >= 1,
                   "a {} anchor must link >=1 partner anchor".format(obj.get("anchor_type")),
                   C.STREAMING_ANCHOR_LINK_BROKEN))
    ch.append(("an::no_self_link", obj.get("anchor_id") not in linked,
               "anchor must not link itself", C.STREAMING_ANCHOR_LINK_BROKEN))
    # honesty: anchor type compatible with the hosting tile role (when provided).
    role = obj.get("tile_role")
    if role in ROLE_ANCHOR_COMPAT:
        ch.append(("an::type_compatible_with_role",
                   obj.get("anchor_type") in ROLE_ANCHOR_COMPAT[role],
                   "anchor_type {} not compatible with tile_role {}".format(
                       obj.get("anchor_type"), role),
                   C.STREAMING_ANCHOR_INVALID))
    ch += _schema_version(obj, RT_ANCHOR, code, "an::")
    return ch


def _example_cross_tile_anchor(**over):
    d = {
        "anchor_id": "anchor_alpine_hub_to_a",
        "region_id": "region_alpine_hub",
        "tile_id": "tile_alpine_hub_entry",
        "anchor_type": "transition",
        "world_location": [12800.0, 0.0, 512.0],
        "linked_anchor_ids": ["anchor_alpine_a_from_hub"],
        "route_role": "transition_out",
        "mission_role": "none",
        "npc_role": "none",
        "save_load_key": "sl_anchor_alpine_hub_to_a",
        "tile_role": "hub",
        "created_by": "worldforge.v2.3",
        "created_at": AUTHORING_TS,
        "schema_version": RT_ANCHOR,
        "report_type": RT_ANCHOR,
    }
    d.update(over)
    return d


# =========================================================================== #
# 4. CrossTileRoute (WF857)
# =========================================================================== #
ROUTE_REQUIRED = (
    "route_id", "region_id", "source_anchor_id", "target_anchor_id", "tile_sequence",
    "route_segments", "traversal_mode", "route_width", "objective_access_status",
    "stream_transition_points", "failure_codes", "schema_version",
)
ROUTE_ALLOWED = ROUTE_REQUIRED + ("meta", "report_type", "created_by", "created_at", "notes")


def validate_cross_tile_route(obj, strict=False):
    code = C.STREAMING_ROUTE_INVALID
    ch = RS.check_required(obj, ROUTE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, ROUTE_ALLOWED, code, strict)
    for f in ("route_id", "region_id", "source_anchor_id", "target_anchor_id"):
        ch += _str(obj, f, code, "rt::")
    ch += RS.check_enum(obj, "traversal_mode", TRAVERSAL_MODES, code, prefix="rt::")
    ch += RS.check_enum(obj, "objective_access_status", ROUTE_STATUS, code, prefix="rt::")
    ch += RS.check_positive_number(obj, "route_width", code, prefix="rt::", allow_zero=False)
    ch += _list_of_str(obj, "tile_sequence", C.STREAMING_ROUTE_TILE_SEQUENCE_INVALID,
                       "rt::", min_len=2)
    ch.append(("rt::route_segments_nonempty",
               _is_list(obj, "route_segments") and len(obj["route_segments"]) >= 1,
               "route_segments must be non-empty", C.STREAMING_ROUTE_INVALID))
    ch.append(("rt::transition_points_list", _is_list(obj, "stream_transition_points"),
               "stream_transition_points must be a list", C.STREAMING_TRANSITION_POINT_INVALID))
    ch.append(("rt::failure_codes_list", _is_list(obj, "failure_codes"),
               "failure_codes must be a list", C.STREAMING_ROUTE_INVALID))
    # honesty: a cross-tile route must span >=2 distinct tiles AND carry a transition
    # point at each internal boundary (tile_sequence length - 1).
    seq = obj.get("tile_sequence") if _is_list(obj, "tile_sequence") else []
    tp = obj.get("stream_transition_points") if _is_list(obj, "stream_transition_points") else []
    if len(seq) >= 2:
        ch.append(("rt::transition_points_match_boundaries", len(tp) >= len(seq) - 1,
                   "a route across {} tiles needs >= {} stream_transition_points "
                   "(got {})".format(len(seq), len(seq) - 1, len(tp)),
                   C.STREAMING_TRANSITION_POINT_INVALID))
        ch.append(("rt::distinct_tiles", len(set(seq)) == len(seq),
                   "tile_sequence must not repeat a tile",
                   C.STREAMING_ROUTE_TILE_SEQUENCE_INVALID))
    # TRUTH GUARD: a proved objective access requires a proved grounded WorldForge
    # mode. grounded_navmesh is a headless path_missing limit; 'failed' is not proved.
    if obj.get("objective_access_status") == "pass":
        ch.append(("rt::no_navmesh_overclaim",
                   obj.get("traversal_mode") in PROVED_TRAVERSAL_MODES,
                   "objective_access_status=pass requires a proved grounded WorldForge "
                   "mode {} (got {!r}); grounded_navmesh/failed are not proved".format(
                       PROVED_TRAVERSAL_MODES, obj.get("traversal_mode")),
                   C.STREAMING_NAVMESH_OVERCLAIM))
    # honesty: a failed route cannot also claim pass objective access.
    if obj.get("traversal_mode") == "failed":
        ch.append(("rt::failed_not_pass", obj.get("objective_access_status") != "pass",
                   "a failed route cannot have objective_access_status=pass",
                   C.STREAMING_ROUTE_UNREACHABLE))
    ch += _schema_version(obj, RT_ROUTE, code, "rt::")
    return ch


def _example_cross_tile_route(**over):
    d = {
        "route_id": "route_alpine_hub_to_a",
        "region_id": "region_alpine_hub",
        "source_anchor_id": "anchor_alpine_hub_to_a",
        "target_anchor_id": "anchor_alpine_a_from_hub",
        "tile_sequence": ["tile_alpine_hub_entry", "tile_alpine_objective_a"],
        "route_segments": [{"from": "anchor_alpine_hub_to_a",
                            "to": "anchor_alpine_a_from_hub", "length": 12800.0}],
        "traversal_mode": "grounded_worldforge_route",
        "route_width": 384.0,
        "objective_access_status": "pass",
        "stream_transition_points": [{"at_tile_boundary": ["tile_alpine_hub_entry",
                                     "tile_alpine_objective_a"], "location": [12800.0, 0.0, 512.0]}],
        "failure_codes": [],
        "created_by": "worldforge.v2.3",
        "created_at": AUTHORING_TS,
        "schema_version": RT_ROUTE,
        "report_type": RT_ROUTE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 5. StreamedMissionBinding (WF861)
# =========================================================================== #
MISSION_BINDING_REQUIRED = (
    "binding_id", "region_id", "scenario_id", "quest_id", "mission_archetype",
    "required_tile_ids", "start_anchor_id", "objective_anchor_ids",
    "completion_anchor_id", "required_cross_tile_routes", "streaming_requirements",
    "runtime_claims_required", "schema_version",
)
MISSION_BINDING_ALLOWED = MISSION_BINDING_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "streaming_profile", "seed")


def validate_streamed_mission_binding(obj, strict=False):
    code = C.STREAMING_MISSION_BINDING_INVALID
    ch = RS.check_required(obj, MISSION_BINDING_REQUIRED, code)
    ch += RS.check_no_unknown(obj, MISSION_BINDING_ALLOWED, code, strict)
    for f in ("binding_id", "region_id", "scenario_id", "quest_id", "mission_archetype",
              "start_anchor_id", "completion_anchor_id"):
        ch += _str(obj, f, code, "mb::")
    ch += _list_of_str(obj, "required_tile_ids", code, "mb::", min_len=2)
    ch += _list_of_str(obj, "objective_anchor_ids", code, "mb::", min_len=1)
    ch += _list_of_str(obj, "required_cross_tile_routes",
                       C.STREAMING_ROUTE_INVALID, "mb::", min_len=1)
    ch.append(("mb::streaming_requirements_dict", _is_dict(obj, "streaming_requirements"),
               "streaming_requirements must be a dict", code))
    # runtime claims machine-checkable.
    rc = obj.get("runtime_claims_required")
    rc_ok = isinstance(rc, list) and len(rc) >= 1 and all(_predicate_machine_checkable(p) for p in rc)
    ch.append(("mb::runtime_claims_machine_checkable", rc_ok,
               "runtime_claims_required must be >=1 machine-checkable {claim,op,value}",
               C.STREAMING_MISSION_BINDING_INVALID))
    # honesty: a streamed mission must require crossing >=2 tiles (it's cross-tile).
    ch += _schema_version(obj, RT_MISSION_BINDING, code, "mb::")
    return ch


def _example_streamed_mission_binding(**over):
    d = {
        "binding_id": "smb_region_alpine_hub_survey_hub_to_spoke_transition_s1",
        "region_id": "region_alpine_hub",
        "scenario_id": "st_region_alpine_hub_survey_landmark_hub_to_spoke_transition_s1",
        "quest_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "mission_archetype": "survey_landmark",
        "required_tile_ids": ["tile_alpine_hub_entry", "tile_alpine_objective_a"],
        "start_anchor_id": "anchor_alpine_hub_entry",
        "objective_anchor_ids": ["anchor_alpine_a_objective"],
        "completion_anchor_id": "anchor_alpine_a_objective",
        "required_cross_tile_routes": ["route_alpine_hub_to_a"],
        "streaming_requirements": {"min_transitions": 1, "streaming_profile":
                                   "hub_to_spoke_transition"},
        "runtime_claims_required": [
            {"claim": "transition", "op": ">=", "value": 1},
            {"claim": "route", "op": "==", "value": "completed"},
            {"claim": "mission", "op": "==", "value": "completed"},
        ],
        "streaming_profile": "hub_to_spoke_transition",
        "seed": 1,
        "created_by": "worldforge.v2.3",
        "created_at": AUTHORING_TS,
        "schema_version": RT_MISSION_BINDING,
        "report_type": RT_MISSION_BINDING,
    }
    d.update(over)
    return d


# =========================================================================== #
# 6. StreamedNPCBinding (WF862)
# =========================================================================== #
NPC_BINDING_REQUIRED = (
    "binding_id", "region_id", "scenario_id", "npc_profile_id", "spawn_anchor_id",
    "allowed_tile_ids", "perception_tile_scope", "pressure_tile_scope",
    "combat_tile_scope", "stream_in_policy", "stream_out_policy", "save_load_key",
    "schema_version",
)
NPC_BINDING_ALLOWED = NPC_BINDING_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes")


def validate_streamed_npc_binding(obj, strict=False):
    code = C.STREAMING_NPC_BINDING_INVALID
    ch = RS.check_required(obj, NPC_BINDING_REQUIRED, code)
    ch += RS.check_no_unknown(obj, NPC_BINDING_ALLOWED, code, strict)
    for f in ("binding_id", "region_id", "scenario_id", "npc_profile_id",
              "spawn_anchor_id", "save_load_key"):
        ch += _str(obj, f, code, "nb::")
    ch += RS.check_enum(obj, "stream_in_policy", STREAM_IN_POLICIES, code, prefix="nb::")
    ch += RS.check_enum(obj, "stream_out_policy", STREAM_OUT_POLICIES, code, prefix="nb::")
    ch += _list_of_str(obj, "allowed_tile_ids", code, "nb::", min_len=1)
    for f in ("perception_tile_scope", "pressure_tile_scope", "combat_tile_scope"):
        ch += _list_of_str(obj, f, code, "nb::")
    allowed = set(obj.get("allowed_tile_ids") or []) if _is_list(obj, "allowed_tile_ids") else set()
    # honesty: every tile scope must be a SUBSET of allowed tiles — an NPC can never
    # perceive / pressure / fight in a tile it is not allowed in (and thus may be
    # unloaded). This is the "no pressure in an unloaded tile" guard at authoring.
    for f, ccode in (("perception_tile_scope", C.STREAMING_NPC_BINDING_INVALID),
                     ("pressure_tile_scope", C.STREAMING_NPC_PRESSURE_MISSING),
                     ("combat_tile_scope", C.STREAMING_COMBAT_EVIDENCE_MISSING)):
        scope = set(obj.get(f) or []) if _is_list(obj, f) else set()
        ch.append(("nb::{}_subset_allowed".format(f), scope <= allowed,
                   "{} must be a subset of allowed_tile_ids (leak: {})".format(
                       f, sorted(scope - allowed)),
                   ccode))
    # honesty: the spawn tile scope makes sense — spawn anchor's tile is allowed is
    # cross-record; here just require allowed non-empty (already) + save_load stable.
    ch += _schema_version(obj, RT_NPC_BINDING, code, "nb::")
    return ch


def _example_streamed_npc_binding(**over):
    d = {
        "binding_id": "snb_region_alpine_hub_sentry_s1",
        "region_id": "region_alpine_hub",
        "scenario_id": "st_region_alpine_hub_survey_landmark_hub_to_spoke_transition_s1",
        "npc_profile_id": "npc_sentry_baseline",
        "spawn_anchor_id": "anchor_alpine_a_npc_spawn",
        "allowed_tile_ids": ["tile_alpine_objective_a", "tile_alpine_hub_entry"],
        "perception_tile_scope": ["tile_alpine_objective_a"],
        "pressure_tile_scope": ["tile_alpine_objective_a"],
        "combat_tile_scope": ["tile_alpine_objective_a"],
        "stream_in_policy": "spawn_on_tile_load",
        "stream_out_policy": "despawn_on_tile_unload",
        "save_load_key": "sl_npc_alpine_a_sentry",
        "created_by": "worldforge.v2.3",
        "created_at": AUTHORING_TS,
        "schema_version": RT_NPC_BINDING,
        "report_type": RT_NPC_BINDING,
    }
    d.update(over)
    return d


# =========================================================================== #
# 7. StreamingBudgetProfile (WF863)
# =========================================================================== #
BUDGET_REQUIRED = (
    "budget_profile_id", "max_loaded_tiles", "max_loaded_maps", "max_runtime_actors",
    "max_npcs", "max_active_combat_events", "max_memory_mb", "max_load_time_ms",
    "max_transition_gap_ms", "package_budget_mb", "schema_version",
)
BUDGET_ALLOWED = BUDGET_REQUIRED + ("meta", "report_type", "created_by", "created_at", "notes")
_BUDGET_MAXES = ("max_loaded_tiles", "max_loaded_maps", "max_runtime_actors", "max_npcs",
                 "max_active_combat_events", "max_memory_mb", "max_load_time_ms",
                 "max_transition_gap_ms", "package_budget_mb")


def validate_streaming_budget_profile(obj, strict=False):
    code = C.STREAMING_BUDGET_PROFILE_INVALID
    ch = RS.check_required(obj, BUDGET_REQUIRED, code)
    ch += RS.check_no_unknown(obj, BUDGET_ALLOWED, code, strict)
    ch += _str(obj, "budget_profile_id", code, "bp::")
    for f in _BUDGET_MAXES:
        ch += _int(obj, f, code, "bp::", allow_zero=False)  # all maxes must be > 0
    ch.append(("bp::max_loaded_tiles_ge1",
               RS.is_number(obj.get("max_loaded_tiles")) and obj.get("max_loaded_tiles") >= 1,
               "max_loaded_tiles must be >= 1", C.STREAMING_BUDGET_PROFILE_INVALID))
    ch += _schema_version(obj, RT_BUDGET_PROFILE, code, "bp::")
    return ch


def _example_streaming_budget_profile(**over):
    d = {
        "budget_profile_id": "budget_standard",
        "max_loaded_tiles": 3,
        "max_loaded_maps": 3,
        "max_runtime_actors": 400,
        "max_npcs": 24,
        "max_active_combat_events": 8,
        "max_memory_mb": 4096,
        "max_load_time_ms": 4000,
        "max_transition_gap_ms": 250,
        "package_budget_mb": 512,
        "created_by": "worldforge.v2.3",
        "created_at": AUTHORING_TS,
        "schema_version": RT_BUDGET_PROFILE,
        "report_type": RT_BUDGET_PROFILE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 8. TileLifecycleReport (WF864 / schema WF883)
# =========================================================================== #
LIFECYCLE_REQUIRED = (
    "report_id", "region_id", "tile_id", "scenario_id", "load_requested",
    "load_started", "load_completed", "became_active", "unload_requested",
    "unload_completed", "reload_completed", "actors_spawned",
    "actors_destroyed_or_preserved", "state_preserved", "budget_result",
    "failure_codes", "schema_version",
)
LIFECYCLE_ALLOWED = LIFECYCLE_REQUIRED + ("meta", "report_type", "created_by",
                                          "created_at", "notes")


def validate_tile_lifecycle_report(obj, strict=False):
    code = C.STREAMING_RUNTIME_REPORT_INVALID
    ch = RS.check_required(obj, LIFECYCLE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, LIFECYCLE_ALLOWED, code, strict)
    for f in ("report_id", "region_id", "tile_id", "scenario_id"):
        ch += _str(obj, f, code, "tl::")
    for f in ("load_requested", "load_started", "load_completed", "became_active",
              "unload_requested", "unload_completed", "reload_completed",
              "state_preserved"):
        ch += _bool(obj, f, code, "tl::")
    ch += _int(obj, "actors_spawned", code, "tl::", allow_zero=True)
    ch += _int(obj, "actors_destroyed_or_preserved", code, "tl::", allow_zero=True)
    ch += RS.check_enum(obj, "budget_result", BUDGET_RESULTS, C.STREAMING_BUDGET_EXCEEDED,
                        prefix="tl::")
    ch.append(("tl::failure_codes_list", _is_list(obj, "failure_codes"),
               "failure_codes must be a list", code))
    clean = _is_list(obj, "failure_codes") and len(obj.get("failure_codes") or []) == 0
    # honesty: an active tile requires a completed load.
    if obj.get("became_active") is True:
        ch.append(("tl::active_requires_load_completed", obj.get("load_completed") is True,
                   "became_active=true requires load_completed=true",
                   C.STREAMING_TILE_LOAD_MISSING))
    # honesty: a reload requires state_preserved (that's the whole point of reload proof).
    if obj.get("reload_completed") is True:
        ch.append(("tl::reload_requires_state_preserved", obj.get("state_preserved") is True,
                   "reload_completed=true requires state_preserved=true",
                   C.STREAMING_TILE_STATE_LOST))
    # honesty: a clean lifecycle (no failure codes) must have completed its load and
    # not lost state, and its budget must not be exceeded.
    if clean:
        ch.append(("tl::clean_requires_load_completed", obj.get("load_completed") is True,
                   "a clean lifecycle requires load_completed=true",
                   C.STREAMING_TILE_LOAD_FAILED))
        ch.append(("tl::clean_budget_not_exceeded", obj.get("budget_result") != "exceeded",
                   "a clean lifecycle cannot have budget_result=exceeded",
                   C.STREAMING_BUDGET_EXCEEDED))
    ch += _schema_version(obj, RT_TILE_LIFECYCLE, code, "tl::")
    return ch


def _example_tile_lifecycle_report(**over):
    d = {
        "report_id": "tlc_region_alpine_hub_tile_alpine_hub_entry_s1",
        "region_id": "region_alpine_hub",
        "tile_id": "tile_alpine_hub_entry",
        "scenario_id": "st_region_alpine_hub_survey_landmark_hub_to_spoke_transition_s1",
        "load_requested": True, "load_started": True, "load_completed": True,
        "became_active": True, "unload_requested": True, "unload_completed": True,
        "reload_completed": True, "actors_spawned": 12,
        "actors_destroyed_or_preserved": 12, "state_preserved": True,
        "budget_result": "pass", "failure_codes": [],
        "created_by": "worldforge.v2.3", "created_at": "live",
        "schema_version": RT_TILE_LIFECYCLE, "report_type": RT_TILE_LIFECYCLE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 9. StreamingRuntimeReport (WF883)
# =========================================================================== #
RUNTIME_REPORT_REQUIRED = (
    "report_id", "run_id", "region_id", "scenario_id", "streaming_profile",
    "tile_sequence_seen", "anchors_reached", "routes_completed",
    "stream_transitions_seen", "mission_completed", "npc_pressure_seen",
    "combat_damage_seen", "reward_granted", "quest_state_updated",
    "faction_state_updated", "cross_tile_save_load_result", "budget_result",
    "operator_trace_paths", "failure_codes", "schema_version",
)
RUNTIME_REPORT_ALLOWED = RUNTIME_REPORT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "runtime_mode",
    "required_tile_ids", "required_anchor_ids", "required_route_ids", "seed")


def validate_streaming_runtime_report(obj, strict=False):
    code = C.STREAMING_RUNTIME_REPORT_INVALID
    ch = RS.check_required(obj, RUNTIME_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, RUNTIME_REPORT_ALLOWED, code, strict)
    for f in ("report_id", "run_id", "region_id", "scenario_id"):
        ch += _str(obj, f, code, "sr::")
    ch += RS.check_enum(obj, "streaming_profile", STREAMING_PROFILES, code, prefix="sr::")
    ch += RS.check_enum(obj, "cross_tile_save_load_result", SAVE_LOAD_RESULTS,
                        C.STREAMING_CROSS_TILE_SAVE_FAILED, prefix="sr::")
    ch += RS.check_enum(obj, "budget_result", BUDGET_RESULTS, C.STREAMING_BUDGET_EXCEEDED,
                        prefix="sr::")
    if "runtime_mode" in (obj if isinstance(obj, dict) else {}):
        ch += RS.check_enum(obj, "runtime_mode", RUNTIME_MODES, code, prefix="sr::")
    for f in ("mission_completed", "npc_pressure_seen", "combat_damage_seen",
              "reward_granted", "quest_state_updated", "faction_state_updated"):
        ch += _bool(obj, f, code, "sr::")
    ch += _int(obj, "stream_transitions_seen", code, "sr::", allow_zero=True)
    for f in ("tile_sequence_seen", "anchors_reached", "routes_completed",
              "operator_trace_paths", "failure_codes"):
        ch.append(("sr::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    fcs = obj.get("failure_codes")
    if _is_list(obj, "failure_codes"):
        ch.append(("sr::failure_codes_well_formed",
                   all(isinstance(c, str) and _WF_CODE_RE.match(c) for c in fcs),
                   "failure_codes must be WFnnn_* strings", C.STREAMING_UNKNOWN_FAILURE_CODE))

    # --- honesty: a CLEAN report (empty failure_codes) MUST carry real evidence ---
    clean = _is_list(obj, "failure_codes") and len(fcs or []) == 0
    if clean:
        ch.append(("sr::clean_crosses_tiles",
                   _is_list(obj, "tile_sequence_seen") and len(obj["tile_sequence_seen"]) >= 2,
                   "a clean streaming report must cross >= 2 tiles",
                   C.STREAMING_MISSION_NOT_COMPLETED))
        ch.append(("sr::clean_has_transition",
                   RS.is_number(obj.get("stream_transitions_seen"))
                   and obj["stream_transitions_seen"] >= 1,
                   "a clean streaming report requires stream_transitions_seen >= 1",
                   C.STREAMING_REQUIRED_TRANSITION_MISSING))
        ch.append(("sr::clean_completes_routes",
                   _is_list(obj, "routes_completed") and len(obj["routes_completed"]) >= 1,
                   "a clean streaming report must complete >= 1 cross-tile route",
                   C.STREAMING_REQUIRED_ROUTE_NOT_COMPLETED))
        ch.append(("sr::clean_reaches_anchors",
                   _is_list(obj, "anchors_reached") and len(obj["anchors_reached"]) >= 1,
                   "a clean streaming report must reach >= 1 anchor",
                   C.STREAMING_REQUIRED_ANCHOR_NOT_REACHED))
        ch.append(("sr::clean_mission_completed", obj.get("mission_completed") is True,
                   "a clean streaming report requires mission_completed=true",
                   C.STREAMING_MISSION_NOT_COMPLETED))
        ch.append(("sr::clean_save_roundtrip",
                   obj.get("cross_tile_save_load_result") == "roundtrip_ok",
                   "a clean streaming report requires cross_tile_save_load_result=roundtrip_ok",
                   C.STREAMING_CROSS_TILE_SAVE_FAILED))
        ch.append(("sr::clean_budget_ok", obj.get("budget_result") in ("pass", "advisory"),
                   "a clean streaming report requires budget_result in (pass, advisory)",
                   C.STREAMING_BUDGET_EXCEEDED))
        # runtime-mode honesty: a clean report may NOT claim full_ue_streaming (v2.3
        # does not prove native UE streaming); it must use an honest alpha mode.
        if "runtime_mode" in obj:
            ch.append(("sr::clean_no_ue_streaming_overclaim",
                       obj.get("runtime_mode") in ("simulated_streaming_lifecycle",
                                                   "process_isolated_tile_sequence"),
                       "v2.3 must not label the alpha as full_ue_streaming",
                       C.STREAMING_NAVMESH_OVERCLAIM))
    ch += _schema_version(obj, RT_RUNTIME_REPORT, code, "sr::")
    return ch


def _example_streaming_runtime_report(**over):
    d = {
        "report_id": "srr_region_alpine_hub_survey_hub_to_spoke_transition_s1",
        "run_id": "strun_region_alpine_hub_survey_hub_to_spoke_transition_s1",
        "region_id": "region_alpine_hub",
        "scenario_id": "st_region_alpine_hub_survey_landmark_hub_to_spoke_transition_s1",
        "streaming_profile": "hub_to_spoke_transition",
        "tile_sequence_seen": ["tile_alpine_hub_entry", "tile_alpine_objective_a"],
        "anchors_reached": ["anchor_alpine_hub_entry", "anchor_alpine_a_objective"],
        "routes_completed": ["route_alpine_hub_to_a"],
        "stream_transitions_seen": 1,
        "mission_completed": True, "npc_pressure_seen": True, "combat_damage_seen": True,
        "reward_granted": True, "quest_state_updated": True, "faction_state_updated": True,
        "cross_tile_save_load_result": "roundtrip_ok", "budget_result": "pass",
        "runtime_mode": "simulated_streaming_lifecycle",
        "operator_trace_paths": [
            "procedural/reports/operator/regions/region_alpine_hub.html"],
        "failure_codes": [], "seed": 1,
        "created_by": "worldforge.v2.3", "created_at": "live",
        "schema_version": RT_RUNTIME_REPORT, "report_type": RT_RUNTIME_REPORT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 10. CrossTileSaveState (WF870)
# =========================================================================== #
SAVE_STATE_REQUIRED = (
    "save_state_id", "region_id", "scenario_id", "loaded_tile_ids", "unloaded_tile_ids",
    "tile_state_hashes", "actor_state_hashes", "mission_state_hash", "quest_state_hash",
    "faction_state_hash", "player_location_anchor_id", "reload_tile_id",
    "roundtrip_result", "schema_version",
)
SAVE_STATE_ALLOWED = SAVE_STATE_REQUIRED + ("meta", "report_type", "created_by",
                                            "created_at", "notes")


def validate_cross_tile_save_state(obj, strict=False):
    code = C.STREAMING_CROSS_TILE_SAVE_FAILED
    ch = RS.check_required(obj, SAVE_STATE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SAVE_STATE_ALLOWED, code, strict)
    for f in ("save_state_id", "region_id", "scenario_id", "mission_state_hash",
              "player_location_anchor_id", "reload_tile_id"):
        ch += _str(obj, f, code, "ss::")
    for f in ("loaded_tile_ids", "unloaded_tile_ids"):
        ch.append(("ss::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += RS.check_enum(obj, "roundtrip_result", SAVE_LOAD_RESULTS, code, prefix="ss::")
    for f in ("tile_state_hashes", "actor_state_hashes"):
        ch.append(("ss::{}_is_dict".format(f), _is_dict(obj, f),
                   "{} must be a dict tile_id -> hash".format(f),
                   C.STREAMING_CROSS_TILE_SAVE_MISSING))
    # honesty: a roundtrip_ok save MUST carry a hash for every visited tile.
    if obj.get("roundtrip_result") == "roundtrip_ok":
        loaded = obj.get("loaded_tile_ids") if _is_list(obj, "loaded_tile_ids") else []
        hashes = obj.get("tile_state_hashes") if _is_dict(obj, "tile_state_hashes") else {}
        ch.append(("ss::roundtrip_has_tile_hashes",
                   len(hashes) >= 1 and all(t in hashes for t in loaded),
                   "roundtrip_ok requires a tile_state_hash for every loaded tile",
                   C.STREAMING_CROSS_TILE_SAVE_MISSING))
    ch += _schema_version(obj, RT_SAVE_STATE, code, "ss::")
    return ch


def _example_cross_tile_save_state(**over):
    d = {
        "save_state_id": "cts_region_alpine_hub_survey_s1",
        "region_id": "region_alpine_hub",
        "scenario_id": "st_region_alpine_hub_survey_landmark_hub_to_spoke_transition_s1",
        "loaded_tile_ids": ["tile_alpine_hub_entry", "tile_alpine_objective_a"],
        "unloaded_tile_ids": ["tile_alpine_objective_b"],
        "tile_state_hashes": {"tile_alpine_hub_entry": "sha256:t1",
                              "tile_alpine_objective_a": "sha256:t2"},
        "actor_state_hashes": {"npc_sentry_baseline": "sha256:a1"},
        "mission_state_hash": "sha256:m1", "quest_state_hash": "sha256:q1",
        "faction_state_hash": "sha256:f1",
        "player_location_anchor_id": "anchor_alpine_a_objective",
        "reload_tile_id": "tile_alpine_objective_a", "roundtrip_result": "roundtrip_ok",
        "created_by": "worldforge.v2.3", "created_at": "live",
        "schema_version": RT_SAVE_STATE, "report_type": RT_SAVE_STATE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 11. StreamingEvidenceIndex (WF884)
# =========================================================================== #
EVIDENCE_INDEX_REQUIRED = (
    "index_id", "created_at", "git_sha", "region_count", "tile_count",
    "scenario_count_expected", "scenario_count_seen", "region_definition_paths",
    "tile_definition_paths", "anchor_paths", "route_paths", "runtime_report_paths",
    "tile_lifecycle_report_paths", "save_load_report_paths", "operator_view_paths",
    "missing_evidence", "stale_evidence", "integrity_result", "schema_version",
)
EVIDENCE_INDEX_ALLOWED = EVIDENCE_INDEX_REQUIRED + ("meta", "report_type", "created_by", "notes")
_INDEX_PATH_LISTS = (
    "region_definition_paths", "tile_definition_paths", "anchor_paths", "route_paths",
    "runtime_report_paths", "tile_lifecycle_report_paths", "save_load_report_paths",
    "operator_view_paths",
)


def validate_streaming_evidence_index(obj, strict=False):
    code = C.STREAMING_EVIDENCE_INDEX_INVALID
    ch = RS.check_required(obj, EVIDENCE_INDEX_REQUIRED, code)
    ch += RS.check_no_unknown(obj, EVIDENCE_INDEX_ALLOWED, code, strict)
    for f in ("index_id", "created_at", "git_sha"):
        ch += _str(obj, f, code, "ei::")
    for f in ("region_count", "tile_count", "scenario_count_expected",
              "scenario_count_seen"):
        ch += _int(obj, f, code, "ei::", allow_zero=True)
    for f in _INDEX_PATH_LISTS + ("missing_evidence", "stale_evidence"):
        ch.append(("ei::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += RS.check_enum(obj, "integrity_result", INTEGRITY_RESULTS, code, prefix="ei::")
    if obj.get("created_at") == "live":
        sha = obj.get("git_sha")
        ch.append(("ei::live_requires_real_sha",
                   isinstance(sha, str) and sha and sha != "unknown",
                   "created_at='live' requires a real git_sha", C.STREAMING_STALE_EVIDENCE))
    if obj.get("integrity_result") == "pass":
        seen, exp = obj.get("scenario_count_seen"), obj.get("scenario_count_expected")
        ch.append(("ei::pass_requires_full_matrix",
                   RS.is_number(seen) and RS.is_number(exp) and seen == exp and exp > 0,
                   "integrity_result=pass requires scenario_count_seen == expected > 0 "
                   "(got {} / {})".format(seen, exp), C.STREAMING_PARTIAL_MATRIX))
        ch.append(("ei::pass_requires_no_missing",
                   _is_list(obj, "missing_evidence") and len(obj["missing_evidence"]) == 0,
                   "integrity_result=pass requires empty missing_evidence",
                   C.STREAMING_CROSS_TILE_SAVE_MISSING))
        ch.append(("ei::pass_requires_no_stale",
                   _is_list(obj, "stale_evidence") and len(obj["stale_evidence"]) == 0,
                   "integrity_result=pass requires empty stale_evidence",
                   C.STREAMING_STALE_EVIDENCE))
    ch += _schema_version(obj, RT_EVIDENCE_INDEX, code, "ei::")
    return ch


def _example_streaming_evidence_index(**over):
    d = {
        "index_id": "streaming_evidence_index", "created_at": "live",
        "git_sha": "0" * 40, "region_count": 2, "tile_count": 6,
        "scenario_count_expected": 24, "scenario_count_seen": 24,
        "region_definition_paths": [REGIONS_REL + "/region_alpine_hub.json"],
        "tile_definition_paths": [TILES_REL + "/tile_alpine_hub_entry.json"],
        "anchor_paths": [ANCHORS_REL + "/anchor_alpine_hub_entry.json"],
        "route_paths": [ROUTES_REL + "/route_alpine_hub_to_a.json"],
        "runtime_report_paths": [STREAM_REPORTS_REL + "/runtime/strun_x/report.json"],
        "tile_lifecycle_report_paths": [STREAM_REPORTS_REL + "/lifecycle/x.json"],
        "save_load_report_paths": [STREAM_REPORTS_REL + "/save_load/x.json"],
        "operator_view_paths": ["procedural/reports/operator/index/region_views.json"],
        "missing_evidence": [], "stale_evidence": [], "integrity_result": "pass",
        "created_by": "worldforge.v2.3",
        "schema_version": RT_EVIDENCE_INDEX, "report_type": RT_EVIDENCE_INDEX,
    }
    d.update(over)
    return d


# =========================================================================== #
# 12. OperatorRegionView (WF885)
# =========================================================================== #
OP_REGION_REQUIRED = (
    "region_id", "region_definition_path", "tile_ids", "tile_graph", "anchors",
    "cross_tile_routes", "streaming_scenarios", "runtime_status_summary",
    "budget_status_summary", "save_load_status_summary", "quest_faction_status_summary",
    "failure_codes", "schema_version",
)
OP_REGION_ALLOWED = OP_REGION_REQUIRED + ("meta", "report_type", "created_by",
                                          "created_at", "notes")


def validate_operator_region_view(obj, strict=False):
    code = C.STREAMING_OPERATOR_VIEW_INVALID
    ch = RS.check_required(obj, OP_REGION_REQUIRED, code)
    ch += RS.check_no_unknown(obj, OP_REGION_ALLOWED, code, strict)
    ch += _str(obj, "region_id", code, "or::")
    ch += _str(obj, "region_definition_path", code, "or::")
    ch += _list_of_str(obj, "tile_ids", code, "or::", min_len=1)
    ch += _list_of_str(obj, "streaming_scenarios", code, "or::", min_len=1)
    ch.append(("or::tile_graph_dict", _is_dict(obj, "tile_graph"),
               "tile_graph must be a dict", code))
    for f in ("anchors", "cross_tile_routes", "failure_codes"):
        ch.append(("or::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    for f in ("runtime_status_summary", "budget_status_summary",
              "save_load_status_summary", "quest_faction_status_summary"):
        ch += _str(obj, f, code, "or::")
    # honesty: a clean region view (no failure codes) claiming a passing save/load
    # summary must reference the region definition on a real path (link resolved by
    # the operator smoke gate; here require non-empty).
    ch += _schema_version(obj, RT_OPERATOR_REGION_VIEW, code, "or::")
    return ch


def _example_operator_region_view(**over):
    d = {
        "region_id": "region_alpine_hub",
        "region_definition_path": REGIONS_REL + "/region_alpine_hub.json",
        "tile_ids": ["tile_alpine_hub_entry", "tile_alpine_objective_a",
                     "tile_alpine_objective_b"],
        "tile_graph": {"tile_alpine_hub_entry": ["tile_alpine_objective_a",
                       "tile_alpine_objective_b"]},
        "anchors": ["anchor_alpine_hub_entry"], "cross_tile_routes": ["route_alpine_hub_to_a"],
        "streaming_scenarios": [
            "st_region_alpine_hub_survey_landmark_hub_to_spoke_transition_s1"],
        "runtime_status_summary": "pass", "budget_status_summary": "pass",
        "save_load_status_summary": "roundtrip_ok",
        "quest_faction_status_summary": "updated", "failure_codes": [],
        "created_by": "worldforge.v2.3", "created_at": "live",
        "schema_version": RT_OPERATOR_REGION_VIEW, "report_type": RT_OPERATOR_REGION_VIEW,
    }
    d.update(over)
    return d


# =========================================================================== #
# 13. OperatorTileView (WF885)
# =========================================================================== #
OP_TILE_REQUIRED = (
    "tile_id", "region_id", "map_id", "tile_role", "neighbors", "anchors",
    "lifecycle_reports", "route_reports", "budget_reports", "asset_ownership_paths",
    "runtime_status", "failure_codes", "schema_version",
)
OP_TILE_ALLOWED = OP_TILE_REQUIRED + ("meta", "report_type", "created_by",
                                      "created_at", "notes")


def validate_operator_tile_view(obj, strict=False):
    code = C.STREAMING_OPERATOR_VIEW_INVALID
    ch = RS.check_required(obj, OP_TILE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, OP_TILE_ALLOWED, code, strict)
    for f in ("tile_id", "region_id", "map_id", "runtime_status"):
        ch += _str(obj, f, code, "ot::")
    ch += RS.check_enum(obj, "tile_role", TILE_ROLES, code, prefix="ot::")
    ch += _list_of_str(obj, "neighbors", code, "ot::", min_len=1)
    for f in ("anchors", "route_reports", "budget_reports", "asset_ownership_paths",
              "failure_codes"):
        ch.append(("ot::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch.append(("ot::lifecycle_reports_is_list", _is_list(obj, "lifecycle_reports"),
               "lifecycle_reports must be a list", code))
    # honesty: a clean tile view (no failure codes, runtime_status pass) MUST link at
    # least one lifecycle report — its runtime status is only meaningful with proof.
    clean = _is_list(obj, "failure_codes") and len(obj.get("failure_codes") or []) == 0
    if clean and obj.get("runtime_status") == "pass":
        lr = obj.get("lifecycle_reports")
        ch.append(("ot::pass_requires_lifecycle",
                   _is_list(obj, "lifecycle_reports") and len(lr) >= 1,
                   "a passing tile view must link >= 1 lifecycle report",
                   C.STREAMING_TILE_LOAD_MISSING))
    ch += _schema_version(obj, RT_OPERATOR_TILE_VIEW, code, "ot::")
    return ch


def _example_operator_tile_view(**over):
    d = {
        "tile_id": "tile_alpine_hub_entry", "region_id": "region_alpine_hub",
        "map_id": "Alpine_GlacialBasin_Debris_Photoreal_01", "tile_role": "hub",
        "neighbors": ["tile_alpine_objective_a", "tile_alpine_objective_b"],
        "anchors": ["anchor_alpine_hub_entry"],
        "lifecycle_reports": [
            "procedural/reports/streaming/lifecycle/tlc_x.json"],
        "route_reports": ["route_alpine_hub_to_a"], "budget_reports": ["budget_standard"],
        "asset_ownership_paths": [
            "procedural/reports/operator/index/asset_ownership_views.json"],
        "runtime_status": "pass", "failure_codes": [],
        "created_by": "worldforge.v2.3", "created_at": "live",
        "schema_version": RT_OPERATOR_TILE_VIEW, "report_type": RT_OPERATOR_TILE_VIEW,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry — one source of truth for dogfood / negatives / fuzz suites.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "RegionDefinition": (
        validate_region_definition, _example_region_definition,
        # entry_tile_id not in tile_ids -> disconnected graph (WF853).
        lambda: _example_region_definition(entry_tile_id="tile_nowhere")),
    "StreamingTileDefinition": (
        validate_tile_definition, _example_tile_definition,
        # tile lists itself as a neighbor -> WF854.
        lambda: _example_tile_definition(
            neighbor_tile_ids=["tile_alpine_hub_entry"])),
    "CrossTileAnchor": (
        validate_cross_tile_anchor, _example_cross_tile_anchor,
        # transition anchor with no linked partner -> WF856.
        lambda: _example_cross_tile_anchor(linked_anchor_ids=[])),
    "CrossTileRoute": (
        validate_cross_tile_route, _example_cross_tile_route,
        # objective pass claimed via grounded_navmesh (headless overclaim) -> WF882.
        lambda: _example_cross_tile_route(traversal_mode="grounded_navmesh")),
    "StreamedMissionBinding": (
        validate_streamed_mission_binding, _example_streamed_mission_binding,
        # only one required tile -> not cross-tile (WF861).
        lambda: _example_streamed_mission_binding(required_tile_ids=["tile_alpine_hub_entry"])),
    "StreamedNPCBinding": (
        validate_streamed_npc_binding, _example_streamed_npc_binding,
        # pressure scope escapes allowed tiles -> WF875.
        lambda: _example_streamed_npc_binding(pressure_tile_scope=["tile_far_away"])),
    "StreamingBudgetProfile": (
        validate_streaming_budget_profile, _example_streaming_budget_profile,
        # zero loaded-tile budget -> WF863.
        lambda: _example_streaming_budget_profile(max_loaded_tiles=0)),
    "TileLifecycleReport": (
        validate_tile_lifecycle_report, _example_tile_lifecycle_report,
        # reload completed but state not preserved -> WF868.
        lambda: _example_tile_lifecycle_report(state_preserved=False)),
    "StreamingRuntimeReport": (
        validate_streaming_runtime_report, _example_streaming_runtime_report,
        # clean report but zero stream transitions -> WF873.
        lambda: _example_streaming_runtime_report(stream_transitions_seen=0)),
    "CrossTileSaveState": (
        validate_cross_tile_save_state, _example_cross_tile_save_state,
        # roundtrip_ok but no tile hashes -> WF869.
        lambda: _example_cross_tile_save_state(tile_state_hashes={})),
    "StreamingEvidenceIndex": (
        validate_streaming_evidence_index, _example_streaming_evidence_index,
        # integrity pass but only 23/24 seen -> WF886.
        lambda: _example_streaming_evidence_index(scenario_count_seen=23)),
    "OperatorRegionView": (
        validate_operator_region_view, _example_operator_region_view,
        # empty streaming_scenarios -> WF885.
        lambda: _example_operator_region_view(streaming_scenarios=[])),
    "OperatorTileView": (
        validate_operator_tile_view, _example_operator_tile_view,
        # passing tile view but no lifecycle report -> WF864.
        lambda: _example_operator_tile_view(lifecycle_reports=[])),
}

CONTRACT_GROUPS = {
    "region": ("RegionDefinition", "StreamingTileDefinition"),
    "anchors_routes": ("CrossTileAnchor", "CrossTileRoute"),
    "bindings": ("StreamedMissionBinding", "StreamedNPCBinding", "StreamingBudgetProfile"),
    "runtime": ("TileLifecycleReport", "StreamingRuntimeReport", "CrossTileSaveState"),
    "index_operator": ("StreamingEvidenceIndex", "OperatorRegionView", "OperatorTileView"),
}

KNOWN_BAD_OWNING_CODE = {
    "RegionDefinition": C.STREAMING_TILE_GRAPH_DISCONNECTED,
    "StreamingTileDefinition": C.STREAMING_NEIGHBOR_NOT_RECIPROCAL,
    "CrossTileAnchor": C.STREAMING_ANCHOR_LINK_BROKEN,
    "CrossTileRoute": C.STREAMING_NAVMESH_OVERCLAIM,
    "StreamedMissionBinding": C.STREAMING_MISSION_BINDING_INVALID,
    "StreamedNPCBinding": C.STREAMING_NPC_PRESSURE_MISSING,
    "StreamingBudgetProfile": C.STREAMING_BUDGET_PROFILE_INVALID,
    "TileLifecycleReport": C.STREAMING_TILE_STATE_LOST,
    "StreamingRuntimeReport": C.STREAMING_REQUIRED_TRANSITION_MISSING,
    "CrossTileSaveState": C.STREAMING_CROSS_TILE_SAVE_MISSING,
    "StreamingEvidenceIndex": C.STREAMING_PARTIAL_MATRIX,
    "OperatorRegionView": C.STREAMING_OPERATOR_VIEW_INVALID,
    "OperatorTileView": C.STREAMING_TILE_LOAD_MISSING,
}

# The set of streaming failure codes this milestone owns (WF851–930).
STREAMING_CODES = tuple(
    v for k, v in vars(C).items()
    if not k.startswith("_") and isinstance(v, str)
    and 851 <= (int(v[2:5]) if v[2:5].isdigit() else -1) <= 930
)
