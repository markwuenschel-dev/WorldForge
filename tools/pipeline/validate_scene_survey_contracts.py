#!/usr/bin/env python3
"""validate_scene_survey_contracts.py — v2.6 SceneSurveyForge contract-spine gate.

Proves the SceneSurveyForge schema spine (scene_survey_contracts.CONTRACTS) is
coherent and constrains correctly — the always-available, runtime-free gate that is
GREEN from Wave 1 while the C++/runtime/bridge gates stay honestly RED until real
artifacts exist.

DOGFOODS the registry: every valid example passes its own validator with zero
failures; every known-bad is REJECTED for its OWNING failure code. A validator that
greens its known-bad, or rejects the valid example, is a fake-green vector and turns
this gate RED. Mirrors validate_tactical_contracts.py exactly.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_scene_survey_contracts.py --strict
Reports -> procedural/reports/scene_survey/validate_scene_survey_contracts_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as SS
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey"


def dogfood(rep, names=None):
    names = names or list(SS.CONTRACTS.keys())
    n = 0
    for name in names:
        validate, good, bad = SS.CONTRACTS[name]
        n += 1
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("dogfood::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=FailureCode.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
        bfails = [c for c in validate(bad(), strict=True) if not c[1]]
        codes = {c[3] for c in bfails}
        rep.check("dogfood::{}::known_bad_rejected".format(name), len(bfails) > 0,
                  "known-bad example must be rejected",
                  code=FailureCode.SCENE_SURVEY_NEGATIVE_ACCEPTED)
        owning = SS.KNOWN_BAD_OWNING_CODE.get(name)
        rep.check("dogfood::{}::rejected_for_owning_code".format(name), owning in codes,
                  "known-bad must be rejected for owning code {} (got {})".format(
                      owning, sorted(str(c) for c in codes)[:4]),
                  code=FailureCode.SCENE_SURVEY_NEGATIVE_ACCEPTED)
    return n


def _registry_coherent(rep):
    rep.check("dogfood::registry_nonempty", len(SS.CONTRACTS) >= 7,
              "CONTRACTS registry must carry the 7 scene-survey contracts",
              code=FailureCode.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    grouped = [c for lane in SS.CONTRACT_GROUPS.values() for c in lane]
    rep.check("dogfood::groups_partition_registry",
              sorted(grouped) == sorted(SS.CONTRACTS.keys()),
              "CONTRACT_GROUPS must partition CONTRACTS exactly",
              code=FailureCode.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::known_bad_owning_complete",
              sorted(SS.KNOWN_BAD_OWNING_CODE.keys()) == sorted(SS.CONTRACTS.keys()),
              "KNOWN_BAD_OWNING_CODE must cover every contract",
              code=FailureCode.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::owns_failure_band", len(SS.SCENE_SURVEY_CODES) >= 40,
              "scene-survey milestone must own the WF1061-1105 failure band",
              code=FailureCode.SCENE_SURVEY_UNKNOWN_FAILURE_CODE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey contract-spine gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = dogfood(rep)
    _registry_coherent(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="scene-survey-contracts", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.scene_survey.contract_spine.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_scene_survey_contracts_report.json")
    rep.print_summary("scene-survey-contracts")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
