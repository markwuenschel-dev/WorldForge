#!/usr/bin/env python3
"""quest_faction_spec.py — v2.2 shared authoring spec (one source of truth).

Both generators (generate_quests.py, generate_factions.py) and the authoring
validators import this so quests and factions agree on the roster, the archetype ->
faction mapping, and the bounded delta rules. Keeping it here (not duplicated in
each generator) is what stops a quest from requesting a faction the roster never
defines, or a delta rule from citing an unknown target.

Deterministic + bounded: no wall-clock, no randomness. Every delta stays within the
per-facet caps declared in quest_faction_contracts (asserted by the validators).
"""

import quest_faction_contracts as QF

# The 4-faction roster (handoff §7). Abstract, substrate-focused — bounded state
# vectors, not lore. class/risk/tags feed FactionDefinition; preferred/opposed are
# disjoint (a faction can't both want and oppose an archetype).
FACTION_ROSTER = [
    {
        "faction_id": "wardens",
        "display_key": "faction.wardens",
        "faction_class": "protector",
        "preferred_quest_archetypes": ["HazardClearance", "StabilizeRoute"],
        "opposed_quest_archetypes": [],
        "risk_profile": "measured",
        "territory_tags": ["alpine_snow", "volcanic_ashlands"],
        "resource_tags": ["ward_beacon", "shelter_kit"],
        "hazard_tags": ["rockfall", "ashfall", "exposure"],
        "hazard_sensitivity": 0.7,
    },
    {
        "faction_id": "surveyors",
        "display_key": "faction.surveyors",
        "faction_class": "explorer",
        "preferred_quest_archetypes": ["Survey"],
        "opposed_quest_archetypes": ["HazardClearance"],
        "risk_profile": "averse",
        "territory_tags": ["alpine_snow", "volcanic_ashlands"],
        "resource_tags": ["survey_data", "landmark_scan"],
        "hazard_tags": ["exposure", "whiteout"],
        "hazard_sensitivity": 0.9,
    },
    {
        "faction_id": "salvagers",
        "display_key": "faction.salvagers",
        "faction_class": "extractor",
        "preferred_quest_archetypes": ["Recovery"],
        "opposed_quest_archetypes": ["StabilizeRoute"],
        "risk_profile": "bold",
        "territory_tags": ["volcanic_ashlands"],
        "resource_tags": ["salvage", "ore", "relic"],
        "hazard_tags": ["ashfall", "heat"],
        "hazard_sensitivity": 0.3,
    },
    {
        "faction_id": "outriders",
        "display_key": "faction.outriders",
        "faction_class": "stabilizer",
        "preferred_quest_archetypes": ["StabilizeRoute", "HazardClearance"],
        "opposed_quest_archetypes": [],
        "risk_profile": "measured",
        "territory_tags": ["alpine_snow", "volcanic_ashlands"],
        "resource_tags": ["route_marker", "supply_cache"],
        "hazard_tags": ["rockfall", "washout"],
        "hazard_sensitivity": 0.5,
    },
]
FACTION_IDS = tuple(f["faction_id"] for f in FACTION_ROSTER)

# v2.0 mission_archetype -> v2.2 quest archetype (handoff §6).
MISSION_TO_QUEST_ARCHETYPE = {
    "survey_landmark": "Survey",
    "recover_resource": "Recovery",
    "clear_hazard": "HazardClearance",
}

# Which faction requests each archetype, and which are affected (bounded <= 4).
ARCHETYPE_FACTIONS = {
    "Survey": {"requesting": "surveyors", "affected": ["wardens", "salvagers"]},
    "Recovery": {"requesting": "salvagers", "affected": ["outriders", "wardens"]},
    "HazardClearance": {"requesting": "wardens", "affected": ["outriders", "surveyors"]},
}

# The archetype-specific action step (step 2). Step 1 is always reach_objective and
# the final step is always extract_reward; "high" pressure adds an optional
# survive_pressure step.
ARCHETYPE_ACTION = {
    "Survey": ("survey_landmark", "objective", "surveyed"),
    "Recovery": ("recover_resource", "objective", "recovered"),
    "HazardClearance": ("clear_hazard", "combat", "cleared"),
}

# Reason code per archetype (bounded vocabulary).
ARCHETYPE_REASON = {
    "Survey": "resource_recovered",
    "Recovery": "resource_recovered",
    "HazardClearance": "hazard_cleared",
}

# Resource a successful archetype yields to a benefiting faction.
ARCHETYPE_RESOURCE = {
    "Survey": "survey_data",
    "Recovery": "salvage",
    "HazardClearance": "ward_beacon",
}


def _opposed(faction_id, archetype):
    for f in FACTION_ROSTER:
        if f["faction_id"] == faction_id:
            return archetype in f["opposed_quest_archetypes"]
    return False


def delta_rules_for(archetype):
    """Bounded per-faction delta rules for a quest of this archetype.

    Returns a list of rule dicts keyed by (target_faction_id, on_outcome). The
    requesting + benefiting factions gain standing/trust on success; a faction that
    OPPOSES the archetype loses standing/trust and gains alarm. On failure the
    requesting faction takes a mild standing/trust hit. Every magnitude stays within
    the caps in quest_faction_contracts. The runtime scales partial_success to half.
    """
    fac = ARCHETYPE_FACTIONS[archetype]
    targets = [fac["requesting"]] + fac["affected"]
    res_tag = ARCHETYPE_RESOURCE[archetype]
    rules = []
    for i, tid in enumerate(targets):
        harmed = _opposed(tid, archetype)
        requesting = (tid == fac["requesting"])
        if harmed:
            success = {
                "standing_delta": -8, "influence_delta": -2, "trust_delta": -6,
                "alarm_delta": 10, "resources_delta": {},
                "relationship_deltas": {fac["requesting"]: -5},
                "reason_code": "rival_setback",
            }
        else:
            base = 12 if requesting else 6
            success = {
                "standing_delta": base, "influence_delta": 5 if requesting else 3,
                "trust_delta": base - 2, "alarm_delta": -2,
                "resources_delta": {res_tag: 15 if requesting else 6},
                "relationship_deltas": ({fac["requesting"]: 4} if not requesting else {}),
                "reason_code": ARCHETYPE_REASON[archetype] if requesting else "ally_boosted",
            }
        rules.append(dict(target_faction_id=tid, on_outcome="success", **success))
        # failure rule: requesting faction takes a mild hit; others unmoved-ish.
        if requesting:
            rules.append(dict(
                target_faction_id=tid, on_outcome="failure",
                standing_delta=-6, influence_delta=-3, trust_delta=-5, alarm_delta=6,
                resources_delta={}, relationship_deltas={},
                reason_code="quest_failure"))
    return rules
