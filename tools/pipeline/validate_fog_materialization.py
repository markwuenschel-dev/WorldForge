#!/usr/bin/env python3
"""validate_fog_materialization.py — WorldForge v1.3.5 fog materialization validator (Agent 3).

The ExponentialHeightFog lane of the environment rig (brief §5). Fog must be a
resolved component with real numeric density and a height_falloff, not a bare
profile name.

Per rig: ExponentialHeightFog present + enabled + source_profile + params where
density is a number >= 0 and height_falloff is present; if params.volumetric is
present it must be a bool.

Usage:
    python tools/pipeline/validate_fog_materialization.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_fog_materialization/validate_fog_materialization_report.json
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

CODE = FailureCode.FOG_MATERIALIZATION_FAILURE


def check_rig(rep, sid, rig):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=CODE)

    fog = components_by_type(rig).get(VC.COMP_HEIGHT_FOG)
    if not c("fog_component_present", bool(fog), "no ExponentialHeightFog component"):
        return
    c("fog_enabled", fog.get("enabled") is True, "enabled={}".format(fog.get("enabled")))
    c("fog_source_profile", bool(fog.get("source_profile")),
      "source_profile={}".format(fog.get("source_profile")))

    params = fog.get("params") or {}
    density = params.get("density")
    c("fog_density_number", is_number(density), "density={}".format(density))
    c("fog_density_nonnegative", is_number(density) and density >= 0,
      "density={}".format(density))
    c("fog_height_falloff_present", params.get("height_falloff") is not None,
      "height_falloff={}".format(params.get("height_falloff")))

    if "volumetric" in params:
        c("fog_volumetric_bool", isinstance(params.get("volumetric"), bool),
          "volumetric={}".format(params.get("volumetric")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 fog materialization.")
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
    rep.set_meta(build_meta(command="validate-fog-materialization", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_fog_materialization",
              "validate_fog_materialization_report.json")
    rep.print_summary("validate-fog-materialization")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
