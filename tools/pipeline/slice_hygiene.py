#!/usr/bin/env python3
"""slice_hygiene.py — v2.0 Agent-7 artifact-hygiene gate.

Proves the committed slice authoring artifacts are internally consistent and free
of orphans/staleness: the contract + manifest + the 24 scenario files agree
exactly (no scenario file missing from or extra to the manifest), scenario_count
is 24 everywhere, and every manifest map resolves to a real .umap on disk. This is
the "no silent drift" gate — it catches a stale generator run or a hand-edited
manifest before it reaches the runtime waves. GREEN from Wave 2.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/slice_hygiene.py --strict
Reports -> procedural/reports/slice/slice_hygiene_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "slice"
MAPS_DIR = REPO_ROOT / "Content" / "WorldForge" / "Maps"


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice artifact-hygiene gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "slice_hygiene", strict=strict)

    contract_path = REPO_ROOT / SX.SLICE_CONTRACT_REL
    manifest_path = REPO_ROOT / SX.SLICE_MANIFEST_REL
    scen_dir = REPO_ROOT / SX.SLICE_SCENARIOS_REL

    rep.check("contract_present", contract_path.is_file(), "vertical_slice_contract.json missing",
              code=F.SLICE_ARTIFACT_HYGIENE_FAILED)
    rep.check("manifest_present", manifest_path.is_file(), "manifest.json missing",
              code=F.SLICE_ARTIFACT_HYGIENE_FAILED)
    if not (contract_path.is_file() and manifest_path.is_file() and scen_dir.is_dir()):
        rep.error("slice authoring artifacts absent")
        rep.finalize()
        rep.write(REPORT_DIR, "slice_hygiene_report.json")
        rep.print_summary("vertical-slice-hygiene")
        sys.exit(rep.exit_code)

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scen_files = {p.stem for p in scen_dir.glob("vs_*.json")}
    manifest_scen = set(manifest.get("scenarios", []))

    # counts agree at 24 everywhere
    rep.check("contract_count_24", contract.get("scenario_count") == 24,
              "contract scenario_count != 24", code=F.SLICE_ARTIFACT_HYGIENE_FAILED)
    rep.check("manifest_count_24", manifest.get("scenario_count") == 24,
              "manifest scenario_count != 24", code=F.SLICE_ARTIFACT_HYGIENE_FAILED)
    rep.check("scenario_files_24", len(scen_files) == 24,
              "expected 24 scenario files, got {}".format(len(scen_files)),
              code=F.SLICE_ARTIFACT_HYGIENE_FAILED)

    # no orphan / no missing: scenario files set == manifest scenarios set
    orphan = scen_files - manifest_scen
    missing = manifest_scen - scen_files
    rep.check("no_orphan_scenario_files", not orphan,
              "scenario files not in manifest: {}".format(sorted(orphan)[:4]),
              code=F.SLICE_ORPHAN_REPORT)
    rep.check("no_missing_scenario_files", not missing,
              "manifest scenarios with no file: {}".format(sorted(missing)[:4]),
              code=F.SLICE_ARTIFACT_HYGIENE_FAILED)

    # every manifest map resolves to a real .umap
    unresolved = [m for m in manifest.get("maps", [])
                  if not (MAPS_DIR / (m + ".umap")).is_file()]
    rep.check("all_maps_on_disk", not unresolved,
              "manifest maps missing .umap: {}".format(unresolved[:4]),
              code=F.SLICE_ARTIFACT_HYGIENE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(command="vertical-slice-hygiene", pack=None, strict=strict,
                            status=rep.status, record_count=len(scen_files),
                            report_type="wf.slice.hygiene.v1"))
    rep.write(REPORT_DIR, "slice_hygiene_report.json")
    rep.print_summary("vertical-slice-hygiene")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
