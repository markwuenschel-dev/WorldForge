#!/usr/bin/env python3
"""validate_npc_damage_bridge.py — WorldForge v1.8 CombatForge NPC-damage-bridge gate.

Proves that v1.7 NPC *behavior pressure* was actually wired to *damage* at runtime.
For every combat completion record whose NPC damage was expected (npc_damage_result
is not 'skipped' — i.e. the scenario's damage source includes npc_pressure), this
gate asserts against the LIVE evidence:

  * at least one DamageEvent with source_type='npc_pressure' and amount>0 landed
    (else NPC_DAMAGE_BRIDGE_FAILURE — pressure never became damage), and
  * the player's health actually dropped: player_min_health < player_max_health
    (else PLAYER_DAMAGE_NOT_APPLIED — the bridge fired but nothing was applied).

Every referenced DamageEvent is also run through the frozen DamageEvent contract so
a fabricated or zero-damage record cannot slip through. Scenarios that do not expect
NPC damage (npc_damage_result == 'skipped') are 'skipped', not failed.

Until the Wave-R UE matrix has emitted evidence the completion dir is empty and this
gate is HONESTLY FAIL-CLOSED (RED); its logic is still proven now by dogfooding a
synthetic VALID record (passes) and a synthetic KNOWN-BAD record (rejected).

Acceptance: `python tools/pipeline/validate_npc_damage_bridge.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / CX.COMBAT_COMPLETION_REPORTS_REL
_SKIPPED_RESULTS = (None, "skipped", "not_implemented")


def _npc_expected(report):
    """A scenario expects NPC damage iff its npc_damage_result is a real (non-skipped)
    result — i.e. npc_pressure is one of its declared damage sources."""
    return report.get("npc_damage_result") not in _SKIPPED_RESULTS


def _load_damage_events(report):
    """Load the DamageEvent list this completion record was realized with. Runtime
    stores them alongside the telemetry stream under a 'damage_events' key."""
    tp = report.get("telemetry_path")
    if not tp:
        return []
    p = REPO_ROOT / tp
    if not p.is_file():
        return []
    try:
        t = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    evs = t.get("damage_events")
    return evs if isinstance(evs, list) else []


def _check_scenario(report, damage_events, strict):
    """Pure logic shared by dogfood + real evidence. Returns (name, ok, detail, code)
    tuples for one NPC-damage-expecting scenario."""
    ch = []
    # Every referenced DamageEvent must itself be a genuine (non-fabricated) record.
    for i, de in enumerate(damage_events):
        for name, ok, detail, code in CX.validate_damage_event(de, strict=strict):
            if not ok:
                ch.append(("de{}::{}".format(i, name), ok, detail, code))
    npc_hits = [de for de in damage_events
                if isinstance(de, dict) and de.get("source_type") == "npc_pressure"
                and CX.RS.is_number(de.get("amount")) and de.get("amount") > 0]
    ch.append(("npc_pressure_damage_present", len(npc_hits) > 0,
               "NPC pressure produced no positive-amount damage event (bridge dead)",
               FailureCode.NPC_DAMAGE_BRIDGE_FAILURE))
    pmax, pmin = report.get("player_max_health"), report.get("player_min_health")
    dropped = CX.RS.is_number(pmax) and CX.RS.is_number(pmin) and pmin < pmax
    ch.append(("player_health_dropped", dropped,
               "player health never dropped (player_min_health < player_max_health) — damage not applied",
               FailureCode.PLAYER_DAMAGE_NOT_APPLIED))
    # npc_damage_result must be an affirmative pass for an NPC-damage scenario.
    ch.append(("npc_damage_result_pass", report.get("npc_damage_result") == "pass",
               "npc_damage_result must be 'pass' for an NPC-damage scenario",
               FailureCode.NPC_DAMAGE_BRIDGE_FAILURE))
    return ch


def _dogfood(rep):
    """Prove logic now with in-memory records (no files touched)."""
    # VALID: NPC-damage scenario, one positive npc_pressure damage event, health dropped.
    good_report = CX._example_combat_completion(npc_damage_result="pass",
                                                player_max_health=100.0, player_min_health=63.0)
    good_events = [CX._example_damage_event()]
    good_fails = [c for c in _check_scenario(good_report, good_events, strict=True) if not c[1]]
    rep.check("dogfood::valid_passes", not good_fails,
              "synthetic NPC-damage scenario passes ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]),
              code=FailureCode.NPC_DAMAGE_BRIDGE_FAILURE)
    # KNOWN-BAD: NPC damage expected, but the only event is a hazard event AND player
    # health never dropped -> bridge dead + damage not applied.
    bad_report = CX._example_combat_completion(npc_damage_result="pass",
                                               player_max_health=100.0, player_min_health=100.0)
    bad_events = [CX._example_damage_event(source_type="hazard", damage_type="hazard_zone",
                                           source_id="hz_0")]
    bad_fails = [c for c in _check_scenario(bad_report, bad_events, strict=True) if not c[1]]
    rep.check("dogfood::known_bad_rejected", len(bad_fails) > 0,
              "synthetic dead-bridge / unapplied-damage scenario is rejected ({} check(s))".format(
                  len(bad_fails)),
              code=FailureCode.NPC_DAMAGE_BRIDGE_FAILURE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-live", action="store_true", default=True)
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    files = sorted(COMPLETION_DIR.glob("cs_*.json")) if COMPLETION_DIR.is_dir() else []
    rep.check("npc_bridge::evidence_present", len(files) > 0,
              "no combat completion evidence in {} (run the Wave-R combat matrix)".format(
                  CX.COMBAT_COMPLETION_REPORTS_REL),
              code=FailureCode.NPC_DAMAGE_BRIDGE_FAILURE)

    bad = applicable = skipped = 0
    for f in files:
        tag = f.stem
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("npc::{}::readable".format(tag), False, "unreadable: {}".format(e),
                      code=FailureCode.NPC_DAMAGE_BRIDGE_FAILURE)
            continue
        if not _npc_expected(report):
            skipped += 1
            rep.skip("npc::{}::not_applicable".format(tag), "scenario has no npc_pressure source")
            continue
        applicable += 1
        for name, ok, detail, code in _check_scenario(report, _load_damage_events(report), strict):
            if not ok:
                bad += 1
                rep.check("npc::{}::{}".format(tag, name), False, detail, code=code)

    if files:
        rep.check("npc_bridge::all_ok", bad == 0,
                  "{} NPC-damage-bridge failure(s) across {} applicable scenario(s)".format(
                      bad, applicable),
                  code=FailureCode.NPC_DAMAGE_BRIDGE_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-damage-bridge", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type=CX.RT_COMBAT_COMPLETION, records_total=len(files),
                            extra={"applicable": applicable, "skipped": skipped,
                                   "evidence_present": bool(files)}))
    rep.write(COMPLETION_DIR, "validate_npc_damage_bridge_report.json")
    rep.print_summary("validate-npc-damage-bridge")
    print("[validate-npc-damage-bridge] {} record(s), {} npc-applicable, {} skipped; evidence_present={}".format(
        len(files), applicable, skipped, bool(files)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
