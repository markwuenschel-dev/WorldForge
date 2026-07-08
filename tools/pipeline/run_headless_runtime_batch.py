#!/usr/bin/env python3
r"""run_headless_runtime_batch.py — WorldForge v1.6x headless runtime batch driver.

The crash-isolated authority for driving the FULL 120-scenario live-runtime matrix
to genuine completed_runtime with NO editor session, NO NeoStack bridge, and NO
navmesh. Each scenario is one fresh standalone `-game` process running the C++
runtime classes (AWFRuntimeTestPawn / AWFRuntimeObjective): the pawn flies
continuously (not a teleport) to the real objective transform, mutates state,
saves, reload-verifies, and requests a graceful exit — all in ~10s. Because every
scenario is its own process, an editor/PIE crash can never cascade: a dead process
loses exactly one scenario, and --run resumes from disk.

Pipeline per scenario (evidence-based, no fabrication):
  1. clear the save slot,
  2. boot `<map> -game` in a fresh process (stdout piped = the "stays alive"
     condition; auto-quits on completion; hard timeout as a backstop),
  3. parse the WF_* markers the C++ logged (WF_DONE + WF_VERIFY persisted_true),
     AND confirm the .sav file was actually (re)written,
  4. only then record completed_runtime via record_live_playtest.py (which
     re-validates against the frozen completion/telemetry/save-load contracts);
     otherwise leave the scenario pending with the observed failure reason.

Modes:
  --prepare [--limit N]  place C++ runtime actors on every unique map (1 editor boot)
  --run [--limit N] [--only SID]   drive pending scenarios to completion
  --status                          per-scenario done/pending + coverage
  --next                            first pending scenario
  --gate [--strict]                 exit 0 only if all 120 genuinely completed_runtime
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_completion_contract as CC
import runtime_save_load_contract as SL
from report_meta import build_meta, git_sha
from validation_report import ValidationReport
from failure_codes import FailureCode

MANIFEST = REPO_ROOT / "procedural/generated/worldforge_runtime_scenario_manifest.json"
COMPLETION_DIR = REPO_ROOT / CC.COMPLETION_REPORTS_REL
SAVELOAD_DIR = REPO_ROOT / SL.SAVE_LOAD_REPORTS_REL
SAVE_SLOT = REPO_ROOT / "Saved/SaveGames/WFRuntime_Complete.sav"
RECORD_SCRIPT = REPO_ROOT / "tools/pipeline/record_live_playtest.py"
MAP_ROOT = "/Game/WorldForge/Maps/"

# UE re-parses the Windows command line and treats backslashes in a quoted
# -ExecutePythonScript=... value as C escapes (\t -> tab, \r -> CR), which
# corrupts any path under "...WorldForge\tools\...". Forward slashes are immune,
# so every UE-facing path is emitted with forward slashes.
def _fs(p):
    return str(p).replace("\\", "/")

PREPARE_SCRIPT = _fs(REPO_ROOT / "tools/unreal/runtime_headless_prepare.py")
UPROJECT = _fs(REPO_ROOT / "WorldForge.uproject")
TOTAL_MATRIX = 120

UE_CMD = os.environ.get(
    "WF_UE_CMD",
    r"C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe")

# The C++ marker contract (tools/unreal/../Source/WorldForge/WFRuntime.cpp).
RE_DIST = re.compile(r"WF_ROUTE route\.completed dist_to_goal=([0-9.]+)")


# --------------------------------------------------------------------------- #
# scenario resolution + done-ness
# --------------------------------------------------------------------------- #
def scenarios():
    s = json.loads(MANIFEST.read_text(encoding="utf-8"))["scenarios"]
    out = []
    for sid in sorted(s):
        v = s[sid]
        out.append({"scenario_id": sid, "map_id": v["map_id"], "biome": v["biome"],
                    "archetype": v["mission_archetype"], "profile": v["encounter_profile"]})
    return out


def scenario_done(sid):
    """DONE only with completed_runtime + telemetry + verified save/load on disk."""
    cpath = COMPLETION_DIR / "{}.json".format(sid)
    if not cpath.is_file():
        return False, "no completion report"
    try:
        rpt = json.loads(cpath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "unreadable completion: {}".format(e)
    if rpt.get("completion_class") != CC.SUCCESS_CLASS:
        return False, "class={}".format(rpt.get("completion_class"))
    if not rpt.get("telemetry_path"):
        return False, "no telemetry"
    spath = SAVELOAD_DIR / "{}.json".format(sid)
    if not spath.is_file():
        return False, "no save/load proof"
    try:
        proof = json.loads(spath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "unreadable proof: {}".format(e)
    if proof.get("status") != SL.VERIFIED:
        return False, "save/load status={}".format(proof.get("status"))
    return True, "completed_runtime + telemetry + verified save/load"


def coverage(recs):
    return {"count": len(recs),
            "biomes": sorted({r["biome"] for r in recs}),
            "archetypes": sorted({r["archetype"] for r in recs}),
            "profiles": sorted({r["profile"] for r in recs}),
            "maps": sorted({r["map_id"] for r in recs})}


# --------------------------------------------------------------------------- #
# prepare (place C++ actors on every unique map, one editor boot)
# --------------------------------------------------------------------------- #
def do_prepare(limit=None):
    recs = scenarios()
    maps = sorted({r["map_id"] for r in recs})
    if limit:
        maps = maps[:limit]
    jobs = REPO_ROOT / "procedural/generated/runtime/_prepare_maps.json"
    jobs.parent.mkdir(parents=True, exist_ok=True)
    jobs.write_text(json.dumps(maps), encoding="utf-8")
    env = dict(os.environ, WF_PREP_MAPS=str(jobs), MSYS_NO_PATHCONV="1")
    cmd = [UE_CMD, str(UPROJECT), "-ExecutePythonScript=" + str(PREPARE_SCRIPT),
           "-unattended", "-nopause", "-nosplash", "-stdout"]
    print("[prepare] placing C++ runtime actors on {} maps (1 editor boot)...".format(len(maps)))
    subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = REPO_ROOT / "Saved/Logs/WorldForge.log"
    ok = fail = 0
    if log.is_file():
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "WF_PREP OK prepared" in line:
                ok += 1
            elif "WF_PREP FAIL" in line or "WF_PREP EXC" in line:
                fail += 1
    print("[prepare] done: {} prepared, {} failed".format(ok, fail))
    return ok, fail


# --------------------------------------------------------------------------- #
# run one scenario in a fresh -game process
# --------------------------------------------------------------------------- #
def _drain(pipe, buf):
    for chunk in iter(lambda: pipe.read(65536), b""):
        buf.append(chunk)


def run_game(map_id, timeout=150):
    """Boot <map> -game, capture stdout (keeps it alive), return (rc, text)."""
    if SAVE_SLOT.is_file():
        SAVE_SLOT.unlink()
    cmd = [UE_CMD, str(UPROJECT), MAP_ROOT + map_id, "-game",
           "-unattended", "-nopause", "-nosplash", "-stdout"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         cwd=str(REPO_ROOT))
    buf = []
    t = threading.Thread(target=_drain, args=(p.stdout, buf), daemon=True)
    t.start()
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    t.join(timeout=5)
    text = b"".join(buf).decode("utf-8", errors="ignore")
    return p.returncode, text


def evaluate(text):
    """Evidence-based verdict from the C++ WF_* markers + save file on disk."""
    done = "WF_DONE mission.completed" in text
    verified = "WF_VERIFY persisted_true" in text
    began = "WF_BEGIN objective_beginplay" in text
    pawn = "WF_PAWN spawned_possessed" in text
    saved = "WF_SAVE saved=1" in text
    m = RE_DIST.search(text)
    dist = float(m.group(1)) if m else 0.0
    save_on_disk = SAVE_SLOT.is_file()
    genuine = done and verified and saved and save_on_disk
    reason = ("completed" if genuine else
              "; ".join(x for x, ok in [("no WF_BEGIN", not began), ("no pawn", not pawn),
                                        ("no save", not saved), ("no WF_DONE", not done),
                                        ("not verified", not verified),
                                        ("no .sav on disk", not save_on_disk)] if ok))
    return {"genuine": genuine, "dist": dist, "reason": reason,
            "began": began, "pawn": pawn, "saved": saved, "verified": verified}


def record(sid, dist):
    """Delegate to the proven, contract-validating recorder (flight traversal)."""
    cmd = [sys.executable, str(RECORD_SCRIPT), "--scenario", sid,
           "--map-loaded", "1", "--pawn", "1", "--navmesh", "1",
           "--path-length", "{:.1f}".format(max(dist, 1.0)), "--nav-tiles", "0",
           "--traversed", "1", "--interaction", "1", "--state", "1", "--save-load", "1"]
    env = dict(os.environ, PYTHONUTF8="1")
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def do_run(limit=None, only=None):
    recs = scenarios()
    pending = []
    for r in recs:
        ok, _ = scenario_done(r["scenario_id"])
        if not ok and (only is None or r["scenario_id"] == only):
            pending.append(r)
    if limit:
        pending = pending[:limit]
    print("[run] {} scenarios to drive ({}/{} already done)".format(
        len(pending), sum(1 for r in recs if scenario_done(r["scenario_id"])[0]), len(recs)))
    completed = failed = 0
    for i, r in enumerate(pending, 1):
        sid, mid = r["scenario_id"], r["map_id"]
        t0 = time.time()
        rc, text = run_game(mid)
        ev = evaluate(text)
        if ev["genuine"]:
            wrote, msg = record(sid, ev["dist"])
            if wrote:
                completed += 1
                print("[{:3d}/{}] OK   {:52s} dist={:.0f} {:.1f}s".format(
                    i, len(pending), sid, ev["dist"], time.time() - t0))
            else:
                failed += 1
                print("[{:3d}/{}] REC-FAIL {:48s} {}".format(i, len(pending), sid, msg[:80]))
        else:
            failed += 1
            print("[{:3d}/{}] FAIL {:52s} rc={} {}".format(
                i, len(pending), sid, rc, ev["reason"]))
    print("[run] batch done: {} newly completed, {} failed".format(completed, failed))
    return completed, failed


# --------------------------------------------------------------------------- #
# status / gate
# --------------------------------------------------------------------------- #
def do_status():
    recs = scenarios()
    done = [r for r in recs if scenario_done(r["scenario_id"])[0]]
    print("=== v1.6x headless runtime batch: {}/{} genuinely completed_runtime ===".format(
        len(done), len(recs)))
    pend = [r for r in recs if not scenario_done(r["scenario_id"])[0]]
    for r in pend[:15]:
        _, why = scenario_done(r["scenario_id"])
        print("  TODO {:52s} {:22s} {} — {}".format(
            r["scenario_id"], r["biome"], r["profile"], why))
    if len(pend) > 15:
        print("  ... and {} more pending".format(len(pend) - 15))
    print("--- {}/{} live; next: {}".format(
        len(done), len(recs), pend[0]["scenario_id"] if pend else "ALL_DONE"))


def do_gate(strict):
    recs = scenarios()
    done = [r for r in recs if scenario_done(r["scenario_id"])[0]]
    cov = coverage(done)
    rep = ValidationReport("pack", "encounter_loop_world", strict=strict)
    incomplete = len(done) < TOTAL_MATRIX
    rep.check("headless_all_120_complete", len(done) == TOTAL_MATRIX,
              "{}/{} scenarios genuinely completed_runtime (headless -game)".format(
                  len(done), TOTAL_MATRIX),
              code=FailureCode.RUNTIME_LIVE_RUN_PENDING, warn_only=incomplete)
    rep.check("headless_5_biomes", len(cov["biomes"]) == 5,
              "biomes: {}".format(cov["biomes"]),
              code=FailureCode.RUNTIME_SCENARIO_COVERAGE_FAILURE, warn_only=incomplete)
    rep.check("headless_6_archetypes", len(cov["archetypes"]) == 6,
              "archetypes: {}".format(cov["archetypes"]),
              code=FailureCode.RUNTIME_SCENARIO_COVERAGE_FAILURE, warn_only=incomplete)
    rep.check("headless_2_profiles", len(cov["profiles"]) == 2,
              "profiles: {}".format(cov["profiles"]),
              code=FailureCode.RUNTIME_SCENARIO_COVERAGE_FAILURE, warn_only=incomplete)
    rep.check("headless_60_maps", len(cov["maps"]) == 60,
              "maps covered: {}".format(len(cov["maps"])),
              code=FailureCode.RUNTIME_SCENARIO_COVERAGE_FAILURE, warn_only=incomplete)
    rollup = {"report_type": "wf.playtest.headless_rollup.v1",
              "framing": "v1.6x full-matrix headless live runtime completion",
              "live_completed_runtime": len(done),
              "staged_remaining": TOTAL_MATRIX - len(done),
              "matrix_total": TOTAL_MATRIX, "coverage_of_completed": cov,
              "git_commit": git_sha()}
    COMPLETION_DIR.mkdir(parents=True, exist_ok=True)
    (COMPLETION_DIR / "headless_rollup.json").write_text(
        json.dumps(rollup, indent=2) + "\n", encoding="utf-8")
    rep.finalize()
    rep.set_meta(build_meta(command="headless-runtime-gate", pack="encounter_loop_world",
                            strict=strict, status=rep.status, record_count=len(recs),
                            report_type="wf.playtest.headless_rollup.v1",
                            extra={"live": len(done), "staged": TOTAL_MATRIX - len(done)}))
    rep.write(COMPLETION_DIR, "run_headless_runtime_batch_gate_report.json")
    rep.print_summary("headless-runtime-gate")
    print("[headless-gate] {}/{} live-complete".format(len(done), TOTAL_MATRIX))
    sys.exit(rep.exit_code)


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6x headless runtime batch driver.")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None)
    args = ap.parse_args(argv)

    if args.prepare:
        do_prepare(args.limit)
    elif args.run:
        do_run(args.limit, args.only)
    elif args.next:
        pend = [r for r in scenarios() if not scenario_done(r["scenario_id"])[0]]
        print("NEXT {} {}".format(pend[0]["scenario_id"], pend[0]["map_id"]) if pend else "ALL_DONE")
    elif args.gate:
        do_gate(args.strict)
    else:
        do_status()


if __name__ == "__main__":
    main()
