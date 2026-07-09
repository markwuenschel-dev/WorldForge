#!/usr/bin/env python3
"""validate_npc_completion.py — WorldForge v1.7 Wave R behavior-completion gate.

Validates every behavior completion report against the BehaviorCompletionReport
contract AND the anti-fake-green honesty invariants: a behavior_completed_runtime
must be status=pass with npc_count>0, pressure_events_seen>0, mission_completed=true,
save_load_result=pass, a telemetry_path, no failure codes, and all core results
pass; a failed class must own a failure code + owner. It also cross-checks the
rollup against what is actually on disk (no phantom completions) and confirms the
success reports have a matching telemetry file. FAIL-CLOSED.

Acceptance: `python tools/pipeline/validate_npc_completion.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / NX.COMPLETION_REPORTS_REL
SKIP = {"npc_behavior_rollup.json", "run_npc_behavior_batch_gate_report.json",
        "validate_npc_completion_report.json"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    files = sorted(COMPLETION_DIR.glob("bs_*.json")) if COMPLETION_DIR.is_dir() else []
    rep.check("completion::present", len(files) > 0,
              "no behavior completion reports (run the NPC behavior batch)",
              code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)

    bad = success = 0
    for f in files:
        sid = f.stem
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("cmp::{}::readable".format(sid), False, "unreadable: {}".format(e),
                      code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)
            continue
        for name, ok, detail, code in NX.validate_completion_report(r, strict=strict):
            if not ok:
                bad += 1
                rep.check("cmp::{}::{}".format(sid, name), False, detail, code=code)
        if r.get("completion_class") == NX.SUCCESS_COMPLETION_CLASS:
            success += 1
            # A success must point at a telemetry file that actually exists.
            tp = r.get("telemetry_path") or ""
            exists = bool(tp) and (REPO_ROOT / tp).is_file()
            if not exists:
                bad += 1
                rep.check("cmp::{}::telemetry_on_disk".format(sid), False,
                          "success telemetry_path missing on disk: {}".format(tp),
                          code=FailureCode.NPC_TELEMETRY_MISSING)

    rep.check("completion::all_valid", bad == 0,
              "{} completion check failure(s) across {} reports".format(bad, len(files)),
              code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)

    # rollup consistency: reported count must match on-disk successes.
    rollup = COMPLETION_DIR / "npc_behavior_rollup.json"
    if rollup.is_file():
        try:
            ru = json.loads(rollup.read_text(encoding="utf-8"))
            claimed = ru.get("behavior_completed_runtime")
            rep.check("completion::rollup_matches_disk", claimed == success,
                      "rollup claims {} but {} success reports on disk".format(claimed, success),
                      code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)
        except Exception as e:  # noqa: BLE001
            rep.check("completion::rollup_readable", False, "unreadable rollup: {}".format(e),
                      code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-completion", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files), report_type=NX.RT_COMPLETION,
                            records_total=len(files), extra={"success": success}))
    rep.write(COMPLETION_DIR, "validate_npc_completion_report.json")
    rep.print_summary("validate-npc-completion")
    print("[validate-npc-completion] {} completion reports, {} success".format(len(files), success))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
