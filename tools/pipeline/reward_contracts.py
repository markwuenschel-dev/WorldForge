#!/usr/bin/env python3
"""reward_contracts.py — WorldForge v1.9 Reward/Loadout/Progression Alpha spine.

Turns mission and combat completion (the v1.8 CombatForge substrate,
[[worldforge_v1_8-combatforge]]) into durable player consequence: reward grants,
inventory mutation, progression/XP, unlock state, and a next-mission state
handoff. This is the persistence-and-consequence substrate — NOT a loot game.

One module, one section per contract, each with X_REQUIRED / X_ALLOWED field
sets, a ``validate_X(obj, strict)`` returning ``(name, ok, detail, code)`` check
tuples in the exact shape ValidationReport.check consumes, and a canonical
``_example_X`` factory. A ``CONTRACTS`` registry pairs each validator with a
valid example and a known-bad example so the schema gates can dogfood that every
contract actually constrains (a contract that accepts its own known-bad is a
fake-green vector). ``CONTRACT_GROUPS`` splits the registry into the loadout,
reward, and progression lanes the three contract gates dogfood separately.

The honesty invariants live here at the schema layer:
  * a RewardGrantEvent must reference a real mission completion and mutate
    inventory or progression (pre/post state hashes must differ) unless it is
    explicitly a no_reward grant;
  * a RewardCompletionReport whose class is rewarded MUST show inventory or
    progression mutation, a resolved reward table, and a save/load pass;
  * grant_once rewards cannot be granted twice;
  * inventory/progression hashes must match their contents;
  * risk/reward class must be consistent with the reward value delivered.

Contracts:
  LoadoutProfile          validate_loadout_profile        (loadout lane)
  EquipmentItem           validate_equipment_item         (loadout lane)
  RewardTable             validate_reward_table           (reward lane)
  RewardGrantEvent        validate_reward_grant_event     (reward lane)
  RewardCompletionReport  validate_reward_completion_report (reward lane)
  InventoryState          validate_inventory_state        (progression lane)
  ProgressionState        validate_progression_state      (progression lane)
  UnlockState             validate_unlock_state           (progression lane)
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]
C = FailureCode

# --------------------------------------------------------------------------- #
# Taxonomy — the reward/progression vocabulary. One source of truth for every
# generator / validator / shield.
# --------------------------------------------------------------------------- #
# The v1.3 MISSION archetypes rewards key off (mirrors mission_contract.
# MISSION_ARCHETYPES — the vocabulary real missions and v1.8 combat completion
# reports use for `mission_archetype`). Redefined locally, house style.
MISSION_ARCHETYPES = (
    "disable_site", "recover_resource", "survey_landmark",
    "clear_hazard", "restore_power", "extract_cache",
)

# The 8 v1.4/v1.8 ENCOUNTER archetypes — combat pressure shape, referenced only
# indirectly by a reward table via its combat_profile_id (a CombatProfile carries
# the encounter_archetype). Kept for linkage/reference; NOT the reward-table key.
ENCOUNTER_ARCHETYPES = (
    "guarded_objective", "patrol_route", "ambush_choke", "hazard_field",
    "resource_contest", "defensive_holdout", "roaming_threat", "extraction_pressure",
)

# The 5 real biome families in encounter_loop_world (grounded in v1.8 combat
# evidence). Biome is validated as a non-empty string, not enum-locked, so packs
# with additional biomes stay valid; this set drives deterministic generation.
KNOWN_BIOMES = (
    "alien_crystal_badlands", "alpine_snow", "volcanic_ashlands",
    "temperate_forest", "wetland_mire",
)

# Equipment slots a loadout exposes. Bounded and explicit — no arbitrary slots.
EQUIPMENT_SLOTS = ("primary", "secondary", "tool", "consumable")

# Equipment item types. Deliberately small — v1.9 is a substrate, not itemization.
ITEM_TYPES = ("weapon", "tool", "consumable", "gadget", "armor")

# Rarity bands. Bounded ladder; NOT a rarity casino — just a value tier.
RARITY_BANDS = ("common", "uncommon", "rare", "elite")

# Ownership classes carried through from the asset spine.
OWNERSHIP_CLASSES = ("generated_owned", "third_party_owned", "human_owned")

# Reward entry types a reward table can grant.
REWARD_TYPES = ("item", "xp", "unlock", "currency", "no_reward")

# Risk bands a reward table keys off (mirrors combat survivability pressure).
RISK_BANDS = ("low", "baseline", "high", "extreme")

# Minimum mission result an entry requires before it can be granted.
MISSION_RESULTS = ("attempted", "partial", "completed")

# Unlock types — what an unlock affects. affects_generation must be explicit.
UNLOCK_TYPES = ("loadout_slot", "equipment", "mission_archetype", "biome", "modifier")

# Risk/reward classification bands. Only over_rewarded / exploit_suspected /
# invalid are blocking; under_rewarded is a warning surface.
RISK_REWARD_CLASSES = (
    "no_reward", "baseline_reward", "high_risk_high_reward",
    "over_rewarded", "under_rewarded", "exploit_suspected", "invalid",
)
BLOCKING_RISK_REWARD_CLASSES = ("over_rewarded", "exploit_suspected", "invalid")

# Exploit classifier verdicts.
EXPLOIT_RESULTS = ("clean", "suspected", "confirmed")

RESULT_STATUS = ("pass", "fail", "skipped", "not_implemented")

# Reward telemetry event vocabulary — the runtime event stream proving a reward
# was actually granted and persisted (not just claimed in a report).
REWARD_EVENT_TYPES = (
    "reward.scenario.started", "reward.mission.completion.read", "reward.combat.completion.read",
    "reward.table.selected", "reward.grant.applied", "reward.inventory.mutated",
    "reward.progression.mutated", "reward.unlock.granted", "reward.state.saved",
    "reward.state.reload.verified", "reward.next_mission.state.written",
    "reward.risk_reward.classified", "reward.scenario.completed", "reward.scenario.failed",
    "reward.scenario.no_reward",
)
# The event set a genuine reward_granted_runtime run must contain — proof the
# grant happened, mutated state, and persisted through reload.
COMPLETION_REQUIRED_REWARD_EVENTS = (
    "reward.scenario.started", "reward.mission.completion.read", "reward.table.selected",
    "reward.grant.applied", "reward.state.saved", "reward.state.reload.verified",
    "reward.scenario.completed",
)

# RewardCompletionReport completion classes. The one success class is
# reward_granted_runtime — everything else names an owned failure surface.
REWARD_COMPLETION_CLASSES = (
    "reward_granted_runtime",
    "no_reward_runtime",          # honest: completion classified as no_reward
    "failed_reward_table_select", "failed_reward_grant", "failed_inventory_mutation",
    "failed_progression_mutation", "failed_unlock_grant", "failed_reward_save_load",
    "failed_inventory_save_load", "failed_progression_save_load",
    "failed_next_mission_state", "failed_risk_reward_class", "failed_report_integrity",
)
SUCCESS_REWARD_CLASS = "reward_granted_runtime"
NO_REWARD_CLASS = "no_reward_runtime"

# Report type identifiers.
RT_LOADOUT_PROFILE = "wf.reward.loadout_profile.v1"
RT_EQUIPMENT_ITEM = "wf.reward.equipment_item.v1"
RT_REWARD_TABLE = "wf.reward.reward_table.v1"
RT_REWARD_GRANT_EVENT = "wf.reward.reward_grant_event.v1"
RT_INVENTORY_STATE = "wf.reward.inventory_state.v1"
RT_PROGRESSION_STATE = "wf.reward.progression_state.v1"
RT_UNLOCK_STATE = "wf.reward.unlock_state.v1"
RT_REWARD_COMPLETION = "wf.reward.reward_completion_report.v1"
RT_RISK_REWARD_BALANCE = "wf.reward.risk_reward_balance.v1"
RT_SHIELD_ROLLUP = "wf.v1_9.full_shield_rollup.v1"

# Independent runtime save slots — v1.9 reward/progression state must NOT reuse
# the mission/NPC/combat slots (WFRuntime_Complete / WFNPC_State / WFCombat_State).
REWARD_SAVE_SLOT = "WFReward_State"
INVENTORY_SAVE_SLOT = "WFInventory_State"
PROGRESSION_SAVE_SLOT = "WFProgression_State"
FORBIDDEN_SAVE_SLOTS = ("WFRuntime_Complete", "WFNPC_State", "WFCombat_State")

# Generated / report roots (repo-relative) — reward/progression state is
# independently inspectable and never mixed into combat/npc/runtime reports.
LOADOUT_GENERATED_REL = "procedural/generated/loadouts"
REWARD_TABLE_GENERATED_REL = "procedural/generated/rewards/tables"
REWARD_EVENT_GENERATED_REL = "procedural/generated/rewards/events"
PROGRESSION_GENERATED_REL = "procedural/generated/progression"
REWARD_COMPLETION_REPORTS_REL = "procedural/reports/rewards/completion"
REWARD_TELEMETRY_REPORTS_REL = "procedural/reports/rewards/telemetry"
REWARD_SAVE_LOAD_REPORTS_REL = "procedural/reports/rewards/save_load"
PROGRESSION_REPORTS_REL = "procedural/reports/progression"


def runtime_realized_reward_maps(completion_dir):
    """The set of maps genuinely realized WITH A REWARD GRANT at runtime, derived
    only from committed reward-completion evidence: a map counts iff it has >=1
    completion report whose completion_class is SUCCESS_REWARD_CLASS with
    inventory_mutated OR progression_mutated true (real durable consequence).
    Single source of truth shared by the batch writer and the gate so the two can
    never drift — reward realization cannot be greened without real state
    mutation. Returns a set of map_id strings."""
    import json as _json
    from pathlib import Path as _Path
    d = _Path(completion_dir)
    realized = set()
    if not d.is_dir():
        return realized
    for f in sorted(d.glob("reward_completion_*.json")):
        try:
            r = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if (r.get("completion_class") == SUCCESS_REWARD_CLASS
                and (r.get("inventory_mutated") is True or r.get("progression_mutated") is True)
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


def _str(obj, field, code, prefix):
    return RS.check_type(obj, field, str, code, prefix=prefix)


# --------------------------------------------------------------------------- #
# LoadoutProfile — the player's equipped slots for a scenario, bounded by power
# and risk budgets and by what the mission archetype / biome allows.
# --------------------------------------------------------------------------- #
LOADOUT_PROFILE_SCHEMA_VERSION = RT_LOADOUT_PROFILE
LOADOUT_PROFILE_REQUIRED = (
    "loadout_profile_id", "player_id", "scenario_id", "primary_slot", "secondary_slot",
    "tool_slot", "consumable_slots", "allowed_mission_archetypes", "allowed_biomes",
    "power_budget", "risk_budget", "source",
)
LOADOUT_PROFILE_ALLOWED = LOADOUT_PROFILE_REQUIRED + (
    "meta", "schema_version", "report_type", "created_by", "created_at")
_LP_STR_FIELDS = ("loadout_profile_id", "player_id", "scenario_id", "source")


def validate_loadout_profile(obj, strict=False):
    ch = RS.check_required(obj, LOADOUT_PROFILE_REQUIRED, C.LOADOUT_CONTRACT_INVALID,
                           nullable=("secondary_slot",))
    ch += RS.check_no_unknown(obj, LOADOUT_PROFILE_ALLOWED, C.LOADOUT_CONTRACT_INVALID, strict)
    if not isinstance(obj, dict):
        return ch
    for f in _LP_STR_FIELDS:
        ch += _str(obj, f, C.LOADOUT_CONTRACT_INVALID, "lp::")
    for f in ("consumable_slots", "allowed_mission_archetypes", "allowed_biomes"):
        ch += _list(obj, f, C.LOADOUT_CONTRACT_INVALID, "lp::", min_len=1)
    # Budgets must be finite and bounded (non-negative). Unbounded budgets are the
    # classic "grant anything" vector.
    ch += _num(obj, "power_budget", C.LOADOUT_CONTRACT_INVALID, "lp::", allow_zero=False)
    ch += _num(obj, "risk_budget", C.LOADOUT_CONTRACT_INVALID, "lp::", allow_zero=False)
    # primary_slot is required equipment; tool_slot required; secondary may be null.
    for f in ("primary_slot", "tool_slot"):
        ch.append(("lp::{}_present".format(f),
                   isinstance(obj.get(f), str) and len(obj.get(f)) > 0,
                   "{} must name an equipment item_id".format(f), C.LOADOUT_CONTRACT_INVALID))
    # Allowed mission archetypes must all be known — an unknown archetype means the
    # loadout could be applied where it was never validated.
    ams = obj.get("allowed_mission_archetypes")
    if isinstance(ams, list):
        bad = [a for a in ams if a not in MISSION_ARCHETYPES]
        ch.append(("lp::archetypes_known", not bad,
                   "unknown allowed_mission_archetypes: {}".format(bad), C.LOADOUT_CONTRACT_INVALID))
    # No duplicate exclusive equipment across primary/secondary/tool.
    exclusive = [obj.get(f) for f in ("primary_slot", "secondary_slot", "tool_slot")
                 if isinstance(obj.get(f), str) and obj.get(f)]
    ch.append(("lp::no_duplicate_exclusive", len(exclusive) == len(set(exclusive)),
               "primary/secondary/tool must not hold the same item_id twice",
               C.LOADOUT_CONTRACT_INVALID))
    return ch


def _example_loadout_profile(**over):
    d = {
        "loadout_profile_id": "lo_scout_std", "player_id": "player_M", "scenario_id": "rs_M_s0",
        "primary_slot": "eq_rifle_std", "secondary_slot": "eq_sidearm_std", "tool_slot": "eq_scanner",
        "consumable_slots": ["eq_medkit"], "allowed_mission_archetypes": ["disable_site", "recover_resource"],
        "allowed_biomes": ["volcanic_ashlands", "alpine_snow"], "power_budget": 100.0, "risk_budget": 60.0,
        "source": "generated",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# EquipmentItem — a single item that can occupy a loadout slot.
# --------------------------------------------------------------------------- #
EQUIPMENT_ITEM_SCHEMA_VERSION = RT_EQUIPMENT_ITEM
EQUIPMENT_ITEM_REQUIRED = (
    "item_id", "item_type", "display_name", "slot", "rarity_band", "power_value",
    "risk_value", "allowed_loadout_profiles", "allowed_mission_archetypes", "tags",
    "ownership_class", "provenance",
)
EQUIPMENT_ITEM_ALLOWED = EQUIPMENT_ITEM_REQUIRED + (
    "meta", "schema_version", "report_type", "created_by", "created_at")


def validate_equipment_item(obj, strict=False):
    ch = RS.check_required(obj, EQUIPMENT_ITEM_REQUIRED, C.EQUIPMENT_ITEM_INVALID)
    ch += RS.check_no_unknown(obj, EQUIPMENT_ITEM_ALLOWED, C.EQUIPMENT_ITEM_INVALID, strict)
    ch += RS.check_enum(obj, "item_type", ITEM_TYPES, C.EQUIPMENT_ITEM_INVALID)
    ch += RS.check_enum(obj, "slot", EQUIPMENT_SLOTS, C.EQUIPMENT_ITEM_INVALID)
    ch += RS.check_enum(obj, "rarity_band", RARITY_BANDS, C.EQUIPMENT_ITEM_INVALID)
    ch += RS.check_enum(obj, "ownership_class", OWNERSHIP_CLASSES, C.EQUIPMENT_ITEM_INVALID)
    if not isinstance(obj, dict):
        return ch
    for f in ("item_id", "display_name"):
        ch += _str(obj, f, C.EQUIPMENT_ITEM_INVALID, "eq::")
    for f in ("allowed_loadout_profiles", "allowed_mission_archetypes", "tags"):
        ch += _list(obj, f, C.EQUIPMENT_ITEM_INVALID, "eq::", min_len=0)
    # power/risk must be finite and non-negative.
    ch += _num(obj, "power_value", C.EQUIPMENT_ITEM_INVALID, "eq::", allow_zero=True)
    ch += _num(obj, "risk_value", C.EQUIPMENT_ITEM_INVALID, "eq::", allow_zero=True)
    # provenance must be present and non-empty (ownership spine invariant).
    prov = obj.get("provenance")
    ch.append(("eq::provenance_present", bool(prov),
               "provenance must be present", C.EQUIPMENT_ITEM_INVALID))
    return ch


def _example_equipment_item(**over):
    d = {
        "item_id": "eq_rifle_std", "item_type": "weapon", "display_name": "Standard Rifle",
        "slot": "primary", "rarity_band": "common", "power_value": 20.0, "risk_value": 5.0,
        "allowed_loadout_profiles": ["lo_scout_std"], "allowed_mission_archetypes": ["disable_site"],
        "tags": ["ranged", "starter"], "ownership_class": "generated_owned",
        "provenance": {"generator": "reward_forge", "seed": 0},
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# RewardTable — deterministic reward entries keyed by archetype/biome/combat/risk.
# --------------------------------------------------------------------------- #
REWARD_TABLE_SCHEMA_VERSION = RT_REWARD_TABLE
REWARD_TABLE_REQUIRED = (
    "reward_table_id", "pack_id", "mission_archetype", "biome", "combat_profile_id",
    "risk_band", "reward_entries", "budget_min", "budget_max", "anti_exploit_rules",
)
REWARD_TABLE_ALLOWED = REWARD_TABLE_REQUIRED + (
    "meta", "schema_version", "report_type", "seed", "created_by", "created_at")
REWARD_ENTRY_REQUIRED = (
    "reward_entry_id", "reward_type", "item_id", "xp_amount", "unlock_id",
    "currency_amount", "weight", "min_mission_result", "max_repeat_count", "grant_once",
)


def validate_reward_entry(entry, prefix, strict=False):
    ch = []
    if not isinstance(entry, dict):
        return [("{}entry_object".format(prefix), False, "reward entry must be an object",
                 C.REWARD_TABLE_INVALID)]
    ch += RS.check_required(entry, REWARD_ENTRY_REQUIRED, C.REWARD_TABLE_INVALID,
                            nullable=("item_id", "unlock_id"))
    ch += RS.check_enum(entry, "reward_type", REWARD_TYPES, C.REWARD_TABLE_INVALID, prefix=prefix)
    ch += RS.check_enum(entry, "min_mission_result", MISSION_RESULTS, C.REWARD_TABLE_INVALID, prefix=prefix)
    ch += _bool(entry, "grant_once", C.REWARD_TABLE_INVALID, prefix)
    # weight must be strictly positive — a zero/negative-weight entry can never (or
    # always) fire and is a table-authoring bug.
    ch += RS.check_positive_number(entry, "weight", C.REWARD_TABLE_INVALID, prefix=prefix, allow_zero=False)
    for f in ("xp_amount", "currency_amount"):
        ch += RS.check_positive_number(entry, f, C.REWARD_TABLE_INVALID, prefix=prefix, allow_zero=True)
    rt = entry.get("reward_type")
    # A rewarding entry must actually reference the thing it grants.
    if rt == "item":
        ch.append(("{}item_ref".format(prefix), bool(entry.get("item_id")),
                   "item reward must reference an item_id", C.REWARD_TABLE_INVALID))
    elif rt == "unlock":
        ch.append(("{}unlock_ref".format(prefix), bool(entry.get("unlock_id")),
                   "unlock reward must reference an unlock_id", C.REWARD_TABLE_INVALID))
    elif rt == "xp":
        ch.append(("{}xp_positive".format(prefix), RS.is_number(entry.get("xp_amount")) and entry.get("xp_amount") > 0,
                   "xp reward must grant xp_amount > 0", C.REWARD_TABLE_INVALID))
    # grant_once entries need a stable id; repeatable entries need a repeat cap.
    go = entry.get("grant_once")
    mrc = entry.get("max_repeat_count")
    if go is True:
        ch.append(("{}grant_once_stable_id".format(prefix), bool(entry.get("reward_entry_id")),
                   "grant_once reward must have a stable reward_entry_id", C.REWARD_DUPLICATE_GRANT))
    elif go is False:
        ch.append(("{}repeat_cap".format(prefix), isinstance(mrc, int) and mrc >= 1,
                   "repeatable reward must set max_repeat_count >= 1", C.REWARD_TABLE_INVALID))
    return ch


def validate_reward_table(obj, strict=False):
    ch = RS.check_required(obj, REWARD_TABLE_REQUIRED, C.REWARD_TABLE_INVALID)
    ch += RS.check_no_unknown(obj, REWARD_TABLE_ALLOWED, C.REWARD_TABLE_INVALID, strict)
    ch += RS.check_enum(obj, "mission_archetype", MISSION_ARCHETYPES, C.REWARD_TABLE_INVALID)
    ch += RS.check_enum(obj, "risk_band", RISK_BANDS, C.REWARD_TABLE_INVALID)
    if not isinstance(obj, dict):
        return ch
    for f in ("reward_table_id", "pack_id", "biome", "combat_profile_id"):
        ch += _str(obj, f, C.REWARD_TABLE_INVALID, "rt::")
    ch += _list(obj, "reward_entries", C.REWARD_TABLE_INVALID, "rt::", min_len=1)
    ch += _list(obj, "anti_exploit_rules", C.REWARD_TABLE_INVALID, "rt::", min_len=1)
    # Budget range must be valid: 0 <= min <= max.
    bmin, bmax = obj.get("budget_min"), obj.get("budget_max")
    ch += RS.check_positive_number(obj, "budget_min", C.REWARD_TABLE_INVALID, prefix="rt::", allow_zero=True)
    ch += RS.check_positive_number(obj, "budget_max", C.REWARD_TABLE_INVALID, prefix="rt::", allow_zero=True)
    if RS.is_number(bmin) and RS.is_number(bmax):
        ch.append(("rt::budget_range_valid", bmin <= bmax,
                   "budget_min must be <= budget_max", C.REWARD_TABLE_INVALID))
    entries = obj.get("reward_entries")
    if isinstance(entries, list):
        ids = []
        for i, e in enumerate(entries):
            ch += validate_reward_entry(e, "rt::entry{}::".format(i), strict=strict)
            if isinstance(e, dict):
                ids.append(e.get("reward_entry_id"))
        ch.append(("rt::entry_ids_unique", len(ids) == len(set(ids)),
                   "reward_entry_id must be unique within a table", C.REWARD_DUPLICATE_GRANT))
    return ch


def _example_reward_entry(**over):
    d = {
        "reward_entry_id": "re_xp_base", "reward_type": "xp", "item_id": None, "xp_amount": 100.0,
        "unlock_id": None, "currency_amount": 0.0, "weight": 1.0, "min_mission_result": "completed",
        "max_repeat_count": 5, "grant_once": False,
    }
    d.update(over)
    return d


def _example_reward_table(**over):
    d = {
        "reward_table_id": "rwt_disable_site_ash_baseline", "pack_id": "encounter_loop_world",
        "mission_archetype": "disable_site", "biome": "volcanic_ashlands",
        "combat_profile_id": "cp_guard_pressure", "risk_band": "baseline",
        "reward_entries": [
            _example_reward_entry(),
            _example_reward_entry(reward_entry_id="re_item_rifle", reward_type="item",
                                  item_id="eq_rifle_std", xp_amount=0.0, weight=1.0,
                                  grant_once=True, max_repeat_count=1),
        ],
        "budget_min": 50.0, "budget_max": 200.0,
        "anti_exploit_rules": ["grant_once_stable", "budget_capped"],
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# RewardGrantEvent — a single reward grant, linked to a completion, mutating state.
# --------------------------------------------------------------------------- #
REWARD_GRANT_EVENT_SCHEMA_VERSION = RT_REWARD_GRANT_EVENT
REWARD_GRANT_EVENT_REQUIRED = (
    "event_id", "scenario_id", "mission_id", "player_id", "reward_table_id",
    "reward_entry_id", "reward_type", "granted_item_id", "xp_amount", "unlock_id",
    "pre_inventory_hash", "post_inventory_hash", "pre_progression_hash",
    "post_progression_hash", "timestamp", "frame", "source_completion_report",
    "source_combat_report",
)
REWARD_GRANT_EVENT_ALLOWED = REWARD_GRANT_EVENT_REQUIRED + (
    "meta", "schema_version", "report_type")


def validate_reward_grant_event(obj, strict=False):
    ch = RS.check_required(obj, REWARD_GRANT_EVENT_REQUIRED, C.REWARD_GRANT_EVENT_INVALID,
                           nullable=("granted_item_id", "unlock_id", "source_combat_report"))
    ch += RS.check_no_unknown(obj, REWARD_GRANT_EVENT_ALLOWED, C.REWARD_GRANT_EVENT_INVALID, strict)
    ch += RS.check_enum(obj, "reward_type", REWARD_TYPES, C.REWARD_GRANT_EVENT_INVALID)
    if not isinstance(obj, dict):
        return ch
    for f in ("event_id", "scenario_id", "mission_id", "player_id", "reward_table_id",
              "reward_entry_id"):
        ch += _str(obj, f, C.REWARD_GRANT_EVENT_INVALID, "rge::")
    # Must reference a real mission completion report — a grant with no source is a
    # fabricated reward (fake green).
    ch.append(("rge::source_completion_ref",
               isinstance(obj.get("source_completion_report"), str) and len(obj.get("source_completion_report")) > 0,
               "reward grant must reference a source_completion_report", C.REWARD_WITHOUT_COMPLETION))
    ch += RS.check_positive_number(obj, "xp_amount", C.REWARD_GRANT_EVENT_INVALID, prefix="rge::", allow_zero=True)
    # State hashes must be present strings.
    for f in ("pre_inventory_hash", "post_inventory_hash", "pre_progression_hash", "post_progression_hash"):
        ch += _str(obj, f, C.REWARD_GRANT_EVENT_INVALID, "rge::")
    rt = obj.get("reward_type")
    inv_mut = _hash_differs(obj.get("pre_inventory_hash"), obj.get("post_inventory_hash"))
    prog_mut = _hash_differs(obj.get("pre_progression_hash"), obj.get("post_progression_hash"))
    if rt == "no_reward":
        # A no_reward grant must NOT mutate state — that would be a hidden grant.
        ch.append(("rge::no_reward_no_mutation", not (inv_mut or prog_mut),
                   "no_reward grant must not mutate inventory or progression",
                   C.REWARD_GRANT_EVENT_INVALID))
    else:
        # A rewarding grant MUST mutate inventory or progression — a reward that
        # only appears in the event but changes no durable state is fake.
        ch.append(("rge::mutates_state", inv_mut or prog_mut,
                   "reward grant must mutate inventory or progression (pre/post hash differ)",
                   C.REWARD_GRANT_INVALID))
    return ch


def _hash_differs(a, b):
    return isinstance(a, str) and isinstance(b, str) and a != b


def _example_reward_grant_event(**over):
    d = {
        "event_id": "rge_M_s0_0001", "scenario_id": "rs_M_s0", "mission_id": "m_M", "player_id": "player_M",
        "reward_table_id": "rwt_disable_site_ash_baseline", "reward_entry_id": "re_xp_base", "reward_type": "xp",
        "granted_item_id": None, "xp_amount": 100.0, "unlock_id": None,
        "pre_inventory_hash": "inv:aaaa", "post_inventory_hash": "inv:aaaa",
        "pre_progression_hash": "prog:0001", "post_progression_hash": "prog:0002",
        "timestamp": "live", "frame": 512,
        "source_completion_report": "procedural/reports/rewards/completion/reward_completion_rs_M_s0.json",
        "source_combat_report": "procedural/reports/combat/completion/cs_M.json",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# InventoryState — durable item inventory (independent save/load unit).
# --------------------------------------------------------------------------- #
INVENTORY_STATE_SCHEMA_VERSION = RT_INVENTORY_STATE
INVENTORY_STATE_REQUIRED = (
    "player_id", "scenario_id", "inventory_id", "items", "capacity",
    "equipped_loadout_id", "inventory_hash", "save_load_key",
)
INVENTORY_STATE_ALLOWED = INVENTORY_STATE_REQUIRED + (
    "meta", "schema_version", "report_type")
INVENTORY_ITEM_REQUIRED = (
    "item_instance_id", "item_id", "quantity", "bound", "source_reward_event", "acquired_at",
)


def _inventory_hash(items):
    """Deterministic content hash of an inventory item list — the same function the
    runtime state model must mirror so inventory_hash can be independently checked."""
    import hashlib
    payload = "|".join(
        "{}:{}:{}".format(i.get("item_instance_id"), i.get("item_id"), i.get("quantity"))
        for i in sorted(items, key=lambda x: str(x.get("item_instance_id"))))
    return "inv:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def validate_inventory_state(obj, strict=False):
    ch = RS.check_required(obj, INVENTORY_STATE_REQUIRED, C.INVENTORY_STATE_INVALID)
    ch += RS.check_no_unknown(obj, INVENTORY_STATE_ALLOWED, C.INVENTORY_STATE_INVALID, strict)
    if not isinstance(obj, dict):
        return ch
    for f in ("player_id", "scenario_id", "inventory_id", "equipped_loadout_id",
              "inventory_hash", "save_load_key"):
        ch += _str(obj, f, C.INVENTORY_STATE_INVALID, "inv::")
    ch += _list(obj, "items", C.INVENTORY_STATE_INVALID, "inv::", min_len=0)
    ch.append(("inv::capacity_int", isinstance(obj.get("capacity"), int) and obj.get("capacity") >= 0,
               "capacity must be an int >= 0", C.INVENTORY_STATE_INVALID))
    # save/load key must be the reward/inventory slot, never a combat/mission slot.
    sk = obj.get("save_load_key")
    ch.append(("inv::save_load_key_dedicated",
               isinstance(sk, str) and sk not in FORBIDDEN_SAVE_SLOTS,
               "inventory save_load_key must not reuse a combat/mission/npc slot",
               C.INVENTORY_SAVE_LOAD_FAILED))
    items = obj.get("items")
    if isinstance(items, list):
        iids = []
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                ch.append(("inv::item{}_object".format(i), False, "inventory item must be an object",
                           C.INVENTORY_STATE_INVALID))
                continue
            ch += RS.check_required(it, INVENTORY_ITEM_REQUIRED, C.INVENTORY_STATE_INVALID,
                                    prefix="inv::item{}::".format(i))
            q = it.get("quantity")
            ch.append(("inv::item{}_qty_positive".format(i), isinstance(q, int) and q > 0,
                       "quantity must be an int > 0", C.INVENTORY_STATE_INVALID))
            iids.append(it.get("item_instance_id"))
        ch.append(("inv::instance_ids_unique", len(iids) == len(set(iids)),
                   "item_instance_id must be unique", C.INVENTORY_STATE_INVALID))
        # Capacity must not be exceeded.
        cap = obj.get("capacity")
        if isinstance(cap, int):
            ch.append(("inv::capacity_not_exceeded", len(items) <= cap,
                       "inventory item count exceeds capacity", C.INVENTORY_CAPACITY_EXCEEDED))
        # inventory_hash must match the contents.
        ih = obj.get("inventory_hash")
        if isinstance(ih, str) and all(isinstance(x, dict) for x in items):
            ch.append(("inv::hash_matches", ih == _inventory_hash(items),
                       "inventory_hash must match item contents", C.INVENTORY_HASH_MISMATCH))
    return ch


def _example_inventory_state(**over):
    items = [{
        "item_instance_id": "ii_M_0001", "item_id": "eq_medkit", "quantity": 2, "bound": False,
        "source_reward_event": "rge_M_s0_0002", "acquired_at": "live",
    }]
    d = {
        "player_id": "player_M", "scenario_id": "rs_M_s0", "inventory_id": "inv_M", "items": items,
        "capacity": 32, "equipped_loadout_id": "lo_scout_std", "inventory_hash": _inventory_hash(items),
        "save_load_key": INVENTORY_SAVE_SLOT,
    }
    d.update(over)
    # Keep the hash coherent if the caller overrode items but not the hash.
    if "items" in over and "inventory_hash" not in over:
        d["inventory_hash"] = _inventory_hash(d["items"])
    return d


# --------------------------------------------------------------------------- #
# ProgressionState — durable XP / level / unlocks / completed history.
# --------------------------------------------------------------------------- #
PROGRESSION_STATE_SCHEMA_VERSION = RT_PROGRESSION_STATE
PROGRESSION_STATE_REQUIRED = (
    "player_id", "scenario_id", "level", "xp_total", "xp_delta", "unlocks",
    "completed_missions", "completed_encounters", "progression_hash", "save_load_key",
)
PROGRESSION_STATE_ALLOWED = PROGRESSION_STATE_REQUIRED + (
    "meta", "schema_version", "report_type", "source_reward_event")

# XP -> level curve. Level N requires LEVEL_XP_CURVE[N-1] cumulative XP. Bounded,
# deterministic, and the single source of truth shared with the runtime level calc.
LEVEL_XP_CURVE = (0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500)


def level_for_xp(xp_total):
    """Level derived from cumulative XP via LEVEL_XP_CURVE. Bounded at the top."""
    if not RS.is_number(xp_total) or xp_total < 0:
        return None
    lvl = 1
    for i, threshold in enumerate(LEVEL_XP_CURVE):
        if xp_total >= threshold:
            lvl = i + 1
    return lvl


def _progression_hash(level, xp_total, unlocks, completed_missions):
    import hashlib
    payload = "{}|{}|{}|{}".format(
        level, xp_total, ",".join(sorted(unlocks or [])), ",".join(sorted(completed_missions or [])))
    return "prog:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def validate_progression_state(obj, strict=False):
    ch = RS.check_required(obj, PROGRESSION_STATE_REQUIRED, C.PROGRESSION_STATE_INVALID)
    ch += RS.check_no_unknown(obj, PROGRESSION_STATE_ALLOWED, C.PROGRESSION_STATE_INVALID, strict)
    if not isinstance(obj, dict):
        return ch
    for f in ("player_id", "scenario_id", "progression_hash", "save_load_key"):
        ch += _str(obj, f, C.PROGRESSION_STATE_INVALID, "prog::")
    for f in ("unlocks", "completed_missions", "completed_encounters"):
        ch += _list(obj, f, C.PROGRESSION_STATE_INVALID, "prog::", min_len=0)
    # xp_total must be non-negative; xp_delta may be any non-negative grant.
    xt, xd = obj.get("xp_total"), obj.get("xp_delta")
    ch += RS.check_positive_number(obj, "xp_total", C.PROGRESSION_STATE_INVALID, prefix="prog::", allow_zero=True)
    ch += RS.check_positive_number(obj, "xp_delta", C.PROGRESSION_STATE_INVALID, prefix="prog::", allow_zero=True)
    lvl = obj.get("level")
    ch.append(("prog::level_int", isinstance(lvl, int) and lvl >= 1,
               "level must be an int >= 1", C.PROGRESSION_STATE_INVALID))
    # level must match the XP curve.
    if isinstance(lvl, int) and RS.is_number(xt):
        expected = level_for_xp(xt)
        ch.append(("prog::level_matches_curve", lvl == expected,
                   "level {} does not match XP curve (expected {})".format(lvl, expected),
                   C.LEVEL_CURVE_MISMATCH))
    # dedicated save slot.
    sk = obj.get("save_load_key")
    ch.append(("prog::save_load_key_dedicated",
               isinstance(sk, str) and sk not in FORBIDDEN_SAVE_SLOTS,
               "progression save_load_key must not reuse a combat/mission/npc slot",
               C.PROGRESSION_SAVE_LOAD_FAILED))
    # progression_hash must match contents.
    ph = obj.get("progression_hash")
    if isinstance(ph, str) and isinstance(lvl, int) and RS.is_number(xt):
        ch.append(("prog::hash_matches",
                   ph == _progression_hash(lvl, xt, obj.get("unlocks"), obj.get("completed_missions")),
                   "progression_hash must match contents", C.PROGRESSION_HASH_MISMATCH))
    return ch


def _example_progression_state(**over):
    level, xp_total = 2, 150.0
    unlocks = ["unl_scout_slot"]
    completed = ["m_M"]
    d = {
        "player_id": "player_M", "scenario_id": "rs_M_s0", "level": level, "xp_total": xp_total,
        "xp_delta": 100.0, "unlocks": unlocks, "completed_missions": completed,
        "completed_encounters": ["enc_M_guarded_objective"],
        "progression_hash": _progression_hash(level, xp_total, unlocks, completed),
        "save_load_key": PROGRESSION_SAVE_SLOT,
    }
    d.update(over)
    # Recompute derived fields when the caller overrides inputs but not the hash.
    if any(k in over for k in ("level", "xp_total", "unlocks", "completed_missions")) and "progression_hash" not in over:
        d["progression_hash"] = _progression_hash(
            d["level"], d["xp_total"], d["unlocks"], d["completed_missions"])
    return d


# --------------------------------------------------------------------------- #
# UnlockState — a durable unlock that the NEXT mission generation can consume.
# --------------------------------------------------------------------------- #
UNLOCK_STATE_SCHEMA_VERSION = RT_UNLOCK_STATE
UNLOCK_STATE_REQUIRED = (
    "unlock_id", "player_id", "unlock_type", "source_mission_id", "source_reward_event",
    "available_from_scenario", "affects_generation", "enabled",
)
UNLOCK_STATE_ALLOWED = UNLOCK_STATE_REQUIRED + (
    "meta", "schema_version", "report_type")


def validate_unlock_state(obj, strict=False):
    ch = RS.check_required(obj, UNLOCK_STATE_REQUIRED, C.UNLOCK_STATE_INVALID)
    ch += RS.check_no_unknown(obj, UNLOCK_STATE_ALLOWED, C.UNLOCK_STATE_INVALID, strict)
    ch += RS.check_enum(obj, "unlock_type", UNLOCK_TYPES, C.UNLOCK_STATE_INVALID)
    if not isinstance(obj, dict):
        return ch
    for f in ("unlock_id", "player_id", "source_mission_id", "source_reward_event",
              "available_from_scenario"):
        ch += _str(obj, f, C.UNLOCK_STATE_INVALID, "unl::")
    # affects_generation must be an explicit boolean — never implied.
    ch += _bool(obj, "affects_generation", C.UNLOCK_STATE_INVALID, "unl::")
    ch += _bool(obj, "enabled", C.UNLOCK_STATE_INVALID, "unl::")
    # source must resolve — an unlock with no source reward event is unsourced.
    ch.append(("unl::source_resolves",
               bool(obj.get("source_mission_id")) and bool(obj.get("source_reward_event")),
               "unlock must name a source_mission_id and source_reward_event",
               C.UNLOCK_SOURCE_UNRESOLVED))
    return ch


def _example_unlock_state(**over):
    d = {
        "unlock_id": "unl_scout_slot", "player_id": "player_M", "unlock_type": "loadout_slot",
        "source_mission_id": "m_M", "source_reward_event": "rge_M_s0_0003",
        "available_from_scenario": "rs_M_s1", "affects_generation": True, "enabled": True,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# RewardCompletionReport — per-scenario reward/progression outcome (runtime).
# --------------------------------------------------------------------------- #
REWARD_COMPLETION_SCHEMA_VERSION = RT_REWARD_COMPLETION
REWARD_COMPLETION_REQUIRED = (
    "report_id", "scenario_id", "map_id", "mission_id", "encounter_id", "biome",
    "combat_profile_id", "mission_completed", "combat_completed", "reward_table_id",
    "reward_events_seen", "items_granted", "xp_granted", "unlocks_granted",
    "inventory_mutated", "progression_mutated", "next_mission_state_written",
    "save_load_result", "risk_reward_class", "exploit_result", "status",
    "completion_class", "telemetry_path", "evidence_paths", "failure_owner",
    "failure_codes", "created_at", "git_commit",
)
REWARD_COMPLETION_ALLOWED = REWARD_COMPLETION_REQUIRED + (
    "meta", "schema_version", "report_type", "reward_events", "source_combat_report")


def validate_reward_completion_report(obj, strict=False):
    ch = RS.check_required(obj, REWARD_COMPLETION_REQUIRED, C.REWARD_COMPLETION_REPORT_INVALID,
                           nullable=("failure_owner",))
    ch += RS.check_no_unknown(obj, REWARD_COMPLETION_ALLOWED, C.REWARD_COMPLETION_REPORT_INVALID, strict)
    ch += RS.check_enum(obj, "status", RESULT_STATUS, C.REWARD_COMPLETION_REPORT_INVALID)
    ch += RS.check_enum(obj, "completion_class", REWARD_COMPLETION_CLASSES, C.REWARD_COMPLETION_REPORT_INVALID)
    ch += RS.check_enum(obj, "risk_reward_class", RISK_REWARD_CLASSES, C.RISK_REWARD_CLASSIFICATION_INVALID)
    ch += RS.check_enum(obj, "exploit_result", EXPLOIT_RESULTS, C.REWARD_EXPLOIT_DETECTED)
    ch += RS.check_enum(obj, "save_load_result", RESULT_STATUS, C.REWARD_COMPLETION_REPORT_INVALID)
    if not isinstance(obj, dict):
        return ch
    for f in ("mission_completed", "combat_completed", "inventory_mutated",
              "progression_mutated", "next_mission_state_written"):
        ch += _bool(obj, f, C.REWARD_COMPLETION_REPORT_INVALID, "rcr::")
    ch.append(("rcr::codes_list", isinstance(obj.get("failure_codes"), list),
               "failure_codes must be a list", C.REWARD_COMPLETION_REPORT_INVALID))
    ch.append(("rcr::evidence_list", isinstance(obj.get("evidence_paths"), list),
               "evidence_paths must be a list", C.REWARD_COMPLETION_REPORT_INVALID))
    cnt = obj.get("reward_events_seen")
    ch.append(("rcr::events_seen_int", isinstance(cnt, int) and cnt >= 0,
               "reward_events_seen must be an int >= 0", C.REWARD_COMPLETION_REPORT_INVALID))
    cls = obj.get("completion_class")
    status = obj.get("status")
    inv_mut = obj.get("inventory_mutated")
    prog_mut = obj.get("progression_mutated")
    rr_class = obj.get("risk_reward_class")
    # ---- anti-fake-green honesty invariants ----
    if cls == SUCCESS_REWARD_CLASS:
        ch.append(("rcr::success_is_pass", status == "pass",
                   "reward_granted_runtime must have status=pass", C.REWARD_REPORT_INTEGRITY_FAILED))
        # Completion must be real — you cannot be rewarded for a mission you did not
        # complete.
        ch.append(("rcr::success_mission_done", obj.get("mission_completed") is True,
                   "reward grant requires mission_completed=true", C.REWARD_WITHOUT_COMPLETION))
        # Real durable consequence: inventory or progression actually mutated.
        ch.append(("rcr::success_state_mutated", inv_mut is True or prog_mut is True,
                   "reward grant requires inventory or progression mutation",
                   C.COMPLETION_WITHOUT_REWARD))
        # At least one reward event was seen.
        ch.append(("rcr::success_has_events", isinstance(cnt, int) and cnt > 0,
                   "reward grant requires reward_events_seen > 0", C.REWARD_GRANT_INVALID))
        # Reward table resolved.
        ch.append(("rcr::success_table_ref", bool(obj.get("reward_table_id")),
                   "reward grant requires a resolved reward_table_id", C.REWARD_TABLE_INVALID))
        # Save/load persisted.
        ch.append(("rcr::success_save_load", obj.get("save_load_result") == "pass",
                   "reward grant requires save_load_result=pass", C.REWARD_SAVE_LOAD_FAILED))
        # Risk/reward class must be a rewarding, non-exploit class.
        ch.append(("rcr::success_rr_class", rr_class in ("baseline_reward", "high_risk_high_reward"),
                   "reward grant class must be baseline_reward or high_risk_high_reward",
                   C.RISK_REWARD_CLASSIFICATION_INVALID))
        ch.append(("rcr::success_exploit_clean", obj.get("exploit_result") == "clean",
                   "reward grant must be exploit-clean", C.REWARD_EXPLOIT_DETECTED))
        ch.append(("rcr::success_no_codes", len(obj.get("failure_codes") or []) == 0,
                   "success must carry no failure_codes", C.REWARD_REPORT_INTEGRITY_FAILED))
        ch.append(("rcr::success_has_telemetry",
                   isinstance(obj.get("telemetry_path"), str) and len(obj.get("telemetry_path")) > 0,
                   "success must reference a telemetry_path", C.REWARD_TELEMETRY_MISSING))
    elif cls == NO_REWARD_CLASS:
        # An honest no_reward completion: no mutation, class must be no_reward.
        ch.append(("rcr::no_reward_class", rr_class == "no_reward",
                   "no_reward_runtime must classify risk_reward_class=no_reward",
                   C.RISK_REWARD_CLASSIFICATION_INVALID))
        ch.append(("rcr::no_reward_no_mutation", not (inv_mut is True or prog_mut is True),
                   "no_reward_runtime must not mutate inventory or progression",
                   C.REWARD_REPORT_INTEGRITY_FAILED))
    else:
        ch.append(("rcr::failure_has_code", len(obj.get("failure_codes") or []) > 0,
                   "a failed completion_class must own a failure_code", C.REWARD_REPORT_INTEGRITY_FAILED))
        ch.append(("rcr::failure_not_pass", status != "pass",
                   "a failed completion_class must not have status=pass", C.REWARD_REPORT_INTEGRITY_FAILED))
        ch.append(("rcr::failure_has_owner", bool(obj.get("failure_owner")),
                   "a failed completion_class must name a failure_owner", C.REWARD_REPORT_INTEGRITY_FAILED))
    return ch


def _example_reward_completion(**over):
    d = {
        "report_id": "reward_cmp:rs_M_s0", "scenario_id": "rs_M_s0", "map_id": "M", "mission_id": "m_M",
        "encounter_id": "enc_M_guarded_objective", "biome": "volcanic_ashlands",
        "combat_profile_id": "cp_guard_pressure", "mission_completed": True, "combat_completed": True,
        "reward_table_id": "rwt_disable_site_ash_baseline", "reward_events_seen": 2, "items_granted": ["eq_rifle_std"],
        "xp_granted": 100.0, "unlocks_granted": ["unl_scout_slot"], "inventory_mutated": True,
        "progression_mutated": True, "next_mission_state_written": True, "save_load_result": "pass",
        "risk_reward_class": "baseline_reward", "exploit_result": "clean", "status": "pass",
        "completion_class": "reward_granted_runtime",
        "telemetry_path": "procedural/reports/rewards/telemetry/reward_telemetry_rs_M_s0.json",
        "evidence_paths": ["procedural/reports/rewards/telemetry/reward_telemetry_rs_M_s0.json"],
        "failure_owner": None, "failure_codes": [], "created_at": "live", "git_commit": "unknown",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# RewardTelemetry — the runtime event stream proving a reward grant occurred.
# --------------------------------------------------------------------------- #
RT_REWARD_TELEMETRY = "wf.reward.telemetry.v1"


def validate_reward_telemetry(obj, strict=False, require_completion=False):
    ch = []
    ok_top = isinstance(obj, dict) and isinstance(obj.get("events"), list)
    ch.append(("rtel::has_events", ok_top, "telemetry must carry an events list",
               C.REWARD_TELEMETRY_MISSING))
    if not ok_top:
        return ch
    evs = obj["events"]
    ch.append(("rtel::events_nonempty", len(evs) > 0, "telemetry events must be non-empty",
               C.REWARD_TELEMETRY_MISSING))
    seen = set()
    for i, e in enumerate(evs):
        et = e.get("event_type") if isinstance(e, dict) else None
        ok = et in REWARD_EVENT_TYPES
        ch.append(("rtel::event{}_type".format(i), ok,
                   "event {} type {!r} not in registry".format(i, et), C.REWARD_TELEMETRY_MISSING))
        if ok:
            seen.add(et)
    if require_completion:
        missing = [e for e in COMPLETION_REQUIRED_REWARD_EVENTS if e not in seen]
        ch.append(("rtel::completion_events_present", not missing,
                   "reward completion telemetry missing events: {}".format(missing),
                   C.REWARD_TELEMETRY_MISSING))
        ch.append(("rtel::has_grant_event", "reward.grant.applied" in seen,
                   "completion telemetry has no reward.grant.applied event (no real grant)",
                   C.REWARD_GRANT_INVALID))
    return ch


def _example_reward_telemetry(**over):
    d = {"report_type": RT_REWARD_TELEMETRY, "scenario_id": "rs_M_s0",
         "events": [{"event_type": t, "frame": i} for i, t in enumerate(COMPLETION_REQUIRED_REWARD_EVENTS)]}
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry of all contracts, for the schema validators + fuzz harness.
# Each entry: name -> (validate_fn, valid_example_fn, known_bad_example_fn).
# The known-bad MUST fail the validator — a contract that accepts it is fake green.
# CONTRACT_GROUPS splits the registry into the three gate lanes.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "LoadoutProfile": (
        validate_loadout_profile, _example_loadout_profile,
        # same item in primary and tool = duplicate exclusive equipment, rejected.
        lambda: _example_loadout_profile(tool_slot="eq_rifle_std")),
    "EquipmentItem": (
        validate_equipment_item, _example_equipment_item,
        # missing provenance = ownership-spine violation, rejected.
        lambda: _example_equipment_item(provenance=None)),
    "RewardTable": (
        validate_reward_table, _example_reward_table,
        # budget_min > budget_max = invalid range, rejected.
        lambda: _example_reward_table(budget_min=500.0, budget_max=100.0)),
    "RewardGrantEvent": (
        validate_reward_grant_event, _example_reward_grant_event,
        # rewarding grant that mutates NO state (pre==post on both) = fake reward.
        lambda: _example_reward_grant_event(pre_progression_hash="prog:0001",
                                            post_progression_hash="prog:0001")),
    "RewardCompletionReport": (
        validate_reward_completion_report, _example_reward_completion,
        # success class but no state mutation = completion-without-reward, rejected.
        lambda: _example_reward_completion(inventory_mutated=False, progression_mutated=False)),
    "InventoryState": (
        validate_inventory_state, _example_inventory_state,
        # capacity 0 with an item present = capacity exceeded, rejected.
        lambda: _example_inventory_state(capacity=0)),
    "ProgressionState": (
        validate_progression_state, _example_progression_state,
        # level inconsistent with XP curve (level 9 at 150 xp), rejected.
        lambda: _example_progression_state(level=9)),
    "UnlockState": (
        validate_unlock_state, _example_unlock_state,
        # affects_generation not an explicit bool, rejected.
        lambda: _example_unlock_state(affects_generation="yes")),
    "RewardTelemetry": (
        lambda o, strict=False: validate_reward_telemetry(o, strict=strict, require_completion=True),
        _example_reward_telemetry,
        # completion telemetry missing the grant.applied event.
        lambda: {"events": [{"event_type": "reward.scenario.started"},
                            {"event_type": "reward.scenario.completed"}]}),
}

CONTRACT_GROUPS = {
    "loadout": ("LoadoutProfile", "EquipmentItem"),
    "reward": ("RewardTable", "RewardGrantEvent", "RewardCompletionReport", "RewardTelemetry"),
    "progression": ("InventoryState", "ProgressionState", "UnlockState"),
}
