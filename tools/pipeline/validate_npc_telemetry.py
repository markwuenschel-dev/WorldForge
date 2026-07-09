#!/usr/bin/env python3
"""validate_npc_telemetry.py — WorldForge v1.7 Wave R behavior-telemetry gate.

Validates the live behavior telemetry the runtime batch emits: every telemetry
report must carry a non-empty events list of known behavior event types, and — as
runtime evidence of a genuine behavior_completed_runtime — must contain the full
COMPLETION_REQUIRED_EVENTS set including a real pressure event. A telemetry report
that loads a map but shows no spawn / no pressure / no completion is NOT active
behavior and fails here. FAIL-CLOSED: with no telemetry present the gate is RED
under strict (nothing to prove behavior happened).

Acceptance: `python tools/pipeline/validate_npc_telemetry.py --pack encounter_loop_world --strict`.
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

TELEMETRY_DIR = REPO_ROOT / NX.TELEMETRY_REPORTS_REL


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    files = sorted(TELEMETRY_DIR.glob("bs_*.json")) if TELEMETRY_DIR.is_dir() else []
    rep.check("telemetry::present", len(files) > 0,
              "no behavior telemetry emitted (run the NPC behavior batch)",
              code=FailureCode.NPC_TELEMETRY_MISSING)

    bad = 0
    for f in files:
        sid = f.stem
        try:
            tel = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("tel::{}::readable".format(sid), False, "unreadable: {}".format(e),
                      code=FailureCode.NPC_TELEMETRY_MISSING)
            continue
        for name, ok, detail, code in NX.validate_telemetry(tel, strict=strict, require_completion=True):
            if not ok:
                bad += 1
                rep.check("tel::{}::{}".format(sid, name), False, detail, code=code)

    rep.check("telemetry::all_valid", bad == 0,
              "{} telemetry check failure(s) across {} reports".format(bad, len(files)),
              code=FailureCode.NPC_TELEMETRY_MISSING)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-telemetry", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files), report_type=NX.RT_TELEMETRY,
                            records_total=len(files)))
    rep.write(TELEMETRY_DIR, "validate_npc_telemetry_report.json")
    rep.print_summary("validate-npc-telemetry")
    print("[validate-npc-telemetry] {} telemetry reports checked".format(len(files)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
