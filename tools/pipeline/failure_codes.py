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
    080–089  UE materialization (D7-gated)
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

    # -- UE materialization, D7-gated (080) ---------------------------------
    UE_MATERIALIZATION_PENDING = "WF080_UE_MATERIALIZATION_PENDING"
    UE_ASSET_NOT_STATIC_MESH = "WF081_UE_ASSET_NOT_STATIC_MESH"
    UE_STATE_NOT_APPLIED = "WF082_UE_STATE_NOT_APPLIED"

    # -- packaging (090) -----------------------------------------------------
    PACKAGE_FORBIDDEN_DEPENDENCY = "WF090_PACKAGE_FORBIDDEN_DEPENDENCY"
    PACKAGE_UNRESOLVED_REFERENCE = "WF091_PACKAGE_UNRESOLVED_REFERENCE"
    PACKAGE_MISSING_OWNED_ASSET = "WF092_PACKAGE_MISSING_OWNED_ASSET"


# severity hint per code: "fail" (blocking), "warn" (soft / strict-blocking),
# or "gated" (D7 human/editor — never blocking).  This is the *default* nature
# of the code; a validator may still choose a stricter verdict for context.
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
    FailureCode.UE_MATERIALIZATION_PENDING: "gated",
    FailureCode.UE_ASSET_NOT_STATIC_MESH: "gated",
    FailureCode.UE_STATE_NOT_APPLIED: "gated",
    FailureCode.PACKAGE_FORBIDDEN_DEPENDENCY: "fail",
    FailureCode.PACKAGE_UNRESOLVED_REFERENCE: "fail",
    FailureCode.PACKAGE_MISSING_OWNED_ASSET: "fail",
}


def all_codes():
    """Return every defined code string (for tests / docs generation)."""
    return [v for k, v in vars(FailureCode).items()
            if not k.startswith("_") and isinstance(v, str)]


def severity_of(code):
    """Return the default severity bucket for a code, or 'fail' if unknown."""
    return SEVERITY.get(code, "fail")
