#!/usr/bin/env python3
r"""validate_reward_bridge.py — WorldForge v1.9 Wave R reward runtime-evidence gate.

Gates the RUNTIME reward evidence produced by run_reward_forge_alpha.py: it loads
every RewardCompletionReport whose created_at=="live" (the genuine
reward_granted_runtime evidence — authoring reports carry created_at="authoring"
and are ignored here) and proves, per report, that a real reward grant fired and
mutated durable, reload-verified state:

  * completion_class == reward_granted_runtime, status == pass;
  * inventory_mutated OR progression_mutated is true (real durable consequence);
  * reward_events_seen > 0;
  * git_commit is a real sha (not "unknown"/empty) — the report is anchored to a
    real build, not fabricated;
  * telemetry_path exists AND passes validate_reward_telemetry(require_completion=True);
  * the paired inventory + progression save/load state proofs exist and pass their
    strict validators.

If ZERO live completions exist yet (the real 120 matrix has not been run), this
gate FAILS honestly with RUNTIME_LIVE_RUN_PENDING — it is NEVER green with no
runtime evidence. Report -> procedural/reports/rewards/validate_reward_bridge_report.json.

Usage:
    python tools/pipeline/validate_reward_bridge.py --pack encounter_loop_world [--strict]
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as C

COMPLETION_DIR = REPO_ROOT / RX.REWARD_COMPLETION_REPORTS_REL
INV_SL_DIR = REPO_ROOT / RX.REWARD_SAVE_LOAD_REPORTS_REL
PROG_SL_DIR = REPO_ROOT / "procedural/reports/progression/save_load"
REPORT_DIR = REPO_ROOT / "procedural/reports/rewards"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _live_completions():
    """Every committed RewardCompletionReport whose created_at == 'live'."""
    out = []
    if not COMPLETION_DIR.is_dir():
        return out
    for f in sorted(COMPLETION_DIR.glob("reward_completion_*.json")):
        try:
            r = _load(f)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(r, dict) and r.get("created_at") == "live":
            out.append((f, r))
    return out


def _check_one(rep, f, r):
    rs = r.get("scenario_id") or f.stem
    tag = rs

    rep.check("{}::success_class".format(tag),
              r.get("completion_class") == RX.SUCCESS_REWARD_CLASS,
              "completion_class must be reward_granted_runtime (got {})".format(r.get("completion_class")),
              code=C.REWARD_REPORT_INTEGRITY_FAILED)
    rep.check("{}::status_pass".format(tag), r.get("status") == "pass",
              "status must be pass (got {})".format(r.get("status")),
              code=C.REWARD_REPORT_INTEGRITY_FAILED)
    # Report body must itself be contract-valid at strict.
    rbad = [c for c in RX.validate_reward_completion_report(r, strict=True) if not c[1]]
    rep.check("{}::report_contract_valid".format(tag), not rbad,
              "completion report invalid: {}".format([c[0] for c in rbad][:5]),
              code=C.REWARD_COMPLETION_REPORT_INVALID)
    rep.check("{}::state_mutated".format(tag),
              r.get("inventory_mutated") is True or r.get("progression_mutated") is True,
              "inventory_mutated or progression_mutated must be true (no durable consequence)",
              code=C.COMPLETION_WITHOUT_REWARD)
    cnt = r.get("reward_events_seen")
    rep.check("{}::events_seen".format(tag), isinstance(cnt, int) and cnt > 0,
              "reward_events_seen must be > 0 (got {})".format(cnt),
              code=C.REWARD_GRANT_INVALID)
    sha = r.get("git_commit")
    rep.check("{}::real_git_commit".format(tag),
              isinstance(sha, str) and sha not in ("", "unknown"),
              "git_commit must be a real sha (got {!r})".format(sha),
              code=C.REWARD_REPORT_INTEGRITY_FAILED)

    # Telemetry file exists and passes require_completion validator.
    tpath = r.get("telemetry_path")
    tfile = REPO_ROOT / tpath if isinstance(tpath, str) and tpath else None
    t_ok = bool(tfile) and tfile.is_file()
    rep.check("{}::telemetry_exists".format(tag), t_ok,
              "telemetry_path missing or not a file: {}".format(tpath),
              code=C.REWARD_TELEMETRY_MISSING)
    if t_ok:
        try:
            tel = _load(tfile)
            tbad = [c for c in RX.validate_reward_telemetry(tel, strict=True, require_completion=True)
                    if not c[1]]
        except Exception as e:  # noqa: BLE001
            tbad = [("unreadable", False, str(e), None)]
        rep.check("{}::telemetry_valid".format(tag), not tbad,
                  "telemetry not completion-valid: {}".format([c[0] for c in tbad][:4]),
                  code=C.REWARD_TELEMETRY_MISSING)

    # Paired inventory + progression save/load state proofs exist and validate.
    inv_f = INV_SL_DIR / "inventory_save_load_{}.json".format(rs)
    prog_f = PROG_SL_DIR / "progression_save_load_{}.json".format(rs)
    rep.check("{}::inventory_proof_exists".format(tag), inv_f.is_file(),
              "missing inventory save/load proof: {}".format(inv_f.name),
              code=C.REWARD_SAVE_LOAD_MISSING)
    rep.check("{}::progression_proof_exists".format(tag), prog_f.is_file(),
              "missing progression save/load proof: {}".format(prog_f.name),
              code=C.REWARD_SAVE_LOAD_MISSING)
    # The runtime save/load evidence is a PROOF (roundtrip_ok), consistent with the
    # authoring proof schema and what reward_report_integrity gates: the in-engine
    # WF_REWARD_VERIFY persisted_true is the roundtrip. Require roundtrip_ok=true on
    # the correct dedicated slot.
    if inv_f.is_file():
        try:
            ip = _load(inv_f)
            ib_ok = ip.get("roundtrip_ok") is True and ip.get("save_load_key") == RX.INVENTORY_SAVE_SLOT
            idetail = "inventory proof roundtrip_ok={} slot={}".format(
                ip.get("roundtrip_ok"), ip.get("save_load_key"))
        except Exception as e:  # noqa: BLE001
            ib_ok, idetail = False, "unreadable: {}".format(e)
        rep.check("{}::inventory_proof_valid".format(tag), ib_ok, idetail,
                  code=C.INVENTORY_SAVE_LOAD_FAILED)
    if prog_f.is_file():
        try:
            pp = _load(prog_f)
            pb_ok = pp.get("roundtrip_ok") is True and pp.get("save_load_key") == RX.PROGRESSION_SAVE_SLOT
            pdetail = "progression proof roundtrip_ok={} slot={}".format(
                pp.get("roundtrip_ok"), pp.get("save_load_key"))
        except Exception as e:  # noqa: BLE001
            pb_ok, pdetail = False, "unreadable: {}".format(e)
        rep.check("{}::progression_proof_valid".format(tag), pb_ok, pdetail,
                  code=C.PROGRESSION_SAVE_LOAD_FAILED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.9 reward runtime-evidence gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    live = _live_completions()

    # Honest RED when no runtime evidence exists yet: never green with zero live runs.
    rep.check("reward_live_runtime_evidence_present", len(live) > 0,
              "no live reward_granted_runtime completion reports under {} — "
              "run the real reward matrix (run_reward_forge_alpha.py --run) first "
              "[{}]".format(RX.REWARD_COMPLETION_REPORTS_REL, C.RUNTIME_LIVE_RUN_PENDING),
              code=C.RUNTIME_LIVE_RUN_PENDING)

    for f, r in live:
        _check_one(rep, f, r)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-reward-bridge", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(live),
                            report_type="wf.reward.reward_completion_report.v1",
                            extra={"live_completions": len(live)}))
    rep.write(REPORT_DIR, "validate_reward_bridge_report.json")
    rep.print_summary("validate-reward-bridge")
    print("[reward-bridge] {} live reward_granted_runtime completion(s) gated".format(len(live)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
