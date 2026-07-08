#!/usr/bin/env python3
"""v1_6_taxonomy.py — WorldForge v1.6 central taxonomy registry (single source).

One module every v1.6 runtime tool consults for the shared vocabularies: runtime
event types, completion classes, interaction verbs, failure owners, pawn profile
types, route statuses, save/load statuses, plus the mission-archetype→verb map,
encounter profiles, and validation requirements. Where a runtime contract already
owns an enum, this module IMPORTS it rather than restating it, so the taxonomy can
never drift from the contracts that enforce it (mirrors v1_5_taxonomy).

``validate_taxonomy`` is the integrity self-check: no registry may be empty and
no registry may contain duplicate values. Stdlib only.
"""

from pathlib import Path

from failure_codes import FailureCode
from runtime_completion_contract import (
    COMPLETION_CLASSES as _COMPLETION_CLASSES,
    FAILURE_OWNERS as _FAILURE_OWNERS,
    RESULT_STATUS as _RESULT_STATUS,
)
from runtime_interaction_contract import (
    INTERACTION_VERBS as _INTERACTION_VERBS,
    MISSION_ARCHETYPE_VERBS as _MISSION_ARCHETYPE_VERBS,
)
from runtime_pawn_contract import PAWN_PROFILE_TYPES as _PAWN_PROFILE_TYPES
from runtime_route_contract import ROUTE_STATUS as _ROUTE_STATUS
from runtime_save_load_contract import SAVE_LOAD_STATUS as _SAVE_LOAD_STATUS
from runtime_scenario_contract import (
    ENCOUNTER_PROFILES as _ENCOUNTER_PROFILES,
    MISSION_ARCHETYPES as _MISSION_ARCHETYPES,
    VALIDATION_REQUIREMENTS as _VALIDATION_REQUIREMENTS,
)
from runtime_telemetry_contract import RUNTIME_EVENT_TYPES as _RUNTIME_EVENT_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "1.6"

# --- imported registries (owned by the runtime contracts) --------------------
RUNTIME_EVENT_TYPES = _RUNTIME_EVENT_TYPES         # runtime_telemetry_contract
COMPLETION_CLASSES = _COMPLETION_CLASSES           # runtime_completion_contract
RUNTIME_FAILURE_OWNERS = _FAILURE_OWNERS           # runtime_completion_contract
RESULT_STATUS = _RESULT_STATUS                     # runtime_completion_contract
INTERACTION_VERBS = _INTERACTION_VERBS             # runtime_interaction_contract
MISSION_ARCHETYPE_VERBS = _MISSION_ARCHETYPE_VERBS  # runtime_interaction_contract
PAWN_PROFILE_TYPES = _PAWN_PROFILE_TYPES           # runtime_pawn_contract
ROUTE_STATUS = _ROUTE_STATUS                       # runtime_route_contract
SAVE_LOAD_STATUS = _SAVE_LOAD_STATUS               # runtime_save_load_contract
ENCOUNTER_PROFILES = _ENCOUNTER_PROFILES           # runtime_scenario_contract
MISSION_ARCHETYPES = _MISSION_ARCHETYPES           # runtime_scenario_contract
VALIDATION_REQUIREMENTS = _VALIDATION_REQUIREMENTS  # runtime_scenario_contract

# Registry-name -> tuple. The single lookup surface for is_known / validate.
REGISTRIES = {
    "RUNTIME_EVENT_TYPES": RUNTIME_EVENT_TYPES,
    "COMPLETION_CLASSES": COMPLETION_CLASSES,
    "RUNTIME_FAILURE_OWNERS": RUNTIME_FAILURE_OWNERS,
    "RESULT_STATUS": RESULT_STATUS,
    "INTERACTION_VERBS": INTERACTION_VERBS,
    "PAWN_PROFILE_TYPES": PAWN_PROFILE_TYPES,
    "ROUTE_STATUS": ROUTE_STATUS,
    "SAVE_LOAD_STATUS": SAVE_LOAD_STATUS,
    "ENCOUNTER_PROFILES": ENCOUNTER_PROFILES,
    "MISSION_ARCHETYPES": MISSION_ARCHETYPES,
    "VALIDATION_REQUIREMENTS": VALIDATION_REQUIREMENTS,
}


def is_known(registry_name, value):
    """True if ``value`` is a member of the named registry (False for unknowns)."""
    return value in REGISTRIES.get(registry_name, ())


def validate_taxonomy():
    """Integrity self-check over every registry plus cross-contract coherence.

    Returns a list of ``(check_name, ok, detail, failure_code)`` tuples.
    """
    C = FailureCode
    checks = []
    for name, values in REGISTRIES.items():
        checks.append((
            "{}_non_empty".format(name), bool(values),
            "registry {} is empty".format(name) if not values
            else "{} has {} entries".format(name, len(values)),
            C.V1_6_TAXONOMY_FAILURE,
        ))
        seen = set()
        dupes = sorted({v for v in values if v in seen or seen.add(v)})
        checks.append((
            "{}_no_duplicates".format(name), not dupes,
            "registry {} has duplicate values: {}".format(name, dupes) if dupes
            else "{} has no duplicates".format(name),
            C.V1_6_TAXONOMY_FAILURE,
        ))
    # Cross-contract coherence: every archetype maps to a supported verb.
    verbs_ok = set(MISSION_ARCHETYPE_VERBS.values()) <= set(INTERACTION_VERBS)
    checks.append(("archetype_verbs_supported", verbs_ok,
                   "every mission archetype maps to a supported interaction verb"
                   if verbs_ok else "archetype→verb map references unsupported verb",
                   C.V1_6_TAXONOMY_FAILURE))
    # Each archetype has a verb.
    all_mapped = set(MISSION_ARCHETYPES) == set(MISSION_ARCHETYPE_VERBS.keys())
    checks.append(("all_archetypes_mapped", all_mapped,
                   "every mission archetype has a verb mapping" if all_mapped
                   else "archetype↔verb map mismatch", C.V1_6_TAXONOMY_FAILURE))
    # Success class must be present exactly once.
    checks.append(("completion_has_success_class", "completed_runtime" in COMPLETION_CLASSES,
                   "completion classes include completed_runtime",
                   C.V1_6_TAXONOMY_FAILURE))
    return checks


if __name__ == "__main__":
    results = validate_taxonomy()
    failing = [c for c in results if not c[1]]
    assert not failing, "self-check failed: {}".format(failing)
    print("OK v1_6_taxonomy self-check: {} checks, 0 failing "
          "({} registries)".format(len(results), len(REGISTRIES)))
