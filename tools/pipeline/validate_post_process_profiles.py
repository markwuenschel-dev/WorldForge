#!/usr/bin/env python3
"""validate_post_process_profiles.py — WorldForge v1.3.5 post-process validator (Agent 3).

The PostProcessVolume lane of the environment rig (brief §5). The tone/grade of
every map must be a resolved post-process component with a bound exposure and
color-grading, not a bare profile name.

Per rig: PostProcessVolume present + enabled + source_profile + params where
exposure_ev is present and color_grading is bound.

Usage:
    python tools/pipeline/validate_post_process_profiles.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_post_process_profiles/validate_post_process_profiles_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_rig_common import iter_rigs, components_by_type
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.POST_PROCESS_PROFILE_FAILURE


def check_rig(rep, sid, rig):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=CODE)

    pp = components_by_type(rig).get(VC.COMP_POST_PROCESS)
    if not c("post_process_present", bool(pp), "no PostProcessVolume component"):
        return
    c("post_process_enabled", pp.get("enabled") is True, "enabled={}".format(pp.get("enabled")))
    c("post_process_source_profile", bool(pp.get("source_profile")),
      "source_profile={}".format(pp.get("source_profile")))

    params = pp.get("params") or {}
    c("post_process_exposure_present", params.get("exposure_ev") is not None,
      "exposure_ev={}".format(params.get("exposure_ev")))
    c("post_process_color_grading_bound", bool(params.get("color_grading")),
      "color_grading={}".format(params.get("color_grading")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 post-process profiles.")
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
    rep.set_meta(build_meta(command="validate-post-process-profiles", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_post_process_profiles",
              "validate_post_process_profiles_report.json")
    rep.print_summary("validate-post-process-profiles")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
