#!/usr/bin/env python3
"""validate_environment_rig.py — WorldForge v1.3.5 environment rig validator (Agent 3).

The keystone environment-rig gate (brief §5): every mission map must carry a
FULLY-RESOLVED UE-native environment rig, not a bare profile name. There is no
live UE editor on this runner — the rig is materialized as a concrete
actor/component SPEC plus a materialization_report that a UE driver will consume.
This validator fails the JSON-only case and passes the fully-resolved case.

Per rig: VC.rig_is_fully_resolved(rig) is True (all required components present +
enabled + bound params + source_profile); materialization_report present with
spec_resolved True and a non-empty actor_set; ownership_class generated_owned.

Usage:
    python tools/pipeline/validate_environment_rig.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_environment_rig/validate_environment_rig_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_rig_common import iter_rigs
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.ENVIRONMENT_RIG_FAILURE


def check_rig(rep, sid, rig):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=CODE)

    ok, detail = VC.rig_is_fully_resolved(rig)
    c("rig_fully_resolved", ok, detail)

    mr = rig.get("materialization_report") or {}
    c("materialization_report_present", bool(mr), "no materialization_report")
    c("spec_resolved", mr.get("spec_resolved") is True,
      "spec_resolved={}".format(mr.get("spec_resolved")))
    actor_set = mr.get("actor_set") or []
    c("actor_set_nonempty", bool(actor_set),
      "actor_set has {} actors".format(len(actor_set)))

    c("ownership_generated", rig.get("ownership_class") == VC.OWNERSHIP_GENERATED,
      "ownership_class={}".format(rig.get("ownership_class")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 environment rigs.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = 0
    for sid, rig, err in iter_rigs(REPO_ROOT):
        if rig is None:
            rep.check("{}::loads".format(sid), False, err, code=CODE)
            continue
        check_rig(rep, sid, rig)
        n += 1
    if n == 0:
        rep.error("no environment rigs — run 'make materialize-environment-rigs' first")

    rep.finalize()
    rep.set_meta(build_meta(command="validate-environment-rig", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_environment_rig",
              "validate_environment_rig_report.json")
    rep.print_summary("validate-environment-rig")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
