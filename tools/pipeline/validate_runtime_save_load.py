#!/usr/bin/env python3
"""validate_runtime_save_load.py — WorldForge v1.6 save/load gate (Agent 6B).

Validates the RuntimeSaveLoadProof each completed scenario produced: a proof may
only be `verified` when every expected state key was verified after reload with
no missing/mismatched keys (no empty-diff success). Proofs only exist AFTER a
live run + save/reload, so with the editor offline this gate fails CLOSED
(RUNTIME_LIVE_RUN_PENDING, blocking under STRICT). Any proofs present are
validated against the frozen save/load contract.

Usage:
    python tools/pipeline/validate_runtime_save_load.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/save_load/validate_runtime_save_load_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_save_load_contract as SL
from runtime_bridge import ue_bridge_live, bridge_status_detail
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def load_proofs():
    d = REPO_ROOT / SL.SAVE_LOAD_REPORTS_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            if p.name.startswith("validate_"):
                continue
            try:
                out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                out[p.stem] = None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 save/load gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    proofs = load_proofs()

    if not proofs:
        rep.check("save_load_proofs_present", False,
                  "no save/load proofs — " + bridge_status_detail(),
                  code=C.RUNTIME_LIVE_RUN_PENDING, warn_only=True)
    else:
        for pid in sorted(proofs):
            for name, ok, detail, code in SL.validate_save_load_proof(proofs[pid] or {}, strict=strict):
                rep.check("{}::{}".format(pid, name), ok, detail, code=code)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-save-load", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(proofs),
                            report_type="wf.runtime.save_load_proof.v1",
                            extra={"proofs": len(proofs), "bridge_live": ue_bridge_live()}))
    rep.write(REPO_ROOT / SL.SAVE_LOAD_REPORTS_REL, "validate_runtime_save_load_report.json")
    rep.print_summary("validate-runtime-save-load")
    print("[validate-runtime-save-load] {} proofs — {}".format(len(proofs), bridge_status_detail()))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
