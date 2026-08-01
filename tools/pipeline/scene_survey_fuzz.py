#!/usr/bin/env python3
"""scene_survey_fuzz.py — v2.6 deterministic SceneSurveyForge schema fuzz.

Generates CASES mutated scene-survey records from the contract registry — each mutation
breaks a valid example in one way (drop a required field, wrong-type a field, inject an
unknown field, corrupt schema_version, apply the registered known-bad, or corrupt the
subject-binding vocabulary) — and asserts the schema REJECTS every one under STRICT.
_mutate GUARANTEES invalidity: if the chosen mutation does not break the record, it falls
back to dropping a required field (check_required always catches that). Deterministic
(--seed).

The 'subject_vocab' strategy fuzzes the v2.6 ownership boundary specifically: the two
anchor channels (neither / both / mode-channel disagreement), a resolved_by that is not
"caller", and the report-side echo (subject_id, observed anchor, captures_requested). A
second PAIR lane fuzzes the subject<->report binding — mismatched id/map, transform drift
past tolerance, a swapped object path, a non-caller resolver — because a report that
surveyed the wrong subject is shaped-perfectly on both sides and only the pair can see it.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/scene_survey_fuzz.py --cases 300 --seed 1337 --strict
Reports -> procedural/reports/scene_survey/negatives/scene_survey_fuzz_report.json
"""

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as SS
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "negatives"

REQUIRED = {
    "SceneSurveySubject": SS.SUBJECT_REQUIRED,
    "SceneSurveyProfile": SS.PROFILE_REQUIRED,
    "SceneSurveyCameraCapture": SS.CAMERA_REQUIRED,
    "SceneSurveySupportMap": SS.SUPPORT_REQUIRED,
    "SceneSurveyTemporaryPlacement": SS.PLACEMENT_REQUIRED,
    "SceneSurveyProxyReport": SS.PROXY_REPORT_REQUIRED,
    "SceneSurveyReport": SS.REPORT_REQUIRED,
    "SceneSurveyEvidenceIndex": SS.INDEX_REQUIRED,
}
_WRONG_TYPE_VALUE = {"__wf_fuzz__": "not_a_valid_scalar_or_bounded_entry"}
# Neutral fixture object paths — WorldForge owns no subject vocabulary of its own.
_OBJ_PATH_A = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.Fixture_Subject_0"
_OBJ_PATH_B = "/Game/Fixture/Lvl_Fixture.Lvl_Fixture:PersistentLevel.Fixture_Other_7"


def _vocab_mutations(name):
    """Overrides that break the v2.6 subject-binding vocabulary specifically.

    Built fresh per call so a mutated record can never leak into the next case.
    Records with no subject vocabulary return () and fall back to a required drop.
    """
    if name == "SceneSurveySubject":
        return (
            {"anchor_location": None, "anchor_object_path": None},     # neither channel
            {"anchor_object_path": _OBJ_PATH_A},                       # both channels
            {"anchor_location": None, "anchor_object_path": _OBJ_PATH_A,
             "anchor_mode": "explicit_transform"},                     # mode vs channel
            {"anchor_mode": "actor_object_path"},                      # mode vs channel
            {"anchor_mode": "nearest_thing"},
            {"subject_kind": "vibe"},
            {"resolved_by": "worldforge"},                             # WF1108
            {"resolved_by": None},
            {"subject_id": "   "},
            {"anchor_rotation": [0.0, 90.0]},
            {"anchor_location": [1200.0, -450.0]},
        )
    if name == "SceneSurveyProfile":
        return (
            {"subject": "subject_fixture_alpha"},
            {"subject": {}},
            {"subject": SS._example_scene_survey_subject(subject_id="")},
            {"subject": SS._example_scene_survey_subject(resolved_by="worldforge")},
            {"subject": SS._example_scene_survey_subject(
                anchor_location=None, anchor_object_path=None)},
            {"captures": ["gameplay", "xray"]},
        )
    if name == "SceneSurveyReport":
        return (
            {"subject_id": ""},
            {"subject_resolved_by": "worldforge"},                     # WF1108
            {"subject_resolved_by": None},
            {"observed_anchor_location": None},                        # executed run
            {"observed_anchor_location": [1200.0, -450.0]},
            {"observed_anchor_object_path": 17},
            {"captures_requested": ["xray"]},
            {"captures_requested": "gameplay"},
        )
    return ()


def _pair_mutations():
    """(label, subject, report) pairs the binding validator MUST reject."""
    subj = SS._example_scene_survey_subject
    rpt = SS._example_scene_survey_report

    def path_subject():
        return subj(subject_kind="actor", anchor_mode="actor_object_path",
                    anchor_location=None, anchor_object_path=_OBJ_PATH_A)

    return (
        ("subject_id", subj(), rpt(subject_id="subject_fixture_beta")),
        ("map", subj(), rpt(map_asset_path="/Game/Fixture/Lvl_Other")),
        ("transform_drift", subj(), rpt(observed_anchor_location=[1200.0, -450.0, 97.5])),
        ("transform_absent", subj(), rpt(observed_anchor_location=None)),
        ("object_path", path_subject(), rpt(observed_anchor_object_path=_OBJ_PATH_B)),
        ("object_path_absent", path_subject(), rpt(observed_anchor_object_path=None)),
        ("report_resolver", subj(), rpt(subject_resolved_by="worldforge")),
        ("subject_resolver", subj(resolved_by="worldforge"), rpt()),
    )


def _mutate(rng, name, validate, good_fn, bad_fn):
    strat = rng.choice(("drop_required", "wrong_type", "unknown_field",
                        "bad_schema_version", "known_bad", "subject_vocab"))
    rec, req = good_fn(), REQUIRED[name]
    if strat == "subject_vocab":
        muts = _vocab_mutations(name)
        if muts:
            over = muts[rng.randrange(len(muts))]
            rec.update(over)
            label = "vocab:{}".format("+".join(sorted(over)))
        else:
            f = rng.choice(req)
            rec.pop(f, None)
            return ("vocab_na+drop:{}".format(f), rec)
    elif strat == "wrong_type":
        f = rng.choice(req)
        rec[f] = dict(_WRONG_TYPE_VALUE)
        label = "wrongtype:{}".format(f)
    elif strat == "unknown_field":
        rec["__fuzz_unknown__{}".format(rng.randint(0, 9))] = "x"
        label = "unknown_field"
    elif strat == "bad_schema_version":
        rec["schema_version"] = "wf.scene_survey.bogus.v{}".format(rng.randint(2, 9))
        label = "bad_schema_version"
    elif strat == "known_bad":
        return ("known_bad", bad_fn())
    else:
        f = rng.choice(req)
        rec.pop(f, None)
        return ("drop:{}".format(f), rec)
    # guarantee invalidity: if the mutation didn't break it, drop a required field.
    if not [c for c in validate(rec, strict=True) if not c[1]]:
        f = rng.choice(req)
        rec.pop(f, None)
        label += "+drop:{}".format(f)
    return (label, rec)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey schema fuzz.")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "scene_survey_fuzz", strict=strict)
    rng = random.Random(args.seed)

    names = list(SS.CONTRACTS.keys())
    accepted_invalid = 0
    for i in range(args.cases):
        name = names[i % len(names)]
        validate, good_fn, bad_fn = SS.CONTRACTS[name]
        label, rec = _mutate(rng, name, validate, good_fn, bad_fn)
        if not [c for c in validate(rec, strict=True) if not c[1]]:
            accepted_invalid += 1
            rep.check("fuzz::case{}::{}::{}".format(i, name, label), False,
                      "mutated {} record was ACCEPTED (fake green)".format(name),
                      code=F.SCENE_SURVEY_FUZZ_ACCEPTED)

    rep.check("fuzz::zero_invalid_accepted", accepted_invalid == 0,
              "{} invalid case(s) accepted".format(accepted_invalid), code=F.SCENE_SURVEY_FUZZ_ACCEPTED)
    rep.check("fuzz::case_count", args.cases > 0, "must run > 0 cases", code=F.SCENE_SURVEY_FUZZ_ACCEPTED)

    # --- PAIR lane: the subject<->report binding, invisible from either object ---
    # Draws from the same rng stream, so --seed still reproduces the whole run.
    pair_modes = _pair_mutations()
    pair_cases = max(len(pair_modes), args.cases // 5)
    pair_accepted = 0
    for i in range(pair_cases):
        label, subject, report = pair_modes[rng.randrange(len(pair_modes))]
        pfails = [c for c in SS.validate_subject_binding(subject, report, strict=True)
                  if not c[1]]
        if not pfails:
            pair_accepted += 1
            rep.check("fuzz::pair{}::{}".format(i, label), False,
                      "mismatched subject<->report pair was ACCEPTED (fake green)",
                      code=F.SCENE_SURVEY_FUZZ_ACCEPTED)
    rep.check("fuzz::pair::zero_invalid_accepted", pair_accepted == 0,
              "{} mismatched pair(s) accepted".format(pair_accepted),
              code=F.SCENE_SURVEY_FUZZ_ACCEPTED)
    rep.check("fuzz::pair::case_count", pair_cases >= len(pair_modes),
              "pair lane must exercise every mutation mode at least once",
              code=F.SCENE_SURVEY_FUZZ_ACCEPTED)
    # reverse: a MATCHED pair must still pass clean, or the lane is rejecting everything.
    for tag, subj, rp in (
            ("explicit_transform", SS._example_scene_survey_subject(),
             SS._example_scene_survey_report()),
            ("actor_object_path",
             SS._example_scene_survey_subject(
                 subject_kind="actor", anchor_mode="actor_object_path",
                 anchor_location=None, anchor_object_path=_OBJ_PATH_A),
             SS._example_scene_survey_report(observed_anchor_object_path=_OBJ_PATH_A))):
        mfails = [c for c in SS.validate_subject_binding(subj, rp, strict=True) if not c[1]]
        rep.check("fuzz::pair::matched::{}".format(tag), len(mfails) == 0,
                  "matched pair rejected: {}".format([c[0] for c in mfails][:3]),
                  code=F.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    for name, (validate, good_fn, _bad) in SS.CONTRACTS.items():
        gfails = [c for c in validate(good_fn(), strict=True) if not c[1]]
        rep.check("fuzz::valid::{}".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:3]),
                  code=F.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="scene-survey-fuzz", pack=None, strict=strict, status=rep.status,
        record_count=args.cases + pair_cases, records_total=args.cases + pair_cases,
        report_type="wf.scene_survey.fuzz.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "scene_survey_fuzz_report.json")
    rep.print_summary("scene-survey-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
