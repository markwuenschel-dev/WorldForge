#!/usr/bin/env python3
"""validate_combat_profiles.py — WorldForge v1.8 CombatForge Alpha profile gate.

Validates the generated CombatProfile set as a whole:

  * FAIL-CLOSED if zero combat profiles exist (a gate that passes over an empty
    directory is a fake-green vector — no profiles means the generator never ran);
  * every profile passes its strict ``validate_combat_profile`` contract;
  * every profile references a v1.7 ``behavior_profile_id`` that actually exists
    under the behavior-profile root (no dangling combat->behavior link);
  * combat_profile_ids are unique.

This gate is fully green NOW with no UE runtime evidence — it validates authored
combat profiles, not runtime damage. Exits nonzero on any invalid profile or if
the set is empty.

Acceptance: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_combat_profiles.py --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

BEHAVIOR_PROFILE_GENERATED_REL = "procedural/generated/npc/behavior_profiles"


def _load_all(rel):
    d = REPO_ROOT / rel
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                out.append((p.name, json.loads(p.read_text(encoding="utf-8"))))
            except Exception:  # noqa: BLE001
                out.append((p.name, None))
    return out


def _load_ids(rel):
    d = REPO_ROOT / rel
    return {p.stem for p in d.glob("*.json")} if d.is_dir() else set()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    profiles = _load_all(CC.COMBAT_PROFILE_GENERATED_REL)
    behavior_ids = _load_ids(BEHAVIOR_PROFILE_GENERATED_REL)

    # FAIL-CLOSED: an empty profile set is not a vacuous pass.
    rep.check("combat_profiles::exist", len(profiles) > 0,
              "no combat profiles under {} (run generate-combat-profiles)".format(
                  CC.COMBAT_PROFILE_GENERATED_REL),
              code=FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE)

    invalid = dangling = 0
    seen_ids = {}
    for fname, p in profiles:
        if not isinstance(p, dict):
            invalid += 1
            rep.check("cp::{}::parse".format(fname), False,
                      "combat profile did not parse as an object",
                      code=FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE)
            continue
        cpid = p.get("combat_profile_id", fname)
        fails = [c for c in CC.validate_combat_profile(p, strict=True) if not c[1]]
        if fails:
            invalid += 1
            rep.check("cp::{}::valid".format(cpid), False,
                      "invalid combat profile: {}".format([c[0] for c in fails][:5]),
                      code=FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE)
        # combat -> behavior link must resolve (no dangling reference).
        bpid = p.get("behavior_profile_id")
        if bpid not in behavior_ids:
            dangling += 1
            rep.check("cp::{}::behavior_ref".format(cpid), False,
                      "behavior_profile_id {!r} not found under behavior-profile root".format(bpid),
                      code=FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE)
        seen_ids[cpid] = seen_ids.get(cpid, 0) + 1

    dupes = {k: v for k, v in seen_ids.items() if v > 1}
    rep.check("combat_profiles::unique_ids", not dupes,
              "duplicate combat_profile_id(s): {}".format(dupes),
              code=FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE)
    rep.check("combat_profiles::all_valid", invalid == 0,
              "{} invalid combat profiles".format(invalid),
              code=FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE)
    rep.check("combat_profiles::no_dangling_behavior_refs", dangling == 0,
              "{} combat profiles reference a missing behavior profile".format(dangling),
              code=FailureCode.COMBAT_PROFILE_SCHEMA_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-combat-profiles", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(profiles),
                            report_type=CC.RT_COMBAT_PROFILE,
                            records_total=len(profiles), records_failed=invalid + dangling))
    rep.write(REPO_ROOT / "procedural/reports/combat/profiles",
              "validate_combat_profiles_report.json")
    rep.print_summary("validate-combat-profiles")
    print("[validate-combat-profiles] {} combat profiles, {} behavior profiles".format(
        len(profiles), len(behavior_ids)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
