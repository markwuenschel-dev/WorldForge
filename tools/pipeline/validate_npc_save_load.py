#!/usr/bin/env python3
"""validate_npc_save_load.py — WorldForge v1.7 Wave R NPC save/load gate.

Validates every NPC save/load proof the runtime batch emits against the runtime
save/load contract: each proof must record a reload-verified status with matching
pre/post state keys (npc_count + pressure_applied), no missing/mismatched keys, and
reference the distinct NPC save slot (WFNPC_State.sav — proven independently of the
mission-completion save). A proof that is not `verified`, or that laundered a
missing key, fails. FAIL-CLOSED: with no proofs present the gate is RED under strict.

Acceptance: `python tools/pipeline/validate_npc_save_load.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
import runtime_save_load_contract as SL
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

SAVELOAD_DIR = REPO_ROOT / "procedural/reports/npc/save_load"
SKIP = {"validate_npc_save_load_report.json"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    files = sorted(SAVELOAD_DIR.glob("bs_*.json")) if SAVELOAD_DIR.is_dir() else []
    rep.check("save_load::present", len(files) > 0,
              "no NPC save/load proofs (run the NPC behavior batch)",
              code=FailureCode.NPC_SAVE_LOAD_FAILURE)

    bad = verified = 0
    for f in files:
        sid = f.stem
        try:
            proof = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad += 1
            rep.check("sl::{}::readable".format(sid), False, "unreadable: {}".format(e),
                      code=FailureCode.NPC_SAVE_LOAD_FAILURE)
            continue
        for name, ok, detail, code in SL.validate_save_load_proof(proof, strict=strict):
            if not ok:
                bad += 1
                rep.check("sl::{}::{}".format(sid, name), False, detail,
                          code=FailureCode.NPC_SAVE_LOAD_FAILURE)
        if proof.get("status") == SL.VERIFIED:
            verified += 1
            # Must be the distinct NPC slot — not the mission-completion save.
            if "WFNPC_State" not in (proof.get("save_file_path") or ""):
                bad += 1
                rep.check("sl::{}::npc_slot".format(sid), False,
                          "verified proof does not reference the NPC save slot",
                          code=FailureCode.NPC_SAVE_LOAD_FAILURE)

    rep.check("save_load::all_verified", bad == 0,
              "{} save/load check failure(s) across {} proofs".format(bad, len(files)),
              code=FailureCode.NPC_SAVE_LOAD_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-save-load", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type="wf.npc.save_load_report.v1",
                            records_total=len(files), extra={"verified": verified}))
    rep.write(SAVELOAD_DIR, "validate_npc_save_load_report.json")
    rep.print_summary("validate-npc-save-load")
    print("[validate-npc-save-load] {} proofs, {} verified".format(len(files), verified))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
