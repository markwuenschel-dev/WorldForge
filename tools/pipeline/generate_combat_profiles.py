#!/usr/bin/env python3
"""generate_combat_profiles.py — WorldForge v1.8 CombatForge Alpha profile generator.

Layers real runtime *combat* semantics onto the v1.7 NPC *behavior* substrate:
reads every v1.7 BehaviorProfile under ``procedural/generated/npc/behavior_profiles/``
and derives one CombatProfile per behavior profile. The derivation is REAL, not a
copy — the profile's ``profile_kind`` selects the damage source (hazard profiles
produce ``hazard`` damage, everything else produces ``npc_pressure``; the
``hazard_field`` archetype produces both), the damage_type, per-tick amounts, and a
deterministic ``baseline_expected_damage`` (strictly < player_max_health so the
baseline stays winnable). Each derived profile is validated against
``combat_contracts.validate_combat_profile(p, strict=True)`` with zero failures
BEFORE it is written — a generator that emits a record its own contract rejects is
a bug, and such records are skipped and reported, never written.

Every CombatProfile references the ``behavior_profile_id`` it layered on, so the
combat substrate is auditable back to the v1.7 behavior spine.

Acceptance: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_combat_profiles.py --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CC
from npc_gen_common import run_generator
from report_meta import build_meta, strict_from_env
from failure_codes import FailureCode

BEHAVIOR_PROFILE_GENERATED_REL = "procedural/generated/npc/behavior_profiles"
CREATED_BY = "worldforge.v1.8"
CREATED_AT = "2026-07-09T00:00:00+00:00"

# Per behavior profile_kind: the damage source, the damage_type it deals, the
# per-tick amount, and the deterministic baseline damage a full run under standard
# pressure is expected to inflict. Every baseline is in [25, 60] and < 100 (the
# fixed player_max_health) so the baseline stays winnable. Derived from the v1.7
# pressure models: a proximity_pressure kind becomes proximity_tick damage, etc.
KIND_DAMAGE = {
    "guard_pressure":   dict(source="npc_pressure", damage_type="proximity_tick",
                             tick=4.0, interval=0.5, requires_los=False, baseline=35.0),
    "patrol_pressure":  dict(source="npc_pressure", damage_type="proximity_tick",
                             tick=3.0, interval=0.6, requires_los=False, baseline=30.0),
    "ranged_pressure":  dict(source="npc_pressure", damage_type="ranged_tick",
                             tick=6.0, interval=1.0, requires_los=True, baseline=40.0),
    "ambush_pressure":  dict(source="npc_pressure", damage_type="contact",
                             tick=9.0, interval=1.5, requires_los=False, baseline=45.0),
    "hazard_pressure":  dict(source="hazard", damage_type="hazard_zone",
                             tick=5.0, interval=0.5, requires_los=False, baseline=50.0),
}

PLAYER_MAX_HEALTH = 100.0


def _combat_profile_id(behavior_profile_id):
    """Derive a stable combat_profile_id from the behavior profile id.

    The v1.7 ids are prefixed ``bp_`` (behavior profile); the combat analog is
    ``cp_`` (combat profile), keeping the archetype/kind suffix intact so the two
    substrates line up one-to-one and remain auditable.
    """
    if behavior_profile_id.startswith("bp_"):
        return "cp_" + behavior_profile_id[len("bp_"):]
    return "cp_" + behavior_profile_id


def build_profile(bp):
    """Derive a real CombatProfile dict from a v1.7 BehaviorProfile dict."""
    bpid = bp["behavior_profile_id"]
    kind = bp.get("profile_kind", "guard_pressure")
    archetype = bp["encounter_archetype"]
    km = KIND_DAMAGE.get(kind, KIND_DAMAGE["guard_pressure"])

    # Damage sources: hazard kinds -> hazard; everything else -> npc_pressure. The
    # hazard_field archetype is the mixed case — NPC wardens patrol a hazard zone,
    # so it produces BOTH real damage sources.
    npc_rules = {}
    hazard_rules = {}
    if km["source"] == "hazard":
        damage_sources = ["hazard"]
        hazard_rules = {"damage_type": km["damage_type"], "zone_tick": km["tick"],
                        "tick_interval_seconds": km["interval"], "requires_los": km["requires_los"]}
    else:
        damage_sources = ["npc_pressure"]
        npc_rules = {"damage_type": km["damage_type"], "proximity_tick": km["tick"],
                     "tick_interval_seconds": km["interval"], "requires_los": km["requires_los"]}
    if archetype == "hazard_field" and "hazard" not in damage_sources:
        damage_sources.append("hazard")
        hazard_rules = hazard_rules or {"damage_type": "hazard_zone", "zone_tick": 5.0,
                                        "tick_interval_seconds": 0.5, "requires_los": False}
    elif archetype == "hazard_field" and "npc_pressure" not in damage_sources:
        # hazard_field with hazard source also fields patrolling NPC pressure.
        damage_sources.append("npc_pressure")
        npc_rules = npc_rules or {"damage_type": "proximity_tick", "proximity_tick": 3.0,
                                  "tick_interval_seconds": 0.6, "requires_los": False}

    baseline = km["baseline"]

    profile = {
        "combat_profile_id": _combat_profile_id(bpid),
        "encounter_archetype": archetype,
        "pressure_profile": bp.get("pressure_profile", "standard_pressure"),
        "behavior_profile_id": bpid,
        "player_max_health": PLAYER_MAX_HEALTH,
        "damage_sources": damage_sources,
        "npc_damage_rules": npc_rules,
        "hazard_damage_rules": hazard_rules,
        "baseline_expected_damage": baseline,
        "survivability_policy": {
            "min_final_health": 1.0,
            "max_final_health": PLAYER_MAX_HEALTH - baseline * 0.5,
            "blocking_bands": list(CC.BLOCKING_SURVIVABILITY_BANDS),
        },
        "mission_completion_policy": "must_remain_possible_under_baseline",
        "save_load_policy": {"persist": ["current_health", "damage_taken_total",
                                         "damage_events_count"]},
        "telemetry_requirements": ["combat.player.damage.taken", "combat.player.health.changed",
                                   "combat.player.health.initialized"],
        "balance_requirements": ["baseline_winnable", "damage_events_seen",
                                 "survivable_band"],
        "created_by": CREATED_BY,
        "created_at": CREATED_AT,
        "schema_version": CC.COMBAT_PROFILE_SCHEMA_VERSION,
        "report_type": CC.RT_COMBAT_PROFILE,
    }
    profile["meta"] = build_meta(
        command="generate-combat-profiles", pack=None, strict=True,
        status="ok", record_count=1, report_type=CC.RT_COMBAT_PROFILE,
        report_id_suffix=profile["combat_profile_id"], records_total=1, records_passed=1)
    return profile


def _load_behavior_profiles():
    d = REPO_ROOT / BEHAVIOR_PROFILE_GENERATED_REL
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    behavior_profiles = _load_behavior_profiles()

    # Derive a combat profile per behavior profile, keeping only those that pass
    # the strict contract with zero failures (skip + report any that can't be made
    # valid — never write an invalid record).
    profiles = []
    skipped = []
    for bp in behavior_profiles:
        cp = build_profile(bp)
        fails = [c for c in CC.validate_combat_profile(cp, strict=True) if not c[1]]
        if fails:
            skipped.append((cp.get("combat_profile_id", "?"), [c[0] for c in fails][:4]))
            continue
        profiles.append(cp)

    extra = [
        ("combat_profiles::behavior_source_present", len(behavior_profiles) > 0,
         "no v1.7 behavior profiles found under {} (run generate-npc-behavior-profiles)".format(
             BEHAVIOR_PROFILE_GENERATED_REL),
         FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE),
        ("combat_profiles::none_skipped", not skipped,
         "combat profiles failed their own contract and were skipped: {}".format(skipped),
         FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE),
        ("combat_profiles::one_per_behavior", len(profiles) == len(behavior_profiles),
         "derived {} combat profiles from {} behavior profiles".format(
             len(profiles), len(behavior_profiles)),
         FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE),
    ]

    if skipped:
        for sid, names in skipped:
            print("[generate-combat-profiles] SKIPPED invalid profile {}: {}".format(sid, names))

    run_generator("generate-combat-profiles", args.pack, profiles,
                  CC.validate_combat_profile, CC.COMBAT_PROFILE_GENERATED_REL,
                  "combat_profile_id", "procedural/reports/combat/profiles",
                  "generate_combat_profiles_report.json", CC.RT_COMBAT_PROFILE,
                  FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE, strict=strict, extra_checks=extra)


if __name__ == "__main__":
    main()
