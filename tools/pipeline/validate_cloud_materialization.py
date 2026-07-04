#!/usr/bin/env python3
"""validate_cloud_materialization.py — WorldForge v1.3.5 cloud materialization validator (Agent 3).

The VolumetricCloud lane of the environment rig (brief §5). Clouds are optional:
a clear-sky rig legitimately DISABLES the component, but the component entry must
still be DECLARED. When enabled, it must be fully resolved (positive coverage +
bound cloud_model), not a bare name.

Per rig: VolumetricCloud component present; if enabled -> params.coverage > 0 and
cloud_model bound; if disabled -> valid (clear sky) provided the entry exists.

Usage:
    python tools/pipeline/validate_cloud_materialization.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_cloud_materialization/validate_cloud_materialization_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_rig_common import iter_rigs, components_by_type, is_number
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.CLOUD_MATERIALIZATION_FAILURE


def check_rig(rep, sid, rig):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=CODE)

    cloud = components_by_type(rig).get(VC.COMP_VOLUMETRIC_CLOUD)
    if not c("cloud_component_declared", bool(cloud),
             "VolumetricCloud entry must be declared (even when disabled)"):
        return

    if cloud.get("enabled"):
        params = cloud.get("params") or {}
        coverage = params.get("coverage")
        c("cloud_coverage_positive", is_number(coverage) and coverage > 0,
          "enabled cloud coverage={}".format(coverage))
        c("cloud_model_bound", bool(params.get("cloud_model")),
          "cloud_model={}".format(params.get("cloud_model")))
    else:
        c("cloud_disabled_clear_sky_valid", True,
          "clouds disabled (clear sky) — declared entry present")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 cloud materialization.")
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
    rep.set_meta(build_meta(command="validate-cloud-materialization", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_cloud_materialization",
              "validate_cloud_materialization_report.json")
    rep.print_summary("validate-cloud-materialization")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
