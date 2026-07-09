#!/usr/bin/env python3
"""classify_npc_pressure.py — WorldForge v1.7 Wave R BalanceForge pressure classifier.

Reads every behavior completion report and classifies its runtime pressure into a
balance band (balanced / too_low / too_high / unwinnable / no_pressure) from the
GENUINE observed evidence — pressure_events_seen and whether the mission actually
completed under that pressure. Emits one balance report per scenario plus a rollup.
This is BalanceForge on real runtime telemetry, not a paper model: no_pressure and
unwinnable are hard integrity failures downstream; too_low / too_high are advisory
(v1.7 alpha pressure is telemetry/state pressure, so it can never itself make a
baseline unwinnable — kept honest).

Acceptance: `python tools/pipeline/classify_npc_pressure.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
from report_meta import build_meta, git_sha, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / NX.COMPLETION_REPORTS_REL
BALANCE_DIR = REPO_ROOT / NX.BALANCE_REPORTS_REL
SKIP = {"npc_behavior_rollup.json", "run_npc_behavior_batch_gate_report.json",
        "validate_npc_completion_report.json"}

# Pressure-event bands (per scenario). Advisory bands (too_low/too_high) do not
# block — alpha pressure is telemetry/state, never damage.
TOO_LOW_MAX = 2       # 1..2 events = thin pressure (advisory)
TOO_HIGH_MIN = 120    # > this = heavy pressure (advisory)


def classify(pev, mission_completed):
    if pev <= 0:
        return "no_pressure"
    if not mission_completed:
        return "unwinnable"
    if pev <= TOO_LOW_MAX:
        return "too_low"
    if pev >= TOO_HIGH_MIN:
        return "too_high"
    return "balanced"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    files = sorted(COMPLETION_DIR.glob("bs_*.json")) if COMPLETION_DIR.is_dir() else []
    rep.check("classify::completions_present", len(files) > 0,
              "no completion reports to classify (run the NPC behavior batch)",
              code=FailureCode.NPC_BALANCE_REPORT_FAILURE)

    BALANCE_DIR.mkdir(parents=True, exist_ok=True)
    bands = {b: 0 for b in NX.BALANCE_CLASSES}
    emitted = 0
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if r.get("completion_class") != NX.SUCCESS_COMPLETION_CLASS:
            continue
        sid = r["behavior_scenario_id"]
        pev = int(r.get("pressure_events_seen", 0))
        mc = r.get("mission_completed") is True
        band = classify(pev, mc)
        bands[band] += 1
        out = {
            "report_type": NX.RT_BALANCE, "behavior_scenario_id": sid,
            "runtime_scenario_id": r.get("runtime_scenario_id"), "map_id": r.get("map_id"),
            "biome": r.get("biome"), "mission_archetype": r.get("mission_archetype"),
            "pressure_profile": r.get("pressure_profile"), "seed": r.get("seed"),
            "npc_count": r.get("npc_count"), "pressure_events_seen": pev,
            "mission_completed": mc, "baseline_winnable": mc,
            "pressure_present": pev > 0, "balance_class": band,
            "advisory": band in ("too_low", "too_high"),
            "created_at": "live", "git_commit": git_sha(),
            "meta": build_meta(command="classify-npc-pressure", pack=args.pack, strict=strict,
                               status="ok", record_count=1, report_type=NX.RT_BALANCE,
                               report_id="npc_balance:{}".format(sid),
                               records_total=1, records_passed=1),
        }
        (BALANCE_DIR / "{}.json".format(sid)).write_text(json.dumps(out, indent=2) + "\n",
                                                         encoding="utf-8")
        emitted += 1

    rollup = {"report_type": "wf.npc.balance_rollup.v1", "pack": args.pack,
              "scenarios_classified": emitted, "bands": bands, "git_commit": git_sha(),
              "meta": build_meta(command="classify-npc-pressure", pack=args.pack, strict=strict,
                                 status="ok", record_count=emitted,
                                 report_type="wf.npc.balance_rollup.v1",
                                 report_id="npc_balance_rollup", records_total=emitted,
                                 records_passed=emitted)}
    (BALANCE_DIR / "balance_rollup.json").write_text(json.dumps(rollup, indent=2) + "\n",
                                                     encoding="utf-8")

    rep.check("classify::no_no_pressure", bands["no_pressure"] == 0,
              "{} scenarios with zero pressure (not active behavior)".format(bands["no_pressure"]),
              code=FailureCode.NPC_NO_PRESSURE_EVENTS)
    rep.check("classify::no_unwinnable", bands["unwinnable"] == 0,
              "{} scenarios unwinnable under pressure".format(bands["unwinnable"]),
              code=FailureCode.NPC_UNWINNABLE_BASELINE)

    rep.finalize()
    rep.set_meta(build_meta(command="classify-npc-pressure", pack=args.pack, strict=strict,
                            status=rep.status, record_count=emitted, report_type=NX.RT_BALANCE,
                            records_total=emitted, extra={"bands": bands}))
    rep.write(BALANCE_DIR, "classify_npc_pressure_report.json")
    rep.print_summary("classify-npc-pressure")
    print("[classify-npc-pressure] {} classified — bands: {}".format(emitted, bands))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
