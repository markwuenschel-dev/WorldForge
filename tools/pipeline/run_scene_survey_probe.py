#!/usr/bin/env python3
r"""run_scene_survey_probe.py — v2.6 SceneSurveyForge operator command.

The single documented surface that runs a READ-ONLY scene survey against an external
UE 5.8 project. It boots the target project's editor headless, executes
tools/bridge/scene_survey_far_side.py inside it (which drives the compiled
USceneSurveyStatics primitives over the target map), then re-derives a
SceneSurveyReport from the WF_SURVEY_* markers on stdout and the far-side JSON —
without trusting the far side (runtime_executed=True only when a real process
returned; observed engine comes from the running editor, never a config file).

Read-only w.r.t. the target: never saves the map, authors no permanent actor, and
places no persistent marker (marker CLEARANCE is trace-probed, never spawned). The
first pass runs under -nullrhi and does the spatial work (enumeration + 6-class
support + marker clearance); camera capture (needs an RHI) and MeshForge proxy toggle
(needs a -game pass) are honestly reported as not-run-in-this-pass, so a -nullrhi
survey is status="blocked" pending those passes — never a faked "pass".

Determinism: --repeat N runs the survey N times and proves the spatial results are
byte-identical (determinism_hash); a mismatch is WF1094.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/run_scene_survey_probe.py --smoke   (bootless self-check)
Live (single-writer against a real project):
    PYTHONUTF8=1 python tools/pipeline/run_scene_survey_probe.py \
        --project "D:/Unreal Projects/Gloamstead5_8/Gloamstead5_8.uproject" \
        --map /Game/ThirdPerson/Lvl_ThirdPerson --anchor player \
        --sample-radius-cm 3000 --sample-step-cm 100 --temporary-markers 3 \
        --repeat 2 --strict
Report -> procedural/reports/scene_survey/runtime/scene_survey_report.json
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import scene_survey_contracts as SS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "runtime"
FAR_SIDE = REPO_ROOT / "tools" / "bridge" / "scene_survey_far_side.py"

RE_SUPPORT = re.compile(
    r"WF_SURVEY_SUPPORT total=(\d+) valid=(\d+) unsupported=(\d+) edge=(\d+) "
    r"blocked=(\d+) trace_error=(\d+) unknown=(\d+)")
RE_ENUM = re.compile(r"WF_SURVEY_ENUM actors=(\d+) components=(\d+)")
RE_MARKER = re.compile(
    r"WF_SURVEY_MARKER .*grounded=(\d) footprint=(\d) overlap=(\d) "
    r"clearance=(\d) accepted=(\d)")


def _resolve_paths(args):
    """Resolve engine root + UnrealEditor-Cmd via the bridge ladder (arg->env->registry)."""
    from bridge import paths as P
    engine_root = P.resolve_engine_root(args.engine_root)
    ue_cmd = P.resolve_ue_cmd(engine_root.value, args.ue_cmd)
    return engine_root, ue_cmd


def _run_editor(ue_cmd, uproject, script, env_extra, timeout):
    """Launch the target project's editor headless; return (exit_code, stdout, secs)."""
    env = dict(os.environ)
    env.update(env_extra)
    env["PYTHONUTF8"] = "1"
    cmd = [
        str(ue_cmd),
        str(uproject).replace("\\", "/"),
        "-ExecutePythonScript={}".format(str(script).replace("\\", "/")),
        "-unattended", "-nopause", "-nosplash", "-nullrhi", "-stdout",
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, env=env, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), round(time.time() - t0, 2)
    except subprocess.TimeoutExpired as exc:
        return None, (exc.stdout or b"").decode("utf-8", "replace"), round(time.time() - t0, 2)


def _parse_markers(stdout):
    """Extract the spatial result from the WF_SURVEY_* marker lines."""
    r = {"support": None, "enum": None, "markers": []}
    m = RE_SUPPORT.search(stdout or "")
    if m:
        keys = ("total", "valid", "unsupported", "edge", "blocked", "trace_error", "unknown")
        r["support"] = {k: int(v) for k, v in zip(keys, m.groups())}
    m = RE_ENUM.search(stdout or "")
    if m:
        r["enum"] = {"actors": int(m.group(1)), "components": int(m.group(2))}
    for mk in RE_MARKER.finditer(stdout or ""):
        g = [int(x) for x in mk.groups()]
        r["markers"].append(dict(zip(
            ("grounded", "footprint", "overlap", "clearance", "accepted"), g)))
    return r


def _spatial_hash(parsed):
    """Deterministic hash over the spatial result (the determinism unit)."""
    payload = json.dumps({"support": parsed["support"], "enum": parsed["enum"],
                          "markers": parsed["markers"]}, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _one_run(args, ue_cmd, out_json):
    env_extra = {
        "WF_SURVEY_OUT": str(out_json).replace("\\", "/"),
        "WF_SURVEY_MAP": args.map,
        "WF_SURVEY_ANCHOR": args.anchor,
        "WF_SURVEY_RADIUS_CM": str(args.sample_radius_cm),
        "WF_SURVEY_STEP_CM": str(args.sample_step_cm),
        "WF_SURVEY_MARKERS": str(args.temporary_markers),
        "WF_SURVEY_OPERATION_ID": args.operation_id,
    }
    if out_json.exists():
        out_json.unlink()  # never let a prior run's file masquerade as this one's
    code, stdout, secs = _run_editor(ue_cmd, args.project, FAR_SIDE, env_extra, args.timeout)
    far = {}
    if out_json.is_file():
        try:
            far = json.loads(out_json.read_text(encoding="utf-8"))
        except ValueError as exc:
            far = {"error": "unparseable far-side json: {}".format(exc)}
    return {"exit_code": code, "stdout": stdout, "secs": secs, "far": far,
            "parsed": _parse_markers(stdout)}


def _build_report(args, runs, determinism_ok):
    """Fold the runs into a SceneSurveyReport (per the v2.6 contract)."""
    last = runs[-1]
    parsed, far = last["parsed"], last["far"]
    sup = parsed.get("support") or {}
    en = parsed.get("enum") or {}
    runtime_executed = last["exit_code"] is not None
    markers = parsed.get("markers") or []
    grounded = sum(1 for mk in markers if mk.get("accepted"))
    overlaps = sum(1 for mk in markers if mk.get("overlap"))
    clearance_ok = all((not mk.get("accepted")) or mk.get("clearance") for mk in markers)

    fcodes = []
    # This -nullrhi pass does not capture cameras -> honestly blocked, not a fake pass.
    fcodes.append(C.SCENE_SURVEY_CAMERA_CAPTURE_MISSING)
    if not determinism_ok:
        fcodes.append(C.SCENE_SURVEY_DETERMINISM_MISMATCH)
    if far.get("error"):
        fcodes.append(C.SCENE_SURVEY_REPORT_INVALID)
    status = "fail" if (not determinism_ok or far.get("error")) else "blocked"

    report = {
        "report_id": "scene_survey_report_{}".format(args.operation_id),
        "operation_id": args.operation_id,
        "map_asset_path": args.map,
        "anchor": args.anchor,
        "camera_capture_ok": False,
        "actor_bounds_valid": bool(en.get("actors", 0) > 0 and not far.get("error")),
        "support_samples_total": int(sup.get("total", 0)),
        "support_samples_valid": int(sup.get("valid", 0)),
        "unsupported_regions": int(sup.get("unsupported", 0)),
        "edge_regions": int(sup.get("edge", 0)),
        "proxy_owners": 0,
        "proxies_disabled": False,
        "temporary_placements_grounded": int(grounded),
        "overlap_count": int(overlaps),
        "player_clearance_valid": bool(clearance_ok),
        "cleanup_verified": True,  # markers are trace-probed, never spawned: nothing to clean
        "determinism_hash": _spatial_hash(parsed),
        "runtime_mode": "live_survey_runtime" if runtime_executed else "deterministic_survey_simulation",
        "runtime_executed": runtime_executed,
        "evidence_paths": ["procedural/reports/scene_survey/runtime/{}".format(
            REPORT_DIR.joinpath("far_side_run{}.json".format(len(runs))).name)],
        "failure_codes": [str(x) for x in fcodes],
        "status": status,
        "schema_version": SS.RT_SURVEY_REPORT,
        "report_type": SS.RT_SURVEY_REPORT,
        "created_by": "worldforge.v2.6",
        "created_at": SS.AUTHORING_TS,
        "meta": {
            "engine_root": args.engine_root or "resolved",
            "observed_engine_version": far.get("observed_engine_version"),
            "uproject": far.get("resolved_uproject") or str(args.project),
            "runtime_executed": runtime_executed,
            "repeat": args.repeat,
            "determinism_consistent": determinism_ok,
            "per_run_hashes": [_spatial_hash(r["parsed"]) for r in runs],
            "anchor_actor": far.get("anchor_actor"),
            "camera_pass": far.get("camera_capture_reason"),
            "proxy_pass": far.get("proxy_pass_reason"),
        },
    }
    return report


def _smoke():
    """Bootless self-check: far-side present, contracts import, a synthetic report validates."""
    problems = []
    if not FAR_SIDE.is_file():
        problems.append("far-side script missing: {}".format(FAR_SIDE))
    example = SS._example_scene_survey_report()
    fails = [c for c in SS.validate_scene_survey_report(example, strict=True) if not c[1]]
    if fails:
        problems.append("example SceneSurveyReport fails validation: {}".format(
            [c[0] for c in fails][:4]))
    # a realistic blocked-pending-camera report must also validate
    blocked = SS._example_scene_survey_report(
        camera_capture_ok=False, status="blocked",
        failure_codes=[str(C.SCENE_SURVEY_CAMERA_CAPTURE_MISSING)])
    bfails = [c for c in SS.validate_scene_survey_report(blocked, strict=True) if not c[1]]
    if bfails:
        problems.append("blocked-pending-camera report fails validation: {}".format(
            [c[0] for c in bfails][:4]))
    if problems:
        for p in problems:
            print("[scene-survey-smoke] FAIL — {}".format(p))
        return 1
    print("[scene-survey-smoke] PASS — operator surface wired "
          "(far-side present, report contract satisfied)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 SceneSurveyForge operator command.")
    ap.add_argument("--smoke", action="store_true", help="bootless self-check; no UE launch")
    ap.add_argument("--target-repository", default=None)
    ap.add_argument("--project", default=None, help="external .uproject to survey")
    ap.add_argument("--engine-root", default=None)
    ap.add_argument("--ue-cmd", default=None)
    ap.add_argument("--map", default="/Game/ThirdPerson/Lvl_ThirdPerson")
    ap.add_argument("--anchor", default="player", choices=["player", "heart"])
    ap.add_argument("--capture", default="gameplay,elevated_oblique,top_down")
    ap.add_argument("--sample-radius-cm", type=float, default=3000.0)
    ap.add_argument("--sample-step-cm", type=float, default=100.0)
    ap.add_argument("--temporary-markers", type=int, default=3)
    ap.add_argument("--disable-debug-proxies", action="store_true")
    ap.add_argument("--cleanup", action="store_true")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--operation-id", default="op_v2_6_scene_survey_0001")
    args, _ = ap.parse_known_args(argv)

    if args.smoke:
        return _smoke()

    if not args.project:
        print("[scene-survey] FAIL — --project is required for a live survey "
              "(or use --smoke for the bootless self-check)")
        return 2

    _engine_root, ue_cmd = _resolve_paths(args)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    runs = []
    for i in range(1, max(1, args.repeat) + 1):
        out_json = REPORT_DIR / "far_side_run{}.json".format(i)
        print("[scene-survey] run {}/{} -> booting {} on {}".format(
            i, args.repeat, Path(str(args.project)).name, args.map))
        runs.append(_one_run(args, ue_cmd.value, out_json))

    hashes = [_spatial_hash(r["parsed"]) for r in runs]
    determinism_ok = len(set(hashes)) == 1 and runs[0]["parsed"]["support"] is not None
    survey = _build_report(args, runs, determinism_ok)

    # validate the domain SceneSurveyReport against its contract before writing.
    fails = [c for c in SS.validate_scene_survey_report(survey, strict=True) if not c[1]]
    if fails:
        print("[scene-survey] WARNING — survey failed self-validation: {}".format(
            [c[0] for c in fails][:6]))

    # Wrap the domain report in a house report so the report-integrity gate (which
    # scans *_report.json for a real meta block + checks + a bounded status) accepts
    # it. The domain SceneSurveyReport (with its own status vocab pass/fail/blocked)
    # rides under "survey"; the house wrapper carries build_meta + checks + ok/fail.
    checks = [
        {"name": "runtime_executed", "verdict": "pass" if survey["runtime_executed"] else "fail"},
        {"name": "support_samples_present",
         "verdict": "pass" if survey["support_samples_total"] > 0 else "fail"},
        {"name": "actors_enumerated", "verdict": "pass" if survey["actor_bounds_valid"] else "fail"},
        {"name": "deterministic", "verdict": "pass" if determinism_ok else "fail"},
        {"name": "cleanup_verified", "verdict": "pass" if survey["cleanup_verified"] else "fail"},
        {"name": "contract_valid", "verdict": "pass" if not fails else "fail"},
        {"name": "camera_capture", "verdict": "warn"},  # honest: pending a rendering pass
    ]
    house_status = "fail" if any(c["verdict"] == "fail" for c in checks) else "ok"
    wrapped = {
        "status": house_status,
        "checks": checks,
        "survey": survey,
        "meta": build_meta(
            command="run-scene-survey-probe", pack="worldforge_vertical_slice",
            strict=args.strict, status=house_status, record_count=1, records_total=1,
            report_type=SS.RT_SURVEY_REPORT),
    }

    out = REPORT_DIR / "scene_survey_report.json"
    out.write_text(json.dumps(wrapped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = survey  # for the summary print below

    print("[scene-survey] -> {}".format(out.relative_to(REPO_ROOT).as_posix()))
    for k in ("status", "runtime_executed", "support_samples_total", "support_samples_valid",
              "unsupported_regions", "edge_regions", "temporary_placements_grounded",
              "overlap_count", "player_clearance_valid", "cleanup_verified", "determinism_hash"):
        print("[scene-survey]   {:<28} = {}".format(k, report.get(k)))
    print("[scene-survey]   determinism_consistent       = {} ({})".format(
        determinism_ok, hashes))
    # exit non-zero unless a genuinely clean pass (this -nullrhi pass is blocked-pending-camera)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
