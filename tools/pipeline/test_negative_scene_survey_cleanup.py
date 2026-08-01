#!/usr/bin/env python3
"""
test_negative_scene_survey_cleanup.py
Mutation gate for the v2.6 temporary-object cleanup ledger.

WHAT THIS PROVES, AND WHY IT IS NOT A UNIT TEST OF A FUNCTION
-------------------------------------------------------------
`CleanupVerified` has four conjuncts:

    O_1 == O_0   AND   D_1 == D_0   AND   P_1 == P_0
    AND for every x in O_created: destroyed(x) AND NOT present_final(x)

The first three are computed from two snapshots of the world. THEY CANNOT FAIL for
an object that is created AFTER the pre snapshot and destroyed BEFORE the post
snapshot: it is absent from both, so every set comparison agrees and the verdict
comes out True while the operation did in fact mutate the level. The fourth
conjunct is the only one that ranges over objects, and it can only be evaluated
from a ledger that watched the spawn path.

So this file does not assert that a function returns a value. It runs the REAL
producer (`scene_survey_far_side._SpawnLedger`) against a fake editor, takes the
raw bundle it actually emits, feeds that to the REAL consumer
(`scene_survey_evidence.derive`), and then reintroduces each defect the ledger
exists to catch — including one (`destroy_actor` lying) injected at the EDITOR, not
at the data, so the honest producer is the thing being tested.

Every mutant is required to come back NOT-SUCCESS, and the two failure modes are
kept apart, because they mean different things:

    UNKNOWN — the raw evidence cannot answer. A hole in the observation.
    FALSE   — the raw evidence answers, and the answer is that cleanup failed.
              A defect in the world.

A mutant that produced `True` would be a fake green; a mutant that produced the
WRONG one of unknown/false would be a rail reporting a defect in the world that is
really a defect in the pass, or the reverse.

Runnable as a plain script (no pytest needed in CI); pytest-compatible too.

Usage:
    python tools/pipeline/test_negative_scene_survey_cleanup.py
    pytest tools/pipeline/test_negative_scene_survey_cleanup.py
"""

import copy
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FAR_SIDE = REPO_ROOT / "tools" / "bridge" / "scene_survey_far_side.py"

sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
import scene_survey_evidence as SSE  # noqa: E402

UNKNOWN = SSE.UNKNOWN
MAP_PKG = "/Game/Maps/_wf_test_lvl"


# --------------------------------------------------------------------------- #
# A fake editor. Every behaviour here was chosen to match a MEASURED one.
# --------------------------------------------------------------------------- #
class _FakeActor:
    def __init__(self, path):
        self._path = path

    def get_path_name(self):
        return self._path


class _FakePackage:
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class _FakeWorld:
    """The editor state the ledger measures against.

    `destroy_really` is the mutation knob for MUTANT 2. When it is False,
    `destroy_actor` returns True and the actor stays alive — the exact hazard the
    ledger exists for, and the one a `destroy_returned`-only rail cannot see.
    """

    def __init__(self):
        # A transient actor is NEVER returned by get_all_level_actors() — measured
        # on a live UE 5.8 -nullrhi boot (1 -> 1 across a transient spawn, against
        # 234 -> 235 for a non-transient one). `level_actors` therefore never gains
        # the spawned object, which is precisely why enumeration-absence proves
        # nothing and `is_valid` is the channel that decides.
        self.level_actors = [_FakeActor("/Game/Maps/M.M:PersistentLevel.Existing_0")]
        self.alive = set()
        self.dirty_map = []
        self.dirty_content = []
        self.destroy_really = True
        # The other half of the same split. `destroy_returns` is what the CALL
        # reports; `destroy_really` is what happens to the object. They are
        # independent knobs because the two channels are independent measurements,
        # and a rail that consults only one of them survives a mutation of the
        # other — which is exactly how this harness caught its own blind spot.
        self.destroy_returns = True
        self.in_pie = False
        self._n = 0

    def next_path(self):
        self._n += 1
        return "/Game/Maps/M.M:PersistentLevel.WFTemp_{}".format(self._n)


WORLD = _FakeWorld()


class _FakeEditorActorSubsystem:
    def get_all_level_actors(self):
        return list(WORLD.level_actors)

    def spawn_actor_from_class(self, actor_class, location, rotation, transient=False):
        actor = _FakeActor(WORLD.next_path())
        WORLD.alive.add(id(actor))
        if not transient:
            WORLD.level_actors.append(actor)
        return actor

    def destroy_actor(self, actor):
        if WORLD.destroy_really:
            WORLD.alive.discard(id(actor))
        return WORLD.destroy_returns


class _FakeLevelEditorSubsystem:
    def is_in_play_in_editor(self):
        return WORLD.in_pie


class _FakeSystemLibrary:
    @staticmethod
    def is_valid(obj):
        return id(obj) in WORLD.alive

    @staticmethod
    def quit_editor():
        return None


class _FakeLoadSave:
    @staticmethod
    def get_dirty_map_packages():
        return [_FakePackage(n) for n in WORLD.dirty_map]

    @staticmethod
    def get_dirty_content_packages():
        return [_FakePackage(n) for n in WORLD.dirty_content]


class _FakeVector:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)


class _FakeRotator:
    def __init__(self, pitch, yaw, roll):
        self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)


def _install_fake_unreal():
    u = types.ModuleType("unreal")
    u.EditorActorSubsystem = _FakeEditorActorSubsystem
    u.LevelEditorSubsystem = _FakeLevelEditorSubsystem
    u.SystemLibrary = _FakeSystemLibrary
    u.EditorLoadingAndSavingUtils = _FakeLoadSave
    u.Vector = _FakeVector
    u.Rotator = _FakeRotator
    u.Actor = type("Actor", (), {})
    u.get_editor_subsystem = lambda cls: cls()
    sys.modules["unreal"] = u
    return u


# --------------------------------------------------------------------------- #
# Load the far side WITHOUT running its survey.
# --------------------------------------------------------------------------- #
# The module invokes `main()` at import time (it is an -ExecutePythonScript entry
# point, not a library), so it is exec'd up to that call and no further. The split
# sentinel is asserted to occur exactly once: if the entry point is ever restructured
# this test fails loudly rather than silently testing a truncated module.
_ENTRY_SENTINEL = "\ntry:\n    main()\n"


def load_far_side():
    src = FAR_SIDE.read_text(encoding="utf-8")
    if src.count(_ENTRY_SENTINEL) != 1:
        raise AssertionError(
            "expected exactly one {!r} entry point in {} (found {}) — the loader "
            "below would otherwise exec a module it cannot vouch for".format(
                _ENTRY_SENTINEL, FAR_SIDE, src.count(_ENTRY_SENTINEL)))
    body = src.split(_ENTRY_SENTINEL)[0]
    _install_fake_unreal()
    mod = types.ModuleType("wf_scene_survey_far_side_under_test")
    # A real __file__ so the module's own source introspection
    # (`_spawn_call_sites`) reads the REAL file rather than the truncated string —
    # counting spawn call sites in a truncated copy would measure the test harness.
    mod.__file__ = str(FAR_SIDE)
    sys.modules[mod.__name__] = mod
    exec(compile(body, str(FAR_SIDE), "exec"), mod.__dict__)  # noqa: S102
    return mod


# --------------------------------------------------------------------------- #
# The honest run: create one owned object, clean it up, snapshot both sides.
# --------------------------------------------------------------------------- #
# The 11 fields the ledger contract requires on every owned-object record.
REQUIRED_PLACEMENT_FIELDS = (
    "object_id", "operation_id", "ownership_tag", "creation_observed",
    "creation_stage", "destruction_attempted", "destruction_result",
    "post_cleanup_presence", "world_identity", "package_identity", "failure_code",
)


def honest_bundle(far, spawn=True):
    """Run the REAL ledger against the fake editor and return its raw bundle.

    The object is created AFTER the pre snapshot and destroyed BEFORE the post
    snapshot, on purpose: that is the case the inventories are blind to.
    """
    raw = far._new_raw_bundle()
    ledger = far._SpawnLedger(raw)
    raw["inventory"]["pre"] = far._inventory(far.ST_ANCHOR_BIND, ledger, MAP_PKG)
    if spawn:
        ledger.spawn_transient(object(), far.unreal.Actor, [10.0, 20.0, 30.0], "t0")
    ledger.cleanup()
    raw["inventory"]["post"] = far._inventory(far.ST_CLEANUP, ledger, MAP_PKG)
    return raw


def outcome(raw, field="cleanup_verified"):
    """(verdict, detail) where verdict is True / False / UNKNOWN."""
    enough, value, _inputs, detail = SSE.derive(field, raw)
    return (value if enough else UNKNOWN), detail


def inputs_of(raw, field="cleanup_verified"):
    _e, _v, inputs, _d = SSE.derive(field, raw)
    return inputs or {}


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), str(detail)[:400]))
        return bool(ok)

    def failures(self):
        return [r for r in self.rows if not r[1]]


def run(rep):
    far = load_far_side()

    # ---- 0. the producer is real, and it is the ONLY spawn path -------------- #
    total, ledgered = far._spawn_call_sites()
    rep.check("producer::single_spawn_path",
              total is not None and total == ledgered and ledgered == 1,
              "spawn_actor_from_class call sites: module={} inside "
              "_SpawnLedger.spawn_transient={}".format(total, ledgered))

    WORLD.__init__()
    raw = honest_bundle(far)

    placement = (raw.get("temporary_placement") or {}).get("t0") or {}
    missing = [f for f in REQUIRED_PLACEMENT_FIELDS if f not in placement]
    rep.check("producer::placement_carries_contract_fields", not missing,
              "missing: {}".format(missing))
    rep.check("producer::placement_is_a_real_life_story",
              placement.get("creation_observed") is True
              and placement.get("destruction_attempted") is True
              and placement.get("destruction_result") == "destroyed"
              and placement.get("post_cleanup_presence") == "absent"
              and placement.get("absent_after_cleanup") is True
              and placement.get("ownership_tag", "").startswith(
                  "worldforge.scene_survey/"),
              {k: placement.get(k) for k in REQUIRED_PLACEMENT_FIELDS})
    rep.check("producer::no_verdict_boolean_on_the_raw_record",
              not any(k in placement for k in
                      ("cleanup_verified", "cleanup_ok", "clean", "verdict")),
              sorted(placement))

    # The far side's own structural invariants, run over the bundle the ledger
    # produced. INV-ENV in particular: the manifest is a new record kind, and a
    # record missing envelope fields is one a consumer cannot attribute.
    integ = far._record_ref_integrity(raw)
    rep.check("producer::far_side_ref_integrity_clean",
              integ["unresolved_ref_count"] == 0
              and integ["record_id_mismatch_count"] == 0
              and integ["envelope_incomplete_count"] == 0,
              {k: integ.get(k) for k in ("unresolved_refs", "record_id_mismatches",
                                         "envelope_incomplete_records")})
    ok_refs, why_refs = SSE.check_reference_integrity(raw)
    rep.check("producer::consumer_side_ref_integrity_clean", ok_refs, why_refs)

    led = SSE.temporary_object_ledger(raw)
    rep.check("producer::ledger_manifest_emitted", led is not None)
    rep.check("producer::ledger_enumerates_o_created",
              led is not None and led.get("object_ids") == ["t0"]
              and led.get("created_object_ids") == ["t0"]
              and led.get("cleanup_ran") is True,
              None if led is None else {k: led.get(k) for k in
                                        ("object_ids", "created_object_ids",
                                         "cleanup_ran")})
    rep.check("producer::persistent_package_hash_is_unsupported_null",
              led is not None
              and led.get("persistent_package_hash") is None
              and led.get("persistent_package_hash_supported") is False
              and led.get("persistent_package_hash_evidence_class") == "unsupported"
              and bool(led.get("persistent_package_hash_unsupported_reason")),
              None if led is None else led.get("persistent_package_hash_supported"))

    # ---- 1. the honest run is answerable and clean --------------------------- #
    verdict, detail = outcome(raw)
    rep.check("honest::cleanup_verified_true", verdict is True, detail)
    i = inputs_of(raw)
    rep.check("honest::inventories_alone_saw_nothing",
              i.get("temporary_objects_equal") is True
              and i.get("dirty_packages_equal") is True
              and i.get("leaked_actors") == [] and i.get("vanished_actors") == [],
              "the object was created and destroyed BETWEEN the snapshots, so all "
              "three set conjuncts agree; only the ledger witnessed it: "
              "created={}".format(i.get("ledger_created_object_ids")))
    rep.check("honest::per_object_conjunct_did_the_work",
              i.get("ledger_created_object_ids") == ["t0"]
              and i.get("ledger_conjunct") is True, i.get("ledger_created_object_ids"))
    rep.check("honest::P_content_half_unsupported_not_agreed",
              i.get("persistent_package_hash_supported") is False
              and i.get("persistent_package_hash_equal") is None
              and i.get("persistent_package_identity_equal") is True, i)

    # An operation that spawns nothing is the EXPECTED case, and it is still only
    # answerable because the ledger said so.
    WORLD.__init__()
    empty = honest_bundle(far, spawn=False)
    v_empty, d_empty = outcome(empty)
    rep.check("honest::empty_operation_is_clean", v_empty is True, d_empty)

    # ---- MUTANT 1: no ledger at all ------------------------------------------ #
    # The mutation is "this operation kept no ledger", so everything the ledger
    # produced goes with it: its manifest, the placement record it filed, and the
    # inventory back-references to that record. What is left is EXACTLY the bundle
    # the pre-ledger far side emitted — two honest snapshots and nothing else — so
    # the refusal below is attributable to the missing ledger and not to a dangling
    # reference left behind by a sloppy mutation.
    m1 = copy.deepcopy(raw)
    del m1[SSE.LEDGER_KIND][SSE.LEDGER_IDENT]
    del m1["temporary_placement"]["t0"]
    for _side in ("pre", "post"):
        m1["inventory"][_side]["temporary_object_refs"] = []
    ok_refs, why_refs = SSE.check_reference_integrity(m1)
    rep.check("mutant1::bundle_is_otherwise_intact", ok_refs, why_refs)
    v1, d1 = outcome(m1)
    rep.check("mutant1::ledger_absent_is_unknown_never_success",
              v1 is UNKNOWN and "no temporary-object ledger" in d1,
              "verdict={!r} detail={}".format(v1, d1))

    # The same two inventories under the OLD rule. This is the fake green the whole
    # ledger exists to remove: three set comparisons over snapshots that never saw
    # the object, all agreeing, verdict True.
    old_ok, _old_inputs = SSE._inventory_only_cleanup_verdict(m1)
    rep.check("mutant1::inventories_alone_would_have_said_true", old_ok is True,
              "the pre/post-only rule returns {!r} for a bundle in which an object "
              "was created and destroyed between the snapshots".format(old_ok))

    # ---- MUTANT 2: destroy_actor lies ---------------------------------------- #
    # Injected at the EDITOR, not at the data: the real ledger runs unmodified and
    # emits destruction_result='destroyed' because destroy_actor returned True,
    # while its independent is_valid re-observation still finds the object.
    WORLD.__init__()
    WORLD.destroy_really = False
    m2 = honest_bundle(far)
    p2 = m2["temporary_placement"]["t0"]
    rep.check("mutant2::producer_recorded_both_channels_honestly",
              p2.get("destruction_result") == "destroyed"
              and p2.get("destroy_returned") is True
              and p2.get("post_cleanup_presence") == "present"
              and p2.get("absent_after_cleanup") is False,
              {k: p2.get(k) for k in ("destruction_result", "destroy_returned",
                                      "post_cleanup_presence",
                                      "absent_after_cleanup")})
    v2, d2 = outcome(m2)
    i2 = inputs_of(m2)
    rep.check("mutant2::survivor_is_false_not_unknown", v2 is False,
              "verdict={!r} detail={}".format(v2, d2))
    rep.check("mutant2::inventories_still_agree",
              i2.get("temporary_objects_equal") is True
              and i2.get("dirty_packages_equal") is True
              and i2.get("map_identity_equal") is True
              and i2.get("ledger_objects_present_after_cleanup") == ["t0"],
              "every snapshot conjunct passed; the ledger alone said no")
    v2p, _ = outcome(m2, "temporary_cleanup_valid")
    rep.check("mutant2::per_object_predicate_also_false", v2p is False, v2p)

    # MUTANT 2b — the mirror image, and the reason the conjunct is `destroyed(x)
    # AND NOT present(x)` rather than either half alone. Here the object really is
    # gone but the destroy call reported failure: something removed it that this
    # operation cannot account for, and a presence-only rail would call that clean.
    WORLD.__init__()
    WORLD.destroy_returns = False
    m2b = honest_bundle(far)
    p2b = m2b["temporary_placement"]["t0"]
    rep.check("mutant2b::producer_recorded_the_failed_destroy",
              p2b.get("destruction_result") == "destroy_returned_false"
              and p2b.get("post_cleanup_presence") == "absent",
              {k: p2b.get(k) for k in ("destruction_result",
                                       "post_cleanup_presence")})
    v2b, d2b = outcome(m2b)
    i2b = inputs_of(m2b)
    rep.check("mutant2b::unaccounted_removal_is_false", v2b is False,
              "verdict={!r} detail={}".format(v2b, d2b))
    rep.check("mutant2b::names_the_undestroyed_object",
              i2b.get("ledger_objects_not_destroyed") == ["t0"],
              i2b.get("ledger_objects_not_destroyed"))

    # ---- MUTANT 3: a package was dirtied ------------------------------------- #
    WORLD.__init__()
    m3 = copy.deepcopy(raw)
    m3["inventory"]["post"]["dirty_packages"] = [MAP_PKG]
    m3["inventory"]["post"]["dirty_map_packages"] = [MAP_PKG]
    v3, d3 = outcome(m3)
    i3 = inputs_of(m3)
    rep.check("mutant3::dirty_package_is_false", v3 is False,
              "verdict={!r} detail={}".format(v3, d3))
    rep.check("mutant3::names_the_package",
              i3.get("dirty_packages_equal") is False
              and i3.get("newly_dirty_packages") == [MAP_PKG], i3.get("newly_dirty_packages"))
    # ...and the reverse direction: a package that STOPS being dirty was saved.
    m3b = copy.deepcopy(raw)
    m3b["inventory"]["pre"]["dirty_packages"] = [MAP_PKG]
    v3b, _ = outcome(m3b)
    rep.check("mutant3::package_saved_is_also_false", v3b is False, v3b)

    # ---- MUTANT 4: a record from another operation --------------------------- #
    m4 = copy.deepcopy(raw)
    foreign = copy.deepcopy(m4["temporary_placement"]["t0"])
    foreign.update({"record_id": "temporary_placement#t9", "record_ident": "t9",
                    "object_id": "t9", "operation_id": "some-other-operation",
                    "ownership_tag": "worldforge.scene_survey/some-other-operation"})
    m4["temporary_placement"]["t9"] = foreign
    v4, d4 = outcome(m4)
    i4 = inputs_of(m4)
    rep.check("mutant4::foreign_operation_record_is_false", v4 is False,
              "verdict={!r} detail={}".format(v4, d4))
    rep.check("mutant4::named_as_foreign_and_unledgered",
              i4.get("ledger_foreign_operation_placements") == ["t9"]
              and i4.get("ledger_misattributed_placements") == ["t9"]
              and i4.get("ledger_unledgered_placements") == ["t9"], i4)
    # And when the ledger CLAIMS the foreign record, the bundle is cross-operation
    # and reference integrity refuses it one gate earlier. Still never success.
    m4b = copy.deepcopy(m4)
    m4b[SSE.LEDGER_KIND][SSE.LEDGER_IDENT]["object_ids"] = ["t0", "t9"]
    m4b[SSE.LEDGER_KIND][SSE.LEDGER_IDENT]["temporary_object_refs"] = [
        "temporary_placement#t0", "temporary_placement#t9"]
    v4b, d4b = outcome(m4b)
    rep.check("mutant4::claimed_foreign_record_is_unknown_via_integrity",
              v4b is UNKNOWN and "operation" in d4b,
              "verdict={!r} detail={}".format(v4b, d4b))

    # ---- extra rails the ledger buys ----------------------------------------- #
    # A cleanup that never ran cannot be witnessed by a post snapshot.
    m5 = copy.deepcopy(raw)
    m5[SSE.LEDGER_KIND][SSE.LEDGER_IDENT]["cleanup_ran"] = False
    v5, d5 = outcome(m5)
    rep.check("extra::cleanup_never_ran_is_unknown", v5 is UNKNOWN, d5)
    # A forged summary over an honest atom is a contradiction, not a pass.
    m6 = copy.deepcopy(m2)
    m6["temporary_placement"]["t0"]["post_cleanup_presence"] = "absent"
    v6, d6 = outcome(m6)
    rep.check("extra::forged_presence_contradicts_its_atom",
              v6 is UNKNOWN and "contradicts absent_after_cleanup" in d6, d6)
    # A stray spawn path means O_created may be incomplete.
    m7 = copy.deepcopy(raw)
    m7[SSE.LEDGER_KIND][SSE.LEDGER_IDENT]["unledgered_spawn_call_sites"] = 1
    v7, d7 = outcome(m7)
    rep.check("extra::stray_spawn_path_is_unknown", v7 is UNKNOWN, d7)
    # A PIE refusal creates nothing, and that is a measurement, not a hole.
    WORLD.__init__()
    WORLD.in_pie = True
    m8 = honest_bundle(far)
    p8 = m8["temporary_placement"]["t0"]
    v8, d8 = outcome(m8)
    rep.check("extra::pie_refusal_creates_nothing_and_stays_clean",
              p8.get("creation_observed") is False
              and p8.get("post_cleanup_presence") == "never_created"
              and p8.get("evidence_class") == "unsupported"
              and v8 is True,
              "verdict={!r} presence={!r} detail={}".format(
                  v8, p8.get("post_cleanup_presence"), d8))
    v8p, _ = outcome(m8, "temporary_cleanup_valid")
    rep.check("extra::never_created_reads_clean_not_unknown", v8p is True, v8p)

    run_vectors(rep, far, raw)


def _led(raw):
    return raw[SSE.LEDGER_KIND][SSE.LEDGER_IDENT]


def _consistent_uncreated(raw):
    """Blank the ledger's creation SUMMARY so only the atom rail can object.

    Without this the summary/atom cross-check fires first and the bundle is refused
    one gate early — which is a real defence, but it would leave the tri-state rail
    underneath it untested. A serious forger edits both.
    """
    led = _led(raw)
    led["created_object_ids"] = []
    led["created_object_count"] = 0
    return raw


def run_vectors(rep, far, raw):
    """The named attack vectors, one mutation each.

    Each mutation is minimal and is applied to the bundle the REAL ledger produced,
    so what is being tested is the consumer's response to one changed fact rather
    than to a hand-built fixture that never came from a producer.

    Where a vector is already covered by a mutant above, the check here is the one
    that ISOLATES it — e.g. `unledgered` is exercised by mutant 4 only in
    combination with a foreign operation_id and a mismatched ownership tag, so all
    three of those inputs fire at once and none of them is shown to be load-bearing
    on its own.
    """
    # ---- V1. a created object the ledger never declared ---------------------- #
    # Same operation, same ownership tag: ONLY `unledgered` may fire. If this record
    # is counted, `for every x in O_created` never visits an object that exists.
    v1 = copy.deepcopy(raw)
    extra = copy.deepcopy(v1["temporary_placement"]["t0"])
    extra.update({"record_id": "temporary_placement#t1", "record_ident": "t1",
                  "object_id": "t1", "ident": "t1"})
    v1["temporary_placement"]["t1"] = extra
    val, detail = outcome(v1)
    i1 = inputs_of(v1)
    rep.check("vector::unledgered_placement_alone_is_false", val is False, detail)
    rep.check("vector::unledgered_is_the_only_contaminant_firing",
              i1.get("ledger_unledgered_placements") == ["t1"]
              and i1.get("ledger_foreign_operation_placements") == []
              and i1.get("ledger_misattributed_placements") == [], i1)

    # ---- V2. creation_observed is UNKNOWN ------------------------------------ #
    # The forged-cleanup case that used to read True. `creation_observed` gates the
    # whole per-object conjunct, so blanking it on one record dropped that record —
    # and its fate — out of the quantifier entirely.
    # (a) nothing else is decided: the conjunct is UNASKABLE, so unknown.
    v2a = _consistent_uncreated(copy.deepcopy(raw))
    p = v2a["temporary_placement"]["t0"]
    p.update({"creation_observed": None, "destruction_attempted": False,
              "destruction_result": "not_attempted",
              "post_cleanup_presence": "unknown", "absent_after_cleanup": None})
    rep.check("vector::ledger_is_self_consistent_so_only_the_atom_rail_can_object",
              SSE.contradictory_atoms(v2a) == [], SSE.contradictory_atoms(v2a))
    val, detail = outcome(v2a)
    rep.check("vector::creation_observed_unknown_is_unknown_never_true",
              val is UNKNOWN and "creation_observed" in detail,
              "verdict={!r} detail={}".format(val, detail))
    # (b) ...but a WITNESSED leak still decides the record. False dominates unknown
    #     within a record, so blanking the creation atom must not erase a measured
    #     survivor. This is the direction that would have been a fake green.
    v2b = _consistent_uncreated(copy.deepcopy(raw))
    p = v2b["temporary_placement"]["t0"]
    p.update({"creation_observed": None, "destruction_attempted": True,
              "destruction_result": "destroy_returned_false",
              "post_cleanup_presence": "present", "absent_after_cleanup": False})
    val, detail = outcome(v2b)
    i2b = inputs_of(v2b)
    rep.check("vector::unknown_creation_does_not_erase_a_witnessed_leak",
              val is False, "verdict={!r} detail={}".format(val, detail))
    rep.check("vector::the_survivor_is_named_despite_unknown_creation",
              i2b.get("ledger_objects_present_after_cleanup") == ["t0"]
              and i2b.get("ledger_objects_creation_undecided") == ["t0"], i2b)

    # ---- V3. destruction never attempted ------------------------------------- #
    v3 = copy.deepcopy(raw)
    v3["temporary_placement"]["t0"].update({"destruction_attempted": False,
                                            "destroy_attempted": False,
                                            "destruction_result": "not_attempted"})
    val, detail = outcome(v3)
    i3 = inputs_of(v3)
    rep.check("vector::destruction_never_attempted_is_false", val is False, detail)
    rep.check("vector::not_attempted_names_the_object",
              i3.get("ledger_objects_not_destroyed") == ["t0"],
              i3.get("ledger_objects_not_destroyed"))

    # ---- V4. the destroy call failed ----------------------------------------- #
    # mutant 2b covers `destroy_returned_false`; `error` is the other failure the
    # far side can file (an exception out of destroy_actor), and it must not be a
    # vocabulary member that reads as success.
    v4 = copy.deepcopy(raw)
    v4["temporary_placement"]["t0"]["destruction_result"] = "error"
    val, detail = outcome(v4)
    rep.check("vector::destruction_error_is_false", val is False, detail)
    rep.check("vector::every_non_destroyed_result_is_false",
              all(outcome(_with_result(raw, r))[0] is False
                  for r in ("not_attempted", "destroy_returned_false", "error",
                            "unknown")),
              "one of the four non-'destroyed' vocabulary members did not read "
              "False")

    # ---- V6/V8. SAME COUNT, DIFFERENT IDENTITY ------------------------------- #
    # The critical forged-cleanup shape: every cardinality matches, so a rail
    # written over counts sees nothing. All three sets are compared as SETS.
    v6 = copy.deepcopy(raw)
    v6["inventory"]["post"]["actor_paths"] = [
        "/Game/Maps/M.M:PersistentLevel.Substituted_0"]
    val, detail = outcome(v6)
    i6 = inputs_of(v6)
    rep.check("vector::actor_set_same_count_different_identity_is_false",
              val is False, detail)
    rep.check("vector::the_swap_is_named_in_both_directions",
              i6.get("actors_pre") == i6.get("actors_post")
              and i6.get("leaked_actors") and i6.get("vanished_actors"),
              {k: i6.get(k) for k in ("actors_pre", "actors_post", "leaked_actors",
                                      "vanished_actors")})
    v6b = copy.deepcopy(raw)
    v6b["inventory"]["pre"]["operation_owned_actor_paths"] = ["/Game/X.X:A"]
    v6b["inventory"]["post"]["operation_owned_actor_paths"] = ["/Game/X.X:B"]
    val, detail = outcome(v6b)
    i6b = inputs_of(v6b)
    rep.check("vector::owned_set_same_count_different_identity_is_false",
              val is False, detail)
    rep.check("vector::owned_swap_is_named_in_both_directions",
              i6b.get("temporary_objects_equal") is False
              and i6b.get("temporary_objects_leaked") == ["/Game/X.X:B"]
              and i6b.get("temporary_objects_released") == ["/Game/X.X:A"], i6b)
    v8 = copy.deepcopy(raw)
    v8["inventory"]["pre"]["dirty_packages"] = ["/Game/Maps/P1"]
    v8["inventory"]["post"]["dirty_packages"] = ["/Game/Maps/P2"]
    val, detail = outcome(v8)
    i8 = inputs_of(v8)
    rep.check("vector::dirty_set_same_count_different_identity_is_false",
              val is False, detail)
    rep.check("vector::dirty_swap_is_named_in_both_directions",
              i8.get("newly_dirty_packages") == ["/Game/Maps/P2"]
              and i8.get("no_longer_dirty_packages") == ["/Game/Maps/P1"], i8)

    # ---- V9. the persistent package's CONTENT changed ------------------------ #
    # `persistent_package_hash_supported` / `_equal` used to be written as the
    # literals False / None regardless of the raw, so a far side that grew a hash
    # api would have had its measurement discarded and a mutated package would have
    # derived clean. They are read from the snapshots now.
    v9 = _with_hashes(raw, "sha256:aaa", "sha256:bbb")
    val, detail = outcome(v9)
    i9 = inputs_of(v9)
    rep.check("vector::persistent_package_hash_changed_is_false", val is False,
              detail)
    rep.check("vector::changed_hash_is_reported_as_a_real_comparison",
              i9.get("persistent_package_hash_supported") is True
              and i9.get("persistent_package_hash_equal") is False, i9)
    v9b = _with_hashes(raw, "sha256:aaa", "sha256:aaa")
    val, _d = outcome(v9b)
    rep.check("vector::matching_hash_does_not_block", val is True,
              inputs_of(v9b).get("persistent_package_hash_equal"))
    # A snapshot that DECLARES the channel but carries no hash has read nothing.
    # Half a comparison is unsupported, never agreement.
    v9c = _with_hashes(raw, "sha256:aaa", None)
    i9c = inputs_of(v9c)
    rep.check("vector::half_read_hash_is_unsupported_not_agreed",
              i9c.get("persistent_package_hash_supported") is False
              and i9c.get("persistent_package_hash_equal") is None, i9c)

    # ---- V11. wrong world identity ------------------------------------------- #
    v11 = copy.deepcopy(raw)
    v11["inventory"]["post"]["map_identity"] = "/Game/Maps/_wf_other_lvl"
    v11["inventory"]["post"]["package_identity"] = "/Game/Maps/_wf_other_lvl"
    val, detail = outcome(v11)
    rep.check("vector::map_identity_changed_is_false", val is False, detail)
    rep.check("vector::map_identity_change_is_named",
              inputs_of(v11).get("map_identity_equal") is False,
              inputs_of(v11).get("map_identity_post"))
    # ...and at the OBJECT level: a placement claiming a world these snapshots never
    # witnessed cannot be reasoned about by them at all.
    v11b = copy.deepcopy(raw)
    v11b["inventory"]["pre"]["map_identity"] = MAP_PKG
    v11b["temporary_placement"]["t0"]["world_identity"] = "/Game/Maps/_wf_other_lvl"
    v11b["temporary_placement"]["t0"]["package_identity"] = "/Game/Maps/_wf_other_lvl"
    val, detail = outcome(v11b)
    i11b = inputs_of(v11b)
    rep.check("vector::placement_from_a_foreign_world_is_false", val is False,
              detail)
    rep.check("vector::foreign_world_placement_is_named",
              i11b.get("ledger_foreign_world_placements") == ["t0"], i11b)

    # ---- V12. a ledger entry listed twice ------------------------------------ #
    # An id named twice inflates every count taken over the list. The honest bundle
    # is otherwise untouched, so the refusal is attributable to the duplicate.
    v12 = copy.deepcopy(raw)
    _led(v12)["object_ids"] = ["t0", "t0"]
    val, detail = outcome(v12)
    rep.check("vector::duplicated_ledger_entry_is_unknown",
              val is UNKNOWN and "more than once" in detail,
              "verdict={!r} detail={}".format(val, detail))

    # ---- V13. a ledger entry pointing at nothing ----------------------------- #
    v13 = copy.deepcopy(raw)
    _led(v13)["object_ids"] = ["t0", "ghost"]
    _led(v13)["object_count"] = 2
    val, detail = outcome(v13)
    rep.check("vector::ledger_entry_for_an_unknown_object_is_unknown",
              val is UNKNOWN and "no matching temporary_placement record" in detail,
              "verdict={!r} detail={}".format(val, detail))

    # ---- V14. an aggregate that outruns its atoms ---------------------------- #
    # Nothing in the derivation READS these summaries — O_created is recomputed from
    # the per-object `creation_observed` atoms. That is exactly why a lying summary
    # has to be rejected rather than ignored: a manifest whose counts disagree with
    # its own enumeration was written by something other than the ledger that
    # produced the atoms, and a bundle in that state is not answered from at all.
    v14a = copy.deepcopy(raw)
    _led(v14a)["object_count"] = 99
    val, detail = outcome(v14a)
    rep.check("vector::ledger_object_count_lying_is_unknown",
              val is UNKNOWN and "object_count=99" in detail,
              "verdict={!r} detail={}".format(val, detail))
    v14b = copy.deepcopy(raw)
    _led(v14b)["created_object_ids"] = []
    _led(v14b)["created_object_count"] = 0
    val, detail = outcome(v14b)
    rep.check("vector::created_summary_contradicting_atoms_is_unknown",
              val is UNKNOWN and "creation_observed atoms" in detail,
              "verdict={!r} detail={}".format(val, detail))
    v14c = copy.deepcopy(raw)
    _led(v14c)["created_object_ids"] = ["t0", "t9"]
    _led(v14c)["created_object_count"] = 2
    val, detail = outcome(v14c)
    rep.check("vector::created_summary_naming_an_undeclared_object_is_unknown",
              val is UNKNOWN and "does not declare" in detail,
              "verdict={!r} detail={}".format(val, detail))


def _with_result(raw, result):
    m = copy.deepcopy(raw)
    m["temporary_placement"]["t0"]["destruction_result"] = result
    return m


def _with_hashes(raw, pre_hash, post_hash):
    """A bundle whose snapshots declare the (currently unsupported) hash channel.

    The far side has no hash api today, so this is a bundle from a HYPOTHETICAL
    future collector. That is the point: the consumer must already be reading the
    field rather than asserting its own answer about it, or the day the channel
    appears is the day a mutated package starts deriving clean.
    """
    m = copy.deepcopy(raw)
    for which, h in (("pre", pre_hash), ("post", post_hash)):
        m["inventory"][which]["persistent_package_hash"] = h
        m["inventory"][which]["persistent_package_hash_supported"] = True
        m["inventory"][which]["persistent_package_hash_evidence_class"] = "observed"
    return m


def test_cleanup_ledger_mutants():
    rep = Report()
    run(rep)
    assert not rep.failures(), "\n".join(
        "{}: {}".format(n, d) for n, _ok, d in rep.failures())


def main():
    rep = Report()
    try:
        run(rep)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("HARNESS ERROR: {}: {}".format(type(exc).__name__, exc))
        return 2
    for name, ok, detail in rep.rows:
        print("{}  {}".format("PASS" if ok else "FAIL", name))
        if not ok:
            print("      {}".format(detail))
    fails = rep.failures()
    print()
    if fails:
        print("SCENE-SURVEY CLEANUP LEDGER MUTATION GATE: FAIL "
              "({} of {} checks)".format(len(fails), len(rep.rows)))
        return 1
    print("SCENE-SURVEY CLEANUP LEDGER MUTATION GATE: PASS ({} checks)".format(
        len(rep.rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
