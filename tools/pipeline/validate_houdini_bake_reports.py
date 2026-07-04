#!/usr/bin/env python3
"""validate_houdini_bake_reports.py — WorldForge v1.2 Houdini bake/import validator.

Validates the declared BAKE and IMPORT reports of every ``houdini_generated``
mesh asset (addendum §5). Same shape as the cook-report gate, for the two later
stages: both the bake report and the import report must be present, well-formed,
status-ok, and their hda_id must match the intake block. A missing/failed bake is
a HOUDINI_BAKE_FAILURE; a missing/failed import is a HOUDINI_IMPORT_FAILURE.

In HOUDINI=metadata_only mode this validates the declared prior-cook reports — it
is not fake green: the reports must exist and be status-ok.

Usage:
    PYTHONUTF8=1 STRICT=1 HOUDINI=metadata_only \
        python tools/pipeline/validate_houdini_bake_reports.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_houdini_bake_reports/validate_houdini_bake_reports_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import houdini_contract as HC
import mesh_contract as MC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _load_descriptor(asset_id):
    path = MC.mesh_descriptor_path(asset_id, REPO_ROOT)
    if not path.is_file():
        return None, "descriptor not found: {}".format(path)
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover
        return None, "descriptor unparseable: {}".format(exc)


def _load_report(rel_path):
    if not rel_path:
        return None, "report path missing"
    path = (REPO_ROOT / rel_path).resolve()
    if not path.is_file():
        return None, "report file not found: {}".format(rel_path)
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover
        return None, "report unparseable: {}".format(exc)


def _check_stage(rep, asset_id, intake, stage, code):
    """Validate one report stage (bake or import) for an asset."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code)

    rel = intake.get("{}_report".format(stage))
    report, err = _load_report(rel)

    c("{}_report_exists".format(stage), report is not None, err or "")
    if report is None:
        return

    missing = [k for k in HC.HOUDINI_REPORT_REQUIRED if k not in report or
               report.get(k) in (None, "")]
    c("{}_report_complete".format(stage), not missing,
      "{} report missing keys: {}".format(stage, missing))
    c("{}_report_ok".format(stage), HC.report_ok(report) and not HC.report_failed(report),
      "{} report status not ok: {}".format(stage, report.get("status")))
    c("{}_report_hda_matches".format(stage), report.get("hda_id") == intake.get("hda_id"),
      "{} report hda_id={} != intake hda_id={}".format(
          stage, report.get("hda_id"), intake.get("hda_id")))


def check_asset(rep, asset_id, entry, descriptor):
    intake = HC.houdini_intake_block(descriptor)
    _check_stage(rep, asset_id, intake, "bake", FailureCode.HOUDINI_BAKE_FAILURE)
    _check_stage(rep, asset_id, intake, "import", FailureCode.HOUDINI_IMPORT_FAILURE)


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    n = 0
    for aid, entry in HC.iter_houdini_assets(catalog):
        descriptor, err = _load_descriptor(aid)
        if descriptor is None:
            rep.check("{}::descriptor_loads".format(aid), False, err or "no descriptor",
                      code=FailureCode.HOUDINI_BAKE_FAILURE)
            continue
        check_asset(rep, aid, entry, descriptor)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate WorldForge v1.2 Houdini bake/import reports.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-houdini-bake-reports", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_houdini_bake_reports"
    rep.write(report_dir, "validate_houdini_bake_reports_report.json")
    rep.print_summary("validate-houdini-bake-reports")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
