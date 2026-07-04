#!/usr/bin/env python3
"""playtest_beta_contract.py — WorldForge v1.4 PlaytestForge Beta contract (Lane E).

PlaytestForge Beta proves a generated ENCOUNTER is playable on top of its
linked mission (brief §14) — pure Python, no UE. The five alpha modes are
REUSED by calling through playtest_contract.MODE_FUNCS against the mission;
the four beta modes are new pure functions of (encounter, mission) built on
encounter_contract's deterministic pressure/pacing model. An encounter
"completes" only if every declared beta mode passes AND the mission's own
alpha playtest still completes — pressure that breaks the mission loop is a
beta failure, not a shrug.

Shared by run_playtest_forge_beta.py and the beta validators so there is ONE
implementation of the beta simulation.
"""

from pathlib import Path

import mission_contract as MC
import playtest_contract as PC
import encounter_contract as EC

REPO_ROOT = Path(__file__).resolve().parents[2]

BETA_MODES = (
    "route_playtest",                 # alpha graph: objective graph traversable
    "anchor_playtest",                # alpha: spawn valid, anchors reachable in budget
    "state_transition_playtest",      # alpha: mission deltas resolve completion
    "save_load_playtest",             # alpha: persisted state survives roundtrip
    "budget_safe_playtest",           # alpha: route/asset budget within profile cap
    "encounter_pressure_playtest",    # beta: pressure score within band/budget caps
    "encounter_resolution_playtest",  # beta: combined mission+encounter state resolves
    "pacing_playtest",                # beta: pacing metrics meet the pacing_target
    "resource_reward_playtest",       # beta: resource reward fires only on resolution
)

# Core modes every encounter MUST declare (resource_reward is conditional on a
# resource_grant hook). An encounter that omits these is a contract failure —
# a playtest that ignores the encounter proves nothing.
REQUIRED_BETA_MODES = BETA_MODES[:8]

# The five reuse modes call through the alpha implementation (by alpha name).
ALPHA_MODE_MAP = {
    "route_playtest": "graph_playtest",
    "anchor_playtest": "anchor_playtest",
    "state_transition_playtest": "state_transition_playtest",
    "save_load_playtest": "save_load_playtest",
    "budget_safe_playtest": "budget_safe_playtest",
}

# Profile → the max_pressure_band the playtest contract must declare (v1.4).
PROFILE_MAX_BAND = {
    "light_pressure": "standard",
    "standard_pressure": "hard",
}


# --- shared helpers -----------------------------------------------------------

def band_index(band):
    """Index of a band in EC.DIFFICULTY_BANDS, or None if unknown."""
    try:
        return EC.DIFFICULTY_BANDS.index(band)
    except (ValueError, TypeError):
        return None


def has_resource_grant(encounter):
    """True iff the encounter declares a resource_grant reward hook."""
    return any((h or {}).get("reward_type") == "resource_grant"
               for h in (encounter or {}).get("reward_hooks") or [])


def combined_final_state(encounter, mission):
    """Apply mission deltas AND encounter deltas; return the merged final state."""
    final = PC.simulate_state(mission or {})
    final.update(PC.simulate_state(encounter or {}))
    return final


def route_blockage_ratio(encounter, mission):
    """Fraction of densified mission-route waypoints within EC.PRESSURE_RADIUS_CM
    of a spawn anchor. None when the mission has no usable route."""
    waypoints = EC.densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))
    if not waypoints:
        return None
    spawns = [a.get("world_position") for a in (encounter or {}).get("spawn_anchors") or []
              if a.get("world_position")]
    contested = 0
    for wp in waypoints:
        if any(MC.dist2d(wp, s) <= EC.PRESSURE_RADIUS_CM for s in spawns):
            contested += 1
    return round(contested / len(waypoints), 3)


def activation_coherent(encounter, mission):
    """(ok, detail). Activation must be declared; for extraction_pressure the
    activation threshold must EQUAL the mission completion threshold on the same
    state key, so the resolution order (mission objective -> pressure) is provable."""
    acts = (encounter or {}).get("activation_conditions") or []
    if not acts:
        return False, "no activation_conditions declared"
    if (encounter or {}).get("encounter_archetype") != "extraction_pressure":
        return True, "activation declared ({} condition(s))".format(len(acts))
    completion = {c.get("state_key"): c.get("threshold")
                  for c in (mission or {}).get("completion_conditions") or []}
    for a in acts:
        sk = a.get("state_key")
        if sk not in completion:
            return False, ("extraction_pressure activation key {!r} is not a "
                           "mission completion key".format(sk))
        try:
            if float(a.get("threshold")) != float(completion[sk]):
                return False, ("extraction_pressure activation threshold {!r} != "
                               "mission completion threshold {!r} for {!r}".format(
                                   a.get("threshold"), completion[sk], sk))
        except (TypeError, ValueError):
            return False, "non-numeric activation/completion threshold for {!r}".format(sk)
    return True, "extraction_pressure activation thresholds equal mission completion"


# --- beta modes; each returns (passed: bool, detail: str) ---------------------

def mode_encounter_pressure(encounter, mission):
    """Pressure score within: valid band, profile band targets, pressure budget,
    and the contract's max_pressure_band (band order = EC.DIFFICULTY_BANDS)."""
    comps = EC.pressure_components(encounter, mission)
    total = EC.total_pressure(comps)
    band = EC.classify_band(total)
    profile = encounter.get("encounter_profile")
    not_extreme = band not in ("invalid", "extreme")
    in_targets = EC.band_allowed_for_profile(band, profile)
    try:
        budget = float(encounter.get("pressure_budget"))
    except (TypeError, ValueError):
        budget = None
    within_budget = budget is not None and total <= budget
    max_band = (encounter.get("playtest_contract") or {}).get("max_pressure_band")
    bi, mi = band_index(band), band_index(max_band)
    within_max = bi is not None and mi is not None and bi <= mi
    below_invalid = 0.0 <= total <= EC.INVALID_PRESSURE_ABOVE
    ok = not_extreme and in_targets and within_budget and within_max and below_invalid
    return ok, ("total={} band={} profile={} in_targets={} budget={} within_budget={} "
                "max_pressure_band={} within_max={} below_invalid={}".format(
                    total, band, profile, in_targets, budget, within_budget,
                    max_band, within_max, below_invalid))


def mode_encounter_resolution(encounter, mission):
    """Combined mission+encounter state simulation: both completion sets resolve,
    no failure condition fires, activation is coherent, and the objective stays
    reachable under pressure (route not fully blocked, within pacing budget)."""
    final = combined_final_state(encounter, mission)
    m_resolves = PC.completion_resolves(mission, final)
    e_resolves = PC.completion_resolves(encounter, final)
    m_fails = PC.failure_fires(mission, final)
    e_fails = PC.failure_fires(encounter, final)
    act_ok, act_detail = activation_coherent(encounter, mission)
    blockage = route_blockage_ratio(encounter, mission)
    max_block = (encounter.get("pacing_target") or {}).get("max_route_blockage_ratio")
    reachable = (blockage is not None and blockage < 1.0
                 and isinstance(max_block, (int, float)) and blockage <= max_block)
    ok = (m_resolves and e_resolves and not m_fails and not e_fails
          and act_ok and reachable)
    return ok, ("mission_resolves={} encounter_resolves={} mission_failure_fires={} "
                "encounter_failure_fires={} activation_ok={} ({}) "
                "route_blockage={} max={} reachable={}".format(
                    m_resolves, e_resolves, m_fails, e_fails,
                    act_ok, act_detail, blockage, max_block, reachable))


def mode_pacing(encounter, mission):
    """EC.pacing_metrics against the encounter's pacing_target."""
    pm = EC.pacing_metrics(encounter, mission)
    pt = encounter.get("pacing_target") or {}
    first = pm.get("distance_from_spawn_to_first_pressure")
    min_first = pt.get("min_first_pressure_cm")
    first_ok = (isinstance(first, (int, float)) and isinstance(min_first, (int, float))
                and first >= min_first)
    max_block = pt.get("max_route_blockage_ratio")
    block = pm.get("route_blockage_ratio")
    block_ok = (isinstance(block, (int, float)) and isinstance(max_block, (int, float))
                and block <= max_block)
    min_cover = pt.get("min_cover_per_pressure_point")
    cover = pm.get("cover_density_near_pressure")
    cover_ok = (isinstance(cover, (int, float)) and isinstance(min_cover, (int, float))
                and cover >= min_cover)
    safe_ok = pm.get("safe_zone_distance_after_pressure") is not None
    ok = first_ok and block_ok and cover_ok and safe_ok
    return ok, ("first_pressure={} (min {}) blockage={} (max {}) cover_density={} "
                "(min {}) safe_zone_after_pressure={}".format(
                    first, min_first, block, max_block, cover, min_cover,
                    pm.get("safe_zone_distance_after_pressure")))


def mode_resource_reward(encounter, mission):
    """Resource reward wiring: a resource_grant hook that fires only on
    resolution, a resource node linked in objective_links, and the encounter
    completion state key(s) persisted across save/load."""
    grants = [h for h in encounter.get("reward_hooks") or []
              if (h or {}).get("reward_type") == "resource_grant"]
    hook_ok = bool(grants)
    fires_ok = hook_ok and all(h.get("fires_on") == "encounter_resolved" for h in grants)
    links = encounter.get("objective_links") or []
    nodes = encounter.get("resource_nodes") or []
    node_ok = any((n or {}).get("id") in links for n in nodes)
    persist = (encounter.get("save_load_contract") or {}).get("persist_keys") or []
    ckeys = [c.get("state_key") for c in encounter.get("completion_conditions") or []]
    persist_ok = bool(ckeys) and all(k in persist for k in ckeys)
    ok = hook_ok and fires_ok and node_ok and persist_ok
    return ok, ("resource_grant_hook={} fires_on_resolution={} node_linked={} "
                "completion_key_persisted={} (keys={} persist={})".format(
                    hook_ok, fires_ok, node_ok, persist_ok, ckeys, persist))


BETA_MODE_FUNCS = {
    "encounter_pressure_playtest": mode_encounter_pressure,
    "encounter_resolution_playtest": mode_encounter_resolution,
    "pacing_playtest": mode_pacing,
    "resource_reward_playtest": mode_resource_reward,
}


def run_beta_modes(encounter, mission):
    """Run the encounter's declared beta modes; return (results, completed).

    completed = every declared mode passed AND the mission's own alpha playtest
    still completes (an encounter must never break its host mission loop).
    Only modes listed in the encounter's playtest_contract are run — a contract
    that omits the encounter_* modes is caught by the contract validator.
    """
    modes = (encounter.get("playtest_contract") or {}).get("modes") or []
    results = {}
    for mode in modes:
        if mode in ALPHA_MODE_MAP:
            fn = PC.MODE_FUNCS.get(ALPHA_MODE_MAP[mode])
            if fn is None:
                results[mode] = {"passed": False,
                                 "detail": "alpha mode {} missing".format(ALPHA_MODE_MAP[mode])}
                continue
            passed, detail = fn(mission)
        elif mode in BETA_MODE_FUNCS:
            passed, detail = BETA_MODE_FUNCS[mode](encounter, mission)
        else:
            results[mode] = {"passed": False, "detail": "unknown mode"}
            continue
        results[mode] = {"passed": bool(passed), "detail": detail}
    _, mission_completed = PC.run_modes(
        mission, (mission.get("playtest_contract") or {}).get("modes"))
    completed = (bool(results)
                 and all(r["passed"] for r in results.values())
                 and mission_completed)
    return results, completed
