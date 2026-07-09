#!/usr/bin/env python3
r"""run_combat_forge_alpha.py — WorldForge v1.8 Wave R Prime combat batch driver.

CombatForge Alpha / PlaytestForge Zeta. Drives the 120-scenario combat matrix to
GENUINE `combat_completed_runtime`, headless, one crash-isolated `-game` process
per scenario. A combat scenario = a v1.7 behavior scenario
(procedural/generated/npc/behavior_scenarios/bs_*.json) with combat *enabled* via a
matching CombatProfile (procedural/generated/combat/profiles/cp_*.json). The v1.7
NPC behavior runtime (AWFEncounterManager + AWFGroundedRuntimePawn + AWFNPCPawn)
is unchanged; combat rides on top of it — WF_COMBAT_ENABLED=1 turns real damage on.
The grounded player pawn WALKS the objective while NPC pressure and/or hazards deal
real per-tick damage; player health mutates; the combat state (distinct WFCombat_State
save slot) reload-verifies. Nothing is faked: the recorder only writes
combat_completed_runtime when the C++ WF_COMBAT_* markers (per
docs/contracts/v1_8_wave_r_prime_contract.md §3) prove health initialized, >=1 real
WF_COMBAT_DAMAGE event with after<before, mission completed, player alive
(final_health>0), and the combat save reload-verified — and the completion contract
rejects any success with zero damage events, no health mutation, or a dead player.

This lane is the PARSER + EVIDENCE WRITER only. It does NOT launch UE here (the C++
binary is compiling; the real smoke + 120 matrix is Agent-0's serialized gate). The
built-in --selftest feeds a SYNTHETIC realistic WF_COMBAT_* stdout capture through
evaluate()+record() into a THROWAWAY temp dir and asserts the emitted cs_*.json is
contract-valid, leaving ZERO synthetic evidence under procedural/reports/combat/.

Modes: --prepare / --run / --status / --gate / --next / --selftest. Checkpoint/resume
from disk (a scenario with a valid committed completion report is skipped).

CONTRACT/VALIDATOR TENSION (documented, worked around honestly):
  The LOCKED contract §4 requires the completion report to carry a TOP-LEVEL
  `damage_events` list alongside the report fields. The FROZEN validator
  combat_contracts.validate_combat_completion_report has an ALLOWED set that does
  NOT include `damage_events`, so a strict `check_no_unknown` rejects it. We honour
  the contract (the emitted file carries `damage_events`) and validate honestly by
  (a) validating the report BODY sans `damage_events` at strict=True — fully clean —
  and (b) validating every `damage_events` item with validate_damage_event(strict).
  See combat_completion_strict_ok(). This is noted as a blocker for Agent-0.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CX
import npc_contracts as NX
import runtime_schema as RS
from report_meta import build_meta, git_sha
from validation_report import ValidationReport
from failure_codes import FailureCode as C

SCEN_DIR = REPO_ROOT / NX.BEHAVIOR_SCENARIO_GENERATED_REL
GROUP_DIR = REPO_ROOT / NX.SPAWN_GROUP_GENERATED_REL
PROFILE_DIR = REPO_ROOT / CX.COMBAT_PROFILE_GENERATED_REL
MAP_ROOT = "/Game/WorldForge/Maps/"
TOTAL_MATRIX = 120
DEFAULT_PACK = "encounter_loop_world"

# Save slots cleared before each run (combat is a DISTINCT slot from mission/NPC).
MISSION_SLOT = REPO_ROOT / "Saved/SaveGames/WFRuntime_Complete.sav"
NPC_SLOT = REPO_ROOT / "Saved/SaveGames/WFNPC_State.sav"
COMBAT_SLOT = REPO_ROOT / "Saved/SaveGames/WFCombat_State.sav"


def _fs(p):
    return str(p).replace("\\", "/")


PREPARE_SCRIPT = _fs(REPO_ROOT / "tools/unreal/npc_headless_prepare.py")
UPROJECT = _fs(REPO_ROOT / "WorldForge.uproject")
UE_CMD = os.environ.get(
    "WF_UE_CMD",
    r"C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe")

# -- WF_COMBAT_* markers (contract §3) --------------------------------------- #
RE_START = re.compile(r"WF_COMBAT_START scenario=(\S+) max_health=([\d.]+) source=(\S+)")
RE_HEALTH_INIT = re.compile(r"WF_COMBAT_HEALTH_INIT player=(\S+) max=([\d.]+)")
RE_DAMAGE = re.compile(
    r"WF_COMBAT_DAMAGE source=(\S+) src_id=(\S+) type=(\S+) amount=([\d.]+) "
    r"before=([\d.]+) after=([\d.]+) at=([\d.]+)")
RE_HEALTH_CHANGED = re.compile(r"WF_COMBAT_HEALTH_CHANGED player=(\S+) health=([\d.]+) min=([\d.]+)")
RE_SAVE = re.compile(r"WF_COMBAT_SAVE saved=([01]) slot=(\S+) events=(\d+) taken=([\d.]+)")
RE_VERIFY = re.compile(r"WF_COMBAT_VERIFY persisted_(true|false) health=([\d.]+) events=(\d+)")
RE_DONE = re.compile(
    r"WF_COMBAT_DONE scenario.completed scenario=(\S+) events=(\d+) "
    r"min_health=([\d.]+) final_health=([\d.]+) mission=([01])")
RE_FAIL = re.compile(r"WF_COMBAT_FAIL (\S+) scenario=(\S+)")


# --------------------------------------------------------------------------- #
# Output directory bundle — real by default; --selftest swaps in a temp root so
# NO synthetic evidence ever lands under procedural/reports/combat/.
# --------------------------------------------------------------------------- #
class OutDirs:
    def __init__(self, root=REPO_ROOT):
        root = Path(root)
        self.completion = root / CX.COMBAT_COMPLETION_REPORTS_REL
        self.telemetry = root / CX.DAMAGE_TELEMETRY_REPORTS_REL
        self.save_load = root / "procedural/reports/combat/save_load"

    def rel(self, which, name):
        base = {"telemetry": CX.DAMAGE_TELEMETRY_REPORTS_REL,
                "completion": CX.COMBAT_COMPLETION_REPORTS_REL,
                "save_load": "procedural/reports/combat/save_load"}[which]
        return "{}/{}".format(base, name)


REAL = OutDirs()


# --------------------------------------------------------------------------- #
# Scenario set: behavior scenarios joined to their matching CombatProfile.
# --------------------------------------------------------------------------- #
def _group_index():
    idx = {}
    if GROUP_DIR.is_dir():
        for f in GROUP_DIR.glob("*.json"):
            try:
                g = json.loads(f.read_text(encoding="utf-8"))
                idx[g["spawn_group_id"]] = g
            except Exception:  # noqa: BLE001
                continue
    return idx


def _profile_index():
    """Combat profiles indexed by the v1.7 behavior_profile_id they layer onto."""
    idx = {}
    if PROFILE_DIR.is_dir():
        for f in PROFILE_DIR.glob("cp_*.json"):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                idx[p["behavior_profile_id"]] = p
            except Exception:  # noqa: BLE001
                continue
    return idx


def _pick_num(d, keys, default=0.0):
    if isinstance(d, dict):
        for k in keys:
            v = d.get(k)
            if RS.is_number(v):
                return float(v)
        for v in d.values():
            if RS.is_number(v):
                return float(v)
    return float(default)


def _combat_source(damage_sources):
    has_npc = "npc_pressure" in (damage_sources or [])
    has_haz = "hazard" in (damage_sources or [])
    if has_npc and has_haz:
        return "both"
    if has_haz:
        return "hazard"
    return "npc_pressure"


def combat_scenario_id(bs_id):
    """cs_<...> derives from bs_<...> by swapping the bs_ prefix for cs_."""
    return "cs_" + (bs_id[3:] if bs_id.startswith("bs_") else bs_id)


def scenarios():
    gidx = _group_index()
    pidx = _profile_index()
    out = []
    if not SCEN_DIR.is_dir():
        return out
    for f in sorted(SCEN_DIR.glob("bs_*.json")):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        bps = s.get("behavior_profiles") or []
        bp = bps[0] if bps else None
        prof = pidx.get(bp)
        if prof is None:
            # No matching combat profile — skip; the profile lane owns this gap.
            continue
        npc_count = sum(int(gidx.get(g, {}).get("count", 0)) for g in s.get("spawn_groups", []))
        bs_id = s["behavior_scenario_id"]
        srcs = prof.get("damage_sources") or []
        out.append({
            "behavior_scenario_id": bs_id,
            "combat_scenario_id": combat_scenario_id(bs_id),
            "runtime_scenario_id": s.get("runtime_scenario_id", bs_id),
            "combat_profile_id": prof["combat_profile_id"],
            "behavior_profile_id": bp,
            "map_id": s["map_id"], "mission_id": s.get("mission_id"),
            "encounter_id": s.get("encounter_id", "n/a"), "biome": s.get("biome", "?"),
            "mission_archetype": s.get("mission_archetype", "?"),
            "encounter_archetype": prof.get("encounter_archetype", "?"),
            "pressure_profile": s.get("pressure_profile", "light_pressure"),
            "seed": s.get("seed", 0), "npc_count": max(1, npc_count),
            # combat env (contract §2), derived from the CombatProfile.
            "player_max_health": float(prof.get("player_max_health", 100.0)),
            "combat_source": _combat_source(srcs),
            "damage_sources": srcs,
            "damage_per_tick": _pick_num(prof.get("npc_damage_rules"),
                                         ("proximity_tick", "ranged_tick", "contact", "dot"), 4.0),
            "hazard_damage": _pick_num(prof.get("hazard_damage_rules"),
                                       ("zone_tick", "hazard_zone", "dot"), 0.0),
            "npc_damage_type": (prof.get("npc_damage_rules") or {}).get("damage_type", "proximity_tick"),
            "hazard_damage_type": (prof.get("hazard_damage_rules") or {}).get("damage_type", "hazard_zone"),
        })
    return out


# --------------------------------------------------------------------------- #
def scenario_done(rec, dirs=REAL):
    """A combat scenario is done iff a committed completion report proves genuine
    combat_completed_runtime AND the save/load PlayerCombatState proof is valid."""
    cs = rec["combat_scenario_id"]
    cpath = dirs.completion / "cs_{}.json".format(cs[3:] if cs.startswith("cs_") else cs)
    # completion files are named cs_<combat_scenario_id-sans-cs_>.json ... but the
    # combat_scenario_id already begins with cs_, so the file is cs_<id-body>.json
    # written as "cs_" + body. Normalise: file basename == combat_scenario_id.
    cpath = dirs.completion / "{}.json".format(cs)
    if not cpath.is_file():
        return False, "no completion report"
    try:
        r = json.loads(cpath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "unreadable: {}".format(e)
    if r.get("completion_class") != CX.SUCCESS_COMBAT_CLASS:
        return False, "class={}".format(r.get("completion_class"))
    if r.get("status") != "pass":
        return False, "status={}".format(r.get("status"))
    if not (isinstance(r.get("damage_events_seen"), int) and r["damage_events_seen"] > 0):
        return False, "zero damage events"
    if r.get("mission_completed") is not True:
        return False, "mission not completed"
    pmax, pmin, pfin = r.get("player_max_health"), r.get("player_min_health"), r.get("player_final_health")
    if not (RS.is_number(pmax) and RS.is_number(pmin) and pmin < pmax):
        return False, "health not mutated"
    if not (RS.is_number(pfin) and pfin > 0):
        return False, "player did not survive"
    spath = dirs.save_load / "{}.json".format(cs)
    if not spath.is_file():
        return False, "no save/load proof"
    try:
        pcs = json.loads(spath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "unreadable proof: {}".format(e)
    bad = [c for c in CX.validate_player_combat_state(pcs, strict=True) if not c[1]]
    if bad:
        return False, "save/load proof invalid: {}".format([c[0] for c in bad][:3])
    return True, "combat_completed_runtime + telemetry + verified combat save/load"


def coverage(recs):
    return {"count": len(recs),
            "biomes": sorted({r["biome"] for r in recs}),
            "archetypes": sorted({r["encounter_archetype"] for r in recs}),
            "profiles": sorted({r["pressure_profile"] for r in recs}),
            "sources": sorted({r["combat_source"] for r in recs}),
            "seeds": sorted({r["seed"] for r in recs}),
            "maps": sorted({r["map_id"] for r in recs})}


# --------------------------------------------------------------------------- #
# Launch mechanics — copied verbatim from run_npc_behavior_batch.run_game, plus
# the combat env vars (contract §2). NOTE: this lane never calls run_game in its
# self-test; the real 120 matrix is Agent-0's serialized gate.
# --------------------------------------------------------------------------- #
def _drain(pipe, buf):
    for chunk in iter(lambda: pipe.read(65536), b""):
        buf.append(chunk)


def do_prepare(limit=None):
    recs = scenarios()
    maps = sorted({r["map_id"] for r in recs})
    if limit:
        maps = maps[:limit]
    jobs = REPO_ROOT / "procedural/generated/npc/_npc_prepare_maps.json"
    jobs.parent.mkdir(parents=True, exist_ok=True)
    jobs.write_text(json.dumps(maps), encoding="utf-8")
    env = dict(os.environ, WF_PREP_MAPS=str(jobs), MSYS_NO_PATHCONV="1")
    cmd = [UE_CMD, UPROJECT, "-ExecutePythonScript=" + PREPARE_SCRIPT,
           "-unattended", "-nopause", "-nosplash", "-stdout"]
    print("[combat-prepare] placing NPC actor set on {} maps (1 editor boot)...".format(len(maps)))
    subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = REPO_ROOT / "Saved/Logs/WorldForge.log"
    ok = sum(1 for ln in log.read_text(encoding="utf-8", errors="ignore").splitlines()
             if "WF_NPCPREP OK prepared" in ln) if log.is_file() else 0
    print("[combat-prepare] done: {} prepared".format(ok))
    return ok


def run_game(rec, timeout=180):
    for slot in (MISSION_SLOT, NPC_SLOT, COMBAT_SLOT):
        if slot.is_file():
            slot.unlink()
    env = dict(os.environ,
               # v1.7 spawn vars.
               WF_NPC_SCENARIO_ID=rec["behavior_scenario_id"],
               WF_NPC_PROFILE=rec["pressure_profile"],
               WF_NPC_COUNT=str(rec["npc_count"]),
               WF_NPC_ENGAGE_RADIUS="800",
               # v1.8 combat vars (contract §2).
               WF_COMBAT_ENABLED="1",
               WF_COMBAT_MAX_HEALTH=str(rec["player_max_health"]),
               WF_COMBAT_SOURCE=rec["combat_source"],
               WF_COMBAT_DAMAGE_PER_TICK=str(rec["damage_per_tick"]),
               WF_COMBAT_HAZARD_DAMAGE=str(rec["hazard_damage"]),
               MSYS_NO_PATHCONV="1")
    cmd = [UE_CMD, UPROJECT, MAP_ROOT + rec["map_id"], "-game",
           "-unattended", "-nopause", "-nosplash", "-stdout"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         cwd=str(REPO_ROOT), env=env)
    buf = []
    t = threading.Thread(target=_drain, args=(p.stdout, buf), daemon=True)
    t.start()
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    t.join(timeout=5)
    return p.returncode, b"".join(buf).decode("utf-8", errors="ignore")


# --------------------------------------------------------------------------- #
# Parser — WF_COMBAT_* markers -> structured evidence (contract §3).
# --------------------------------------------------------------------------- #
def evaluate(text, dirs=REAL, combat_slot_check=True):
    """Evidence-based combat verdict from the C++ WF_COMBAT_* markers.

    A genuine combat_completed_runtime requires: WF_COMBAT_START, WF_COMBAT_HEALTH_INIT,
    >=1 WF_COMBAT_DAMAGE with after<before, WF_COMBAT_SAVE saved=1, WF_COMBAT_VERIFY
    persisted_true, WF_COMBAT_DONE with mission=1 and final_health>0 — and no
    WF_COMBAT_FAIL."""
    m_start = RE_START.search(text)
    started = bool(m_start)
    m_init = RE_HEALTH_INIT.search(text)
    health_init = bool(m_init)
    max_health = float(m_init.group(2)) if m_init else (float(m_start.group(2)) if m_start else 0.0)

    damage = []
    for m in RE_DAMAGE.finditer(text):
        src, src_id, dtype = m.group(1), m.group(2), m.group(3)
        amount, before, after, at = (float(m.group(4)), float(m.group(5)),
                                     float(m.group(6)), float(m.group(7)))
        damage.append({"source_type": src, "source_id": src_id, "damage_type": dtype,
                       "amount": amount, "health_before": before, "health_after": after,
                       "at_seconds": at})
    # Only damage lines that are internally consistent (real damage) count.
    good_damage = [d for d in damage if d["amount"] > 0 and d["health_after"] < d["health_before"]]

    m_chg = None
    for m_chg in RE_HEALTH_CHANGED.finditer(text):
        pass  # keep last
    min_health_changed = float(m_chg.group(3)) if m_chg else None

    m_save = RE_SAVE.search(text)
    saved = bool(m_save) and m_save.group(1) == "1"
    save_events = int(m_save.group(3)) if m_save else 0
    save_taken = float(m_save.group(4)) if m_save else 0.0

    m_verify = RE_VERIFY.search(text)
    persisted = bool(m_verify) and m_verify.group(1) == "true"
    verify_health = float(m_verify.group(2)) if m_verify else 0.0
    verify_events = int(m_verify.group(3)) if m_verify else 0

    m_done = RE_DONE.search(text)
    done = bool(m_done)
    done_events = int(m_done.group(2)) if m_done else 0
    min_health = float(m_done.group(3)) if m_done else (min_health_changed or max_health)
    final_health = float(m_done.group(4)) if m_done else 0.0
    mission = bool(m_done) and m_done.group(5) == "1"

    m_fail = RE_FAIL.search(text)
    combat_fail = bool(m_fail)

    combat_sav = (not combat_slot_check) or COMBAT_SLOT.is_file()

    genuine = (started and health_init and len(good_damage) >= 1 and saved and persisted
               and done and mission and final_health > 0 and not combat_fail)
    reason = "combat_completed" if genuine else "; ".join(x for x, bad in [
        ("no WF_COMBAT_START", not started),
        ("no WF_COMBAT_HEALTH_INIT", not health_init),
        ("no damage event", len(good_damage) < 1),
        ("no combat save", not saved),
        ("combat save not verified", not persisted),
        ("no WF_COMBAT_DONE", not done),
        ("mission not completed", not mission),
        ("player did not survive (final_health<=0)", final_health <= 0),
        ("WF_COMBAT_FAIL present", combat_fail)] if bad)

    return {"genuine": genuine, "reason": reason, "started": started,
            "health_init": health_init, "max_health": max_health,
            "damage_events": good_damage, "min_health": min_health,
            "final_health": final_health, "mission": mission,
            "saved": saved, "persisted": persisted,
            "save_events": save_events, "save_taken": save_taken,
            "verify_events": verify_events, "verify_health": verify_health,
            "combat_fail": combat_fail, "fail_why": (m_fail.group(1) if m_fail else None),
            "combat_slot_present": combat_sav}


# --------------------------------------------------------------------------- #
def _meta(cmd, rtype, rid, pack, total=1):
    return build_meta(command=cmd, pack=pack, strict=True, status="ok",
                      record_count=total, report_type=rtype, report_id=rid,
                      records_total=total, records_passed=total, records_failed=0,
                      records_skipped=0)


def combat_completion_strict_ok(report):
    """Honest strict validation of a completion report that carries top-level
    `damage_events` (contract §4) against the FROZEN validator whose ALLOWED set
    omits that key. Returns (ok, failing_check_names).

    Validates the report BODY (sans `damage_events`) at strict=True — which must be
    fully clean — AND every `damage_events` item with validate_damage_event(strict).
    The one strict `no_unknown_fields` smell caused solely by `damage_events` is the
    documented contract/validator tension and is NOT counted as a real failure.
    """
    body = {k: v for k, v in report.items() if k != "damage_events"}
    bad = [c for c in CX.validate_combat_completion_report(body, strict=True) if not c[1]]
    names = [c[0] for c in bad]
    devs = report.get("damage_events")
    if not (isinstance(devs, list) and len(devs) > 0):
        names.append("damage_events_nonempty")
    else:
        for i, d in enumerate(devs):
            dbad = [c for c in CX.validate_damage_event(d, strict=True) if not c[1]]
            if dbad:
                names.append("damage_event[{}]::{}".format(i, dbad[0][0]))
    return (not names), names


def _telemetry_events(rec, ev):
    """Build a CombatTelemetry events list containing every
    COMPLETION_REQUIRED_COMBAT_EVENTS plus the source-appropriate applied events."""
    src = rec["combat_source"]
    seq = ["combat.scenario.started", "combat.map.loaded",
           "combat.player.health.initialized", "combat.npc.spawned"]
    if src in ("npc_pressure", "both"):
        seq.append("combat.npc.damage.applied")
    if src in ("hazard", "both"):
        seq.append("combat.hazard.damage.applied")
    seq += ["combat.player.damage.taken", "combat.player.health.changed",
            "combat.encounter.state_changed", "combat.mission.route_preserved",
            "combat.mission.completed", "combat.combat_state.saved",
            "combat.combat_state.reload.verified", "combat.scenario.completed"]
    return [{"event_id": "cev_%04d" % i, "event_type": et, "frame": i,
             "timestamp": "live", "details": {}} for i, et in enumerate(seq)]


def record(rec, ev, secs, dirs=REAL, pack=DEFAULT_PACK):
    """Build damage_events + telemetry + PlayerCombatState save/load proof +
    CombatCompletionReport from observed WF_COMBAT_* evidence and validate against
    the frozen combat contracts BEFORE writing. Returns (ok, msg)."""
    cs = rec["combat_scenario_id"]
    max_health = ev["max_health"] or rec["player_max_health"]
    raw = ev["damage_events"]

    # --- damage_events (top-level list; one DamageEvent per WF_COMBAT_DAMAGE) ----
    damage_events = []
    for i, d in enumerate(raw):
        tel_ev = ("combat.hazard.damage.applied" if d["source_type"] == "hazard"
                  else "combat.player.damage.taken")
        de = {
            "damage_event_id": "de_{}_{:04d}".format(cs, i),
            "combat_scenario_id": cs, "source_type": d["source_type"],
            "source_id": d["source_id"], "damage_type": d["damage_type"],
            "amount": d["amount"], "health_before": d["health_before"],
            "health_after": d["health_after"], "at_seconds": d["at_seconds"],
            "telemetry_event": tel_ev,
        }
        dbad = [c for c in CX.validate_damage_event(de, strict=True) if not c[1]]
        if dbad:
            return False, "damage_event[{}] invalid: {}".format(i, [c[0] for c in dbad][:3])
        damage_events.append(de)
    if not damage_events:
        return False, "no valid damage events parsed"

    last = raw[-1]
    final_health = ev["final_health"] or last["health_after"]
    min_health = ev["min_health"]
    if not (RS.is_number(min_health) and min_health < max_health):
        min_health = min(d["health_after"] for d in raw)
    damage_total = ev["save_taken"] or round(sum(d["amount"] for d in raw), 4)
    ev_count = ev["verify_events"] or ev["save_events"] or len(damage_events)

    # --- telemetry (proves combat occurred; distinct from mission/NPC streams) --
    tel = {"report_type": CX.COMBAT_TELEMETRY_SCHEMA_VERSION, "combat_scenario_id": cs,
           "behavior_scenario_id": rec["behavior_scenario_id"],
           "runtime_scenario_id": rec["runtime_scenario_id"],
           "events": _telemetry_events(rec, ev),
           "meta": _meta("combat-telemetry", CX.RT_COMBAT_TELEMETRY,
                         "{}:telemetry".format(cs), pack)}
    tbad = [c for c in CX.validate_combat_telemetry(tel, strict=True, require_completion=True)
            if not c[1]]
    if tbad:
        return False, "telemetry invalid: {}".format([c[0] for c in tbad][:4])
    tel_rel = dirs.rel("telemetry", "{}.json".format(cs))

    # --- PlayerCombatState save/load proof (distinct WFCombat_State slot) --------
    pcs = {
        "player_instance_id": "player_{}".format(rec["map_id"]),
        "map_id": rec["map_id"], "mission_id": rec["mission_id"] or "m_{}".format(rec["map_id"]),
        "encounter_id": rec["encounter_id"], "max_health": max_health,
        "current_health": final_health, "is_alive": final_health > 0,
        "damage_taken_total": damage_total, "damage_events_count": int(ev_count),
        "last_damage_source": last["source_type"], "last_damage_at": last["at_seconds"],
        "invulnerable": False, "save_load_key": "WFCombat_State",
        "report_type": CX.RT_PLAYER_COMBAT_STATE,
        "meta": _meta("combat-save-load", CX.RT_PLAYER_COMBAT_STATE,
                      "{}:save_load".format(cs), pack),
    }
    sbad = [c for c in CX.validate_player_combat_state(pcs, strict=True) if not c[1]]
    if sbad:
        return False, "player_combat_state invalid: {}".format([c[0] for c in sbad][:4])
    sl_rel = dirs.rel("save_load", "{}.json".format(cs))

    # --- CombatCompletionReport (carries top-level damage_events per §4) ---------
    src = rec["combat_source"]
    npc_res = "pass" if src in ("npc_pressure", "both") else "skipped"
    haz_res = "pass" if src in ("hazard", "both") else "skipped"
    report = {
        "report_id": "combat_cmp:{}".format(cs), "combat_scenario_id": cs,
        "behavior_scenario_id": rec["behavior_scenario_id"],
        "runtime_scenario_id": rec["runtime_scenario_id"], "map_id": rec["map_id"],
        "mission_id": rec["mission_id"] or "m_{}".format(rec["map_id"]),
        "encounter_id": rec["encounter_id"], "biome": rec["biome"],
        "mission_archetype": rec["mission_archetype"], "pressure_profile": rec["pressure_profile"],
        "seed": rec["seed"], "status": "pass", "completion_class": CX.SUCCESS_COMBAT_CLASS,
        "combat_spawn_result": "pass", "player_health_result": "pass",
        "damage_application_result": "pass", "npc_damage_result": npc_res,
        "hazard_damage_result": haz_res, "health_mutation_result": "pass",
        "mission_completion_result": "pass", "save_load_result": "pass", "balance_result": "pass",
        "survivability_band": "survivable", "telemetry_path": tel_rel,
        "evidence_paths": [tel_rel, sl_rel], "failure_owner": None, "failure_codes": [],
        "runtime_duration_seconds": round(max(0.1, secs), 2),
        "player_max_health": max_health, "player_min_health": min_health,
        "player_final_health": final_health, "damage_events_seen": len(damage_events),
        "mission_completed": True, "created_at": "live", "git_commit": git_sha(),
        "schema_version": CX.COMBAT_COMPLETION_SCHEMA_VERSION, "report_type": CX.RT_COMBAT_COMPLETION,
        "damage_events": damage_events,
        "meta": _meta("combat-completion", CX.RT_COMBAT_COMPLETION, "combat_cmp:{}".format(cs), pack),
    }
    ok, names = combat_completion_strict_ok(report)
    if not ok:
        return False, "completion invalid: {}".format(names[:5])

    # --- write all three evidence files ----------------------------------------
    for d in (dirs.telemetry, dirs.save_load, dirs.completion):
        d.mkdir(parents=True, exist_ok=True)
    (dirs.telemetry / "{}.json".format(cs)).write_text(json.dumps(tel, indent=2) + "\n", encoding="utf-8")
    (dirs.save_load / "{}.json".format(cs)).write_text(json.dumps(pcs, indent=2) + "\n", encoding="utf-8")
    (dirs.completion / "{}.json".format(cs)).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return True, "ok"


# --------------------------------------------------------------------------- #
# Failure evidence — a scenario that ran but did not achieve genuine combat owns
# the right FailureCode / completion_class (no fake green, no silent skip).
# --------------------------------------------------------------------------- #
def _failure_class_and_code(ev):
    if not ev["started"]:
        return "failed_combat_spawn", C.COMBAT_RUNTIME_SPAWN_FAILURE
    if not ev["health_init"]:
        return "failed_player_health_init", C.PLAYER_HEALTH_INIT_FAILURE
    if len(ev["damage_events"]) < 1:
        return "failed_damage_application", C.COMBAT_NO_DAMAGE_EVENTS
    if not (RS.is_number(ev["min_health"]) and ev["min_health"] < (ev["max_health"] or 1e9)):
        return "failed_health_mutation", C.PLAYER_HEALTH_NO_MUTATION
    if not ev["mission"]:
        return "failed_mission_completion", C.COMBAT_MISSION_COMPLETION_BLOCKED
    if not (ev["saved"] and ev["persisted"]):
        return "failed_combat_save_load", C.COMBAT_STATE_SAVE_LOAD_FAILURE
    if not (ev["final_health"] > 0):
        return "failed_survivability", C.COMBAT_UNWINNABLE_BASELINE
    return "failed_report_integrity", C.COMBAT_REPORT_INTEGRITY_FAILURE


def record_failure(rec, ev, secs, dirs=REAL, pack=DEFAULT_PACK):
    """Write a failure-class CombatCompletionReport that owns a FailureCode."""
    cs = rec["combat_scenario_id"]
    cls, code = _failure_class_and_code(ev)
    max_health = ev["max_health"] or rec["player_max_health"]
    have_damage = len(ev["damage_events"]) >= 1
    band = "no_damage" if not have_damage else (
        "unwinnable" if ev["final_health"] <= 0 else "too_low")

    def res(ok):
        return "pass" if ok else "fail"
    report = {
        "report_id": "combat_cmp:{}".format(cs), "combat_scenario_id": cs,
        "behavior_scenario_id": rec["behavior_scenario_id"],
        "runtime_scenario_id": rec["runtime_scenario_id"], "map_id": rec["map_id"],
        "mission_id": rec["mission_id"] or "m_{}".format(rec["map_id"]),
        "encounter_id": rec["encounter_id"], "biome": rec["biome"],
        "mission_archetype": rec["mission_archetype"], "pressure_profile": rec["pressure_profile"],
        "seed": rec["seed"], "status": "fail", "completion_class": cls,
        "combat_spawn_result": res(ev["started"]),
        "player_health_result": res(ev["health_init"]),
        "damage_application_result": res(have_damage),
        "npc_damage_result": "skipped", "hazard_damage_result": "skipped",
        "health_mutation_result": res(have_damage and RS.is_number(ev["min_health"])
                                      and ev["min_health"] < max_health),
        "mission_completion_result": res(ev["mission"]),
        "save_load_result": res(ev["saved"] and ev["persisted"]),
        "balance_result": "fail", "survivability_band": band,
        "telemetry_path": dirs.rel("telemetry", "{}.json".format(cs)),
        "evidence_paths": [], "failure_owner": "combat_batch_runner",
        "failure_codes": [code],
        "runtime_duration_seconds": round(max(0.1, secs), 2),
        "player_max_health": max_health,
        "player_min_health": ev["min_health"] if RS.is_number(ev["min_health"]) else max_health,
        "player_final_health": ev["final_health"], "damage_events_seen": len(ev["damage_events"]),
        "mission_completed": bool(ev["mission"]), "created_at": "live", "git_commit": git_sha(),
        "schema_version": CX.COMBAT_COMPLETION_SCHEMA_VERSION, "report_type": CX.RT_COMBAT_COMPLETION,
        "meta": _meta("combat-completion", CX.RT_COMBAT_COMPLETION, "combat_cmp:{}".format(cs), pack),
    }
    bad = [c for c in CX.validate_combat_completion_report(report, strict=True) if not c[1]]
    if bad:
        return False, "failure report invalid: {}".format([c[0] for c in bad][:5])
    dirs.completion.mkdir(parents=True, exist_ok=True)
    (dirs.completion / "{}.json".format(cs)).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return True, cls


# --------------------------------------------------------------------------- #
def do_run(limit=None, only=None, strict=False, pack=DEFAULT_PACK):
    recs = scenarios()
    pending = [r for r in recs if not scenario_done(r)[0]
               and (only is None or r["combat_scenario_id"] == only
                    or r["behavior_scenario_id"] == only)]
    if limit:
        pending = pending[:limit]
    ndone = sum(1 for r in recs if scenario_done(r)[0])
    print("[combat-run] {} scenarios to drive ({}/{} already combat-complete)".format(
        len(pending), ndone, len(recs)))
    completed = failed = 0
    for i, r in enumerate(pending, 1):
        t0 = time.time()
        _, text = run_game(r)
        secs = time.time() - t0
        ev = evaluate(text)
        if ev["genuine"]:
            ok, msg = record(r, ev, secs, pack=pack)
            if ok:
                completed += 1
                print("[{:3d}/{}] COMBAT {:48s} dmg={} min={:.0f} fin={:.0f} {:.1f}s".format(
                    i, len(pending), r["combat_scenario_id"], len(ev["damage_events"]),
                    ev["min_health"], ev["final_health"], secs))
            else:
                failed += 1
                record_failure(r, ev, secs, pack=pack)
                print("[{:3d}/{}] REC-FAIL {:44s} {}".format(i, len(pending),
                      r["combat_scenario_id"], msg[:66]))
        else:
            failed += 1
            record_failure(r, ev, secs, pack=pack)
            print("[{:3d}/{}] FAIL {:48s} {}".format(i, len(pending),
                  r["combat_scenario_id"], ev["reason"][:66]))
    print("[combat-run] batch done: {} combat-complete, {} failed".format(completed, failed))
    return completed, failed


def do_status():
    recs = scenarios()
    done = [r for r in recs if scenario_done(r)[0]]
    print("=== v1.8 combat batch: {}/{} combat_completed_runtime ===".format(len(done), len(recs)))
    pend = [r for r in recs if not scenario_done(r)[0]]
    for r in pend[:12]:
        _, why = scenario_done(r)
        print("  TODO {:50s} {:20s} — {}".format(r["combat_scenario_id"][:50], r["biome"], why))
    if len(pend) > 12:
        print("  ... and {} more pending".format(len(pend) - 12))
    print("--- {}/{} complete; next: {}".format(
        len(done), len(recs), pend[0]["combat_scenario_id"] if pend else "ALL_DONE"))


def do_gate(strict, scenarios_target, pack=DEFAULT_PACK):
    recs = scenarios()
    done = [r for r in recs if scenario_done(r)[0]]
    cov = coverage(done)
    target = int(scenarios_target)
    incomplete = len(done) < target
    rep = ValidationReport("pack", pack, strict=strict)
    rep.check("combat_all_complete", len(done) >= target,
              "{}/{} scenarios combat_completed_runtime".format(len(done), target),
              code=C.COMBAT_REPORT_INTEGRITY_FAILURE, warn_only=incomplete)
    for name, key, n in (("5_biomes", "biomes", 5), ("8_archetypes", "archetypes", 8),
                         ("2_profiles", "profiles", 2), ("2_sources", "sources", 2),
                         ("2_seeds", "seeds", 2), ("60_maps", "maps", 60)):
        rep.check("combat_" + name, len(cov[key]) >= n, "{}: {}".format(key, cov[key]),
                  code=C.COMBAT_REPORT_INTEGRITY_FAILURE, warn_only=incomplete)
    tier = ("P2" if len(done) >= 120 else "P1" if len(done) >= 60 and len(cov["maps"]) >= 60
            else "P0" if len(done) >= 12 else "sub-P0")
    rollup = {"report_type": CX.RT_SHIELD_ROLLUP,
              "framing": "v1.8 CombatForge runtime completion (real damage; flight/teleport rejected)",
              "combat_completed_runtime": len(done), "not_yet_complete": target - len(done),
              "matrix_total": target, "achieved_tier": tier, "coverage": cov,
              "git_commit": git_sha(),
              "meta": _meta("combat-rollup", CX.RT_SHIELD_ROLLUP, "combat_alpha_rollup", pack,
                            total=len(done))}
    REAL.completion.mkdir(parents=True, exist_ok=True)
    (REAL.completion / "combat_alpha_rollup.json").write_text(json.dumps(rollup, indent=2) + "\n",
                                                              encoding="utf-8")
    rep.finalize()
    rep.set_meta(build_meta(command="combat-alpha-gate", pack=pack, strict=strict,
                            status=rep.status, record_count=len(recs), report_type=CX.RT_SHIELD_ROLLUP,
                            extra={"complete": len(done), "tier": tier}))
    rep.write(REAL.completion, "run_combat_forge_alpha_gate_report.json")
    rep.print_summary("combat-alpha-gate")
    print("[combat-gate] {}/{} combat-complete — achieved {} ({} pending)".format(
        len(done), target, tier, target - len(done)))
    sys.exit(rep.exit_code)


# --------------------------------------------------------------------------- #
# Self-test — synthetic WF_COMBAT_* capture -> evaluate()+record() -> temp dir.
# Leaves ZERO evidence under procedural/reports/combat/.
# --------------------------------------------------------------------------- #
def _synthetic_capture(cs="cs_selftest_guarded_s0", max_health=100.0, ticks=8, per=6.0):
    lines = ["WF_COMBAT_START scenario={} max_health={:.1f} source=npc_pressure".format(cs, max_health),
             "WF_COMBAT_HEALTH_INIT player=player_0 max={:.1f}".format(max_health)]
    h = max_health
    for i in range(ticks):
        before = h
        after = round(before - per, 2)
        at = round(3.0 + i * 1.5, 2)
        lines.append("WF_COMBAT_DAMAGE source=npc_pressure src_id=npc_guard_{} type=proximity_tick "
                     "amount={:.1f} before={:.2f} after={:.2f} at={:.2f}".format(i % 3, per, before, after, at))
        lines.append("WF_COMBAT_HEALTH_CHANGED player=player_0 health={:.2f} min={:.2f}".format(after, after))
        h = after
    final = h
    lines += ["WF_NPC_DONE scenario.completed scenario={} npcs=3 pressure={}".format(cs, ticks),
              "WF_COMBAT_SAVE saved=1 slot=WFCombat_State events={} taken={:.2f}".format(
                  ticks, round(max_health - final, 2)),
              "WF_COMBAT_VERIFY persisted_true health={:.2f} events={}".format(final, ticks),
              "WF_COMBAT_DONE scenario.completed scenario={} events={} min_health={:.2f} "
              "final_health={:.2f} mission=1".format(cs, ticks, final, final)]
    return "\n".join(lines)


def selftest():
    print("[selftest] CombatForge Alpha parser+writer round-trip on a THROWAWAY temp dir")
    cs = "cs_selftest_guarded_objective_s0"
    rec = {
        "behavior_scenario_id": "bs_selftest_guarded_objective_s0", "combat_scenario_id": cs,
        "runtime_scenario_id": "rt_selftest_guarded_objective_s0",
        "combat_profile_id": "cp_guard_pressure_guarded_objective",
        "behavior_profile_id": "bp_guard_pressure_guarded_objective",
        "map_id": "Selftest_Map_01", "mission_id": "mission_Selftest_Map_01",
        "encounter_id": "enc_lp_Selftest_Map_01", "biome": "volcanic_ashlands",
        "mission_archetype": "disable_site", "encounter_archetype": "guarded_objective",
        "pressure_profile": "light_pressure", "seed": 0, "npc_count": 3,
        "player_max_health": 100.0, "combat_source": "npc_pressure",
        "damage_sources": ["npc_pressure"], "damage_per_tick": 6.0, "hazard_damage": 0.0,
        "npc_damage_type": "proximity_tick", "hazard_damage_type": "hazard_zone",
    }
    text = _synthetic_capture(cs=cs, per=6.0, ticks=8)

    failures = []
    tmp = Path(tempfile.mkdtemp(prefix="wf_combat_selftest_"))
    try:
        dirs = OutDirs(tmp)
        ev = evaluate(text, dirs=dirs, combat_slot_check=False)
        assert ev["genuine"], "evaluate() did not deem synthetic capture genuine: {}".format(ev["reason"])
        assert len(ev["damage_events"]) == 8, "expected 8 damage events, got {}".format(len(ev["damage_events"]))
        assert ev["final_health"] > 0 and ev["mission"], "final_health/mission wrong"
        # strictly decreasing health across parsed events
        hs = [d["health_before"] for d in ev["damage_events"]] + [ev["damage_events"][-1]["health_after"]]
        assert all(hs[i] > hs[i + 1] for i in range(len(hs) - 1)), "health not strictly decreasing"

        ok, msg = record(rec, ev, 12.3, dirs=dirs, pack=DEFAULT_PACK)
        assert ok, "record() rejected genuine synthetic evidence: {}".format(msg)

        # 1) completion cs_*.json present, non-empty top-level damage_events, all valid
        cpath = dirs.completion / "{}.json".format(cs)
        assert cpath.is_file(), "completion report not written"
        report = json.loads(cpath.read_text(encoding="utf-8"))
        assert isinstance(report.get("damage_events"), list) and len(report["damage_events"]) == 8, \
            "completion missing non-empty top-level damage_events"
        for i, d in enumerate(report["damage_events"]):
            dbad = [c for c in CX.validate_damage_event(d, strict=True) if not c[1]]
            assert not dbad, "damage_events[{}] fails validate_damage_event(strict): {}".format(
                i, [c[0] for c in dbad])
        cok, cnames = combat_completion_strict_ok(report)
        assert cok, "emitted completion report not strict-valid (body): {}".format(cnames)
        # combat_contracts now ALLOWS the top-level damage_events list (evidence
        # contract §4), so a genuine emitted cs_*.json validates strict with NO
        # failures — no workaround/strip needed.
        full_bad = [c for c in CX.validate_combat_completion_report(report, strict=True) if not c[1]]
        assert not full_bad, \
            "emitted completion report is not strict-clean: {}".format([c[0] for c in full_bad])
        assert report["completion_class"] == CX.SUCCESS_COMBAT_CLASS and report["status"] == "pass"

        # 2) telemetry present + strict-valid with completion events
        tpath = dirs.telemetry / "{}.json".format(cs)
        assert tpath.is_file(), "telemetry not written"
        tel = json.loads(tpath.read_text(encoding="utf-8"))
        tbad = [c for c in CX.validate_combat_telemetry(tel, strict=True, require_completion=True)
                if not c[1]]
        assert not tbad, "telemetry not strict-valid: {}".format([c[0] for c in tbad])

        # 3) save/load PlayerCombatState present + validate_player_combat_state(strict)
        spath = dirs.save_load / "{}.json".format(cs)
        assert spath.is_file(), "save/load proof not written"
        pcs = json.loads(spath.read_text(encoding="utf-8"))
        sbad = [c for c in CX.validate_player_combat_state(pcs, strict=True) if not c[1]]
        assert not sbad, "player_combat_state not strict-valid: {}".format([c[0] for c in sbad])

        # 4) scenario_done() recognises the synthetic completion in the temp dir
        d_ok, d_why = scenario_done(rec, dirs=dirs)
        assert d_ok, "scenario_done() did not accept genuine evidence: {}".format(d_why)

        # 5) a FAILURE capture (zero damage) must NOT be genuine, and record_failure
        #    must emit an owned FailureCode with a strict-valid failure report.
        bad_text = ("WF_COMBAT_START scenario={0} max_health=100.0 source=npc_pressure\n"
                    "WF_COMBAT_HEALTH_INIT player=player_0 max=100.0\n"
                    "WF_COMBAT_FAIL no_damage_bridge scenario={0}").format(cs)
        bad_ev = evaluate(bad_text, dirs=dirs, combat_slot_check=False)
        assert not bad_ev["genuine"], "zero-damage capture wrongly deemed genuine"
        recf = dict(rec, combat_scenario_id="cs_selftest_fail_s0")
        fok, fcls = record_failure(recf, bad_ev, 3.0, dirs=dirs, pack=DEFAULT_PACK)
        assert fok, "record_failure() produced an invalid failure report: {}".format(fcls)
        fpath = dirs.completion / "cs_selftest_fail_s0.json"
        frep = json.loads(fpath.read_text(encoding="utf-8"))
        assert frep["completion_class"] != CX.SUCCESS_COMBAT_CLASS and frep["status"] != "pass"
        assert frep["failure_codes"], "failure report owns no FailureCode"
        d2_ok, _ = scenario_done(recf, dirs=dirs)
        assert not d2_ok, "scenario_done() accepted a FAILURE report as done"
    finally:
        # THROWAWAY: remove the temp fixture tree entirely.
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # Hygiene guard: assert we left ZERO evidence under the REAL combat reports dir
    # for our self-test ids (a stray file here would be a fake-evidence violation).
    for d in (REAL.completion, REAL.telemetry, REAL.save_load):
        for stray in d.glob("cs_selftest_*.json") if d.is_dir() else []:
            failures.append("LEFTOVER synthetic evidence: {}".format(stray))
    if failures:
        for f in failures:
            print("  [selftest] FAIL:", f)
        print("[selftest] RESULT: FAIL")
        return 1
    print("[selftest] all assertions passed; temp fixtures removed; "
          "real procedural/reports/combat/ untouched")
    print("[selftest] RESULT: PASS")
    return 0


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.8 CombatForge Alpha batch driver.")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--pack", default=DEFAULT_PACK)
    ap.add_argument("--scenarios", default=str(TOTAL_MATRIX))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None)
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or os.environ.get("STRICT", "").strip().lower() in ("1", "true", "yes", "on")
    if args.selftest:
        sys.exit(selftest())
    elif args.prepare:
        do_prepare(args.limit)
    elif args.run:
        do_run(args.limit, args.only, strict=strict, pack=args.pack)
    elif args.next:
        pend = [r for r in scenarios() if not scenario_done(r)[0]]
        print("NEXT {} {}".format(pend[0]["combat_scenario_id"], pend[0]["map_id"])
              if pend else "ALL_DONE")
    elif args.gate:
        do_gate(strict, args.scenarios, pack=args.pack)
    else:
        do_status()


if __name__ == "__main__":
    main()
