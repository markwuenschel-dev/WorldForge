#!/usr/bin/env python3
"""validate_encounter_save_load.py — WorldForge v1.4 encounter save/load validator (Lane C).

Proves brief §8 "encounter state survives save/load": every encounter's
save_load_contract persists ALL encounter state, keeps every persistence
guarantee of its linked mission (an encounter must never drop mission
persistence), declares no phantom persist keys, and survives a literal
JSON serialize->parse roundtrip after which completion still resolves.
A playtest that would falsely report completion (or lose resolution state)
after a load blocks with ENCOUNTER_SAVE_LOAD_FAILURE.

Simulation reuses playtest_contract.simulate_state / completion_resolves so
the roundtrip verdict agrees byte-for-byte with the playtest harness.

Usage:
    python tools/pipeline/validate_encounter_save_load.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_save_load/validate_encounter_save_load_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
import playtest_contract as PC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def check_save_load(rep, eid, enc, mission):
    """Importable core: add save/load-contract checks for one encounter to ``rep``."""
    code = FailureCode.ENCOUNTER_SAVE_LOAD_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(eid, name), ok, detail, code=code)

    slc = enc.get("save_load_contract") or {}
    shape_ok = isinstance(slc, dict) and all(k in slc for k in EC.SAVE_LOAD_REQUIRED)
    c("contract_shape", shape_ok,
      "save_load_contract missing required keys {}".format(EC.SAVE_LOAD_REQUIRED))
    c("expect_roundtrip_true", slc.get("expect_roundtrip") is True,
      "expect_roundtrip is {!r} — encounters must guarantee a roundtrip".format(
          slc.get("expect_roundtrip")))

    persist = slc.get("persist_keys") or []
    c("persist_keys_present", bool(persist),
      "empty persist_keys — nothing survives a save")

    enc_keys = [s.get("key") for s in enc.get("state_keys") or []
                if isinstance(s, dict) and s.get("key")]
    mission_keys = [s.get("key") for s in (mission or {}).get("state_keys") or []
                    if isinstance(s, dict) and s.get("key")]

    # EVERY encounter state key must be persisted (encounter state not saved = fail).
    unsaved = [k for k in enc_keys if k not in persist]
    c("persists_all_encounter_state", not unsaved,
      "encounter state keys missing from persist_keys: {}".format(unsaved))

    # The encounter must not drop the linked mission's persistence guarantees.
    mission_persist = ((mission or {}).get("save_load_contract") or {}).get(
        "persist_keys") or []
    dropped = [k for k in mission_persist if k not in persist]
    c("persists_mission_state", not dropped,
      "mission persist keys dropped by encounter contract: {}".format(dropped))

    # No phantom persistence: every persist key must be a declared state key
    # of the encounter or of the linked mission.
    declared = set(enc_keys) | set(mission_keys)
    undeclared = [k for k in persist if k not in declared]
    c("no_undeclared_persist_keys", not undeclared,
      "persist keys never declared as state: {}".format(undeclared))

    # --- literal save -> load roundtrip over the resolved state --------------
    final = {}
    final.update(PC.simulate_state(mission or {}))
    final.update(PC.simulate_state(enc))
    saved = {k: final.get(k) for k in persist}
    try:
        loaded = json.loads(json.dumps(saved, sort_keys=True))
    except (TypeError, ValueError) as exc:
        c("roundtrip_serializable", False,
          "persisted state not JSON-serializable: {}".format(exc))
        return
    c("roundtrip_serializable", True)
    c("roundtrip_values_survive",
      loaded == saved and all(k in loaded for k in persist),
      "loaded state {} != saved state {}".format(loaded, saved))

    # Completion must still resolve from the LOADED state alone; otherwise the
    # playtest would report a completion the save file cannot reproduce.
    c("completion_resolves_after_load", PC.completion_resolves(enc, loaded),
      "completion does not resolve from loaded state {} — "
      "resolution lost across save/load".format(loaded))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate v1.4 encounter save/load contracts (brief §8).")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_SAVE_LOAD_FAILURE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        rep.check("{}::mission_loads".format(eid), mission is not None,
                  merr or "", code=FailureCode.ENCOUNTER_SAVE_LOAD_FAILURE)
        check_save_load(rep, eid, enc, mission)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-save-load", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_save_load",
              "validate_encounter_save_load_report.json")
    rep.print_summary("validate-encounter-save-load")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
