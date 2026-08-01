#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acceptance_recompute_mutations.py — mutation evidence for the acceptance rails.

A rail that has only ever been observed passing proves nothing, and a rail that
has only ever been observed failing is indistinguishable from a rail that always
fails. This harness drives the SHIPPED rail —
``validate_scene_survey_runtime._validate_recompute`` — over one acceptance
fixture, both clean and with exactly one atom changed per term, and prints what
each run actually failed.

TWO KINDS OF MUTATION, and both are needed:

  INPUT MUTATION      Break one atom of the raw (or forge one value in the
                      report) while the report still claims
                      ``acceptance_eligible=True``. The rail must go RED.
                      This proves the rail CATCHES the defect.

  IMPLEMENTATION MUTATION
                      Re-introduce the defect in this repository's own code:
                      stub the term's derivation so it always answers True — the
                      "trust the emitted value" shape the whole evidence model
                      exists to forbid — and re-run the SAME input mutation. The
                      rail must go GREEN. This proves the RED above was produced
                      by that term and not by some unrelated rail firing nearby.
                      A negative nobody can kill is a negative nobody has tested.

Usage::

    PYTHONUTF8=1 python tools/pipeline/acceptance_recompute_mutations.py
    PYTHONUTF8=1 python tools/pipeline/acceptance_recompute_mutations.py --verbose
    PYTHONUTF8=1 python tools/pipeline/acceptance_recompute_mutations.py \
        --json procedural/reports/scene_survey/hostile/acceptance_mutations.json

EXIT-CODE CONTRACT (this is what a gate calls):

    0  every one of the six terms M W P T B E had its input mutation RED the
       acceptance rail AND had that RED killed by the implementation mutation,
       AND both controls, the cross-check, the symmetry case and the
       anti-circularity demonstration held.
    1  any of the above did not hold.
    2  the harness could not run at all (import/fixture failure) — distinct from
       1, because "the rails are not carrying their weight" and "we never got to
       ask" are different verdicts and must not be conflated.

``--json PATH`` additionally writes the structured verdict, so a caller can
assert on the CONTENT — which terms were actually exercised — instead of trusting
a bare zero. An exit code alone cannot distinguish "six terms all killed their
mutants" from "the TERMS tuple was emptied", and a gate that cannot tell those
apart is the same vacuity this harness exists to refuse.
See ``run_v2_6_known_bads.py --mutations``, which is that caller.
"""

import argparse
import json
import sys
from pathlib import Path

#: Terms the JSON verdict must report as exercised. A caller asserts on this so
#: that emptying TERMS cannot quietly turn the harness into a no-op that exits 0.
EXPECTED_TERMS = ("M", "W", "P", "T", "B", "E")

VERDICT_SCHEMA = "wf.scene_survey.acceptance_mutation_evidence.v1"

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_recompute as RC              # noqa: E402
import validate_scene_survey_runtime as V        # noqa: E402

ACC_RAIL = "recompute::mut::acceptance_claim_matches_raw"
ACC_COMP = "recompute::mut::acceptance_components_follow_from_raw"
ACC_EV = "recompute::mut::acceptance_evidence_not_contradicted"

ANCHOR = RC._ACC_ANCHOR
PATH = RC._ACC_PATH
OTHER = RC._ACC_OTHER


# --------------------------------------------------------------------------- #
# INPUT mutations — one atom each. Every one leaves the report claiming
# acceptance_eligible=True, which is what the assembler writes when the shared
# predicate is satisfied (run_scene_survey_probe.py:795-796).
# --------------------------------------------------------------------------- #
def m_anchor_mode(subject, _report, _raw):
    """M — the caller's mode is not the observable one."""
    subject["anchor_mode"] = "explicit_transform"


def w_world_identity(_subject, _report, raw):
    """W — the editor measured a different world than the caller requested."""
    # BOTH fields, because scene_survey_far_side.py:2238 caches world_identity FROM
    # package_name — a bundle where only one moved is incoherent and term E catches
    # it first, which would make this mutation unattributable to W. The coherent
    # form is also the harder case: a survey of the wrong world that is internally
    # perfectly consistent about it.
    raw["world"]["observed"]["package_name"] = "/Game/Fixture/Lvl_Elsewhere"
    raw["world"]["observed"]["world_identity"] = "/Game/Fixture/Lvl_Elsewhere"


def w_world_identity_incoherent(_subject, _report, raw):
    """W/E — package_name moved but the cached world_identity did not."""
    raw["world"]["observed"]["package_name"] = "/Game/Fixture/Lvl_Elsewhere"


def p_actor_identity(_subject, _report, raw):
    """P — the surveyed actor population does not contain the requested actor."""
    rec = raw["actor"].pop(PATH)
    rec["path_name"] = OTHER + "_substitute"
    rec["actor_object_path"] = rec["path_name"]
    raw["actor"][rec["path_name"]] = rec


def t_transform(_subject, report, _raw):
    """T — the anchor the report states is 500cm from where the actor measures."""
    report["observed_anchor_location"] = [ANCHOR[0] + 500.0, ANCHOR[1], ANCHOR[2]]


def b_survey_origin(_subject, _report, raw):
    """B — the sweep distances do not resolve about the resolved actor."""
    raw["actor"][OTHER]["distance_to_anchor_cm"] = 999.0


def e_operation_binding(_subject, _report, raw):
    """E — the bundle carries records from two different operations."""
    raw["actor"][OTHER]["operation_id"] = "op_some_other_run"


# --------------------------------------------------------------------------- #
# IMPLEMENTATION mutations — reintroduce the defect, one term at a time.
# Each replaces the term's derivation with a stub that answers True regardless of
# the evidence: the "the value is whatever the producer said" failure mode.
# --------------------------------------------------------------------------- #
def _always_true(name):
    def _stub(*_a, **_kw):
        return RC._verdict(True, "MUTANT: {} stubbed to True regardless of raw".format(name))
    return _stub


def _resolve_by_proximity(name):
    """The P defect, as it would actually be written: identity by POSITION.

    A stub that merely forces P's verdict to True is not a faithful mutant — it
    returns no resolved record, so T and B are starved of the actor they measure
    against and go UNKNOWN, and the rail stays RED for a reason that has nothing to
    do with P. The plausible real defect is resolving the anchor by "whichever
    actor the sweep centred on" instead of by the path the caller named, which is
    precisely the substitution term P exists to refuse. That is what this stubs in,
    and the rail must then go GREEN — proving the original RED was P's doing.
    """
    def _stub(raw, requested_path, *_a, **_kw):
        actors = RC._actor_records(raw)
        for ident in sorted(actors):
            rec = actors[ident]
            if isinstance(rec, dict) and RC.is_finite_number(
                    rec.get("distance_to_anchor_cm")) \
                    and abs(float(rec["distance_to_anchor_cm"])) <= 0.05:
                return RC._verdict(
                    True, "MUTANT: {} resolved {!r} by proximity, not by the "
                          "requested path {!r}".format(name, ident, requested_path),
                    record=rec, ident=ident)
        return RC._verdict(True, "MUTANT: {} stubbed True with nothing to resolve"
                           .format(name), record=None, ident=None)
    return _stub


TERMS = (
    ("M", "anchor_mode_observable", m_anchor_mode, (ACC_RAIL,),
     "anchor mode is exactly 'actor_object_path'"),
    ("W", "world_identity_ok", w_world_identity, (ACC_RAIL,),
     "requested map == independently observed world package"),
    ("P", "anchor_actor_resolution", p_actor_identity, (ACC_RAIL,),
     "requested actor path == independently resolved actor path"),
    ("T", "anchor_transform_bound", t_transform, (ACC_RAIL,),
     "stated transform agrees with the measured actor transform within tau"),
    ("B", "survey_bound_to_anchor", b_survey_origin, (ACC_RAIL,),
     "survey origin and measurements are bound to that resolved actor"),
    ("E", "raw_observations_complete", e_operation_binding, (ACC_RAIL, ACC_EV),
     "raw observations complete, operation-bound, finite, self-consistent"),
)


def run(mutate=None, operation_id=RC._ACC_OP):
    """Run the SHIPPED recompute rail over the fixture; return the failed rails."""
    subject, report, raw = RC._clean_acceptance_case()
    if mutate is not None:
        mutate(subject, report, raw)
    return V._ran(V._validate_recompute, subject, report,
                  [("acceptance_fixture", raw, {"operation_id": operation_id})],
                  V._Args(), "mut", operation_id=operation_id)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verbose", action="store_true",
                    help="print every failed rail, not just the acceptance ones")
    ap.add_argument("--json", dest="json_path", default=None,
                    help="write the structured verdict here (see VERDICT_SCHEMA)")
    # Accepted so the shield's uniform `--pack X --strict` argv shape reaches this
    # harness unchanged. Neither changes what is tested: the mutation ladder is
    # already the strictest reading of the rail, so there is no laxer mode to
    # select, and this gate is not pack-scoped.
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _unknown = ap.parse_known_args(argv)

    failures = []
    verdict = {
        "schema": VERDICT_SCHEMA,
        "pack": args.pack,
        "rail_under_test": "validate_scene_survey_runtime._validate_recompute",
        "fixture": "scene_survey_recompute._clean_acceptance_case",
        "tau_anchor_transform_cm": RC.TAU_ANCHOR_TRANSFORM_CM,
        "terms": {},
        "controls": {},
        "failures": failures,
    }

    def show(label, got, expect_red, note=""):
        rails = sorted(r for r in got if "acceptance" in r) if not args.verbose \
            else sorted(got)
        red = all(r in got for r in expect_red) if expect_red else not got
        mark = "RED " if got else "GREEN"
        print("  [{}] {:<46} {}".format(mark, label, note))
        for rail in rails:
            print("           ^ {}".format(rail))
        return red

    print("=" * 78)
    print("ACCEPTANCE RECOMPUTE — MUTATION EVIDENCE")
    print("rail under test: validate_scene_survey_runtime._validate_recompute")
    print("fixture:         scene_survey_recompute._clean_acceptance_case()")
    print("tolerance tau_T: {}cm (scene_survey_recompute.TAU_ANCHOR_TRANSFORM_CM)"
          .format(RC.TAU_ANCHOR_TRANSFORM_CM))
    print("=" * 78)

    print("\n0. CONTROL — unmutated fixture. Every rail must be GREEN.")
    clean = run()
    verdict["controls"]["clean_control_green"] = not clean
    if clean:
        failures.append("control: the clean fixture failed {}".format(sorted(clean)))
        show("clean fixture", clean, (), "<- MUST be green")
    else:
        print("  [GREEN] clean fixture                          "
              "all rails pass; every RED below is caused by the mutation")

    for term, fname, mutate, expect, meaning in TERMS:
        print("\n{}. TERM {} — {}".format(term, term, meaning))
        print("   INPUT MUTATION: {}".format((mutate.__doc__ or "").strip()))
        got = run(mutate)
        input_red = show("input mutation", got, expect, "<- expect RED on {}".format(
            list(expect)))
        if not input_red:
            failures.append("{}: input mutation did NOT red {}; got {}".format(
                term, list(expect), sorted(got)))
        verdict["terms"][term] = {
            "derivation": fname,
            "meaning": meaning,
            "expected_rails": list(expect),
            "input_mutation_red": bool(input_red),
            "observed_failed_rails": sorted(got),
        }

        print("   IMPLEMENTATION MUTATION: scene_survey_recompute.{} -> always True"
              .format(fname))
        original = getattr(RC, fname)
        setattr(RC, fname,
                _resolve_by_proximity(fname) if term == "P" else _always_true(fname))
        try:
            killed = run(mutate)
        finally:
            setattr(RC, fname, original)
        still_red = [r for r in expect if r in killed]
        verdict["terms"][term]["mutant_killed"] = not still_red
        verdict["terms"][term]["survived_rails"] = sorted(still_red)
        if still_red:
            failures.append(
                "{}: stubbing {} to True did NOT stop {} from firing — the RED "
                "above is not attributable to term {}".format(term, fname,
                                                              still_red, term))
            show("with the term stubbed out", killed, (), "<- MUTANT SURVIVED")
        else:
            print("  [GREEN] with the term stubbed out              "
                  "<- mutant killed: the RED above IS term {}".format(term))
        # And the restoration must be real, not hopeful.
        restored = getattr(RC, fname) is original
        verdict["terms"][term]["derivation_restored"] = restored
        assert restored, "failed to restore " + fname

    print("\n7. CROSS-CHECK — an INCOHERENT world record is caught twice over.")
    print("   (package_name moved but the cached world_identity did not: W denies "
          "it, and\n    E denies the record's right to be read at all)")
    got = run(w_world_identity_incoherent)
    cross_ok = show("world_identity drift", got, (ACC_RAIL, ACC_EV),
                    "<- expect RED on the acceptance AND the evidence rail")
    verdict["controls"]["cross_check_double_catch"] = bool(cross_ok)
    if not cross_ok:
        failures.append("cross-check: an incoherent world record did not red both "
                        "{} and {}; got {}".format(ACC_RAIL, ACC_EV, sorted(got)))

    print("\n8. SYMMETRY — a report UNDER-claiming against its own evidence.")

    def under_claim(_s, report, _raw):
        report["acceptance_eligible"] = False
        report["acceptance_ineligibility_reason"] = \
            "independent_subject_anchor_not_observable"

    got = run(under_claim)
    sym_ok = show("acceptance_eligible=False over eligible raw", got, (ACC_RAIL,),
                  "<- expect RED (contracts.py:1144-1153 left this uninstalled)")
    verdict["controls"]["symmetry_under_claim_red"] = bool(sym_ok)
    if not sym_ok:
        failures.append("symmetry: an under-claim did not red {}".format(ACC_RAIL))

    print("\n9. ANTI-CIRCULARITY — the shared predicate is STRUCTURALLY blind here.")
    print("   No mutation needed for this one. The raw says the editor opened")
    print("   Lvl_Elsewhere; the report echoes the requested map, which is what")
    print("   scene_survey_evidence.acceptance_raw:1557 feeds the shared predicate")
    print("   as the 'observed' world. So the shared predicate — the one the")
    print("   assembler wrote the claim with (run_scene_survey_probe.py:795) and")
    print("   the one the validator used to reach eligibility through")
    print("   SS.validate_subject_binding — agrees the survey is eligible.")
    import scene_survey_contracts as SS_READONLY   # test-only: to SHOW the blindness
    b_sub, b_rep, b_raw = RC._clean_acceptance_case()
    w_world_identity(b_sub, b_rep, b_raw)
    shared = SS_READONLY.evaluate_acceptance_eligibility(b_sub, b_rep)
    shared_binding = [c[0] for c in SS_READONLY.validate_subject_binding(
        b_sub, b_rep, strict=True) if not c[1]]
    print("     shared evaluate_acceptance_eligibility -> eligible={!r} "
          "failed_components={}".format(shared["eligible"],
                                        shared["failed_components"]))
    print("     shared validate_subject_binding        -> failures={}".format(
        shared_binding))
    mine = run(w_world_identity)
    print("     THIS module's independent rail         -> failures={}".format(
        sorted(r for r in mine if "acceptance" in r)))
    anti_ok = (shared["eligible"] is True and not shared_binding
               and ACC_RAIL in mine)
    verdict["controls"]["anti_circularity_independent"] = bool(anti_ok)
    if not anti_ok:
        failures.append(
            "anti-circularity: expected the shared predicate to accept and this "
            "module to REJECT the same wrong-world survey; shared eligible={!r} "
            "shared binding failures={} mine={}".format(
                shared["eligible"], shared_binding, sorted(mine)))
    else:
        print("  [OK] the two disagree, which is the entire point: the shared")
        print("       predicate never opens the raw bundle, and this one never")
        print("       opens the shared predicate.")

    print("\n10. RESTORATION — every implementation mutation reverted.")
    final = run()
    verdict["controls"]["restoration_green"] = not final
    if final:
        failures.append("restoration: the clean fixture now fails {}".format(
            sorted(final)))
        show("clean fixture, after all mutations", final, (), "<- MUST be green")
    else:
        print("  [GREEN] clean fixture                          "
              "the harness left no mutation behind")

    # Self-vacuity rail. Everything above is conditional on TERMS being populated;
    # an empty TERMS would skip every loop body and reach here with no failures at
    # all. This is the one check that cannot be satisfied by doing nothing.
    missing = [t for t in EXPECTED_TERMS if t not in verdict["terms"]]
    if missing:
        failures.append(
            "coverage: terms {} were never exercised — a harness that skips a term "
            "reports PASS for a rail it never questioned".format(missing))
    verdict["terms_exercised"] = sorted(verdict["terms"])
    verdict["terms_expected"] = list(EXPECTED_TERMS)
    verdict["ok"] = not failures
    verdict["status"] = "pass" if not failures else "fail"

    if args.json_path:
        out = Path(args.json_path)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(verdict, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")
        print("\n[mutations] verdict -> {}".format(out))

    print("\n" + "=" * 78)
    for line in failures:
        print("FAIL {}".format(line))
    print("ACCEPTANCE MUTATION EVIDENCE: {} ({} term(s) x input+implementation, "
          "+ symmetry, + 2 controls)".format("PASS" if not failures else "FAIL",
                                             len(TERMS)))
    print("=" * 78)
    return 0 if not failures else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:                                  # noqa: BLE001
        # Exit 2, never 1: "the rails did not carry their weight" and "the harness
        # never got to ask" are different verdicts, and a gate that reads them as
        # the same one will one day report a broken import as a tested rail.
        print("ACCEPTANCE MUTATION EVIDENCE: ERROR — harness did not complete: "
              "{}: {}".format(type(exc).__name__, exc), file=sys.stderr)
        sys.exit(2)
