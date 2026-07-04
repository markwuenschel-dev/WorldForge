#!/usr/bin/env python3
"""validate_sky_materialization.py — WorldForge v1.3.5 sky materialization validator (Agent 3).

The SkyAtmosphere lane of the environment rig (brief §5). A sky that exists only
as a profile *name* — with no resolved luminance or colors — is NOT materialized
and FAILS. A fully-bound SkyAtmosphere component PASSES.

Per rig: the SkyAtmosphere component present + enabled + source_profile set +
params carrying a bound sky_luminance_cd_m2 (a positive number) and zenith/horizon
colors present.

Usage:
    python tools/pipeline/validate_sky_materialization.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_sky_materialization/validate_sky_materialization_report.json
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

CODE = FailureCode.SKY_MATERIALIZATION_FAILURE


def check_rig(rep, sid, rig):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=CODE)

    sky = components_by_type(rig).get(VC.COMP_SKY_ATMOSPHERE)
    if not c("sky_component_present", bool(sky), "no SkyAtmosphere component"):
        return
    c("sky_enabled", sky.get("enabled") is True, "enabled={}".format(sky.get("enabled")))
    c("sky_source_profile", bool(sky.get("source_profile")),
      "source_profile={}".format(sky.get("source_profile")))

    params = sky.get("params") or {}
    lum = params.get("sky_luminance_cd_m2")
    c("sky_luminance_bound", is_number(lum) and lum > 0,
      "sky_luminance_cd_m2={} (a name-only sky has no luminance)".format(lum))
    c("sky_colors_present",
      params.get("zenith_color") is not None and params.get("horizon_color") is not None,
      "zenith={} horizon={}".format(params.get("zenith_color"), params.get("horizon_color")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 sky materialization.")
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
    rep.set_meta(build_meta(command="validate-sky-materialization", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_sky_materialization",
              "validate_sky_materialization_report.json")
    rep.print_summary("validate-sky-materialization")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
