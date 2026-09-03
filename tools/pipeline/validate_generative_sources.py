#!/usr/bin/env python3
"""validate_generative_sources.py -- a declared generative source may not be empty,
and a generated output must name the tool that produced it.

WHY THIS GATE EXISTS
--------------------
``provenance.build_provenance`` records a SHA-256 per declared input, honestly
and without judgement. That is correct behaviour for a stamper -- and it means
an input that is EMPTY is recorded exactly as faithfully as a real one. The
digest of an empty file is a real digest (sha256 of the empty byte string =
e3b0c442...b855), so a manifest whose generative source is a zero-byte file
reads as complete, clean, and ``source_tree_dirty: false``. Nothing in the chain
ever asked whether the thing it hashed was real.

That is an absence wearing a measurement's shape, and it is the same class of
defect as a gate grading its own output: the artifact is well-formed, the
pipeline is honest at every step, and the conclusion is still unsupported.

TWO CHECKS, DELIBERATELY SEPARATE
---------------------------------
1. WF022 -- a declared GENERATIVE source (the graph/HDA an output claims to have
   been produced FROM) exists and is non-empty. Emptiness is judged by ROLE, not
   by size alone: an inert empty file such as a ``.gitkeep`` is not a generative
   source and never trips this. ``procedural/manifests/ue5_8_conversion/
   pre_conversion_manifest.json`` records two such ``.gitkeep`` entries with
   ``size_bytes: 0`` alongside their digest, and it is right to -- that manifest
   declares the size, so a reader can tell. A blanket "no empty digests" rule
   would fire on those, be judged noisy, and get loosened. Role is what makes
   emptiness a lie.

2. WF023 -- a generated output records WHICH tool produced it. When a stopgap
   generator and the real external tool write the same five files, to the same
   paths, in the same format -- which is exactly what
   ``tools/substance/make_placeholder_exports.py`` does, and says so in its own
   docstring ("The contract is unchanged ... No recipe / manifest / validator
   changes are required") -- the artifacts are indistinguishable and the
   manifest cannot answer "was this rendered, or stood in for?". Naming the
   producer is what stops a stopgap silently wearing a render's provenance.

WHAT THIS GATE DOES NOT CLAIM
-----------------------------
It does not prove a render happened. A manifest that declares
``producer: substance_sbsrender`` over a non-empty graph passes here and is
still only a DECLARATION -- proving the render needs cook evidence, which is
``validate_external_tool_providers.py``'s job and uses that module's
COOK_EVIDENCE_REQUIRED vocabulary. This gate closes the cheaper hole: it makes
the lie impossible to tell by accident.

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_generative_sources.py

Writes: procedural/reports/materials/validate_generative_sources/
        validate_generative_sources_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

# sha256 of the empty byte string. A provenance entry carrying this hashed
# nothing -- the digest is real, its subject is not.
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Manifest keys whose VALUE is a path to a generative source -- the thing the
# outputs claim to have been produced from. Role-based on purpose: adding a key
# here is a statement that "the outputs came from this", not merely "this is an
# input we happened to hash".
GENERATIVE_SOURCE_KEYS = ("substance_graph_path",)

# Where the producer of the generated outputs is recorded. Absent => WF023.
SYNTHESIS_BLOCK = "synthesis"
SYNTHESIS_PRODUCER_KEYS = ("producer", "producer_version", "mode")

MANIFEST_GLOBS = ("procedural/manifests/materials/*.json",)

REPORT_REL = Path("procedural") / "reports" / "materials" / "validate_generative_sources"


def _iter_manifests():
    for pattern in MANIFEST_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if path.name.startswith("_"):
                continue
            yield path


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover - unparseable manifest
        return None, "manifest unparseable: {}".format(exc)


def check_manifest(rep, path, data):
    mid = data.get("recipe_id") or path.stem

    def c(name, ok, detail="", code=None):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    # -- 1. every declared generative source exists and is non-empty ---------
    declared = [(k, data.get(k)) for k in GENERATIVE_SOURCE_KEYS if data.get(k)]
    c("declares_generative_source", bool(declared),
      "manifest declares none of {}; nothing identifies what produced its "
      "outputs".format(list(GENERATIVE_SOURCE_KEYS)),
      code=FailureCode.PROVENANCE_INCOMPLETE)

    for key, rel in declared:
        src = REPO_ROOT / rel
        exists = src.is_file()
        if not c("{}_exists".format(key), exists,
                 "declared generative source not found: {}".format(rel),
                 code=FailureCode.PROVENANCE_SOURCE_EMPTY):
            continue
        size = src.stat().st_size
        c("{}_non_empty".format(key), size > 0,
          "declared generative source {} is {} bytes. Its digest is the digest "
          "of nothing, so every artifact claiming to be generated FROM it is "
          "unsupported. This is not a missing file: the file is present and the "
          "provenance block hashed it faithfully, which is exactly what made "
          "the gap invisible.".format(rel, size),
          code=FailureCode.PROVENANCE_SOURCE_EMPTY)

    # -- 2. no declared generative input silently hashed nothing ------------
    inputs = (data.get("provenance") or {}).get("inputs") or {}
    declared_paths = {rel for _key, rel in declared}
    empty_generative = sorted(
        p for p, digest in inputs.items()
        if digest == EMPTY_SHA256 and p in declared_paths)
    c("no_generative_input_hashed_nothing", not empty_generative,
      "provenance.inputs records the empty-string digest for declared "
      "generative source(s) {}. The hash is real; the thing it hashed is "
      "not.".format(empty_generative),
      code=FailureCode.PROVENANCE_SOURCE_EMPTY)

    # -- 3. the outputs name the tool that produced them --------------------
    synth = data.get(SYNTHESIS_BLOCK)
    if not isinstance(synth, dict) or not synth:
        c("declares_producer", False,
          "manifest has no '{}' block, so nothing records which tool wrote its "
          "exports. A stopgap generator and a real render produce byte-"
          "indistinguishable outputs at these paths; without a declared "
          "producer the manifest cannot tell them apart, and neither can a "
          "reader. Produce it by re-running the export lane.".format(
              SYNTHESIS_BLOCK),
          code=FailureCode.GENERATED_OUTPUT_PRODUCER_UNDECLARED)
        return

    missing = [k for k in SYNTHESIS_PRODUCER_KEYS
               if synth.get(k) in (None, "", [], {})]
    c("producer_complete", not missing,
      "synthesis block missing {}".format(missing),
      code=FailureCode.GENERATED_OUTPUT_PRODUCER_UNDECLARED)


def validate(strict):
    rep = ValidationReport("pack", "materials", strict=strict)
    n = 0
    for path in _iter_manifests():
        data, err = _load(path)
        if data is None:
            rep.check("{}::loads".format(path.stem), False, err,
                      code=FailureCode.DESCRIPTOR_UNPARSEABLE)
            continue
        check_manifest(rep, path, data)
        n += 1
    if n == 0:
        # Absence is not a pass: say the question could not be asked.
        rep.skip("manifests_discovered",
                 "no material manifests matched {}; this gate proved NOTHING "
                 "about generative sources (not passed, not failed)".format(
                     list(MANIFEST_GLOBS)))
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate that declared generative sources are real and "
                    "that generated outputs name their producer.")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-generative-sources", pack="materials",
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / REPORT_REL, "validate_generative_sources_report.json")
    rep.print_summary("validate-generative-sources")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
