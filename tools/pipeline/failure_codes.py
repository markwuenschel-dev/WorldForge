#!/usr/bin/env python3
"""failure_codes.py — WorldForge v0.9 canonical validation failure codes.

Stable, machine-readable identifiers for *why* a check failed, so reports,
audits, package-check, and the operator runbook can categorize and triage
failures consistently instead of grepping free-text detail strings.

These codes are ADDITIVE: validators still emit a human-readable ``detail`` for
every check; the code is an optional, stable categorization passed alongside.
The free-text ``detail`` remains the source of specifics — the code is the
bucket.

Code shape: ``WFnnn_SHORT_NAME``.  Numbers are grouped by surface:

    000–009  descriptor / parsing
    010–019  registry / ownership
    020–029  provenance
    030–039  generated artifacts (heightmaps, masks, maps, descriptors)
    040–049  path policy (Houdini Temp/Bake, owned-tree, catalog membership)
    050–059  ownership integrity (human templates, destroyable flags)
    060–069  budget
    070–079  runtime state / scenarios
    080–089  UE materialization (tooling drives the editor)
    090–099  packaging

The taxonomy doc (docs/contracts/v0_9_failure_taxonomy.md) is the human-facing
companion: severity, what it means, and how to clear it.
"""


class FailureCode:
    # -- descriptor / parsing (000) -----------------------------------------
    DESCRIPTOR_MISSING = "WF000_DESCRIPTOR_MISSING"
    DESCRIPTOR_UNPARSEABLE = "WF001_DESCRIPTOR_UNPARSEABLE"
    RECIPE_MISSING = "WF002_RECIPE_MISSING"
    SPEC_INVALID = "WF003_SPEC_INVALID"

    # -- registry / ownership (010) -----------------------------------------
    REGISTRY_MISSING_ENTRY = "WF010_REGISTRY_MISSING_ENTRY"
    REGISTRY_INCONSISTENT = "WF011_REGISTRY_INCONSISTENT"
    OWNER_UNRESOLVABLE = "WF012_OWNER_UNRESOLVABLE"

    # -- provenance (020) ----------------------------------------------------
    PROVENANCE_MISSING = "WF020_PROVENANCE_MISSING"
    PROVENANCE_INCOMPLETE = "WF021_PROVENANCE_INCOMPLETE"

    # -- generated artifacts (030) ------------------------------------------
    ARTIFACT_MISSING = "WF030_ARTIFACT_MISSING"
    ARTIFACT_DEGENERATE = "WF031_ARTIFACT_DEGENERATE"
    DIMENSIONS_INVALID = "WF032_DIMENSIONS_INVALID"
    MAP_INVALID = "WF033_MAP_INVALID"

    # -- path policy (040) ---------------------------------------------------
    FORBIDDEN_PATH = "WF040_FORBIDDEN_PATH"
    PATH_NOT_OWNED = "WF041_PATH_NOT_OWNED"
    CATALOG_MEMBERSHIP_MISSING = "WF042_CATALOG_MEMBERSHIP_MISSING"
    TEMP_PATH_AS_FINAL = "WF043_TEMP_PATH_AS_FINAL"

    # -- ownership integrity (050) ------------------------------------------
    HUMAN_TEMPLATE_MARKED_GENERATED = "WF050_HUMAN_TEMPLATE_MARKED_GENERATED"
    GENERATED_FLAG_MISSING = "WF051_GENERATED_FLAG_MISSING"
    DESTROYABLE_HUMAN_OWNED = "WF052_DESTROYABLE_HUMAN_OWNED"

    # -- budget (060) --------------------------------------------------------
    BUDGET_EXCEEDED = "WF060_BUDGET_EXCEEDED"
    BUDGET_PROFILE_MISSING = "WF061_BUDGET_PROFILE_MISSING"

    # -- runtime state / scenarios (070) ------------------------------------
    SCENARIO_UNPARSEABLE = "WF070_SCENARIO_UNPARSEABLE"
    TARGET_MAP_UNRESOLVED = "WF071_TARGET_MAP_UNRESOLVED"
    STATE_DELTA_UNBOUNDED = "WF072_STATE_DELTA_UNBOUNDED"
    MPC_VALUE_MISMATCH = "WF073_MPC_VALUE_MISMATCH"
    POI_EVIDENCE_MISSING = "WF074_POI_EVIDENCE_MISSING"
    SAVE_LOAD_ROUNDTRIP_FAILED = "WF075_SAVE_LOAD_ROUNDTRIP_FAILED"
    STATE_MUTATION_MISMATCH = "WF076_STATE_MUTATION_MISMATCH"
    AGGREGATE_INCONSISTENT = "WF077_AGGREGATE_INCONSISTENT"

    # -- UE materialization (080) — tooling drives the editor to produce these
    UE_ARTIFACT_MISSING = "WF080_UE_ARTIFACT_MISSING"
    UE_ASSET_NOT_STATIC_MESH = "WF081_UE_ASSET_NOT_STATIC_MESH"
    UE_STATE_NOT_APPLIED = "WF082_UE_STATE_NOT_APPLIED"

    # -- packaging / aggregation rollup (090) --------------------------------
    PACKAGE_FORBIDDEN_DEPENDENCY = "WF090_PACKAGE_FORBIDDEN_DEPENDENCY"
    PACKAGE_UNRESOLVED_REFERENCE = "WF091_PACKAGE_UNRESOLVED_REFERENCE"
    PACKAGE_MISSING_OWNED_ASSET = "WF092_PACKAGE_MISSING_OWNED_ASSET"
    CHILD_VALIDATION_FAILED = "WF093_CHILD_VALIDATION_FAILED"

    # ======================================================================
    # v1.0x hardening — gate-level failure taxonomy (100–260)
    # ----------------------------------------------------------------------
    # These are COARSER than the WF0xx codes above: one per full-shield gate
    # class, so the shared failure taxonomy in the v1.0x brief maps 1:1 to a
    # stable code. Fine-grained WF0xx codes still describe the specific defect;
    # a gate code buckets which lane owns it. Every v1.0x validator SHOULD tag
    # its blocking failures with the matching gate code so full-shield can roll
    # failures up by lane.
    # ======================================================================

    # -- report integrity / no-fake-green (100) -----------------------------
    REPORT_INTEGRITY_FAILURE = "WF100_REPORT_INTEGRITY_FAILURE"
    REPORT_MISSING = "WF101_REPORT_MISSING"
    REPORT_EMPTY = "WF102_REPORT_EMPTY"
    REPORT_STALE = "WF103_REPORT_STALE"
    REPORT_ZERO_RECORD = "WF104_REPORT_ZERO_RECORD"
    RECORD_COUNT_MISMATCH = "WF105_RECORD_COUNT_MISMATCH"
    VALIDATOR_SKIPPED = "WF106_VALIDATOR_SKIPPED"
    UNKNOWN_SCHEMA_FIELD = "WF107_UNKNOWN_SCHEMA_FIELD"
    IMPLICIT_FALLBACK_DEFAULT = "WF108_IMPLICIT_FALLBACK_DEFAULT"
    PARTIAL_SUCCESS_AS_SUCCESS = "WF109_PARTIAL_SUCCESS_AS_SUCCESS"

    # -- contract / generation (110) ----------------------------------------
    CONTRACT_FAILURE = "WF110_CONTRACT_FAILURE"
    GENERATION_FAILURE = "WF111_GENERATION_FAILURE"
    ASSET_REFERENCE_FAILURE = "WF112_ASSET_REFERENCE_FAILURE"
    OWNERSHIP_FAILURE = "WF113_OWNERSHIP_FAILURE"

    # -- environment / visual profiles (120) --------------------------------
    ENVIRONMENT_PROFILE_FAILURE = "WF120_ENVIRONMENT_PROFILE_FAILURE"
    VISUAL_STYLE_FAILURE = "WF121_VISUAL_STYLE_FAILURE"
    PROFILE_NOT_MATERIAL = "WF122_PROFILE_NOT_MATERIAL"
    PROFILE_INCOMPATIBLE = "WF123_PROFILE_INCOMPATIBLE"
    PROFILE_MISSING_BINDING = "WF124_PROFILE_MISSING_BINDING"

    # -- sky / lighting / fog / atmosphere (130) ----------------------------
    SKY_PROFILE_FAILURE = "WF130_SKY_PROFILE_FAILURE"
    LIGHTING_PROFILE_FAILURE = "WF131_LIGHTING_PROFILE_FAILURE"
    FOG_PROFILE_FAILURE = "WF132_FOG_PROFILE_FAILURE"
    ATMOSPHERE_PROFILE_FAILURE = "WF133_ATMOSPHERE_PROFILE_FAILURE"
    VISIBILITY_MINIMUM_VIOLATED = "WF134_VISIBILITY_MINIMUM_VIOLATED"
    EXPOSURE_OUT_OF_RANGE = "WF135_EXPOSURE_OUT_OF_RANGE"

    # -- POI / level design / reachability (140) ----------------------------
    POI_USABILITY_FAILURE = "WF140_POI_USABILITY_FAILURE"
    LEVEL_DESIGN_FAILURE = "WF141_LEVEL_DESIGN_FAILURE"
    REACHABILITY_FAILURE = "WF142_REACHABILITY_FAILURE"
    POI_GRAPH_FAILURE = "WF143_POI_GRAPH_FAILURE"
    POI_PLACEMENT_INVALID = "WF144_POI_PLACEMENT_INVALID"

    # -- entity anchors / encounter substrate (150) -------------------------
    ENTITY_ANCHOR_FAILURE = "WF150_ENTITY_ANCHOR_FAILURE"
    NPC_SPAWN_FAILURE = "WF151_NPC_SPAWN_FAILURE"
    ENCOUNTER_READINESS_FAILURE = "WF152_ENCOUNTER_READINESS_FAILURE"
    ENTITY_DENSITY_EXCEEDED = "WF153_ENTITY_DENSITY_EXCEEDED"

    # -- rendering / scalability / ray tracing / budgets (160) --------------
    RENDERING_PROFILE_FAILURE = "WF160_RENDERING_PROFILE_FAILURE"
    SCALABILITY_FAILURE = "WF161_SCALABILITY_FAILURE"
    RAYTRACING_FAILURE = "WF162_RAYTRACING_FAILURE"
    BUDGET_FAILURE = "WF163_BUDGET_FAILURE"
    FRAME_RISK_EXCEEDED = "WF164_FRAME_RISK_EXCEEDED"

    # -- scenario / package (170) -------------------------------------------
    SCENARIO_FAILURE = "WF170_SCENARIO_FAILURE"
    PACKAGE_FAILURE = "WF171_PACKAGE_FAILURE"

    # -- lifecycle / determinism / fuzz / regression (180) ------------------
    LIFECYCLE_FAILURE = "WF180_LIFECYCLE_FAILURE"
    DETERMINISM_FAILURE = "WF181_DETERMINISM_FAILURE"
    REGRESSION_FAILURE = "WF182_REGRESSION_FAILURE"
    FUZZ_FAILURE = "WF183_FUZZ_FAILURE"
    CORRUPTION_UNDETECTED = "WF184_CORRUPTION_UNDETECTED"
    REPAIR_TOUCHED_HUMAN_OWNED = "WF185_REPAIR_TOUCHED_HUMAN_OWNED"

    # ======================================================================
    # v1.1 BiomeForge — multi-environment expansion taxonomy (190–219)
    # ----------------------------------------------------------------------
    # ADDITIVE to the v1.0x taxonomy: one code per BiomeForge gate class so the
    # biome_expansion_world full-shield can roll biome failures up by lane the
    # same way v1.0x rolls up by gate. Fine-grained WF0xx codes still describe
    # the specific defect; these bucket which biome lane owns it. Do NOT reuse
    # or renumber a v1.0x code — extend cleanly here.
    # ======================================================================
    BIOME_CONTRACT_FAILURE = "WF190_BIOME_CONTRACT_FAILURE"
    BIOME_MATRIX_FAILURE = "WF191_BIOME_MATRIX_FAILURE"
    BIOME_PROFILE_BINDING_FAILURE = "WF192_BIOME_PROFILE_BINDING_FAILURE"
    BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE = "WF193_BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE"
    TERRAIN_FORM_FAILURE = "WF194_TERRAIN_FORM_FAILURE"
    MATERIAL_FAMILY_FAILURE = "WF195_MATERIAL_FAMILY_FAILURE"
    VEGETATION_PROFILE_FAILURE = "WF196_VEGETATION_PROFILE_FAILURE"
    PLACEMENT_PROFILE_FAILURE = "WF197_PLACEMENT_PROFILE_FAILURE"
    BIOME_POI_COMPATIBILITY_FAILURE = "WF198_BIOME_POI_COMPATIBILITY_FAILURE"
    BIOME_TRAVERSAL_FAILURE = "WF199_BIOME_TRAVERSAL_FAILURE"
    BIOME_ECOLOGY_FAILURE = "WF200_BIOME_ECOLOGY_FAILURE"
    BIOME_BUDGET_FAILURE = "WF201_BIOME_BUDGET_FAILURE"
    BIOME_PACKAGE_FAILURE = "WF202_BIOME_PACKAGE_FAILURE"
    BIOME_FUZZ_FAILURE = "WF203_BIOME_FUZZ_FAILURE"

    # ======================================================================
    # v1.2 MeshForge Intake — generated mesh asset taxonomy (210–239)
    # ----------------------------------------------------------------------
    # ADDITIVE to the v1.0x / v1.1 taxonomy: one code per MeshForge Intake gate
    # class so the biome_expansion_world full-shield (MESHES=1) can roll mesh
    # failures up by lane. Fine-grained WF0xx codes still describe the specific
    # defect; these bucket which mesh lane owns it. Do NOT reuse or renumber an
    # earlier code — extend cleanly here.
    # ======================================================================
    MESH_CONTRACT_FAILURE = "WF210_MESH_CONTRACT_FAILURE"
    MESH_CATALOG_FAILURE = "WF211_MESH_CATALOG_FAILURE"
    MESH_PROVENANCE_FAILURE = "WF212_MESH_PROVENANCE_FAILURE"
    MESH_OWNERSHIP_FAILURE = "WF213_MESH_OWNERSHIP_FAILURE"
    MESH_FINAL_PATH_FAILURE = "WF214_MESH_FINAL_PATH_FAILURE"
    MESH_SOURCE_FAILURE = "WF215_MESH_SOURCE_FAILURE"
    MESH_MATERIAL_BINDING_FAILURE = "WF216_MESH_MATERIAL_BINDING_FAILURE"
    MESH_COLLISION_FAILURE = "WF217_MESH_COLLISION_FAILURE"
    MESH_BOUNDS_FAILURE = "WF218_MESH_BOUNDS_FAILURE"
    MESH_PIVOT_FAILURE = "WF219_MESH_PIVOT_FAILURE"
    MESH_SCALE_FAILURE = "WF220_MESH_SCALE_FAILURE"
    MESH_PCG_ELIGIBILITY_FAILURE = "WF221_MESH_PCG_ELIGIBILITY_FAILURE"
    MESH_BIOME_COMPATIBILITY_FAILURE = "WF222_MESH_BIOME_COMPATIBILITY_FAILURE"
    MESH_RENDERING_BUDGET_FAILURE = "WF223_MESH_RENDERING_BUDGET_FAILURE"
    MESH_PACKAGE_FAILURE = "WF224_MESH_PACKAGE_FAILURE"
    MESH_LIFECYCLE_FAILURE = "WF225_MESH_LIFECYCLE_FAILURE"
    MESH_REPAIR_FAILURE = "WF226_MESH_REPAIR_FAILURE"
    MESH_DESTROY_FAILURE = "WF227_MESH_DESTROY_FAILURE"
    MESH_NEGATIVE_FIXTURE_FAILURE = "WF228_MESH_NEGATIVE_FIXTURE_FAILURE"


# severity hint per code: "fail" (blocking) or "warn" (soft / strict-blocking).
# This is the *default* nature of the code; a validator may still choose a
# stricter verdict for context.
SEVERITY = {
    FailureCode.DESCRIPTOR_MISSING: "fail",
    FailureCode.DESCRIPTOR_UNPARSEABLE: "fail",
    FailureCode.RECIPE_MISSING: "fail",
    FailureCode.SPEC_INVALID: "fail",
    FailureCode.REGISTRY_MISSING_ENTRY: "fail",
    FailureCode.REGISTRY_INCONSISTENT: "fail",
    FailureCode.OWNER_UNRESOLVABLE: "fail",
    FailureCode.PROVENANCE_MISSING: "fail",
    FailureCode.PROVENANCE_INCOMPLETE: "fail",
    FailureCode.ARTIFACT_MISSING: "fail",
    FailureCode.ARTIFACT_DEGENERATE: "fail",
    FailureCode.DIMENSIONS_INVALID: "fail",
    FailureCode.MAP_INVALID: "fail",
    FailureCode.FORBIDDEN_PATH: "fail",
    FailureCode.PATH_NOT_OWNED: "fail",
    FailureCode.CATALOG_MEMBERSHIP_MISSING: "fail",
    FailureCode.TEMP_PATH_AS_FINAL: "fail",
    FailureCode.HUMAN_TEMPLATE_MARKED_GENERATED: "fail",
    FailureCode.GENERATED_FLAG_MISSING: "fail",
    FailureCode.DESTROYABLE_HUMAN_OWNED: "fail",
    FailureCode.BUDGET_EXCEEDED: "fail",
    FailureCode.BUDGET_PROFILE_MISSING: "warn",
    FailureCode.SCENARIO_UNPARSEABLE: "fail",
    FailureCode.TARGET_MAP_UNRESOLVED: "fail",
    FailureCode.STATE_DELTA_UNBOUNDED: "fail",
    FailureCode.MPC_VALUE_MISMATCH: "fail",
    FailureCode.POI_EVIDENCE_MISSING: "fail",
    FailureCode.SAVE_LOAD_ROUNDTRIP_FAILED: "fail",
    FailureCode.STATE_MUTATION_MISMATCH: "fail",
    FailureCode.AGGREGATE_INCONSISTENT: "fail",
    FailureCode.UE_ARTIFACT_MISSING: "fail",
    FailureCode.UE_ASSET_NOT_STATIC_MESH: "fail",
    FailureCode.UE_STATE_NOT_APPLIED: "fail",
    FailureCode.PACKAGE_FORBIDDEN_DEPENDENCY: "fail",
    FailureCode.PACKAGE_UNRESOLVED_REFERENCE: "fail",
    FailureCode.PACKAGE_MISSING_OWNED_ASSET: "fail",
    FailureCode.CHILD_VALIDATION_FAILED: "fail",
    # v1.0x gate-level codes — every gate failure is blocking by nature.
    FailureCode.REPORT_INTEGRITY_FAILURE: "fail",
    FailureCode.REPORT_MISSING: "fail",
    FailureCode.REPORT_EMPTY: "fail",
    FailureCode.REPORT_STALE: "fail",
    FailureCode.REPORT_ZERO_RECORD: "fail",
    FailureCode.RECORD_COUNT_MISMATCH: "fail",
    FailureCode.VALIDATOR_SKIPPED: "fail",
    FailureCode.UNKNOWN_SCHEMA_FIELD: "fail",
    FailureCode.IMPLICIT_FALLBACK_DEFAULT: "fail",
    FailureCode.PARTIAL_SUCCESS_AS_SUCCESS: "fail",
    FailureCode.CONTRACT_FAILURE: "fail",
    FailureCode.GENERATION_FAILURE: "fail",
    FailureCode.ASSET_REFERENCE_FAILURE: "fail",
    FailureCode.OWNERSHIP_FAILURE: "fail",
    FailureCode.ENVIRONMENT_PROFILE_FAILURE: "fail",
    FailureCode.VISUAL_STYLE_FAILURE: "fail",
    FailureCode.PROFILE_NOT_MATERIAL: "fail",
    FailureCode.PROFILE_INCOMPATIBLE: "fail",
    FailureCode.PROFILE_MISSING_BINDING: "fail",
    FailureCode.SKY_PROFILE_FAILURE: "fail",
    FailureCode.LIGHTING_PROFILE_FAILURE: "fail",
    FailureCode.FOG_PROFILE_FAILURE: "fail",
    FailureCode.ATMOSPHERE_PROFILE_FAILURE: "fail",
    FailureCode.VISIBILITY_MINIMUM_VIOLATED: "fail",
    FailureCode.EXPOSURE_OUT_OF_RANGE: "fail",
    FailureCode.POI_USABILITY_FAILURE: "fail",
    FailureCode.LEVEL_DESIGN_FAILURE: "fail",
    FailureCode.REACHABILITY_FAILURE: "fail",
    FailureCode.POI_GRAPH_FAILURE: "fail",
    FailureCode.POI_PLACEMENT_INVALID: "fail",
    FailureCode.ENTITY_ANCHOR_FAILURE: "fail",
    FailureCode.NPC_SPAWN_FAILURE: "fail",
    FailureCode.ENCOUNTER_READINESS_FAILURE: "fail",
    FailureCode.ENTITY_DENSITY_EXCEEDED: "fail",
    FailureCode.RENDERING_PROFILE_FAILURE: "fail",
    FailureCode.SCALABILITY_FAILURE: "fail",
    FailureCode.RAYTRACING_FAILURE: "fail",
    FailureCode.BUDGET_FAILURE: "fail",
    FailureCode.FRAME_RISK_EXCEEDED: "fail",
    FailureCode.SCENARIO_FAILURE: "fail",
    FailureCode.PACKAGE_FAILURE: "fail",
    FailureCode.LIFECYCLE_FAILURE: "fail",
    FailureCode.DETERMINISM_FAILURE: "fail",
    FailureCode.REGRESSION_FAILURE: "fail",
    FailureCode.FUZZ_FAILURE: "fail",
    FailureCode.CORRUPTION_UNDETECTED: "fail",
    FailureCode.REPAIR_TOUCHED_HUMAN_OWNED: "fail",
    # v1.1 BiomeForge gate-level codes — every gate failure is blocking.
    FailureCode.BIOME_CONTRACT_FAILURE: "fail",
    FailureCode.BIOME_MATRIX_FAILURE: "fail",
    FailureCode.BIOME_PROFILE_BINDING_FAILURE: "fail",
    FailureCode.BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE: "fail",
    FailureCode.TERRAIN_FORM_FAILURE: "fail",
    FailureCode.MATERIAL_FAMILY_FAILURE: "fail",
    FailureCode.VEGETATION_PROFILE_FAILURE: "fail",
    FailureCode.PLACEMENT_PROFILE_FAILURE: "fail",
    FailureCode.BIOME_POI_COMPATIBILITY_FAILURE: "fail",
    FailureCode.BIOME_TRAVERSAL_FAILURE: "fail",
    FailureCode.BIOME_ECOLOGY_FAILURE: "fail",
    FailureCode.BIOME_BUDGET_FAILURE: "fail",
    FailureCode.BIOME_PACKAGE_FAILURE: "fail",
    FailureCode.BIOME_FUZZ_FAILURE: "fail",
    # v1.2 MeshForge Intake gate-level codes — every gate failure is blocking.
    FailureCode.MESH_CONTRACT_FAILURE: "fail",
    FailureCode.MESH_CATALOG_FAILURE: "fail",
    FailureCode.MESH_PROVENANCE_FAILURE: "fail",
    FailureCode.MESH_OWNERSHIP_FAILURE: "fail",
    FailureCode.MESH_FINAL_PATH_FAILURE: "fail",
    FailureCode.MESH_SOURCE_FAILURE: "fail",
    FailureCode.MESH_MATERIAL_BINDING_FAILURE: "fail",
    FailureCode.MESH_COLLISION_FAILURE: "fail",
    FailureCode.MESH_BOUNDS_FAILURE: "fail",
    FailureCode.MESH_PIVOT_FAILURE: "fail",
    FailureCode.MESH_SCALE_FAILURE: "fail",
    FailureCode.MESH_PCG_ELIGIBILITY_FAILURE: "fail",
    FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE: "fail",
    FailureCode.MESH_RENDERING_BUDGET_FAILURE: "fail",
    FailureCode.MESH_PACKAGE_FAILURE: "fail",
    FailureCode.MESH_LIFECYCLE_FAILURE: "fail",
    FailureCode.MESH_REPAIR_FAILURE: "fail",
    FailureCode.MESH_DESTROY_FAILURE: "fail",
    FailureCode.MESH_NEGATIVE_FIXTURE_FAILURE: "fail",
}

# The v1.0x gate-level failure taxonomy (brief §"shared failure taxonomy"):
# one code per full-shield gate class, used by full-shield to roll failures up
# by lane. Keyed by the human name in the brief -> stable code.
GATE_TAXONOMY = {
    "CONTRACT_FAILURE": FailureCode.CONTRACT_FAILURE,
    "GENERATION_FAILURE": FailureCode.GENERATION_FAILURE,
    "ASSET_REFERENCE_FAILURE": FailureCode.ASSET_REFERENCE_FAILURE,
    "OWNERSHIP_FAILURE": FailureCode.OWNERSHIP_FAILURE,
    "ENVIRONMENT_PROFILE_FAILURE": FailureCode.ENVIRONMENT_PROFILE_FAILURE,
    "SKY_PROFILE_FAILURE": FailureCode.SKY_PROFILE_FAILURE,
    "LIGHTING_PROFILE_FAILURE": FailureCode.LIGHTING_PROFILE_FAILURE,
    "FOG_PROFILE_FAILURE": FailureCode.FOG_PROFILE_FAILURE,
    "ATMOSPHERE_PROFILE_FAILURE": FailureCode.ATMOSPHERE_PROFILE_FAILURE,
    "POI_USABILITY_FAILURE": FailureCode.POI_USABILITY_FAILURE,
    "LEVEL_DESIGN_FAILURE": FailureCode.LEVEL_DESIGN_FAILURE,
    "REACHABILITY_FAILURE": FailureCode.REACHABILITY_FAILURE,
    "ENTITY_ANCHOR_FAILURE": FailureCode.ENTITY_ANCHOR_FAILURE,
    "RENDERING_PROFILE_FAILURE": FailureCode.RENDERING_PROFILE_FAILURE,
    "SCALABILITY_FAILURE": FailureCode.SCALABILITY_FAILURE,
    "RAYTRACING_FAILURE": FailureCode.RAYTRACING_FAILURE,
    "BUDGET_FAILURE": FailureCode.BUDGET_FAILURE,
    "SCENARIO_FAILURE": FailureCode.SCENARIO_FAILURE,
    "PACKAGE_FAILURE": FailureCode.PACKAGE_FAILURE,
    "LIFECYCLE_FAILURE": FailureCode.LIFECYCLE_FAILURE,
    "DETERMINISM_FAILURE": FailureCode.DETERMINISM_FAILURE,
    "REPORT_INTEGRITY_FAILURE": FailureCode.REPORT_INTEGRITY_FAILURE,
    "REGRESSION_FAILURE": FailureCode.REGRESSION_FAILURE,
    "FUZZ_FAILURE": FailureCode.FUZZ_FAILURE,
    # v1.1 BiomeForge lane codes.
    "BIOME_CONTRACT_FAILURE": FailureCode.BIOME_CONTRACT_FAILURE,
    "BIOME_MATRIX_FAILURE": FailureCode.BIOME_MATRIX_FAILURE,
    "BIOME_PROFILE_BINDING_FAILURE": FailureCode.BIOME_PROFILE_BINDING_FAILURE,
    "BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE": FailureCode.BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE,
    "TERRAIN_FORM_FAILURE": FailureCode.TERRAIN_FORM_FAILURE,
    "MATERIAL_FAMILY_FAILURE": FailureCode.MATERIAL_FAMILY_FAILURE,
    "VEGETATION_PROFILE_FAILURE": FailureCode.VEGETATION_PROFILE_FAILURE,
    "PLACEMENT_PROFILE_FAILURE": FailureCode.PLACEMENT_PROFILE_FAILURE,
    "BIOME_POI_COMPATIBILITY_FAILURE": FailureCode.BIOME_POI_COMPATIBILITY_FAILURE,
    "BIOME_TRAVERSAL_FAILURE": FailureCode.BIOME_TRAVERSAL_FAILURE,
    "BIOME_ECOLOGY_FAILURE": FailureCode.BIOME_ECOLOGY_FAILURE,
    "BIOME_BUDGET_FAILURE": FailureCode.BIOME_BUDGET_FAILURE,
    "BIOME_PACKAGE_FAILURE": FailureCode.BIOME_PACKAGE_FAILURE,
    "BIOME_FUZZ_FAILURE": FailureCode.BIOME_FUZZ_FAILURE,
    # v1.2 MeshForge Intake lane codes.
    "MESH_CONTRACT_FAILURE": FailureCode.MESH_CONTRACT_FAILURE,
    "MESH_CATALOG_FAILURE": FailureCode.MESH_CATALOG_FAILURE,
    "MESH_PROVENANCE_FAILURE": FailureCode.MESH_PROVENANCE_FAILURE,
    "MESH_OWNERSHIP_FAILURE": FailureCode.MESH_OWNERSHIP_FAILURE,
    "MESH_FINAL_PATH_FAILURE": FailureCode.MESH_FINAL_PATH_FAILURE,
    "MESH_SOURCE_FAILURE": FailureCode.MESH_SOURCE_FAILURE,
    "MESH_MATERIAL_BINDING_FAILURE": FailureCode.MESH_MATERIAL_BINDING_FAILURE,
    "MESH_COLLISION_FAILURE": FailureCode.MESH_COLLISION_FAILURE,
    "MESH_BOUNDS_FAILURE": FailureCode.MESH_BOUNDS_FAILURE,
    "MESH_PIVOT_FAILURE": FailureCode.MESH_PIVOT_FAILURE,
    "MESH_SCALE_FAILURE": FailureCode.MESH_SCALE_FAILURE,
    "MESH_PCG_ELIGIBILITY_FAILURE": FailureCode.MESH_PCG_ELIGIBILITY_FAILURE,
    "MESH_BIOME_COMPATIBILITY_FAILURE": FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE,
    "MESH_RENDERING_BUDGET_FAILURE": FailureCode.MESH_RENDERING_BUDGET_FAILURE,
    "MESH_PACKAGE_FAILURE": FailureCode.MESH_PACKAGE_FAILURE,
    "MESH_LIFECYCLE_FAILURE": FailureCode.MESH_LIFECYCLE_FAILURE,
    "MESH_REPAIR_FAILURE": FailureCode.MESH_REPAIR_FAILURE,
    "MESH_DESTROY_FAILURE": FailureCode.MESH_DESTROY_FAILURE,
    "MESH_NEGATIVE_FIXTURE_FAILURE": FailureCode.MESH_NEGATIVE_FIXTURE_FAILURE,
}


def all_codes():
    """Return every defined code string (for tests / docs generation)."""
    return [v for k, v in vars(FailureCode).items()
            if not k.startswith("_") and isinstance(v, str)]


def severity_of(code):
    """Return the default severity bucket for a code, or 'fail' if unknown."""
    return SEVERITY.get(code, "fail")
