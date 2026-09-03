#!/usr/bin/env python3
"""validate_houdini_cook_evidence.py -- does the declared cook report constitute
EVIDENCE that Houdini ran?

WHY THIS IS A SEPARATE GATE
---------------------------
``validate_houdini_cook_reports.py`` and ``validate_houdini_bake_reports.py``
already ask a real question: is the declared report present, well-formed, and
status-ok? That check has genuine value -- ``test_negative_sources.py`` and
``source_lifecycle_torture.py`` both prove it goes RED on a corrupted or missing
report and GREEN again on restore. Nothing here weakens it.

What those gates do NOT ask is who wrote the file they are grading. The answer
is: this pipeline did. ``create_mesh_assets._write_houdini_reports`` emits
exactly the keys ``houdini_contract.HOUDINI_REPORT_REQUIRED`` demands, with
``status`` hardcoded to ``"ok"``, and the validators then grade those files. The
gate and the subject share an author, so the lane reports 222 green checks over
six assets while no Houdini process has ever run in this repository.

Conflating the two questions is what hid the gap. Separating them is the fix:
- WF233 / WF234 / WF235 keep meaning "the declared report is missing, malformed
  or failed" -- a descriptor-integrity claim, still enforced, still useful.
- WF239 means "the report is perfectly well-formed and proves nothing."

WHAT WOULD CLEAR THIS GATE
--------------------------
Evidence a Houdini process leaves behind and a metadata stamp cannot fake. The
vocabulary is not invented here -- it is imported verbatim from
``validate_external_tool_providers.COOK_EVIDENCE_REQUIRED``, the gate that
already polices this exact question for wfcore provider declarations. One
vocabulary, two lanes; a second parallel definition would let the two lanes
disagree about what a cook is.

THREE STATES, KEPT SEPARATE
---------------------------
"could not check" is never "checked and failed" (the observation-intake rule):
- ``resolved``      cook_evidence present and complete, producer is external
- ``self_authored`` producer names a WorldForge module -- refused BY NAME
- ``undeclared``    no producer and no cook_evidence -- authorship unknown,
                    so the report cannot be evidence either way
Only ``resolved`` passes. ``self_authored`` and ``undeclared`` both fail, with
different check names, because the remedies differ: one needs a real cook, the
other needs the writer to say who it is first.

HONEST LIMIT
------------
A caller that writes a false ``cook_evidence`` block has it read as resolved.
No reader here can detect that. This gate closes the accidental lie, not the
deliberate one.

Usage:
    PYTHONUTF8=1 STRICT=1 HOUDINI=metadata_only \
        python tools/pipeline/validate_houdini_cook_evidence.py --pack biome_expansion_world

Writes: procedural/reports/mesh/validate_houdini_cook_evidence/
        validate_houdini_cook_evidence_report.json
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

# ONE vocabulary for "what a real cook records", shared with the wfcore lane.
# Imported, never re-declared: two definitions would let the lanes disagree.
from validate_external_tool_providers import COOK_EVIDENCE_REQUIRED

# Producer ids that identify the WorldForge pipeline itself. A report bearing
# one of these is a declaration this repo wrote about its own intent -- never a
# measurement of an external tool. Prefix match, so new modules are covered
# without editing this list.
SELF_AUTHORED_PREFIXES = ("worldforge.",)

# The three stages whose reports claim a Houdini process did something.
STAGES = ("cook", "bake", "import")

STAGE_CODE = {
    "cook": FailureCode.HOUDINI_COOK_EVIDENCE_SELF_AUTHORED,
    "bake": FailureCode.HOUDINI_COOK_EVIDENCE_SELF_AUTHORED,
    "import": FailureCode.HOUDINI_COOK_EVIDENCE_SELF_AUTHORED,
}

REPORT_REL = Path("procedural") / "reports" / "mesh" / "validate_houdini_cook_evidence"


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


def classify(report):
    """Return (state, detail). States: resolved | self_authored | undeclared.

    Deliberately does NOT look at ``status``. A report can be status-ok and
    still be something this pipeline wrote about itself; that is the entire
    distinction this module exists to draw.
    """
    if not isinstance(report, dict):
        return "undeclared", "report is not an object"

    producer = report.get("producer")
    if isinstance(producer, str) and producer.startswith(SELF_AUTHORED_PREFIXES):
        return "self_authored", (
            "report names its own author as {!r}, a WorldForge pipeline module. "
            "It is a declaration this repository wrote about its own intended "
            "intake shape, not a measurement of anything Houdini did".format(
                producer))

    cook = report.get("cook_evidence")
    if not isinstance(cook, dict) or not cook:
        if producer in (None, ""):
            return "undeclared", (
                "report carries neither a 'producer' nor a 'cook_evidence' "
                "block, so nothing identifies who wrote it or what ran. "
                "Authorship unknown is not the same as authorship external")
        return "undeclared", (
            "report declares producer {!r} but carries no 'cook_evidence' "
            "block".format(producer))

    missing = [f for f in COOK_EVIDENCE_REQUIRED
               if cook.get(f) in (None, "", [], {})]
    if missing:
        return "undeclared", (
            "cook_evidence present but missing {}; that is metadata about a "
            "cook rather than evidence one happened".format(missing))

    return "resolved", "cook evidence complete, producer {!r}".format(producer)


def check_asset(rep, asset_id, descriptor):
    intake = HC.houdini_intake_block(descriptor)

    for stage in STAGES:
        key = "{}_report".format(stage)
        rel = intake.get(key)
        report, err = _load_report(rel)

        if report is None:
            # Absence is WF233/WF234/WF235's job, not this gate's. Record it as
            # a skip so a reader sees the question was ASKED and could not be
            # answered here -- never as a pass.
            rep.skip("{}::{}_evidence".format(asset_id, stage),
                     "cannot judge cook evidence: {}. The declared-report "
                     "checks own this case.".format(err))
            continue

        state, detail = classify(report)
        rep.check(
            "{}::{}_evidence_is_independent".format(asset_id, stage),
            state == "resolved",
            "{} report for {} is {}: {}".format(stage, asset_id, state, detail),
            code=STAGE_CODE[stage])


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    n = 0
    for aid, _entry in HC.iter_houdini_assets(catalog):
        descriptor, err = _load_descriptor(aid)
        if descriptor is None:
            rep.check("{}::descriptor_loads".format(aid), False,
                      err or "no descriptor",
                      code=FailureCode.HOUDINI_COOK_EVIDENCE_SELF_AUTHORED)
            continue
        check_asset(rep, aid, descriptor)
        n += 1
    if n == 0:
        rep.skip("houdini_assets_discovered",
                 "no houdini_generated assets in the mesh catalog; this gate "
                 "proved NOTHING about cook evidence (not passed, not failed)")
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Refuse self-authored Houdini cook evidence (WF239).")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-houdini-cook-evidence", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / REPORT_REL, "validate_houdini_cook_evidence_report.json")
    rep.print_summary("validate-houdini-cook-evidence")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
