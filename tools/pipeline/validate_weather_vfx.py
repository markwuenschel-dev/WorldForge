#!/usr/bin/env python3
"""validate_weather_vfx.py — WorldForge v1.3.5 weather VFX validator (Agent 3).

The WeatherVFX_Niagara lane of the environment rig (brief §5). Weather is
optional: a clear-weather rig legitimately DISABLES the emitter (emitter_count 0
/ absent is valid), but the component entry must still be DECLARED. When enabled,
the emitter must be bound with a positive emitter_count — not a bare name.

Per rig: WeatherVFX_Niagara component present; if enabled -> params.emitter bound
and emitter_count > 0; if disabled -> emitter_count 0/absent is valid.

Usage:
    python tools/pipeline/validate_weather_vfx.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_weather_vfx/validate_weather_vfx_report.json
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

CODE = FailureCode.WEATHER_VFX_FAILURE


def check_rig(rep, sid, rig):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=CODE)

    weather = components_by_type(rig).get(VC.COMP_WEATHER_VFX)
    if not c("weather_component_declared", bool(weather),
             "WeatherVFX_Niagara entry must be declared (even when disabled)"):
        return

    params = weather.get("params") or {}
    if weather.get("enabled"):
        c("weather_emitter_bound", bool(params.get("emitter")),
          "enabled weather emitter={}".format(params.get("emitter")))
        emitter_count = params.get("emitter_count")
        c("weather_emitter_count_positive", is_number(emitter_count) and emitter_count > 0,
          "enabled weather emitter_count={}".format(emitter_count))
    else:
        emitter_count = params.get("emitter_count")
        c("weather_clear_valid", emitter_count in (None, 0) or emitter_count == 0,
          "disabled weather emitter_count={} (0/absent is valid)".format(emitter_count))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 weather VFX.")
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
    rep.set_meta(build_meta(command="validate-weather-vfx", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_weather_vfx",
              "validate_weather_vfx_report.json")
    rep.print_summary("validate-weather-vfx")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
