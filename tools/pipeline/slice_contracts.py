#!/usr/bin/env python3
"""slice_contracts.py — WorldForge v2.0 VerticalSliceForge strict-schema spine.

v2.0 integrates the v1.5-v1.9 substrates (asset/visual materialization, grounded
traversal, NPC behavior, combat pressure, reward/progression consequence,
save/load persistence) into ONE generated playable slice. This module holds the
strict contracts that define the slice and prove — at authoring time, before any
runtime or package evidence exists — that the *shape* of the slice is coherent.

Design mirrors reward_contracts.py exactly (the v1.9 spine):
    * frozen tuple enums (bounded taxonomy, one source of truth)
    * ``X_REQUIRED`` / ``X_ALLOWED`` field-name tuples
    * ``validate_X(obj, strict=False)`` returning a list of
      ``(check_name, ok, detail, failure_code)`` tuples — the exact shape
      ValidationReport.check consumes — built from the shared runtime_schema (RS)
      helpers plus domain-specific cross-field checks
    * ``_example_X(**over)`` canonical-valid factories (``d.update(over)`` spawns
      known-bad variants for the negatives/fuzz suites)
    * a ``CONTRACTS`` registry pairing each validator with a valid + known-bad
      example, split into gate lanes by ``CONTRACT_GROUPS``

The honesty invariants (anti-fake-green) live INSIDE the validators as cross-field
checks so a report cannot claim slice completion its own fields do not back:
    * a slice contract's scenario_count MUST equal the matrix product
      (biomes x archetypes x encounter_profiles x seeds) -> WF672
    * a runtime report claiming ``slice_completed_runtime`` MUST have every major
      system true (launched, player_spawned, traversal, npc, combat damage,
      mission completed, reward granted, inventory OR progression mutated,
      save/load roundtrip_ok) AND an empty failure_codes list -> WF686/702/703/704
    * reward participation that mutates NO state is fake reward -> WF704
    * save/load MUST use the v1.9 reward slots, never the mission/combat slots
      -> WF705
    * a package report cannot pass with no package on disk -> WF675/676
    * an evidence index must cover every expected scenario (count_seen ==
      count_expected) with no missing/stale entries -> WF686/687/685

This module is schema-only: it validates the *structure and internal coherence*
of a record. Cross-record resolution (does ``map_id`` name a real generated map?
does ``expected_reward_table_id`` resolve to a v1.9 reward table?) is the job of
the Wave 2 authoring validators, which have the manifests in hand. Stdlib only;
no jsonschema (the house style is hand-rolled field checks via RS).
"""

import runtime_schema as RS
from failure_codes import FailureCode as C

# --------------------------------------------------------------------------- #
# schema_version / report_type dotted namespaces (wf.<domain>.<type>.v<n>)
# --------------------------------------------------------------------------- #
RT_VERTICAL_SLICE_CONTRACT = "wf.slice.vertical_slice_contract.v1"
RT_SLICE_SCENARIO = "wf.slice.slice_scenario.v1"
RT_SLICE_MANIFEST = "wf.slice.slice_manifest.v1"
RT_SLICE_RUNTIME_REPORT = "wf.slice.runtime_report.v1"
RT_SLICE_PACKAGE_REPORT = "wf.slice.package_report.v1"
RT_SLICE_EVIDENCE_INDEX = "wf.slice.evidence_index.v1"

# --------------------------------------------------------------------------- #
# Bounded taxonomy (one source of truth). Membership resolution against real
# generated content is the Wave-2 authoring validator's job, NOT the schema's;
# these enums bound the *values a record may legally carry*.
# --------------------------------------------------------------------------- #
# save/load result vocabulary — slice completion requires ROUNDTRIP_OK.
SAVE_LOAD_ROUNDTRIP_OK = "roundtrip_ok"
SLICE_SAVE_LOAD_RESULTS = (SAVE_LOAD_ROUNDTRIP_OK, "not_run", "failed")

# evidence-index integrity verdict vocabulary.
INTEGRITY_RESULTS = ("ok", "fail")

# The v1.9 reward/progression save slots the slice's save/load MUST use, and the
# mission/npc/combat slots it must NOT reuse (mirrors reward_contracts.py so the
# honesty invariant is identical across milestones).
REWARD_SAVE_SLOT = "WFReward_State"
INVENTORY_SAVE_SLOT = "WFInventory_State"
PROGRESSION_SAVE_SLOT = "WFProgression_State"
SLICE_SAVE_SLOTS = (REWARD_SAVE_SLOT, INVENTORY_SAVE_SLOT, PROGRESSION_SAVE_SLOT)
FORBIDDEN_SAVE_SLOTS = ("WFRuntime_Complete", "WFNPC_State", "WFCombat_State")

# The major-system boolean fields a runtime report must ALL have true to claim a
# completed slice. This is the anti-fake-green spine of v2.0: partial success can
# never claim slice_completed_runtime.
RUNTIME_SYSTEM_FLAGS = (
    "launched", "player_spawned", "traversal_completed", "npc_behavior_seen",
    "combat_damage_seen", "mission_completed", "reward_granted",
)

# The shared authoring timestamp (deterministic, NOT wall-clock) for example/
# authoring records; runtime/package evidence uses created_at == "live" + real sha.
AUTHORING_TS = "2026-07-10T00:00:00+00:00"

# Canonical slice matrix counts — the ONE place these live. Every gate imports
# SX.EXPECTED_SCENARIOS / SX.EXPECTED_MAPS instead of a bare literal, and
# slice_hygiene ties EXPECTED_SCENARIOS to the committed contract's scenario_count
# so a dimension change cannot silently desync the gates.
#   matrix = 2 biomes x 3 archetypes x 2 profiles x 2 seeds = 24 scenarios,
#   over 12 maps (maps are profile-agnostic: 24 / 2 profiles = 12).
EXPECTED_SCENARIOS = 24
EXPECTED_MAPS = 12

# --------------------------------------------------------------------------- #
# Generated / report roots (repo-relative). Slice evidence is independently
# inspectable and is NOT mixed into the combat/npc/reward/ground trees — it may
# only REFERENCE them (brief §11).
# --------------------------------------------------------------------------- #
SLICE_GENERATED_REL = "procedural/generated/slice"
SLICE_CONTRACT_REL = "procedural/generated/slice/vertical_slice_contract.json"
SLICE_SCENARIOS_REL = "procedural/generated/slice/scenarios"
SLICE_MANIFEST_REL = "procedural/generated/slice/manifest.json"
SLICE_REPORTS_REL = "procedural/reports/slice"
SLICE_RUNTIME_REPORTS_REL = "procedural/reports/slice/runtime"
SLICE_PACKAGE_REPORTS_REL = "procedural/reports/slice/package"
SLICE_SAVE_LOAD_REPORTS_REL = "procedural/reports/slice/save_load"
SLICE_INTEGRITY_REPORTS_REL = "procedural/reports/slice/integrity"


# --------------------------------------------------------------------------- #
# small local helpers (mirror reward_contracts.py)
# --------------------------------------------------------------------------- #
def _str(obj, field, code, prefix):
    """A required id/path/version string: present, a str, and non-empty.

    RS.check_type accepts "" as a valid str and RS.check_required accepts "" as
    non-None, so an empty id would otherwise slip through — every field routed
    here is an identifier/path/version that must carry a real value.
    """
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
    """A required integer field: a real number, integer-valued, and >=0 (or >0).

    RS.check_positive_number accepts any non-negative float (e.g. 3.14159), so an
    explicit integer-value check is added — counts/seeds/sizes must be integers.
    """
    ch = RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)
    v = obj.get(field) if isinstance(obj, dict) else None
    is_int = RS.is_number(v) and float(v).is_integer()
    ch.append(("{}{}_integer".format(prefix, field), is_int,
               "{} must be an integer (got {!r})".format(field, v), code))
    return ch


def _list_of_str(obj, field, code, prefix, min_len=0):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) >= min_len and all(isinstance(x, str) for x in v)
    return [("{}{}_str_list".format(prefix, field), ok,
             "{} must be a list of >= {} strings".format(field, min_len), code)]


def _list_of_int(obj, field, code, prefix, min_len=0):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = (isinstance(v, list) and len(v) >= min_len
          and all(RS.is_number(x) and float(x).is_integer() for x in v))
    return [("{}{}_int_list".format(prefix, field), ok,
             "{} must be a list of >= {} integers (deterministic seeds)".format(field, min_len), code)]


def _is_list(obj, field):
    return isinstance(obj.get(field), list) if isinstance(obj, dict) else False


# --------------------------------------------------------------------------- #
# 1. VerticalSliceContract (WF671)  — the slice definition
# --------------------------------------------------------------------------- #
VERTICAL_SLICE_CONTRACT_REQUIRED = (
    "slice_id", "pack_id", "biomes", "mission_archetypes", "encounter_profiles",
    "seeds", "scenario_count",
    "requires_package", "requires_runtime", "requires_traversal", "requires_npc",
    "requires_combat", "requires_rewards", "requires_save_load",
    "requires_evidence_index", "schema_version",
)
VERTICAL_SLICE_CONTRACT_ALLOWED = VERTICAL_SLICE_CONTRACT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "description", "notes",
)
_REQUIRES_FLAGS = (
    "requires_package", "requires_runtime", "requires_traversal", "requires_npc",
    "requires_combat", "requires_rewards", "requires_save_load",
    "requires_evidence_index",
)


def validate_vertical_slice_contract(obj, strict=False):
    code = C.SLICE_CONTRACT_INVALID
    ch = RS.check_required(obj, VERTICAL_SLICE_CONTRACT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, VERTICAL_SLICE_CONTRACT_ALLOWED, code, strict)
    ch += _str(obj, "slice_id", code, "vsc::")
    ch += _str(obj, "pack_id", code, "vsc::")
    ch += _list_of_str(obj, "biomes", C.SLICE_CONTRACT_INVALID, "vsc::", min_len=1)
    ch += _list_of_str(obj, "mission_archetypes", C.SLICE_CONTRACT_INVALID, "vsc::", min_len=1)
    ch += _list_of_str(obj, "encounter_profiles", C.SLICE_CONTRACT_INVALID, "vsc::", min_len=1)
    ch += _list_of_int(obj, "seeds", C.SLICE_CONTRACT_INVALID, "vsc::", min_len=1)
    ch += _int(obj, "scenario_count", C.SLICE_SCENARIO_SET_INVALID, "vsc::", allow_zero=False)
    for f in _REQUIRES_FLAGS:
        ch += _bool(obj, f, code, "vsc::")

    # --- honesty invariant: scenario_count == matrix product -----------------
    if all(_is_list(obj, f) for f in ("biomes", "mission_archetypes",
                                      "encounter_profiles", "seeds")):
        product = (len(obj["biomes"]) * len(obj["mission_archetypes"])
                   * len(obj["encounter_profiles"]) * len(obj["seeds"]))
        declared = obj.get("scenario_count")
        ok = RS.is_number(declared) and int(declared) == product
        ch.append(("vsc::scenario_count_is_matrix_product", ok,
                   "scenario_count ({}) must equal biomes*archetypes*profiles*seeds = {}"
                   .format(declared, product), C.SLICE_SCENARIO_SET_INVALID))
        # dimensions must have no duplicate values (a repeated biome/seed inflates
        # the product without adding real coverage).
        for f in ("biomes", "mission_archetypes", "encounter_profiles", "seeds"):
            vals = obj.get(f) or []
            uniq = len(vals) == len(set(vals))
            ch.append(("vsc::{}_unique".format(f), uniq,
                       "{} must contain no duplicate values".format(f), code))

    # schema_version must be the declared namespace.
    sv = obj.get("schema_version")
    ch.append(("vsc::schema_version", sv == RT_VERTICAL_SLICE_CONTRACT,
               "schema_version must be {!r} (got {!r})".format(RT_VERTICAL_SLICE_CONTRACT, sv), code))
    return ch


def _example_vertical_slice_contract(**over):
    d = {
        "slice_id": "worldforge_vertical_slice",
        "pack_id": "encounter_loop_world",
        "biomes": ["desert", "forest"],
        "mission_archetypes": ["reach_objective", "recover_item", "clear_encounter"],
        "encounter_profiles": ["baseline", "high"],
        "seeds": [1, 2],
        "scenario_count": 24,
        "requires_package": True,
        "requires_runtime": True,
        "requires_traversal": True,
        "requires_npc": True,
        "requires_combat": True,
        "requires_rewards": True,
        "requires_save_load": True,
        "requires_evidence_index": True,
        "created_by": "worldforge.v2.0",
        "created_at": AUTHORING_TS,
        "schema_version": RT_VERTICAL_SLICE_CONTRACT,
        "report_type": RT_VERTICAL_SLICE_CONTRACT,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 2. SliceScenario (WF696)  — one cell of the 24-scenario matrix
# --------------------------------------------------------------------------- #
SLICE_SCENARIO_REQUIRED = (
    "slice_scenario_id", "slice_id", "biome", "mission_archetype",
    "encounter_profile", "seed", "map_id", "mission_id", "encounter_id",
    "expected_route_id", "expected_reward_table_id", "expected_build_target",
    "schema_version",
)
SLICE_SCENARIO_ALLOWED = SLICE_SCENARIO_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "pack_id", "notes",
)


def validate_slice_scenario(obj, strict=False):
    code = C.SLICE_SCENARIO_INVALID
    ch = RS.check_required(obj, SLICE_SCENARIO_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SLICE_SCENARIO_ALLOWED, code, strict)
    for f in ("slice_scenario_id", "slice_id", "biome", "mission_archetype",
              "encounter_profile", "map_id", "mission_id", "encounter_id",
              "expected_build_target"):
        ch += _str(obj, f, code, "ss::")
    ch += _str(obj, "expected_route_id", C.SLICE_ROUTE_BINDING_INVALID, "ss::")
    ch += _str(obj, "expected_reward_table_id", C.SLICE_REWARD_TABLE_BINDING_INVALID, "ss::")
    ch += _int(obj, "seed", code, "ss::", allow_zero=True)
    sv = obj.get("schema_version")
    ch.append(("ss::schema_version", sv == RT_SLICE_SCENARIO,
               "schema_version must be {!r} (got {!r})".format(RT_SLICE_SCENARIO, sv), code))
    return ch


def _example_slice_scenario(**over):
    d = {
        "slice_scenario_id": "vs_desert_reach_objective_baseline_s1",
        "slice_id": "worldforge_vertical_slice",
        "pack_id": "encounter_loop_world",
        "biome": "desert",
        "mission_archetype": "reach_objective",
        "encounter_profile": "baseline",
        "seed": 1,
        "map_id": "L_desert_reach_objective_s1",
        "mission_id": "mission_desert_reach_objective_s1",
        "encounter_id": "enc_desert_baseline_s1",
        "expected_route_id": "route_desert_reach_objective_s1",
        "expected_reward_table_id": "rwt_reach_objective_baseline",
        "expected_build_target": "WorldForgeVerticalSlice",
        "created_by": "worldforge.v2.0",
        "created_at": AUTHORING_TS,
        "schema_version": RT_SLICE_SCENARIO,
        "report_type": RT_SLICE_SCENARIO,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 3. SliceManifest (WF697)  — the index over the whole authored slice
# --------------------------------------------------------------------------- #
SLICE_MANIFEST_REQUIRED = (
    "slice_id", "pack_id", "scenario_count", "scenarios", "maps",
    "biomes", "mission_archetypes", "encounter_profiles", "seeds",
    "schema_version",
)
SLICE_MANIFEST_ALLOWED = SLICE_MANIFEST_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "build_target", "notes",
)


def validate_slice_manifest(obj, strict=False):
    code = C.SLICE_MANIFEST_INVALID
    ch = RS.check_required(obj, SLICE_MANIFEST_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SLICE_MANIFEST_ALLOWED, code, strict)
    ch += _str(obj, "slice_id", code, "sm::")
    ch += _str(obj, "pack_id", code, "sm::")
    ch += _int(obj, "scenario_count", code, "sm::", allow_zero=False)
    ch += _list_of_str(obj, "scenarios", code, "sm::", min_len=1)
    ch += _list_of_str(obj, "maps", code, "sm::", min_len=1)
    ch += _list_of_str(obj, "biomes", code, "sm::", min_len=1)
    ch += _list_of_str(obj, "mission_archetypes", code, "sm::", min_len=1)
    ch += _list_of_str(obj, "encounter_profiles", code, "sm::", min_len=1)
    ch += _list_of_int(obj, "seeds", code, "sm::", min_len=1)

    # honesty: the scenario list length AND uniqueness must match scenario_count.
    if _is_list(obj, "scenarios"):
        scn = obj["scenarios"]
        ch.append(("sm::scenarios_len_matches_count",
                   RS.is_number(obj.get("scenario_count")) and len(scn) == int(obj["scenario_count"]),
                   "scenarios list length ({}) must equal scenario_count ({})"
                   .format(len(scn), obj.get("scenario_count")), code))
        ch.append(("sm::scenarios_unique", len(scn) == len(set(scn)),
                   "scenarios must contain no duplicate ids", C.SLICE_DUPLICATE_SCENARIO_REPORT))
    sv = obj.get("schema_version")
    ch.append(("sm::schema_version", sv == RT_SLICE_MANIFEST,
               "schema_version must be {!r} (got {!r})".format(RT_SLICE_MANIFEST, sv), code))
    return ch


def _example_slice_manifest(**over):
    scn = ["vs_desert_reach_objective_baseline_s1", "vs_desert_reach_objective_baseline_s2"]
    d = {
        "slice_id": "worldforge_vertical_slice",
        "pack_id": "encounter_loop_world",
        "scenario_count": len(scn),
        "scenarios": list(scn),
        "maps": ["L_desert_reach_objective_s1", "L_desert_reach_objective_s2"],
        "biomes": ["desert", "forest"],
        "mission_archetypes": ["reach_objective", "recover_item", "clear_encounter"],
        "encounter_profiles": ["baseline", "high"],
        "seeds": [1, 2],
        "build_target": "WorldForgeVerticalSlice",
        "created_by": "worldforge.v2.0",
        "created_at": AUTHORING_TS,
        "schema_version": RT_SLICE_MANIFEST,
        "report_type": RT_SLICE_MANIFEST,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 4. SliceRuntimeReport (WF678)  — per-scenario integrated runtime proof
# --------------------------------------------------------------------------- #
SLICE_RUNTIME_REPORT_REQUIRED = (
    "report_id", "slice_id", "slice_scenario_id", "map_id", "mission_id",
    "biome", "mission_archetype", "encounter_profile", "seed",
    "launched", "player_spawned", "traversal_completed", "npc_behavior_seen",
    "combat_damage_seen", "mission_completed", "reward_granted",
    "inventory_mutated", "progression_mutated", "save_load_result",
    "save_slot", "slice_completed_runtime", "package_build_id",
    "telemetry_paths", "failure_codes", "schema_version",
)
SLICE_RUNTIME_REPORT_ALLOWED = SLICE_RUNTIME_REPORT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "git_commit",
    "damage_events", "npc_spawn_count", "notes",
)


def validate_slice_runtime_report(obj, strict=False):
    code = C.SLICE_RUNTIME_REPORT_MISSING
    ch = RS.check_required(obj, SLICE_RUNTIME_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SLICE_RUNTIME_REPORT_ALLOWED, code, strict)
    for f in ("report_id", "slice_id", "slice_scenario_id", "map_id",
              "mission_id", "biome", "mission_archetype", "encounter_profile",
              "package_build_id", "save_slot"):
        ch += _str(obj, f, code, "sr::")
    ch += _int(obj, "seed", code, "sr::", allow_zero=True)
    for f in RUNTIME_SYSTEM_FLAGS + ("inventory_mutated", "progression_mutated",
                                     "slice_completed_runtime"):
        ch += _bool(obj, f, code, "sr::")
    ch += RS.check_enum(obj, "save_load_result", SLICE_SAVE_LOAD_RESULTS,
                        C.SLICE_SAVE_LOAD_FAILED, prefix="sr::")
    ch += _list_of_str(obj, "telemetry_paths", C.SLICE_TRAVERSAL_MISSING, "sr::", min_len=0)
    # failure_codes must be a list (empty only on a valid completed slice).
    fc_is_list = _is_list(obj, "failure_codes")
    ch.append(("sr::failure_codes_list", fc_is_list,
               "failure_codes must be a list", code))

    completed = obj.get("slice_completed_runtime") is True

    # --- honesty invariant: completed slice requires every system + clean codes -
    if completed:
        for f in RUNTIME_SYSTEM_FLAGS:
            ch.append(("sr::completed_requires::{}".format(f), obj.get(f) is True,
                       "slice_completed_runtime requires {} == true".format(f),
                       _RUNTIME_FLAG_CODE.get(f, C.SLICE_PARTIAL_MATRIX)))
        # reward participation must mutate at least one persistent store.
        mutated = (obj.get("inventory_mutated") is True
                   or obj.get("progression_mutated") is True)
        ch.append(("sr::completed_requires::state_mutated", mutated,
                   "reward_granted with NO inventory/progression mutation is fake reward",
                   C.SLICE_REWARD_WITHOUT_MUTATION))
        # save/load must round-trip AND use a v1.9 reward slot, never mission/combat.
        ch.append(("sr::completed_requires::save_load_roundtrip",
                   obj.get("save_load_result") == SAVE_LOAD_ROUNDTRIP_OK,
                   "slice_completed_runtime requires save_load_result == roundtrip_ok",
                   C.SLICE_SAVE_LOAD_FAILED))
        slot = obj.get("save_slot")
        ch.append(("sr::completed_requires::v1_9_save_slot",
                   slot in SLICE_SAVE_SLOTS and slot not in FORBIDDEN_SAVE_SLOTS,
                   "save_slot must be a v1.9 reward slot {} (got {!r}), never {}"
                   .format(SLICE_SAVE_SLOTS, slot, FORBIDDEN_SAVE_SLOTS),
                   C.SLICE_SAVE_LOAD_WRONG_SLOT))
        # a completed slice's failure_codes MUST be empty.
        ch.append(("sr::completed_requires::no_failure_codes",
                   fc_is_list and len(obj.get("failure_codes")) == 0,
                   "slice_completed_runtime requires an empty failure_codes list",
                   C.SLICE_PARTIAL_MATRIX))
        # telemetry paths must exist as records (schema level: non-empty list).
        ch.append(("sr::completed_requires::telemetry_present",
                   _is_list(obj, "telemetry_paths") and len(obj["telemetry_paths"]) > 0,
                   "slice_completed_runtime requires >= 1 telemetry path",
                   C.SLICE_TRAVERSAL_MISSING))
    else:
        # a non-completed report that also declares an empty failure_codes list is
        # an integrity smell — it claims nothing failed yet did not complete.
        if fc_is_list:
            ch.append(("sr::incomplete_has_failure_codes",
                       len(obj.get("failure_codes")) > 0,
                       "a report that is not slice_completed_runtime must carry >=1 "
                       "failure_code explaining why", code))

    sv = obj.get("schema_version")
    ch.append(("sr::schema_version", sv == RT_SLICE_RUNTIME_REPORT,
               "schema_version must be {!r} (got {!r})".format(RT_SLICE_RUNTIME_REPORT, sv), code))
    return ch


# map each system flag to the most specific failure code for a completed-claim gap.
_RUNTIME_FLAG_CODE = {
    "launched": C.SLICE_LAUNCH_FAILED,
    "player_spawned": C.SLICE_LAUNCH_FAILED,
    "traversal_completed": C.SLICE_TRAVERSAL_MISSING,
    "npc_behavior_seen": C.SLICE_NPC_EVIDENCE_MISSING,
    "combat_damage_seen": C.SLICE_NPC_NO_DAMAGE,
    "mission_completed": C.SLICE_MISSION_INCOMPLETE,
    "reward_granted": C.SLICE_REWARD_EVIDENCE_MISSING,
}


def _example_slice_runtime_report(**over):
    d = {
        "report_id": "slice_runtime_vs_desert_reach_objective_baseline_s1",
        "slice_id": "worldforge_vertical_slice",
        "slice_scenario_id": "vs_desert_reach_objective_baseline_s1",
        "map_id": "L_desert_reach_objective_s1",
        "mission_id": "mission_desert_reach_objective_s1",
        "biome": "desert",
        "mission_archetype": "reach_objective",
        "encounter_profile": "baseline",
        "seed": 1,
        "launched": True,
        "player_spawned": True,
        "traversal_completed": True,
        "npc_behavior_seen": True,
        "combat_damage_seen": True,
        "mission_completed": True,
        "reward_granted": True,
        "inventory_mutated": True,
        "progression_mutated": True,
        "save_load_result": SAVE_LOAD_ROUNDTRIP_OK,
        "save_slot": REWARD_SAVE_SLOT,
        "slice_completed_runtime": True,
        "package_build_id": "slicebuild_0001",
        "telemetry_paths": ["procedural/reports/slice/runtime/slice_traversal_vs_desert_reach_objective_baseline_s1.json"],
        "failure_codes": [],
        "damage_events": 3,
        "npc_spawn_count": 2,
        "created_at": "live",
        "git_commit": "0000000000000000000000000000000000000000",
        "schema_version": RT_SLICE_RUNTIME_REPORT,
        "report_type": RT_SLICE_RUNTIME_REPORT,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 5. SlicePackageReport (WF674/675)  — the build/package artifact proof
# --------------------------------------------------------------------------- #
SLICE_PACKAGE_REPORT_REQUIRED = (
    "package_report_id", "slice_id", "pack_id", "build_target", "package_path",
    "package_exists", "package_size_bytes", "build_config", "maps_included",
    "assets_included", "runtime_entrypoint", "created_at", "git_sha",
    "failure_codes", "schema_version",
)
SLICE_PACKAGE_REPORT_ALLOWED = SLICE_PACKAGE_REPORT_REQUIRED + (
    "meta", "report_type", "created_by", "package_hash", "notes",
)


def validate_slice_package_report(obj, strict=False):
    code = C.SLICE_BUILD_MANIFEST_INVALID
    ch = RS.check_required(obj, SLICE_PACKAGE_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SLICE_PACKAGE_REPORT_ALLOWED, code, strict)
    for f in ("package_report_id", "slice_id", "pack_id", "build_target",
              "package_path", "build_config", "runtime_entrypoint", "git_sha",
              "created_at"):
        ch += _str(obj, f, code, "pr::")
    ch += _bool(obj, "package_exists", C.SLICE_PACKAGE_MISSING, "pr::")
    ch += _int(obj, "package_size_bytes", C.SLICE_PACKAGE_INVALID, "pr::", allow_zero=True)
    ch += _list_of_str(obj, "maps_included", code, "pr::", min_len=1)
    ch += _list_of_str(obj, "assets_included", code, "pr::", min_len=0)
    fc_is_list = _is_list(obj, "failure_codes")
    ch.append(("pr::failure_codes_list", fc_is_list, "failure_codes must be a list", code))

    # --- honesty invariant: a package report cannot pass with no package -------
    exists = obj.get("package_exists") is True
    size = obj.get("package_size_bytes")
    ch.append(("pr::package_exists_requires_size",
               (not exists) or (RS.is_number(size) and size > 0),
               "package_exists=true requires package_size_bytes > 0 (got {!r})".format(size),
               C.SLICE_PACKAGE_MISSING))
    # a passing package report (empty failure_codes) MUST have a real package.
    passing = fc_is_list and len(obj.get("failure_codes") or []) == 0
    ch.append(("pr::pass_requires_real_package",
               (not passing) or (exists and RS.is_number(size) and size > 0),
               "a package report with empty failure_codes must have package_exists=true "
               "and package_size_bytes > 0",
               C.SLICE_PACKAGE_MISSING))
    # live evidence requires a real sha (mirrors the reward staleness invariant).
    if obj.get("created_at") == "live":
        sha = obj.get("git_sha")
        ch.append(("pr::live_requires_real_sha",
                   isinstance(sha, str) and sha and sha != "unknown",
                   "created_at='live' requires a real git_sha (got {!r})".format(sha),
                   C.SLICE_STALE_EVIDENCE))
    sv = obj.get("schema_version")
    ch.append(("pr::schema_version", sv == RT_SLICE_PACKAGE_REPORT,
               "schema_version must be {!r} (got {!r})".format(RT_SLICE_PACKAGE_REPORT, sv), code))
    return ch


def _example_slice_package_report(**over):
    d = {
        "package_report_id": "slice_package_worldforge_vertical_slice",
        "slice_id": "worldforge_vertical_slice",
        "pack_id": "encounter_loop_world",
        "build_target": "WorldForgeVerticalSlice",
        "package_path": "Build/WorldForgeVerticalSlice/Windows/WorldForgeVerticalSlice.exe",
        "package_exists": True,
        "package_size_bytes": 524288000,
        "build_config": "Development",
        "maps_included": ["L_desert_reach_objective_s1", "L_desert_reach_objective_s2"],
        "assets_included": ["MI_Terrain_Desert_01", "SM_Cover_Rock_01"],
        "runtime_entrypoint": "L_desert_reach_objective_s1",
        "package_hash": "0" * 64,
        "created_at": "live",
        "git_sha": "0000000000000000000000000000000000000000",
        "failure_codes": [],
        "schema_version": RT_SLICE_PACKAGE_REPORT,
        "report_type": RT_SLICE_PACKAGE_REPORT,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 6. SliceEvidenceIndex (WF685)  — coverage over all 24 scenarios
# --------------------------------------------------------------------------- #
SLICE_EVIDENCE_INDEX_REQUIRED = (
    "slice_id", "scenario_count_expected", "scenario_count_seen",
    "runtime_reports", "save_load_reports", "package_reports",
    "missing_evidence", "stale_evidence", "integrity_result", "schema_version",
)
SLICE_EVIDENCE_INDEX_ALLOWED = SLICE_EVIDENCE_INDEX_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "duplicate_reports", "notes",
)
# Evidence categories carried by the index. Only categories backed by a real,
# independently-inspectable artifact are listed: runtime_reports (one
# slice_runtime_<ssid>.json per scenario), save_load_reports (the scenarios whose
# runtime report proved save_load_result==roundtrip_ok — a DERIVED subset, not a
# blind copy), and package_reports (the SlicePackageReport). The traversal / npc /
# combat / reward facets are proven INSIDE each SliceRuntimeReport and by the
# per-facet validators (validate_slice_traversal/npc_combat/rewards) — they are
# not separate evidence files, so listing them here (as copies of the runtime
# ssids) claimed independence the index did not have. Audit candidate C4.
_EVIDENCE_LIST_FIELDS = (
    "runtime_reports", "save_load_reports", "package_reports",
)


def validate_slice_evidence_index(obj, strict=False):
    code = C.SLICE_EVIDENCE_INDEX_INVALID
    ch = RS.check_required(obj, SLICE_EVIDENCE_INDEX_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SLICE_EVIDENCE_INDEX_ALLOWED, code, strict)
    ch += _str(obj, "slice_id", code, "ei::")
    ch += _int(obj, "scenario_count_expected", code, "ei::", allow_zero=False)
    ch += _int(obj, "scenario_count_seen", code, "ei::", allow_zero=True)
    for f in _EVIDENCE_LIST_FIELDS + ("missing_evidence", "stale_evidence"):
        ch.append(("ei::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += RS.check_enum(obj, "integrity_result", INTEGRITY_RESULTS, code, prefix="ei::")

    exp = obj.get("scenario_count_expected")
    seen = obj.get("scenario_count_seen")
    # --- honesty invariant: index passes only if every scenario is covered -----
    passing = obj.get("integrity_result") == "ok"
    full = RS.is_number(exp) and RS.is_number(seen) and int(seen) == int(exp)
    ch.append(("ei::seen_equals_expected", (not passing) or full,
               "integrity_result=ok requires scenario_count_seen ({}) == expected ({})"
               .format(seen, exp), C.SLICE_PARTIAL_MATRIX))
    if passing:
        ch.append(("ei::no_missing_evidence",
                   _is_list(obj, "missing_evidence") and len(obj["missing_evidence"]) == 0,
                   "integrity_result=ok requires missing_evidence to be empty",
                   C.SLICE_PARTIAL_MATRIX))
        ch.append(("ei::no_stale_evidence",
                   _is_list(obj, "stale_evidence") and len(obj["stale_evidence"]) == 0,
                   "integrity_result=ok requires stale_evidence to be empty",
                   C.SLICE_STALE_EVIDENCE))
        # each evidence category must cover the SAME distinct scenarios — count
        # alone is not coverage (24 duplicate ids is not 24 scenarios). runtime_
        # reports is the reference set; every other per-scenario category must be
        # exactly that set of distinct ids.
        ref = set(obj["runtime_reports"]) if _is_list(obj, "runtime_reports") else set()
        ch.append(("ei::runtime_reports_distinct_full",
                   RS.is_number(exp) and len(ref) == int(exp),
                   "runtime_reports must list {} DISTINCT scenario ids (got {} distinct)"
                   .format(exp, len(ref)), C.SLICE_PARTIAL_MATRIX))
        for f in _EVIDENCE_LIST_FIELDS:
            if f == "package_reports":
                continue  # one package covers the whole slice, not one-per-scenario
            vals = obj[f] if _is_list(obj, f) else []
            distinct = set(vals)
            ok = RS.is_number(exp) and len(distinct) == int(exp) and distinct == ref
            ch.append(("ei::{}_covers_all".format(f), ok,
                       "{} must cover the {} distinct scenarios in runtime_reports "
                       "({} distinct, same_set={})"
                       .format(f, exp, len(distinct), distinct == ref),
                       C.SLICE_PARTIAL_MATRIX))
    sv = obj.get("schema_version")
    ch.append(("ei::schema_version", sv == RT_SLICE_EVIDENCE_INDEX,
               "schema_version must be {!r} (got {!r})".format(RT_SLICE_EVIDENCE_INDEX, sv), code))
    return ch


def _example_slice_evidence_index(**over):
    one = ["vs_desert_reach_objective_baseline_s1"]
    d = {
        "slice_id": "worldforge_vertical_slice",
        "scenario_count_expected": 1,
        "scenario_count_seen": 1,
        "runtime_reports": list(one),
        "save_load_reports": list(one),
        "package_reports": ["slice_package_worldforge_vertical_slice"],
        "missing_evidence": [],
        "stale_evidence": [],
        "duplicate_reports": [],
        "integrity_result": "ok",
        "created_at": "live",
        "schema_version": RT_SLICE_EVIDENCE_INDEX,
        "report_type": RT_SLICE_EVIDENCE_INDEX,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry of all contracts, for the schema validators + fuzz harness.
# Each entry: name -> (validate_fn, valid_example_fn, known_bad_example_fn).
# The known-bad MUST fail the validator for its OWNING code — a contract that
# accepts it is fake green. CONTRACT_GROUPS splits the registry into gate lanes.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "VerticalSliceContract": (
        validate_vertical_slice_contract, _example_vertical_slice_contract,
        # scenario_count 25 != matrix product 24 -> WF672.
        lambda: _example_vertical_slice_contract(scenario_count=25)),
    "SliceScenario": (
        validate_slice_scenario, _example_slice_scenario,
        # missing the reward-table binding -> WF699.
        lambda: _example_slice_scenario(expected_reward_table_id=None)),
    "SliceManifest": (
        validate_slice_manifest, _example_slice_manifest,
        # scenario_count says 2 but list carries a duplicate (len 2, set 1) -> WF707.
        lambda: _example_slice_manifest(
            scenarios=["vs_desert_reach_objective_baseline_s1",
                       "vs_desert_reach_objective_baseline_s1"])),
    "SliceRuntimeReport": (
        validate_slice_runtime_report, _example_slice_runtime_report,
        # claims completed but no state mutated = fake reward -> WF704.
        lambda: _example_slice_runtime_report(inventory_mutated=False,
                                              progression_mutated=False)),
    "SlicePackageReport": (
        validate_slice_package_report, _example_slice_package_report,
        # passing report (empty failure_codes) but package_exists false -> WF675.
        lambda: _example_slice_package_report(package_exists=False,
                                              package_size_bytes=0)),
    "SliceEvidenceIndex": (
        validate_slice_evidence_index, _example_slice_evidence_index,
        # integrity ok but only 1 of 2 scenarios seen = partial matrix -> WF686.
        lambda: _example_slice_evidence_index(scenario_count_expected=2)),
}

CONTRACT_GROUPS = {
    "definition": ("VerticalSliceContract", "SliceScenario", "SliceManifest"),
    "runtime": ("SliceRuntimeReport",),
    "package": ("SlicePackageReport",),
    "evidence": ("SliceEvidenceIndex",),
}

# The owning failure code each known-bad must be rejected FOR (used by the
# negatives suite: rejection for the wrong reason is not real coverage).
KNOWN_BAD_OWNING_CODE = {
    "VerticalSliceContract": C.SLICE_SCENARIO_SET_INVALID,
    "SliceScenario": C.SLICE_REWARD_TABLE_BINDING_INVALID,
    "SliceManifest": C.SLICE_DUPLICATE_SCENARIO_REPORT,
    "SliceRuntimeReport": C.SLICE_REWARD_WITHOUT_MUTATION,
    "SlicePackageReport": C.SLICE_PACKAGE_MISSING,
    "SliceEvidenceIndex": C.SLICE_PARTIAL_MATRIX,
}
