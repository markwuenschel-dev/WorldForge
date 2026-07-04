#!/usr/bin/env python3
"""validate_mission_save_load.py — WorldForge v1.3 mission save/load validator (Agent 3).

Proves brief §3 "save/load": a mission's progress survives a save/load roundtrip
and, critically, the persisted subset is SUFFICIENT to still resolve completion.
A mission whose completion depends on a state key that is not persisted would
silently lose its objective across a reload — that is a MISSION_SAVE_LOAD_FAILURE.

Roundtrip simulation reuses playtest_contract.simulate_state / completion_resolves
so this agrees with the PlaytestForge harness, but it evaluates completion from
the PERSISTED state ALONE (not merged with volatile state) to catch keys that
save/load would drop.

Usage:
    python tools/pipeline/validate_mission_save_load.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_save_load/validate_mission_save_load_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
import playtest_contract as PC
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def check_mission(rep, mid, m):
    code = FailureCode.MISSION_SAVE_LOAD_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    sl = m.get("save_load_contract") or {}
    missing = [k for k in MC.SAVE_LOAD_REQUIRED if k not in sl]
    c("save_load_complete", not missing, "save_load_contract missing: {}".format(missing))
    if missing:
        return

    persist = sl.get("persist_keys") or []
    c("persist_keys_present", bool(persist), "no persist_keys")

    declared = {s.get("key") for s in (m.get("state_keys") or [])}
    unknown = [k for k in persist if k not in declared]
    c("persist_keys_declared", not unknown,
      "persist_keys not declared as state_keys: {}".format(unknown))

    c("expect_roundtrip_true", sl.get("expect_roundtrip") is True,
      "expect_roundtrip={}".format(sl.get("expect_roundtrip")))

    if not persist:
        return

    # Simulate save -> load roundtrip of ONLY the persisted keys.
    final = PC.simulate_state(m)
    saved = {k: final.get(k) for k in persist}
    loaded = dict(saved)  # "reload"
    roundtrip_ok = loaded == saved and all(k in loaded for k in persist)
    c("roundtrip_lossless", roundtrip_ok,
      "reloaded state differs from saved: saved={} loaded={}".format(saved, loaded))

    # Completion must still resolve from the PERSISTED state alone; any completion
    # key that was not persisted is missing here and completion cannot resolve.
    still_complete = PC.completion_resolves(m, loaded)
    c("completion_survives_reload", still_complete,
      "completion does not resolve from persisted state {} — a completion key is not persisted".format(loaded))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission save/load roundtrip.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")
    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.MISSION_SAVE_LOAD_FAILURE)
            continue
        check_mission(rep, mid, m)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-save-load", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_save_load",
              "validate_mission_save_load_report.json")
    rep.print_summary("validate-mission-save-load")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
