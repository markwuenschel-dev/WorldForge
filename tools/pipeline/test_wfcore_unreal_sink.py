#!/usr/bin/env python3
"""
test_wfcore_unreal_sink.py
Gate for the engine-backed MutationSink and its near-side driver.

WHAT THIS PROVES, WITHOUT AN EDITOR
-----------------------------------
The sink's job is to be the ONE implementation of Core's ``MutationSink`` that
touches a real world. Everything about it that can be wrong falls into four bands,
and this file covers all four with no engine present:

  1. THE NEAR SIDE'S CONSTRUCTION -- the environment contract and the argv it hands
     the editor. A typo in an env-var name produces a far side that reads a default
     and silently surveys the wrong thing; that is a string comparison, so it is
     tested as one.

  2. THE FAR SIDE'S PURE LOGIC -- address parsing, class-name normalization, payload
     rounding, and the (target_kind, operation) -> kind -> compensating-action
     tables. The last is the one with teeth: a kind with no compensating action must
     be REFUSED BEFORE it is applied (WF1279), never discovered while unwinding.

  3. THE DUPLICATION BETWEEN THE TWO SIDES. The near side cannot import the far
     side (it does ``import unreal`` at module scope), so four helpers and one
     constant exist twice. Drift between them would write the caller's declared
     postcondition and the sink's observation of it in different alphabets, and
     every CORRECT mutation would read as a violated postcondition and be rolled
     back. So parity is asserted over a table rather than assumed.

  4. THE WHOLE TRANSACTION, END TO END, against a FAKE editor. The REAL
     ``wfcore.transaction.executor.apply_delta`` drives the REAL
     ``UnrealMutationSink`` over a fake ``unreal`` module. That is the only way to
     find out whether observe/apply/undo/drain_touched actually satisfy the contract
     the executor was written against -- and the fake editor is where the defects
     that matter can be INJECTED: a spawn that lands somewhere other than asked, and
     a ``destroy_actor`` that reports success and destroys nothing.

     Those two mutants are required to come back NOT-COMMITTED, and to come back as
     DIFFERENT outcomes, because they mean different things:

         rolled_back    -- the world was put back, and re-observation confirmed it
         partial_commit -- the undo ran, re-observation says it did not work, and
                           the world is now neither committed nor rolled back

     An outcome that rounded the second to the first would tell a caller it may
     safely retry from the original base, on top of a world that is half-changed.

Runnable as a plain script (no pytest needed); pytest-compatible too.

Usage:
    python tools/pipeline/test_wfcore_unreal_sink.py
"""

import copy
import json
import math
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
FAR_SIDE_PATH = TOOLS_DIR / "unreal" / "wfcore_unreal_sink.py"
NEAR_SIDE_PATH = TOOLS_DIR / "pipeline" / "run_wfcore_transaction.py"

for _p in (str(TOOLS_DIR), str(TOOLS_DIR / "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from wfcore import tri  # noqa: E402
from wfcore.transaction import delta as D  # noqa: E402
from wfcore.transaction import executor as EX  # noqa: E402
import failure_codes as FCODES  # noqa: E402
import run_wfcore_transaction as NEAR  # noqa: E402

MAP_PKG = "/Game/Maps/_wf_test_lvl"


# =========================================================================== #
# the fake editor
# =========================================================================== #
class _World(object):
    """One mutable fake level, plus the knobs that inject each real defect."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.package_name = MAP_PKG
        self.actors = []
        self.saved = []
        self.loaded = []
        self.assets = set()
        # -- defect injection --------------------------------------------- #
        self.spawn_location_drift = None   # the spawn lands somewhere else
        self.destroy_is_a_lie = False      # destroy_actor reports success, does nothing
        self.spawn_returns_none = False
        self.save_fails = False
        self.label_raises = False


WORLD = _World()


class _FakeVector(object):
    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)


class _FakeRotator(object):
    def __init__(self, pitch, yaw, roll):
        self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)


class _FakeClass(object):
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class _FakePackage(object):
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class _FakeWorld(object):
    def get_package(self):
        return _FakePackage(WORLD.package_name)


class _FakeActor(object):
    _counter = [0]

    def __init__(self, class_name, location, rotation, scale=(1.0, 1.0, 1.0)):
        _FakeActor._counter[0] += 1
        self._class_name = class_name
        self._label = "{}_{}".format(class_name, _FakeActor._counter[0])
        self._loc = list(location)
        self._rot = list(rotation)
        self._scale = list(scale)
        self._path = "{}.{}:PersistentLevel.{}".format(
            WORLD.package_name, WORLD.package_name.rsplit("/", 1)[-1], self._label)
        self.destroyed = False

    # identity
    def get_actor_label(self):
        return self._label

    def set_actor_label(self, label):
        if WORLD.label_raises:
            raise RuntimeError("injected: set_actor_label refused")
        self._label = label

    def get_path_name(self):
        return self._path

    def get_class(self):
        return _FakeClass(self._class_name)

    # transform
    def get_actor_location(self):
        return _FakeVector(*self._loc)

    def set_actor_location(self, vec, sweep=False, teleport=False):
        self._loc = [vec.x, vec.y, vec.z]
        return True

    def get_actor_rotation(self):
        return _FakeRotator(*self._rot)

    def set_actor_rotation(self, rot, teleport=False):
        self._rot = [rot.pitch, rot.yaw, rot.roll]
        return True

    def get_actor_scale3d(self):
        return _FakeVector(*self._scale)

    def set_actor_scale3d(self, vec):
        self._scale = [vec.x, vec.y, vec.z]


class _FakeUnrealEditorSubsystem(object):
    def get_editor_world(self):
        return _FakeWorld()


class _FakeEditorActorSubsystem(object):
    def get_all_level_actors(self):
        return [a for a in WORLD.actors if not a.destroyed]

    def spawn_actor_from_class(self, cls, location, rotation):
        if WORLD.spawn_returns_none:
            return None
        loc = [location.x, location.y, location.z]
        if WORLD.spawn_location_drift:
            loc = [loc[i] + WORLD.spawn_location_drift[i] for i in range(3)]
        actor = _FakeActor(cls.get_name() if hasattr(cls, "get_name") else str(cls),
                           loc, [rotation.pitch, rotation.yaw, rotation.roll])
        WORLD.actors.append(actor)
        return actor

    def destroy_actor(self, actor):
        if WORLD.destroy_is_a_lie:
            return True          # reports success, destroys nothing
        actor.destroyed = True
        if actor in WORLD.actors:
            WORLD.actors.remove(actor)
        return True


class _FakeLevelEditorSubsystem(object):
    def load_level(self, path):
        WORLD.loaded.append(path)
        WORLD.package_name = path
        return True


class _FakeSystemLibrary(object):
    @staticmethod
    def is_valid(obj):
        return bool(obj) and not getattr(obj, "destroyed", False)

    @staticmethod
    def quit_editor():
        return None

    @staticmethod
    def execute_console_command(world, command):
        return None


class _FakeLoadSave(object):
    @staticmethod
    def load_map(path):
        WORLD.loaded.append(path)
        WORLD.package_name = path
        return True

    @staticmethod
    def save_map(world, path):
        if WORLD.save_fails:
            return False
        WORLD.saved.append(path)
        return True


class _FakeEditorAssetLibrary(object):
    @staticmethod
    def does_asset_exist(path):
        return path in WORLD.assets


class _FakeScopedEditorTransaction(object):
    def __init__(self, description):
        self.description = description

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def install_fake_unreal():
    u = types.ModuleType("unreal")
    u.log = lambda msg: None
    u.Vector = _FakeVector
    u.Rotator = _FakeRotator
    u.UnrealEditorSubsystem = _FakeUnrealEditorSubsystem
    u.EditorActorSubsystem = _FakeEditorActorSubsystem
    u.LevelEditorSubsystem = _FakeLevelEditorSubsystem
    u.SystemLibrary = _FakeSystemLibrary
    u.EditorLoadingAndSavingUtils = _FakeLoadSave
    u.EditorAssetLibrary = _FakeEditorAssetLibrary
    u.ScopedEditorTransaction = _FakeScopedEditorTransaction
    u.StaticMeshActor = _FakeClass("StaticMeshActor")
    u.load_class = lambda outer, path: None
    u.get_editor_subsystem = lambda cls: cls()
    sys.modules["unreal"] = u
    return u


# --------------------------------------------------------------------------- #
# Load the far side WITHOUT running its transaction.
# --------------------------------------------------------------------------- #
# The module invokes `main()` at import time (it is an -ExecutePythonScript entry
# point, not a library), so it is exec'd up to that call and no further. The split
# sentinel is asserted to occur exactly once: if the entry point is ever
# restructured, this fails loudly rather than silently testing a truncated module.
_ENTRY_SENTINEL = "\ntry:\n    main()\n"


def load_far_side():
    src = FAR_SIDE_PATH.read_text(encoding="utf-8")
    if src.count(_ENTRY_SENTINEL) != 1:
        raise AssertionError(
            "expected exactly one {!r} entry point in {} (found {}) -- the loader "
            "would otherwise exec a module it cannot vouch for".format(
                _ENTRY_SENTINEL, FAR_SIDE_PATH, src.count(_ENTRY_SENTINEL)))
    body = src.split(_ENTRY_SENTINEL)[0]
    install_fake_unreal()
    mod = types.ModuleType("wfcore_unreal_sink_under_test")
    mod.__file__ = str(FAR_SIDE_PATH)
    sys.modules[mod.__name__] = mod
    exec(compile(body, str(FAR_SIDE_PATH), "exec"), mod.__dict__)  # noqa: S102
    return mod


FAR = load_far_side()


# =========================================================================== #
# reporting harness
# =========================================================================== #
class Report(object):
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), str(detail)))
        return bool(ok)

    def eq(self, name, got, want):
        return self.check(name, got == want, "got {!r}, want {!r}".format(got, want))

    def failures(self):
        return [r for r in self.rows if not r[1]]


# =========================================================================== #
# 1. NEAR SIDE -- environment and argv construction
# =========================================================================== #
DOCUMENTED_ENV_KEYS = {
    "WF_TX_OUT", "WF_TX_REQUEST", "WF_TX_MAP", "WF_TX_REPO_ROOT",
    "WF_TX_OPERATION_ID", "WF_TX_SAVE_MAP", "WF_TX_OBSERVE_AFTER", "WF_TX_TOOLS",
    "PYTHONUTF8",
}


def test_near_side_env(rep):
    env = NEAR.build_far_side_env("/out.json", "/req.json", MAP_PKG, REPO_ROOT,
                                  "op_x", save_map=False, observe_after=True)
    rep.eq("near.env.key_set_is_exactly_the_documented_contract",
           set(env), DOCUMENTED_ENV_KEYS)
    rep.check("near.env.every_value_is_a_string",
              all(isinstance(v, str) for v in env.values()),
              {k: type(v).__name__ for k, v in env.items()})
    rep.eq("near.env.save_map_off_is_the_literal_0", env["WF_TX_SAVE_MAP"], "0")
    rep.eq("near.env.observe_after_on_is_the_literal_1", env["WF_TX_OBSERVE_AFTER"], "1")
    rep.eq("near.env.operation_id_passes_through", env["WF_TX_OPERATION_ID"], "op_x")
    rep.eq("near.env.map_passes_through", env["WF_TX_MAP"], MAP_PKG)

    on = NEAR.build_far_side_env("/o", "/r", MAP_PKG, REPO_ROOT, "op",
                                 save_map=True, observe_after=False)
    rep.eq("near.env.save_map_on_is_the_literal_1", on["WF_TX_SAVE_MAP"], "1")
    rep.eq("near.env.observe_after_off_is_the_literal_0", on["WF_TX_OBSERVE_AFTER"], "0")

    # The far side must actually READ what the near side writes. Both flags are
    # parsed by the same function; a flag that is not recognised silently keeps its
    # default, which for observe_after would turn a measured commit into an
    # unverified one and nobody would see why.
    for token, want in (("1", True), ("0", False)):
        os.environ["WF_TX_PARITY_PROBE"] = token
        got, err = FAR._env_flag("WF_TX_PARITY_PROBE", not want)
        rep.check("far.env_flag_reads_{!r}_as_{}".format(token, want),
                  got is want and err is None, "got {!r} err={!r}".format(got, err))
    os.environ.pop("WF_TX_PARITY_PROBE", None)

    # A malformed flag degrades to the documented default PLUS a recorded reason.
    os.environ["WF_TX_PARITY_PROBE"] = "perhaps"
    got, err = FAR._env_flag("WF_TX_PARITY_PROBE", True)
    rep.check("far.env_flag_degrades_to_default_with_a_reason",
              got is True and isinstance(err, str) and err,
              "got {!r} err={!r}".format(got, err))
    os.environ.pop("WF_TX_PARITY_PROBE", None)


def test_near_side_command(rep):
    cmd = NEAR.build_editor_command("D:/UE_5.8/.../UnrealEditor-Cmd.exe",
                                    "D:\\repo\\WorldForge.uproject", FAR_SIDE_PATH)
    rep.check("near.cmd.uproject_is_forward_slashed",
              "\\" not in cmd[1], cmd[1])
    rep.check("near.cmd.script_is_forward_slashed_in_the_switch",
              cmd[2].startswith("-ExecutePythonScript=") and "\\" not in cmd[2], cmd[2])
    for flag in ("-unattended", "-nopause", "-nosplash", "-nullrhi", "-stdout"):
        rep.check("near.cmd.carries_{}".format(flag.strip("-")), flag in cmd, cmd)
    rep.check("near.cmd.script_is_the_far_side_this_repo_ships",
              cmd[2].endswith("wfcore_unreal_sink.py"), cmd[2])


def test_near_side_request(rep):
    request, err = NEAR.build_demo_spawn_request(
        MAP_PKG, "StaticMeshActor", "WF_TX_Probe", [10.0, 20.0, 30.0],
        [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], "op_demo", save_map=False)
    rep.check("near.request.builds", request is not None, err)
    if request is None:
        return
    errors, _warnings = NEAR.validate_request(request)
    rep.check("near.request.passes_the_executors_own_shape_validators",
              not errors, errors)
    bound = request["bounds"][0]
    address = "{}:WF_TX_Probe".format(MAP_PKG)
    rep.eq("near.request.bound_names_exactly_the_one_address",
           bound["allowed_actors"], [address])
    rep.eq("near.request.unsaved_run_declares_no_package_bound",
           bound["allowed_packages"], [])
    mutation = request["mutations"][0]
    rep.eq("near.request.create_declares_an_absent_before_state",
           mutation["before_state"]["state_kind"], D.STATE_ABSENT)
    rep.eq("near.request.rollback_mode_is_compensating",
           mutation["rollback_mode"], "compensating")
    rep.check("near.request.rollback_mode_is_one_the_executor_accepts",
              mutation["rollback_mode"] in
              __import__("wfcore.providers.base", fromlist=["x"]).ROLLBACK_CAPABLE,
              mutation["rollback_mode"])

    saved, _ = NEAR.build_demo_spawn_request(
        MAP_PKG, "StaticMeshActor", "WF_TX_Probe", [0, 0, 0], [0, 0, 0], [1, 1, 1],
        "op_demo", save_map=True)
    rep.eq("near.request.saving_run_declares_the_map_package_in_its_bound",
           saved["bounds"][0]["allowed_packages"], [MAP_PKG])

    # A request the executor would refuse must be refused HERE, before an editor
    # boot is paid to discover it.
    broken = copy.deepcopy(request)
    broken["mutations"][0]["target_path"] = "no_colon_here"
    errors, _ = NEAR.validate_request(broken)
    rep.check("near.request.refuses_an_unparseable_actor_address", bool(errors), errors)


def test_near_side_cli(rep):
    scratch = REPO_ROOT / "procedural" / "reports" / "core" / "transaction" / "op_wfcore_tx_selftest"
    try:
        rep.eq("near.cli.unknown_expect_outcome_exits_2",
               NEAR.main(["--demo-spawn", "StaticMeshActor", "--map", MAP_PKG,
                          "--expect", "banana", "--operation-id", "op_wfcore_tx_selftest",
                          "--dry-run"]), 2)
        rep.eq("near.cli.two_request_channels_exits_2",
               NEAR.main(["--demo-spawn", "StaticMeshActor", "--request", "x.json",
                          "--dry-run"]), 2)
        rep.eq("near.cli.no_request_channel_exits_2", NEAR.main(["--dry-run"]), 2)
        rep.eq("near.cli.demo_spawn_without_map_exits_2",
               NEAR.main(["--demo-spawn", "StaticMeshActor", "--dry-run"]), 2)
        rep.eq("near.cli.dry_run_is_bootless_and_succeeds",
               NEAR.main(["--demo-spawn", "StaticMeshActor", "--map", MAP_PKG,
                          "--operation-id", "op_wfcore_tx_selftest", "--dry-run"]), 0)
        written = scratch / "request.json"
        rep.check("near.cli.dry_run_writes_the_request_it_would_send",
                  written.is_file(), str(written))
        if written.is_file():
            body = json.loads(written.read_text(encoding="utf-8"))
            errs, _ = NEAR.validate_request(body)
            rep.check("near.cli.the_written_request_round_trips_through_json",
                      not errs, errs)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# =========================================================================== #
# 2. FAR SIDE -- pure logic
# =========================================================================== #
ADDRESS_CASES = [
    ("/Game/Maps/Foo:Bar", ("/Game/Maps/Foo", "Bar", None)),
    ("  /Game/Maps/Foo:Bar  ", ("/Game/Maps/Foo", "Bar", None)),
    ("/Game/Maps/Foo/:Bar", ("/Game/Maps/Foo", "Bar", None)),
    ("/Game/Maps/Foo", None),          # no colon
    ("/Game/Maps/Foo:a:b", None),      # two colons
    (":Bar", None),                    # empty map
    ("/Game/Maps/Foo:", None),         # empty label
    ("", None),
    (None, None),
    (17, None),
]

CLASS_CASES = [
    ("StaticMeshActor", "StaticMeshActor"),
    ("/Script/Engine.StaticMeshActor", "StaticMeshActor"),
    ("/Game/BP/BP_Foo.BP_Foo_C", "BP_Foo_C"),
    ("  PointLight  ", "PointLight"),
    ("", None),
    (None, None),
    (3, None),
]

PAYLOAD_CASES = [
    ("StaticMeshActor", [1.00000001, 2, 3], [0, 0, 0], [1, 1, 1]),
    ("/Script/Engine.PointLight", [-0.0, 2.00049, 3.9999], [1, 2, 3], [2, 2, 2]),
    ("StaticMeshActor", [float("nan"), 0, 0], [0, 0, 0], [1, 1, 1]),
    ("StaticMeshActor", [float("inf"), 0, 0], [0, 0, 0], [1, 1, 1]),
    ("StaticMeshActor", [1, 2], [0, 0, 0], [1, 1, 1]),
    (None, [1, 2, 3], [0, 0, 0], [1, 1, 1]),
]


def test_far_side_pure(rep):
    for raw, want in ADDRESS_CASES:
        got = FAR.parse_actor_address(raw)
        if want is None:
            rep.check("far.address.refuses_{!r}".format(raw),
                      got[0] is None and got[1] is None and isinstance(got[2], str),
                      got)
        else:
            rep.eq("far.address.parses_{!r}".format(raw), got, want)

    for raw, want in CLASS_CASES:
        rep.eq("far.class.normalizes_{!r}".format(raw),
               FAR.normalize_class_ref(raw), want)

    payload = FAR.actor_payload("StaticMeshActor", [1.00000001, 2, 3], [0, 0, 0],
                                [1, 1, 1])
    rep.eq("far.payload.rounds_to_ROUND_DIGITS", payload["location"], [1.0, 2.0, 3.0])
    rep.eq("far.payload.key_set_is_exactly_the_comparison_shape", set(payload),
           {"actor_class", "location", "rotation", "scale"})
    rep.check("far.payload.carries_no_object_path",
              "object_path" not in payload,
              "an object path a caller cannot predict would make every "
              "postcondition unsatisfiable")
    for bad in ([float("nan"), 0, 0], [float("inf"), 0, 0], [1, 2], "nope", None):
        rep.check("far.payload.refuses_location_{!r}".format(bad),
                  FAR.actor_payload("StaticMeshActor", bad, [0, 0, 0], [1, 1, 1]) is None,
                  "a payload with a hole in it is not a restore point")
    rep.check("far.payload.negative_zero_is_normalised",
              FAR.actor_payload("A", [-0.0, 0, 0], [0, 0, 0], [1, 1, 1])["location"][0] == 0.0
              and not math.copysign(1, FAR.actor_payload(
                  "A", [-0.0, 0, 0], [0, 0, 0], [1, 1, 1])["location"][0]) < 0,
              "-0.0 and 0.0 serialize differently and would read as a violated "
              "postcondition")


def test_compensation_tables(rep):
    # The structural rail. Adding a kind to MUTATION_KINDS without adding its
    # inverse to COMPENSATIONS is exactly the mistake WF1279 exists to catch, and
    # this is the check that catches it at authoring time rather than at unwind time.
    missing = [k for k in set(FAR.MUTATION_KINDS.values())
               if not FAR.compensation_for(k)]
    rep.check("far.kinds.every_supported_kind_declares_a_compensating_action",
              not missing,
              "kinds {} have no inverse; the engine exposes no generic Undo, so a "
              "kind with no inverse cannot be rolled back".format(missing))
    rep.eq("far.kinds.actor_create_is_a_spawn",
           FAR.mutation_kind("actor", "create"), FAR.KIND_ACTOR_SPAWN)
    rep.eq("far.kinds.actor_modify_is_a_transform",
           FAR.mutation_kind("actor", "modify"), FAR.KIND_ACTOR_TRANSFORM)
    rep.eq("far.kinds.spawn_compensates_by_destroying",
           FAR.compensation_for(FAR.KIND_ACTOR_SPAWN), "destroy_spawned_actor")
    rep.eq("far.kinds.transform_compensates_by_restoring_the_captured_transform",
           FAR.compensation_for(FAR.KIND_ACTOR_TRANSFORM),
           "restore_captured_transform")
    for pair in (("actor", "delete"), ("package", "create"), ("package", "modify"),
                 ("package", "delete"), ("actor", "teleport"), (None, None)):
        rep.check("far.kinds.unsupported_{}_{}_maps_to_nothing".format(*pair),
                  FAR.mutation_kind(pair[0], pair[1]) is None, pair)


def test_refusals(rep):
    def m(kind, op, mid="m0"):
        return {"mutation_id": mid, "target_kind": kind, "operation": op}

    ok = FAR.refusals_for([m("actor", "create", "a"), m("actor", "modify", "b")])
    rep.check("far.refusal.supported_kinds_are_not_refused", not ok, ok)

    for kind, op in (("actor", "delete"), ("package", "create"),
                     ("package", "modify"), ("widget", "create")):
        got = FAR.refusals_for([m(kind, op)])
        rep.check("far.refusal.{}_{}_is_refused".format(kind, op), len(got) == 1, got)
        if got:
            rep.eq("far.refusal.{}_{}_carries_WF1279".format(kind, op),
                   got[0]["failure_code"], FAR.FC_NO_COMPENSATION)

    rep.check("far.refusal.a_non_object_mutation_is_refused_not_skipped",
              len(FAR.refusals_for(["not a dict"])) == 1)

    # The literal code must be the one the repository registry actually declares --
    # a code that exists only in this file is published to nobody.
    rep.eq("far.refusal.WF1279_is_the_registered_code",
           FAR.FC_NO_COMPENSATION, FCODES.FailureCode.CORE_SINK_NO_COMPENSATION)
    for literal, registered in (
            (FAR.FC_SINK_UNAVAILABLE, FCODES.FailureCode.CORE_SINK_UNAVAILABLE),
            (FAR.FC_OBSERVATION_FAILED, FCODES.FailureCode.CORE_SINK_OBSERVATION_FAILED),
            (FAR.FC_APPLY_FAILED, FCODES.FailureCode.CORE_SINK_APPLY_FAILED),
            (FAR.FC_SAVE_FAILED, FCODES.FailureCode.CORE_SINK_SAVE_FAILED),
            (FAR.FC_RELOAD_MISMATCH, FCODES.FailureCode.CORE_SINK_RELOAD_MISMATCH)):
        rep.eq("far.codes.{}_matches_the_registry".format(registered), literal, registered)


# =========================================================================== #
# 3. PARITY between the two copies
# =========================================================================== #
def test_parity(rep):
    rep.eq("parity.ROUND_DIGITS", NEAR.ROUND_DIGITS, FAR.ROUND_DIGITS)
    for raw, _want in ADDRESS_CASES:
        near, far = NEAR.parse_actor_address(raw), FAR.parse_actor_address(raw)
        rep.check("parity.parse_actor_address_{!r}".format(raw),
                  near[0] == far[0] and near[1] == far[1]
                  and (near[2] is None) == (far[2] is None),
                  "near={!r} far={!r}".format(near, far))
    for raw, _want in CLASS_CASES:
        rep.eq("parity.normalize_class_ref_{!r}".format(raw),
               NEAR.normalize_class_ref(raw), FAR.normalize_class_ref(raw))
    for (cls, loc, rot, scl) in PAYLOAD_CASES:
        rep.eq("parity.actor_payload_{!r}_{!r}".format(cls, loc),
               NEAR.actor_payload(cls, loc, rot, scl),
               FAR.actor_payload(cls, loc, rot, scl))
    rep.eq("parity.provider_rollback_mode_is_compensating",
           NEAR.ROLLBACK_MODE, "compensating")


# =========================================================================== #
# 4. JSON round-tripping and the fatal-path document
# =========================================================================== #
def test_json_round_trip(rep):
    tmp = Path(tempfile.mkdtemp(prefix="wf_tx_json_"))
    try:
        doc = FAR._new_doc()
        text = json.dumps(doc, indent=2, sort_keys=True, allow_nan=False, default=str)
        rep.check("json.skeleton_serializes_with_allow_nan_false", bool(text))
        rep.eq("json.skeleton_round_trips", json.loads(text), json.loads(text))

        out = tmp / "far.json"
        saved_out = FAR.OUT
        saved_req, saved_inline = FAR.REQUEST_PATH, FAR.REQUEST_INLINE
        try:
            FAR.OUT = str(out)
            FAR._write(FAR._new_doc())
            rep.check("json.write_produces_one_file", out.is_file(), str(out))
            back = json.loads(out.read_text(encoding="utf-8"))
            rep.eq("json.written_document_has_the_skeleton_key_set",
                   set(back), set(FAR._new_doc()))

            # The no-request path must still leave a document -- a far side that
            # writes nothing is indistinguishable from one that never started.
            out.unlink()
            FAR.REQUEST_PATH, FAR.REQUEST_INLINE = "", ""
            FAR.main()
            rep.check("json.a_far_side_with_no_request_still_writes_evidence",
                      out.is_file(), str(out))
            if out.is_file():
                back = json.loads(out.read_text(encoding="utf-8"))
                rep.eq("json.error_document_keeps_key_set_parity_with_the_skeleton",
                       set(back), set(FAR._new_doc()))
                rep.check("json.error_document_names_its_reason",
                          isinstance(back.get("error"), str) and back["error"],
                          back.get("error"))

            # A refused request must be refused with the world provably untouched.
            out.unlink()
            before = len(WORLD.actors)
            FAR.REQUEST_INLINE = json.dumps({
                "operation_id": "op_refuse",
                "bounds": [], "mutations": [
                    {"mutation_id": "m0", "target_kind": "actor",
                     "operation": "delete", "target_path": "{}:X".format(MAP_PKG)}],
                "evidence_refs": ["x"]})
            FAR.main()
            back = json.loads(out.read_text(encoding="utf-8"))
            rep.check("json.uncompensatable_request_is_refused_with_WF1279",
                      FAR.FC_NO_COMPENSATION in (back.get("failure_codes") or []),
                      back.get("failure_codes"))
            rep.check("json.refusal_never_produced_a_delta",
                      back.get("delta") is None, back.get("delta"))
            rep.eq("json.refusal_left_the_world_untouched", len(WORLD.actors), before)
        finally:
            FAR.OUT, FAR.REQUEST_PATH, FAR.REQUEST_INLINE = (
                saved_out, saved_req, saved_inline)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


# =========================================================================== #
# 5. END TO END -- the REAL executor over the REAL sink over a FAKE editor
# =========================================================================== #
def run_transaction(request, repo_root, save_map=False, observe_after=True):
    sink = FAR.UnrealMutationSink(save_map=save_map, expected_map=MAP_PKG)
    record = EX.apply_delta(
        sink, request["bounds"], request["mutations"],
        repo_root=str(repo_root),
        operation_id=request["operation_id"],
        evidence_refs=request.get("evidence_refs") or ["x"],
        observe_after=observe_after,
        journal=True)
    return sink, record


def spawn_request(label, operation_id, location=(10.0, 20.0, 30.0), bound_address=None):
    request, err = NEAR.build_demo_spawn_request(
        MAP_PKG, "StaticMeshActor", label, list(location), [0.0, 0.0, 0.0],
        [1.0, 1.0, 1.0], operation_id, save_map=False)
    if request is None:
        raise AssertionError(err)
    if bound_address is not None:
        request["bounds"][0]["allowed_actors"] = [bound_address]
    return request


def actor_with_label(label):
    return [a for a in WORLD.actors if a.get_actor_label() == label and not a.destroyed]


def test_end_to_end(rep):
    tmp = Path(tempfile.mkdtemp(prefix="wf_tx_repo_"))
    try:
        # -- I1: an honest spawn COMMITS, and the commit is MEASURED ---------- #
        WORLD.reset()
        request = spawn_request("WF_TX_A", "op_e2e_commit")
        sink, record = run_transaction(request, tmp)
        rep.eq("e2e.spawn.outcome_is_committed", record["outcome"], D.DELTA_COMMITTED)
        rep.eq("e2e.spawn.verification_was_measured_not_assumed",
               record["verification"], tri.SATISFIED)
        rep.eq("e2e.spawn.bound_enforcement_satisfied",
               record["bound_enforcement"], tri.SATISFIED)
        rep.check("e2e.spawn.the_actor_is_actually_in_the_world",
                  len(actor_with_label("WF_TX_A")) == 1,
                  [a.get_actor_label() for a in WORLD.actors])
        rep.eq("e2e.spawn.mutation_status_is_applied",
               record["mutations"][0]["status"], D.MUT_APPLIED)
        rep.eq("e2e.spawn.before_state_was_observed_absent",
               record["mutations"][0]["before_state"]["state_kind"], D.STATE_ABSENT)
        rep.check("e2e.spawn.lock_was_taken_and_released",
                  record["lock"]["held"] and record["lock"]["released"],
                  record["lock"])
        rep.check("e2e.spawn.journal_was_published",
                  record.get("journal_path") and Path(record["journal_path"]).is_file(),
                  record.get("journal_path"))
        rep.check("e2e.spawn.the_returned_delta_passes_its_own_coherence_rails",
                  not [c for c in D.validate_world_delta(record) if not c[1]],
                  [c[0] for c in D.validate_world_delta(record) if not c[1]])
        rep.check("e2e.spawn.unsaved_run_touched_no_package",
                  not any(k == "package" for (k, _p) in sink.observe_calls),
                  sink.observe_calls)
        rep.eq("e2e.spawn.nothing_was_saved_to_disk", WORLD.saved, [])

        # -- the near side's re-derivation agrees with what came back --------- #
        findings = NEAR.rederive({"delta": record})
        rep.check("e2e.spawn.near_side_reverifies_the_verification_fold",
                  findings["verification_agrees"] is True, findings)
        rep.check("e2e.spawn.near_side_finds_no_coherence_failure",
                  not findings["validation_failures"], findings["validation_failures"])
        # A committed delta ran no rollback, so the rollback fold ranged over
        # NOTHING. `tri.conj([])` is vacuously satisfied while the executor leaves
        # the field UNKNOWN, so comparing them would fire on every healthy run.
        # NOT CHECKED must read as None -- neither agreement nor disagreement.
        rep.eq("e2e.spawn.rollback_fold_over_nothing_is_NOT_CHECKED",
               findings["rollback_agrees"], None)
        rep.eq("e2e.spawn.and_says_so_explicitly",
               findings["rollback_fold_ranged_over_something"], False)

        # -- I2: a transform of that actor COMMITS ---------------------------- #
        address = "{}:WF_TX_A".format(MAP_PKG)
        step = "step_transform"
        payload = NEAR.actor_payload("StaticMeshActor", [111.0, 222.0, 333.0],
                                     [0.0, 45.0, 0.0], [2.0, 2.0, 2.0])
        move = {
            "operation_id": "op_e2e_transform",
            "bounds": [NEAR.build_bound(step, [address])],
            "mutations": [NEAR.build_mutation("mut_move", step, address,
                                              D.OP_MODIFY, payload)],
            "evidence_refs": ["x"],
        }
        sink, record = run_transaction(move, tmp)
        rep.eq("e2e.transform.outcome_is_committed", record["outcome"], D.DELTA_COMMITTED)
        moved = actor_with_label("WF_TX_A")
        rep.eq("e2e.transform.the_actor_actually_moved",
               [round(v, 3) for v in moved[0]._loc], [111.0, 222.0, 333.0])
        rep.eq("e2e.transform.before_state_captured_the_old_transform",
               record["mutations"][0]["before_state"]["payload"]["location"],
               [10.0, 20.0, 30.0])

        # -- I3: a spawn that lands somewhere else ROLLS BACK ----------------- #
        WORLD.reset()
        WORLD.spawn_location_drift = [0.0, 0.0, 5.0]
        request = spawn_request("WF_TX_B", "op_e2e_drift")
        sink, record = run_transaction(request, tmp)
        rep.eq("e2e.drift.outcome_is_rolled_back", record["outcome"], D.DELTA_ROLLED_BACK)
        rep.eq("e2e.drift.rollback_was_confirmed_by_reobservation",
               record["rollback_completeness"], tri.SATISFIED)
        rep.eq("e2e.drift.mutation_status_is_rolled_back",
               record["mutations"][0]["status"], D.MUT_ROLLED_BACK)
        rep.check("e2e.drift.the_drifted_actor_was_destroyed",
                  not actor_with_label("WF_TX_B"),
                  [a.get_actor_label() for a in WORLD.actors])
        rep.check("e2e.drift.rolled_back_is_not_reported_as_committed",
                  not D.is_committed(record["outcome"]), record["outcome"])
        # Here the rollback fold DID range over something, so the near side
        # re-derives it independently and the comparison is real.
        findings = NEAR.rederive({"delta": record})
        rep.eq("e2e.drift.rollback_fold_ranged_over_something",
               findings["rollback_fold_ranged_over_something"], True)
        rep.check("e2e.drift.near_side_reverifies_the_rollback_fold",
                  findings["rollback_agrees"] is True, findings)

        # -- I4: destroy_actor LIES -> PARTIAL COMMIT, never a rollback ------- #
        WORLD.reset()
        WORLD.spawn_location_drift = [0.0, 0.0, 5.0]
        WORLD.destroy_is_a_lie = True
        request = spawn_request("WF_TX_C", "op_e2e_lying_destroy")
        sink, record = run_transaction(request, tmp)
        rep.eq("e2e.lying_destroy.outcome_is_partial_commit",
               record["outcome"], D.DELTA_PARTIAL_COMMIT)
        rep.eq("e2e.lying_destroy.rollback_completeness_is_violated",
               record["rollback_completeness"], tri.VIOLATED)
        rep.check("e2e.lying_destroy.undo_REPORTED_success",
                  record["mutations"][0].get("undo_reported_ok") is True,
                  "the undo's own opinion of itself is recorded and then not used "
                  "as the verdict")
        rep.eq("e2e.lying_destroy.status_is_rollback_failed",
               record["mutations"][0]["status"], D.MUT_ROLLBACK_FAILED)
        rep.check("e2e.lying_destroy.carries_the_partial_commit_code",
                  FCODES.FailureCode.CORE_DELTA_PARTIAL_COMMIT
                  in record["failure_codes"], record["failure_codes"])
        rep.check("e2e.lying_destroy.is_neither_committed_nor_rolled_back",
                  not D.is_committed(record["outcome"])
                  and not D.is_rolled_back(record["outcome"]), record["outcome"])
        rep.check("e2e.lying_destroy.the_actor_is_still_there",
                  len(actor_with_label("WF_TX_C")) == 1,
                  [a.get_actor_label() for a in WORLD.actors])

        # -- I5: an address outside its bound is refused, world untouched ----- #
        WORLD.reset()
        request = spawn_request("WF_TX_D", "op_e2e_out_of_bounds",
                                bound_address="{}:SOMETHING_ELSE".format(MAP_PKG))
        sink, record = run_transaction(request, tmp)
        rep.eq("e2e.out_of_bounds.outcome_is_refused", record["outcome"], D.DELTA_REFUSED)
        rep.check("e2e.out_of_bounds.carries_the_out_of_bounds_code",
                  FCODES.FailureCode.CORE_DELTA_OUT_OF_BOUNDS in record["failure_codes"],
                  record["failure_codes"])
        rep.eq("e2e.out_of_bounds.nothing_was_spawned", WORLD.actors, [])
        rep.eq("e2e.out_of_bounds.apply_was_never_called", sink.apply_calls, [])

        # -- I6: an ambiguous label is UNMEASURABLE, not absent --------------- #
        WORLD.reset()
        WORLD.actors.append(_FakeActor("StaticMeshActor", [0, 0, 0], [0, 0, 0]))
        WORLD.actors[-1].set_actor_label("WF_TX_E")
        WORLD.actors.append(_FakeActor("StaticMeshActor", [1, 1, 1], [0, 0, 0]))
        WORLD.actors[-1].set_actor_label("WF_TX_E")
        request = spawn_request("WF_TX_E", "op_e2e_ambiguous")
        sink, record = run_transaction(request, tmp)
        rep.check("e2e.ambiguous.was_not_applied",
                  record["outcome"] != D.DELTA_COMMITTED, record["outcome"])
        rep.check("e2e.ambiguous.reported_as_unverified_not_as_absent",
                  FCODES.FailureCode.CORE_DELTA_UNVERIFIED in record["failure_codes"],
                  record["failure_codes"])
        rep.eq("e2e.ambiguous.apply_was_never_called", sink.apply_calls, [])
        rep.eq("e2e.ambiguous.no_third_actor_appeared", len(WORLD.actors), 2)

        # -- I7: the wrong world open is UNMEASURABLE, not absent ------------- #
        WORLD.reset()
        WORLD.package_name = "/Game/Maps/SomeOtherLevel"
        request = spawn_request("WF_TX_F", "op_e2e_wrong_world")
        sink, record = run_transaction(request, tmp)
        rep.eq("e2e.wrong_world.apply_was_never_called", sink.apply_calls, [])
        rep.check("e2e.wrong_world.reported_as_unverified",
                  FCODES.FailureCode.CORE_DELTA_UNVERIFIED in record["failure_codes"],
                  record["failure_codes"])
        rep.eq("e2e.wrong_world.nothing_was_spawned", WORLD.actors, [])

        # -- I8: saving reports the map package as touched -------------------- #
        WORLD.reset()
        request, _ = NEAR.build_demo_spawn_request(
            MAP_PKG, "StaticMeshActor", "WF_TX_G", [1.0, 2.0, 3.0], [0, 0, 0],
            [1, 1, 1], "op_e2e_saved", save_map=True)
        sink, record = run_transaction(request, tmp, save_map=True)
        rep.eq("e2e.saved.outcome_is_committed", record["outcome"], D.DELTA_COMMITTED)
        rep.eq("e2e.saved.the_map_was_actually_saved", WORLD.saved, [MAP_PKG])

        # The same run with the package left OUT of the bound must be caught by
        # the post-apply actual-touch check -- the one check a lying provider
        # cannot pass by construction.
        WORLD.reset()
        request, _ = NEAR.build_demo_spawn_request(
            MAP_PKG, "StaticMeshActor", "WF_TX_H", [1.0, 2.0, 3.0], [0, 0, 0],
            [1, 1, 1], "op_e2e_saved_unbounded", save_map=False)
        sink, record = run_transaction(request, tmp, save_map=True)
        rep.check("e2e.saved.an_undeclared_package_write_is_caught_after_the_fact",
                  record["bound_enforcement"] == tri.VIOLATED,
                  "bound_enforcement={} outcome={}".format(
                      record["bound_enforcement"], record["outcome"]))
        rep.check("e2e.saved.the_undeclared_write_is_not_reported_as_a_commit",
                  not D.is_committed(record["outcome"]), record["outcome"])

        # -- I10: an unresolvable actor class raises WF1278, and rolls back --- #
        # wfcore/failure.py is explicit that DEFINING a code proves nothing: every
        # code in the WF1200 band needs a real raise site AND a test that observes
        # it. These two observe WF1278 and WF1280 from the sink's own raise sites.
        WORLD.reset()
        step = "step_bad_class"
        addr_ok = "{}:WF_TX_J".format(MAP_PKG)
        addr_bad = "{}:WF_TX_K".format(MAP_PKG)
        doomed = {
            "operation_id": "op_e2e_bad_class",
            "bounds": [NEAR.build_bound(step, [addr_ok, addr_bad])],
            "mutations": [
                NEAR.build_mutation("mut_ok", step, addr_ok, D.OP_CREATE,
                                    NEAR.actor_payload("StaticMeshActor", [0, 0, 7],
                                                       [0, 0, 0], [1, 1, 1])),
                NEAR.build_mutation("mut_doomed", step, addr_bad, D.OP_CREATE,
                                    NEAR.actor_payload("NoSuchActorClassXYZ", [0, 0, 8],
                                                       [0, 0, 0], [1, 1, 1]))],
            "evidence_refs": ["x"],
        }
        sink, record = run_transaction(doomed, tmp)
        rep.check("e2e.bad_class.abort_names_WF1278",
                  FAR.FC_APPLY_FAILED in record["abort_reason"], record["abort_reason"])
        rep.eq("e2e.bad_class.outcome_is_rolled_back",
               record["outcome"], D.DELTA_ROLLED_BACK)
        rep.check("e2e.bad_class.the_earlier_spawn_was_compensated",
                  not actor_with_label("WF_TX_J"),
                  "a mutation that succeeded before the failing one must be undone")

        # -- I11: a save that reports failure raises WF1280 ------------------- #
        WORLD.reset()
        WORLD.save_fails = True
        request, _ = NEAR.build_demo_spawn_request(
            MAP_PKG, "StaticMeshActor", "WF_TX_L", [0, 0, 9], [0, 0, 0], [1, 1, 1],
            "op_e2e_save_fails", save_map=True)
        sink, record = run_transaction(request, tmp, save_map=True)
        rep.check("e2e.save_failure.abort_names_WF1280",
                  FAR.FC_SAVE_FAILED in record["abort_reason"], record["abort_reason"])
        rep.check("e2e.save_failure.is_not_reported_as_a_commit",
                  not D.is_committed(record["outcome"]), record["outcome"])

        # -- I9: observe_after=False can never report a plain commit ---------- #
        WORLD.reset()
        request = spawn_request("WF_TX_I", "op_e2e_unverified")
        sink, record = run_transaction(request, tmp, observe_after=False)
        rep.eq("e2e.unverified.outcome_is_committed_unverified",
               record["outcome"], D.DELTA_COMMITTED_UNVERIFIED)
        rep.check("e2e.unverified.is_committed_but_not_VERIFIED",
                  D.is_committed(record["outcome"])
                  and not D.commit_is_verified(record["outcome"]), record["outcome"])
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def test_drain_touched(rep):
    """drain_touched is the ONLY channel an out-of-bound write can be seen through."""
    WORLD.reset()
    sink = FAR.UnrealMutationSink(save_map=False, expected_map=MAP_PKG)
    rep.eq("drain.starts_empty", sink.drain_touched(), [])
    address = "{}:WF_TX_DRAIN".format(MAP_PKG)
    payload = FAR.actor_payload("StaticMeshActor", [0, 0, 0], [0, 0, 0], [1, 1, 1])
    sink.apply({"mutation_id": "m", "target_kind": "actor", "operation": "create",
                "target_path": address,
                "expected_after_state": D.present_state(payload)})
    rep.eq("drain.reports_exactly_what_was_written", sink.drain_touched(),
           [("actor", address)])
    rep.eq("drain.is_emptied_by_the_drain", sink.drain_touched(), [])
    rep.check("drain.never_returns_None",
              sink.drain_touched() is not None,
              "None means 'this sink cannot tell', which would make the bound "
              "unenforceable for no reason -- this sink wrote it, so it knows")


def test_observe_is_three_valued(rep):
    WORLD.reset()
    sink = FAR.UnrealMutationSink(save_map=False, expected_map=MAP_PKG)
    absent = sink.observe("actor", "{}:NOBODY".format(MAP_PKG))
    rep.eq("observe.an_enumerated_empty_level_is_MEASURED_absent",
           absent["state_kind"], D.STATE_ABSENT)
    rep.check("observe.measured_absent_is_measured", D.is_measured(absent), absent)

    bad = sink.observe("actor", "no_colon")
    rep.eq("observe.an_unparseable_address_is_unmeasured",
           bad["state_kind"], D.STATE_UNMEASURED)
    rep.check("observe.unmeasured_carries_a_reason", bool(bad.get("reason")), bad)

    unknown_kind = sink.observe("widget", "whatever")
    rep.eq("observe.an_unknown_target_kind_is_unmeasured",
           unknown_kind["state_kind"], D.STATE_UNMEASURED)

    WORLD.assets.add("/Game/Foo/Bar")
    rep.eq("observe.a_present_package_is_present",
           sink.observe("package", "/Game/Foo/Bar")["state_kind"], D.STATE_PRESENT)
    rep.eq("observe.a_missing_package_is_absent",
           sink.observe("package", "/Game/Foo/Missing")["state_kind"], D.STATE_ABSENT)

    rep.check("observe.never_raises",
              all(D.is_state(sink.observe(k, p)) for k, p in
                  (("actor", None), ("actor", 17), ("package", None),
                   (None, None), ("actor", ":"), ("actor", "a:b:c"))),
              "observe must degrade to a state record, never propagate an exception")


# =========================================================================== #
def run(rep):
    test_near_side_env(rep)
    test_near_side_command(rep)
    test_near_side_request(rep)
    test_near_side_cli(rep)
    test_far_side_pure(rep)
    test_compensation_tables(rep)
    test_refusals(rep)
    test_parity(rep)
    test_json_round_trip(rep)
    test_drain_touched(rep)
    test_observe_is_three_valued(rep)
    test_end_to_end(rep)


def test_wfcore_unreal_sink():  # pytest entry point
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
        print("WFCORE UNREAL SINK GATE: FAIL ({} of {} checks)".format(
            len(fails), len(rep.rows)))
        return 1
    print("WFCORE UNREAL SINK GATE: PASS ({} checks)".format(len(rep.rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
