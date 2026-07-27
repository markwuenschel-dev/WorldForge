#!/usr/bin/env python3
r"""run_v2_6_fixture_smoke.py — runtime proof for the v2.6 survey API surface.

WHY THIS EXISTS
---------------
tools/bridge/scene_survey_far_side.py is written defensively against a Python
symbol surface it has never been able to execute. Its own header says so:

    "Every Unreal API call below is individually guarded. The Python symbol
     surface of UE 5.8 cannot be executed or introspected from the repo side"
    (scene_survey_far_side.py:79-82)

and its bounds helpers carry literal ``ASSUMED symbol:`` notes
(scene_survey_far_side.py:311, :337). Those guards are correct engineering, but
they mean a *degraded* result and a *working* result are indistinguishable from
the repo side: every one of those symbols is currently ``still_assumed``.

This harness converts assumption into observation. It boots THIS repo's own
project headless under ``-nullrhi``, calls each load-bearing symbol for real, and
classifies every one as exactly one of:

    runtime_verified    — called it in a live editor; the result was well-formed
                          and usable.
    runtime_unavailable — the symbol is not reflected here, or no editor exists
                          to ask. Nothing was observed.
    runtime_failed      — the symbol exists but raised, or returned a shape the
                          caller cannot use.
    still_assumed       — never reached; a prerequisite did not hold. This is the
                          status the repo is in TODAY, and it is NEVER a pass.

GATE
----
GREEN only when EVERY required probe is ``runtime_verified``. An unavailable or
unreached required symbol leaves the gate RED and the process exits non-zero.
``still_assumed`` is reported honestly and never counted as a pass — the entire
point of this file is that "we did not check" must not look like "it works".

Safe when no editor exists: it does not crash and does not pretend. It reports
``runtime_unavailable`` for every probe, says why, and exits non-zero.

READ-ONLY AGAINST PROJECT CONTENT
---------------------------------
Never saves a package, never authors a permanent actor, never writes a ``.umap``.
The single mutation is one TRANSIENT actor which is spawned, destroyed, and then
RE-OBSERVED to be absent from a fresh level enumeration — the destroy call's own
return value is not trusted. Dirty-package sets are snapshotted before and after
so cleanup is verified rather than asserted.

PROJECT GUARD
-------------
The project path is DERIVED from this file's location and cannot be overridden by
any flag or environment variable. A misconfigured invocation is physically unable
to boot a different project — in particular the caller's separate WorldForge
checkout or any Gloamstead project. See ``_resolve_uproject``.

DUAL MODE
---------
One file, two roles. Run normally it is the NEAR side (launcher). The editor runs
the very same file as the FAR side via ``-ExecutePythonScript``, discriminated by
the ``WF_FIXTURE_SMOKE_FAR_SIDE`` environment variable the near side sets. Passing
this file's own path is the established pattern (gloam_bridge_live.py:83, which is
how tools/bridge/far_side.py is launched from a path that also contains a space).

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/run_v2_6_fixture_smoke.py --dry-run
Live (boots the editor once, ~minutes):
    PYTHONUTF8=1 python tools/pipeline/run_v2_6_fixture_smoke.py
Report -> procedural/reports/scene_survey/fixture_smoke/v2_6_fixture_smoke_report.json
"""

import json
import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# shared constants — read by BOTH sides, so they cannot drift apart
# --------------------------------------------------------------------------- #
ENV_FAR_SIDE = "WF_FIXTURE_SMOKE_FAR_SIDE"
ENV_OUT = "WF_FIXTURE_SMOKE_OUT"
ENV_MAP = "WF_FIXTURE_SMOKE_MAP"

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_UPROJECT = REPO_ROOT / "WorldForge.uproject"

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "fixture_smoke"
REPORT_NAME = "v2_6_fixture_smoke_report.json"

SCHEMA_VERSION = "wf.scene_survey.fixture_smoke.v1"

# The smallest, most boring map in the repo: 12,554 bytes, one StaticMeshActor,
# non-World-Partition, and byte-identical in every committed census pass
# (procedural/evidence/ue5_8/census_ue58_postresave.json). A StaticMeshActor is
# also exactly what the component-bounds probe needs — it carries a
# UStaticMeshComponent, which IS a UPrimitiveComponent.
DEFAULT_MAP = "/Game/WorldForge/Terrain/Terrain_AshFlats_01_Preview"

STATUS_VERIFIED = "runtime_verified"
STATUS_UNAVAILABLE = "runtime_unavailable"
STATUS_FAILED = "runtime_failed"
STATUS_ASSUMED = "still_assumed"
ALL_STATUSES = (STATUS_VERIFIED, STATUS_UNAVAILABLE, STATUS_FAILED, STATUS_ASSUMED)

# Every probe here is REQUIRED. Each names a symbol scene_survey_far_side.py
# depends on, with the citation of the line that depends on it. There is no
# "optional" tier on purpose: an optional runtime probe is a probe whose failure
# nobody acts on.
#
# NOTE ON THE CITATIONS BELOW: scene_survey_far_side.py is under active edit by a
# parallel lane and grew from ~1375 to 1991 lines during this harness's own
# session, which moved every line number. The citations are pinned to the symbol
# text, not just the number -- re-locate with grep before trusting a number.
PROBES = (
    ("world_identity",
     "world.get_package().get_name() -- scene_survey_far_side.py:431"),
    ("actor_path_name",
     "Actor.get_path_name() -- scene_survey_far_side.py:659"),
    ("actor_world_membership",
     "Actor.get_world() identity vs the editor world -- "
     "scene_survey_far_side.py:1079-1085 (_all_level_actors)"),
    ("actor_transform",
     "get_actor_location/get_actor_rotation/get_actor_scale3d"),
    ("actor_bounds",
     "Actor.get_actor_bounds(only_colliding[, include_from_child_actors]) -- "
     "scene_survey_far_side.py:709 (marked ASSUMED at :700)"),
    ("component_bounds",
     "SystemLibrary.get_component_bounds(comp) -- "
     "scene_survey_far_side.py:729 (marked ASSUMED at :725)"),
    ("dirty_map_packages",
     "EditorLoadingAndSavingUtils.get_dirty_map_packages() -- "
     "scene_survey_far_side.py:1101"),
    ("dirty_content_packages",
     "EditorLoadingAndSavingUtils.get_dirty_content_packages() -- "
     "scene_survey_far_side.py:1101"),
    ("transient_spawn_destroy_reobserve",
     "EditorActorSubsystem.spawn_actor_from_class(..., transient=True) then "
     "destroy_actor, then destruction RE-OBSERVED through a NON-VACUOUS channel "
     "-- scene_survey_far_side.py:1204,1237,1252-1256"),
)
PROBE_NAMES = tuple(name for name, _ in PROBES)
REQUIRED_PROBES = PROBE_NAMES  # all of them; see the note above


def new_probe_table(status, detail):
    """A full probe table pinned to one status. Every probe key ALWAYS exists.

    A missing probe key would read as "not applicable" when it actually means
    "never ran", which is the exact confusion this file exists to remove.
    """
    return {name: {"status": status, "detail": detail, "symbol": symbol,
                   "observed": None}
            for name, symbol in PROBES}


# =========================================================================== #
# FAR SIDE — runs INSIDE the editor, launched via -ExecutePythonScript.
# =========================================================================== #
def far_side_main():
    """Probe the live symbol surface and write raw observations to ENV_OUT.

    Emits observations only. It computes no gate and no pass/fail verdict: the
    near side derives those. A far side that graded itself would be attesting to
    its own success.
    """
    import traceback

    import unreal  # provided by the UE Python runtime

    out_path = os.environ.get(ENV_OUT)
    map_path = os.environ.get(ENV_MAP) or DEFAULT_MAP

    doc = {
        "far_side_ran": True,
        "map_requested": map_path,
        "map_loaded": None,
        "observed_engine_version": None,
        "observed_uproject": None,
        "probes": new_probe_table(
            STATUS_ASSUMED, "the far side aborted before this probe was reached"),
        "safety": {
            "dirty_map_packages_pre": None,
            "dirty_map_packages_post": None,
            "dirty_content_packages_pre": None,
            "dirty_content_packages_post": None,
            "target_map_dirty_after": None,
            "packages_saved": 0,
            "permanent_actors_authored": 0,
        },
        "notes": [],
        "error": None,
        "traceback": None,
    }

    def log(msg):
        try:
            unreal.log("[v2.6-fixture-smoke] " + str(msg))
        except Exception:  # noqa: BLE001 — logging must never fail the run
            pass

    def record(name, status, detail, observed=None):
        if status not in ALL_STATUSES:
            raise ValueError("illegal probe status " + repr(status))
        rec = doc["probes"][name]
        rec["status"] = status
        rec["detail"] = str(detail)
        rec["observed"] = observed
        log("{}: {} ({})".format(name, status, detail))

    def write():
        if not out_path:
            log("FATAL: " + ENV_OUT + " is unset; nowhere to write observations")
            return
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, sort_keys=True)
            log("wrote observations -> " + out_path)
        except Exception:  # noqa: BLE001
            log("FATAL: could not write observations")

    def finite3(value):
        """[x, y, z] of finite floats, or None. Never substitutes zeros."""
        import math
        try:
            out = [float(value[0]), float(value[1]), float(value[2])]
        except Exception:  # noqa: BLE001
            return None
        return out if all(math.isfinite(v) for v in out) else None

    def xyz(vec):
        try:
            return finite3([vec.x, vec.y, vec.z])
        except Exception:  # noqa: BLE001
            return None

    def pyr(rot):
        try:
            return finite3([rot.pitch, rot.yaw, rot.roll])
        except Exception:  # noqa: BLE001
            return None

    def why(exc):
        return "{}: {}".format(type(exc).__name__, exc)

    try:
        # --- identity of the process we are actually inside -----------------
        try:
            doc["observed_engine_version"] = unreal.SystemLibrary.get_engine_version()
        except Exception as exc:  # noqa: BLE001
            doc["notes"].append("engine version unreadable: " + why(exc))
        try:
            doc["observed_uproject"] = unreal.Paths.get_project_file_path()
        except Exception as exc:  # noqa: BLE001
            doc["notes"].append("project file path unreadable: " + why(exc))

        # --- load the target map (proven pattern: wf_map_actor_census.py:47-49)
        try:
            les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
            doc["map_loaded"] = bool(les.load_level(map_path))
        except Exception as exc:  # noqa: BLE001
            doc["map_loaded"] = False
            doc["notes"].append("load_level raised: " + why(exc))

        if not doc["map_loaded"]:
            # Everything downstream is about a loaded world. Leaving the probes
            # at still_assumed is the honest state: nothing was observed.
            doc["error"] = "map {} did not load; no probe could be reached".format(map_path)
            write()
            return

        # --- probe: world identity ------------------------------------------
        world = None
        world_package = None
        try:
            ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            world = ues.get_editor_world()
        except Exception as exc:  # noqa: BLE001
            record("world_identity", STATUS_UNAVAILABLE,
                   "UnrealEditorSubsystem.get_editor_world is unavailable: " + why(exc))
        if world is None and doc["probes"]["world_identity"]["status"] == STATUS_ASSUMED:
            record("world_identity", STATUS_FAILED,
                   "get_editor_world() returned None inside a loaded map")
        elif world is not None:
            try:
                pkg = world.get_package()
            except Exception as exc:  # noqa: BLE001
                pkg = None
                record("world_identity", STATUS_UNAVAILABLE,
                       "World.get_package is not reflected: " + why(exc))
            if pkg is not None:
                try:
                    world_package = pkg.get_name()
                except Exception as exc:  # noqa: BLE001
                    record("world_identity", STATUS_UNAVAILABLE,
                           "Package.get_name is not reflected: " + why(exc))
                else:
                    if isinstance(world_package, str) and world_package.strip():
                        record("world_identity", STATUS_VERIFIED,
                               "world.get_package().get_name() returned a usable "
                               "package name", world_package)
                    else:
                        record("world_identity", STATUS_FAILED,
                               "world.get_package().get_name() returned an unusable "
                               "value: {!r}".format(world_package))

        # --- enumerate actors (proven: wf_map_actor_census.py:51) ------------
        actors = None
        eas = None
        try:
            eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actors = list(eas.get_all_level_actors())
        except Exception as exc:  # noqa: BLE001
            doc["notes"].append("get_all_level_actors failed: " + why(exc))

        if not actors:
            doc["notes"].append(
                "no actors enumerated in {}; the per-actor probes could not be "
                "reached and remain still_assumed".format(map_path))
            write()
            return

        subject = actors[0]

        # --- probe: actor path name -----------------------------------------
        try:
            path_name = subject.get_path_name()
        except Exception as exc:  # noqa: BLE001
            record("actor_path_name", STATUS_UNAVAILABLE,
                   "Actor.get_path_name is not reflected: " + why(exc))
            path_name = None
        else:
            if isinstance(path_name, str) and path_name.strip():
                record("actor_path_name", STATUS_VERIFIED,
                       "Actor.get_path_name() returned a usable object path", path_name)
            else:
                record("actor_path_name", STATUS_FAILED,
                       "Actor.get_path_name() returned {!r}".format(path_name))

        # --- probe: actor world membership -----------------------------------
        # Two independent channels must agree: the actor's own get_world()
        # package, and the actor's presence in the level enumeration. Either one
        # alone could be satisfied by an actor from some other world.
        try:
            actor_world = subject.get_world()
        except Exception as exc:  # noqa: BLE001
            record("actor_world_membership", STATUS_UNAVAILABLE,
                   "Actor.get_world is not reflected: " + why(exc))
        else:
            actor_world_pkg = None
            try:
                actor_world_pkg = actor_world.get_package().get_name()
            except Exception as exc:  # noqa: BLE001
                doc["notes"].append("actor world package unreadable: " + why(exc))
            in_enumeration = path_name is not None and any(
                _safe_path(a) == path_name for a in actors)
            observed = {
                "actor_world_package": actor_world_pkg,
                "editor_world_package": world_package,
                "present_in_level_enumeration": in_enumeration,
            }
            if actor_world_pkg is None:
                record("actor_world_membership", STATUS_UNAVAILABLE,
                       "the actor's world package could not be read, so membership "
                       "could not be established", observed)
            elif world_package is not None and actor_world_pkg == world_package \
                    and in_enumeration:
                record("actor_world_membership", STATUS_VERIFIED,
                       "the actor's world matches the editor world AND the actor is "
                       "present in the level enumeration", observed)
            else:
                record("actor_world_membership", STATUS_FAILED,
                       "world membership channels disagree", observed)

        # --- probe: actor transform ------------------------------------------
        transform = {}
        transform_errors = []
        for key, getter, conv in (("location", "get_actor_location", xyz),
                                  ("rotation", "get_actor_rotation", pyr),
                                  ("scale3d", "get_actor_scale3d", xyz)):
            try:
                fn = getattr(subject, getter)
            except Exception as exc:  # noqa: BLE001
                transform_errors.append("{} is not reflected: {}".format(getter, why(exc)))
                continue
            try:
                transform[key] = conv(fn())
            except Exception as exc:  # noqa: BLE001
                transform_errors.append("{} raised: {}".format(getter, why(exc)))
        if transform_errors and not transform:
            record("actor_transform", STATUS_UNAVAILABLE,
                   "; ".join(transform_errors), transform)
        elif transform_errors:
            record("actor_transform", STATUS_FAILED,
                   "; ".join(transform_errors), transform)
        elif all(transform.get(k) is not None for k in ("location", "rotation", "scale3d")):
            record("actor_transform", STATUS_VERIFIED,
                   "location, rotation and scale3d all returned finite 3-vectors",
                   transform)
        else:
            record("actor_transform", STATUS_FAILED,
                   "a transform getter returned a non-finite or unreadable vector",
                   transform)

        # --- probe: actor bounds ---------------------------------------------
        # Mirrors scene_survey_far_side.py:317-320 exactly: 2-arg form first,
        # 1-arg fallback. Which form actually answers is the finding.
        bounds_errors = []
        bounds_done = False
        for args, label in (((False, True), "get_actor_bounds(False, True)"),
                            ((False,), "get_actor_bounds(False)")):
            try:
                res = subject.get_actor_bounds(*args)
            except Exception as exc:  # noqa: BLE001
                bounds_errors.append("{}: {}".format(label, why(exc)))
                continue
            try:
                origin, extent = xyz(res[0]), xyz(res[1])
            except Exception as exc:  # noqa: BLE001
                bounds_errors.append("{} returned an unusable shape: {}".format(label, why(exc)))
                continue
            if origin is None or extent is None:
                bounds_errors.append(label + " returned non-finite components")
                continue
            record("actor_bounds", STATUS_VERIFIED,
                   "the ASSUMED signature at scene_survey_far_side.py:700 is real; "
                   "answered by " + label,
                   {"api_used": label, "origin": origin, "extent": extent,
                    "rejected_forms": bounds_errors})
            bounds_done = True
            break
        if not bounds_done:
            record("actor_bounds", STATUS_UNAVAILABLE if not bounds_errors else STATUS_FAILED,
                   "; ".join(bounds_errors) or "get_actor_bounds is unavailable")

        # --- probe: component bounds ------------------------------------------
        comps = None
        try:
            comps = list(subject.get_components_by_class(unreal.PrimitiveComponent))
        except Exception as exc:  # noqa: BLE001
            record("component_bounds", STATUS_UNAVAILABLE,
                   "could not enumerate PrimitiveComponents: " + why(exc))
        if comps is not None:
            if not comps:
                record("component_bounds", STATUS_ASSUMED,
                       "the subject actor carries no PrimitiveComponent, so "
                       "SystemLibrary.get_component_bounds was never called")
            else:
                try:
                    res = unreal.SystemLibrary.get_component_bounds(comps[0])
                except Exception as exc:  # noqa: BLE001
                    record("component_bounds", STATUS_UNAVAILABLE,
                           "SystemLibrary.get_component_bounds is not reflected or "
                           "raised: " + why(exc))
                else:
                    try:
                        origin, extent, radius = xyz(res[0]), xyz(res[1]), float(res[2])
                    except Exception as exc:  # noqa: BLE001
                        record("component_bounds", STATUS_FAILED,
                               "get_component_bounds returned an unusable shape "
                               "({!r}): {}".format(type(res).__name__, why(exc)))
                    else:
                        if origin is None or extent is None:
                            record("component_bounds", STATUS_FAILED,
                                   "get_component_bounds returned non-finite components")
                        else:
                            record("component_bounds", STATUS_VERIFIED,
                                   "the ASSUMED 3-tuple at "
                                   "scene_survey_far_side.py:725 is real",
                                   {"origin": origin, "extent": extent,
                                    "sphere_radius": radius})

        # --- probe: dirty package sets ----------------------------------------
        def dirty(getter_name):
            """(names, status, detail). None names == not observed, never []."""
            try:
                getter = getattr(unreal.EditorLoadingAndSavingUtils, getter_name)
            except Exception as exc:  # noqa: BLE001
                return None, STATUS_UNAVAILABLE, \
                    "EditorLoadingAndSavingUtils.{} is not reflected: {}".format(
                        getter_name, why(exc))
            try:
                pkgs = getter()
            except Exception as exc:  # noqa: BLE001
                return None, STATUS_FAILED, "{} raised: {}".format(getter_name, why(exc))
            try:
                names = sorted(str(p.get_name()) for p in pkgs)
            except Exception as exc:  # noqa: BLE001
                return None, STATUS_FAILED, \
                    "{} result is not a usable package sequence: {}".format(
                        getter_name, why(exc))
            # [] is a legitimate MEASUREMENT here: nothing is dirty. It is only a
            # lie when it stands in for an unreadable set, which the branches
            # above have already routed away.
            return names, STATUS_VERIFIED, \
                "{} returned a readable package set ({} entries)".format(
                    getter_name, len(names))

        maps_pre, map_status, map_detail = dirty("get_dirty_map_packages")
        record("dirty_map_packages", map_status, map_detail, maps_pre)
        doc["safety"]["dirty_map_packages_pre"] = maps_pre

        content_pre, content_status, content_detail = dirty("get_dirty_content_packages")
        record("dirty_content_packages", content_status, content_detail, content_pre)
        doc["safety"]["dirty_content_packages_pre"] = content_pre

        # --- probe: transient spawn -> destroy -> RE-OBSERVE absence ----------
        # RUNTIME FINDING (observed by this harness, 2026-07-27): an actor spawned
        # with transient=True is NOT returned by get_all_level_actors(). Measured
        # here as 1 -> 1 across the spawn, against 234 -> 235 for a NON-transient
        # spawn in committed evidence (procedural/evidence/ue5_8/runtime_smoke.json,
        # produced by wf_runtime_smoke.py:56 which passes no transient kwarg).
        #
        # The consequence is load-bearing and is the reason this probe carries two
        # channels. scene_survey_far_side.py:1252-1256 derives
        #     absent_after_cleanup = (path not in present)
        # where `present` comes from that same enumeration. For a transient actor
        # the path was NEVER in `present`, so the expression is True whether or not
        # destroy_actor did anything: the cleanup "verification" is VACUOUS -- it
        # cannot fail, so it proves nothing. Absence from a set that never
        # contained the item is not evidence of removal.
        #
        # So this probe demands a channel that could actually have said "no":
        # object validity after destroy. Enumeration absence is still recorded, but
        # it is explicitly NOT allowed to be the proof.
        spawn_obs = {
            "pie_state": None,
            "actors_before": len(actors),
            "actors_after_spawn": None,
            "actors_after_destroy": None,
            "spawned_path": None,
            "destroy_returned": None,
            "absent_after_cleanup": None,
            "visible_in_enumeration_after_spawn": None,
            "validity_channel": None,
            "valid_before_destroy": None,
            "valid_after_destroy": None,
            "enumeration_absence_is_vacuous": None,
        }

        def validity(obj):
            """(is_valid, channel) or (None, None) if no channel answered.

            Tried in order; whichever answers is recorded, so a signature drift
            degrades to a named reason instead of a silent False.
            """
            try:
                return bool(unreal.SystemLibrary.is_valid(obj)), \
                    "SystemLibrary.is_valid"
            except Exception:  # noqa: BLE001
                pass
            try:
                return bool(obj.is_valid()), "UObject.is_valid"
            except Exception:  # noqa: BLE001
                pass
            try:
                return (not bool(obj.is_actor_being_destroyed())), \
                    "not Actor.is_actor_being_destroyed"
            except Exception:  # noqa: BLE001
                pass
            return None, None
        pie = None
        try:
            pie = bool(unreal.get_editor_subsystem(
                unreal.LevelEditorSubsystem).is_in_play_in_editor())
        except Exception as exc:  # noqa: BLE001
            doc["notes"].append("PIE state unreadable: " + why(exc))
        spawn_obs["pie_state"] = pie
        if pie is not False:
            # scene_survey_far_side.py:594-605 — spawn/destroy silently no-op in
            # PIE, so a spawn here could report a placement that never existed.
            record("transient_spawn_destroy_reobserve", STATUS_ASSUMED,
                   "refused to spawn: play-in-editor state is {!r} and spawn/destroy "
                   "silently no-op during PIE".format(pie), spawn_obs)
        elif eas is None:
            record("transient_spawn_destroy_reobserve", STATUS_UNAVAILABLE,
                   "EditorActorSubsystem is unavailable", spawn_obs)
        else:
            spawned = None
            try:
                spawned = eas.spawn_actor_from_class(
                    unreal.StaticMeshActor, unreal.Vector(0.0, 0.0, 0.0),
                    unreal.Rotator(0.0, 0.0, 0.0), transient=True)
            except Exception as exc:  # noqa: BLE001
                record("transient_spawn_destroy_reobserve", STATUS_UNAVAILABLE,
                       "spawn_actor_from_class(..., transient=True) is not reflected "
                       "or raised: " + why(exc), spawn_obs)
            if spawned is None and \
                    doc["probes"]["transient_spawn_destroy_reobserve"]["status"] \
                    == STATUS_ASSUMED:
                record("transient_spawn_destroy_reobserve", STATUS_FAILED,
                       "spawn_actor_from_class returned None", spawn_obs)
            elif spawned is not None:
                spawn_obs["spawned_path"] = _safe_path(spawned)
                # Channel 1 (enumeration) -- recorded, but NOT trusted as proof.
                mid = None
                try:
                    mid = [_safe_path(a) for a in eas.get_all_level_actors()]
                except Exception as exc:  # noqa: BLE001
                    doc["notes"].append("post-spawn enumeration failed: " + why(exc))
                if mid is not None:
                    spawn_obs["actors_after_spawn"] = len(mid)
                    spawn_obs["visible_in_enumeration_after_spawn"] = \
                        spawn_obs["spawned_path"] in mid
                # Channel 2 (validity) -- the channel that can actually say "no".
                valid_before, channel = validity(spawned)
                spawn_obs["valid_before_destroy"] = valid_before
                spawn_obs["validity_channel"] = channel

                try:
                    spawn_obs["destroy_returned"] = bool(eas.destroy_actor(spawned))
                except Exception as exc:  # noqa: BLE001
                    doc["notes"].append("destroy_actor raised: " + why(exc))

                after = None
                try:
                    after = [_safe_path(a) for a in eas.get_all_level_actors()]
                except Exception as exc:  # noqa: BLE001
                    doc["notes"].append("post-destroy enumeration failed: " + why(exc))
                if after is not None:
                    spawn_obs["actors_after_destroy"] = len(after)
                    spawn_obs["absent_after_cleanup"] = \
                        spawn_obs["spawned_path"] not in after
                valid_after, _ = validity(spawned)
                spawn_obs["valid_after_destroy"] = valid_after

                # Absence proves removal ONLY if presence was observable to begin
                # with. If the spawn was never visible, the absence test could not
                # have failed, and we say so instead of banking it.
                spawn_obs["enumeration_absence_is_vacuous"] = (
                    spawn_obs["visible_in_enumeration_after_spawn"] is not True)

                if valid_before is None or valid_after is None:
                    record("transient_spawn_destroy_reobserve", STATUS_UNAVAILABLE,
                           "no object-validity channel answered, and enumeration "
                           "absence is vacuous for a transient actor, so the "
                           "destruction could not be RE-OBSERVED by any channel that "
                           "was capable of reporting failure", spawn_obs)
                elif valid_before and not valid_after:
                    detail = ("transient spawn destroyed and the destruction "
                              "RE-OBSERVED via {} (valid True -> False)".format(channel))
                    if spawn_obs["enumeration_absence_is_vacuous"]:
                        detail += (". NOTE: the transient actor was never visible in "
                                   "get_all_level_actors(), so the enumeration-absence "
                                   "channel used by scene_survey_far_side.py:1252-1256 "
                                   "is VACUOUS here and proves nothing on its own")
                    record("transient_spawn_destroy_reobserve", STATUS_VERIFIED,
                           detail, spawn_obs)
                elif not valid_before:
                    record("transient_spawn_destroy_reobserve", STATUS_FAILED,
                           "the spawned actor was already invalid BEFORE destroy, so "
                           "the spawn did not really produce a live actor", spawn_obs)
                else:
                    record("transient_spawn_destroy_reobserve", STATUS_FAILED,
                           "the actor is STILL VALID after destroy_actor returned {} "
                           "-- destruction did not happen".format(
                               spawn_obs["destroy_returned"]), spawn_obs)

        # --- post-mutation safety snapshot ------------------------------------
        maps_post, _, _ = dirty("get_dirty_map_packages")
        content_post, _, _ = dirty("get_dirty_content_packages")
        doc["safety"]["dirty_map_packages_post"] = maps_post
        doc["safety"]["dirty_content_packages_post"] = content_post
        if maps_post is not None and world_package:
            doc["safety"]["target_map_dirty_after"] = world_package in maps_post

    except Exception as exc:  # noqa: BLE001
        doc["error"] = why(exc)
        doc["traceback"] = traceback.format_exc()

    write()


def _safe_path(obj):
    try:
        return obj.get_path_name()
    except Exception:  # noqa: BLE001
        return None


def _safe_count(eas):
    try:
        return len(eas.get_all_level_actors())
    except Exception:  # noqa: BLE001
        return None


# =========================================================================== #
# NEAR SIDE — launcher, classifier, gate.
# =========================================================================== #
class GuardError(RuntimeError):
    """The project guard refused the run."""


def _resolve_uproject():
    """Return THIS repo's .uproject, or raise. Not overridable, by construction.

    The path is derived from this file's own location and compared against the
    expectation. There is deliberately no --project flag and no environment
    override: a knob that can point this harness at another project is a knob
    that can boot the caller's checkout, and booting the wrong project would
    produce runtime evidence attributed to the wrong tree.
    """
    resolved = EXPECTED_UPROJECT.resolve() if EXPECTED_UPROJECT.exists() \
        else EXPECTED_UPROJECT
    if resolved != EXPECTED_UPROJECT.resolve(strict=False):
        raise GuardError("resolved project {} is not this repo's {}".format(
            resolved, EXPECTED_UPROJECT))
    if not resolved.is_file():
        raise GuardError("this repo's project file does not exist: {}".format(resolved))
    if resolved.name != "WorldForge.uproject":
        raise GuardError("refusing to boot {}: only WorldForge.uproject is "
                         "permitted".format(resolved.name))
    # Belt and braces: never boot a project outside this checkout, and never one
    # that belongs to a consumer game project.
    if REPO_ROOT not in resolved.parents:
        raise GuardError("refusing to boot {}: it is outside this repository "
                         "({})".format(resolved, REPO_ROOT))
    lowered = str(resolved).lower()
    for forbidden in ("gloamstead",):
        if forbidden in lowered:
            raise GuardError("refusing to boot {}: path contains {!r}; this harness "
                             "boots only the WorldForge engine repo".format(
                                 resolved, forbidden))
    return resolved


def _resolve_ue_cmd(arg):
    """(path_or_None, source, detail). Never raises — absence is a reportable state."""
    if arg:
        p = Path(arg)
        return (p, "arg", str(p)) if p.is_file() else \
            (None, "arg", "--ue-cmd {} does not exist".format(p))
    env = os.environ.get("WF_UE_CMD")
    if env:
        p = Path(env)
        return (p, "env", str(p)) if p.is_file() else \
            (None, "env", "WF_UE_CMD={} does not exist".format(p))
    sys.path.insert(0, str(REPO_ROOT / "tools" / "bridge"))
    try:
        import paths as P  # tools/bridge/paths.py
        resolved = P.resolve_ue_cmd()
        p = Path(str(resolved))
        return (p, resolved.source, str(p)) if p.is_file() else \
            (None, resolved.source, "{} does not exist".format(p))
    except Exception as exc:  # noqa: BLE001
        return None, "unresolved", "{}: {}".format(type(exc).__name__, exc)


def _classify(far_doc, launch_detail):
    """Derive the probe table from far-side observations, or from their absence."""
    if far_doc is None:
        return new_probe_table(STATUS_UNAVAILABLE, launch_detail)
    probes = new_probe_table(
        STATUS_ASSUMED, "the far side produced no record for this probe")
    for name, rec in (far_doc.get("probes") or {}).items():
        if name not in probes or not isinstance(rec, dict):
            continue
        status = rec.get("status")
        if status not in ALL_STATUSES:
            probes[name]["status"] = STATUS_FAILED
            probes[name]["detail"] = "far side reported an illegal status {!r}".format(status)
            continue
        probes[name]["status"] = status
        probes[name]["detail"] = rec.get("detail")
        probes[name]["observed"] = rec.get("observed")
    return probes


def _human_summary(report):
    width = max(len(n) for n in PROBE_NAMES)
    lines = []
    lines.append("")
    lines.append("v2.6 fixture smoke -- {}".format(
        "GREEN" if report["gate_green"] else "RED"))
    lines.append("project : {}".format(report["project"]))
    lines.append("engine  : {}".format(report["ue_cmd"] or "<none resolved>"))
    lines.append("map     : {}".format(report["map"]))
    lines.append("observed: engine={} loaded={}".format(
        report["observed_engine_version"], report["map_loaded"]))
    lines.append("")
    lines.append("  {}   {}".format("PROBE".ljust(width), "STATUS"))
    lines.append("  {}   {}".format("-" * width, "-" * 20))
    for name in PROBE_NAMES:
        rec = report["probes"][name]
        lines.append("  {}   {}".format(name.ljust(width), rec["status"]))
    lines.append("")
    for name in PROBE_NAMES:
        rec = report["probes"][name]
        if rec["status"] != STATUS_VERIFIED:
            lines.append("  ! {}: {}".format(name, rec["detail"]))
    tally = report["tally"]
    lines.append("")
    lines.append("  verified={} unavailable={} failed={} still_assumed={}".format(
        tally[STATUS_VERIFIED], tally[STATUS_UNAVAILABLE],
        tally[STATUS_FAILED], tally[STATUS_ASSUMED]))
    if not report["gate_green"]:
        lines.append("  GATE RED: {}".format(report["gate_reason"]))
    lines.append("")
    return "\n".join(lines)


def near_side_main(argv=None):
    import argparse
    import subprocess
    import tempfile
    import time

    parser = argparse.ArgumentParser(
        description="Boot this repo's project headless and prove the v2.6 survey "
                    "API surface. There is intentionally no --project flag.")
    parser.add_argument("--map", default=DEFAULT_MAP,
                        help="UE package path of the map to probe (default: %(default)s)")
    parser.add_argument("--ue-cmd", default=None,
                        help="UnrealEditor-Cmd.exe (default: WF_UE_CMD, then "
                             "tools/bridge/paths.resolve_ue_cmd)")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="editor wall-clock budget in seconds (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve and guard everything, print the exact command "
                             "that WOULD run, and launch nothing")
    args = parser.parse_args(argv)

    report = {
        "schema_version": SCHEMA_VERSION,
        "gate_green": False,
        "gate_reason": None,
        "project": None,
        "ue_cmd": None,
        "ue_cmd_source": None,
        "map": args.map,
        "map_loaded": None,
        "observed_engine_version": None,
        "observed_uproject": None,
        "runtime_executed": False,
        "editor_exit_code": None,
        "elapsed_seconds": None,
        "command": None,
        "probes": new_probe_table(STATUS_UNAVAILABLE, "the harness did not get as far "
                                                      "as launching an editor"),
        "tally": {},
        "safety": None,
        "far_side_notes": [],
        "far_side_error": None,
        "stdout_tail": None,
    }

    # --- guard first; nothing else happens until the project is proven -------
    try:
        uproject = _resolve_uproject()
    except GuardError as exc:
        report["gate_reason"] = "project guard refused the run: {}".format(exc)
        return _finish(report, args)
    report["project"] = str(uproject).replace("\\", "/")

    ue_cmd, source, detail = _resolve_ue_cmd(args.ue_cmd)
    report["ue_cmd_source"] = source
    report["ue_cmd"] = str(ue_cmd).replace("\\", "/") if ue_cmd else None

    self_path = str(Path(__file__).resolve()).replace("\\", "/")
    # UE is a Windows process: absolute paths with forward slashes only.
    # Backslashes inside a quoted -ExecutePythonScript= value are re-parsed as C
    # escapes (gloam_bridge_live.py:72-75).
    command = ([str(ue_cmd)] if ue_cmd else ["<UnrealEditor-Cmd.exe unresolved>"]) + [
        report["project"],
        "-ExecutePythonScript={}".format(self_path),
        "-unattended", "-nopause", "-nosplash", "-nullrhi", "-stdout",
    ]
    report["command"] = command

    if ue_cmd is None:
        report["gate_reason"] = (
            "no editor is available, so nothing was observed: {}. Every probe is "
            "{} -- none of them is a pass.".format(detail, STATUS_UNAVAILABLE))
        report["probes"] = new_probe_table(STATUS_UNAVAILABLE, detail)
        return _finish(report, args)

    if args.dry_run:
        report["gate_reason"] = (
            "--dry-run: no editor was launched, so nothing was observed. The probe "
            "table below is the repo's HONEST current state, not a result.")
        report["probes"] = new_probe_table(
            STATUS_ASSUMED, "--dry-run: this symbol has never been executed")
        return _finish(report, args)

    # --- launch --------------------------------------------------------------
    tmp_dir = tempfile.mkdtemp(prefix="wf_v26_fixture_smoke_")
    far_out = str(Path(tmp_dir) / "far_side_observations.json").replace("\\", "/")
    env = dict(os.environ)
    env[ENV_FAR_SIDE] = "1"
    env[ENV_OUT] = far_out
    env[ENV_MAP] = args.map
    env["PYTHONUTF8"] = "1"

    started = time.time()
    stdout = ""
    try:
        proc = subprocess.run(command, env=env, timeout=args.timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        report["editor_exit_code"] = proc.returncode
        stdout = proc.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", "replace")
        report["editor_exit_code"] = None  # timed out: no exit code, no success
    except Exception as exc:  # noqa: BLE001
        stdout = "{}: {}".format(type(exc).__name__, exc)
    report["elapsed_seconds"] = round(time.time() - started, 2)
    report["stdout_tail"] = "\n".join(stdout.splitlines()[-40:]) or None

    far_doc = None
    if Path(far_out).is_file():
        try:
            with open(far_out, "r", encoding="utf-8") as fh:
                far_doc = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            report["far_side_error"] = "far-side JSON unreadable: {}: {}".format(
                type(exc).__name__, exc)

    if far_doc is None:
        launch_detail = (
            "the editor produced no far-side observations (exit_code={}, {}s). "
            "Nothing was observed.".format(
                report["editor_exit_code"], report["elapsed_seconds"]))
        report["probes"] = _classify(None, launch_detail)
    else:
        report["runtime_executed"] = bool(far_doc.get("far_side_ran"))
        report["map_loaded"] = far_doc.get("map_loaded")
        report["observed_engine_version"] = far_doc.get("observed_engine_version")
        report["observed_uproject"] = far_doc.get("observed_uproject")
        report["safety"] = far_doc.get("safety")
        report["far_side_notes"] = far_doc.get("notes") or []
        report["far_side_error"] = far_doc.get("error") or report["far_side_error"]
        report["probes"] = _classify(far_doc, "")

    return _finish(report, args)


def _finish(report, args):
    """Compute the gate, persist the report, print the summary, return an exit code."""
    tally = {status: 0 for status in ALL_STATUSES}
    for name in PROBE_NAMES:
        tally[report["probes"][name]["status"]] += 1
    report["tally"] = tally

    unmet = [n for n in REQUIRED_PROBES
             if report["probes"][n]["status"] != STATUS_VERIFIED]
    report["unmet_required_probes"] = unmet
    if not unmet:
        report["gate_green"] = True
        report["gate_reason"] = "every required symbol was executed in a live editor"
    elif not report["gate_reason"]:
        report["gate_reason"] = (
            "{} required symbol(s) are not runtime_verified: {}. still_assumed is "
            "NOT a pass.".format(len(unmet), ", ".join(unmet)))

    # A green gate is only meaningful if the run also stayed read-only.
    safety = report.get("safety") or {}
    if report["gate_green"] and safety.get("target_map_dirty_after") is True:
        report["gate_green"] = False
        report["gate_reason"] = (
            "every probe passed but the target map was left DIRTY, so the run was "
            "not read-only; refusing to report green")

    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORT_DIR / REPORT_NAME
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        report_path = str(out)
    except Exception as exc:  # noqa: BLE001
        report_path = "<unwritable: {}: {}>".format(type(exc).__name__, exc)

    sys.stdout.write(_human_summary(report))
    sys.stdout.write("  report -> {}\n\n".format(report_path))
    return 0 if report["gate_green"] else 1


# =========================================================================== #
if os.environ.get(ENV_FAR_SIDE) == "1":
    # Inside the editor. Observe, write, then ask for a clean shutdown -- a plain
    # -ExecutePythonScript boot otherwise sits in the editor loop until the near
    # side's timeout (scene_survey_far_side.py:1365-1374).
    far_side_main()
    try:
        import unreal
        unreal.SystemLibrary.quit_editor()
    except Exception:  # noqa: BLE001
        pass
elif __name__ == "__main__":
    sys.exit(near_side_main())
