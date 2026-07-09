#!/usr/bin/env python3
"""combat_contracts.py — WorldForge v1.8 CombatForge Alpha spine.

Turns the v1.7 NPC *behavior pressure* substrate ([[npc_contracts]]) into real
runtime *combat pressure*: NPC pressure and hazards now produce damage, player
health mutates at runtime, and mission completion must remain possible under
baseline. One module, one section per contract, each with X_REQUIRED / X_ALLOWED
field sets, a ``validate_X(obj, strict)`` returning ``(name, ok, detail, code)``
check tuples in the exact shape ValidationReport.check consumes, and a canonical
``_example_X`` factory. A ``CONTRACTS`` registry pairs each validator with a valid
example and a known-bad example so the schema gate can dogfood that every contract
actually constrains (a contract that accepts its own known-bad is a fake-green
vector).

This spine sits directly on the v1.7 behavior substrate: a combat scenario is a
v1.7 behavior scenario with damage semantics layered on, and every combat
completion report references the behavior_scenario_id it was realized from. The
honesty invariants are enforced here at the schema layer — a "combat_completed"
run with zero damage events, no health mutation, or an invulnerable player is
fake green and is rejected.

Contracts:
  CombatProfile            validate_combat_profile
  PlayerCombatState        validate_player_combat_state
  DamageEvent              validate_damage_event
  CombatTelemetry          validate_combat_telemetry
  CombatCompletionReport   validate_combat_completion_report
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]
C = FailureCode

# --------------------------------------------------------------------------- #
# Taxonomy — the combat vocabulary. One source of truth for every generator /
# validator / shield.
# --------------------------------------------------------------------------- #
# The 8 v1.4 encounter archetypes a CombatProfile layers damage onto (same set
# the v1.7 BehaviorProfile maps).
ENCOUNTER_ARCHETYPES = (
    "guarded_objective", "patrol_route", "ambush_choke", "hazard_field",
    "resource_contest", "defensive_holdout", "roaming_threat", "extraction_pressure",
)

# The real damage sources v1.8 Alpha proves. NPC pressure and hazards are the two
# runtime sources; environment is reserved (e.g. fall/liquid) but only counts when
# actually implemented. No weapon/ability/boss sources — those are hard non-goals.
DAMAGE_SOURCE_TYPES = ("npc_pressure", "hazard", "environment")
IMPLEMENTED_DAMAGE_SOURCES = ("npc_pressure", "hazard")

# How a damage source deals damage. Derived from the v1.7 pressure models — a
# pressure model that was telemetry_only in v1.7 becomes a real damage_type here.
DAMAGE_TYPES = (
    "proximity_tick", "ranged_tick", "contact", "hazard_zone", "dot",
)

# Mission-completion policy a profile must honour — completion must remain
# possible; a profile cannot opt out of winnability under baseline.
MISSION_COMPLETION_POLICIES = ("must_remain_possible", "must_remain_possible_under_baseline")

# Survivability classification bands (BalanceForge). Only unwinnable / no_damage
# block; too_soft is a warning band (no real threat), too_low = near-unwinnable.
SURVIVABILITY_BANDS = ("survivable", "too_soft", "too_low", "unwinnable", "no_damage")
BLOCKING_SURVIVABILITY_BANDS = ("unwinnable", "no_damage")

RESULT_STATUS = ("pass", "fail", "skipped", "not_implemented")

# CombatCompletionReport completion classes. The one success class is
# combat_completed_runtime — everything else names an owned failure surface.
COMBAT_COMPLETION_CLASSES = (
    "combat_completed_runtime",
    "failed_combat_spawn", "failed_player_health_init", "failed_damage_application",
    "failed_npc_damage_bridge", "failed_hazard_damage", "failed_health_mutation",
    "failed_mission_completion", "failed_combat_save_load", "failed_survivability",
    "failed_report_integrity",
)
SUCCESS_COMBAT_CLASS = "combat_completed_runtime"

# Report type identifiers.
RT_COMBAT_PROFILE = "wf.combat.combat_profile_report.v1"
RT_PLAYER_COMBAT_STATE = "wf.combat.player_combat_state.v1"
RT_DAMAGE_EVENT = "wf.combat.damage_event.v1"
RT_COMBAT_TELEMETRY = "wf.combat.telemetry.v1"
RT_COMBAT_COMPLETION = "wf.combat.combat_completion_report.v1"
RT_COMBAT_BALANCE = "wf.combat.combat_balance_report.v1"
RT_COMBAT_FAILURE_SUMMARY = "wf.combat.failure_summary.v1"
RT_SHIELD_ROLLUP = "wf.v1_8.full_shield_rollup.v1"

# Generated / report roots (repo-relative).
COMBAT_PROFILE_GENERATED_REL = "procedural/generated/combat/profiles"
COMBAT_SCENARIO_GENERATED_REL = "procedural/generated/combat/scenarios"
DAMAGE_TELEMETRY_REPORTS_REL = "procedural/reports/combat/telemetry"
COMBAT_COMPLETION_REPORTS_REL = "procedural/reports/combat/completion"
COMBAT_BALANCE_REPORTS_REL = "procedural/reports/combat/balance"


def runtime_realized_combat_maps(completion_dir):
    """The set of maps genuinely realized WITH COMBAT at runtime, derived only
    from committed combat-completion evidence: a map counts iff it has >=1
    completion report whose completion_class is SUCCESS_COMBAT_CLASS with
    damage_events_seen > 0 (the engine applied real damage on that map). Single
    source of truth shared by the batch writer and the gate so the two can never
    drift, grounded in evidence a separate validator proves genuine — so combat
    realization cannot be greened without real runtime damage. Returns a set of
    map_id strings."""
    import json as _json
    from pathlib import Path as _Path
    d = _Path(completion_dir)
    realized = set()
    if not d.is_dir():
        return realized
    for f in sorted(d.glob("cs_*.json")):
        try:
            r = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if (r.get("completion_class") == SUCCESS_COMBAT_CLASS
                and isinstance(r.get("damage_events_seen"), int) and r["damage_events_seen"] > 0
                and r.get("map_id")):
            realized.add(r["map_id"])
    return realized


def _num(obj, field, code, prefix, allow_zero=True):
    return RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)


def _list(obj, field, code, prefix, min_len=0):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) >= min_len
    return [("{}{}_list".format(prefix, field), ok,
             "{} must be a list (>= {} items)".format(field, min_len), code)]


def _bool(obj, field, code, prefix):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, bool)
    return [("{}{}_bool".format(prefix, field), ok,
             "{} must be a boolean".format(field), code)]


# --------------------------------------------------------------------------- #
# CombatProfile — layers runtime damage onto a v1.4 encounter archetype.
# --------------------------------------------------------------------------- #
COMBAT_PROFILE_SCHEMA_VERSION = "wf.combat.combat_profile.v1"
COMBAT_PROFILE_REQUIRED = (
    "combat_profile_id", "encounter_archetype", "pressure_profile", "behavior_profile_id",
    "player_max_health", "damage_sources", "npc_damage_rules", "hazard_damage_rules",
    "baseline_expected_damage", "survivability_policy", "mission_completion_policy",
    "save_load_policy", "telemetry_requirements", "balance_requirements",
)
COMBAT_PROFILE_ALLOWED = COMBAT_PROFILE_REQUIRED + ("meta", "schema_version", "report_type",
                                                    "created_by", "created_at")


def validate_combat_profile(obj, strict=False):
    ch = RS.check_required(obj, COMBAT_PROFILE_REQUIRED, C.COMBAT_PROFILE_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, COMBAT_PROFILE_ALLOWED, C.COMBAT_PROFILE_SCHEMA_FAILURE, strict)
    ch += RS.check_enum(obj, "encounter_archetype", ENCOUNTER_ARCHETYPES, C.COMBAT_PROFILE_SCHEMA_FAILURE)
    ch += RS.check_enum(obj, "mission_completion_policy", MISSION_COMPLETION_POLICIES,
                        C.COMBAT_MISSION_COMPLETION_BLOCKED)
    if not isinstance(obj, dict):
        return ch
    ch.append(("cp::behavior_profile_ref",
               isinstance(obj.get("behavior_profile_id"), str) and len(obj.get("behavior_profile_id")) > 0,
               "combat profile must reference a v1.7 behavior_profile_id", C.COMBAT_PROFILE_SCHEMA_FAILURE))
    ch += _num(obj, "player_max_health", C.COMBAT_PROFILE_SCHEMA_FAILURE, "cp::", allow_zero=False)
    ch += _list(obj, "damage_sources", C.COMBAT_PROFILE_SCHEMA_FAILURE, "cp::", min_len=1)
    for f in ("telemetry_requirements", "balance_requirements"):
        ch += _list(obj, f, C.COMBAT_PROFILE_SCHEMA_FAILURE, "cp::", min_len=1)
    for f in ("npc_damage_rules", "hazard_damage_rules", "survivability_policy", "save_load_policy"):
        ok = isinstance(obj.get(f), dict)
        ch.append(("cp::{}_object".format(f), ok, "{} must be an object".format(f),
                   C.COMBAT_PROFILE_SCHEMA_FAILURE))
    # Damage sources must be from the known taxonomy AND at least one must be an
    # IMPLEMENTED source — a profile whose only source is the reserved
    # "environment" declares combat it cannot actually produce (fake green).
    srcs = obj.get("damage_sources")
    if isinstance(srcs, list):
        bad = [s for s in srcs if s not in DAMAGE_SOURCE_TYPES]
        ch.append(("cp::damage_sources_known", not bad,
                   "unknown damage source(s): {}".format(bad), C.COMBAT_PROFILE_SCHEMA_FAILURE))
        ch.append(("cp::damage_source_implemented",
                   any(s in IMPLEMENTED_DAMAGE_SOURCES for s in srcs),
                   "combat profile needs >=1 implemented damage source (npc_pressure/hazard)",
                   C.PLAYER_DAMAGE_NOT_APPLIED))
    # Baseline must expect real damage — a profile that expects zero damage is not
    # combat (BalanceForge no_damage). Positive and strictly below max health so the
    # player can still complete (winnable under baseline).
    bed = obj.get("baseline_expected_damage")
    pmh = obj.get("player_max_health")
    ch.append(("cp::baseline_damage_positive", RS.is_number(bed) and bed > 0,
               "baseline_expected_damage must be > 0 (real combat)", C.COMBAT_NO_DAMAGE_EVENTS))
    if RS.is_number(bed) and RS.is_number(pmh):
        ch.append(("cp::baseline_winnable", bed < pmh,
                   "baseline_expected_damage must be < player_max_health (winnable baseline)",
                   C.COMBAT_UNWINNABLE_BASELINE))
    return ch


def _example_combat_profile(**over):
    d = {
        "combat_profile_id": "cp_guard_pressure", "encounter_archetype": "guarded_objective",
        "pressure_profile": "standard_pressure", "behavior_profile_id": "bp_guard_pressure",
        "player_max_health": 100.0, "damage_sources": ["npc_pressure"],
        "npc_damage_rules": {"proximity_tick": 4.0, "tick_interval_seconds": 0.5, "requires_los": False},
        "hazard_damage_rules": {},
        "baseline_expected_damage": 35.0,
        "survivability_policy": {"min_final_health": 1.0, "max_final_health": 85.0},
        "mission_completion_policy": "must_remain_possible_under_baseline",
        "save_load_policy": {"persist": ["current_health", "damage_taken_total"]},
        "telemetry_requirements": ["combat.player.damage.taken", "combat.player.health.changed"],
        "balance_requirements": ["baseline_winnable", "damage_events_seen"],
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# PlayerCombatState — runtime health state (save/load unit).
# --------------------------------------------------------------------------- #
PLAYER_COMBAT_STATE_SCHEMA_VERSION = "wf.combat.player_combat_state.v1"
PLAYER_COMBAT_STATE_REQUIRED = (
    "player_instance_id", "map_id", "mission_id", "encounter_id", "max_health", "current_health",
    "is_alive", "damage_taken_total", "damage_events_count", "last_damage_source",
    "last_damage_at", "invulnerable", "save_load_key",
)
PLAYER_COMBAT_STATE_ALLOWED = PLAYER_COMBAT_STATE_REQUIRED + ("meta", "schema_version", "report_type")

_PCS_STR_FIELDS = ("player_instance_id", "map_id", "mission_id", "encounter_id", "save_load_key")


def validate_player_combat_state(obj, strict=False):
    ch = RS.check_required(obj, PLAYER_COMBAT_STATE_REQUIRED, C.PLAYER_COMBAT_STATE_SCHEMA_FAILURE,
                           nullable=("last_damage_source",))
    ch += RS.check_no_unknown(obj, PLAYER_COMBAT_STATE_ALLOWED, C.PLAYER_COMBAT_STATE_SCHEMA_FAILURE, strict)
    if not isinstance(obj, dict):
        return ch
    for f in _PCS_STR_FIELDS:
        ch += RS.check_type(obj, f, str, C.PLAYER_COMBAT_STATE_SCHEMA_FAILURE, prefix="pcs::")
    for f in ("is_alive", "invulnerable"):
        ch += _bool(obj, f, C.PLAYER_COMBAT_STATE_SCHEMA_FAILURE, "pcs::")
    for f in ("max_health", "current_health", "damage_taken_total", "last_damage_at"):
        ch += _num(obj, f, C.PLAYER_COMBAT_STATE_SCHEMA_FAILURE, "pcs::", allow_zero=True)
    cnt = obj.get("damage_events_count")
    ch.append(("pcs::events_count_int", isinstance(cnt, int) and cnt >= 0,
               "damage_events_count must be an int >= 0", C.PLAYER_COMBAT_STATE_SCHEMA_FAILURE))
    mh, chp = obj.get("max_health"), obj.get("current_health")
    # current_health must be within [0, max] — no negative or over-heal state.
    if RS.is_number(mh) and RS.is_number(chp):
        ch.append(("pcs::health_in_bounds", 0.0 <= chp <= mh,
                   "current_health must be in [0, max_health]", C.PLAYER_COMBAT_STATE_SCHEMA_FAILURE))
    # is_alive must be consistent with current_health (>0 alive, 0 dead) — a state
    # claiming alive at 0 health (or dead with health) is incoherent.
    if RS.is_number(chp) and isinstance(obj.get("is_alive"), bool):
        ch.append(("pcs::alive_consistent", obj.get("is_alive") == (chp > 0),
                   "is_alive must equal current_health > 0", C.PLAYER_COMBAT_STATE_SCHEMA_FAILURE))
    sk = obj.get("save_load_key")
    ch.append(("pcs::save_load_key", isinstance(sk, str) and len(sk) > 0,
               "save_load_key must be a non-empty string (save/load unit)", C.COMBAT_STATE_SAVE_LOAD_FAILURE))
    return ch


def _example_player_combat_state(**over):
    d = {
        "player_instance_id": "player_M", "map_id": "M", "mission_id": "m_M",
        "encounter_id": "enc_M_guarded_objective", "max_health": 100.0, "current_health": 68.0,
        "is_alive": True, "damage_taken_total": 32.0, "damage_events_count": 8,
        "last_damage_source": "npc_pressure", "last_damage_at": 41.5, "invulnerable": False,
        "save_load_key": "combat_M",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# DamageEvent — a single application of damage to the player.
# --------------------------------------------------------------------------- #
DAMAGE_EVENT_SCHEMA_VERSION = "wf.combat.damage_event.v1"
DAMAGE_EVENT_REQUIRED = (
    "damage_event_id", "combat_scenario_id", "source_type", "source_id", "damage_type",
    "amount", "health_before", "health_after", "at_seconds", "telemetry_event",
)
DAMAGE_EVENT_ALLOWED = DAMAGE_EVENT_REQUIRED + ("meta", "schema_version", "report_type")


def validate_damage_event(obj, strict=False):
    ch = RS.check_required(obj, DAMAGE_EVENT_REQUIRED, C.DAMAGE_EVENT_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, DAMAGE_EVENT_ALLOWED, C.DAMAGE_EVENT_SCHEMA_FAILURE, strict)
    ch += RS.check_enum(obj, "source_type", DAMAGE_SOURCE_TYPES, C.DAMAGE_EVENT_SCHEMA_FAILURE)
    ch += RS.check_enum(obj, "damage_type", DAMAGE_TYPES, C.DAMAGE_EVENT_SCHEMA_FAILURE)
    if not isinstance(obj, dict):
        return ch
    for f in ("damage_event_id", "combat_scenario_id", "source_id", "telemetry_event"):
        ch += RS.check_type(obj, f, str, C.DAMAGE_EVENT_SCHEMA_FAILURE, prefix="dmg::")
    ch += _num(obj, "at_seconds", C.DAMAGE_EVENT_SCHEMA_FAILURE, "dmg::", allow_zero=True)
    amt = obj.get("amount")
    hb, ha = obj.get("health_before"), obj.get("health_after")
    # Damage must be strictly positive — a zero-damage "event" is not damage and is
    # the classic fake-combat vector.
    ch.append(("dmg::amount_positive", RS.is_number(amt) and amt > 0,
               "damage amount must be > 0 (no zero-damage event)", C.COMBAT_ZERO_DAMAGE_FAKE))
    for f in ("health_before", "health_after"):
        ch += _num(obj, f, C.DAMAGE_EVENT_SCHEMA_FAILURE, "dmg::", allow_zero=True)
    # Damage accounting must be internally consistent: health decreased, and the
    # drop equals the damage (clamped at 0). An event whose health_after doesn't
    # follow from the amount is a fabricated record.
    if all(RS.is_number(x) for x in (amt, hb, ha)):
        ch.append(("dmg::health_decreased", ha < hb,
                   "health_after must be < health_before (damage reduces health)",
                   C.DAMAGE_ACCOUNTING_INCONSISTENT))
        expected = max(0.0, hb - amt)
        ch.append(("dmg::accounting_consistent", abs(ha - expected) <= 1e-6,
                   "health_after must equal max(0, health_before - amount)",
                   C.DAMAGE_ACCOUNTING_INCONSISTENT))
    return ch


def _example_damage_event(**over):
    d = {
        "damage_event_id": "de_M_0007", "combat_scenario_id": "cs_M_guarded_objective_s0",
        "source_type": "npc_pressure", "source_id": "npc_M_guard_0", "damage_type": "proximity_tick",
        "amount": 4.0, "health_before": 72.0, "health_after": 68.0, "at_seconds": 41.5,
        "telemetry_event": "combat.player.damage.taken",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# CombatTelemetry — the runtime event stream proving combat occurred.
# --------------------------------------------------------------------------- #
COMBAT_TELEMETRY_SCHEMA_VERSION = "wf.combat.telemetry.v1"
COMBAT_EVENT_TYPES = (
    "combat.scenario.started", "combat.map.loaded", "combat.player.health.initialized",
    "combat.npc.spawned", "combat.npc.damage.applied", "combat.hazard.damage.applied",
    "combat.player.damage.taken", "combat.player.health.changed", "combat.player.died",
    "combat.encounter.state_changed", "combat.mission.route_preserved",
    "combat.mission.completed", "combat.combat_state.saved", "combat.combat_state.reload.verified",
    "combat.scenario.completed", "combat.scenario.failed",
)
# The event set a genuine combat_completed_runtime run must contain — proof that
# damage actually occurred and the player survived and completed, not just a map
# that loaded with an NPC on it.
COMPLETION_REQUIRED_COMBAT_EVENTS = (
    "combat.scenario.started", "combat.player.health.initialized",
    "combat.player.damage.taken", "combat.player.health.changed",
    "combat.mission.completed", "combat.combat_state.saved",
    "combat.combat_state.reload.verified", "combat.scenario.completed",
)


def validate_combat_telemetry(obj, strict=False, require_completion=False):
    ch = []
    ok_top = isinstance(obj, dict) and isinstance(obj.get("events"), list)
    ch.append(("ctel::has_events", ok_top, "telemetry must carry an events list",
               C.COMBAT_DAMAGE_TELEMETRY_MISSING))
    if not ok_top:
        return ch
    evs = obj["events"]
    ch.append(("ctel::events_nonempty", len(evs) > 0, "telemetry events must be non-empty",
               C.COMBAT_DAMAGE_TELEMETRY_MISSING))
    seen = set()
    for i, e in enumerate(evs):
        et = e.get("event_type") if isinstance(e, dict) else None
        ok = et in COMBAT_EVENT_TYPES
        ch.append(("ctel::event{}_type".format(i), ok,
                   "event {} type {!r} not in registry".format(i, et), C.COMBAT_TELEMETRY_SCHEMA_FAILURE))
        if ok:
            seen.add(et)
    if require_completion:
        missing = [e for e in COMPLETION_REQUIRED_COMBAT_EVENTS if e not in seen]
        ch.append(("ctel::completion_events_present", not missing,
                   "combat completion telemetry missing events: {}".format(missing),
                   C.COMBAT_DAMAGE_TELEMETRY_MISSING))
        # No player-damage event means no real combat — hard fail for completion.
        ch.append(("ctel::has_damage_event", "combat.player.damage.taken" in seen,
                   "completion telemetry has no player damage event (no real combat)",
                   C.COMBAT_NO_DAMAGE_EVENTS))
    return ch


def _example_combat_telemetry(**over):
    d = {"report_type": COMBAT_TELEMETRY_SCHEMA_VERSION, "combat_scenario_id": "cs_x",
         "events": [{"event_type": t, "frame": i} for i, t in enumerate(COMPLETION_REQUIRED_COMBAT_EVENTS)]}
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# CombatCompletionReport — per-scenario combat outcome (mirrors v1.7 completion).
# --------------------------------------------------------------------------- #
COMBAT_COMPLETION_SCHEMA_VERSION = "wf.combat.combat_completion_report.v1"
COMBAT_COMPLETION_REQUIRED = (
    "report_id", "combat_scenario_id", "behavior_scenario_id", "runtime_scenario_id", "map_id",
    "mission_id", "encounter_id", "biome", "mission_archetype", "pressure_profile", "seed",
    "status", "completion_class", "combat_spawn_result", "player_health_result",
    "damage_application_result", "npc_damage_result", "hazard_damage_result",
    "health_mutation_result", "mission_completion_result", "save_load_result", "balance_result",
    "survivability_band", "telemetry_path", "evidence_paths", "failure_owner", "failure_codes",
    "runtime_duration_seconds", "player_max_health", "player_min_health", "player_final_health",
    "damage_events_seen", "mission_completed", "created_at", "git_commit",
)
# `damage_events`: the top-level list of DamageEvent records the runtime batch
# emits alongside the report (Wave-R-Prime evidence contract §4). Optional/allowed
# here — its contents are validated per-event by validate_damage_event in the
# evidence validators; the completion schema just permits the field so a genuine
# cs_*.json validates under strict check_no_unknown.
COMBAT_COMPLETION_ALLOWED = COMBAT_COMPLETION_REQUIRED + ("meta", "schema_version", "report_type",
                                                          "damage_events")
_COMBAT_RESULT_FIELDS = ("combat_spawn_result", "player_health_result", "damage_application_result",
                         "npc_damage_result", "hazard_damage_result", "health_mutation_result",
                         "mission_completion_result", "save_load_result", "balance_result")


def validate_combat_completion_report(obj, strict=False):
    ch = RS.check_required(obj, COMBAT_COMPLETION_REQUIRED, C.COMBAT_REPORT_INTEGRITY_FAILURE,
                           nullable=("failure_owner",))
    ch += RS.check_no_unknown(obj, COMBAT_COMPLETION_ALLOWED, C.COMBAT_REPORT_INTEGRITY_FAILURE, strict)
    ch += RS.check_enum(obj, "status", RESULT_STATUS, C.COMBAT_REPORT_INTEGRITY_FAILURE)
    ch += RS.check_enum(obj, "completion_class", COMBAT_COMPLETION_CLASSES, C.COMBAT_REPORT_INTEGRITY_FAILURE)
    ch += RS.check_enum(obj, "survivability_band", SURVIVABILITY_BANDS, C.COMBAT_BALANCE_REPORT_FAILURE)
    if not isinstance(obj, dict):
        return ch
    for f in _COMBAT_RESULT_FIELDS:
        ch += RS.check_enum(obj, f, RESULT_STATUS, C.COMBAT_REPORT_INTEGRITY_FAILURE)
    ch.append(("ccr::codes_list", isinstance(obj.get("failure_codes"), list),
               "failure_codes must be a list", C.COMBAT_REPORT_INTEGRITY_FAILURE))
    ch.append(("ccr::evidence_list", isinstance(obj.get("evidence_paths"), list),
               "evidence_paths must be a list", C.COMBAT_REPORT_INTEGRITY_FAILURE))
    ch += _num(obj, "runtime_duration_seconds", C.COMBAT_REPORT_INTEGRITY_FAILURE, "ccr::", allow_zero=False)
    ch.append(("ccr::behavior_scenario_ref",
               isinstance(obj.get("behavior_scenario_id"), str) and len(obj.get("behavior_scenario_id")) > 0,
               "combat completion must reference the v1.7 behavior_scenario_id it layered on",
               C.COMBAT_REPORT_INTEGRITY_FAILURE))
    cls = obj.get("completion_class")
    status = obj.get("status")
    dev = obj.get("damage_events_seen")
    pmax, pmin = obj.get("player_max_health"), obj.get("player_min_health")
    pfin = obj.get("player_final_health")
    # ---- anti-fake-green honesty invariants ----
    if cls == SUCCESS_COMBAT_CLASS:
        ch.append(("ccr::success_is_pass", status == "pass",
                   "combat_completed_runtime must have status=pass", C.COMBAT_FAKE_SUCCESS))
        # Real combat: at least one damage event actually landed.
        ch.append(("ccr::success_has_damage", isinstance(dev, int) and dev > 0,
                   "success with zero damage events is fake combat", C.COMBAT_NO_DAMAGE_EVENTS))
        # Health actually mutated DOWN at runtime: min health strictly below max.
        if all(RS.is_number(x) for x in (pmax, pmin)):
            ch.append(("ccr::success_health_mutated", pmin < pmax,
                       "success requires player_min_health < player_max_health (health mutated)",
                       C.PLAYER_HEALTH_NO_MUTATION))
        else:
            ch.append(("ccr::success_health_numbers", False,
                       "success requires numeric player_min/max_health", C.PLAYER_HEALTH_NO_MUTATION))
        # Survived and completed under baseline: final health > 0 and mission done.
        ch.append(("ccr::success_survived", RS.is_number(pfin) and pfin > 0,
                   "success requires player_final_health > 0 (survived)", C.COMBAT_UNWINNABLE_BASELINE))
        ch.append(("ccr::success_mission_done", obj.get("mission_completed") is True,
                   "success must have mission_completed=true", C.COMBAT_MISSION_COMPLETION_BLOCKED))
        ch.append(("ccr::success_health_result", obj.get("health_mutation_result") == "pass",
                   "success must have health_mutation_result=pass", C.PLAYER_HEALTH_NO_MUTATION))
        ch.append(("ccr::success_save_load", obj.get("save_load_result") == "pass",
                   "success must have save_load_result=pass", C.COMBAT_STATE_SAVE_LOAD_FAILURE))
        ch.append(("ccr::success_survivable_band", obj.get("survivability_band") == "survivable",
                   "success must be in the 'survivable' band", C.COMBAT_BALANCE_REPORT_FAILURE))
        ch.append(("ccr::success_has_telemetry",
                   isinstance(obj.get("telemetry_path"), str) and len(obj.get("telemetry_path")) > 0,
                   "success must reference a telemetry_path", C.COMBAT_DAMAGE_TELEMETRY_MISSING))
        ch.append(("ccr::success_no_codes", len(obj.get("failure_codes") or []) == 0,
                   "success must carry no failure_codes", C.COMBAT_FAKE_SUCCESS))
        ch.append(("ccr::success_results_pass",
                   all(obj.get(f) == "pass" for f in ("combat_spawn_result", "player_health_result",
                                                      "damage_application_result", "health_mutation_result",
                                                      "mission_completion_result")),
                   "success requires spawn/health/damage/mutation/mission results = pass",
                   C.COMBAT_FAKE_SUCCESS))
    else:
        ch.append(("ccr::failure_has_code", len(obj.get("failure_codes") or []) > 0,
                   "a failed completion_class must own a failure_code", C.COMBAT_REPORT_INTEGRITY_FAILURE))
        ch.append(("ccr::failure_not_pass", status != "pass",
                   "a failed completion_class must not have status=pass", C.COMBAT_REPORT_INTEGRITY_FAILURE))
        ch.append(("ccr::failure_has_owner", bool(obj.get("failure_owner")),
                   "a failed completion_class must name a failure_owner", C.COMBAT_REPORT_INTEGRITY_FAILURE))
    return ch


def _example_combat_completion(**over):
    d = {
        "report_id": "combat_cmp:cs_M_guarded_objective_s0",
        "combat_scenario_id": "cs_M_guarded_objective_s0",
        "behavior_scenario_id": "bs_M_guarded_objective_s0", "runtime_scenario_id": "rt_enc_lp_M_s0",
        "map_id": "M", "mission_id": "m_M", "encounter_id": "enc_M_guarded_objective",
        "biome": "volcanic_ashlands", "mission_archetype": "disable_site",
        "pressure_profile": "standard_pressure", "seed": 0, "status": "pass",
        "completion_class": "combat_completed_runtime", "combat_spawn_result": "pass",
        "player_health_result": "pass", "damage_application_result": "pass", "npc_damage_result": "pass",
        "hazard_damage_result": "skipped", "health_mutation_result": "pass",
        "mission_completion_result": "pass", "save_load_result": "pass", "balance_result": "pass",
        "survivability_band": "survivable",
        "telemetry_path": "procedural/reports/combat/telemetry/cs_M.json",
        "evidence_paths": ["procedural/reports/combat/telemetry/cs_M.json"], "failure_owner": None,
        "failure_codes": [], "runtime_duration_seconds": 14.2, "player_max_health": 100.0,
        "player_min_health": 63.0, "player_final_health": 63.0, "damage_events_seen": 9,
        "mission_completed": True, "created_at": "live", "git_commit": "unknown",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry of all contracts, for the schema validator + fuzz harness.
# Each entry: name -> (validate_fn, valid_example_fn, known_bad_example_fn).
# The known-bad MUST fail the validator — a contract that accepts it is fake green.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "CombatProfile": (
        validate_combat_profile, _example_combat_profile,
        # baseline damage >= max health = unwinnable baseline, rejected.
        lambda: _example_combat_profile(baseline_expected_damage=120.0)),
    "PlayerCombatState": (
        validate_player_combat_state, _example_player_combat_state,
        # alive=True at 0 health is incoherent, rejected.
        lambda: _example_player_combat_state(current_health=0.0, is_alive=True)),
    "DamageEvent": (
        validate_damage_event, _example_damage_event,
        # zero-damage event = fake combat, rejected.
        lambda: _example_damage_event(amount=0.0, health_after=72.0)),
    "CombatTelemetry": (
        lambda o, strict=False: validate_combat_telemetry(o, strict=strict, require_completion=True),
        _example_combat_telemetry,
        # completion telemetry missing the player-damage event.
        lambda: {"events": [{"event_type": "combat.scenario.started"},
                            {"event_type": "combat.scenario.completed"}]}),
    "CombatCompletionReport": (
        validate_combat_completion_report, _example_combat_completion,
        # success class with zero damage events / no health mutation = fake green.
        lambda: _example_combat_completion(damage_events_seen=0, player_min_health=100.0)),
}
