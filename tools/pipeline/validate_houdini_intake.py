#!/usr/bin/env python3
"""validate_houdini_intake.py — WorldForge v1.2 addendum Houdini-intake validator.

Validates the ``houdini_intake`` block of every ``houdini_generated`` mesh asset
(addendum §5 strict rules). Houdini is a GENERATED backend: the baked/imported
StaticMesh output is ``generated_owned``, but the SOURCE HDA is ``project_owned``
or ``third_party_owned`` — NEVER generated-owned. Collapsing the two ownership
classes (treating the HDA source as generated output) is the critical bug this
gate catches: hda_ownership_class must be in HC.HDA_OWNERSHIP_CLASSES and must
NOT be "generated_owned", while the OUTPUT descriptor stays generated_owned.

When Houdini is not live (HOUDINI=metadata_only) this validates the declared
intake metadata from a prior cook — the reports must still be present, the final
path / ownership / registry / provenance guarantees stay hard.

Usage:
    PYTHONUTF8=1 STRICT=1 HOUDINI=metadata_only \
        python tools/pipeline/validate_houdini_intake.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_houdini_intake/validate_houdini_intake_report.json
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
    """Load the materialized descriptor for a mesh asset. Returns (data, error)."""
    path = MC.mesh_descriptor_path(asset_id, REPO_ROOT)
    if not path.is_file():
        return None, "descriptor not found: {}".format(path)
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover
        return None, "descriptor unparseable: {}".format(exc)


def check_asset(rep, asset_id, entry, descriptor):
    def c(name, ok, detail="", code=FailureCode.HOUDINI_SOURCE_FAILURE):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code)

    intake = HC.houdini_intake_block(descriptor)

    # -- intake block present + complete (addendum §5) ----------------------
    c("houdini_intake_present", bool(intake),
      "houdini_intake block absent", code=FailureCode.HOUDINI_SOURCE_FAILURE)
    missing = [k for k in HC.HOUDINI_INTAKE_REQUIRED if k not in intake or
               intake.get(k) in (None, "")]
    c("houdini_intake_complete", not missing,
      "missing houdini_intake keys: {}".format(missing),
      code=FailureCode.HOUDINI_SOURCE_FAILURE)

    # -- HDA source identity -------------------------------------------------
    c("hda_id_present", bool(intake.get("hda_id")),
      "hda_id missing", code=FailureCode.HOUDINI_SOURCE_FAILURE)
    c("hda_path_present", bool(intake.get("hda_path")),
      "hda_path missing", code=FailureCode.HOUDINI_SOURCE_FAILURE)

    # -- HDA ownership: project/third_party ONLY, never generated_owned ------
    hda_oc = intake.get("hda_ownership_class")
    c("hda_ownership_class_valid", hda_oc in HC.HDA_OWNERSHIP_CLASSES,
      "hda_ownership_class={} not in {}".format(hda_oc, HC.HDA_OWNERSHIP_CLASSES),
      code=FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE)
    c("hda_not_generated_owned", hda_oc != MC.OWNERSHIP_GENERATED,
      "HDA source must NOT be generated_owned (hda_ownership_class={})".format(hda_oc),
      code=FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE)

    # -- parameter / source hashes ------------------------------------------
    c("parameter_hash_present", bool(intake.get("parameter_hash")),
      "parameter_hash missing", code=FailureCode.HOUDINI_PARAMETER_FAILURE)
    c("source_hash_present", bool(intake.get("source_hash")),
      "source_hash missing", code=FailureCode.HOUDINI_SOURCE_FAILURE)

    # -- final asset path: allowed owned root, never Temp/Bake --------------
    final_path = descriptor.get("final_asset_path", "")
    c("final_path_present", bool(final_path),
      "final_asset_path missing", code=FailureCode.HOUDINI_IMPORT_FAILURE)
    c("final_path_not_temp_bake", not MC.is_forbidden_final_path(final_path),
      "final_asset_path is a Temp/Bake/quarantine leak: {}".format(final_path),
      code=FailureCode.HOUDINI_IMPORT_FAILURE)
    c("final_path_allowed", MC.is_allowed_final_path(final_path),
      "final_asset_path not under an owned generated root: {}".format(final_path),
      code=FailureCode.HOUDINI_IMPORT_FAILURE)

    # -- baked OUTPUT is generated_owned while HDA is NOT (they DIFFER) ------
    out_generated = (descriptor.get("generated_owned") is True and
                     MC.resolve_ownership_class(descriptor) == MC.OWNERSHIP_GENERATED)
    c("output_generated_owned", out_generated,
      "baked output must be generated_owned (generated_owned={}, class={})".format(
          descriptor.get("generated_owned"), MC.resolve_ownership_class(descriptor)),
      code=FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE)
    c("hda_vs_output_ownership_differ",
      out_generated and hda_oc in HC.HDA_OWNERSHIP_CLASSES and hda_oc != MC.OWNERSHIP_GENERATED,
      "HDA source ({}) and generated output ownership must differ — HDA is not generated".format(hda_oc),
      code=FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE)

    # -- registry + provenance ----------------------------------------------
    c("registry_id_present", bool(entry.get("registry_id")),
      "catalog entry has no registry_id",
      code=FailureCode.HOUDINI_OUTPUT_REGISTRY_FAILURE)
    c("provenance_present",
      bool(descriptor.get("provenance")) and bool(descriptor.get("provenance_id")),
      "descriptor missing provenance/provenance_id",
      code=FailureCode.HOUDINI_OUTPUT_PROVENANCE_FAILURE)


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    n = 0
    for aid, entry in HC.iter_houdini_assets(catalog):
        descriptor, err = _load_descriptor(aid)
        if descriptor is None:
            rep.check("{}::descriptor_loads".format(aid), False, err or "no descriptor",
                      code=FailureCode.HOUDINI_SOURCE_FAILURE)
            continue
        check_asset(rep, aid, entry, descriptor)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate WorldForge v1.2 Houdini intake.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-houdini-intake", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_houdini_intake"
    rep.write(report_dir, "validate_houdini_intake_report.json")
    rep.print_summary("validate-houdini-intake")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
