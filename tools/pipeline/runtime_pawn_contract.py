#!/usr/bin/env python3
"""runtime_pawn_contract.py — WorldForge v1.6 RuntimePawnProfile.

The pawn profile is the stable body the runtime driver spawns and possesses. Its
dimensions must be reported and reused across maps so traversal results are
comparable, it must have real collision (it cannot phase through blockers), and
it must be possessable and emit telemetry — a profile that can teleport to
objectives or move at zero speed is a fake-green vector and is rejected here.
Owns PAWN_PROFILE_TYPES; the taxonomy imports it here.
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "wf.runtime.pawn_profile.v1"

PAWN_GENERATED_REL = "procedural/generated/runtime/pawns"
PAWN_REPORTS_REL = "procedural/reports/runtime/pawns"

PAWN_PROFILE_TYPES = ("default", "agile", "heavy")

REQUIRED_FIELDS = (
    "pawn_profile_id",
    "pawn_class",
    "movement_mode",
    "capsule_radius",
    "capsule_half_height",
    "max_walk_speed",
    "step_height",
    "slope_limit",
    "jump_allowed",
    "crouch_allowed",
    "interaction_component",
    "camera_component",
    "input_driver",
    "nav_agent_properties",
    "collision_channel",
    "failure_recovery_policy",
    "telemetry_channels",
)

OPTIONAL_FIELDS = ("schema_version", "profile_type", "created_by", "created_at",
                   "can_teleport_to_objective")
ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def validate_pawn_profile(obj, strict=False):
    """Return check tuples for one pawn profile."""
    C = FailureCode
    checks = []
    checks += RS.check_required(obj, REQUIRED_FIELDS, C.RUNTIME_PAWN_SCHEMA_FAILURE)
    checks += RS.check_no_unknown(obj, ALLOWED_FIELDS, C.RUNTIME_PAWN_SCHEMA_FAILURE, strict)
    # Physical body must be real and stable.
    checks += RS.check_positive_number(obj, "capsule_radius", C.RUNTIME_PAWN_PROFILE_FAILURE)
    checks += RS.check_positive_number(obj, "capsule_half_height", C.RUNTIME_PAWN_PROFILE_FAILURE)
    checks += RS.check_positive_number(obj, "max_walk_speed", C.RUNTIME_PAWN_PROFILE_FAILURE)
    checks += RS.check_positive_number(obj, "step_height", C.RUNTIME_PAWN_PROFILE_FAILURE, allow_zero=True)
    checks += RS.check_type(obj, "interaction_component", str, C.RUNTIME_PAWN_PROFILE_FAILURE)
    checks += RS.check_type(obj, "telemetry_channels", list, C.RUNTIME_TELEMETRY_MISSING)

    # A profile that can teleport to objectives is a forbidden fake-green vector.
    teleport = obj.get("can_teleport_to_objective") if isinstance(obj, dict) else None
    checks.append(("pawn::no_objective_teleport", teleport in (None, False),
                   "pawn may not teleport to objectives (can_teleport_to_objective={!r})".format(teleport),
                   C.PLAYTEST_GAMMA_TELEPORT_SUCCESS_FORBIDDEN))
    # Must emit telemetry.
    chans = obj.get("telemetry_channels") if isinstance(obj, dict) else None
    checks.append(("pawn::emits_telemetry", isinstance(chans, list) and len(chans) > 0,
                   "pawn must declare >=1 telemetry channel",
                   C.RUNTIME_TELEMETRY_MISSING))
    # Must declare an interaction component (else it cannot invoke verbs).
    ic = obj.get("interaction_component") if isinstance(obj, dict) else None
    checks.append(("pawn::has_interaction_component", bool(ic),
                   "pawn must declare an interaction component",
                   C.RUNTIME_PAWN_PROFILE_FAILURE))
    return checks


def default_profile():
    """The canonical reusable test pawn (brief pawn_profile_id default)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "pawn_profile_id": "wf_runtime_test_pawn_default",
        "profile_type": "default",
        "pawn_class": "WF_RuntimeTestPawn",
        "movement_mode": "walking",
        "capsule_radius": 34.0,
        "capsule_half_height": 88.0,
        "max_walk_speed": 600.0,
        "step_height": 45.0,
        "slope_limit": 44.0,
        "jump_allowed": True,
        "crouch_allowed": True,
        "interaction_component": "WF_RuntimeInteractionComponent",
        "camera_component": "WF_RuntimeCameraComponent",
        "input_driver": "scripted_route_executor",
        "nav_agent_properties": {"agent_radius": 34.0, "agent_height": 176.0},
        "collision_channel": "Pawn",
        "failure_recovery_policy": "report_and_fail",
        "telemetry_channels": ["movement", "interaction", "state", "save_load"],
        "can_teleport_to_objective": False,
    }


if __name__ == "__main__":
    ok = [c for c in validate_pawn_profile(default_profile(), strict=True) if not c[1]]
    assert not ok, "valid pawn failed: {}".format(ok)
    broken = default_profile()
    broken["max_walk_speed"] = 0                 # cannot move
    broken["can_teleport_to_objective"] = True   # forbidden
    broken["telemetry_channels"] = []            # no telemetry
    fails = [c for c in validate_pawn_profile(broken, strict=True) if not c[1]]
    assert any("teleport" in c[0] for c in fails), "teleport pawn not caught"
    assert any("max_walk_speed" in c[0] for c in fails), "zero-speed pawn not caught"
    print("OK runtime_pawn_contract self-check: default profile passes, "
          "known-bad fails ({} types)".format(len(PAWN_PROFILE_TYPES)))
