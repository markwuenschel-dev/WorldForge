#!/usr/bin/env python3
"""run_mesh_synthesis.py -- the missing near side for asset synthesis.

WHY THIS FILE DID NOT EXIST, AND WHY THAT MATTERED
--------------------------------------------------
``tools/unreal/wfcore_mesh_synthesis.py`` is a complete, careful far side: it
builds a real StaticMesh asset from a ``wf.core.terrain_mesh_plan.v1``, refuses
to overwrite an existing asset (WF1279), and re-observes bounds FROM THE ASSET
ON DISK rather than echoing the spec back. And nothing has ever launched it. An
exhaustive search of the repository -- tracked and untracked, all file types --
found no setter of ``WF_MS_SPEC`` or ``WF_MS_OUT`` and no caller of the module
outside its own docstring.

So asset synthesis was specified and unbuilt: ``terrain_mesh_provider`` emits a
validated plan, the far side consumes one, and no code joined them. Compare
``wfcore_unreal_sink.py``, which has both a near side and a 189-check suite.
That asymmetry is why ``mesh_synthesis`` could be declared in the capability
vocabulary while nothing in the repository could produce a mesh.

WHAT THIS DOES
--------------
Plans a terrain mesh, writes the spec, boots a headless editor with the far
side's environment contract satisfied, and then VALIDATES the far side's result
document -- because ``wf.core.mesh_synthesis_result.v1`` had no validator
either. A far side that reports its own success with nothing checking it is the
same shape as a cook report the pipeline writes for itself.

THE RESULT IS GRADED, NOT TRUSTED
---------------------------------
``created`` and ``saved`` are the far side's own booleans. They are recorded,
and they are not the verdict. The verdict is re-derived from the numbers the far
side re-observed from the asset on disk: a mesh that claims creation must carry
a positive vertex and triangle count and non-degenerate bounds, its triangle
count must equal the plan's exactly, and its render-vertex count must fall inside
the bracket a build can legitimately produce. A far side that wrote nothing and
reported ``created: true`` reads exactly like one that worked, unless somebody
checks.

Usage:
    cd tools && MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' PYTHONUTF8=1 \\
        python pipeline/run_mesh_synthesis.py \\
            --asset-path /Game/WorldForge/Generated/Meshes/SM_WF_Synth_01 \\
            --ue-cmd "D:/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"

Exit 0 = the mesh was created AND the re-derived checks pass.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from pipeline import terrain_mesh_provider as TMP      # noqa: E402
from wfcore.failure import FailureCode as C            # noqa: E402

FAR_SIDE = REPO_ROOT / "tools" / "unreal" / "wfcore_mesh_synthesis.py"
RESULT_SCHEMA = "wf.core.mesh_synthesis_result.v1"
REPORT_REL = Path("procedural") / "reports" / "core" / "mesh_synthesis"

DEFAULT_EDITOR_ARGS = ("-unattended", "-nopause", "-nosplash", "-nullrhi", "-stdout")


def build_editor_command(ue_cmd, uproject, script):
    # Forward slashes throughout: UE's command-line parser treats a trailing
    # backslash before a quote as an escape.
    return [str(ue_cmd), str(uproject).replace("\\", "/"),
            "-ExecutePythonScript={}".format(str(script).replace("\\", "/"))
            ] + list(DEFAULT_EDITOR_ARGS)


def run_editor(cmd, env_extra, timeout):
    env = dict(os.environ)
    env.update(env_extra)
    started = time.time()
    try:
        proc = subprocess.run(cmd, env=env, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return (proc.returncode, proc.stdout.decode("utf-8", "replace"),
                round(time.time() - started, 2))
    except subprocess.TimeoutExpired as exc:
        return (None, (exc.stdout or b"").decode("utf-8", "replace"),
                round(time.time() - started, 2))


def validate_result(doc, plan, strict=False):
    """Grade the far side's result. Returns List[(name, ok, detail, code)].

    Deliberately does NOT accept ``created``/``saved`` as the answer. Those are
    the thing under test reporting on itself.
    """
    checks = []

    def c(name, ok, detail="", code=C.CORE_SINK_APPLY_FAILED):
        checks.append((name, bool(ok), detail, None if ok else code))
        return ok

    if not isinstance(doc, dict):
        c("result_is_object", False, "far side wrote no parseable document")
        return checks

    c("result_schema", doc.get("far_side_schema") == RESULT_SCHEMA,
      "far_side_schema must be {}, got {!r}".format(
          RESULT_SCHEMA, doc.get("far_side_schema")))
    c("result_has_no_error", not doc.get("error"),
      "far side reported: {}".format(doc.get("error")))
    c("result_has_no_failure_codes", not doc.get("failure_codes"),
      "far side reported codes {}".format(doc.get("failure_codes")))

    if doc.get("error") or doc.get("failure_codes"):
        return checks

    # -- RE-DERIVED from what the far side observed on disk ------------------
    vc, tc = doc.get("vertex_count"), doc.get("triangle_count")
    c("vertex_count_measured", isinstance(vc, int) and vc > 0,
      "vertex_count is {!r}; a created mesh has vertices, and 'created: true' "
      "with no count is a claim rather than a measurement".format(vc))
    c("triangle_count_measured", isinstance(tc, int) and tc > 0,
      "triangle_count is {!r}".format(tc))

    want_v = plan.get("vertex_count")
    want_t = plan.get("triangle_count")

    # Triangles ARE comparable: a build neither creates nor removes faces.
    if isinstance(want_t, int):
        c("triangle_count_matches_plan", tc == want_t,
          "plan asked for {} triangles, the asset on disk has {}".format(want_t, tc))

    # Vertices are NOT directly comparable, and the first version of this check
    # asserted they were. It fired on the first real run: the plan built a
    # description with 1089 source vertices (33x33) and the asset on disk
    # reported 6144, which is exactly 2048 triangles x 3. Those are different
    # quantities -- a SOURCE vertex is a position in the mesh description, a
    # RENDER vertex is a (position, normal, UV, tangent) tuple, and UE's build
    # splits shared positions whenever their attributes differ. A per-face
    # normal on a heightfield splits every one.
    #
    # So the honest assertion is a bracket, not an equality: the built mesh must
    # have at least as many render vertices as the description had positions
    # (nothing is lost) and at most three per triangle (nothing is invented).
    # That still fails a mesh with the wrong topology; it just stops failing a
    # correct one for using the engine's own vocabulary.
    if isinstance(want_v, int) and isinstance(want_t, int) and isinstance(vc, int):
        c("vertex_count_within_build_bracket", want_v <= vc <= want_t * 3,
          "the asset on disk has {} render vertices; a build of a {}-position, "
          "{}-triangle description must land in [{}, {}] -- below means "
          "positions were lost, above means vertices were invented".format(
              vc, want_v, tc, want_v, want_t * 3))

    b = doc.get("observed_bounds_cm")
    c("bounds_non_degenerate",
      isinstance(b, (list, tuple)) and len(b) == 3
      and all(isinstance(v, (int, float)) and v > 0 for v in b),
      "observed_bounds_cm is {!r}; a mesh with a zero extent on any axis is "
      "degenerate, and this is re-observed from the asset rather than the "
      "spec".format(b))

    # Recorded, never the verdict.
    c("created_flag_agrees_with_measurement",
      bool(doc.get("created")) == (isinstance(vc, int) and vc > 0),
      "the far side's own 'created' flag ({!r}) contradicts its measured "
      "vertex count ({!r}); a flag that disagrees with its own atoms is the "
      "circular-trust pattern validate_runtime_state was fixed for".format(
          doc.get("created"), vc))
    return checks


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Plan a terrain mesh and synthesise it as a real StaticMesh.")
    ap.add_argument("--asset-path", required=True,
                    help="/Game/... package path for the new StaticMesh")
    ap.add_argument("--resolution", type=int, default=32)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--size-cm", type=float, default=3000.0)
    ap.add_argument("--height-cm", type=float, default=400.0)
    ap.add_argument("--ue-cmd", default=os.environ.get("UE_EDITOR_CMD"))
    ap.add_argument("--project", default=None)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default=None, help="report path")
    ap.add_argument("--regrade", action="store_true",
                    help="re-grade the stored far-side document for this asset "
                         "without booting an editor. The far side refuses to "
                         "overwrite an existing asset (WF1279), so a corrected "
                         "validator cannot be re-proved by re-running -- and "
                         "hand-editing a generated report would be worse.")
    args = ap.parse_args(argv)

    if args.regrade:
        op_dir = REPO_ROOT / REPORT_REL / Path(args.asset_path).name
        spec_p, far_p = op_dir / "spec.json", op_dir / "far_side.json"
        if not (spec_p.is_file() and far_p.is_file()):
            print("[mesh-synth] nothing to regrade under {}".format(op_dir),
                  file=sys.stderr)
            return 2
        plan = json.loads(spec_p.read_text(encoding="utf-8"))
        doc = json.loads(far_p.read_text(encoding="utf-8"))
        checks = validate_result(doc, plan, strict=True)
        failed = [c for c in checks if not c[1]]
        report = {
            "report_type": "wf.core.mesh_synthesis_run.v1",
            "asset_path": args.asset_path,
            "spec_path": str(spec_p.relative_to(REPO_ROOT)).replace("\\", "/"),
            "result_path": str(far_p.relative_to(REPO_ROOT)).replace("\\", "/"),
            # Carried from the original boot; a regrade opens no editor and must
            # not claim to have. Read from the previous report when present.
            "editor_exit_code": None,
            "regraded": True,
            "checks": [{"name": n, "ok": o, "detail": d, "code": k}
                       for (n, o, d, k) in checks],
            "failure_count": len(failed),
            "status": "ok" if not failed else "failed",
            "far_side": doc,
        }
        prev = op_dir / "run_report.json"
        if prev.is_file():
            try:
                old = json.loads(prev.read_text(encoding="utf-8"))
                report["editor_exit_code"] = old.get("editor_exit_code")
                report["editor_seconds"] = old.get("editor_seconds")
            except ValueError:
                pass
        prev.write_text(json.dumps(report, indent=2), encoding="utf-8")
        for (n, o, d, _k) in checks:
            if not o:
                print("  FAIL {}: {}".format(n, d))
        print("[mesh-synth] regraded -> {} : {}".format(prev, report["status"]))
        return 0 if report["status"] == "ok" else 1

    if not args.ue_cmd:
        print("[mesh-synth] no editor: pass --ue-cmd or set UE_EDITOR_CMD",
              file=sys.stderr)
        return 2
    uproject = Path(args.project) if args.project else (REPO_ROOT / "WorldForge.uproject")
    if not uproject.is_file():
        print("[mesh-synth] uproject not found: {}".format(uproject), file=sys.stderr)
        return 2

    # -- plan (no editor needed) -------------------------------------------
    plan = TMP.plan_terrain_mesh({
        "terrain_id": "wf_synth_probe",
        "asset_path": args.asset_path,
        "resolution": args.resolution,
        "seed": args.seed,
        "size_cm": args.size_cm,
        "height_cm": args.height_cm,
    })
    bad = [c for c in TMP.validate_terrain_plan(plan, strict=True) if not c[1]]
    if plan.get("refused") or bad:
        print("[mesh-synth] plan refused/invalid: {} {}".format(
            plan.get("refusal_reason"), [(c[0], c[2]) for c in bad]), file=sys.stderr)
        return 1

    op_dir = REPO_ROOT / REPORT_REL / Path(args.asset_path).name
    op_dir.mkdir(parents=True, exist_ok=True)
    spec_path = op_dir / "spec.json"
    result_path = op_dir / "far_side.json"
    spec_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    # -- boot -------------------------------------------------------------
    cmd = build_editor_command(args.ue_cmd, uproject, FAR_SIDE)
    print("[mesh-synth] booting: {}".format(" ".join(cmd)))
    rc, _stdout, secs = run_editor(cmd, {
        "WF_MS_SPEC": str(spec_path),
        "WF_MS_OUT": str(result_path),
    }, args.timeout)
    print("[mesh-synth] editor exited {} after {}s".format(rc, secs))

    doc = None
    if result_path.is_file():
        try:
            doc = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print("[mesh-synth] result unparseable: {}".format(exc), file=sys.stderr)

    checks = validate_result(doc, plan, strict=True)
    failed = [c for c in checks if not c[1]]

    report = {
        "report_type": "wf.core.mesh_synthesis_run.v1",
        "asset_path": args.asset_path,
        "spec_path": str(spec_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "result_path": str(result_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "editor_exit_code": rc,
        "editor_seconds": secs,
        "checks": [{"name": n, "ok": o, "detail": d, "code": k}
                   for (n, o, d, k) in checks],
        "failure_count": len(failed),
        # The verdict is re-derived, and an editor that did not exit cleanly
        # invalidates it regardless of what the document says.
        "status": "ok" if (rc == 0 and not failed) else "failed",
        "far_side": doc,
    }
    out = Path(args.out) if args.out else (op_dir / "run_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("[mesh-synth] report -> {}".format(out))

    for (n, o, d, _k) in checks:
        if not o:
            print("  FAIL {}: {}".format(n, d))
    print("[mesh-synth] {}".format("ACCEPTED" if report["status"] == "ok"
                                   else "NOT ACCEPTED"))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
