#!/usr/bin/env python3
"""runtime_save_load_contract.py — WorldForge v1.6 RuntimeSaveLoadProof.

A mission is not runtime-complete unless completion survives a save/reload. This
module owns SAVE_LOAD_STATUS and the proof schema: the expected state keys, the
keys actually verified after reload, and any missing/mismatched keys. A proof may
only be ``verified`` when every expected key is verified and none are missing or
mismatched — a proof that claims success with an empty state diff is exactly the
fake-green case the brief calls out, and is rejected here.
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "wf.runtime.save_load_proof.v1"

SAVE_LOAD_GENERATED_REL = "procedural/generated/runtime/save_load"
SAVE_LOAD_REPORTS_REL = "procedural/reports/runtime/save_load"

SAVE_LOAD_STATUS = ("verified", "save_failed", "load_failed", "mismatch",
                    "missing", "skipped")

VERIFIED = "verified"

REQUIRED_FIELDS = (
    "proof_id",
    "runtime_scenario_id",
    "save_file_path",
    "pre_save_state",
    "post_load_state",
    "expected_state_keys",
    "verified_state_keys",
    "missing_state_keys",
    "mismatched_state_keys",
    "status",
    "failure_code",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + ("schema_version", "created_at", "meta")


def validate_save_load_proof(obj, strict=False):
    """Return check tuples for one save/load proof, enforcing that a `verified`
    status is backed by a real, complete state diff."""
    C = FailureCode
    checks = []
    checks += RS.check_required(obj, REQUIRED_FIELDS, C.RUNTIME_SAVE_LOAD_SCHEMA_FAILURE,
                                nullable=("failure_code",))
    checks += RS.check_no_unknown(obj, ALLOWED_FIELDS, C.RUNTIME_SAVE_LOAD_SCHEMA_FAILURE, strict)
    checks += RS.check_enum(obj, "status", SAVE_LOAD_STATUS, C.RUNTIME_SAVE_LOAD_SCHEMA_FAILURE)

    status = obj.get("status") if isinstance(obj, dict) else None
    expected = obj.get("expected_state_keys") if isinstance(obj, dict) else None
    verified = obj.get("verified_state_keys") if isinstance(obj, dict) else None
    missing = obj.get("missing_state_keys") if isinstance(obj, dict) else None
    mismatched = obj.get("mismatched_state_keys") if isinstance(obj, dict) else None

    if status == VERIFIED:
        # Coerce non-list values to empty sets rather than crashing on hostile
        # input (a corrupted float/dict here must be REJECTED, not raise).
        exp = set(expected) if isinstance(expected, list) else set()
        ver = set(verified) if isinstance(verified, list) else set()
        checks.append(("save_load::has_expected_keys", len(exp) > 0,
                       "verified proof must declare >=1 expected state key (no empty-diff success)",
                       C.RUNTIME_SAVE_STATE_MISSING))
        checks.append(("save_load::all_expected_verified", exp and exp <= ver,
                       "verified proof must verify every expected key (expected={}, verified={})".format(
                           sorted(exp), sorted(ver)),
                       C.RUNTIME_POST_LOAD_STATE_MISMATCH))
        checks.append(("save_load::none_missing", not (missing or []),
                       "verified proof has missing keys {}".format(missing),
                       C.RUNTIME_COMPLETION_NOT_PERSISTED))
        checks.append(("save_load::none_mismatched", not (mismatched or []),
                       "verified proof has mismatched keys {}".format(mismatched),
                       C.RUNTIME_POST_LOAD_STATE_MISMATCH))
        checks.append(("save_load::has_save_file", bool(obj.get("save_file_path")),
                       "verified proof must reference a save file",
                       C.RUNTIME_SAVE_FILE_MISSING))
    else:
        checks.append(("save_load::failure_has_code", bool(obj.get("failure_code")),
                       "non-verified status {!r} must carry a failure_code".format(status),
                       C.RUNTIME_SAVE_LOAD_SCHEMA_FAILURE))
    return checks


def _valid_verified():
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_id": "rt_demo:save_load",
        "runtime_scenario_id": "rt_demo",
        "save_file_path": "Saved/SaveGames/wf_runtime_rt_demo.sav",
        "pre_save_state": {"mission.disable_site.completed": True},
        "post_load_state": {"mission.disable_site.completed": True},
        "expected_state_keys": ["mission.disable_site.completed"],
        "verified_state_keys": ["mission.disable_site.completed"],
        "missing_state_keys": [],
        "mismatched_state_keys": [],
        "status": "verified",
        "failure_code": None,
    }


if __name__ == "__main__":
    ok = [c for c in validate_save_load_proof(_valid_verified(), strict=True) if not c[1]]
    assert not ok, "valid proof failed: {}".format(ok)
    # An empty-diff "verified" proof must be rejected.
    empty = _valid_verified()
    empty["expected_state_keys"] = []
    empty["verified_state_keys"] = []
    fails = [c for c in validate_save_load_proof(empty, strict=True) if not c[1]]
    assert any("expected_keys" in c[0] for c in fails), "empty-diff success not caught"
    # Load restoring pre-completion state (missing key) must be rejected.
    lost = _valid_verified()
    lost["missing_state_keys"] = ["mission.disable_site.completed"]
    fails2 = [c for c in validate_save_load_proof(lost, strict=True) if not c[1]]
    assert any("missing" in c[0] for c in fails2), "lost completion not caught"
    print("OK runtime_save_load_contract self-check: {} statuses, "
          "empty-diff + lost-completion rejected".format(len(SAVE_LOAD_STATUS)))
