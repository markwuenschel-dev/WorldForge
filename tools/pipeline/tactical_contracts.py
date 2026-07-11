#!/usr/bin/env python3
"""tactical_contracts.py — WorldForge v2.4 AdvancedAIForge / TacticalBehaviorForge spine.

v2.4 adds the first bounded tactical-behavior substrate for WorldForge NPCs on top of
the v1.7 NPC pressure, v1.8 combat, v2.0 slice, v2.2 quest/faction, and v2.3 streaming
stack. It is NOT AAA combat AI, a GOAP planner, a behavior-tree editor, EQS, RL, or an
LLM-driven NPC. It is the bounded production substrate for generated NPCs making
BOUNDED, INSPECTABLE tactical decisions over terrain, routes, cover, objectives, mission
state, quest/faction context, and streaming tile scope.

Core design principle (handoff §5):
    An NPC tactical decision is valid only if its inputs, options, constraints, selected
    action, execution result, and state mutation are recorded and validate against
    contracts. No black-box AI. No "looked smart in logs" claims. Every tactical claim
    needs evidence.

This module holds the strict, schema-only contracts that define those tactical artifacts
and prove — at authoring time, before any generated behavior or runtime report exists —
that their *shape* is coherent and cannot launder an unknown role/action/stimulus, a
decision trace that selects an INVALID option, a trace with no input, an execution with
no state delta, a state delta that claims change with equal hashes, a coordinated group
of one NPC, a suppression claim with no suppressor, a flank action with no flank route, a
cover action with no cover affordance, a retreat with no retreat anchor, a save/load
claim with no tactical hashes, a budget overrun reported as a pass, a navmesh OVERCLAIM,
or a simulation mislabeled as live runtime, into a green view.

Design mirrors streaming_contracts.py / quest_faction_contracts.py exactly:
    * frozen tuple enums (bounded taxonomy, one source of truth)
    * ``X_REQUIRED`` / ``X_ALLOWED`` field-name tuples
    * ``validate_X(obj, strict=False)`` returning (check, ok, detail, code) tuples built
      from shared runtime_schema (RS) helpers + domain honesty checks
    * ``_example_X(**over)`` canonical-valid factories (``d.update(over)`` spawns
      known-bad variants for the negatives/fuzz suites)
    * a ``CONTRACTS`` registry pairing each validator with a valid + known-bad example,
      ``CONTRACT_GROUPS`` partitioning it, and ``KNOWN_BAD_OWNING_CODE`` naming the code
      each known-bad must be rejected FOR

Schema-only: cross-record resolution (does an anchor resolve to a real generated anchor?
does a route exist on disk? does a cover id resolve to an affordance?) is the job of the
Wave-2/3 authoring validators and Wave-4 runtime validators, which have the datasets +
filesystem in hand. Stdlib only; no jsonschema.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_schema as RS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402

# --------------------------------------------------------------------------- #
# schema_version / report_type dotted namespaces (wf.tactical.<type>.v1)
# --------------------------------------------------------------------------- #
RT_PROFILE = "wf.tactical.behavior_profile.v1"
RT_ROLE = "wf.tactical.role_definition.v1"
RT_AFFORDANCE = "wf.tactical.affordance_map.v1"
RT_NPC_BINDING = "wf.tactical.npc_binding.v1"
RT_DECISION_INPUT = "wf.tactical.decision_input.v1"
RT_DECISION_OPTION = "wf.tactical.decision_option.v1"
RT_DECISION_TRACE = "wf.tactical.decision_trace.v1"
RT_STATE_DELTA = "wf.tactical.state_delta.v1"
RT_GROUP_STATE = "wf.tactical.group_state.v1"
RT_RUNTIME_REPORT = "wf.tactical.runtime_report.v1"
RT_SAVE_STATE = "wf.tactical.save_state.v1"
RT_BUDGET_REPORT = "wf.tactical.budget_report.v1"
RT_EVIDENCE_INDEX = "wf.tactical.evidence_index.v1"
RT_OPERATOR_SCENARIO_VIEW = "wf.tactical.operator_scenario_view.v1"
RT_OPERATOR_NPC_VIEW = "wf.tactical.operator_npc_view.v1"

# --------------------------------------------------------------------------- #
# Bounded taxonomy (one source of truth) — handoff §6.
# --------------------------------------------------------------------------- #
# Tactical roles. reinforcer is the optional stretch role (handoff §6).
TACTICAL_ROLES = ("sentinel", "skirmisher", "suppressor", "reinforcer")
REQUIRED_ROLES = ("sentinel", "skirmisher", "suppressor")
# Tactical actions (handoff §6). The whole bounded action vocabulary.
TACTICAL_ACTIONS = (
    "hold_position", "advance_to_anchor", "retreat_to_anchor", "flank_via_route",
    "use_cover", "leave_cover", "pressure_objective", "protect_objective",
    "pursue_player", "break_pursuit", "call_reinforcement", "disengage",
)
# Actions that REQUIRE a target field to be a real (non-"none") reference when a
# valid option selects them. Maps action -> (target_field, missing_code).
ACTION_TARGET_REQUIREMENT = {
    "flank_via_route": ("target_route_id", C.TACTICAL_FLANK_ROUTE_MISSING),
    "retreat_to_anchor": ("target_anchor_id", C.TACTICAL_RETREAT_ROUTE_MISSING),
    "advance_to_anchor": ("target_anchor_id", C.TACTICAL_ANCHOR_REFERENCE_INVALID),
    "pressure_objective": ("target_anchor_id", C.TACTICAL_ANCHOR_REFERENCE_INVALID),
    "protect_objective": ("target_anchor_id", C.TACTICAL_ANCHOR_REFERENCE_INVALID),
    "use_cover": ("target_cover_id", C.TACTICAL_COVER_REFERENCE_INVALID),
}
# Tactical stimuli (handoff §6). The bounded set of things an NPC may react to.
TACTICAL_STIMULI = (
    "player_seen", "player_lost", "damage_taken", "ally_damaged",
    "objective_threatened", "quest_objective_active", "faction_priority_changed",
    "tile_transition_started", "tile_unload_pending", "health_low",
    "cover_available", "route_blocked",
)
# Tactical pressure profiles (handoff §7).
TACTICAL_PRESSURE_PROFILES = ("baseline_tactical", "high_pressure_tactical")
# Role policy vocabularies (handoff §8.2).
COVER_POLICIES = ("prefer_cover", "opportunistic_cover", "ignore_cover")
RETREAT_POLICIES = ("retreat_when_low", "hold_to_death", "fighting_withdrawal")
OBJECTIVE_POLICIES = ("pressure", "protect", "ignore")
GROUP_POLICIES = ("solo", "loose_pack", "coordinated_squad")
# Group roles (handoff §8.9 group_role).
GROUP_ROLES = ("fireteam", "overwatch", "pursuit", "mixed")
# Group coordination states (handoff §8.9).
COORDINATION_STATES = ("none", "loose", "coordinated", "broken", "invalid")
# Player visibility / streaming state / objective-status vocab for decision inputs.
PLAYER_VISIBILITY = ("visible", "occluded", "lost", "unknown")
STREAMING_STATES = ("resident", "transitioning", "unload_pending")
CONTEXT_STATUS = ("active", "inactive", "threatened", "updated", "none")
# Execution results for a decision trace.
EXECUTION_RESULTS = ("succeeded", "failed", "interrupted", "no_op")
# Budget classification (shared with streaming semantics): advisory = soft-over,
# exceeded = hard-cap overrun that blocks a runtime pass.
BUDGET_RESULTS = ("pass", "advisory", "exceeded")
CLASSIFICATIONS = ("within_budget", "advisory", "over_budget")
# Save/load roundtrip vocabulary.
SAVE_LOAD_RESULTS = ("roundtrip_ok", "roundtrip_failed", "not_run", "missing")
# Evidence-index integrity verdicts.
INTEGRITY_RESULTS = ("pass", "fail", "blocked")
# Streaming profiles a tactical scenario runs over (mirror of the v2.3 set).
STREAMING_PROFILES = ("adjacent_tile_crossing", "hub_to_spoke_transition",
                      "three_tile_chain")
# Honest runtime-mode labels (handoff §12): the alpha must NOT label a deterministic
# simulation as live UE tactical AI. Both are acceptable if labeled honestly.
RUNTIME_MODES = ("deterministic_tactical_simulation", "live_tactical_runtime")
LIVE_RUNTIME_MODES = ("live_tactical_runtime",)
# Required tactical-action classes the MATRIX as a whole must cover (handoff §8.10/§8.13).
# Not every scenario flanks/retreats/uses cover, but the matrix must prove each once.
REQUIRED_COVERAGE_ACTIONS = (
    "hold_position", "advance_to_anchor", "retreat_to_anchor", "flank_via_route",
    "use_cover", "pressure_objective",
)

# The bounded v2.4 matrix (handoff §3/§11): 2 regions × 3 roles × 2 profiles × 2 seeds
# = 24 tactical scenarios (no new 120 matrix).
EXPECTED_SCENARIO_COUNT = 24
EXPECTED_REGION_COUNT = 2
EXPECTED_ROLE_COUNT = 3
EXPECTED_PROFILE_COUNT = 2

# The shared deterministic authoring timestamp (NOT wall-clock).
AUTHORING_TS = "2026-07-11T00:00:00+00:00"

# Generated / report roots (repo-relative).
PROFILES_REL = "procedural/generated/tactical/profiles"
ROLES_REL = "procedural/generated/tactical/roles"
AFFORDANCES_REL = "procedural/generated/tactical/affordances"
BINDINGS_REL = "procedural/generated/tactical/bindings"
GROUPS_REL = "procedural/generated/tactical/groups"
TAC_REPORTS_REL = "procedural/reports/tactical"

_WF_CODE_RE = re.compile(r"^WF\d{3}_[A-Z0-9_]+$")


# --------------------------------------------------------------------------- #
# small local helpers (mirror streaming_contracts.py)
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


def _num(obj, field, code, prefix, allow_zero=True):
    return RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)


def _float_range(obj, field, code, prefix, lo=0.0, hi=1.0):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = RS.is_number(v) and lo <= float(v) <= hi
    return [("{}{}_in_range".format(prefix, field), ok,
             "{} must be a finite number in [{}, {}] (got {!r})".format(field, lo, hi, v),
             code)]


def _list_of_str(obj, field, code, prefix, min_len=0, max_len=None):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) >= min_len and all(isinstance(x, str) for x in v)
    if ok and max_len is not None:
        ok = len(v) <= max_len
    return [("{}{}_str_list".format(prefix, field), ok,
             "{} must be a list of {}..{} strings".format(field, min_len, max_len or "N"),
             code)]


def _subset(obj, field, allowed, code, prefix, min_len=0):
    v = obj.get(field) if isinstance(obj, dict) else None
    is_list = isinstance(v, list) and all(isinstance(x, str) for x in v)
    ok = is_list and len(v) >= min_len and all(x in allowed for x in v)
    bad = sorted(set(v) - set(allowed)) if is_list else v
    return [("{}{}_subset".format(prefix, field), ok,
             "{} must be a >= {}-length subset of the bounded set (unknown: {})".format(
                 field, min_len, bad), code)]


def _is_list(obj, field):
    return isinstance(obj.get(field), list) if isinstance(obj, dict) else False


def _is_dict(obj, field):
    return isinstance(obj.get(field), dict) if isinstance(obj, dict) else False


def _finite_vec(v, n=3):
    return isinstance(v, list) and len(v) == n and all(RS.is_number(x) for x in v)


def _schema_version(obj, expected, code, prefix):
    sv = obj.get("schema_version") if isinstance(obj, dict) else None
    return [("{}schema_version".format(prefix), sv == expected,
             "schema_version must be {!r} (got {!r})".format(expected, sv), code)]


# =========================================================================== #
# 1. TacticalBehaviorProfile (WF931) — handoff §8.1
# =========================================================================== #
PROFILE_REQUIRED = (
    "profile_id", "tactical_pressure_profile", "roles_allowed", "actions_allowed",
    "stimuli_allowed", "decision_cadence_ms", "aggression", "cover_preference",
    "flank_preference", "retreat_health_threshold", "objective_pressure_weight",
    "reinforcement_threshold", "max_active_tactical_npcs", "max_decisions_per_minute",
    "budget_profile_id", "schema_version",
)
PROFILE_ALLOWED = PROFILE_REQUIRED + ("meta", "report_type", "created_by", "created_at",
                                      "notes", "display_key")
_PROFILE_WEIGHTS = ("aggression", "cover_preference", "flank_preference",
                    "retreat_health_threshold", "objective_pressure_weight",
                    "reinforcement_threshold")


def validate_tactical_behavior_profile(obj, strict=False):
    code = C.TACTICAL_PROFILE_INVALID
    ch = RS.check_required(obj, PROFILE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, PROFILE_ALLOWED, code, strict)
    for f in ("profile_id", "budget_profile_id"):
        ch += _str(obj, f, code, "bp::")
    ch += RS.check_enum(obj, "tactical_pressure_profile", TACTICAL_PRESSURE_PROFILES,
                        code, prefix="bp::")
    ch += _subset(obj, "roles_allowed", TACTICAL_ROLES, C.TACTICAL_UNKNOWN_ROLE, "bp::", min_len=1)
    ch += _subset(obj, "actions_allowed", TACTICAL_ACTIONS, C.TACTICAL_UNKNOWN_ACTION, "bp::", min_len=1)
    ch += _subset(obj, "stimuli_allowed", TACTICAL_STIMULI, C.TACTICAL_UNKNOWN_STIMULUS, "bp::", min_len=1)
    ch += _int(obj, "decision_cadence_ms", code, "bp::", allow_zero=False)
    for f in _PROFILE_WEIGHTS:
        ch += _float_range(obj, f, code, "bp::", 0.0, 1.0)
    ch += _int(obj, "max_active_tactical_npcs", code, "bp::", allow_zero=False)
    ch += _int(obj, "max_decisions_per_minute", code, "bp::", allow_zero=False)
    ch += _schema_version(obj, RT_PROFILE, code, "bp::")
    return ch


def _example_tactical_behavior_profile(**over):
    d = {
        "profile_id": "tac_profile_baseline_tactical",
        "tactical_pressure_profile": "baseline_tactical",
        "roles_allowed": ["sentinel", "skirmisher", "suppressor"],
        "actions_allowed": list(TACTICAL_ACTIONS),
        "stimuli_allowed": list(TACTICAL_STIMULI),
        "decision_cadence_ms": 750,
        "aggression": 0.45,
        "cover_preference": 0.6,
        "flank_preference": 0.35,
        "retreat_health_threshold": 0.3,
        "objective_pressure_weight": 0.5,
        "reinforcement_threshold": 0.4,
        "max_active_tactical_npcs": 8,
        "max_decisions_per_minute": 80,
        "budget_profile_id": "tac_budget_standard",
        "display_key": "tactical.profile.baseline",
        "created_by": "worldforge.v2.4",
        "created_at": AUTHORING_TS,
        "schema_version": RT_PROFILE,
        "report_type": RT_PROFILE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 2. TacticalRoleDefinition (WF932) — handoff §8.2
# =========================================================================== #
ROLE_REQUIRED = (
    "role_id", "display_key", "allowed_actions", "preferred_actions",
    "forbidden_actions", "min_engagement_distance", "max_engagement_distance",
    "cover_usage_policy", "retreat_policy", "objective_policy", "group_policy",
    "schema_version",
)
ROLE_ALLOWED = ROLE_REQUIRED + ("meta", "report_type", "created_by", "created_at", "notes")


def validate_tactical_role_definition(obj, strict=False):
    code = C.TACTICAL_ROLE_INVALID
    ch = RS.check_required(obj, ROLE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, ROLE_ALLOWED, code, strict)
    ch += RS.check_enum(obj, "role_id", TACTICAL_ROLES, C.TACTICAL_UNKNOWN_ROLE, prefix="rl::")
    ch += _str(obj, "display_key", code, "rl::")
    ch += _subset(obj, "allowed_actions", TACTICAL_ACTIONS, C.TACTICAL_UNKNOWN_ACTION, "rl::", min_len=1)
    ch += _subset(obj, "preferred_actions", TACTICAL_ACTIONS, C.TACTICAL_UNKNOWN_ACTION, "rl::")
    ch += _subset(obj, "forbidden_actions", TACTICAL_ACTIONS, C.TACTICAL_UNKNOWN_ACTION, "rl::")
    ch += RS.check_enum(obj, "cover_usage_policy", COVER_POLICIES, code, prefix="rl::")
    ch += RS.check_enum(obj, "retreat_policy", RETREAT_POLICIES, code, prefix="rl::")
    ch += RS.check_enum(obj, "objective_policy", OBJECTIVE_POLICIES, code, prefix="rl::")
    ch += RS.check_enum(obj, "group_policy", GROUP_POLICIES, code, prefix="rl::")
    ch += _num(obj, "min_engagement_distance", code, "rl::", allow_zero=True)
    ch += _num(obj, "max_engagement_distance", code, "rl::", allow_zero=False)
    allowed = set(obj.get("allowed_actions") or []) if _is_list(obj, "allowed_actions") else set()
    pref = set(obj.get("preferred_actions") or []) if _is_list(obj, "preferred_actions") else set()
    forb = set(obj.get("forbidden_actions") or []) if _is_list(obj, "forbidden_actions") else set()
    # honesty: preferred actions must be a subset of allowed actions.
    ch.append(("rl::preferred_subset_allowed", pref <= allowed,
               "preferred_actions must be a subset of allowed_actions (leak: {})".format(
                   sorted(pref - allowed)), code))
    # honesty: forbidden actions must be disjoint from allowed actions.
    ch.append(("rl::forbidden_disjoint_allowed", forb.isdisjoint(allowed),
               "forbidden_actions must be disjoint from allowed_actions (overlap: {})".format(
                   sorted(forb & allowed)), code))
    # honesty: engagement distances finite and ordered (min <= max).
    lo, hi = obj.get("min_engagement_distance"), obj.get("max_engagement_distance")
    if RS.is_number(lo) and RS.is_number(hi):
        ch.append(("rl::distances_ordered", lo <= hi,
                   "min_engagement_distance must be <= max_engagement_distance", code))
    ch += _schema_version(obj, RT_ROLE, code, "rl::")
    return ch


def _example_tactical_role_definition(**over):
    d = {
        "role_id": "sentinel",
        "display_key": "tactical.role.sentinel",
        "allowed_actions": ["hold_position", "use_cover", "leave_cover",
                            "protect_objective", "pressure_objective", "advance_to_anchor",
                            "retreat_to_anchor", "call_reinforcement", "disengage"],
        "preferred_actions": ["hold_position", "protect_objective", "use_cover"],
        "forbidden_actions": ["flank_via_route", "pursue_player", "break_pursuit"],
        "min_engagement_distance": 200.0,
        "max_engagement_distance": 4000.0,
        "cover_usage_policy": "prefer_cover",
        "retreat_policy": "fighting_withdrawal",
        "objective_policy": "protect",
        "group_policy": "coordinated_squad",
        "created_by": "worldforge.v2.4",
        "created_at": AUTHORING_TS,
        "schema_version": RT_ROLE,
        "report_type": RT_ROLE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 3. TacticalAffordanceMap (WF933) — handoff §8.3
# =========================================================================== #
AFFORDANCE_REQUIRED = (
    "affordance_map_id", "region_id", "tile_id", "scenario_id", "cover_points",
    "vantage_points", "retreat_anchors", "flank_routes", "objective_pressure_points",
    "line_of_sight_zones", "hazard_zones", "streaming_transition_zones",
    "source_reports", "schema_version",
)
AFFORDANCE_ALLOWED = AFFORDANCE_REQUIRED + ("meta", "report_type", "created_by",
                                            "created_at", "notes")
_AFFORDANCE_ZONE_LISTS = ("vantage_points", "line_of_sight_zones", "hazard_zones",
                          "streaming_transition_zones", "objective_pressure_points")


def _cover_point_ok(p):
    return (isinstance(p, dict) and isinstance(p.get("cover_id"), str)
            and bool(p.get("cover_id", "").strip()) and _finite_vec(p.get("location"), 3))


def validate_tactical_affordance_map(obj, strict=False):
    code = C.TACTICAL_AFFORDANCE_MAP_INVALID
    ch = RS.check_required(obj, AFFORDANCE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, AFFORDANCE_ALLOWED, code, strict)
    for f in ("affordance_map_id", "region_id", "tile_id", "scenario_id"):
        ch += _str(obj, f, code, "af::")
    # cover_points: each must be a well-formed {cover_id, location[3]} — a malformed
    # cover point is a cover-reference the runtime cannot resolve (WF947). Cover may be
    # explicitly absent (empty list) for a tile with no cover.
    cps = obj.get("cover_points") if _is_list(obj, "cover_points") else None
    ch.append(("af::cover_points_list", cps is not None,
               "cover_points must be a list (may be empty)", code))
    if cps is not None:
        ch.append(("af::cover_points_well_formed", all(_cover_point_ok(p) for p in cps),
                   "every cover point must be {cover_id, location:[x,y,z]}",
                   C.TACTICAL_COVER_REFERENCE_INVALID))
    ch += _list_of_str(obj, "retreat_anchors", C.TACTICAL_ANCHOR_REFERENCE_INVALID, "af::")
    ch += _list_of_str(obj, "flank_routes", C.TACTICAL_ROUTE_REFERENCE_INVALID, "af::")
    for f in _AFFORDANCE_ZONE_LISTS:
        ch.append(("af::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # honesty: hazard zones must be bounded — each {location[3], radius>0}.
    hz = obj.get("hazard_zones") if _is_list(obj, "hazard_zones") else []
    ch.append(("af::hazard_zones_bounded",
               all(isinstance(z, dict) and _finite_vec(z.get("location"), 3)
                   and RS.is_number(z.get("radius")) and z.get("radius") > 0 for z in hz),
               "every hazard zone must be a bounded {location:[x,y,z], radius>0}", code))
    # honesty: source reports must exist (non-empty) — an affordance map with no source
    # evidence is unfalsifiable.
    ch += _list_of_str(obj, "source_reports", code, "af::", min_len=1)
    ch += _schema_version(obj, RT_AFFORDANCE, code, "af::")
    return ch


def _example_tactical_affordance_map(**over):
    d = {
        "affordance_map_id": "afm_region_alpine_hub_tile_alpine_hub_entry_s1",
        "region_id": "region_alpine_hub",
        "tile_id": "tile_alpine_hub_entry",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "cover_points": [
            {"cover_id": "cover_alpine_hub_rock_01", "location": [1200.0, 340.0, 64.0]},
            {"cover_id": "cover_alpine_hub_debris_02", "location": [-800.0, 900.0, 48.0]},
        ],
        "vantage_points": [{"vantage_id": "vp_alpine_hub_ridge", "location": [0.0, 2400.0, 512.0]}],
        "retreat_anchors": ["anchor_alpine_hub_entry", "anchor_alpine_hub_to_a"],
        "flank_routes": ["route_alpine_hub_to_a"],
        "objective_pressure_points": [
            {"point_id": "opp_alpine_a_objective", "location": [12800.0, 0.0, 128.0]}],
        "line_of_sight_zones": [{"zone_id": "los_alpine_hub_open", "location": [600.0, 0.0, 128.0],
                                 "radius": 3000.0}],
        "hazard_zones": [{"hazard_id": "hz_alpine_crevasse", "location": [400.0, -1200.0, 0.0],
                          "radius": 800.0}],
        "streaming_transition_zones": [
            {"transition_id": "stz_alpine_hub_to_a", "location": [12800.0, 0.0, 512.0]}],
        "source_reports": [
            "procedural/generated/regions/region_alpine_hub.json",
            "procedural/generated/routes/route_alpine_hub_to_a.json"],
        "created_by": "worldforge.v2.4",
        "created_at": AUTHORING_TS,
        "schema_version": RT_AFFORDANCE,
        "report_type": RT_AFFORDANCE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 4. TacticalNPCBinding (WF934) — handoff §8.4
# =========================================================================== #
NPC_BINDING_REQUIRED = (
    "binding_id", "scenario_id", "region_id", "tile_id", "npc_profile_id",
    "tactical_role_id", "behavior_profile_id", "spawn_anchor_id", "allowed_tile_ids",
    "allowed_route_ids", "allowed_cover_ids", "quest_context_id", "faction_context_id",
    "streaming_scope", "save_load_key", "schema_version",
)
NPC_BINDING_ALLOWED = NPC_BINDING_REQUIRED + ("meta", "report_type", "created_by",
                                              "created_at", "notes", "seed", "group_id")


def validate_tactical_npc_binding(obj, strict=False):
    code = C.TACTICAL_NPC_BINDING_INVALID
    ch = RS.check_required(obj, NPC_BINDING_REQUIRED, code)
    ch += RS.check_no_unknown(obj, NPC_BINDING_ALLOWED, code, strict)
    for f in ("binding_id", "scenario_id", "region_id", "tile_id", "npc_profile_id",
              "behavior_profile_id", "spawn_anchor_id", "quest_context_id",
              "faction_context_id", "save_load_key"):
        ch += _str(obj, f, code, "nb::")
    ch += RS.check_enum(obj, "tactical_role_id", TACTICAL_ROLES, C.TACTICAL_UNKNOWN_ROLE,
                        prefix="nb::")
    ch += _list_of_str(obj, "allowed_tile_ids", code, "nb::", min_len=1)
    ch += _list_of_str(obj, "allowed_route_ids", C.TACTICAL_ROUTE_REFERENCE_INVALID, "nb::")
    ch += _list_of_str(obj, "allowed_cover_ids", C.TACTICAL_COVER_REFERENCE_INVALID, "nb::")
    ch.append(("nb::streaming_scope_dict", _is_dict(obj, "streaming_scope"),
               "streaming_scope must be a dict", code))
    allowed = obj.get("allowed_tile_ids") if _is_list(obj, "allowed_tile_ids") else []
    # honesty: the spawn tile must be within the allowed tile scope — an NPC can never be
    # bound to a tile it is not allowed in (and thus may be unloaded).
    ch.append(("nb::tile_in_allowed", obj.get("tile_id") in allowed,
               "tile_id must be one of allowed_tile_ids", code))
    # honesty: the streaming scope's allowed tiles must not exceed the binding's allowed
    # tiles (bounded scope — no leak past the streaming binding).
    scope = obj.get("streaming_scope") if _is_dict(obj, "streaming_scope") else {}
    scope_tiles = set(scope.get("allowed_tile_ids") or []) if isinstance(scope, dict) else set()
    ch.append(("nb::scope_subset_allowed", scope_tiles <= set(allowed),
               "streaming_scope.allowed_tile_ids must be a subset of allowed_tile_ids "
               "(leak: {})".format(sorted(scope_tiles - set(allowed))), code))
    ch += _schema_version(obj, RT_NPC_BINDING, code, "nb::")
    return ch


def _example_tactical_npc_binding(**over):
    d = {
        "binding_id": "tnb_region_alpine_hub_sentinel_baseline_tactical_s1",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "region_id": "region_alpine_hub",
        "tile_id": "tile_alpine_objective_a",
        "npc_profile_id": "npc_sentry_baseline",
        "tactical_role_id": "sentinel",
        "behavior_profile_id": "tac_profile_baseline_tactical",
        "spawn_anchor_id": "anchor_alpine_a_npc_spawn",
        "allowed_tile_ids": ["tile_alpine_objective_a", "tile_alpine_hub_entry"],
        "allowed_route_ids": ["route_alpine_hub_to_a"],
        "allowed_cover_ids": ["cover_alpine_hub_rock_01", "cover_alpine_a_wall_01"],
        "quest_context_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "faction_context_id": "faction_alpine_wardens",
        "streaming_scope": {"region_id": "region_alpine_hub",
                            "allowed_tile_ids": ["tile_alpine_objective_a"]},
        "save_load_key": "sl_tac_npc_alpine_a_sentinel",
        "group_id": "tac_group_alpine_a_fireteam_s1",
        "seed": 1,
        "created_by": "worldforge.v2.4",
        "created_at": AUTHORING_TS,
        "schema_version": RT_NPC_BINDING,
        "report_type": RT_NPC_BINDING,
    }
    d.update(over)
    return d


# =========================================================================== #
# 5. TacticalDecisionInput (WF938) — handoff §8.5
# =========================================================================== #
DECISION_INPUT_REQUIRED = (
    "decision_input_id", "scenario_id", "npc_id", "timestamp", "current_tile_id",
    "current_anchor_id", "health_state", "player_visibility", "distance_to_player",
    "objective_state", "quest_state", "faction_state", "available_cover_ids",
    "available_route_ids", "active_stimuli", "streaming_state", "schema_version",
)
DECISION_INPUT_ALLOWED = DECISION_INPUT_REQUIRED + ("meta", "report_type", "created_by",
                                                    "created_at", "notes")


def _health_state_ok(h):
    if not isinstance(h, dict):
        return False
    hp, hp_max = h.get("hp"), h.get("hp_max")
    return RS.is_number(hp) and RS.is_number(hp_max) and hp_max > 0 and 0 <= hp <= hp_max


def validate_tactical_decision_input(obj, strict=False):
    code = C.TACTICAL_DECISION_INPUT_INVALID
    ch = RS.check_required(obj, DECISION_INPUT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, DECISION_INPUT_ALLOWED, code, strict)
    for f in ("decision_input_id", "scenario_id", "npc_id", "timestamp",
              "current_tile_id", "current_anchor_id"):
        ch += _str(obj, f, code, "di::")
    ch.append(("di::health_state_ok", _health_state_ok(obj.get("health_state")),
               "health_state must be {hp, hp_max>0} with 0<=hp<=hp_max", code))
    ch += RS.check_enum(obj, "player_visibility", PLAYER_VISIBILITY, code, prefix="di::")
    ch += RS.check_enum(obj, "streaming_state", STREAMING_STATES, code, prefix="di::")
    for f in ("objective_state", "quest_state", "faction_state"):
        ch += RS.check_enum(obj, f, CONTEXT_STATUS, code, prefix="di::")
    ch += _num(obj, "distance_to_player", code, "di::", allow_zero=True)
    ch += _list_of_str(obj, "available_cover_ids", C.TACTICAL_COVER_REFERENCE_INVALID, "di::")
    ch += _list_of_str(obj, "available_route_ids", C.TACTICAL_ROUTE_REFERENCE_INVALID, "di::")
    # honesty: active stimuli must be a non-empty subset of the bounded stimulus set —
    # an unknown stimulus is a black-box input (WF937).
    ch += _subset(obj, "active_stimuli", TACTICAL_STIMULI, C.TACTICAL_UNKNOWN_STIMULUS,
                  "di::", min_len=1)
    ch += _schema_version(obj, RT_DECISION_INPUT, code, "di::")
    return ch


def _example_tactical_decision_input(**over):
    d = {
        "decision_input_id": "tdi_alpine_a_sentinel_s1_t0001",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "npc_id": "tacnpc_alpine_a_sentinel_01",
        "timestamp": "t+0001",
        "current_tile_id": "tile_alpine_objective_a",
        "current_anchor_id": "anchor_alpine_a_npc_spawn",
        "health_state": {"hp": 80.0, "hp_max": 100.0},
        "player_visibility": "visible",
        "distance_to_player": 1800.0,
        "objective_state": "threatened",
        "quest_state": "active",
        "faction_state": "active",
        "available_cover_ids": ["cover_alpine_hub_rock_01"],
        "available_route_ids": ["route_alpine_hub_to_a"],
        "active_stimuli": ["player_seen", "objective_threatened", "cover_available"],
        "streaming_state": "resident",
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_DECISION_INPUT,
        "report_type": RT_DECISION_INPUT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 6. TacticalDecisionOption (WF939) — handoff §8.6
# =========================================================================== #
OPTION_REQUIRED = (
    "option_id", "decision_input_id", "action_type", "target_anchor_id",
    "target_cover_id", "target_route_id", "expected_utility", "risk_score",
    "cost_score", "valid", "rejection_reason", "schema_version",
)
OPTION_ALLOWED = OPTION_REQUIRED + ("meta", "report_type", "created_by", "created_at", "notes")
_NONE_VALUES = ("", "none", "None", None)


def _is_none_ref(v):
    return v in _NONE_VALUES or (isinstance(v, str) and v.strip().lower() == "none")


def validate_tactical_decision_option(obj, strict=False):
    code = C.TACTICAL_DECISION_OPTION_INVALID
    ch = RS.check_required(obj, OPTION_REQUIRED, code)
    ch += RS.check_no_unknown(obj, OPTION_ALLOWED, code, strict)
    for f in ("option_id", "decision_input_id"):
        ch += _str(obj, f, code, "op::")
    ch += RS.check_enum(obj, "action_type", TACTICAL_ACTIONS, C.TACTICAL_UNKNOWN_ACTION,
                        prefix="op::")
    for f in ("expected_utility", "risk_score", "cost_score"):
        ch.append(("op::{}_finite".format(f), RS.is_number(obj.get(f)),
                   "{} must be a finite number".format(f), code))
    ch += _bool(obj, "valid", code, "op::")
    valid = obj.get("valid")
    reason = obj.get("rejection_reason")
    action = obj.get("action_type")
    # honesty: a VALID option that selects a target-requiring action must carry a real
    # (non-"none") target reference; a missing target is the specific missing-affordance
    # failure for that action class.
    if valid is True and isinstance(action, str) and action in ACTION_TARGET_REQUIREMENT:
        tfield, tcode = ACTION_TARGET_REQUIREMENT[action]
        ch.append(("op::valid_{}_has_target".format(action),
                   not _is_none_ref(obj.get(tfield)),
                   "a valid {} option must carry a real {}".format(action, tfield), tcode))
    # honesty: an INVALID option must include a rejection reason; a VALID option must not.
    if valid is False:
        ch.append(("op::invalid_has_reason",
                   isinstance(reason, str) and not _is_none_ref(reason),
                   "an invalid option must include a non-empty rejection_reason", code))
    if valid is True:
        ch.append(("op::valid_no_reason", _is_none_ref(reason),
                   "a valid option must not carry a rejection_reason", code))
    ch += _schema_version(obj, RT_DECISION_OPTION, code, "op::")
    return ch


def _example_tactical_decision_option(**over):
    d = {
        "option_id": "tdo_alpine_a_sentinel_s1_t0001_flank",
        "decision_input_id": "tdi_alpine_a_sentinel_s1_t0001",
        "action_type": "flank_via_route",
        "target_anchor_id": "none",
        "target_cover_id": "none",
        "target_route_id": "route_alpine_hub_to_a",
        "expected_utility": 0.62,
        "risk_score": 0.4,
        "cost_score": 0.3,
        "valid": True,
        "rejection_reason": "none",
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_DECISION_OPTION,
        "report_type": RT_DECISION_OPTION,
    }
    d.update(over)
    return d


# =========================================================================== #
# 7. TacticalDecisionTrace (WF940) — handoff §8.7
# =========================================================================== #
TRACE_REQUIRED = (
    "trace_id", "scenario_id", "npc_id", "decision_input_id", "options_considered",
    "selected_option_id", "selected_action", "selection_reason", "constraints_applied",
    "execution_started", "execution_completed", "execution_result", "state_delta_id",
    "failure_codes", "schema_version",
)
TRACE_ALLOWED = TRACE_REQUIRED + ("meta", "report_type", "created_by", "created_at", "notes")


def validate_tactical_decision_trace(obj, strict=False):
    code = C.TACTICAL_DECISION_TRACE_INVALID
    ch = RS.check_required(obj, TRACE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, TRACE_ALLOWED, code, strict)
    for f in ("trace_id", "scenario_id", "npc_id", "decision_input_id",
              "selected_option_id", "selection_reason"):
        ch += _str(obj, f, code, "tr::")
    ch += RS.check_enum(obj, "selected_action", TACTICAL_ACTIONS, C.TACTICAL_UNKNOWN_ACTION,
                        prefix="tr::")
    ch += RS.check_enum(obj, "execution_result", EXECUTION_RESULTS, C.TACTICAL_EXECUTION_MISSING,
                        prefix="tr::")
    for f in ("execution_started", "execution_completed"):
        ch += _bool(obj, f, code, "tr::")
    ch.append(("tr::constraints_applied_list", _is_list(obj, "constraints_applied"),
               "constraints_applied must be a list", code))
    ch.append(("tr::failure_codes_list", _is_list(obj, "failure_codes"),
               "failure_codes must be a list", code))
    # options_considered: non-empty list of {option_id, valid} dicts.
    opts = obj.get("options_considered") if _is_list(obj, "options_considered") else None
    opts_ok = (opts is not None and len(opts) >= 1
               and all(isinstance(o, dict) and isinstance(o.get("option_id"), str)
                       and isinstance(o.get("valid"), bool) for o in opts))
    ch.append(("tr::options_considered_well_formed", opts_ok,
               "options_considered must be >=1 {option_id, valid} dicts", code))
    # honesty: the selected option must EXIST among the options considered.
    opt_by_id = {o.get("option_id"): o for o in opts} if opts_ok else {}
    sel = obj.get("selected_option_id")
    ch.append(("tr::selected_option_exists", sel in opt_by_id,
               "selected_option_id must be one of options_considered", code))
    # honesty: the selected option must be VALID (an NPC may not execute a rejected option).
    if sel in opt_by_id:
        ch.append(("tr::selected_option_valid", opt_by_id[sel].get("valid") is True,
                   "selected option must be valid=true (cannot execute a rejected option)",
                   C.TACTICAL_SELECTED_INVALID_OPTION))
    # honesty: a CLEAN trace (empty failure_codes) requires a completed execution that
    # succeeded, and a recorded state delta (execution that changes NPC state).
    clean = _is_list(obj, "failure_codes") and len(obj.get("failure_codes") or []) == 0
    if clean:
        ch.append(("tr::clean_execution_completed", obj.get("execution_completed") is True,
                   "a clean trace requires execution_completed=true",
                   C.TACTICAL_EXECUTION_MISSING))
        ch.append(("tr::clean_has_state_delta",
                   isinstance(obj.get("state_delta_id"), str)
                   and not _is_none_ref(obj.get("state_delta_id")),
                   "a clean trace requires a recorded state_delta_id",
                   C.TACTICAL_STATE_NOT_MUTATED))
        ch.append(("tr::clean_result_terminal",
                   obj.get("execution_result") in ("succeeded", "no_op"),
                   "a clean trace requires execution_result in (succeeded, no_op)",
                   C.TACTICAL_EXECUTION_MISSING))
    ch += _schema_version(obj, RT_DECISION_TRACE, code, "tr::")
    return ch


def _example_tactical_decision_trace(**over):
    d = {
        "trace_id": "tdt_alpine_a_sentinel_s1_t0001",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "npc_id": "tacnpc_alpine_a_sentinel_01",
        "decision_input_id": "tdi_alpine_a_sentinel_s1_t0001",
        "options_considered": [
            {"option_id": "opt_hold", "valid": True},
            {"option_id": "opt_use_cover", "valid": True},
            {"option_id": "opt_flank", "valid": False},
        ],
        "selected_option_id": "opt_use_cover",
        "selected_action": "use_cover",
        "selection_reason": "cover_available + player_seen at mid distance; prefer_cover policy",
        "constraints_applied": ["cover_in_allowed_ids", "tile_resident", "role_allows_use_cover"],
        "execution_started": True,
        "execution_completed": True,
        "execution_result": "succeeded",
        "state_delta_id": "tsd_alpine_a_sentinel_s1_t0001",
        "failure_codes": [],
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_DECISION_TRACE,
        "report_type": RT_DECISION_TRACE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 8. TacticalStateDelta (WF943) — handoff §8.8
# =========================================================================== #
STATE_DELTA_REQUIRED = (
    "delta_id", "scenario_id", "npc_id", "pre_state_hash", "post_state_hash",
    "position_changed", "cover_state_changed", "engagement_state_changed",
    "target_changed", "group_state_changed", "quest_pressure_changed",
    "faction_pressure_changed", "streaming_scope_changed", "schema_version",
)
STATE_DELTA_ALLOWED = STATE_DELTA_REQUIRED + ("meta", "report_type", "created_by",
                                              "created_at", "notes", "quest_context_id",
                                              "faction_context_id", "tile_transition_id")
_DELTA_FLAGS = ("position_changed", "cover_state_changed", "engagement_state_changed",
                "target_changed", "group_state_changed", "quest_pressure_changed",
                "faction_pressure_changed", "streaming_scope_changed")


def validate_tactical_state_delta(obj, strict=False):
    code = C.TACTICAL_STATE_DELTA_INVALID
    ch = RS.check_required(obj, STATE_DELTA_REQUIRED, code)
    ch += RS.check_no_unknown(obj, STATE_DELTA_ALLOWED, code, strict)
    for f in ("delta_id", "scenario_id", "npc_id", "pre_state_hash", "post_state_hash"):
        ch += _str(obj, f, code, "sd::")
    for f in _DELTA_FLAGS:
        ch += _bool(obj, f, code, "sd::")
    any_changed = any(obj.get(f) is True for f in _DELTA_FLAGS)
    pre, post = obj.get("pre_state_hash"), obj.get("post_state_hash")
    # honesty: if ANY changed flag is true, the post-state hash MUST differ from the
    # pre-state hash — a claimed change with equal hashes is fake mutation (WF944).
    if any_changed:
        ch.append(("sd::changed_requires_new_hash",
                   isinstance(pre, str) and isinstance(post, str) and pre != post,
                   "a state delta with any changed flag must have post_state_hash != "
                   "pre_state_hash", C.TACTICAL_STATE_NOT_MUTATED))
    # honesty: a quest/faction pressure change requires the corresponding context id.
    if obj.get("quest_pressure_changed") is True:
        ch.append(("sd::quest_pressure_needs_context",
                   isinstance(obj.get("quest_context_id"), str)
                   and not _is_none_ref(obj.get("quest_context_id")),
                   "quest_pressure_changed=true requires a quest_context_id",
                   C.TACTICAL_QUEST_STATE_MISSING))
    if obj.get("faction_pressure_changed") is True:
        ch.append(("sd::faction_pressure_needs_context",
                   isinstance(obj.get("faction_context_id"), str)
                   and not _is_none_ref(obj.get("faction_context_id")),
                   "faction_pressure_changed=true requires a faction_context_id",
                   C.TACTICAL_FACTION_STATE_MISSING))
    # honesty: a streaming scope change requires a tile transition evidence id.
    if obj.get("streaming_scope_changed") is True:
        ch.append(("sd::streaming_change_needs_transition",
                   isinstance(obj.get("tile_transition_id"), str)
                   and not _is_none_ref(obj.get("tile_transition_id")),
                   "streaming_scope_changed=true requires a tile_transition_id", code))
    ch += _schema_version(obj, RT_STATE_DELTA, code, "sd::")
    return ch


def _example_tactical_state_delta(**over):
    d = {
        "delta_id": "tsd_alpine_a_sentinel_s1_t0001",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "npc_id": "tacnpc_alpine_a_sentinel_01",
        "pre_state_hash": "sha256:pre_0001",
        "post_state_hash": "sha256:post_0001",
        "position_changed": True,
        "cover_state_changed": True,
        "engagement_state_changed": False,
        "target_changed": False,
        "group_state_changed": False,
        "quest_pressure_changed": False,
        "faction_pressure_changed": False,
        "streaming_scope_changed": False,
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_STATE_DELTA,
        "report_type": RT_STATE_DELTA,
    }
    d.update(over)
    return d


# =========================================================================== #
# 9. TacticalGroupState (WF945) — handoff §8.9
# =========================================================================== #
GROUP_STATE_REQUIRED = (
    "group_id", "scenario_id", "npc_ids", "group_role", "shared_target_id",
    "shared_objective_id", "coordination_state", "suppression_active", "flank_active",
    "reinforcement_requested", "retreat_called", "schema_version",
)
GROUP_STATE_ALLOWED = GROUP_STATE_REQUIRED + ("meta", "report_type", "created_by",
                                              "created_at", "notes", "roles_present",
                                              "flank_route_id")


def validate_tactical_group_state(obj, strict=False):
    code = C.TACTICAL_GROUP_STATE_INVALID
    ch = RS.check_required(obj, GROUP_STATE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, GROUP_STATE_ALLOWED, code, strict)
    for f in ("group_id", "scenario_id", "shared_target_id", "shared_objective_id"):
        ch += _str(obj, f, code, "gs::")
    ch += RS.check_enum(obj, "group_role", GROUP_ROLES, code, prefix="gs::")
    ch += RS.check_enum(obj, "coordination_state", COORDINATION_STATES,
                        C.TACTICAL_COORDINATION_INVALID, prefix="gs::")
    ch += _list_of_str(obj, "npc_ids", code, "gs::", min_len=1)
    for f in ("suppression_active", "flank_active", "reinforcement_requested",
              "retreat_called"):
        ch += _bool(obj, f, code, "gs::")
    npc_ids = obj.get("npc_ids") if _is_list(obj, "npc_ids") else []
    # honesty: a coordinated state requires at least two NPCs (one NPC cannot coordinate).
    if obj.get("coordination_state") == "coordinated":
        ch.append(("gs::coordinated_needs_two", len(npc_ids) >= 2,
                   "coordination_state=coordinated requires >= 2 npc_ids",
                   C.TACTICAL_COORDINATION_INVALID))
    # honesty: an active flank requires a flank route.
    if obj.get("flank_active") is True:
        ch.append(("gs::flank_needs_route",
                   isinstance(obj.get("flank_route_id"), str)
                   and not _is_none_ref(obj.get("flank_route_id")),
                   "flank_active=true requires a flank_route_id",
                   C.TACTICAL_FLANK_ROUTE_MISSING))
    # honesty: active suppression requires a suppressor in the group.
    if obj.get("suppression_active") is True:
        roles = obj.get("roles_present") if _is_list(obj, "roles_present") else []
        ch.append(("gs::suppression_needs_suppressor", "suppressor" in roles,
                   "suppression_active=true requires a suppressor in roles_present",
                   C.TACTICAL_COORDINATION_INVALID))
    ch += _schema_version(obj, RT_GROUP_STATE, code, "gs::")
    return ch


def _example_tactical_group_state(**over):
    d = {
        "group_id": "tac_group_alpine_a_fireteam_s1",
        "scenario_id": "tac_region_alpine_hub_suppressor_high_pressure_tactical_s1",
        "npc_ids": ["tacnpc_alpine_a_suppressor_01", "tacnpc_alpine_a_skirmisher_02"],
        "group_role": "fireteam",
        "shared_target_id": "player",
        "shared_objective_id": "anchor_alpine_a_objective",
        "coordination_state": "coordinated",
        "suppression_active": True,
        "flank_active": True,
        "reinforcement_requested": False,
        "retreat_called": False,
        "roles_present": ["suppressor", "skirmisher"],
        "flank_route_id": "route_alpine_hub_to_a",
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_GROUP_STATE,
        "report_type": RT_GROUP_STATE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 10. TacticalRuntimeReport (WF961) — handoff §8.10
# =========================================================================== #
RUNTIME_REPORT_REQUIRED = (
    "report_id", "run_id", "scenario_id", "region_id", "streaming_profile",
    "tactical_profile_id", "npc_count", "roles_present", "decision_count",
    "valid_decision_count", "invalid_decision_count", "actions_executed", "cover_used",
    "flank_attempted", "retreat_attempted", "objective_pressure_seen",
    "group_coordination_seen", "combat_damage_seen", "mission_completed",
    "quest_state_updated", "faction_state_updated", "save_load_result", "budget_result",
    "operator_trace_paths", "failure_codes", "schema_version",
)
RUNTIME_REPORT_ALLOWED = RUNTIME_REPORT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "runtime_mode",
    "live_runtime_evidence", "expected_invalid", "seed", "decision_trace_paths")


def validate_tactical_runtime_report(obj, strict=False):
    code = C.TACTICAL_RUNTIME_REPORT_INVALID
    ch = RS.check_required(obj, RUNTIME_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, RUNTIME_REPORT_ALLOWED, code, strict)
    for f in ("report_id", "run_id", "scenario_id", "region_id", "tactical_profile_id"):
        ch += _str(obj, f, code, "rr::")
    ch += RS.check_enum(obj, "streaming_profile", STREAMING_PROFILES, code, prefix="rr::")
    ch += RS.check_enum(obj, "save_load_result", SAVE_LOAD_RESULTS,
                        C.TACTICAL_SAVE_LOAD_FAILED, prefix="rr::")
    ch += RS.check_enum(obj, "budget_result", BUDGET_RESULTS, C.TACTICAL_BUDGET_EXCEEDED,
                        prefix="rr::")
    if isinstance(obj, dict) and "runtime_mode" in obj:
        ch += RS.check_enum(obj, "runtime_mode", RUNTIME_MODES, code, prefix="rr::")
    for f in ("npc_count", "decision_count", "valid_decision_count",
              "invalid_decision_count"):
        ch += _int(obj, f, code, "rr::", allow_zero=True)
    for f in ("cover_used", "flank_attempted", "retreat_attempted",
              "objective_pressure_seen", "group_coordination_seen", "combat_damage_seen",
              "mission_completed", "quest_state_updated", "faction_state_updated"):
        ch += _bool(obj, f, code, "rr::")
    ch += _subset(obj, "roles_present", TACTICAL_ROLES, C.TACTICAL_UNKNOWN_ROLE, "rr::")
    ch += _subset(obj, "actions_executed", TACTICAL_ACTIONS, C.TACTICAL_UNKNOWN_ACTION, "rr::")
    for f in ("operator_trace_paths", "failure_codes"):
        ch.append(("rr::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    fcs = obj.get("failure_codes")
    if _is_list(obj, "failure_codes"):
        ch.append(("rr::failure_codes_well_formed",
                   all(isinstance(c, str) and _WF_CODE_RE.match(c) for c in fcs),
                   "failure_codes must be WFnnn_* strings", C.TACTICAL_UNKNOWN_FAILURE_CODE))

    # --- honesty: a CLEAN report (empty failure_codes) MUST carry real evidence ---
    clean = _is_list(obj, "failure_codes") and len(fcs or []) == 0
    if clean:
        ch.append(("rr::clean_has_npcs",
                   RS.is_number(obj.get("npc_count")) and obj.get("npc_count") > 0,
                   "a clean tactical report requires npc_count > 0", code))
        ch.append(("rr::clean_has_decisions",
                   RS.is_number(obj.get("decision_count")) and obj.get("decision_count") > 0,
                   "a clean tactical report requires decision_count > 0", code))
        ch.append(("rr::clean_has_valid_decisions",
                   RS.is_number(obj.get("valid_decision_count"))
                   and obj.get("valid_decision_count") > 0,
                   "a clean tactical report requires valid_decision_count > 0", code))
        # invalid_decision_count must be 0 unless explicitly expected.
        expected_invalid = obj.get("expected_invalid") is True
        inv = obj.get("invalid_decision_count")
        ch.append(("rr::clean_no_unexpected_invalid",
                   expected_invalid or (RS.is_number(inv) and inv == 0),
                   "a clean tactical report requires invalid_decision_count=0 unless "
                   "expected_invalid=true", code))
        ch.append(("rr::clean_has_actions",
                   _is_list(obj, "actions_executed") and len(obj["actions_executed"]) >= 1,
                   "a clean tactical report must execute >= 1 action", code))
        ch.append(("rr::clean_mission_completed", obj.get("mission_completed") is True,
                   "a clean tactical report requires mission_completed=true", code))
        ch.append(("rr::clean_save_roundtrip", obj.get("save_load_result") == "roundtrip_ok",
                   "a clean tactical report requires save_load_result=roundtrip_ok",
                   C.TACTICAL_SAVE_LOAD_FAILED))
        ch.append(("rr::clean_budget_ok", obj.get("budget_result") in ("pass", "advisory"),
                   "a clean tactical report requires budget_result in (pass, advisory)",
                   C.TACTICAL_BUDGET_EXCEEDED))
        # runtime-mode honesty: a clean report claiming live_tactical_runtime must carry
        # live-runtime evidence; otherwise it is an overclaim of the alpha substrate.
        if obj.get("runtime_mode") in LIVE_RUNTIME_MODES:
            ev = obj.get("live_runtime_evidence")
            ch.append(("rr::live_requires_evidence",
                       _is_list(obj, "live_runtime_evidence") and len(ev or []) >= 1,
                       "runtime_mode=live_tactical_runtime requires non-empty "
                       "live_runtime_evidence", C.TACTICAL_NAVMESH_OVERCLAIM))
    ch += _schema_version(obj, RT_RUNTIME_REPORT, code, "rr::")
    return ch


def _example_tactical_runtime_report(**over):
    d = {
        "report_id": "trr_region_alpine_hub_sentinel_baseline_tactical_s1",
        "run_id": "tacrun_region_alpine_hub_sentinel_baseline_tactical_s1",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "region_id": "region_alpine_hub",
        "streaming_profile": "hub_to_spoke_transition",
        "tactical_profile_id": "tac_profile_baseline_tactical",
        "npc_count": 3,
        "roles_present": ["sentinel", "skirmisher", "suppressor"],
        "decision_count": 18,
        "valid_decision_count": 18,
        "invalid_decision_count": 0,
        "actions_executed": ["hold_position", "advance_to_anchor", "use_cover",
                            "flank_via_route", "pressure_objective", "retreat_to_anchor"],
        "cover_used": True,
        "flank_attempted": True,
        "retreat_attempted": True,
        "objective_pressure_seen": True,
        "group_coordination_seen": True,
        "combat_damage_seen": True,
        "mission_completed": True,
        "quest_state_updated": True,
        "faction_state_updated": True,
        "save_load_result": "roundtrip_ok",
        "budget_result": "pass",
        "runtime_mode": "deterministic_tactical_simulation",
        "operator_trace_paths": [
            "procedural/reports/operator/tactical/scenarios/"
            "tac_region_alpine_hub_sentinel_baseline_tactical_s1.json"],
        "decision_trace_paths": [
            "procedural/reports/tactical/decisions/"
            "tac_region_alpine_hub_sentinel_baseline_tactical_s1.json"],
        "failure_codes": [],
        "seed": 1,
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_RUNTIME_REPORT,
        "report_type": RT_RUNTIME_REPORT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 11. TacticalSaveState (WF957) — handoff §8.11
# =========================================================================== #
SAVE_STATE_REQUIRED = (
    "save_state_id", "scenario_id", "region_id", "npc_state_hashes",
    "group_state_hashes", "active_decision_hashes", "cover_claim_hashes",
    "target_assignment_hashes", "quest_pressure_hash", "faction_pressure_hash",
    "streaming_tile_scope_hash", "roundtrip_result", "schema_version",
)
SAVE_STATE_ALLOWED = SAVE_STATE_REQUIRED + ("meta", "report_type", "created_by",
                                            "created_at", "notes")
_SAVE_HASH_DICTS = ("npc_state_hashes", "group_state_hashes", "active_decision_hashes",
                    "cover_claim_hashes", "target_assignment_hashes")


def validate_tactical_save_state(obj, strict=False):
    code = C.TACTICAL_SAVE_LOAD_FAILED
    ch = RS.check_required(obj, SAVE_STATE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SAVE_STATE_ALLOWED, code, strict)
    for f in ("save_state_id", "scenario_id", "region_id", "quest_pressure_hash",
              "faction_pressure_hash", "streaming_tile_scope_hash"):
        ch += _str(obj, f, code, "ss::")
    for f in _SAVE_HASH_DICTS:
        ch.append(("ss::{}_is_dict".format(f), _is_dict(obj, f),
                   "{} must be a dict id -> hash".format(f), C.TACTICAL_SAVE_LOAD_MISSING))
    ch += RS.check_enum(obj, "roundtrip_result", SAVE_LOAD_RESULTS, code, prefix="ss::")
    # honesty: a roundtrip_ok save MUST carry a hash for at least every tactical NPC —
    # a save/load claim with no tactical hashes is unfalsifiable (WF957).
    if obj.get("roundtrip_result") == "roundtrip_ok":
        npc_hashes = obj.get("npc_state_hashes") if _is_dict(obj, "npc_state_hashes") else {}
        ch.append(("ss::roundtrip_has_npc_hashes", len(npc_hashes) >= 1,
                   "roundtrip_ok requires >= 1 npc_state_hash",
                   C.TACTICAL_SAVE_LOAD_MISSING))
        ch.append(("ss::roundtrip_has_decision_hashes",
                   _is_dict(obj, "active_decision_hashes")
                   and len(obj.get("active_decision_hashes")) >= 1,
                   "roundtrip_ok requires >= 1 active_decision_hash",
                   C.TACTICAL_SAVE_LOAD_MISSING))
    ch += _schema_version(obj, RT_SAVE_STATE, code, "ss::")
    return ch


def _example_tactical_save_state(**over):
    d = {
        "save_state_id": "tss_region_alpine_hub_sentinel_baseline_tactical_s1",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "region_id": "region_alpine_hub",
        "npc_state_hashes": {"tacnpc_alpine_a_sentinel_01": "sha256:npc1"},
        "group_state_hashes": {"tac_group_alpine_a_fireteam_s1": "sha256:grp1"},
        "active_decision_hashes": {"tdt_alpine_a_sentinel_s1_t0001": "sha256:dec1"},
        "cover_claim_hashes": {"cover_alpine_hub_rock_01": "sha256:cov1"},
        "target_assignment_hashes": {"tacnpc_alpine_a_sentinel_01": "sha256:tgt1"},
        "quest_pressure_hash": "sha256:q1",
        "faction_pressure_hash": "sha256:f1",
        "streaming_tile_scope_hash": "sha256:s1",
        "roundtrip_result": "roundtrip_ok",
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_SAVE_STATE,
        "report_type": RT_SAVE_STATE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 12. TacticalBudgetReport (WF959) — handoff §8.12
# =========================================================================== #
BUDGET_REPORT_REQUIRED = (
    "budget_report_id", "scenario_id", "region_id", "npc_count", "decision_count",
    "decisions_per_minute", "max_active_tactical_npcs", "max_decision_ms",
    "total_decision_ms", "memory_classification", "runtime_classification",
    "budget_result", "failure_codes", "schema_version",
)
BUDGET_REPORT_ALLOWED = BUDGET_REPORT_REQUIRED + ("meta", "report_type", "created_by",
                                                  "created_at", "notes",
                                                  "max_decisions_per_minute")


def validate_tactical_budget_report(obj, strict=False):
    code = C.TACTICAL_BUDGET_REPORT_INVALID
    ch = RS.check_required(obj, BUDGET_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, BUDGET_REPORT_ALLOWED, code, strict)
    for f in ("budget_report_id", "scenario_id", "region_id"):
        ch += _str(obj, f, code, "br::")
    for f in ("npc_count", "decision_count"):
        ch += _int(obj, f, code, "br::", allow_zero=True)
    ch += _int(obj, "max_active_tactical_npcs", code, "br::", allow_zero=False)
    for f in ("decisions_per_minute", "total_decision_ms"):
        ch += _num(obj, f, code, "br::", allow_zero=True)
    ch += _num(obj, "max_decision_ms", code, "br::", allow_zero=False)
    ch += RS.check_enum(obj, "memory_classification", CLASSIFICATIONS, code, prefix="br::")
    ch += RS.check_enum(obj, "runtime_classification", CLASSIFICATIONS, code, prefix="br::")
    ch += RS.check_enum(obj, "budget_result", BUDGET_RESULTS, C.TACTICAL_BUDGET_EXCEEDED,
                        prefix="br::")
    ch.append(("br::failure_codes_list", _is_list(obj, "failure_codes"),
               "failure_codes must be a list", code))
    # honesty: an overrun cannot pass silently — budget_result must be recomputed from
    # raw values. If npc_count exceeds the active-NPC cap, budget_result must be
    # "exceeded". Likewise a decisions_per_minute over the declared cap.
    npc, cap = obj.get("npc_count"), obj.get("max_active_tactical_npcs")
    if RS.is_number(npc) and RS.is_number(cap) and npc > cap:
        ch.append(("br::npc_overrun_is_exceeded", obj.get("budget_result") == "exceeded",
                   "npc_count > max_active_tactical_npcs must classify budget_result="
                   "exceeded", C.TACTICAL_BUDGET_EXCEEDED))
    dpm, dpm_cap = obj.get("decisions_per_minute"), obj.get("max_decisions_per_minute")
    if RS.is_number(dpm) and RS.is_number(dpm_cap) and dpm > dpm_cap:
        ch.append(("br::dpm_overrun_is_exceeded", obj.get("budget_result") == "exceeded",
                   "decisions_per_minute > max_decisions_per_minute must classify "
                   "budget_result=exceeded", C.TACTICAL_BUDGET_EXCEEDED))
    # honesty: a classification over budget cannot coexist with a pass result.
    if "over_budget" in (obj.get("memory_classification"), obj.get("runtime_classification")):
        ch.append(("br::over_budget_not_pass", obj.get("budget_result") != "pass",
                   "an over_budget classification cannot report budget_result=pass",
                   C.TACTICAL_BUDGET_EXCEEDED))
    ch += _schema_version(obj, RT_BUDGET_REPORT, code, "br::")
    return ch


def _example_tactical_budget_report(**over):
    d = {
        "budget_report_id": "tbr_region_alpine_hub_sentinel_baseline_tactical_s1",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "region_id": "region_alpine_hub",
        "npc_count": 3,
        "decision_count": 18,
        "decisions_per_minute": 42.0,
        "max_active_tactical_npcs": 8,
        "max_decisions_per_minute": 80,
        "max_decision_ms": 12.0,
        "total_decision_ms": 96.0,
        "memory_classification": "within_budget",
        "runtime_classification": "within_budget",
        "budget_result": "pass",
        "failure_codes": [],
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_BUDGET_REPORT,
        "report_type": RT_BUDGET_REPORT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 13. TacticalEvidenceIndex (WF962) — handoff §8.13
# =========================================================================== #
EVIDENCE_INDEX_REQUIRED = (
    "index_id", "created_at", "git_sha", "scenario_count_expected", "scenario_count_seen",
    "behavior_profile_paths", "role_definition_paths", "affordance_map_paths",
    "npc_binding_paths", "decision_trace_paths", "runtime_report_paths",
    "save_state_paths", "budget_report_paths", "operator_view_paths", "actions_covered",
    "missing_evidence", "stale_evidence", "integrity_result", "schema_version",
)
EVIDENCE_INDEX_ALLOWED = EVIDENCE_INDEX_REQUIRED + ("meta", "report_type", "created_by", "notes")
_INDEX_PATH_LISTS = (
    "behavior_profile_paths", "role_definition_paths", "affordance_map_paths",
    "npc_binding_paths", "decision_trace_paths", "runtime_report_paths",
    "save_state_paths", "budget_report_paths", "operator_view_paths",
)


def validate_tactical_evidence_index(obj, strict=False):
    code = C.TACTICAL_EVIDENCE_INDEX_INVALID
    ch = RS.check_required(obj, EVIDENCE_INDEX_REQUIRED, code)
    ch += RS.check_no_unknown(obj, EVIDENCE_INDEX_ALLOWED, code, strict)
    for f in ("index_id", "created_at", "git_sha"):
        ch += _str(obj, f, code, "ei::")
    for f in ("scenario_count_expected", "scenario_count_seen"):
        ch += _int(obj, f, code, "ei::", allow_zero=True)
    for f in _INDEX_PATH_LISTS + ("actions_covered", "missing_evidence", "stale_evidence"):
        ch.append(("ei::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += RS.check_enum(obj, "integrity_result", INTEGRITY_RESULTS, code, prefix="ei::")
    if obj.get("created_at") == "live":
        sha = obj.get("git_sha")
        ch.append(("ei::live_requires_real_sha",
                   isinstance(sha, str) and sha and sha != "unknown",
                   "created_at='live' requires a real git_sha", C.TACTICAL_STALE_EVIDENCE))
    if obj.get("integrity_result") == "pass":
        seen, exp = obj.get("scenario_count_seen"), obj.get("scenario_count_expected")
        ch.append(("ei::pass_requires_full_matrix",
                   RS.is_number(seen) and RS.is_number(exp) and seen == exp and exp > 0,
                   "integrity_result=pass requires scenario_count_seen == expected > 0 "
                   "(got {} / {})".format(seen, exp), C.TACTICAL_PARTIAL_MATRIX))
        ch.append(("ei::pass_requires_no_missing",
                   _is_list(obj, "missing_evidence") and len(obj["missing_evidence"]) == 0,
                   "integrity_result=pass requires empty missing_evidence",
                   C.TACTICAL_SAVE_LOAD_MISSING))
        ch.append(("ei::pass_requires_no_stale",
                   _is_list(obj, "stale_evidence") and len(obj["stale_evidence"]) == 0,
                   "integrity_result=pass requires empty stale_evidence",
                   C.TACTICAL_STALE_EVIDENCE))
        # honesty: the matrix must cover every required tactical-action class.
        covered = set(obj.get("actions_covered") or []) if _is_list(obj, "actions_covered") else set()
        missing_actions = sorted(set(REQUIRED_COVERAGE_ACTIONS) - covered)
        ch.append(("ei::pass_requires_action_coverage", not missing_actions,
                   "integrity_result=pass requires all required action classes covered "
                   "(missing: {})".format(missing_actions), C.TACTICAL_ACTION_COVERAGE_MISSING))
    ch += _schema_version(obj, RT_EVIDENCE_INDEX, code, "ei::")
    return ch


def _example_tactical_evidence_index(**over):
    d = {
        "index_id": "tactical_evidence_index",
        "created_at": "live",
        "git_sha": "0" * 40,
        "scenario_count_expected": 24,
        "scenario_count_seen": 24,
        "behavior_profile_paths": [PROFILES_REL + "/tac_profile_baseline_tactical.json"],
        "role_definition_paths": [ROLES_REL + "/sentinel.json"],
        "affordance_map_paths": [AFFORDANCES_REL + "/afm_region_alpine_hub_x.json"],
        "npc_binding_paths": [BINDINGS_REL + "/tnb_region_alpine_hub_x.json"],
        "decision_trace_paths": [TAC_REPORTS_REL + "/decisions/tac_x.json"],
        "runtime_report_paths": [TAC_REPORTS_REL + "/runtime/tac_x.json"],
        "save_state_paths": [TAC_REPORTS_REL + "/save_load/tac_x.json"],
        "budget_report_paths": [TAC_REPORTS_REL + "/budgets/tac_x.json"],
        "operator_view_paths": ["procedural/reports/operator/tactical/scenarios/tac_x.json"],
        "actions_covered": list(REQUIRED_COVERAGE_ACTIONS),
        "missing_evidence": [],
        "stale_evidence": [],
        "integrity_result": "pass",
        "created_by": "worldforge.v2.4",
        "schema_version": RT_EVIDENCE_INDEX,
        "report_type": RT_EVIDENCE_INDEX,
    }
    d.update(over)
    return d


# =========================================================================== #
# 14. OperatorTacticalScenarioView (WF963) — handoff §8.14
# =========================================================================== #
OP_SCENARIO_REQUIRED = (
    "scenario_id", "region_id", "tactical_profile_id", "npc_count", "roles_present",
    "decision_summary", "action_coverage", "cover_usage", "flank_usage", "retreat_usage",
    "objective_pressure", "group_coordination", "combat_result", "quest_faction_result",
    "save_load_status", "budget_status", "decision_trace_paths", "failure_codes",
    "schema_version",
)
OP_SCENARIO_ALLOWED = OP_SCENARIO_REQUIRED + ("meta", "report_type", "created_by",
                                              "created_at", "notes")


def validate_operator_tactical_scenario_view(obj, strict=False):
    code = C.TACTICAL_OPERATOR_VIEW_INVALID
    ch = RS.check_required(obj, OP_SCENARIO_REQUIRED, code)
    ch += RS.check_no_unknown(obj, OP_SCENARIO_ALLOWED, code, strict)
    for f in ("scenario_id", "region_id", "tactical_profile_id", "cover_usage",
              "flank_usage", "retreat_usage", "objective_pressure", "group_coordination",
              "combat_result", "quest_faction_result", "save_load_status", "budget_status"):
        ch += _str(obj, f, code, "os::")
    ch += _int(obj, "npc_count", code, "os::", allow_zero=True)
    ch += _subset(obj, "roles_present", TACTICAL_ROLES, C.TACTICAL_UNKNOWN_ROLE, "os::")
    ch.append(("os::decision_summary_dict", _is_dict(obj, "decision_summary"),
               "decision_summary must be a dict", code))
    ch.append(("os::action_coverage_dict", _is_dict(obj, "action_coverage"),
               "action_coverage must be a dict", code))
    for f in ("decision_trace_paths", "failure_codes"):
        ch.append(("os::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # honesty: a clean scenario view (no failure codes) with a passing save/load status
    # MUST link >= 1 decision trace — a tactical claim with no inspectable trace is
    # unfalsifiable.
    clean = _is_list(obj, "failure_codes") and len(obj.get("failure_codes") or []) == 0
    if clean and obj.get("save_load_status") == "roundtrip_ok":
        dtp = obj.get("decision_trace_paths")
        ch.append(("os::pass_requires_trace",
                   _is_list(obj, "decision_trace_paths") and len(dtp) >= 1,
                   "a passing scenario view must link >= 1 decision trace", code))
    ch += _schema_version(obj, RT_OPERATOR_SCENARIO_VIEW, code, "os::")
    return ch


def _example_operator_tactical_scenario_view(**over):
    d = {
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "region_id": "region_alpine_hub",
        "tactical_profile_id": "tac_profile_baseline_tactical",
        "npc_count": 3,
        "roles_present": ["sentinel", "skirmisher", "suppressor"],
        "decision_summary": {"total": 18, "valid": 18, "invalid": 0},
        "action_coverage": {"hold_position": 4, "advance_to_anchor": 3, "use_cover": 5,
                            "flank_via_route": 2, "pressure_objective": 3,
                            "retreat_to_anchor": 1},
        "cover_usage": "used",
        "flank_usage": "attempted",
        "retreat_usage": "attempted",
        "objective_pressure": "seen",
        "group_coordination": "coordinated",
        "combat_result": "damage_seen",
        "quest_faction_result": "updated",
        "save_load_status": "roundtrip_ok",
        "budget_status": "pass",
        "decision_trace_paths": [
            "procedural/reports/tactical/decisions/"
            "tac_region_alpine_hub_sentinel_baseline_tactical_s1.json"],
        "failure_codes": [],
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_OPERATOR_SCENARIO_VIEW,
        "report_type": RT_OPERATOR_SCENARIO_VIEW,
    }
    d.update(over)
    return d


# =========================================================================== #
# 15. OperatorTacticalNPCView (WF963) — handoff §8.15
# =========================================================================== #
OP_NPC_REQUIRED = (
    "npc_id", "scenario_id", "role_id", "profile_id", "spawn_anchor_id",
    "decision_trace_paths", "actions_executed", "state_delta_paths", "save_state_path",
    "budget_report_path", "failure_codes", "schema_version",
)
OP_NPC_ALLOWED = OP_NPC_REQUIRED + ("meta", "report_type", "created_by", "created_at", "notes")


def validate_operator_tactical_npc_view(obj, strict=False):
    code = C.TACTICAL_OPERATOR_VIEW_INVALID
    ch = RS.check_required(obj, OP_NPC_REQUIRED, code)
    ch += RS.check_no_unknown(obj, OP_NPC_ALLOWED, code, strict)
    for f in ("npc_id", "scenario_id", "profile_id", "spawn_anchor_id", "save_state_path",
              "budget_report_path"):
        ch += _str(obj, f, code, "on::")
    ch += RS.check_enum(obj, "role_id", TACTICAL_ROLES, C.TACTICAL_UNKNOWN_ROLE, prefix="on::")
    ch += _subset(obj, "actions_executed", TACTICAL_ACTIONS, C.TACTICAL_UNKNOWN_ACTION, "on::")
    for f in ("decision_trace_paths", "state_delta_paths", "failure_codes"):
        ch.append(("on::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # honesty: a clean NPC view (no failure codes) that executed actions MUST link >= 1
    # decision trace AND >= 1 state delta — actions without traces/deltas are unproven.
    clean = _is_list(obj, "failure_codes") and len(obj.get("failure_codes") or []) == 0
    acted = _is_list(obj, "actions_executed") and len(obj.get("actions_executed") or []) >= 1
    if clean and acted:
        ch.append(("on::acted_requires_trace",
                   _is_list(obj, "decision_trace_paths")
                   and len(obj["decision_trace_paths"]) >= 1,
                   "an NPC view that executed actions must link >= 1 decision trace", code))
        ch.append(("on::acted_requires_state_delta",
                   _is_list(obj, "state_delta_paths") and len(obj["state_delta_paths"]) >= 1,
                   "an NPC view that executed actions must link >= 1 state delta",
                   C.TACTICAL_STATE_NOT_MUTATED))
    ch += _schema_version(obj, RT_OPERATOR_NPC_VIEW, code, "on::")
    return ch


def _example_operator_tactical_npc_view(**over):
    d = {
        "npc_id": "tacnpc_alpine_a_sentinel_01",
        "scenario_id": "tac_region_alpine_hub_sentinel_baseline_tactical_s1",
        "role_id": "sentinel",
        "profile_id": "tac_profile_baseline_tactical",
        "spawn_anchor_id": "anchor_alpine_a_npc_spawn",
        "decision_trace_paths": [
            "procedural/reports/tactical/decisions/"
            "tac_region_alpine_hub_sentinel_baseline_tactical_s1.json"],
        "actions_executed": ["hold_position", "use_cover", "protect_objective"],
        "state_delta_paths": [
            "procedural/reports/tactical/decisions/"
            "tac_region_alpine_hub_sentinel_baseline_tactical_s1_deltas.json"],
        "save_state_path": "procedural/reports/tactical/save_load/"
                           "tss_region_alpine_hub_sentinel_baseline_tactical_s1.json",
        "budget_report_path": "procedural/reports/tactical/budgets/"
                              "tbr_region_alpine_hub_sentinel_baseline_tactical_s1.json",
        "failure_codes": [],
        "created_by": "worldforge.v2.4",
        "created_at": "live",
        "schema_version": RT_OPERATOR_NPC_VIEW,
        "report_type": RT_OPERATOR_NPC_VIEW,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry — one source of truth for dogfood / negatives / fuzz suites.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "TacticalBehaviorProfile": (
        validate_tactical_behavior_profile, _example_tactical_behavior_profile,
        # aggression out of [0,1] -> profile invalid (WF931).
        lambda: _example_tactical_behavior_profile(aggression=1.5)),
    "TacticalRoleDefinition": (
        validate_tactical_role_definition, _example_tactical_role_definition,
        # preferred action not in allowed (it is forbidden) -> role invalid (WF932).
        lambda: _example_tactical_role_definition(preferred_actions=["flank_via_route"])),
    "TacticalAffordanceMap": (
        validate_tactical_affordance_map, _example_tactical_affordance_map,
        # malformed cover point -> cover reference invalid (WF947).
        lambda: _example_tactical_affordance_map(
            cover_points=[{"cover_id": "cover_x"}])),
    "TacticalNPCBinding": (
        validate_tactical_npc_binding, _example_tactical_npc_binding,
        # spawn tile not in allowed tiles -> binding invalid (WF934).
        lambda: _example_tactical_npc_binding(tile_id="tile_nowhere")),
    "TacticalDecisionInput": (
        validate_tactical_decision_input, _example_tactical_decision_input,
        # unknown stimulus -> WF937.
        lambda: _example_tactical_decision_input(active_stimuli=["telepathy"])),
    "TacticalDecisionOption": (
        validate_tactical_decision_option, _example_tactical_decision_option,
        # valid flank option with no route -> flank route missing (WF951).
        lambda: _example_tactical_decision_option(target_route_id="none")),
    "TacticalDecisionTrace": (
        validate_tactical_decision_trace, _example_tactical_decision_trace,
        # selects the rejected (invalid) option -> WF941.
        lambda: _example_tactical_decision_trace(selected_option_id="opt_flank")),
    "TacticalStateDelta": (
        validate_tactical_state_delta, _example_tactical_state_delta,
        # claims change but hashes equal -> state not mutated (WF944).
        lambda: _example_tactical_state_delta(post_state_hash="sha256:pre_0001")),
    "TacticalGroupState": (
        validate_tactical_group_state, _example_tactical_group_state,
        # coordinated with one NPC -> coordination invalid (WF946).
        lambda: _example_tactical_group_state(npc_ids=["only_one"])),
    "TacticalRuntimeReport": (
        validate_tactical_runtime_report, _example_tactical_runtime_report,
        # clean report but zero valid decisions -> runtime report invalid (WF961).
        lambda: _example_tactical_runtime_report(valid_decision_count=0)),
    "TacticalSaveState": (
        validate_tactical_save_state, _example_tactical_save_state,
        # roundtrip_ok but no npc hashes -> save/load missing (WF957).
        lambda: _example_tactical_save_state(npc_state_hashes={})),
    "TacticalBudgetReport": (
        validate_tactical_budget_report, _example_tactical_budget_report,
        # npc overrun but marked pass -> budget exceeded (WF960).
        lambda: _example_tactical_budget_report(npc_count=999)),
    "TacticalEvidenceIndex": (
        validate_tactical_evidence_index, _example_tactical_evidence_index,
        # integrity pass but only 23/24 seen -> partial matrix (WF965).
        lambda: _example_tactical_evidence_index(scenario_count_seen=23)),
    "OperatorTacticalScenarioView": (
        validate_operator_tactical_scenario_view, _example_operator_tactical_scenario_view,
        # passing scenario view but no decision trace -> operator view invalid (WF963).
        lambda: _example_operator_tactical_scenario_view(decision_trace_paths=[])),
    "OperatorTacticalNPCView": (
        validate_operator_tactical_npc_view, _example_operator_tactical_npc_view,
        # acted NPC view but no state delta link -> state not mutated (WF944).
        lambda: _example_operator_tactical_npc_view(state_delta_paths=[])),
}

CONTRACT_GROUPS = {
    "profiles_roles": ("TacticalBehaviorProfile", "TacticalRoleDefinition"),
    "affordance_bindings": ("TacticalAffordanceMap", "TacticalNPCBinding"),
    "decision": ("TacticalDecisionInput", "TacticalDecisionOption", "TacticalDecisionTrace",
                 "TacticalStateDelta", "TacticalGroupState"),
    "runtime": ("TacticalRuntimeReport", "TacticalSaveState", "TacticalBudgetReport"),
    "index_operator": ("TacticalEvidenceIndex", "OperatorTacticalScenarioView",
                       "OperatorTacticalNPCView"),
}

KNOWN_BAD_OWNING_CODE = {
    "TacticalBehaviorProfile": C.TACTICAL_PROFILE_INVALID,
    "TacticalRoleDefinition": C.TACTICAL_ROLE_INVALID,
    "TacticalAffordanceMap": C.TACTICAL_COVER_REFERENCE_INVALID,
    "TacticalNPCBinding": C.TACTICAL_NPC_BINDING_INVALID,
    "TacticalDecisionInput": C.TACTICAL_UNKNOWN_STIMULUS,
    "TacticalDecisionOption": C.TACTICAL_FLANK_ROUTE_MISSING,
    "TacticalDecisionTrace": C.TACTICAL_SELECTED_INVALID_OPTION,
    "TacticalStateDelta": C.TACTICAL_STATE_NOT_MUTATED,
    "TacticalGroupState": C.TACTICAL_COORDINATION_INVALID,
    "TacticalRuntimeReport": C.TACTICAL_RUNTIME_REPORT_INVALID,
    "TacticalSaveState": C.TACTICAL_SAVE_LOAD_MISSING,
    "TacticalBudgetReport": C.TACTICAL_BUDGET_EXCEEDED,
    "TacticalEvidenceIndex": C.TACTICAL_PARTIAL_MATRIX,
    "OperatorTacticalScenarioView": C.TACTICAL_OPERATOR_VIEW_INVALID,
    "OperatorTacticalNPCView": C.TACTICAL_STATE_NOT_MUTATED,
}

# The set of tactical failure codes this milestone owns (WF931–1010).
TACTICAL_CODES = tuple(
    v for k, v in vars(C).items()
    if not k.startswith("_") and isinstance(v, str)
    and 931 <= (int(v[2:5]) if v[2:5].isdigit() else -1) <= 1010
)
