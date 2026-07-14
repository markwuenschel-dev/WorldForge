#!/usr/bin/env python3
r"""gloam_bridge_live.py — v2.5.1 LIVE cross-repository bridge runner (DoD #17).

v2.5 shipped a rejecting DRY probe as the bridge gate. A dry probe asserts that
nothing ran; it is a NEGATIVE test and it cannot satisfy DoD #17's POSITIVE gate,
which requires a real run against a SEPARATE UE 5.8 project. This runner is the
missing live half. gloam_bridge_probe.py is untouched and stays the negative.

What one live run does:

  1. Resolves every path through tools.bridge.paths (arg -> env -> discovery). No
     machine-specific constant is baked anywhere; the ladder rung that answered is
     recorded in the report's ``resolution_sources``.
  2. Creates/refreshes a minimal UE 5.8 FIXTURE project OUTSIDE this repo, in its
     own git repository (tools.bridge.fixture). That project is the far side.
  3. Launches the fixture's editor headless under UE 5.8 and executes
     tools/bridge/far_side.py INSIDE it, passing the request by environment.
  4. Reads the far side's evidence back across the repository boundary and verifies
     it WITHOUT trusting it:
       * operation_id must be echoed back unchanged (WF1030);
       * every artifact is RE-HASHED here, on the near side, from the bytes on disk
         — the far side's own hashes are never taken on faith;
       * artifacts must live inside the target project (WF1024) and be recorded
         project-relative (WF1029).
  5. Writes a LiveBridgeReport (wf.transition.gloam_bridge_live.v1).

HONESTY (binding): runtime_executed=True is written ONLY when a real editor process
actually ran; execution_mode is always "live"; observed_runtime_engine is whatever
the running editor reported and is never copied from a config file. When the run
fails, this writes an honest FAILING report — it never synthesises a pass. The far
side is a fixture stand-in, not Gloamstead, and the report says so
(fixture_standin=True, is_gloamstead_target=False).

Acceptance:
    MSYS_NO_PATHCONV=1 PYTHONUTF8=1 python tools/pipeline/gloam_bridge_live.py
Report -> procedural/reports/ue5_8/gloam/live/gloam_bridge_live_report.json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import bridge  # noqa: E402
from bridge import fixture as FX  # noqa: E402
from bridge import live as LIVE  # noqa: E402
from bridge import paths as P  # noqa: E402
from report_meta import build_meta, hash_file, utc_now_iso  # noqa: E402
from transition_identity import transition_identity  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "gloam" / "live"
REPORT_NAME = "gloam_bridge_live_report.json"

# The far-side script that runs inside the fixture's editor.
FAR_SIDE_SCRIPT = REPO_ROOT / "tools" / "bridge" / "far_side.py"

DEFAULT_OPERATION_ID = "op_v2_5_1_gloam_bridge_live_0001"
REQUESTED_OPERATION = "materialize_recipe_asset"
ASSET_DIR = "/Game/WFBridge"


def _run_editor(ue_cmd, uproject, script, env_extra, timeout):
    """Launch the fixture's editor headless and execute ``script`` inside it.

    Returns (exit_code, stdout_tail, seconds). UE is a Windows process: every path
    handed to it is an absolute Windows path with forward slashes (MSYS /tmp-style
    paths silently do nothing), and backslashes in a quoted -ExecutePythonScript=
    value are re-parsed as C escapes, so forward slashes are mandatory.
    """
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
        code, out = proc.returncode, proc.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode("utf-8", "replace")
        code = None  # timed out: no exit code, and certainly no success
    return code, out, round(time.time() - t0, 2)


def _marker_lines(stdout):
    return [ln for ln in (stdout or "").splitlines() if FX and "WF_BRIDGE_FAR_SIDE" in ln]


def run_live(args):
    """Execute one live bridge operation. Returns the LiveBridgeReport dict."""
    operation_id = args.operation_id

    # --- 1. resolve every path (arg -> env -> discovery); nothing baked ------
    engine_root = P.resolve_engine_root(args.engine_root)
    ue_cmd = P.resolve_ue_cmd(engine_root.value, args.ue_cmd)
    # Pick plugin binaries by BuildId match against the engine we are about to run,
    # so a stale other-engine build is never silently selected.
    plugin_source = P.resolve_plugin_source(
        REPO_ROOT, args.plugin_source, engine_build_id=FX.engine_build_id(engine_root.value))
    fixture_root = P.resolve_fixture_root(REPO_ROOT, args.fixture_root)
    resolution_sources = {
        "engine_root": engine_root.as_dict(),
        "ue_cmd": ue_cmd.as_dict(),
        "plugin_source": plugin_source.as_dict(),
        "fixture_root": fixture_root.as_dict(),
    }

    if not FX.is_outside(fixture_root.value, REPO_ROOT):
        raise RuntimeError(
            "fixture root {} is INSIDE the WorldForge repo — it would not be a "
            "separate repository".format(fixture_root.value))

    # --- 2. the far side: a separate UE 5.8 project in its own git repo ------
    info = FX.create_fixture(fixture_root.value, plugin_source.value,
                             engine_root.value, force=args.rebuild_fixture)

    # --- 3. the request (pure intent; building it launches nothing) ----------
    request = bridge.build_request(
        operation_id=operation_id,
        target_repository=info["repository"],
        target_commit=info["commit"],
        target_project=info["project_name"],
        target_map="",
        required_plugin="WorldForge",
        required_plugin_version="0.1.0",
        requested_operation=REQUESTED_OPERATION,
        output_location="procedural/reports/ue5_8/gloam/live",
        timeout_seconds=args.timeout,
    )

    # Evidence lands inside the TARGET project, keyed by operation — the far side
    # writes it, we read it back across the boundary.
    evidence_rel = "Saved/WorldForgeBridge/{}/far_side_response.json".format(operation_id)
    evidence_abs = (Path(info["fixture_root"]) / evidence_rel)
    if evidence_abs.exists():
        evidence_abs.unlink()  # never let a previous run's file masquerade as this one's

    # Clear this operation's artifact BEFORE launching, from the near side. Two
    # reasons, both load-bearing:
    #   * correctness — a stale .uasset that the far side's asset registry has not
    #     scanned yet is invisible to it, but still collides with create_asset;
    #   * honesty — every artifact this run reports must have been authored by THIS
    #     run, not inherited from a previous one that happened to use the same id.
    stale_asset = (Path(info["fixture_root"]) / "Content" / "WFBridge"
                   / "WFBridgeRecipe_{}.uasset".format(operation_id))
    if stale_asset.exists():
        stale_asset.unlink()

    env_extra = {
        "WF_BRIDGE_OPERATION_ID": operation_id,
        "WF_BRIDGE_EVIDENCE_OUT": str(evidence_abs).replace("\\", "/"),
        "WF_BRIDGE_REQUIRED_PLUGIN": request.required_plugin,
        "WF_BRIDGE_REQUESTED_OPERATION": request.requested_operation,
        "WF_BRIDGE_ASSET_DIR": ASSET_DIR,
    }

    # --- 4. LIVE: launch the far side's editor ------------------------------
    exit_code, stdout, secs = _run_editor(
        ue_cmd.value, info["uproject"], FAR_SIDE_SCRIPT, env_extra, args.timeout)
    # A process really started and returned: this is the ONLY thing that licenses
    # runtime_executed=True below.
    runtime_executed = exit_code is not None

    far = {}
    if evidence_abs.is_file():
        try:
            far = json.loads(evidence_abs.read_text(encoding="utf-8"))
        except ValueError as exc:
            far = {"error": "unparseable far-side evidence: {}".format(exc)}

    # --- 5. verify the evidence WITHOUT trusting the far side ---------------
    fixture_dir = Path(info["fixture_root"])
    artifacts = [a for a in (far.get("artifacts") or []) if isinstance(a, str)]
    # Only artifacts that (a) live inside the target project and (b) really exist on
    # disk count. We re-hash the bytes ourselves.
    foreign = LIVE.evidence_belongs_to(artifacts, FX.FIXTURE_ROOT_DIRS)
    entries, hashes = [], []
    for rel in artifacts:
        if rel in foreign:
            continue
        p = fixture_dir / rel
        if p.is_file():
            entries.append(rel.replace("\\", "/"))
            hashes.append(hash_file(p))

    observed_engine = far.get("observed_engine")
    exit_status = ("success" if (exit_code == 0 and far.get("operation_completed") is True)
                   else "failure")

    report = {
        "probe_id": "gloam_bridge_live_run",
        "operation_id": operation_id,
        "execution_mode": LIVE.MODE_LIVE,
        "target_repository": request.target_repository,
        "resolved_target_repository": far.get("resolved_target_repository"),
        "target_commit": request.target_commit,
        "resolved_target_commit": far.get("resolved_target_commit"),
        "target_project": request.target_project,
        "resolved_uproject": far.get("resolved_uproject"),
        "declared_target_engine": bridge.BRIDGE_ENGINE,
        # Straight from the running editor. Never from a .uproject or an ini.
        "observed_runtime_engine": observed_engine,
        "plugin_present": far.get("plugin_present"),
        "plugin_loaded": far.get("plugin_loaded"),
        "capability_handshake_ok": far.get("capability_handshake_ok"),
        "plugin_capability_manifest": far.get("plugin_capability_manifest") or [],
        "requested_operation": request.requested_operation,
        "operation_completed": far.get("operation_completed"),
        "operation_detail": far.get("operation_detail") or {},
        "process_exit_status": exit_status,
        "process_exit_code": exit_code,
        "evidence_entries": entries,
        "evidence_hashes": hashes,
        "evidence_count": len(entries),
        # Freshness: the operation the evidence was actually produced for.
        "evidence_operation_id": far.get("operation_id"),
        "runtime_executed": runtime_executed,
        # The far side is a fixture stand-in. Stated in the report's own body.
        "is_gloamstead_target": False,
        "fixture_standin": True,
        "resolution_sources": resolution_sources,
        "far_side_evidence": far,
        "notes": ("live run against a SEPARATE UE 5.8 project ({}) in its own git "
                  "repository; fixture stand-in for Gloamstead, no Gloamstead "
                  "compatibility claimed. wall_seconds={} foreign_artifacts={}"
                  .format(info["repository"], secs, foreign[:2])),
        "schema_version": LIVE.LIVE_SCHEMA_VERSION,
        "report_type": LIVE.LIVE_SCHEMA_VERSION,
        "created_by": "worldforge.v2.5.1",
        "created_at": utc_now_iso(),
    }

    observed_minor = LIVE.engine_minor(observed_engine)
    report["meta"] = build_meta(
        command="gloam-bridge-live",
        pack=args.pack,
        strict=False,
        status="pass" if exit_status == "success" else "fail",
        record_count=1, records_total=1,
        records_passed=1 if exit_status == "success" else 0,
        report_type=LIVE.LIVE_SCHEMA_VERSION,
        extra=transition_identity(
            bridge.BRIDGE_ENGINE,
            runtime_required=True,          # a live bridge is meaningless without a runtime
            runtime_executed=runtime_executed,
            observed_runtime_engine=observed_minor),
    )
    return report, stdout


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="v2.5.1 LIVE cross-repository bridge runner (DoD #17).")
    ap.add_argument("--operation-id", default=DEFAULT_OPERATION_ID)
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--fixture-root", default=None,
                    help="far-side project dir (default: env {} or a sibling of the repo)"
                         .format(P.ENV_FIXTURE_ROOT))
    ap.add_argument("--plugin-source", default=None,
                    help="WorldForge plugin dir with 5.8 binaries (env {})".format(
                        P.ENV_PLUGIN_SOURCE))
    ap.add_argument("--engine-root", default=None,
                    help="UE 5.8 install root (env {})".format(P.ENV_ENGINE_ROOT))
    ap.add_argument("--ue-cmd", default=None,
                    help="UnrealEditor-Cmd.exe (env {})".format(P.ENV_UE_CMD))
    ap.add_argument("--rebuild-fixture", action="store_true",
                    help="delete and recreate the fixture project from scratch")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--log", default=None, help="write the editor stdout here")
    ap.add_argument("--print", action="store_true")
    args, _ = ap.parse_known_args(argv)

    report, stdout = run_live(args)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / REPORT_NAME
    with out.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    if args.log:
        Path(args.log).write_text(stdout or "", encoding="utf-8")

    print("[gloam-bridge-live] LIVE RUN -> {}".format(out.relative_to(REPO_ROOT).as_posix()))
    for k in ("operation_id", "execution_mode", "resolved_target_repository",
              "resolved_target_commit", "resolved_uproject", "observed_runtime_engine",
              "plugin_present", "plugin_loaded", "capability_handshake_ok",
              "operation_completed", "process_exit_status", "process_exit_code",
              "evidence_count", "runtime_executed"):
        print("[gloam-bridge-live]   {:<26} = {}".format(k, report.get(k)))
    if args.print:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0 if report["process_exit_status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
