#!/usr/bin/env python3
"""validate_runtime_telemetry.py — WorldForge v1.6 telemetry gate (Agent 2E).

Validates the telemetry streams a live run produced: each event well-formed, and
each completed scenario's stream contains the required ordered lifecycle events
(scenario.started ... mission.completed ... scenario.completed). Telemetry only
exists AFTER a live UE run, so with the editor offline there are no streams: this
gate fails CLOSED (RUNTIME_LIVE_RUN_PENDING, blocking under STRICT) rather than
passing on an empty set. Any streams that DO exist are validated against the
frozen telemetry contract.

Usage:
    python tools/pipeline/validate_runtime_telemetry.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/telemetry/validate_runtime_telemetry_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_telemetry_contract as TC
from runtime_bridge import ue_bridge_live, bridge_status_detail
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def load_streams():
    d = REPO_ROOT / TC.TELEMETRY_REPORTS_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            if p.name.startswith("validate_"):
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                out[p.stem] = data.get("events", data) if isinstance(data, dict) else data
            except Exception:
                out[p.stem] = None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 telemetry gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    streams = load_streams()

    if not streams:
        # Fail closed: no telemetry means no live run. WARN -> blocking in STRICT.
        rep.check("telemetry_streams_present", False,
                  "no telemetry streams — " + bridge_status_detail(),
                  code=C.RUNTIME_LIVE_RUN_PENDING, warn_only=True)
    else:
        for sid in sorted(streams):
            checks, completed = TC.validate_stream(streams[sid] or [], strict=strict)
            for name, ok, detail, code in checks:
                rep.check("{}::{}".format(sid, name), ok, detail, code=code)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-telemetry", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(streams),
                            report_type="wf.runtime.telemetry.v1",
                            extra={"streams": len(streams), "bridge_live": ue_bridge_live()}))
    rep.write(REPO_ROOT / TC.TELEMETRY_REPORTS_REL, "validate_runtime_telemetry_report.json")
    rep.print_summary("validate-runtime-telemetry")
    print("[validate-runtime-telemetry] {} streams — {}".format(
        len(streams), bridge_status_detail()))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
