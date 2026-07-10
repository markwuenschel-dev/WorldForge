#!/usr/bin/env python3
r"""run_slice_forge_alpha.py — v2.0 Wave R integrated runtime slice matrix.

Produces (--run) and certifies (--gate) the 24-scenario SliceRuntimeReport matrix
proving the FULL integrated loop per scenario (launch -> grounded traversal -> NPC
pressure -> combat damage -> mission completion -> reward grant -> inventory/
progression mutation -> save/load roundtrip), headless, one crash-isolated `-game`
process per scenario.

It does NOT introduce new engine code: every runtime actor already ships in the
compiled game module (Source/WorldForge/WFRuntime.cpp -> UnrealEditor-WorldForge.dll).
Setting WF_NPC_SCENARIO_ID makes UWFRuntimeAutoSpawnSubsystem materialize the
grounded pawn + NPCs + objective + encounter manager at world-begin; WF_COMBAT_*
and WF_REWARD_* enable combat + reward; AWFEncounterManager::FinalizeReward emits
the WF_REWARD_* markers. This driver reuses run_reward_forge_alpha.run_game (the
proven launch) + evaluate (the reward verdict) and adds the grounded/NPC/combat
facet-marker parsing, then writes ONE SliceRuntimeReport per scenario — validated
against slice_contracts.validate_slice_runtime_report BEFORE writing, so a fake
"completed" report can never be emitted.

Nothing is fabricated: a report is slice_completed_runtime only when the real C++
markers prove every system fired (grounded arrival, NPC spawn/pressure, >=1 combat
damage with after<before, mission WF_DONE, reward genuine with state mutation +
save/load verified) and failure_codes is empty. Any gap -> failure_codes populated
+ slice_completed_runtime False.

Modes:
    --run [--limit N] [--only SSID] [--timeout S]  produce SliceRuntimeReports
    --smoke                                          run exactly one scenario
    --index                                          build the SliceEvidenceIndex
    --gate [--scenarios 24]                          certify 24/24 (shield gate)

Checkpoint/resume: --run skips a scenario that already has a valid completed
slice_runtime_<ssid>.json.

Acceptance (gate): PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_slice_forge_alpha.py \
    --gate --pack encounter_loop_world --scenarios 24 --strict
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
import slice_evidence as SE
import run_reward_forge_alpha as RB   # reuse run_game + evaluate + _load_reward_table
from failure_codes import FailureCode as F
from report_meta import build_meta, git_sha, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / SX.SLICE_RUNTIME_REPORTS_REL
INTEGRITY_DIR = REPO_ROOT / SX.SLICE_INTEGRITY_REPORTS_REL
SCEN_DIR = REPO_ROOT / SX.SLICE_SCENARIOS_REL
SLICE_ID = "worldforge_vertical_slice"
PACKAGE_BUILD_ID = "slicebuild_v2_0"

# baseline (light_pressure) vs high (standard_pressure) runtime tuning.
PROFILE_MAP = {"baseline": "light_pressure", "high": "standard_pressure"}
NPC_COUNT = {"baseline": 3, "high": 4}
DMG_PER_TICK = {"baseline": 6, "high": 8}

# --- grounded / NPC / combat facet markers (exact C++ formats) --------------- #
RE_AUTOSPAWN = re.compile(r"WF_AUTOSPAWN spawned scenario=(\S+) pawn=(\d+) obj=(\d+) mgr=(\d+)")
RE_PAWN = re.compile(r"WF_PAWN spawned_possessed controller=(\S+)")
RE_GBEGIN = re.compile(r"WF_GBEGIN grounded_pawn controller=(\S+)")
RE_GARRIVE = re.compile(r"WF_GARRIVE grounded=(\d+)")
RE_NPC_SPAWN = re.compile(r"WF_NPC_SPAWN count=(\d+)")
RE_NPC_PRESSURE = re.compile(r"WF_NPC_PRESSURE ")
RE_COMBAT_DMG = re.compile(r"WF_COMBAT_DAMAGE .*?before=([\d.]+) after=([\d.]+)")
RE_MISSION_DONE = re.compile(r"WF_DONE mission\.completed")


def load_scenarios():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SCEN_DIR.glob("vs_*.json"))]


def build_rec(scn):
    """Build a run_reward_forge_alpha-compatible rec from a slice scenario + its
    expected reward table (resolved by id, not recomputed from seed)."""
    prof = scn["encounter_profile"]
    table = RB._load_reward_table(scn["expected_reward_table_id"]) or {}
    entries = table.get("reward_entries") or []
    xp = round(sum(float(e.get("xp_amount") or 0.0)
                   for e in entries if e.get("reward_type") == "xp"), 4)
    items = [e["item_id"] for e in entries if e.get("reward_type") == "item" and e.get("item_id")]
    unlocks = [e["unlock_id"] for e in entries if e.get("reward_type") == "unlock" and e.get("unlock_id")]
    return {
        "map_id": scn["map_id"],
        "behavior_scenario_id": scn["slice_scenario_id"],   # -> WF_NPC_SCENARIO_ID (auto-spawn)
        "pressure_profile": PROFILE_MAP.get(prof, "light_pressure"),
        "npc_count": NPC_COUNT.get(prof, 3),
        "player_max_health": 100,
        "combat_source": "npc_pressure",
        "damage_per_tick": DMG_PER_TICK.get(prof, 6),
        "hazard_damage": 0,
        "reward_table_id": scn["expected_reward_table_id"],
        "reward_xp": xp,
        "reward_items": items,
        "reward_unlocks": unlocks,
    }


def parse_facets(text):
    m_auto = RE_AUTOSPAWN.search(text)
    m_pawn = RE_PAWN.search(text)
    m_gbegin = RE_GBEGIN.search(text)
    m_garrive = RE_GARRIVE.search(text)
    m_npc = RE_NPC_SPAWN.search(text)
    npc_count = int(m_npc.group(1)) if m_npc else 0
    dmg = [(float(a), float(b)) for a, b in RE_COMBAT_DMG.findall(text)]
    real_dmg = [(bf, af) for bf, af in dmg if af < bf]

    launched = bool(m_auto or m_gbegin or ("WF_BEGIN" in text) or ("WF_REWARD_START" in text))
    pawn_ok = ((m_pawn and m_pawn.group(1) not in ("None", "no", "No"))
               or (m_gbegin and m_gbegin.group(1) not in ("None", "no", "No"))
               or (m_auto and int(m_auto.group(2)) >= 1))
    return {
        "launched": launched,
        "player_spawned": bool(pawn_ok),
        "traversal_completed": bool(m_garrive and m_garrive.group(1) == "1"),
        "npc_behavior_seen": npc_count >= 1 or bool(RE_NPC_PRESSURE.search(text)),
        "combat_damage_seen": len(real_dmg) >= 1,
        "mission_completed": bool(RE_MISSION_DONE.search(text)),
        "damage_events": len(real_dmg),
        "npc_spawn_count": npc_count,
    }


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def build_report(scn, text):
    """Parse UE stdout into a SliceRuntimeReport (validated by caller)."""
    ssid = scn["slice_scenario_id"]
    fac = parse_facets(text)
    ev = RB.evaluate(text)
    reward_granted = bool(ev["genuine"])
    inv = bool(ev["inv_mutated"])
    prog = bool(ev["prog_mutated"])
    persisted = bool(ev["persisted"])
    save_slot = SX.REWARD_SAVE_SLOT  # v1.9 reward slot, never mission/combat

    # write telemetry sidecar so telemetry_paths points at a real file
    tel_rel = "{}/slice_telemetry_{}.json".format(SX.SLICE_RUNTIME_REPORTS_REL, ssid)
    _write_json(REPO_ROOT / tel_rel, {
        "slice_scenario_id": ssid, "map_id": scn["map_id"],
        "reward_verdict": ev["reason"], "grant_count": ev["grant_count"],
        "xp_granted": ev["xp_granted"], "damage_events": fac["damage_events"],
        "npc_spawn_count": fac["npc_spawn_count"],
        "schema_version": "wf.slice.telemetry.v1"})

    save_load_result = SX.SAVE_LOAD_ROUNDTRIP_OK if persisted else "failed"

    # failure_codes: one per unmet honesty requirement (empty == completed slice)
    fc = []
    if not fac["launched"]:
        fc.append(F.SLICE_LAUNCH_FAILED)
    if not fac["player_spawned"]:
        fc.append(F.SLICE_LAUNCH_FAILED)
    if not fac["traversal_completed"]:
        fc.append(F.SLICE_TRAVERSAL_MISSING)
    if not fac["npc_behavior_seen"]:
        fc.append(F.SLICE_NPC_EVIDENCE_MISSING)
    if not fac["combat_damage_seen"]:
        fc.append(F.SLICE_NPC_NO_DAMAGE)
    if not fac["mission_completed"]:
        fc.append(F.SLICE_MISSION_INCOMPLETE)
    if not reward_granted:
        fc.append(F.SLICE_REWARD_EVIDENCE_MISSING)
    if not (inv or prog):
        fc.append(F.SLICE_REWARD_WITHOUT_MUTATION)
    if save_load_result != SX.SAVE_LOAD_ROUNDTRIP_OK:
        fc.append(F.SLICE_SAVE_LOAD_FAILED)
    fc = sorted(set(fc))
    completed = len(fc) == 0

    doc = {
        "report_id": "slice_runtime_{}".format(ssid),
        "slice_id": SLICE_ID,
        "slice_scenario_id": ssid,
        "map_id": scn["map_id"],
        "mission_id": scn["mission_id"],
        "biome": scn["biome"],
        "mission_archetype": scn["mission_archetype"],
        "encounter_profile": scn["encounter_profile"],
        "seed": scn["seed"],
        "launched": fac["launched"],
        "player_spawned": fac["player_spawned"],
        "traversal_completed": fac["traversal_completed"],
        "npc_behavior_seen": fac["npc_behavior_seen"],
        "combat_damage_seen": fac["combat_damage_seen"],
        "mission_completed": fac["mission_completed"],
        "reward_granted": reward_granted,
        "inventory_mutated": inv,
        "progression_mutated": prog,
        "save_load_result": save_load_result,
        "save_slot": save_slot,
        "slice_completed_runtime": completed,
        "package_build_id": PACKAGE_BUILD_ID,
        "telemetry_paths": [tel_rel],
        "failure_codes": [str(c) for c in fc],
        "damage_events": fac["damage_events"],
        "npc_spawn_count": fac["npc_spawn_count"],
        "created_at": "live",
        "git_commit": git_sha(),
        "schema_version": SX.RT_SLICE_RUNTIME_REPORT,
        "report_type": SX.RT_SLICE_RUNTIME_REPORT,
    }
    return doc, completed


def run_one(scn, timeout=180):
    ssid = scn["slice_scenario_id"]
    rec = build_rec(scn)
    rc, text = RB.run_game(rec, timeout=timeout)
    doc, completed = build_report(scn, text)
    # validate BEFORE writing — never emit a schema-invalid or fake-green report.
    fails = [c for c in SX.validate_slice_runtime_report(doc, strict=True) if not c[1]]
    if fails:
        print("  [INVALID] {} — report failed schema: {}".format(ssid, [c[0] for c in fails][:4]))
        return False, doc
    _write_json(RUNTIME_DIR / "slice_runtime_{}.json".format(ssid), doc)
    tag = "DONE" if completed else "PARTIAL"
    print("  [{}] {} rc={} — {}".format(
        tag, ssid, rc, "slice_completed_runtime" if completed else ",".join(doc["failure_codes"])))
    return completed, doc


def already_done(ssid):
    p = RUNTIME_DIR / "slice_runtime_{}.json".format(ssid)
    if not p.is_file():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return d.get("slice_completed_runtime") is True and d.get("created_at") == "live"


def do_run(only=None, limit=None, timeout=180, force=False):
    scns = load_scenarios()
    if only:
        scns = [s for s in scns if s["slice_scenario_id"] == only]
    if limit:
        scns = scns[:limit]
    print("=" * 72)
    print("v2.0 Wave R — running {} slice scenario(s) headless (-game)".format(len(scns)))
    print("=" * 72)
    done = 0
    for scn in scns:
        ssid = scn["slice_scenario_id"]
        if not force and already_done(ssid):
            print("  [skip] {} (already slice_completed_runtime)".format(ssid))
            done += 1
            continue
        ok, _ = run_one(scn, timeout=timeout)
        done += 1 if ok else 0
    print("-" * 72)
    print("Wave R run: {}/{} slice_completed_runtime".format(done, len(scns)))
    return 0 if done == len(scns) else 1


def do_index(strict):
    rep = ValidationReport("pack", SLICE_ID, strict=strict)
    reports = SE.runtime_reports()
    completed = [d for _, d in reports
                 if isinstance(d, dict) and d.get("slice_completed_runtime") is True]
    ssids = sorted({d["slice_scenario_id"] for d in completed})
    expected = set(SE.manifest_scenario_ids())
    missing = sorted(expected - set(ssids))
    # reference the package report in the index if Wave P has produced one.
    pkg_path = SE.PACKAGE_DIR / "slice_package_{}.json".format(SLICE_ID)
    pkg_reports = ["slice_package_{}".format(SLICE_ID)] if pkg_path.is_file() else []
    idx = {
        "slice_id": SLICE_ID,
        "scenario_count_expected": SE.EXPECTED_SCENARIOS,
        "scenario_count_seen": len(ssids),
        "runtime_reports": list(ssids),
        "traversal_reports": list(ssids),
        "npc_reports": list(ssids),
        "combat_reports": list(ssids),
        "reward_reports": list(ssids),
        "save_load_reports": list(ssids),
        "package_reports": pkg_reports,
        "missing_evidence": missing,
        "stale_evidence": [],
        "integrity_result": "ok" if len(ssids) == SE.EXPECTED_SCENARIOS and not missing else "fail",
        "created_at": "live",
        "schema_version": SX.RT_SLICE_EVIDENCE_INDEX,
        "report_type": SX.RT_SLICE_EVIDENCE_INDEX,
    }
    checks = SX.validate_slice_evidence_index(idx, strict=True)
    fails = [c for c in checks if not c[1]]
    for name, ok, detail, code in checks:
        if not ok:
            rep.check("index::{}".format(name), ok, detail, code=code)
    _write_json(INTEGRITY_DIR / "slice_evidence_index_{}.json".format(SLICE_ID), idx)
    print("[index] wrote evidence index: {}/{} scenarios, integrity={}".format(
        len(ssids), SE.EXPECTED_SCENARIOS, idx["integrity_result"]))
    return 0 if not fails and idx["integrity_result"] == "ok" else 1


def do_gate(pack, scenarios_arg, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    # dogfood the completed-slice checker (green regardless of evidence)
    good = SX._example_slice_runtime_report()
    gfails = [c for c in SX.validate_slice_runtime_report(good, strict=True) if not c[1]]
    rep.check("dogfood::good_runtime_report_passes", len(gfails) == 0,
              "reference runtime report rejected: {}".format([c[0] for c in gfails][:4]),
              code=F.SLICE_REPORT_INTEGRITY_FAILED)
    for label, over in (
        ("no_state_mutation", {"inventory_mutated": False, "progression_mutated": False}),
        ("mission_incomplete", {"mission_completed": False}),
        ("forbidden_slot", {"save_slot": "WFCombat_State"}),
        ("dirty_failure_codes", {"failure_codes": ["WF677_SLICE_LAUNCH_FAILED"]}),
    ):
        bad = SX._example_slice_runtime_report(**over)
        bfails = [c for c in SX.validate_slice_runtime_report(bad, strict=True) if not c[1]]
        rep.check("dogfood::rejects_{}".format(label), len(bfails) > 0,
                  "fake-green runtime report '{}' must be rejected".format(label),
                  code=F.SLICE_NEGATIVE_ACCEPTED)

    expected_ids = set(SE.manifest_scenario_ids())
    reports = SE.runtime_reports()
    try:
        need = int(scenarios_arg)
    except (ValueError, TypeError):
        need = SE.EXPECTED_SCENARIOS
    completed = 0
    seen_ids = []
    for path, doc in reports:
        if doc is None:
            rep.check("runtime::{}::parses".format(path.stem), False,
                      "unparseable runtime report", code=F.SLICE_RUNTIME_REPORT_MISSING)
            continue
        ssid = doc.get("slice_scenario_id", path.stem)
        seen_ids.append(ssid)
        fails = [c for c in SX.validate_slice_runtime_report(doc, strict=True) if not c[1]]
        ok = len(fails) == 0 and doc.get("slice_completed_runtime") is True
        rep.check("runtime::{}::completed".format(ssid), ok,
                  "not a clean slice_completed_runtime: {}".format([c[0] for c in fails][:4]),
                  code=F.SLICE_RUNTIME_REPORT_MISSING)
        rep.check("runtime::{}::known_scenario".format(ssid),
                  (not expected_ids) or ssid in expected_ids,
                  "runtime report scenario id not in manifest", code=F.SLICE_UNKNOWN_SCENARIO_ID)
        if ok:
            completed += 1
    rep.check("runtime::matrix_complete", completed >= need,
              "runtime matrix {}/{} slice_completed_runtime (needs {}) — "
              "run 'run_slice_forge_alpha.py --run' (Wave R) to produce evidence"
              .format(completed, len(reports), need), code=F.SLICE_PARTIAL_MATRIX)
    rep.check("runtime::no_duplicate_scenarios", len(seen_ids) == len(set(seen_ids)),
              "duplicate scenario runtime reports", code=F.SLICE_DUPLICATE_SCENARIO_REPORT)

    rep.finalize()
    rep.set_meta(build_meta(command="run-vertical-slice-runtime", pack=pack, strict=strict,
                            status=rep.status, record_count=len(reports),
                            records_total=need, records_passed=completed,
                            report_type="wf.slice.runtime_matrix.v1"))
    rep.write(RUNTIME_DIR, "run_slice_forge_alpha_report.json")
    rep.print_summary("run-vertical-slice-runtime")
    return rep.exit_code


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 runtime slice matrix (produce + certify).")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--gate", action="store_true", help="certify existing runtime evidence")
    ap.add_argument("--run", action="store_true", help="drive UE headless, produce evidence")
    ap.add_argument("--smoke", action="store_true", help="run exactly one scenario")
    ap.add_argument("--index", action="store_true", help="build the SliceEvidenceIndex")
    ap.add_argument("--only", default=None, help="run only this slice_scenario_id")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="re-run even if already completed")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--scenarios", default="24")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    if args.smoke:
        sys.exit(do_run(only=args.only, limit=1, timeout=args.timeout, force=args.force))
    if args.run:
        sys.exit(do_run(only=args.only, limit=args.limit, timeout=args.timeout, force=args.force))
    if args.index:
        sys.exit(do_index(strict))
    sys.exit(do_gate(args.pack, args.scenarios, strict))


if __name__ == "__main__":
    main()
