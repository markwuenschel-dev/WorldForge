#!/usr/bin/env python3
"""quest_faction_contracts.py — WorldForge v2.2 QuestForge + FactionStateForge spine.

v2.2 adds the first stateful narrative-consequence substrate for WorldForge on top
of the v2.0 vertical slice. It is NOT a story campaign, dialogue system, or lore
generator — it is the bounded substrate that proves a generated mission can belong
to a quest, a quest has steps and outcomes, a faction cares about the result,
faction state mutates, and those consequences persist so the next mission can see
the changed state.

For v2.2 (handoff §5):
    * A quest is a validated STATE MACHINE over existing WorldForge scenario actions.
    * A faction is a persistent bounded STATE VECTOR that receives bounded deltas
      from quest outcomes.
Everything else is presentation.

This module holds the strict contracts that define those quest/faction artifacts
and prove — at authoring time, before any generated dataset or runtime report
exists — that their *shape* is coherent and cannot launder a broken quest outcome,
an unbounded faction delta, an unchanged-hash "mutation", or a consequence ledger
over missing evidence into a green view.

Design mirrors operator_contracts.py / slice_contracts.py exactly:
    * frozen tuple enums (bounded taxonomy, one source of truth)
    * ``X_REQUIRED`` / ``X_ALLOWED`` field-name tuples
    * ``validate_X(obj, strict=False)`` returning a list of
      ``(check_name, ok, detail, failure_code)`` tuples — the shape
      ValidationReport.check consumes — built from shared runtime_schema (RS)
      helpers plus domain-specific cross-field honesty checks
    * ``_example_X(**over)`` canonical-valid factories (``d.update(over)`` spawns
      known-bad variants for the negatives/fuzz suites)
    * a ``CONTRACTS`` registry pairing each validator with a valid + known-bad
      example, ``CONTRACT_GROUPS`` partitioning it, and ``KNOWN_BAD_OWNING_CODE``
      naming the code each known-bad must be rejected FOR

The honesty invariants (anti-fake-green) live INSIDE the validators:
    * a QuestDefinition must have >= 1 non-optional step, a known archetype, and a
      requesting faction -> WF771/WF772/WF773
    * a QuestStep's completion_predicate must be machine-checkable and reference a
      known runtime-claim category; an optional step can't be required -> WF776/WF772
    * a QuestRuntimeState=completed requires all required steps completed; an
      outcome-bearing state requires faction_deltas_applied; reward_granted must
      match the reward_binding -> WF777/WF778
    * a FactionState value must sit within its bounds and can't hold the same quest
      in active AND completed -> WF782/WF784
    * a FactionDelta's magnitudes must sit within the per-facet caps and bounded
      must be true -> WF786/WF787
    * a ConsequenceLedger with applied_deltas MUST show post_hash != pre_hash and
      carry a save_load_result -> WF788/WF789
    * a QuestFactionRuntimeReport with an empty failure_codes list (claiming clean)
      MUST carry real evidence: runtime_started, a ledger path, roundtrip_ok
      save/load, next-mission state, and — for an outcome-bearing quest — a mutated
      faction state -> WF778/WF788/WF790/WF792/WF793
    * a QuestFactionEvidenceIndex may only report integrity_result=pass with a full
      matrix (seen==expected) and empty missing/stale evidence -> WF795/WF796
    * an OperatorQuestView/OperatorFactionView claiming a passing outcome must link
      real ledger/state evidence -> WF797

This module is schema-only: it validates the *structure and internal coherence* of
a single record. Cross-record resolution (does a scenario_id bind to a real v2.0
scenario? does a relationship target a real faction in the roster? does a ledger
path exist on disk?) is the job of the Wave-2 authoring validators and the Wave-3
runtime/index validators, which have the datasets and filesystem in hand. Stdlib
only; no jsonschema (house style is hand-rolled field checks via RS).
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_schema as RS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402

# --------------------------------------------------------------------------- #
# schema_version / report_type dotted namespaces (wf.quest_faction.<type>.v1)
# --------------------------------------------------------------------------- #
RT_QUEST_DEFINITION = "wf.quest_faction.quest_definition.v1"
RT_QUEST_STEP = "wf.quest_faction.quest_step.v1"
RT_QUEST_RUNTIME_STATE = "wf.quest_faction.quest_runtime_state.v1"
RT_FACTION_DEFINITION = "wf.quest_faction.faction_definition.v1"
RT_FACTION_STATE = "wf.quest_faction.faction_state.v1"
RT_FACTION_DELTA = "wf.quest_faction.faction_delta.v1"
RT_CONSEQUENCE_LEDGER = "wf.quest_faction.consequence_ledger.v1"
RT_RUNTIME_REPORT = "wf.quest_faction.runtime_report.v1"
RT_EVIDENCE_INDEX = "wf.quest_faction.evidence_index.v1"
RT_OPERATOR_QUEST_VIEW = "wf.quest_faction.operator_quest_view.v1"
RT_OPERATOR_FACTION_VIEW = "wf.quest_faction.operator_faction_view.v1"

# --------------------------------------------------------------------------- #
# Bounded taxonomy (one source of truth).
# --------------------------------------------------------------------------- #
# Quest archetypes (handoff §6). The three core archetypes map 1:1 onto the v2.0
# mission archetypes; StabilizeRoute is the optional stretch archetype (known to
# the schema, reuses the clear_hazard mission binding). No escort/stealth/dialogue/
# boss quests in v2.2.
QUEST_ARCHETYPES = ("Survey", "Recovery", "HazardClearance", "StabilizeRoute")
CORE_QUEST_ARCHETYPES = ("Survey", "Recovery", "HazardClearance")
# Quest archetype -> the v2.0 mission_archetype its scenario bindings must use.
QUEST_ARCHETYPE_MISSION = {
    "Survey": "survey_landmark",
    "Recovery": "recover_resource",
    "HazardClearance": "clear_hazard",
    "StabilizeRoute": "clear_hazard",
}

# QuestStep objective types (handoff §8.2).
OBJECTIVE_TYPES = (
    "survey_landmark", "recover_resource", "clear_hazard",
    "reach_objective", "survive_pressure", "extract_reward",
)

# Runtime evidence categories a required_runtime_claim / completion predicate may
# resolve to. These mirror the v2.0 slice evidence_categories plus the two facets a
# quest step reasons over (objective reached, pressure survived). Cross-resolution
# to the real report is the runtime validator's job; the schema bounds the vocab.
RUNTIME_CLAIM_CATEGORIES = (
    "runtime", "traversal", "npc", "combat", "reward", "save_load", "package",
    "objective", "pressure",
)

# Quest state machine (handoff §8.3).
QUEST_STATES = ("not_started", "active", "completed", "failed", "blocked", "invalid")
QUEST_OUTCOMES = ("success", "partial_success", "failure", "abandoned", "invalid")
# Outcomes that MUST carry a faction consequence (a real state mutation). abandoned
# and invalid are not outcome-bearing.
OUTCOME_BEARING = ("success", "partial_success", "failure")

# Faction classes (handoff §8.4).
FACTION_CLASSES = ("protector", "explorer", "extractor", "stabilizer", "opportunist")

# Risk profiles for a faction.
RISK_PROFILES = ("averse", "measured", "bold", "reckless")

# Faction state numeric bounds (inclusive). standing is signed; the rest are 0..100
# meters. resources are per-tag counters (0..1000). One source of truth — the
# faction manager and delta applier clamp to these.
STANDING_BOUNDS = (-100, 100)
INFLUENCE_BOUNDS = (0, 100)
TRUST_BOUNDS = (0, 100)
ALARM_BOUNDS = (0, 100)
TERRITORY_PRESSURE_BOUNDS = (0, 100)
RELATIONSHIP_BOUNDS = (-100, 100)
RESOURCE_BOUNDS = (0, 1000)

# Per-facet FactionDelta magnitude caps (a single quest outcome can never swing a
# faction by more than this — bounded consequence, not an economy sim).
STANDING_DELTA_CAP = 25
INFLUENCE_DELTA_CAP = 25
TRUST_DELTA_CAP = 25
ALARM_DELTA_CAP = 25
RELATIONSHIP_DELTA_CAP = 25
RESOURCES_DELTA_CAP = 100

# Bounded reason codes a FactionDelta may cite (handoff §8.6). Finite + normalized.
REASON_CODES = (
    "quest_success", "quest_partial", "quest_failure", "quest_abandoned",
    "territory_secured", "resource_recovered", "hazard_cleared",
    "route_stabilized", "rival_setback", "ally_boosted", "trust_gained",
    "alarm_raised",
)

# Save/load roundtrip vocabulary (shared with v1.9 reward save-load semantics).
SAVE_LOAD_RESULTS = ("roundtrip_ok", "roundtrip_failed", "not_run", "missing")

# Evidence-index integrity verdicts (mirror the operator vocabulary).
INTEGRITY_RESULTS = ("pass", "fail", "blocked")

# The bounded v2.0 slice scenario matrix v2.2 quests bind to (handoff §3/§11).
SLICE_BIOMES = ("alpine_snow", "volcanic_ashlands")
SLICE_PRESSURE_PROFILES = ("baseline", "high")
SLICE_SEEDS = (1, 2)
EXPECTED_SCENARIO_COUNT = 24
# Bound on quests / factions / hooks so v2.2 can never balloon into a campaign.
MAX_QUEST_STEPS = 6
MAX_NEXT_MISSION_HOOKS = 4
MAX_AFFECTED_FACTIONS = 4
MAX_FACTIONS = 4
MIN_FACTIONS = 3

# The shared deterministic authoring timestamp (NOT wall-clock) for example/
# authoring records. Real runtime artifacts stamp created_at="live" + a real sha.
AUTHORING_TS = "2026-07-11T00:00:00+00:00"

# Generated / report roots (repo-relative).
QUESTS_REL = "procedural/generated/quests"
FACTIONS_REL = "procedural/generated/factions"
CONSEQUENCES_REL = "procedural/generated/consequences"
QF_REPORTS_REL = "procedural/reports/quest_faction"

_WF_CODE_RE = re.compile(r"^WF\d{3}_[A-Z0-9_]+$")


# --------------------------------------------------------------------------- #
# small local helpers (mirror operator_contracts.py)
# --------------------------------------------------------------------------- #
def _str(obj, field, code, prefix):
    """A required id/path/version string: present, a str, and non-empty."""
    ch = RS.check_type(obj, field, str, code, prefix=prefix)
    v = obj.get(field) if isinstance(obj, dict) else None
    ch.append(("{}{}_nonempty".format(prefix, field),
               isinstance(v, str) and bool(v.strip()),
               "{} must be a non-empty string".format(field), code))
    return ch


def _bool(obj, field, code, prefix):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, bool)
    return [("{}{}_bool".format(prefix, field), ok,
             "{} must be an explicit boolean (got {!r})".format(field, v), code)]


def _int(obj, field, code, prefix, allow_zero=True):
    """A required integer field: a real number, integer-valued, and >=0 (or >0)."""
    ch = RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)
    v = obj.get(field) if isinstance(obj, dict) else None
    is_int = RS.is_number(v) and float(v).is_integer()
    ch.append(("{}{}_integer".format(prefix, field), is_int,
               "{} must be an integer (got {!r})".format(field, v), code))
    return ch


def _num(obj, field, code, prefix):
    """A required numeric field (may be signed)."""
    v = obj.get(field) if isinstance(obj, dict) else None
    return [("{}{}_number".format(prefix, field), RS.is_number(v),
             "{} must be a number (got {!r})".format(field, v), code)]


def _bounded(obj, field, bounds, code, prefix):
    """A numeric field that must sit within [lo, hi] inclusive."""
    lo, hi = bounds
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = RS.is_number(v) and lo <= v <= hi
    return [("{}{}_in_bounds".format(prefix, field), ok,
             "{} must be a number within [{}, {}] (got {!r})".format(field, lo, hi, v),
             code)]


def _capped(obj, field, cap, code, prefix):
    """A signed delta whose magnitude must be <= cap."""
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = RS.is_number(v) and abs(v) <= cap
    return [("{}{}_within_cap".format(prefix, field), ok,
             "{} magnitude must be <= {} (got {!r})".format(field, cap, v),
             code)]


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


def _schema_version(obj, expected, code, prefix):
    sv = obj.get("schema_version") if isinstance(obj, dict) else None
    return [("{}schema_version".format(prefix), sv == expected,
             "schema_version must be {!r} (got {!r})".format(expected, sv), code)]


# =========================================================================== #
# 1. QuestDefinition (WF771) — the validated quest state machine header
# =========================================================================== #
QUEST_DEF_REQUIRED = (
    "quest_id", "quest_archetype", "title_key", "requesting_faction_id",
    "affected_faction_ids", "scenario_bindings", "quest_steps",
    "success_conditions", "failure_conditions", "reward_binding",
    "faction_delta_rules", "next_mission_hooks", "schema_version",
)
QUEST_DEF_ALLOWED = QUEST_DEF_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "biome",
    "pressure_profile", "seed",
)


def validate_quest_definition(obj, strict=False):
    code = C.QUEST_CONTRACT_INVALID
    ch = RS.check_required(obj, QUEST_DEF_REQUIRED, code)
    ch += RS.check_no_unknown(obj, QUEST_DEF_ALLOWED, code, strict)
    for f in ("quest_id", "title_key", "requesting_faction_id", "reward_binding"):
        ch += _str(obj, f, code, "qd::")
    ch += RS.check_enum(obj, "quest_archetype", QUEST_ARCHETYPES,
                        C.QUEST_UNKNOWN_ARCHETYPE, prefix="qd::")
    ch += _list_of_str(obj, "affected_faction_ids", code, "qd::",
                       min_len=0, max_len=MAX_AFFECTED_FACTIONS)
    ch += _list_of_str(obj, "scenario_bindings", C.QUEST_SCENARIO_BINDING_MISSING,
                       "qd::", min_len=1)
    ch += _list_of_str(obj, "success_conditions", C.QUEST_COMPLETION_PREDICATE_INVALID,
                       "qd::", min_len=1)
    for f in ("failure_conditions", "next_mission_hooks", "faction_delta_rules"):
        ch.append(("qd::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # failure conditions must be explicit (non-empty) — a quest with no way to fail
    # is not a state machine.
    ch.append(("qd::failure_conditions_explicit",
               _is_list(obj, "failure_conditions") and len(obj["failure_conditions"]) > 0,
               "failure_conditions must be explicit and non-empty",
               C.QUEST_COMPLETION_PREDICATE_INVALID))
    # quest_steps: non-empty list of step ids (the full step records live in their
    # own QuestStep files; here we bind their ids in order).
    steps_ok = _is_list(obj, "quest_steps") and len(obj["quest_steps"]) > 0 \
        and len(obj["quest_steps"]) <= MAX_QUEST_STEPS \
        and all(isinstance(s, str) and s.strip() for s in obj["quest_steps"])
    ch.append(("qd::quest_steps_nonempty_bounded", steps_ok,
               "quest_steps must be 1..{} non-empty step ids".format(MAX_QUEST_STEPS),
               C.QUEST_STEP_INVALID))
    # next_mission_hooks bounded (handoff §8.1).
    hooks = obj.get("next_mission_hooks")
    ch.append(("qd::next_mission_hooks_bounded",
               _is_list(obj, "next_mission_hooks") and len(hooks) <= MAX_NEXT_MISSION_HOOKS,
               "next_mission_hooks must be a list of <= {} hooks".format(MAX_NEXT_MISSION_HOOKS),
               C.QUEST_NEXT_MISSION_HOOK_INVALID))
    ch += _schema_version(obj, RT_QUEST_DEFINITION, code, "qd::")
    return ch


def _example_quest_definition(**over):
    d = {
        "quest_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "quest_archetype": "Survey",
        "title_key": "quest.survey.alpine_glacial_basin",
        "requesting_faction_id": "surveyors",
        "affected_faction_ids": ["wardens", "salvagers"],
        "scenario_bindings": ["vs_alpine_snow_survey_landmark_baseline_s1"],
        "quest_steps": [
            "qf_alpine_snow_survey_landmark_baseline_s1_step1",
            "qf_alpine_snow_survey_landmark_baseline_s1_step2",
        ],
        "success_conditions": ["all_required_steps_completed"],
        "failure_conditions": ["objective_unreached", "pawn_incapacitated"],
        "reward_binding": "reward_survey_landmark_baseline",
        "faction_delta_rules": [
            {"target_faction_id": "surveyors", "on_outcome": "success"},
            {"target_faction_id": "salvagers", "on_outcome": "success"},
        ],
        "next_mission_hooks": ["unlock_followup_survey_deep"],
        "biome": "alpine_snow",
        "pressure_profile": "baseline",
        "seed": 1,
        "created_by": "worldforge.v2.2",
        "created_at": AUTHORING_TS,
        "schema_version": RT_QUEST_DEFINITION,
        "report_type": RT_QUEST_DEFINITION,
    }
    d.update(over)
    return d


# =========================================================================== #
# 2. QuestStep (WF772) — one ordered, machine-checkable objective
# =========================================================================== #
QUEST_STEP_REQUIRED = (
    "step_id", "quest_id", "step_order", "objective_type", "target_scenario_id",
    "target_map_id", "required_runtime_claims", "completion_predicate",
    "failure_predicate", "optional", "schema_version",
)
QUEST_STEP_ALLOWED = QUEST_STEP_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)


def _predicate_machine_checkable(pred):
    """A completion/failure predicate is machine-checkable when it names a known
    runtime-claim category and a comparison the runtime validator can evaluate.
    Shape: {"claim": <category>, "op": one of ==/>=/true, "value": <any>}."""
    if not isinstance(pred, dict):
        return False
    claim = pred.get("claim")
    op = pred.get("op")
    return (claim in RUNTIME_CLAIM_CATEGORIES
            and op in ("==", ">=", "<=", ">", "<", "true", "false")
            and "value" in pred)


def validate_quest_step(obj, strict=False):
    code = C.QUEST_STEP_INVALID
    ch = RS.check_required(obj, QUEST_STEP_REQUIRED, code)
    ch += RS.check_no_unknown(obj, QUEST_STEP_ALLOWED, code, strict)
    for f in ("step_id", "quest_id", "target_scenario_id", "target_map_id"):
        ch += _str(obj, f, code, "qs::")
    ch += _int(obj, "step_order", C.QUEST_STEP_ORDER_INVALID, "qs::", allow_zero=False)
    ch += RS.check_enum(obj, "objective_type", OBJECTIVE_TYPES, code, prefix="qs::")
    ch += _bool(obj, "optional", code, "qs::")
    # required_runtime_claims must all resolve to known evidence categories.
    rc = obj.get("required_runtime_claims")
    rc_ok = isinstance(rc, list) and len(rc) >= 1 \
        and all(x in RUNTIME_CLAIM_CATEGORIES for x in rc)
    ch.append(("qs::required_runtime_claims_known", rc_ok,
               "required_runtime_claims must be >=1 known categories {}".format(
                   RUNTIME_CLAIM_CATEGORIES),
               C.QUEST_COMPLETION_PREDICATE_INVALID))
    # completion / failure predicate must be machine-checkable.
    ch.append(("qs::completion_predicate_machine_checkable",
               _predicate_machine_checkable(obj.get("completion_predicate")),
               "completion_predicate must be a machine-checkable {claim,op,value}",
               C.QUEST_COMPLETION_PREDICATE_INVALID))
    ch.append(("qs::failure_predicate_machine_checkable",
               _predicate_machine_checkable(obj.get("failure_predicate")),
               "failure_predicate must be a machine-checkable {claim,op,value}",
               C.QUEST_COMPLETION_PREDICATE_INVALID))
    ch += _schema_version(obj, RT_QUEST_STEP, code, "qs::")
    return ch


def _example_quest_step(**over):
    d = {
        "step_id": "qf_alpine_snow_survey_landmark_baseline_s1_step1",
        "quest_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "step_order": 1,
        "objective_type": "reach_objective",
        "target_scenario_id": "vs_alpine_snow_survey_landmark_baseline_s1",
        "target_map_id": "Alpine_GlacialBasin_Debris_Photoreal_01",
        "required_runtime_claims": ["traversal", "objective"],
        "completion_predicate": {"claim": "objective", "op": "==", "value": "reached"},
        "failure_predicate": {"claim": "objective", "op": "==", "value": "unreached"},
        "optional": False,
        "created_by": "worldforge.v2.2",
        "created_at": AUTHORING_TS,
        "schema_version": RT_QUEST_STEP,
        "report_type": RT_QUEST_STEP,
    }
    d.update(over)
    return d


# =========================================================================== #
# 3. QuestRuntimeState (WF777) — the observed state of a quest after a run
# =========================================================================== #
QUEST_RT_REQUIRED = (
    "quest_id", "run_id", "scenario_id", "state", "completed_steps",
    "failed_steps", "active_step_id", "outcome", "runtime_claims",
    "reward_granted", "faction_deltas_applied", "save_slot", "schema_version",
)
QUEST_RT_ALLOWED = QUEST_RT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
    "required_steps", "reward_binding",
)


def validate_quest_runtime_state(obj, strict=False):
    code = C.QUEST_RUNTIME_STATE_INVALID
    ch = RS.check_required(obj, QUEST_RT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, QUEST_RT_ALLOWED, code, strict)
    for f in ("quest_id", "run_id", "scenario_id", "save_slot"):
        ch += _str(obj, f, code, "qr::")
    ch += RS.check_enum(obj, "state", QUEST_STATES, code, prefix="qr::")
    ch += RS.check_enum(obj, "outcome", QUEST_OUTCOMES, code, prefix="qr::")
    for f in ("completed_steps", "failed_steps", "runtime_claims"):
        ch.append(("qr::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += _bool(obj, "reward_granted", code, "qr::")
    ch += _bool(obj, "faction_deltas_applied", code, "qr::")

    # --- honesty: a completed quest requires ALL required steps completed --------
    if obj.get("state") == "completed":
        required = obj.get("required_steps")
        completed = set(obj.get("completed_steps") or [])
        req_ok = isinstance(required, list) and len(required) > 0 \
            and all(s in completed for s in required)
        ch.append(("qr::completed_requires_all_required_steps", req_ok,
                   "state=completed requires every required step in completed_steps",
                   C.QUEST_OUTCOME_EVIDENCE_MISSING))
    # --- honesty: an outcome-bearing quest requires faction_deltas_applied -------
    if obj.get("outcome") in OUTCOME_BEARING:
        ch.append(("qr::outcome_bearing_applies_deltas",
                   obj.get("faction_deltas_applied") is True,
                   "an outcome in {} requires faction_deltas_applied=true".format(
                       OUTCOME_BEARING),
                   C.FACTION_STATE_NOT_MUTATED))
    else:
        # abandoned/invalid outcomes must NOT claim applied deltas.
        ch.append(("qr::non_outcome_no_deltas",
                   obj.get("faction_deltas_applied") is False,
                   "a non-outcome-bearing quest must not claim faction_deltas_applied",
                   C.FACTION_STATE_NOT_MUTATED))
    # --- honesty: reward_granted must be consistent with a real reward_binding ---
    if obj.get("reward_granted") is True:
        rb = obj.get("reward_binding")
        ch.append(("qr::reward_granted_needs_binding",
                   isinstance(rb, str) and bool(rb.strip()) and rb != "none",
                   "reward_granted=true requires a non-none reward_binding",
                   C.QUEST_REWARD_BINDING_INVALID))
    ch += _schema_version(obj, RT_QUEST_RUNTIME_STATE, code, "qr::")
    return ch


def _example_quest_runtime_state(**over):
    d = {
        "quest_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "run_id": "qfrun_alpine_snow_survey_landmark_baseline_s1",
        "scenario_id": "vs_alpine_snow_survey_landmark_baseline_s1",
        "state": "completed",
        "required_steps": [
            "qf_alpine_snow_survey_landmark_baseline_s1_step1",
            "qf_alpine_snow_survey_landmark_baseline_s1_step2",
        ],
        "completed_steps": [
            "qf_alpine_snow_survey_landmark_baseline_s1_step1",
            "qf_alpine_snow_survey_landmark_baseline_s1_step2",
        ],
        "failed_steps": [],
        "active_step_id": "",
        "outcome": "success",
        "runtime_claims": ["traversal", "objective", "reward", "save_load"],
        "reward_granted": True,
        "reward_binding": "reward_survey_landmark_baseline",
        "faction_deltas_applied": True,
        "save_slot": "quest_faction_slot_a",
        "created_by": "worldforge.v2.2",
        "created_at": "live",
        "schema_version": RT_QUEST_RUNTIME_STATE,
        "report_type": RT_QUEST_RUNTIME_STATE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 4. FactionDefinition (WF781) — a bounded faction identity + preferences
# =========================================================================== #
FACTION_DEF_REQUIRED = (
    "faction_id", "display_key", "faction_class", "preferred_quest_archetypes",
    "opposed_quest_archetypes", "standing_bounds", "influence_bounds",
    "relationship_bounds", "risk_profile", "territory_tags", "resource_tags",
    "hazard_tags", "schema_version",
)
FACTION_DEF_ALLOWED = FACTION_DEF_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
    "hazard_sensitivity", "influence",
)


def _bounds_pair(obj, field, code, prefix):
    """A [lo, hi] numeric bounds pair with lo < hi."""
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) == 2 and all(RS.is_number(x) for x in v) \
        and v[0] < v[1]
    return [("{}{}_bounds_pair".format(prefix, field), ok,
             "{} must be a [lo, hi] pair with lo < hi (got {!r})".format(field, v),
             code)]


def validate_faction_definition(obj, strict=False):
    code = C.FACTION_CONTRACT_INVALID
    ch = RS.check_required(obj, FACTION_DEF_REQUIRED, code)
    ch += RS.check_no_unknown(obj, FACTION_DEF_ALLOWED, code, strict)
    for f in ("faction_id", "display_key"):
        ch += _str(obj, f, code, "fd::")
    ch += RS.check_enum(obj, "faction_class", FACTION_CLASSES, code, prefix="fd::")
    ch += RS.check_enum(obj, "risk_profile", RISK_PROFILES, code, prefix="fd::")
    for f in ("standing_bounds", "influence_bounds", "relationship_bounds"):
        ch += _bounds_pair(obj, f, C.FACTION_BOUNDS_INVALID, "fd::")
    # preferred / opposed archetypes must be known and finite.
    for f in ("preferred_quest_archetypes", "opposed_quest_archetypes"):
        v = obj.get(f)
        ok = isinstance(v, list) and all(x in QUEST_ARCHETYPES for x in v)
        ch.append(("fd::{}_known".format(f), ok,
                   "{} must be known quest archetypes {}".format(f, QUEST_ARCHETYPES),
                   code))
    # preferred and opposed must be disjoint (a faction can't both want and oppose).
    pref = set(obj.get("preferred_quest_archetypes") or []) \
        if isinstance(obj.get("preferred_quest_archetypes"), list) else set()
    opp = set(obj.get("opposed_quest_archetypes") or []) \
        if isinstance(obj.get("opposed_quest_archetypes"), list) else set()
    ch.append(("fd::pref_opp_disjoint", not (pref & opp),
               "preferred and opposed archetypes must be disjoint (overlap: {})".format(
                   sorted(pref & opp)),
               code))
    # tags finite + normalized (lowercase snake, list of str).
    for f in ("territory_tags", "resource_tags", "hazard_tags"):
        v = obj.get(f)
        ok = isinstance(v, list) and all(
            isinstance(x, str) and x == x.lower().strip() and " " not in x for x in v)
        ch.append(("fd::{}_normalized".format(f), ok,
                   "{} must be a list of normalized lowercase tags".format(f), code))
    ch += _schema_version(obj, RT_FACTION_DEFINITION, code, "fd::")
    return ch


def _example_faction_definition(**over):
    d = {
        "faction_id": "surveyors",
        "display_key": "faction.surveyors",
        "faction_class": "explorer",
        "preferred_quest_archetypes": ["Survey"],
        "opposed_quest_archetypes": ["HazardClearance"],
        "standing_bounds": list(STANDING_BOUNDS),
        "influence_bounds": list(INFLUENCE_BOUNDS),
        "relationship_bounds": list(RELATIONSHIP_BOUNDS),
        "risk_profile": "measured",
        "territory_tags": ["alpine_snow", "volcanic_ashlands"],
        "resource_tags": ["survey_data", "landmark_scan"],
        "hazard_tags": ["exposure", "rockfall"],
        "hazard_sensitivity": 0.4,
        "created_by": "worldforge.v2.2",
        "created_at": AUTHORING_TS,
        "schema_version": RT_FACTION_DEFINITION,
        "report_type": RT_FACTION_DEFINITION,
    }
    d.update(over)
    return d


# =========================================================================== #
# 5. FactionState (WF782) — a faction's persistent bounded state vector
# =========================================================================== #
FACTION_STATE_REQUIRED = (
    "faction_id", "run_id", "standing", "influence", "trust", "alarm",
    "resources", "territory_pressure", "relationships", "active_quest_ids",
    "completed_quest_ids", "failed_quest_ids", "schema_version",
)
FACTION_STATE_ALLOWED = FACTION_STATE_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "state_hash",
)


def validate_faction_state(obj, strict=False):
    code = C.FACTION_STATE_INVALID
    ch = RS.check_required(obj, FACTION_STATE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, FACTION_STATE_ALLOWED, code, strict)
    for f in ("faction_id", "run_id"):
        ch += _str(obj, f, code, "fs::")
    ch += _bounded(obj, "standing", STANDING_BOUNDS, C.FACTION_BOUNDS_INVALID, "fs::")
    ch += _bounded(obj, "influence", INFLUENCE_BOUNDS, C.FACTION_BOUNDS_INVALID, "fs::")
    ch += _bounded(obj, "trust", TRUST_BOUNDS, C.FACTION_BOUNDS_INVALID, "fs::")
    ch += _bounded(obj, "alarm", ALARM_BOUNDS, C.FACTION_BOUNDS_INVALID, "fs::")
    ch += _bounded(obj, "territory_pressure", TERRITORY_PRESSURE_BOUNDS,
                   C.FACTION_BOUNDS_INVALID, "fs::")
    # resources: dict of tag -> bounded counter.
    res = obj.get("resources")
    res_ok = isinstance(res, dict) and all(
        isinstance(k, str) and RS.is_number(v)
        and RESOURCE_BOUNDS[0] <= v <= RESOURCE_BOUNDS[1] for k, v in res.items())
    ch.append(("fs::resources_bounded_dict", res_ok,
               "resources must be a dict of tag -> counter within {}".format(RESOURCE_BOUNDS),
               C.FACTION_BOUNDS_INVALID))
    # relationships: dict of other_faction_id -> bounded standing.
    rel = obj.get("relationships")
    rel_ok = isinstance(rel, dict) and all(
        isinstance(k, str) and RS.is_number(v)
        and RELATIONSHIP_BOUNDS[0] <= v <= RELATIONSHIP_BOUNDS[1] for k, v in rel.items())
    ch.append(("fs::relationships_bounded_dict", rel_ok,
               "relationships must be a dict of faction_id -> value within {}".format(
                   RELATIONSHIP_BOUNDS),
               C.FACTION_RELATIONSHIP_INVALID))
    for f in ("active_quest_ids", "completed_quest_ids", "failed_quest_ids"):
        ch.append(("fs::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # --- honesty: a quest can't be simultaneously active AND completed -----------
    active = set(obj.get("active_quest_ids") or []) if _is_list(obj, "active_quest_ids") else set()
    completed = set(obj.get("completed_quest_ids") or []) if _is_list(obj, "completed_quest_ids") else set()
    ch.append(("fs::active_completed_disjoint", not (active & completed),
               "a quest cannot be in active_quest_ids AND completed_quest_ids (overlap: {})".format(
                   sorted(active & completed)),
               code))
    ch += _schema_version(obj, RT_FACTION_STATE, code, "fs::")
    return ch


def _example_faction_state(**over):
    d = {
        "faction_id": "surveyors",
        "run_id": "qfrun_alpine_snow_survey_landmark_baseline_s1",
        "standing": 10,
        "influence": 40,
        "trust": 50,
        "alarm": 5,
        "resources": {"survey_data": 20, "landmark_scan": 5},
        "territory_pressure": 15,
        "relationships": {"wardens": 10, "salvagers": -5, "outriders": 0},
        "active_quest_ids": [],
        "completed_quest_ids": ["qf_alpine_snow_survey_landmark_baseline_s1"],
        "failed_quest_ids": [],
        "state_hash": "sha256:pre",
        "created_by": "worldforge.v2.2",
        "created_at": "live",
        "schema_version": RT_FACTION_STATE,
        "report_type": RT_FACTION_STATE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 6. FactionDelta (WF786) — a bounded mutation from one quest outcome
# =========================================================================== #
FACTION_DELTA_REQUIRED = (
    "delta_id", "quest_id", "scenario_id", "source_outcome", "target_faction_id",
    "standing_delta", "influence_delta", "trust_delta", "alarm_delta",
    "resources_delta", "relationship_deltas", "reason_code", "bounded",
    "schema_version",
)
FACTION_DELTA_ALLOWED = FACTION_DELTA_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)


def validate_faction_delta(obj, strict=False):
    code = C.FACTION_DELTA_INVALID
    ch = RS.check_required(obj, FACTION_DELTA_REQUIRED, code)
    ch += RS.check_no_unknown(obj, FACTION_DELTA_ALLOWED, code, strict)
    for f in ("delta_id", "quest_id", "scenario_id", "target_faction_id"):
        ch += _str(obj, f, code, "fx::")
    ch += RS.check_enum(obj, "source_outcome", QUEST_OUTCOMES, code, prefix="fx::")
    ch += RS.check_enum(obj, "reason_code", REASON_CODES,
                        C.FACTION_DELTA_INVALID, prefix="fx::")
    ch += _bool(obj, "bounded", code, "fx::")
    # each scalar delta must sit within its per-facet cap.
    ch += _capped(obj, "standing_delta", STANDING_DELTA_CAP, C.FACTION_DELTA_UNBOUNDED, "fx::")
    ch += _capped(obj, "influence_delta", INFLUENCE_DELTA_CAP, C.FACTION_DELTA_UNBOUNDED, "fx::")
    ch += _capped(obj, "trust_delta", TRUST_DELTA_CAP, C.FACTION_DELTA_UNBOUNDED, "fx::")
    ch += _capped(obj, "alarm_delta", ALARM_DELTA_CAP, C.FACTION_DELTA_UNBOUNDED, "fx::")
    # resources_delta: dict of tag -> capped signed magnitude.
    rd = obj.get("resources_delta")
    rd_ok = isinstance(rd, dict) and all(
        isinstance(k, str) and RS.is_number(v) and abs(v) <= RESOURCES_DELTA_CAP
        for k, v in rd.items())
    ch.append(("fx::resources_delta_capped", rd_ok,
               "resources_delta must be a dict of tag -> signed magnitude <= {}".format(
                   RESOURCES_DELTA_CAP),
               C.FACTION_DELTA_UNBOUNDED))
    # relationship_deltas: dict of faction_id -> capped signed magnitude.
    reld = obj.get("relationship_deltas")
    reld_ok = isinstance(reld, dict) and all(
        isinstance(k, str) and RS.is_number(v) and abs(v) <= RELATIONSHIP_DELTA_CAP
        for k, v in reld.items())
    ch.append(("fx::relationship_deltas_capped", reld_ok,
               "relationship_deltas must be a dict of faction_id -> signed magnitude <= {}".format(
                   RELATIONSHIP_DELTA_CAP),
               C.FACTION_DELTA_UNBOUNDED))
    # --- honesty: a delta MUST assert bounded=true (handoff §8.6) -----------------
    ch.append(("fx::bounded_must_be_true", obj.get("bounded") is True,
               "a FactionDelta must assert bounded=true",
               C.FACTION_DELTA_UNBOUNDED))
    ch += _schema_version(obj, RT_FACTION_DELTA, code, "fx::")
    return ch


def _example_faction_delta(**over):
    d = {
        "delta_id": "fx_alpine_snow_survey_landmark_baseline_s1_surveyors",
        "quest_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "scenario_id": "vs_alpine_snow_survey_landmark_baseline_s1",
        "source_outcome": "success",
        "target_faction_id": "surveyors",
        "standing_delta": 10,
        "influence_delta": 5,
        "trust_delta": 8,
        "alarm_delta": -2,
        "resources_delta": {"survey_data": 15},
        "relationship_deltas": {"salvagers": -4},
        "reason_code": "quest_success",
        "bounded": True,
        "created_by": "worldforge.v2.2",
        "created_at": "live",
        "schema_version": RT_FACTION_DELTA,
        "report_type": RT_FACTION_DELTA,
    }
    d.update(over)
    return d


# =========================================================================== #
# 7. ConsequenceLedger (WF789) — the pre/post continuity proof for one run
# =========================================================================== #
LEDGER_REQUIRED = (
    "ledger_id", "run_id", "scenario_id", "quest_id", "pre_faction_state_hash",
    "post_faction_state_hash", "pre_quest_state_hash", "post_quest_state_hash",
    "applied_deltas", "reward_events", "progression_events", "next_mission_hooks",
    "save_load_result", "schema_version",
)
LEDGER_ALLOWED = LEDGER_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "outcome",
)


def validate_consequence_ledger(obj, strict=False):
    code = C.CONSEQUENCE_LEDGER_INVALID
    ch = RS.check_required(obj, LEDGER_REQUIRED, code)
    ch += RS.check_no_unknown(obj, LEDGER_ALLOWED, code, strict)
    for f in ("ledger_id", "run_id", "scenario_id", "quest_id",
              "pre_faction_state_hash", "post_faction_state_hash",
              "pre_quest_state_hash", "post_quest_state_hash"):
        ch += _str(obj, f, code, "cl::")
    for f in ("applied_deltas", "reward_events", "progression_events",
              "next_mission_hooks"):
        ch.append(("cl::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += RS.check_enum(obj, "save_load_result", SAVE_LOAD_RESULTS,
                        C.QUEST_FACTION_SAVE_LOAD_FAILED, prefix="cl::")
    # next_mission_hooks bounded + serializable (list of str/dict).
    hooks = obj.get("next_mission_hooks")
    hooks_ok = _is_list(obj, "next_mission_hooks") and len(hooks) <= MAX_NEXT_MISSION_HOOKS \
        and all(isinstance(h, (str, dict)) for h in hooks)
    ch.append(("cl::next_mission_hooks_bounded", hooks_ok,
               "next_mission_hooks must be <= {} serializable hooks".format(MAX_NEXT_MISSION_HOOKS),
               C.QUEST_FACTION_NEXT_STATE_MISSING))
    # --- honesty: post hashes MUST differ when deltas apply (real mutation) -------
    applied = obj.get("applied_deltas")
    if _is_list(obj, "applied_deltas") and len(applied) > 0:
        pre, post = obj.get("pre_faction_state_hash"), obj.get("post_faction_state_hash")
        ch.append(("cl::mutation_changes_faction_hash",
                   isinstance(pre, str) and isinstance(post, str) and pre != post,
                   "applied_deltas non-empty requires post_faction_state_hash != pre "
                   "(got pre={!r} post={!r})".format(pre, post),
                   C.FACTION_STATE_NOT_MUTATED))
    ch += _schema_version(obj, RT_CONSEQUENCE_LEDGER, code, "cl::")
    return ch


def _example_consequence_ledger(**over):
    d = {
        "ledger_id": "ledger_alpine_snow_survey_landmark_baseline_s1",
        "run_id": "qfrun_alpine_snow_survey_landmark_baseline_s1",
        "scenario_id": "vs_alpine_snow_survey_landmark_baseline_s1",
        "quest_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "pre_faction_state_hash": "sha256:pre_aaaa",
        "post_faction_state_hash": "sha256:post_bbbb",
        "pre_quest_state_hash": "sha256:qpre_cccc",
        "post_quest_state_hash": "sha256:qpost_dddd",
        "applied_deltas": ["fx_alpine_snow_survey_landmark_baseline_s1_surveyors"],
        "reward_events": ["reward_survey_landmark_baseline"],
        "progression_events": ["xp_survey_landmark"],
        "next_mission_hooks": ["unlock_followup_survey_deep"],
        "save_load_result": "roundtrip_ok",
        "outcome": "success",
        "created_by": "worldforge.v2.2",
        "created_at": "live",
        "schema_version": RT_CONSEQUENCE_LEDGER,
        "report_type": RT_CONSEQUENCE_LEDGER,
    }
    d.update(over)
    return d


# =========================================================================== #
# 8. QuestFactionRuntimeReport (WF794) — the per-scenario runtime proof
# =========================================================================== #
RUNTIME_REPORT_REQUIRED = (
    "report_id", "run_id", "scenario_id", "quest_id", "quest_archetype",
    "requesting_faction_id", "affected_faction_ids", "runtime_started",
    "steps_completed", "quest_outcome", "faction_state_mutated",
    "consequence_ledger_path", "save_load_result", "next_mission_state_available",
    "operator_trace_paths", "failure_codes", "schema_version",
)
RUNTIME_REPORT_ALLOWED = RUNTIME_REPORT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "biome",
    "pressure_profile", "seed",
)


def validate_runtime_report(obj, strict=False):
    code = C.QUEST_FACTION_RUNTIME_REPORT_INVALID
    ch = RS.check_required(obj, RUNTIME_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, RUNTIME_REPORT_ALLOWED, code, strict)
    for f in ("report_id", "run_id", "scenario_id", "quest_id",
              "requesting_faction_id", "consequence_ledger_path"):
        ch += _str(obj, f, code, "rr::")
    ch += RS.check_enum(obj, "quest_archetype", QUEST_ARCHETYPES,
                        C.QUEST_UNKNOWN_ARCHETYPE, prefix="rr::")
    ch += RS.check_enum(obj, "quest_outcome", QUEST_OUTCOMES, code, prefix="rr::")
    ch += RS.check_enum(obj, "save_load_result", SAVE_LOAD_RESULTS,
                        C.QUEST_FACTION_SAVE_LOAD_FAILED, prefix="rr::")
    ch += _bool(obj, "runtime_started", code, "rr::")
    ch += _bool(obj, "faction_state_mutated", code, "rr::")
    ch += _bool(obj, "next_mission_state_available", code, "rr::")
    ch += _int(obj, "steps_completed", code, "rr::", allow_zero=True)
    for f in ("affected_faction_ids", "operator_trace_paths", "failure_codes"):
        ch.append(("rr::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # failure_codes, if present, must be well-formed WF codes.
    fcs = obj.get("failure_codes")
    if _is_list(obj, "failure_codes"):
        ch.append(("rr::failure_codes_well_formed",
                   all(isinstance(c, str) and _WF_CODE_RE.match(c) for c in fcs),
                   "failure_codes must be WFnnn_* strings",
                   C.QUEST_FACTION_UNKNOWN_FAILURE_CODE))

    # --- honesty: a CLEAN report (empty failure_codes) MUST carry real evidence ---
    clean = _is_list(obj, "failure_codes") and len(fcs or []) == 0
    if clean:
        ch.append(("rr::clean_requires_runtime_started",
                   obj.get("runtime_started") is True,
                   "a clean report requires runtime_started=true",
                   C.QUEST_OUTCOME_EVIDENCE_MISSING))
        ch.append(("rr::clean_requires_bearing_outcome",
                   obj.get("quest_outcome") in OUTCOME_BEARING,
                   "a clean report requires quest_outcome in {} (failure is a valid "
                   "outcome; abandoned/invalid are not clean)".format(OUTCOME_BEARING),
                   C.QUEST_OUTCOME_EVIDENCE_MISSING))
        lp = obj.get("consequence_ledger_path")
        ch.append(("rr::clean_requires_ledger_path",
                   isinstance(lp, str) and bool(lp.strip()),
                   "a clean report requires a consequence_ledger_path",
                   C.CONSEQUENCE_LEDGER_MISSING))
        ch.append(("rr::clean_requires_roundtrip_ok",
                   obj.get("save_load_result") == "roundtrip_ok",
                   "a clean report requires save_load_result=roundtrip_ok",
                   C.QUEST_FACTION_SAVE_LOAD_FAILED))
        ch.append(("rr::clean_requires_next_state",
                   obj.get("next_mission_state_available") is True,
                   "a clean report requires next_mission_state_available=true",
                   C.QUEST_FACTION_NEXT_STATE_MISSING))
        # an outcome-bearing quest that is clean MUST have mutated faction state.
        if obj.get("quest_outcome") in OUTCOME_BEARING:
            ch.append(("rr::clean_outcome_mutates_faction",
                       obj.get("faction_state_mutated") is True,
                       "a clean outcome-bearing report requires faction_state_mutated=true",
                       C.FACTION_STATE_NOT_MUTATED))
    ch += _schema_version(obj, RT_RUNTIME_REPORT, code, "rr::")
    return ch


def _example_runtime_report(**over):
    d = {
        "report_id": "qfrpt_alpine_snow_survey_landmark_baseline_s1",
        "run_id": "qfrun_alpine_snow_survey_landmark_baseline_s1",
        "scenario_id": "vs_alpine_snow_survey_landmark_baseline_s1",
        "quest_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "quest_archetype": "Survey",
        "requesting_faction_id": "surveyors",
        "affected_faction_ids": ["wardens", "salvagers"],
        "runtime_started": True,
        "steps_completed": 2,
        "quest_outcome": "success",
        "faction_state_mutated": True,
        "consequence_ledger_path": (CONSEQUENCES_REL
                                    + "/ledger_alpine_snow_survey_landmark_baseline_s1.json"),
        "save_load_result": "roundtrip_ok",
        "next_mission_state_available": True,
        "operator_trace_paths": [
            "procedural/reports/operator/quests/qf_alpine_snow_survey_landmark_baseline_s1.html"],
        "failure_codes": [],
        "biome": "alpine_snow",
        "pressure_profile": "baseline",
        "seed": 1,
        "created_by": "worldforge.v2.2",
        "created_at": "live",
        "schema_version": RT_RUNTIME_REPORT,
        "report_type": RT_RUNTIME_REPORT,
    }
    d.update(over)
    return d


# =========================================================================== #
# 9. QuestFactionEvidenceIndex (WF795) — the coverage/integrity roll-up
# =========================================================================== #
EVIDENCE_INDEX_REQUIRED = (
    "index_id", "created_at", "git_sha", "quest_count", "faction_count",
    "scenario_count_expected", "scenario_count_seen", "runtime_report_paths",
    "quest_definition_paths", "faction_definition_paths", "faction_state_paths",
    "consequence_ledger_paths", "operator_index_paths", "missing_evidence",
    "stale_evidence", "integrity_result", "schema_version",
)
EVIDENCE_INDEX_ALLOWED = EVIDENCE_INDEX_REQUIRED + (
    "meta", "report_type", "created_by", "notes",
)
_INDEX_PATH_LISTS = (
    "runtime_report_paths", "quest_definition_paths", "faction_definition_paths",
    "faction_state_paths", "consequence_ledger_paths", "operator_index_paths",
)


def validate_evidence_index(obj, strict=False):
    code = C.QUEST_FACTION_PARTIAL_MATRIX
    ch = RS.check_required(obj, EVIDENCE_INDEX_REQUIRED, code)
    ch += RS.check_no_unknown(obj, EVIDENCE_INDEX_ALLOWED, code, strict)
    for f in ("index_id", "created_at", "git_sha"):
        ch += _str(obj, f, code, "qfi::")
    for f in ("quest_count", "faction_count", "scenario_count_expected",
              "scenario_count_seen"):
        ch += _int(obj, f, code, "qfi::", allow_zero=True)
    for f in _INDEX_PATH_LISTS + ("missing_evidence", "stale_evidence"):
        ch.append(("qfi::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += RS.check_enum(obj, "integrity_result", INTEGRITY_RESULTS, code, prefix="qfi::")

    # --- honesty: live index requires a real sha --------------------------------
    if obj.get("created_at") == "live":
        sha = obj.get("git_sha")
        ch.append(("qfi::live_requires_real_sha",
                   isinstance(sha, str) and sha and sha != "unknown",
                   "created_at='live' requires a real git_sha (got {!r})".format(sha),
                   C.QUEST_FACTION_STALE_EVIDENCE))
    # --- honesty: integrity_result=pass requires the FULL matrix + no gaps -------
    if obj.get("integrity_result") == "pass":
        seen = obj.get("scenario_count_seen")
        exp = obj.get("scenario_count_expected")
        ch.append(("qfi::pass_requires_full_matrix",
                   RS.is_number(seen) and RS.is_number(exp) and seen == exp and exp > 0,
                   "integrity_result=pass requires scenario_count_seen == "
                   "scenario_count_expected > 0 (got {} / {})".format(seen, exp),
                   C.QUEST_FACTION_PARTIAL_MATRIX))
        ch.append(("qfi::pass_requires_no_missing",
                   _is_list(obj, "missing_evidence") and len(obj["missing_evidence"]) == 0,
                   "integrity_result=pass requires empty missing_evidence",
                   C.CONSEQUENCE_LEDGER_MISSING))
        ch.append(("qfi::pass_requires_no_stale",
                   _is_list(obj, "stale_evidence") and len(obj["stale_evidence"]) == 0,
                   "integrity_result=pass requires empty stale_evidence",
                   C.QUEST_FACTION_STALE_EVIDENCE))
    ch += _schema_version(obj, RT_EVIDENCE_INDEX, code, "qfi::")
    return ch


def _example_evidence_index(**over):
    d = {
        "index_id": "quest_faction_evidence_index",
        "created_at": "live",
        "git_sha": "0000000000000000000000000000000000000000",
        "quest_count": 24,
        "faction_count": 4,
        "scenario_count_expected": 24,
        "scenario_count_seen": 24,
        "runtime_report_paths": [QF_REPORTS_REL + "/runtime/qfrpt_x.json"],
        "quest_definition_paths": [QUESTS_REL + "/qf_x.json"],
        "faction_definition_paths": [FACTIONS_REL + "/surveyors.json"],
        "faction_state_paths": [QF_REPORTS_REL + "/runtime/state_x.json"],
        "consequence_ledger_paths": [CONSEQUENCES_REL + "/ledger_x.json"],
        "operator_index_paths": ["procedural/reports/operator/index/quest_views.json"],
        "missing_evidence": [],
        "stale_evidence": [],
        "integrity_result": "pass",
        "created_by": "worldforge.v2.2",
        "schema_version": RT_EVIDENCE_INDEX,
        "report_type": RT_EVIDENCE_INDEX,
    }
    d.update(over)
    return d


# =========================================================================== #
# 10. OperatorQuestView (WF797) — one quest, inspectable in OperatorForge
# =========================================================================== #
OP_QUEST_VIEW_REQUIRED = (
    "quest_id", "quest_archetype", "requesting_faction_id", "affected_faction_ids",
    "scenario_ids", "step_statuses", "runtime_outcomes", "faction_deltas",
    "consequence_ledger_paths", "save_load_status", "next_mission_hooks",
    "failure_codes", "schema_version",
)
OP_QUEST_VIEW_ALLOWED = OP_QUEST_VIEW_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)


def validate_operator_quest_view(obj, strict=False):
    code = C.QUEST_FACTION_OPERATOR_VIEW_INVALID
    ch = RS.check_required(obj, OP_QUEST_VIEW_REQUIRED, code)
    ch += RS.check_no_unknown(obj, OP_QUEST_VIEW_ALLOWED, code, strict)
    ch += _str(obj, "quest_id", code, "oqv::")
    ch += _str(obj, "requesting_faction_id", code, "oqv::")
    ch += RS.check_enum(obj, "quest_archetype", QUEST_ARCHETYPES,
                        C.QUEST_UNKNOWN_ARCHETYPE, prefix="oqv::")
    ch += RS.check_enum(obj, "save_load_status", SAVE_LOAD_RESULTS,
                        C.QUEST_FACTION_SAVE_LOAD_FAILED, prefix="oqv::")
    ch += _list_of_str(obj, "scenario_ids", code, "oqv::", min_len=1)
    ch += _list_of_str(obj, "consequence_ledger_paths", code, "oqv::")
    for f in ("affected_faction_ids", "step_statuses", "runtime_outcomes",
              "faction_deltas", "next_mission_hooks", "failure_codes"):
        ch.append(("oqv::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # --- honesty: a passing view (no failure codes, roundtrip_ok) must link real
    # ledger evidence — the view indexes evidence, it does not invent it. ---------
    clean = _is_list(obj, "failure_codes") and len(obj.get("failure_codes") or []) == 0
    if clean and obj.get("save_load_status") == "roundtrip_ok":
        lp = obj.get("consequence_ledger_paths")
        ch.append(("oqv::clean_view_links_ledger",
                   _is_list(obj, "consequence_ledger_paths") and len(lp) > 0,
                   "a clean quest view with roundtrip_ok must link >=1 consequence ledger",
                   C.CONSEQUENCE_LEDGER_MISSING))
    ch += _schema_version(obj, RT_OPERATOR_QUEST_VIEW, code, "oqv::")
    return ch


def _example_operator_quest_view(**over):
    d = {
        "quest_id": "qf_alpine_snow_survey_landmark_baseline_s1",
        "quest_archetype": "Survey",
        "requesting_faction_id": "surveyors",
        "affected_faction_ids": ["wardens", "salvagers"],
        "scenario_ids": ["vs_alpine_snow_survey_landmark_baseline_s1"],
        "step_statuses": [{"step_id": "..._step1", "status": "completed"}],
        "runtime_outcomes": ["success"],
        "faction_deltas": ["fx_alpine_snow_survey_landmark_baseline_s1_surveyors"],
        "consequence_ledger_paths": [
            CONSEQUENCES_REL + "/ledger_alpine_snow_survey_landmark_baseline_s1.json"],
        "save_load_status": "roundtrip_ok",
        "next_mission_hooks": ["unlock_followup_survey_deep"],
        "failure_codes": [],
        "created_by": "worldforge.v2.2",
        "created_at": "live",
        "schema_version": RT_OPERATOR_QUEST_VIEW,
        "report_type": RT_OPERATOR_QUEST_VIEW,
    }
    d.update(over)
    return d


# =========================================================================== #
# 11. OperatorFactionView (WF797) — one faction, inspectable in OperatorForge
# =========================================================================== #
OP_FACTION_VIEW_REQUIRED = (
    "faction_id", "definition_path", "state_paths", "standing_history",
    "influence_history", "trust_history", "alarm_history", "quest_history",
    "relationship_history", "active_failure_codes", "schema_version",
)
OP_FACTION_VIEW_ALLOWED = OP_FACTION_VIEW_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)
_FACTION_HISTORY_LISTS = (
    "standing_history", "influence_history", "trust_history", "alarm_history",
    "quest_history", "relationship_history",
)


def validate_operator_faction_view(obj, strict=False):
    code = C.QUEST_FACTION_OPERATOR_VIEW_INVALID
    ch = RS.check_required(obj, OP_FACTION_VIEW_REQUIRED, code)
    ch += RS.check_no_unknown(obj, OP_FACTION_VIEW_ALLOWED, code, strict)
    ch += _str(obj, "faction_id", code, "ofv::")
    ch += _str(obj, "definition_path", code, "ofv::")
    ch += _list_of_str(obj, "state_paths", code, "ofv::", min_len=1)
    for f in _FACTION_HISTORY_LISTS + ("active_failure_codes",):
        ch.append(("ofv::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # --- honesty: a faction with a mutation history must carry >=1 state path -----
    hist = obj.get("standing_history")
    if _is_list(obj, "standing_history") and len(hist) > 1:
        sp = obj.get("state_paths")
        ch.append(("ofv::history_requires_state_paths",
                   _is_list(obj, "state_paths") and len(sp) >= 1,
                   "a faction with standing history must link >=1 state path",
                   C.FACTION_STATE_INVALID))
    ch += _schema_version(obj, RT_OPERATOR_FACTION_VIEW, code, "ofv::")
    return ch


def _example_operator_faction_view(**over):
    d = {
        "faction_id": "surveyors",
        "definition_path": FACTIONS_REL + "/surveyors.json",
        "state_paths": [QF_REPORTS_REL + "/runtime/state_surveyors_run1.json"],
        "standing_history": [0, 10],
        "influence_history": [35, 40],
        "trust_history": [42, 50],
        "alarm_history": [7, 5],
        "quest_history": ["qf_alpine_snow_survey_landmark_baseline_s1"],
        "relationship_history": [{"salvagers": 0}, {"salvagers": -5}],
        "active_failure_codes": [],
        "created_by": "worldforge.v2.2",
        "created_at": "live",
        "schema_version": RT_OPERATOR_FACTION_VIEW,
        "report_type": RT_OPERATOR_FACTION_VIEW,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry — one source of truth for the dogfood / negatives / fuzz suites.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "QuestDefinition": (
        validate_quest_definition, _example_quest_definition,
        # unknown archetype -> WF773.
        lambda: _example_quest_definition(quest_archetype="EscortConvoy")),
    "QuestStep": (
        validate_quest_step, _example_quest_step,
        # completion predicate references an unknown claim category -> WF776.
        lambda: _example_quest_step(
            completion_predicate={"claim": "vibes", "op": "==", "value": "good"})),
    "QuestRuntimeState": (
        validate_quest_runtime_state, _example_quest_runtime_state,
        # outcome=success but faction_deltas_applied=false -> WF788.
        lambda: _example_quest_runtime_state(faction_deltas_applied=False)),
    "FactionDefinition": (
        validate_faction_definition, _example_faction_definition,
        # unknown faction class -> WF781.
        lambda: _example_faction_definition(faction_class="megacorp")),
    "FactionState": (
        validate_faction_state, _example_faction_state,
        # standing out of bounds -> WF784.
        lambda: _example_faction_state(standing=9999)),
    "FactionDelta": (
        validate_faction_delta, _example_faction_delta,
        # standing_delta exceeds the per-facet cap -> WF787.
        lambda: _example_faction_delta(standing_delta=999)),
    "ConsequenceLedger": (
        validate_consequence_ledger, _example_consequence_ledger,
        # applied_deltas non-empty but post hash == pre hash -> WF788.
        lambda: _example_consequence_ledger(
            post_faction_state_hash="sha256:pre_aaaa")),
    "QuestFactionRuntimeReport": (
        validate_runtime_report, _example_runtime_report,
        # clean report (no failure codes) but save/load did not round-trip -> WF792.
        lambda: _example_runtime_report(save_load_result="roundtrip_failed")),
    "QuestFactionEvidenceIndex": (
        validate_evidence_index, _example_evidence_index,
        # integrity_result=pass but only 23/24 scenarios seen -> WF795.
        lambda: _example_evidence_index(scenario_count_seen=23)),
    "OperatorQuestView": (
        validate_operator_quest_view, _example_operator_quest_view,
        # clean roundtrip_ok view but no ledger linked -> WF790.
        lambda: _example_operator_quest_view(consequence_ledger_paths=[])),
    "OperatorFactionView": (
        validate_operator_faction_view, _example_operator_faction_view,
        # mutation history but no state path linked -> WF782.
        lambda: _example_operator_faction_view(state_paths=[])),
}

CONTRACT_GROUPS = {
    "quest": ("QuestDefinition", "QuestStep", "QuestRuntimeState"),
    "faction": ("FactionDefinition", "FactionState", "FactionDelta"),
    "consequence": ("ConsequenceLedger", "QuestFactionRuntimeReport",
                    "QuestFactionEvidenceIndex"),
    "operator": ("OperatorQuestView", "OperatorFactionView"),
}

# The owning failure code each known-bad must be rejected FOR (rejection for the
# wrong reason is not real coverage).
KNOWN_BAD_OWNING_CODE = {
    "QuestDefinition": C.QUEST_UNKNOWN_ARCHETYPE,
    "QuestStep": C.QUEST_COMPLETION_PREDICATE_INVALID,
    "QuestRuntimeState": C.FACTION_STATE_NOT_MUTATED,
    "FactionDefinition": C.FACTION_CONTRACT_INVALID,
    "FactionState": C.FACTION_BOUNDS_INVALID,
    "FactionDelta": C.FACTION_DELTA_UNBOUNDED,
    "ConsequenceLedger": C.FACTION_STATE_NOT_MUTATED,
    "QuestFactionRuntimeReport": C.QUEST_FACTION_SAVE_LOAD_FAILED,
    "QuestFactionEvidenceIndex": C.QUEST_FACTION_PARTIAL_MATRIX,
    "OperatorQuestView": C.CONSEQUENCE_LEDGER_MISSING,
    "OperatorFactionView": C.FACTION_STATE_INVALID,
}

# The set of quest/faction failure codes this milestone owns (WF771–804). Used by
# the negatives/report-integrity suites to prove no view emits an out-of-band code.
QUEST_FACTION_CODES = tuple(
    v for k, v in vars(C).items()
    if not k.startswith("_") and isinstance(v, str)
    and 771 <= (int(v[2:5]) if v[2:5].isdigit() else -1) <= 850
)
