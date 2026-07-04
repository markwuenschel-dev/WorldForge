#!/usr/bin/env python3
"""validate_lighting_exposure.py — WorldForge v1.3.5 lighting/exposure validator (Agent 3).

The DirectionalLight + SkyLight + exposure lane of the environment rig (brief §5
+ readability). A rig that would black-frame or blow out the objective is not
playable; exposure must stay in the readable EV window.

Per rig: DirectionalLight_Sun present + enabled with params.sun_angle_deg (a
number in 0..180) and a bound intensity; SkyLight present + enabled; exposure_ev
within [VC.EXPOSURE_EV_MIN, VC.EXPOSURE_EV_MAX].

Usage:
    python tools/pipeline/validate_lighting_exposure.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_lighting_exposure/validate_lighting_exposure_report.json
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

CODE = FailureCode.LIGHTING_EXPOSURE_FAILURE


def check_rig(rep, sid, rig):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=CODE)

    comps = components_by_type(rig)

    sun = comps.get(VC.COMP_DIRECTIONAL_SUN)
    if c("sun_component_present", bool(sun), "no DirectionalLight_Sun component"):
        c("sun_enabled", sun.get("enabled") is True, "enabled={}".format(sun.get("enabled")))
        params = sun.get("params") or {}
        angle = params.get("sun_angle_deg")
        c("sun_angle_valid", is_number(angle) and 0.0 <= angle <= 180.0,
          "sun_angle_deg={}".format(angle))
        intensity = params.get("intensity_lux")
        c("sun_intensity_bound", is_number(intensity) and intensity > 0,
          "intensity_lux={}".format(intensity))

    skylight = comps.get(VC.COMP_SKY_LIGHT)
    if c("skylight_present", bool(skylight), "no SkyLight component"):
        c("skylight_enabled", skylight.get("enabled") is True,
          "enabled={}".format(skylight.get("enabled")))

    exposure = rig.get("exposure_ev")
    c("exposure_in_readable_range",
      is_number(exposure) and VC.EXPOSURE_EV_MIN <= exposure <= VC.EXPOSURE_EV_MAX,
      "exposure_ev={} not in [{}, {}] (would black-frame/blow out objective)".format(
          exposure, VC.EXPOSURE_EV_MIN, VC.EXPOSURE_EV_MAX))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 lighting/exposure.")
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
    rep.set_meta(build_meta(command="validate-lighting-exposure", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_lighting_exposure",
              "validate_lighting_exposure_report.json")
    rep.print_summary("validate-lighting-exposure")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
