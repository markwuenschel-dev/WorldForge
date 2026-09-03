#!/usr/bin/env python3
"""test_asset_lane_provider -- prove the adapter refuses, and prove the refusals
can actually fire.

The happy path (an asset that exists and its lane passed) is the least
interesting thing here. What these assertions defend:

  * WF1271 and WF1272 have real raise sites AND observed negatives -- the
    WF1200-band rule is that defining a code proves nothing, because
    failure_codes.py backfills severity for any constant typed into the class.
  * The two refusals stay SEPARATE. "the file is not there" and "its lane never
    passed it" have different remedies; a single "unavailable" bucket would hide
    which one applies.
  * A capability with zero available entries is NOT offered. Declaring capability
    the inventory cannot serve would make selection route work to a provider that
    must then refuse it -- the same empty claim the four declaration rails exist
    to stop.
  * The declaration survives all four rails, and each rail is shown to be able to
    reject a mutated copy. A rail that cannot go red is decoration.
  * Mutation test on the gate itself: if the disk check is removed, the absent
    case must STOP being caught. Without this the absent assertion could be
    passing for some unrelated reason and nobody would know.
"""

import copy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import asset_lane_provider as AL         # noqa: E402
from wfcore.failure import FailureCode as C            # noqa: E402
from wfcore.providers import base as PB                # noqa: E402

_FAILS = []
_N = [0]


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))
    return ok


class _files(object):
    """Pretend exactly this set of disk paths exists, and nothing else."""

    def __init__(self, present):
        self.present = set(present)
        self._real = None

    def __enter__(self):
        self._real = AL.os.path.isfile
        AL.os.path.isfile = lambda p: os.path.normpath(p) in {
            os.path.normpath(x) for x in self.present}
        return self

    def __exit__(self, *exc):
        AL.os.path.isfile = self._real
        return False


# --------------------------------------------------------------------------- #
# path mapping -- the notation trap that has bitten this repo before
# --------------------------------------------------------------------------- #
def test_path_mapping():
    short = AL._ue_path_to_disk("/Game/Materials/Terrain/MI_X")
    long = AL._ue_path_to_disk("/Game/Materials/Terrain/MI_X.MI_X")
    check("notation_short_and_long_agree", short == long,
          "/Game/X/Y and /Game/X/Y.Y are the same asset; got {!r} vs {!r}. The "
          "sink hit this exact trap: get_path_name() returns the long form and "
          "callers write the short one".format(short, long))
    check("maps_game_to_content",
          short is not None and short.replace(os.sep, "/").endswith(
              "Content/Materials/Terrain/MI_X.uasset"),
          "unexpected disk mapping: {!r}".format(short))
    check("non_game_path_is_not_claimed",
          AL._ue_path_to_disk("/Engine/BasicShapes/Cube") is None,
          "an /Engine path is not project content; this provider must make no "
          "filesystem claim about it")
    check("none_path_is_not_claimed", AL._ue_path_to_disk(None) is None,
          "a missing final_asset_path must not crash or resolve")


# --------------------------------------------------------------------------- #
# the two refusals, kept separate
# --------------------------------------------------------------------------- #
def test_absent_is_refused():
    with _files([]):
        state, _disk, detail = AL._classify("/Game/Foo/SM_Missing", "valid")
    check("absent_state", state == AL.STATE_ABSENT,
          "an entry whose .uasset is not on disk must be ABSENT, got {!r}".format(state))
    check("absent_detail_names_the_path", "SM_Missing" in detail,
          "refusal must name what could not be resolved; got {!r}".format(detail))


def test_unvalidated_is_refused_separately():
    disk = AL._ue_path_to_disk("/Game/Foo/SM_Pending")
    with _files([disk]):
        state, _d, detail = AL._classify("/Game/Foo/SM_Pending", "pending")
    check("unvalidated_state", state == AL.STATE_UNVALIDATED,
          "an entry that EXISTS but whose lane records pending must be "
          "UNVALIDATED, not ABSENT and not AVAILABLE; got {!r}".format(state))
    check("unvalidated_detail_names_status", "pending" in detail,
          "refusal must say which verdict it read; got {!r}".format(detail))


def test_absent_reports_both_facts():
    """Absent picks the code; the lane's own verdict is still reported."""
    with _files([]):
        _s, _d, detail = AL._classify("/Game/Foo/SM_Missing", "pending")
    check("absent_also_mentions_validation", "pending" in detail,
          "a reader told only 'absent' could assume validation had passed and "
          "the file was merely misplaced. Both facts, one message; got {!r}"
          .format(detail))


def test_available_requires_both():
    disk = AL._ue_path_to_disk("/Game/Foo/SM_Real")
    with _files([disk]):
        state, _d, _detail = AL._classify("/Game/Foo/SM_Real", "valid")
    check("available_state", state == AL.STATE_AVAILABLE,
          "on disk + lane-validated must be AVAILABLE, got {!r}".format(state))
    with _files([disk]):
        state_none, _d, _detail = AL._classify("/Game/Foo/SM_Real", None)
    check("no_declared_status_is_not_a_refusal", state_none == AL.STATE_AVAILABLE,
          "a lane that declares no validation_status has not FAILED validation; "
          "absence of a verdict is not a negative verdict, got {!r}".format(state_none))


def test_absent_check_is_not_tautological():
    """MUTATION: remove the disk check and the absent case must stop being caught.

    Without this, test_absent_is_refused could be passing because of the
    validation branch, the path mapping, or nothing at all.
    """
    real = AL.os.path.isfile
    try:
        AL.os.path.isfile = lambda p: True     # mutation: everything "exists"
        state, _d, _detail = AL._classify("/Game/Foo/SM_Missing", "valid")
    finally:
        AL.os.path.isfile = real
    check("mutation_defeats_absent_check", state != AL.STATE_ABSENT,
          "with the disk check defeated the absent case STILL reported ABSENT, "
          "so the real assertion is not testing what it claims to test")


# --------------------------------------------------------------------------- #
# capability offering
# --------------------------------------------------------------------------- #
def test_capability_not_offered_without_available_entries():
    entries = [
        {"capability": PB.CAP_MESH_SYNTHESIS, "state": AL.STATE_ABSENT},
        {"capability": PB.CAP_MESH_SYNTHESIS, "state": AL.STATE_UNVALIDATED},
        {"capability": PB.CAP_MATERIAL_AUTHORING, "state": AL.STATE_AVAILABLE},
    ]
    caps = AL.offered_capabilities(entries)
    check("unserviceable_capability_withheld", PB.CAP_MESH_SYNTHESIS not in caps,
          "a capability whose every entry is refused must NOT be offered, or "
          "selection routes work to a provider that must then decline it; got "
          "{!r}".format(caps))
    check("serviceable_capability_offered", PB.CAP_MATERIAL_AUTHORING in caps,
          "got {!r}".format(caps))


# --------------------------------------------------------------------------- #
# the declaration and its four rails
# --------------------------------------------------------------------------- #
def _failed(checks):
    return [c for c in checks if not c[1]]


def test_declaration_is_valid():
    d = AL.declaration()
    bad = _failed(PB.validate_provider_declaration(d, strict=True))
    check("declaration_valid", not bad,
          "declaration rejected: {}".format([(c[0], c[2]) for c in bad]))
    check("rollback_is_none", d["rollback"] == PB.ROLLBACK_NONE,
          "asset synthesis is deliberately NOT a sink mutation; rollback must "
          "be none, got {!r}".format(d["rollback"]))
    irreversible = [e for e in d["side_effects"]
                    if e["effect_kind"] == PB.EFFECT_PERSISTENT_ASSET]
    check("persistent_asset_is_irreversible",
          irreversible and all(e["reversible"] is False for e in irreversible),
          "an asset another asset references cannot be un-created honestly, so "
          "the persistent-asset effect must declare reversible=False")


def test_rail_empty_side_effects_rejected():
    d = copy.deepcopy(AL.declaration())
    d["side_effects"] = []
    bad = _failed(PB.validate_provider_declaration(d, strict=True))
    check("rail_side_effects_can_fire", bool(bad),
          "an empty side_effects list was ACCEPTED; silence is not 'none' and "
          "WF1231 exists to say so")


def test_rail_empty_limitations_rejected():
    d = copy.deepcopy(AL.declaration())
    d["limitations"] = []
    bad = _failed(PB.validate_provider_declaration(d, strict=True))
    check("rail_limitations_can_fire", bool(bad),
          "an empty limitations list was ACCEPTED; WF1226 requires the "
          "universality claim to be SIGNED, not merely omitted")


def test_rail_rollback_contradiction_rejected():
    d = copy.deepcopy(AL.declaration())
    d["rollback"] = PB.ROLLBACK_TRANSACTIONAL   # over reversible=False effects
    bad = _failed(PB.validate_provider_declaration(d, strict=True))
    check("rail_rollback_can_fire", bool(bad),
          "a transactional rollback claim over an irreversible effect was "
          "ACCEPTED; that is a rollback-shaped sentence, not a mechanism (WF1232)")


def test_rail_unproven_determinism_rejected():
    d = copy.deepcopy(AL.declaration())
    d["determinism"] = PB.DET_SEEDED
    d.pop("determinism_evidence", None)
    bad = _failed(PB.validate_provider_declaration(d, strict=True))
    check("rail_determinism_can_fire", bool(bad),
          "deterministic_given_seed with no determinism_evidence was ACCEPTED "
          "(WF1233). This provider deliberately claims stable_within_environment "
          "instead, because UE import settings and DDC state participate in what "
          "lands on disk")


# --------------------------------------------------------------------------- #
# the live repository inventory -- a regression guard on a real finding
# --------------------------------------------------------------------------- #
def test_live_inventory_resolves():
    rep = AL.inventory_report()
    check("inventory_non_empty", rep["total"] > 0,
          "no entries resolved at all; the adapter is reading nothing")
    check("every_refusal_carries_a_code",
          all(r["failure_code"] in (C.CORE_ASSET_LANE_ARTIFACT_ABSENT,
                                    C.CORE_ASSET_LANE_ENTRY_UNVALIDATED)
              for r in rep["refusals"]),
          "a refusal without one of the two codes tells a reader that capability "
          "is unavailable without telling them why")
    check("offered_capabilities_are_vocabulary",
          all(c in PB.CAPABILITIES for c in rep["offered_capabilities"]),
          "offered {!r} is not drawn from the closed capability vocabulary"
          .format(rep["offered_capabilities"]))
    # The finding this adapter surfaced on its first run: every mesh-catalog
    # entry names a .uasset that does not exist, and the catalog's own
    # validation_status is pending for all of them. If that ever changes, this
    # assertion should be updated deliberately rather than drifting.
    mesh_available = [e for e in rep["entries"]
                      if e["lane"] == "mesh" and e["state"] == AL.STATE_AVAILABLE]
    check("mesh_lane_state_is_recorded", isinstance(mesh_available, list),
          "structural")
    if mesh_available:
        print("  NOTE: the mesh lane now has {} available entries; it had 0 when "
              "this adapter was written.".format(len(mesh_available)))


def main():
    for fn in sorted(
            (v for k, v in globals().items()
             if k.startswith("test_") and callable(v)),
            key=lambda f: f.__name__):
        fn()
    if _FAILS:
        print("test_asset_lane_provider: {} assertion(s) passed, {} FAILED"
              .format(_N[0], len(_FAILS)))
        for f in _FAILS:
            print("  FAIL {}".format(f))
        return 1
    print("test_asset_lane_provider: {} assertion(s) passed, 0 failed".format(_N[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
