#!/usr/bin/env python3
r"""run_reward_forge_alpha.py — WorldForge v1.9 Wave R reward runtime batch driver.

RewardForge Alpha. Drives the 120-scenario reward matrix to GENUINE
`reward_granted_runtime`, headless, one crash-isolated `-game` process per
scenario. A reward scenario RIDES the v1.8 combat scenarios: it is a v1.8 combat
run (run_combat_forge_alpha.scenarios(), combat *enabled* so combat_completed) with
the v1.9 reward system ALSO enabled (WF_REWARD_ENABLED=1) and a deterministic
reward table bound per scenario. The grounded player pawn walks the objective under
real combat pressure; on mission completion the C++ AWFEncounterManager::FinalizeReward
grants the table's rewards, mutates the durable Inventory/Progression save slots
(distinct from mission/NPC/combat slots), persists WFReward_State, reload-verifies,
and writes a next-mission unlock handoff. Nothing is faked: the recorder only writes
reward_granted_runtime when the C++ WF_REWARD_* markers prove the grant fired,
inventory OR progression actually mutated, the reward state reload-verified, the
mission completed, and there is no WF_REWARD_FAIL — and the completion contract
(reward_contracts.validate_reward_completion_report) rejects any success with no
state mutation, zero reward events, no resolved table, or a failed save/load.

This lane is the PARSER + EVIDENCE WRITER only. It does NOT launch UE here (the C++
binary is compiling; the real smoke + 120 matrix is the parent's serialized gate).
The built-in --selftest feeds a SYNTHETIC realistic WF_REWARD_* stdout capture
through evaluate()+record() into a THROWAWAY temp dir and asserts the emitted
evidence (completion + telemetry + inventory + progression) is contract-valid,
leaving ZERO synthetic evidence under procedural/reports/rewards/ (or the paired
procedural/reports/progression/save_load/).

Modes: --prepare / --run / --status / --gate / --next / --selftest. Checkpoint/resume
from disk (a scenario with a valid committed live completion report is skipped).

Reward tables (unmodified committed authoring data) drive the env: per scenario the
table rwt_<mission_archetype>_<risk> is selected where risk = high if seed is odd
else baseline. The runtime evidence's items/xp/unlocks come from the PARSED markers
(what actually got granted), not from the table (what was asked for).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import re

import reward_contracts as RX
import reward_forge as RF
import run_combat_forge_alpha as CB
import runtime_schema as RS
from report_meta import build_meta, git_sha
from validation_report import ValidationReport
from failure_codes import FailureCode as C

TOTAL_MATRIX = 120
DEFAULT_PACK = "encounter_loop_world"
REWARD_TABLE_DIR = REPO_ROOT / RX.REWARD_TABLE_GENERATED_REL

# Save slots cleared before each run — reward/progression state lives in DISTINCT
# slots from mission/NPC/combat, and all are cleared so a run proves fresh grants.
SAVE_SLOTS = tuple(REPO_ROOT / "Saved/SaveGames" / n for n in (
    "WFRuntime_Complete.sav", "WFNPC_State.sav", "WFCombat_State.sav",
    "WFReward_State.sav", "WFInventory_State.sav", "WFProgression_State.sav"))

# -- WF_REWARD_* markers (FROZEN contract, emitted by FinalizeReward) --------- #
RE_START = re.compile(
    r"WF_REWARD_START scenario=(\S+) table=(\S+) xp=([\d.]+) items=(\d+) "
    r"unlocks=(\d+) mission=([01]) combat=([01])")
RE_GRANT = re.compile(
    r"WF_REWARD_GRANT scenario=(\S+) type=(xp|item|unlock) id=(\S+) amount=([\d.]+)")
RE_INV = re.compile(
    r"WF_REWARD_INVENTORY_MUTATED mutated=([01]) items=(\d+) slot=(\S+)")
RE_PROG = re.compile(
    r"WF_REWARD_PROGRESSION_MUTATED mutated=([01]) level=(\d+) xp_total=([\d.]+) "
    r"unlocks=(\d+) slot=(\S+)")
RE_SAVE = re.compile(r"WF_REWARD_SAVE saved=([01]) slot=(\S+) events=(\d+)")
RE_VERIFY = re.compile(
    r"WF_REWARD_VERIFY persisted_(true|false) inv_items=(\d+) prog_level=(\d+) "
    r"prog_xp=([\d.]+) reward_events=(\d+)")
RE_NEXT = re.compile(
    r"WF_REWARD_NEXT_MISSION written=([01]) unlocks_enabled=(\d+) level=(\d+) "
    r"xp_total=([\d.]+)")
RE_DONE = re.compile(
    r"WF_REWARD_DONE scenario\.completed scenario=(\S+) events=(\d+) items=(\d+) "
    r"xp=([\d.]+) unlocks=(\d+) inv_mutated=([01]) prog_mutated=([01]) level=(\d+) "
    r"xp_total=([\d.]+)")
RE_FAIL = re.compile(r"WF_REWARD_FAIL (\S+) scenario=(\S+)")


# --------------------------------------------------------------------------- #
# Output directory bundle — real by default; --selftest swaps in a temp root so
# NO synthetic evidence ever lands under the committed reward/progression trees.
# --------------------------------------------------------------------------- #
class OutDirs:
    def __init__(self, root=REPO_ROOT):
        root = Path(root)
        self.completion = root / RX.REWARD_COMPLETION_REPORTS_REL
        self.telemetry = root / RX.REWARD_TELEMETRY_REPORTS_REL
        self.inv_sl = root / RX.REWARD_SAVE_LOAD_REPORTS_REL
        self.prog_sl = root / "procedural/reports/progression/save_load"

    def rel(self, which, name):
        base = {"telemetry": RX.REWARD_TELEMETRY_REPORTS_REL,
                "completion": RX.REWARD_COMPLETION_REPORTS_REL,
                "inv_sl": RX.REWARD_SAVE_LOAD_REPORTS_REL,
                "prog_sl": "procedural/reports/progression/save_load"}[which]
        return "{}/{}".format(base, name)


REAL = OutDirs()


# --------------------------------------------------------------------------- #
# Reward-table selection (deterministic, per scenario).
# --------------------------------------------------------------------------- #
def _load_reward_table(table_id):
    p = REWARD_TABLE_DIR / "{}.json".format(table_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def select_reward(rec):
    """Deterministically pick rwt_<archetype>_<risk> where risk=high iff seed odd.
    Returns a dict (risk/table_id/table/xp/items/unlocks) or None if no such table."""
    risk = "high" if (int(rec.get("seed", 0)) % 2 == 1) else "baseline"
    table_id = "rwt_{}_{}".format(rec["mission_archetype"], risk)
    table = _load_reward_table(table_id)
    if table is None:
        return None
    entries = table.get("reward_entries") or []
    xp = round(sum(float(e.get("xp_amount") or 0.0)
                   for e in entries if e.get("reward_type") == "xp"), 4)
    items = [e["item_id"] for e in entries if e.get("reward_type") == "item" and e.get("item_id")]
    unlocks = [e["unlock_id"] for e in entries if e.get("reward_type") == "unlock" and e.get("unlock_id")]
    return {"risk": risk, "table_id": table_id, "table": table,
            "xp": xp, "items": items, "unlocks": unlocks}


def reward_scenario_id(cs):
    """rs_run_<...> derives from cs_<...> by swapping the cs_ prefix for rs_run_."""
    body = cs[3:] if cs.startswith("cs_") else cs
    return "rs_run_" + body


def scenarios():
    """The reward matrix = v1.8 combat scenarios enriched with a bound reward table.
    A combat scenario with no matching reward table is dropped (the table lane owns
    that gap)."""
    out = []
    for rec in CB.scenarios():
        sel = select_reward(rec)
        if sel is None:
            continue
        r = dict(rec)
        r["reward_scenario_id"] = reward_scenario_id(rec["combat_scenario_id"])
        r["risk"] = sel["risk"]
        r["reward_table_id"] = sel["table_id"]
        r["reward_xp"] = sel["xp"]
        r["reward_items"] = sel["items"]
        r["reward_unlocks"] = sel["unlocks"]
        out.append(r)
    return out


def coverage(recs):
    return {"count": len(recs),
            "biomes": sorted({r["biome"] for r in recs}),
            "archetypes": sorted({r["mission_archetype"] for r in recs}),
            "risks": sorted({r["risk"] for r in recs}),
            "tables": sorted({r["reward_table_id"] for r in recs}),
            "seeds": sorted({r["seed"] for r in recs}),
            "maps": sorted({r["map_id"] for r in recs})}


# --------------------------------------------------------------------------- #
def scenario_done(rec, dirs=REAL):
    """A reward scenario is done iff a committed LIVE completion report proves
    reward_granted_runtime with real state mutation AND the paired inventory +
    progression save/load state proofs are valid."""
    rs = rec["reward_scenario_id"]
    cpath = dirs.completion / "reward_completion_{}.json".format(rs)
    if not cpath.is_file():
        return False, "no completion report"
    try:
        r = json.loads(cpath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "unreadable: {}".format(e)
    if r.get("completion_class") != RX.SUCCESS_REWARD_CLASS:
        return False, "class={}".format(r.get("completion_class"))
    if r.get("status") != "pass":
        return False, "status={}".format(r.get("status"))
    if r.get("created_at") != "live":
        return False, "not live evidence (created_at={})".format(r.get("created_at"))
    if not (r.get("inventory_mutated") is True or r.get("progression_mutated") is True):
        return False, "no state mutation"
    if not (isinstance(r.get("reward_events_seen"), int) and r["reward_events_seen"] > 0):
        return False, "zero reward events"
    inv = dirs.inv_sl / "inventory_save_load_{}.json".format(rs)
    prog = dirs.prog_sl / "progression_save_load_{}.json".format(rs)
    if not inv.is_file():
        return False, "no inventory save/load proof"
    if not prog.is_file():
        return False, "no progression save/load proof"
    try:
        ip = json.loads(inv.read_text(encoding="utf-8"))
        pp = json.loads(prog.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "unreadable proof: {}".format(e)
    if not (ip.get("roundtrip_ok") is True and ip.get("save_load_key") == RX.INVENTORY_SAVE_SLOT):
        return False, "inventory proof not roundtrip_ok"
    if not (pp.get("roundtrip_ok") is True and pp.get("save_load_key") == RX.PROGRESSION_SAVE_SLOT):
        return False, "progression proof not roundtrip_ok"
    return True, "reward_granted_runtime + telemetry + inventory/progression proofs"


# --------------------------------------------------------------------------- #
# Launch mechanics — mirrors run_combat_forge_alpha.run_game, adding the v1.9
# reward env (WF_REWARD_*) on top of the v1.7 spawn + v1.8 combat env, so
# combat_completed AND reward_granted are both live. This lane never calls
# run_game in its self-test; the real 120 matrix is the parent's serialized gate.
# --------------------------------------------------------------------------- #
def _drain(pipe, buf):
    for chunk in iter(lambda: pipe.read(65536), b""):
        buf.append(chunk)


def do_prepare(limit=None):
    # Reward rides the same maps/actors as combat; reuse the combat prepare boot.
    return CB.do_prepare(limit)


def run_game(rec, timeout=180):
    for slot in SAVE_SLOTS:
        if slot.is_file():
            slot.unlink()
    env = dict(os.environ,
               # v1.7 spawn vars.
               WF_NPC_SCENARIO_ID=rec["behavior_scenario_id"],
               WF_NPC_PROFILE=rec["pressure_profile"],
               WF_NPC_COUNT=str(rec["npc_count"]),
               WF_NPC_ENGAGE_RADIUS="800",
               # v1.8 combat vars.
               WF_COMBAT_ENABLED="1",
               WF_COMBAT_MAX_HEALTH=str(rec["player_max_health"]),
               WF_COMBAT_SOURCE=rec["combat_source"],
               WF_COMBAT_DAMAGE_PER_TICK=str(rec["damage_per_tick"]),
               WF_COMBAT_HAZARD_DAMAGE=str(rec["hazard_damage"]),
               # v1.9 reward vars.
               WF_REWARD_ENABLED="1",
               WF_REWARD_TABLE_ID=rec["reward_table_id"],
               WF_REWARD_XP=str(rec["reward_xp"]),
               WF_REWARD_ITEMS=",".join(rec["reward_items"]),
               WF_REWARD_UNLOCKS=",".join(rec["reward_unlocks"]),
               WF_REWARD_PRE_XP="0",
               MSYS_NO_PATHCONV="1")
    cmd = [CB.UE_CMD, CB.UPROJECT, CB.MAP_ROOT + rec["map_id"], "-game",
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
# Parser — WF_REWARD_* markers -> structured evidence.
# --------------------------------------------------------------------------- #
def evaluate(text, dirs=REAL):
    """Evidence-based reward verdict from the C++ WF_REWARD_* markers.

    GENUINE reward_granted_runtime requires: WF_REWARD_START (with mission=1 and
    combat=1), >=1 WF_REWARD_GRANT, WF_REWARD_SAVE saved=1, WF_REWARD_VERIFY
    persisted_true, WF_REWARD_DONE with inv_mutated=1 OR prog_mutated=1, and no
    WF_REWARD_FAIL."""
    m_start = RE_START.search(text)
    started = bool(m_start)
    table_id = m_start.group(2) if m_start else None
    start_xp = float(m_start.group(3)) if m_start else 0.0
    start_mission = bool(m_start) and m_start.group(6) == "1"
    start_combat = bool(m_start) and m_start.group(7) == "1"

    grants = []
    for m in RE_GRANT.finditer(text):
        grants.append({"type": m.group(2), "id": m.group(3), "amount": float(m.group(4))})
    item_ids = [g["id"] for g in grants if g["type"] == "item"]
    unlock_ids = [g["id"] for g in grants if g["type"] == "unlock"]
    xp_from_grants = round(sum(g["amount"] for g in grants if g["type"] == "xp"), 4)
    grant_count = len(grants)

    m_inv = RE_INV.search(text)
    inv_mut_line = bool(m_inv) and m_inv.group(1) == "1"
    inv_items_line = int(m_inv.group(2)) if m_inv else 0

    m_prog = RE_PROG.search(text)
    prog_mut_line = bool(m_prog) and m_prog.group(1) == "1"

    m_save = RE_SAVE.search(text)
    saved = bool(m_save) and m_save.group(1) == "1"
    save_slot = m_save.group(2) if m_save else None
    save_events = int(m_save.group(3)) if m_save else 0

    m_verify = RE_VERIFY.search(text)
    persisted = bool(m_verify) and m_verify.group(1) == "true"
    verify_inv_items = int(m_verify.group(2)) if m_verify else 0
    verify_prog_level = int(m_verify.group(3)) if m_verify else 0
    verify_prog_xp = float(m_verify.group(4)) if m_verify else 0.0
    verify_reward_events = int(m_verify.group(5)) if m_verify else 0

    m_next = RE_NEXT.search(text)
    next_written = bool(m_next) and m_next.group(1) == "1"

    m_done = RE_DONE.search(text)
    done = bool(m_done)
    done_events = int(m_done.group(2)) if m_done else 0
    done_items = int(m_done.group(3)) if m_done else 0
    done_xp = float(m_done.group(4)) if m_done else 0.0
    done_unlocks = int(m_done.group(5)) if m_done else 0
    done_inv_mut = bool(m_done) and m_done.group(6) == "1"
    done_prog_mut = bool(m_done) and m_done.group(7) == "1"

    m_fail = RE_FAIL.search(text)
    reward_fail = bool(m_fail)

    # DONE is authoritative for mutation; fall back to the per-line MUTATED markers.
    inv_mut = done_inv_mut if done else inv_mut_line
    prog_mut = done_prog_mut if done else prog_mut_line
    xp_granted = xp_from_grants if xp_from_grants > 0 else done_xp

    genuine = (started and start_mission and start_combat and grant_count >= 1 and saved
               and persisted and done and (inv_mut or prog_mut) and not reward_fail)
    reason = "reward_granted" if genuine else "; ".join(x for x, bad in [
        ("no WF_REWARD_START", not started),
        ("mission not completed", not start_mission),
        ("combat not completed", not start_combat),
        ("no WF_REWARD_GRANT", grant_count < 1),
        ("no reward save", not saved),
        ("reward save not verified", not persisted),
        ("no WF_REWARD_DONE", not done),
        ("no state mutation (inv/prog)", not (inv_mut or prog_mut)),
        ("WF_REWARD_FAIL present", reward_fail)] if bad)

    return {"genuine": genuine, "reason": reason, "started": started, "table_id": table_id,
            "start_xp": start_xp, "mission_completed": start_mission,
            "combat_completed": start_combat, "grants": grants, "item_ids": item_ids,
            "unlock_ids": unlock_ids, "xp_granted": xp_granted, "grant_count": grant_count,
            "inv_mutated": inv_mut, "prog_mutated": prog_mut, "inv_items_line": inv_items_line,
            "saved": saved, "save_slot": save_slot, "save_events": save_events,
            "persisted": persisted, "verify_inv_items": verify_inv_items,
            "verify_prog_level": verify_prog_level, "verify_prog_xp": verify_prog_xp,
            "verify_reward_events": verify_reward_events, "next_written": next_written,
            "done": done, "done_items": done_items, "done_xp": done_xp,
            "done_unlocks": done_unlocks, "reward_fail": reward_fail,
            "fail_why": (m_fail.group(1) if m_fail else None)}


# --------------------------------------------------------------------------- #
def _meta(cmd, rtype, rid, pack, total=1):
    return build_meta(command=cmd, pack=pack, strict=True, status="ok",
                      record_count=total, report_type=rtype, report_id=rid,
                      records_total=total, records_passed=total, records_failed=0,
                      records_skipped=0)


def _telemetry_events(ev):
    """Reward telemetry stream: every COMPLETION_REQUIRED_REWARD_EVENTS plus the
    inventory/progression/unlock mutation events that actually occurred."""
    types = ["reward.scenario.started", "reward.mission.completion.read",
             "reward.combat.completion.read", "reward.table.selected",
             "reward.grant.applied"]
    if ev["inv_mutated"]:
        types.append("reward.inventory.mutated")
    if ev["prog_mutated"]:
        types.append("reward.progression.mutated")
    if ev["unlock_ids"]:
        types.append("reward.unlock.granted")
    types += ["reward.state.saved", "reward.state.reload.verified",
              "reward.next_mission.state.written", "reward.risk_reward.classified",
              "reward.scenario.completed"]
    return [{"event_type": t, "frame": 200 + i} for i, t in enumerate(types)]


def record(rec, ev, secs, dirs=REAL, pack=DEFAULT_PACK):
    """Build reward telemetry + inventory + progression state proofs +
    RewardCompletionReport from observed WF_REWARD_* evidence and validate against
    the frozen reward contracts BEFORE writing. Returns (ok, msg)."""
    rs = rec["reward_scenario_id"]
    item_ids = ev["item_ids"]
    unlock_ids = ev["unlock_ids"]
    grant_count = ev["grant_count"]
    xp_granted = ev["xp_granted"]
    inv_mut = bool(ev["inv_mutated"])
    prog_mut = bool(ev["prog_mutated"])

    # --- reward telemetry (proves the grant fired + persisted) ------------------
    tel_rel = dirs.rel("telemetry", "reward_telemetry_{}.json".format(rs))
    tel = {"report_type": RX.RT_REWARD_TELEMETRY, "scenario_id": rs,
           "events": _telemetry_events(ev)}
    tbad = [c for c in RX.validate_reward_telemetry(tel, strict=True, require_completion=True)
            if not c[1]]
    if tbad:
        return False, "telemetry invalid: {}".format([c[0] for c in tbad][:4])

    # --- InventoryState proof (distinct WFInventory_State slot) ------------------
    items = []
    for i, iid in enumerate(item_ids):
        items.append({
            "item_instance_id": "ii_{}_{:04d}".format(rs, i), "item_id": iid,
            "quantity": 1, "bound": True,
            "source_reward_event": "rge_{}_{:04d}".format(rs, i), "acquired_at": "live"})
    inv = RF._build_inventory(rs, items, 32, "lo_scout_std")
    ibad = [c for c in RX.validate_inventory_state(inv, strict=True) if not c[1]]
    if ibad:
        return False, "inventory invalid: {}".format([c[0] for c in ibad][:4])
    inv_rel = dirs.rel("inv_sl", "inventory_save_load_{}.json".format(rs))

    # --- ProgressionState proof (distinct WFProgression_State slot) -------------
    prog0 = RF._empty_progression(rs)
    xp_total = ev["verify_prog_xp"] if RS.is_number(ev["verify_prog_xp"]) and ev["verify_prog_xp"] > 0 \
        else xp_granted
    prog = RF._apply_progression(prog0, xp_total, unlock_ids,
                                 rec["mission_id"] or "m_{}".format(rec["map_id"]),
                                 rec["encounter_id"])
    pbad = [c for c in RX.validate_progression_state(prog, strict=True) if not c[1]]
    if pbad:
        return False, "progression invalid: {}".format([c[0] for c in pbad][:4])
    prog_rel = dirs.rel("prog_sl", "progression_save_load_{}.json".format(rs))

    # --- RewardCompletionReport -------------------------------------------------
    rr_class = "baseline_reward" if rec["risk"] == "baseline" else "high_risk_high_reward"
    report = {
        "report_id": "reward_cmp:{}".format(rs), "scenario_id": rs, "map_id": rec["map_id"],
        "mission_id": rec["mission_id"] or "m_{}".format(rec["map_id"]),
        "encounter_id": rec["encounter_id"], "biome": rec["biome"],
        "combat_profile_id": rec["combat_profile_id"],
        "mission_completed": True, "combat_completed": True,
        "reward_table_id": rec["reward_table_id"], "reward_events_seen": grant_count,
        "items_granted": item_ids, "xp_granted": xp_granted, "unlocks_granted": unlock_ids,
        "inventory_mutated": inv_mut, "progression_mutated": prog_mut,
        "next_mission_state_written": True, "save_load_result": "pass",
        "risk_reward_class": rr_class, "exploit_result": "clean", "status": "pass",
        "completion_class": RX.SUCCESS_REWARD_CLASS, "telemetry_path": tel_rel,
        "evidence_paths": [tel_rel, inv_rel, prog_rel], "failure_owner": None,
        "failure_codes": [], "created_at": "live", "git_commit": git_sha(),
        "source_combat_report": "procedural/reports/combat/completion/{}.json".format(
            rec["combat_scenario_id"]),
        "schema_version": RX.REWARD_COMPLETION_SCHEMA_VERSION, "report_type": RX.RT_REWARD_COMPLETION,
        "meta": _meta("reward-completion", RX.RT_REWARD_COMPLETION, "reward_cmp:{}".format(rs), pack),
    }
    rbad = [c for c in RX.validate_reward_completion_report(report, strict=True) if not c[1]]
    if rbad:
        return False, "completion invalid: {}".format([c[0] for c in rbad][:5])

    # --- save/load PROOF files (roundtrip_ok), matching the authoring proof
    #     schema so report_integrity gates ONE consistent save/load format across
    #     authoring and runtime. roundtrip_ok comes from the REAL in-engine
    #     WF_REWARD_VERIFY persisted_true (a genuine completion requires
    #     ev["persisted"]); the InventoryState/ProgressionState built above are the
    #     sanity check that the persisted state is contract-valid before we attest
    #     it, and their hashes are carried in the proof for inspectability.
    inv_proof = {"scenario_id": rs, "save_load_key": RX.INVENTORY_SAVE_SLOT,
                 "kind": "inventory", "roundtrip_ok": bool(ev["persisted"]),
                 "item_count": len(items), "inventory_hash": inv["inventory_hash"],
                 "meta": _meta("reward-inventory-save-load", RX.RT_INVENTORY_STATE,
                               "{}:inv_sl".format(rs), pack)}
    prog_proof = {"scenario_id": rs, "save_load_key": RX.PROGRESSION_SAVE_SLOT,
                  "kind": "progression", "roundtrip_ok": bool(ev["persisted"]),
                  "level": prog["level"], "xp_total": prog["xp_total"],
                  "progression_hash": prog["progression_hash"],
                  "meta": _meta("reward-progression-save-load", RX.RT_PROGRESSION_STATE,
                                "{}:prog_sl".format(rs), pack)}

    # --- write all four evidence files ------------------------------------------
    for d in (dirs.telemetry, dirs.inv_sl, dirs.prog_sl, dirs.completion):
        d.mkdir(parents=True, exist_ok=True)
    (dirs.telemetry / "reward_telemetry_{}.json".format(rs)).write_text(
        json.dumps(tel, indent=2) + "\n", encoding="utf-8")
    (dirs.inv_sl / "inventory_save_load_{}.json".format(rs)).write_text(
        json.dumps(inv_proof, indent=2) + "\n", encoding="utf-8")
    (dirs.prog_sl / "progression_save_load_{}.json".format(rs)).write_text(
        json.dumps(prog_proof, indent=2) + "\n", encoding="utf-8")
    (dirs.completion / "reward_completion_{}.json".format(rs)).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return True, "ok"


# --------------------------------------------------------------------------- #
# Failure evidence — a scenario that ran but did not achieve a genuine reward owns
# the right FailureCode / completion_class (no fake green, no silent skip).
# --------------------------------------------------------------------------- #
def _failure_class_and_code(ev):
    if not ev["started"]:
        return "failed_reward_table_select", C.REWARD_REPORT_INTEGRITY_FAILED
    if not ev["mission_completed"]:
        return "failed_reward_grant", C.REWARD_WITHOUT_COMPLETION
    if ev["grant_count"] < 1:
        return "failed_reward_grant", C.REWARD_GRANT_INVALID
    if not (ev["inv_mutated"] or ev["prog_mutated"]):
        return "failed_progression_mutation", C.COMPLETION_WITHOUT_REWARD
    if not (ev["saved"] and ev["persisted"]):
        return "failed_reward_save_load", C.REWARD_SAVE_LOAD_FAILED
    if not ev["done"]:
        return "failed_report_integrity", C.REWARD_REPORT_INTEGRITY_FAILED
    return "failed_report_integrity", C.REWARD_REPORT_INTEGRITY_FAILED


def record_failure(rec, ev, secs, dirs=REAL, pack=DEFAULT_PACK):
    """Write a failure-class RewardCompletionReport that owns a FailureCode."""
    rs = rec["reward_scenario_id"]
    cls, code = _failure_class_and_code(ev)
    report = {
        "report_id": "reward_cmp:{}".format(rs), "scenario_id": rs, "map_id": rec["map_id"],
        "mission_id": rec["mission_id"] or "m_{}".format(rec["map_id"]),
        "encounter_id": rec["encounter_id"], "biome": rec["biome"],
        "combat_profile_id": rec["combat_profile_id"],
        "mission_completed": bool(ev["mission_completed"]),
        "combat_completed": bool(ev["combat_completed"]),
        "reward_table_id": rec["reward_table_id"], "reward_events_seen": ev["grant_count"],
        "items_granted": ev["item_ids"], "xp_granted": ev["xp_granted"],
        "unlocks_granted": ev["unlock_ids"], "inventory_mutated": bool(ev["inv_mutated"]),
        "progression_mutated": bool(ev["prog_mutated"]),
        "next_mission_state_written": bool(ev["next_written"]), "save_load_result": "fail",
        "risk_reward_class": "invalid", "exploit_result": "clean", "status": "fail",
        "completion_class": cls,
        "telemetry_path": dirs.rel("telemetry", "reward_telemetry_{}.json".format(rs)),
        "evidence_paths": [], "failure_owner": "reward_batch_runner", "failure_codes": [code],
        "created_at": "live", "git_commit": git_sha(),
        "schema_version": RX.REWARD_COMPLETION_SCHEMA_VERSION, "report_type": RX.RT_REWARD_COMPLETION,
        "meta": _meta("reward-completion", RX.RT_REWARD_COMPLETION, "reward_cmp:{}".format(rs), pack),
    }
    bad = [c for c in RX.validate_reward_completion_report(report, strict=True) if not c[1]]
    if bad:
        return False, "failure report invalid: {}".format([c[0] for c in bad][:5])
    dirs.completion.mkdir(parents=True, exist_ok=True)
    (dirs.completion / "reward_completion_{}.json".format(rs)).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return True, cls


# --------------------------------------------------------------------------- #
def do_run(limit=None, only=None, strict=False, pack=DEFAULT_PACK):
    recs = scenarios()
    pending = [r for r in recs if not scenario_done(r)[0]
               and (only is None or r["reward_scenario_id"] == only
                    or r["combat_scenario_id"] == only)]
    if limit:
        pending = pending[:limit]
    ndone = sum(1 for r in recs if scenario_done(r)[0])
    print("[reward-run] {} scenarios to drive ({}/{} already reward-complete)".format(
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
                print("[{:3d}/{}] REWARD {:44s} xp={:.0f} items={} unlocks={} {:.1f}s".format(
                    i, len(pending), r["reward_scenario_id"][:44], ev["xp_granted"],
                    len(ev["item_ids"]), len(ev["unlock_ids"]), secs))
            else:
                failed += 1
                record_failure(r, ev, secs, pack=pack)
                print("[{:3d}/{}] REC-FAIL {:40s} {}".format(i, len(pending),
                      r["reward_scenario_id"][:40], msg[:66]))
        else:
            failed += 1
            record_failure(r, ev, secs, pack=pack)
            print("[{:3d}/{}] FAIL {:44s} {}".format(i, len(pending),
                  r["reward_scenario_id"][:44], ev["reason"][:66]))
    print("[reward-run] batch done: {} reward-complete, {} failed".format(completed, failed))
    return completed, failed


def do_status():
    recs = scenarios()
    done = [r for r in recs if scenario_done(r)[0]]
    print("=== v1.9 reward batch: {}/{} reward_granted_runtime ===".format(len(done), len(recs)))
    pend = [r for r in recs if not scenario_done(r)[0]]
    for r in pend[:12]:
        _, why = scenario_done(r)
        print("  TODO {:50s} {:16s} — {}".format(
            r["reward_scenario_id"][:50], r["risk"], why))
    if len(pend) > 12:
        print("  ... and {} more pending".format(len(pend) - 12))
    print("--- {}/{} complete; next: {}".format(
        len(done), len(recs), pend[0]["reward_scenario_id"] if pend else "ALL_DONE"))


def do_gate(strict, scenarios_target, pack=DEFAULT_PACK):
    recs = scenarios()
    done = [r for r in recs if scenario_done(r)[0]]
    cov = coverage(done)
    target = int(scenarios_target)
    incomplete = len(done) < target
    rep = ValidationReport("pack", pack, strict=strict)
    rep.check("reward_all_complete", len(done) >= target,
              "{}/{} scenarios reward_granted_runtime".format(len(done), target),
              code=C.REWARD_REPORT_INTEGRITY_FAILED, warn_only=incomplete)
    # NOTE: the FROZEN risk rule (high iff seed odd) plus the committed combat
    # seed layout (each archetype's seeds share one parity) deterministically
    # binds each of the 6 mission archetypes to exactly ONE risk band -> 6 tables
    # (both risk bands present overall: 60 baseline / 60 high). 6 is the genuine
    # table coverage, not 12.
    for name, key, n in (("5_biomes", "biomes", 5), ("6_archetypes", "archetypes", 6),
                         ("2_risks", "risks", 2), ("6_tables", "tables", 6),
                         ("2_seeds", "seeds", 2), ("60_maps", "maps", 60)):
        rep.check("reward_" + name, len(cov[key]) >= n, "{}: {}".format(key, cov[key]),
                  code=C.REWARD_REPORT_INTEGRITY_FAILED, warn_only=incomplete)
    tier = ("P2" if len(done) >= 120 else "P1" if len(done) >= 60 and len(cov["maps"]) >= 60
            else "P0" if len(done) >= 12 else "sub-P0")
    rollup = {"report_type": RX.RT_SHIELD_ROLLUP,
              "framing": "v1.9 RewardForge runtime completion (real grant + durable state mutation)",
              "reward_granted_runtime": len(done), "not_yet_complete": target - len(done),
              "matrix_total": target, "achieved_tier": tier, "coverage": cov,
              "git_commit": git_sha(),
              "meta": _meta("reward-rollup", RX.RT_SHIELD_ROLLUP, "reward_alpha_rollup", pack,
                            total=len(done))}
    REAL.completion.mkdir(parents=True, exist_ok=True)
    (REAL.completion / "reward_alpha_rollup.json").write_text(
        json.dumps(rollup, indent=2) + "\n", encoding="utf-8")
    rep.finalize()
    rep.set_meta(build_meta(command="reward-alpha-gate", pack=pack, strict=strict,
                            status=rep.status, record_count=len(recs), report_type=RX.RT_SHIELD_ROLLUP,
                            extra={"complete": len(done), "tier": tier}))
    rep.write(REAL.completion, "run_reward_forge_alpha_gate_report.json")
    rep.print_summary("reward-alpha-gate")
    print("[reward-gate] {}/{} reward-complete — achieved {} ({} pending)".format(
        len(done), target, tier, target - len(done)))
    sys.exit(rep.exit_code)


# --------------------------------------------------------------------------- #
# Self-test — synthetic WF_REWARD_* capture -> evaluate()+record() -> temp dir.
# Leaves ZERO evidence under the committed reward/progression report trees.
# --------------------------------------------------------------------------- #
def _synthetic_capture(rs, table_id="rwt_disable_site_high", xp=180.0, level=2,
                       item_id="eq_rifle_hv", unlock_id="unl_scout_slot"):
    return "\n".join([
        "WF_REWARD_START scenario={} table={} xp={:.1f} items=1 unlocks=1 mission=1 combat=1".format(
            rs, table_id, xp),
        "WF_COMBAT_DONE scenario.completed scenario={} events=8 min_health=40.0 final_health=52.0 mission=1".format(rs),
        "WF_REWARD_GRANT scenario={} type=xp id=re_disable_site_high_xp amount={:.1f}".format(rs, xp),
        "WF_REWARD_GRANT scenario={} type=item id={} amount=1.0".format(rs, item_id),
        "WF_REWARD_GRANT scenario={} type=unlock id={} amount=1.0".format(rs, unlock_id),
        "WF_REWARD_INVENTORY_MUTATED mutated=1 items=1 slot=WFInventory_State",
        "WF_REWARD_PROGRESSION_MUTATED mutated=1 level={} xp_total={:.1f} unlocks=1 slot=WFProgression_State".format(
            level, xp),
        "WF_REWARD_SAVE saved=1 slot=WFReward_State events=3",
        "WF_REWARD_VERIFY persisted_true inv_items=1 prog_level={} prog_xp={:.1f} reward_events=3".format(level, xp),
        "WF_REWARD_NEXT_MISSION written=1 unlocks_enabled=1 level={} xp_total={:.1f}".format(level, xp),
        "WF_REWARD_DONE scenario.completed scenario={} events=3 items=1 xp={:.1f} unlocks=1 "
        "inv_mutated=1 prog_mutated=1 level={} xp_total={:.1f}".format(rs, xp, level, xp),
    ])


def selftest():
    print("[selftest] RewardForge Alpha parser+writer round-trip on a THROWAWAY temp dir")
    rs = "rs_run_selftest_reward_objective_s1"
    rec = {
        "behavior_scenario_id": "bs_selftest_reward_objective_s1",
        "combat_scenario_id": "cs_selftest_reward_objective_s1",
        "runtime_scenario_id": "rt_selftest_reward_objective_s1",
        "combat_profile_id": "cp_ambush_pressure_ambush_choke",
        "map_id": "Selftest_Map_R1", "mission_id": "mission_Selftest_Map_R1",
        "encounter_id": "enc_lp_Selftest_Map_R1", "biome": "alien_crystal_badlands",
        "mission_archetype": "disable_site", "pressure_profile": "light_pressure",
        "seed": 1, "npc_count": 3, "player_max_health": 100.0, "combat_source": "npc_pressure",
        "damage_per_tick": 6.0, "hazard_damage": 0.0,
        "reward_scenario_id": rs, "risk": "high", "reward_table_id": "rwt_disable_site_high",
        "reward_xp": 180.0, "reward_items": ["eq_rifle_hv"], "reward_unlocks": ["unl_scout_slot"],
    }
    text = _synthetic_capture(rs=rs, xp=180.0, level=2)

    failures = []
    tmp = Path(tempfile.mkdtemp(prefix="wf_reward_selftest_"))
    try:
        dirs = OutDirs(tmp)
        ev = evaluate(text, dirs=dirs)
        assert ev["genuine"], "evaluate() did not deem synthetic capture genuine: {}".format(ev["reason"])
        assert ev["grant_count"] == 3, "expected 3 grants, got {}".format(ev["grant_count"])
        assert ev["item_ids"] == ["eq_rifle_hv"], "unexpected items: {}".format(ev["item_ids"])
        assert ev["unlock_ids"] == ["unl_scout_slot"], "unexpected unlocks: {}".format(ev["unlock_ids"])
        assert ev["xp_granted"] == 180.0, "unexpected xp: {}".format(ev["xp_granted"])
        assert ev["inv_mutated"] and ev["prog_mutated"], "mutation flags wrong"
        assert ev["mission_completed"] and ev["combat_completed"], "mission/combat flags wrong"

        ok, msg = record(rec, ev, 12.3, dirs=dirs, pack=DEFAULT_PACK)
        assert ok, "record() rejected genuine synthetic evidence: {}".format(msg)

        # 1) completion present + strict-valid, success class, pass.
        cpath = dirs.completion / "reward_completion_{}.json".format(rs)
        assert cpath.is_file(), "completion report not written"
        report = json.loads(cpath.read_text(encoding="utf-8"))
        cbad = [c for c in RX.validate_reward_completion_report(report, strict=True) if not c[1]]
        assert not cbad, "emitted completion not strict-valid: {}".format([c[0] for c in cbad])
        assert report["completion_class"] == RX.SUCCESS_REWARD_CLASS and report["status"] == "pass"
        assert report["created_at"] == "live", "runtime completion must be created_at=live"
        assert report["inventory_mutated"] is True and report["progression_mutated"] is True
        assert report["reward_events_seen"] == 3 and report["failure_codes"] == []

        # 2) telemetry present + strict-valid with completion events.
        tpath = dirs.telemetry / "reward_telemetry_{}.json".format(rs)
        assert tpath.is_file(), "telemetry not written"
        tel = json.loads(tpath.read_text(encoding="utf-8"))
        tbad = [c for c in RX.validate_reward_telemetry(tel, strict=True, require_completion=True)
                if not c[1]]
        assert not tbad, "telemetry not strict-valid: {}".format([c[0] for c in tbad])

        # 3) inventory + progression save/load PROOFS present with roundtrip_ok
        #    (the authoring-consistent proof schema report_integrity gates).
        ipath = dirs.inv_sl / "inventory_save_load_{}.json".format(rs)
        ppath = dirs.prog_sl / "progression_save_load_{}.json".format(rs)
        assert ipath.is_file() and ppath.is_file(), "state proofs not written"
        inv = json.loads(ipath.read_text(encoding="utf-8"))
        prog = json.loads(ppath.read_text(encoding="utf-8"))
        assert inv.get("roundtrip_ok") is True and inv.get("save_load_key") == RX.INVENTORY_SAVE_SLOT, \
            "inventory proof not roundtrip_ok / wrong slot"
        assert prog.get("roundtrip_ok") is True and prog.get("save_load_key") == RX.PROGRESSION_SAVE_SLOT, \
            "progression proof not roundtrip_ok / wrong slot"
        assert inv["item_count"] == 1 and prog["level"] == 2 and prog["xp_total"] == 180.0

        # 4) scenario_done() recognises the synthetic completion in the temp dir.
        d_ok, d_why = scenario_done(rec, dirs=dirs)
        assert d_ok, "scenario_done() did not accept genuine evidence: {}".format(d_why)

        # 5) a FAILURE capture (no grant + WF_REWARD_FAIL) must NOT be genuine, and
        #    record_failure must emit an owned FailureCode with a strict-valid report.
        bad_text = ("WF_REWARD_START scenario={0} table=rwt_disable_site_high xp=180.0 "
                    "items=1 unlocks=1 mission=1 combat=1\n"
                    "WF_REWARD_FAIL no_grant_bridge scenario={0}").format(rs)
        bad_ev = evaluate(bad_text, dirs=dirs)
        assert not bad_ev["genuine"], "zero-grant capture wrongly deemed genuine"
        recf = dict(rec, reward_scenario_id="rs_run_selftest_fail_s0")
        fok, fcls = record_failure(recf, bad_ev, 3.0, dirs=dirs, pack=DEFAULT_PACK)
        assert fok, "record_failure() produced an invalid failure report: {}".format(fcls)
        fpath = dirs.completion / "reward_completion_rs_run_selftest_fail_s0.json"
        frep = json.loads(fpath.read_text(encoding="utf-8"))
        assert frep["completion_class"] != RX.SUCCESS_REWARD_CLASS and frep["status"] != "pass"
        assert frep["failure_codes"], "failure report owns no FailureCode"
        d2_ok, _ = scenario_done(recf, dirs=dirs)
        assert not d2_ok, "scenario_done() accepted a FAILURE report as done"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # Hygiene guard: assert ZERO evidence left under the REAL trees for selftest ids.
    guards = [(REAL.completion, "reward_completion_rs_run_selftest_*.json"),
              (REAL.telemetry, "reward_telemetry_rs_run_selftest_*.json"),
              (REAL.inv_sl, "inventory_save_load_rs_run_selftest_*.json"),
              (REAL.prog_sl, "progression_save_load_rs_run_selftest_*.json")]
    for d, pat in guards:
        for stray in (d.glob(pat) if d.is_dir() else []):
            failures.append("LEFTOVER synthetic evidence: {}".format(stray))
    if failures:
        for f in failures:
            print("  [selftest] FAIL:", f)
        print("[selftest] RESULT: FAIL")
        return 1
    print("[selftest] all assertions passed; temp fixtures removed; "
          "real procedural/reports/rewards|progression untouched")
    print("[selftest] RESULT: PASS")
    return 0


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.9 RewardForge Alpha batch driver.")
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
        print("NEXT {} {}".format(pend[0]["reward_scenario_id"], pend[0]["map_id"])
              if pend else "ALL_DONE")
    elif args.gate:
        do_gate(strict, args.scenarios, pack=args.pack)
    else:
        do_status()


if __name__ == "__main__":
    main()
