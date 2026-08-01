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

The subject<->report PAIR validator (validate_subject_binding, WF1107/WF1108) is
dogfooded separately: it is not a CONTRACTS entry because it validates a RELATION,
not a record, so the registry loop cannot reach it. Both legal anchor modes must
bind clean, and each pair rail must reject for its owning code — otherwise the
ownership boundary the milestone exists to enforce is unguarded.

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


OBJ_PATH_A = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.Fixture_Subject_0"
OBJ_PATH_B = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.Fixture_Other_7"


def _path_subject():
    return SS._example_scene_survey_subject(
        subject_kind="actor", anchor_mode="actor_object_path",
        anchor_location=None, anchor_object_path=OBJ_PATH_A)


def dogfood_pair(rep):
    """Dogfood validate_subject_binding — a RELATION, so the registry can't reach it."""
    subj, rpt = SS._example_scene_survey_subject, SS._example_scene_survey_report
    # A matched pair must bind CLEAN in both legal anchor modes.
    for tag, s, r in (
            ("explicit_transform", subj(), rpt()),
            ("actor_object_path", _path_subject(),
             rpt(observed_anchor_object_path=OBJ_PATH_A))):
        fails = [c for c in SS.validate_subject_binding(s, r, strict=True) if not c[1]]
        rep.check("dogfood::SubjectBinding::{}::matched_pair_binds".format(tag),
                  len(fails) == 0,
                  "matched subject<->report pair rejected: {}".format(
                      [c[0] for c in fails][:4]),
                  code=FailureCode.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    # ...and every pair rail must REJECT for its owning code.
    M = FailureCode.SCENE_SURVEY_SUBJECT_MISMATCH
    I = FailureCode.SCENE_SURVEY_SUBJECT_INFERRED
    for tag, s, r, owning in (
            ("subject_id", subj(), rpt(subject_id="subject_fixture_beta"), M),
            ("map", subj(), rpt(map_asset_path="/Game/Fixture/Lvl_Other"), M),
            ("transform_tolerance", subj(),
             rpt(observed_anchor_location=[1200.0, -450.0, 97.5]), M),
            ("object_path", _path_subject(),
             rpt(observed_anchor_object_path=OBJ_PATH_B), M),
            ("resolver", subj(), rpt(subject_resolved_by="worldforge"), I)):
        fails = [c for c in SS.validate_subject_binding(s, r, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("dogfood::SubjectBinding::{}::rejected".format(tag), len(fails) > 0,
                  "mismatched pair was ACCEPTED (fake green)",
                  code=FailureCode.SCENE_SURVEY_NEGATIVE_ACCEPTED)
        rep.check("dogfood::SubjectBinding::{}::owning_code".format(tag), owning in codes,
                  "pair must be rejected for owning code {} (got {})".format(
                      owning, sorted(str(c) for c in codes)[:4]),
                  code=FailureCode.SCENE_SURVEY_NEGATIVE_ACCEPTED)


def _registry_coherent(rep):
    rep.check("dogfood::registry_nonempty", len(SS.CONTRACTS) >= 8,
              "CONTRACTS registry must carry the 8 scene-survey contracts "
              "(got {})".format(len(SS.CONTRACTS)),
              code=FailureCode.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::subject_contract_registered",
              "SceneSurveySubject" in SS.CONTRACTS,
              "the caller-resolved SceneSurveySubject must be a registered contract",
              code=FailureCode.SCENE_SURVEY_SUBJECT_UNRESOLVED)
    # The deleted anchor vocabulary must stay deleted: WorldForge owning a bounded
    # set of subjects IS the ownership inversion this milestone reverses.
    rep.check("dogfood::no_worldforge_anchor_vocabulary",
              not hasattr(SS, "SURVEY_ANCHORS"),
              "scene_survey_contracts must not re-introduce SURVEY_ANCHORS — a "
              "WorldForge-owned subject vocabulary is the boundary violation itself",
              code=FailureCode.SCENE_SURVEY_SUBJECT_INFERRED)
    rep.check("dogfood::subject_resolver_is_caller_only",
              tuple(SS.SUBJECT_RESOLVERS) == ("caller",),
              "SUBJECT_RESOLVERS must be exactly ('caller',) (got {!r})".format(
                  getattr(SS, "SUBJECT_RESOLVERS", None)),
              code=FailureCode.SCENE_SURVEY_SUBJECT_INFERRED)
    grouped = [c for lane in SS.CONTRACT_GROUPS.values() for c in lane]
    rep.check("dogfood::groups_partition_registry",
              sorted(grouped) == sorted(SS.CONTRACTS.keys()),
              "CONTRACT_GROUPS must partition CONTRACTS exactly",
              code=FailureCode.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::known_bad_owning_complete",
              sorted(SS.KNOWN_BAD_OWNING_CODE.keys()) == sorted(SS.CONTRACTS.keys()),
              "KNOWN_BAD_OWNING_CODE must cover every contract",
              code=FailureCode.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::owns_failure_band", len(SS.SCENE_SURVEY_CODES) >= 49,
              "scene-survey milestone must own the WF1061-1109 failure band (got {})".format(
                  len(SS.SCENE_SURVEY_CODES)),
              code=FailureCode.SCENE_SURVEY_UNKNOWN_FAILURE_CODE)
    # the four subject-binding codes must actually be in the owned band.
    for code in (FailureCode.SCENE_SURVEY_SUBJECT_UNRESOLVED,
                 FailureCode.SCENE_SURVEY_SUBJECT_MISMATCH,
                 FailureCode.SCENE_SURVEY_SUBJECT_INFERRED,
                 FailureCode.SCENE_SURVEY_CHANNEL_DISAGREEMENT):
        rep.check("dogfood::band_owns::{}".format(code[:6]), code in SS.SCENE_SURVEY_CODES,
                  "{} must be inside the scene-survey owned band".format(code),
                  code=FailureCode.SCENE_SURVEY_UNKNOWN_FAILURE_CODE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey contract-spine gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = dogfood(rep)
    dogfood_pair(rep)
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
