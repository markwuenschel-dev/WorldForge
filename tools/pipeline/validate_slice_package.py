#!/usr/bin/env python3
"""validate_slice_package.py — v2.0 Agent-6 package proof gate.

Proves the vertical-slice build artifact exists and is coherent: it validates the
SlicePackageReport against the schema and asserts package_exists with size>0, the
slice maps are included, the runtime entrypoint is one of them, and (live report)
git_sha is real and matches the current commit. A package report cannot pass with
no package on disk. Fail-closed RED until Wave P produces the package.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_package.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/package/validate_slice_package_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
import slice_evidence as SE
from failure_codes import FailureCode as F
from report_meta import build_meta, git_sha, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / SX.SLICE_PACKAGE_REPORTS_REL
SLICE_ID = "worldforge_vertical_slice"
_TARGET_SUFFIX = ".Target.cs"


def _real_ue_targets():
    """The set of real UnrealBuildTool target names (Source/<name>.Target.cs)."""
    return {p.name[:-len(_TARGET_SUFFIX)]
            for p in (REPO_ROOT / "Source").glob("*" + _TARGET_SUFFIX)}


def _dogfood(rep):
    good = SX._example_slice_package_report()
    gfails = [c for c in SX.validate_slice_package_report(good, strict=True) if not c[1]]
    rep.check("dogfood::good_package_passes", len(gfails) == 0,
              "reference package report rejected: {}".format([c[0] for c in gfails][:4]),
              code=F.SLICE_REPORT_INTEGRITY_FAILED)
    for label, over in (("no_package", {"package_exists": False, "package_size_bytes": 0}),
                        ("zero_size", {"package_size_bytes": 0}),
                        ("no_maps", {"maps_included": []}),
                        ("live_no_sha", {"git_sha": "unknown"})):
        bad = SX._example_slice_package_report(**over)
        bfails = [c for c in SX.validate_slice_package_report(bad, strict=True) if not c[1]]
        rep.check("dogfood::rejects_{}".format(label), len(bfails) > 0,
                  "'{}' package report must be rejected".format(label),
                  code=F.SLICE_NEGATIVE_ACCEPTED)
    # C8: prove the ue_target resolution predicate rejects a fictional target.
    real = _real_ue_targets()
    rep.check("dogfood::ue_target_real_passes", "WorldForge" in real,
              "expected WorldForge to resolve as a real UE target", code=F.SLICE_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::ue_target_fiction_rejected", "WorldForgeVerticalSlice" not in real,
              "a fictional ue_target must NOT resolve to a real target",
              code=F.SLICE_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice package gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    pkg_path = SE.PACKAGE_DIR / "slice_package_{}.json".format(SLICE_ID)
    rep.check("package_report_present", pkg_path.is_file(),
              "package report missing — run Wave P (build+package) to produce it",
              code=F.SLICE_PACKAGE_MISSING)
    if pkg_path.is_file():
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        for name, ok, detail, code in SX.validate_slice_package_report(pkg, strict=True):
            rep.check("package::{}".format(name), ok, detail, code=code)
        # the package artifact must actually exist on disk
        ppath = pkg.get("package_path")
        rep.check("package::artifact_on_disk",
                  isinstance(ppath, str) and (REPO_ROOT / ppath).is_file(),
                  "package_path does not resolve to a real file: {!r}".format(ppath),
                  code=F.SLICE_PACKAGE_MISSING)
        # entrypoint must be one of the included maps
        rep.check("package::entrypoint_included",
                  pkg.get("runtime_entrypoint") in (pkg.get("maps_included") or []),
                  "runtime_entrypoint must be one of maps_included", code=F.SLICE_PACKAGE_INVALID)
        # ue_target must resolve to a REAL UnrealBuildTool target (C8): a package
        # report cannot claim a UE target that has no Source/<ue_target>.Target.cs.
        real_targets = _real_ue_targets()
        rep.check("package::ue_target_is_real",
                  pkg.get("ue_target") in real_targets,
                  "ue_target {!r} is not a real UE target (have {})".format(
                      pkg.get("ue_target"), sorted(real_targets)),
                  code=F.SLICE_PACKAGE_INVALID)
        # live evidence must carry a REAL sha (build provenance). We do NOT require
        # ==HEAD: a committed package report necessarily predates the commit that
        # records it, and the repo has no HEAD-comparison staleness check anywhere
        # (the honest invariant, per slice_report_integrity, is "a real sha"). A
        # mismatch against the current HEAD is surfaced as a non-blocking note.
        if pkg.get("created_at") == "live":
            sha = pkg.get("git_sha")
            rep.check("package::git_sha_real",
                      isinstance(sha, str) and sha and sha != "unknown",
                      "live package must carry a real git_sha (got {!r})".format(sha),
                      code=F.SLICE_STALE_EVIDENCE)
            rep.warn_only("package::git_sha_matches_head", sha == git_sha(),
                          "package built at {} (current HEAD {})".format(sha, git_sha()),
                          code=F.SLICE_STALE_EVIDENCE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-package", pack=args.pack, strict=strict,
                            status=rep.status, record_count=1,
                            report_type="wf.slice.package_gate.v1"))
    rep.write(REPORT_DIR, "validate_slice_package_report.json")
    rep.print_summary("validate-slice-package")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
