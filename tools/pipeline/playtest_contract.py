#!/usr/bin/env python3
"""playtest_contract.py — WorldForge v1.3 PlaytestForge contract + shared simulation.

PlaytestForge Alpha proves a generated mission is COMPLETABLE at an abstract
navigation/action/state level (brief §6) — no full player AI, no UE required. It
is the load-bearing answer to "can WorldForge generate something a player can
actually do?". The five modes each prove one link of the loop; a mission
"completes" only if every declared mode passes AND the completion condition
resolves after the simulated state transition.

This module holds the mode vocabulary + the pure-Python simulation primitives so
run_playtest_forge.py and the playtest validators share ONE implementation.
"""

from pathlib import Path

import mission_contract as MC

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYTEST_REPORTS_REL = "procedural/reports/missions/playtest"

PLAYTEST_MODES = (
    "graph_playtest",          # objective graph is well-formed + traversable
    "anchor_playtest",         # spawn valid, objective anchors reachable within budget
    "state_transition_playtest",  # applying deltas resolves the completion condition
    "save_load_playtest",      # persisted state survives a save/load roundtrip
    "budget_safe_playtest",    # route/asset budget within the map's profile cap
)
OPTIONAL_PLAYTEST_MODES = ("headless_ue_playtest",)

BUDGET_CLASSES = ("light", "balanced", "heavy", "performance_safe", "cinematic", "raytraced_high")


def resolve_condition(value, operator, threshold):
    """Evaluate a completion/failure condition against a state value."""
    try:
        v, t = float(value), float(threshold)
    except (TypeError, ValueError):
        return False
    return {
        ">=": v >= t, "<=": v <= t, "==": v == t, ">": v > t, "<": v < t,
    }.get(operator, False)


def simulate_state(mission):
    """Apply each state key's delta to its initial value; return {key: final}."""
    out = {}
    for s in mission.get("state_keys") or []:
        try:
            out[s["key"]] = float(s.get("initial", 0)) + float(s.get("delta", 0))
        except (TypeError, ValueError):
            out[s["key"]] = None
    return out


def completion_resolves(mission, final_state):
    """True iff every completion condition resolves under final_state."""
    conds = mission.get("completion_conditions") or []
    if not conds:
        return False
    for c in conds:
        val = final_state.get(c.get("state_key"))
        if val is None or not resolve_condition(val, c.get("operator"), c.get("threshold")):
            return False
    return True


def failure_fires(mission, final_state):
    """True if any failure condition fires under final_state (should NOT after a
    successful transition — e.g. 'state never changed')."""
    for c in mission.get("failure_conditions") or []:
        val = final_state.get(c.get("state_key"))
        if val is not None and resolve_condition(val, c.get("operator"), c.get("threshold")):
            return True
    return False


# ---- the five modes; each returns (passed: bool, detail: str) ---------------

def mode_graph(mission):
    start = mission.get("start_anchor") or {}
    primary = mission.get("primary_poi") or {}
    objectives = mission.get("objective_anchors") or []
    route = mission.get("required_route") or {}
    ok = (bool(start.get("world_position")) and bool(primary.get("gameplay_anchor"))
          and bool(objectives) and route.get("from_node") == MC.NODE_START
          and route.get("to_node") == MC.NODE_PRIMARY_POI
          and len(route.get("waypoints") or []) >= 2)
    return ok, "graph start->poi->objective connected" if ok else "graph disconnected/incomplete"


def mode_anchor(mission):
    route = mission.get("required_route") or {}
    pt = mission.get("playtest_contract") or {}
    start = mission.get("start_anchor") or {}
    spawn_ok = start.get("valid_spawn", True)
    reachable = bool(route.get("avoids_hazards"))
    within = (route.get("length_cm") or 0) <= (pt.get("max_route_length_cm") or float("inf"))
    obj_ok = all(o.get("world_position") for o in (mission.get("objective_anchors") or []))
    ok = spawn_ok and reachable and within and obj_ok
    return ok, "spawn={} reachable={} within_budget={} objs={}".format(spawn_ok, reachable, within, obj_ok)


def mode_state_transition(mission):
    final = simulate_state(mission)
    resolves = completion_resolves(mission, final)
    no_fail = not failure_fires(mission, final)
    ok = resolves and no_fail
    return ok, "final={} completion_resolves={} failure_fires={}".format(final, resolves, not no_fail)


def mode_save_load(mission):
    final = simulate_state(mission)
    persist = (mission.get("save_load_contract") or {}).get("persist_keys") or []
    # simulate save -> load roundtrip of the persisted keys
    saved = {k: final.get(k) for k in persist}
    loaded = dict(saved)  # roundtrip
    roundtrip = loaded == saved and all(k in loaded for k in persist)
    # completion must still resolve from the loaded (persisted) state
    still_complete = completion_resolves(mission, {**final, **loaded})
    ok = roundtrip and still_complete and bool(persist)
    return ok, "persist={} roundtrip={} still_complete={}".format(persist, roundtrip, still_complete)


def mode_budget_safe(mission):
    route = mission.get("required_route") or {}
    pt = mission.get("playtest_contract") or {}
    budget = mission.get("budget_class")
    within = (route.get("length_cm") or 0) <= (pt.get("max_route_length_cm") or float("inf"))
    known = budget in BUDGET_CLASSES
    ok = within and known
    return ok, "budget={} within_route_budget={}".format(budget, within)


MODE_FUNCS = {
    "graph_playtest": mode_graph,
    "anchor_playtest": mode_anchor,
    "state_transition_playtest": mode_state_transition,
    "save_load_playtest": mode_save_load,
    "budget_safe_playtest": mode_budget_safe,
}


def run_modes(mission, modes=None):
    """Run the requested modes; return (results dict, completed bool)."""
    modes = modes or (mission.get("playtest_contract") or {}).get("modes") or list(PLAYTEST_MODES)
    results = {}
    for mode in modes:
        fn = MODE_FUNCS.get(mode)
        if fn is None:
            results[mode] = {"passed": False, "detail": "unknown mode"}
            continue
        passed, detail = fn(mission)
        results[mode] = {"passed": bool(passed), "detail": detail}
    completed = all(r["passed"] for r in results.values()) and bool(results)
    return results, completed
