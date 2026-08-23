#!/usr/bin/env python3
"""test_consumer_flow.py -- the consumer-proof gate.

    cd tools && PYTHONUTF8=1 python pipeline/test_consumer_flow.py

Asserts the things the consumer proof actually rests on:

  1. both shipped consumers pass every Core stage
  2. they are substantially DIFFERENT -- asserted field by field, because two
     profiles that differ only by name would pass identically and prove nothing;
     the proof is exactly as strong as the distance between the consumers
  3. neither may be labelled caller-originated, and an adapter carrying
     generation logic is rejected
  4. ``--preview`` produces all ten artifact groups for both consumers, observes
     NOTHING, plans a next step that reaches nothing, and never comes back
     satisfied

The Core boundary proof itself is exercised here too: capture, run both
consumers, verify. That is the platform claim, and a claim nobody re-runs decays
into a claim nobody checks.

EVERY PREVIEW ASSERTION IS NEGATIVE-CONTROLLED
----------------------------------------------
"the preview observed nothing", "the preview reaches nothing" and "the preview
is not satisfied" are all claims about ABSENCE, and an absence assertion passes
just as happily against a reader that cannot see anything at all. So each one is
paired with a control that makes the same machinery report the POSITIVE case:
a fabricated backed field must be REJECTED, a step declaring changes must
produce a NON-EMPTY bound, and a provider claiming seeded determinism with no
evidence must be REFUSED. Without those, a broken reader would read as a clean
preview.
"""

import json
import os
import sys
import tempfile

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import core_boundary_proof as CBP            # noqa: E402
from consumers import adapter as ADP         # noqa: E402
from pipeline import run_consumer_flow as RCF  # noqa: E402
from wfcore import tri                       # noqa: E402
from wfcore.models import observed_world as OW  # noqa: E402
from wfcore.providers import base as PB      # noqa: E402
from wfcore.providers import registry as PR   # noqa: E402
from wfcore.transaction import delta as TD    # noqa: E402

CONSUMERS = ("demoarena", "demoexpanse")

# The ten artifact groups a pre-mutation bundle must carry. Named here rather
# than counted in the assertion so a group that gets quietly dropped fails by
# NAME -- a length check would pass as soon as anything else was added.
PREVIEW_ARTIFACTS = (
    "caller_provenance",        # 1  who asked, and may this be called theirs
    "desired_world",            # 2  normalized desired state
    "observed_evidence",        # 3  what was observed (here: nothing)
    "constraint_analysis",      # 4  reconcile's verdict
    "preview_plan",             # 5  the typed plan
    "provider_selection",       # 6  which provider, and why
    "mutation_bounds",          # 7  per-step bound via delta.bound_from_step
    "expected_changes",         # 8  the deduplicated union
    "rollback_actions",         # 9  what can be compensated
    "acceptance_requirements",  # 10 what acceptance will demand
)

FAILURES = []


def check(name, ok, detail=""):
    if not ok:
        FAILURES.append("{}: {}".format(name, detail))
    print("  {:5} {}".format("PASS" if ok else "FAIL", name))


def main():
    print("consumer-proof gate")

    reports = {}
    for cid in CONSUMERS:
        rep = RCF.run_consumer(cid)
        reports[cid] = rep
        check("flow.{}.green".format(cid), rep["green"],
              "stages_failed={} {}".format(
                  rep["stages_failed"],
                  [s for s in rep["stages"] if s["status"] != "ok"][:2]))
        check("flow.{}.not_caller_originated".format(cid),
              rep["caller_originated"] is False,
              "a WorldForge-authored demonstration must never be labelled "
              "caller-originated (WF1288)")

    # --- 2. the consumers really are far apart --------------------------------
    a, b = reports["demoarena"]["profile_shape"], reports["demoexpanse"]["profile_shape"]
    for field in ("game_type", "visual_language", "camera_mode",
                  "rollback_granularity", "unknown_handling", "density_class"):
        check("differ.{}".format(field), a[field] != b[field],
              "both consumers report {}={!r}; a shared value here means this "
              "axis is untested".format(field, a[field]))

    check("differ.extent_orders_of_magnitude",
          b["extent_m2"] >= a["extent_m2"] * 100,
          "extents {} vs {} are too close to stress budgets differently".format(
              a["extent_m2"], b["extent_m2"]))
    check("differ.locomotion_modes",
          set(a["locomotion_modes"]) != set(b["locomotion_modes"]),
          "identical locomotion means identical traversal reasoning")

    # Different constraint CLASSES, not just different counts: demoexpanse
    # carries a declared_unknown, demoarena does not.
    ka = set(reports["demoarena"]["constraint_classes"])
    kb = set(reports["demoexpanse"]["constraint_classes"])
    check("differ.constraint_classes_used", ka != kb,
          "both consumers exercise the same constraint classes {}".format(ka))

    # --- 3. the rails ---------------------------------------------------------
    dirty = ADP._example_adapter()
    dirty["placement_algorithm"] = "poisson_disc"   # a GENERATION_LOGIC_FIELD
    codes = {c for (_n, ok, _d, c) in
             ADP.validate_adapter_has_no_generation_logic(dirty, "x = 1\n")
             if not ok and c}
    check("rail.generation_logic_rejected",
          "WF1287_CORE_ADAPTER_CONTAINS_GENERATION_LOGIC" in codes,
          "codes={}".format(sorted(codes)))

    unread = ADP.validate_adapter_has_no_generation_logic(ADP._example_adapter(), None)
    check("rail.unread_source_is_not_a_pass",
          any(not ok for (_n, ok, _d, _c) in unread),
          "source_text=None must report NOT CHECKED, never clean")

    # --- 4. the pre-mutation preview bundle ------------------------------------
    previews = {}
    for cid in CONSUMERS:
        rep = RCF.run_preview(cid)
        previews[cid] = rep
        art = rep["artifacts"]

        check("preview.{}.green".format(cid), rep["green"],
              "stages_failed={} {}".format(
                  rep["stages_failed"],
                  [s["stage"] for s in rep["stages"] if s["status"] != "ok"]))
        check("preview.{}.report_type".format(cid),
              rep["report_type"] == RCF.PREVIEW_REPORT_TYPE,
              "got {!r}".format(rep["report_type"]))

        missing = [k for k in PREVIEW_ARTIFACTS if k not in art]
        check("preview.{}.all_ten_artifact_groups".format(cid), not missing,
              "missing artifact group(s) {}".format(missing))
        check("preview.{}.envelope_group_present".format(cid),
              "mutation_envelope" in art,
              "the upper bound of what the request could reach is the group a "
              "caller refuses on; it may not be optional")

        # --- THE assertion this mode exists to make --------------------------
        check("preview.{}.acceptance_not_satisfied".format(cid),
              rep["preview_acceptance_verdict"] != tri.SATISFIED,
              "preview acceptance came back {!r}; that would mean the pipeline "
              "can accept a world it has never observed".format(
                  rep["preview_acceptance_verdict"]))
        check("preview.{}.acceptance_not_accepted".format(cid),
              art["acceptance_requirements"]["accepted"] is False
              and art["acceptance_requirements"]["outcome"] != "accepted",
              "outcome={!r} accepted={!r}".format(
                  art["acceptance_requirements"]["outcome"],
                  art["acceptance_requirements"]["accepted"]))
        check("preview.{}.acceptance_evidence_is_demanded".format(cid),
              art["acceptance_requirements"]["required_evidence_count"] > 0
              and art["acceptance_requirements"]["evidence_supplied_count"] == 0,
              "a preview that demanded no evidence would be trivially "
              "unsatisfiable for the wrong reason")

        # --- observation stays honest ----------------------------------------
        census = art["observed_evidence"]["field_census"]
        check("preview.{}.nothing_is_backed".format(cid),
              census and not any(r["backed"] for r in census),
              "a backed field in a preview means a measurement was fabricated: "
              "{}".format([r["path"] for r in census if r["backed"]]))
        check("preview.{}.every_field_is_unbacked_provenance".format(cid),
              all(r["provenance"] in OW.UNBACKED_PROVENANCE for r in census),
              "provenances {}".format(sorted({r["provenance"] for r in census})))
        check("preview.{}.every_unbacked_value_is_null".format(cid),
              all(r["value_is_null"] for r in census),
              "an unbacked field carrying a value cancels the difference the "
              "planner needed to see")
        check("preview.{}.field_evidence_is_unknown".format(cid),
              all(r["field_evidence"] == tri.UNKNOWN for r in census),
              "an unobserved field's evidence status must be UNKNOWN")

        # reconcile must REFUSE, and must not manufacture a violation
        an = art["constraint_analysis"]
        check("preview.{}.reconcile_refuses".format(cid),
              an["reconciled"] is False and an["same_world"] == tri.UNKNOWN,
              "reconciled={!r} same_world={!r}; reconciling against a world "
              "with no measured identity is the failure preview exists to "
              "prevent".format(an["reconciled"], an["same_world"]))
        check("preview.{}.no_violation_without_measurement".format(cid),
              not an["violated"] and not an["satisfied"],
              "a verdict of any kind requires a measurement; got violated={} "
              "satisfied={}".format(an["violated"], an["satisfied"]))

        # --- the plan this run would execute reaches NOTHING ------------------
        nxt = art["expected_changes"]["preview_plan"]
        check("preview.{}.next_plan_mutates_nothing".format(cid),
              nxt["mutates_nothing"] and nxt["total"] == 0,
              "the plan for an unobserved world declared a mutation bound: "
              "{}".format(nxt))
        next_stage = next(s for s in rep["stages"] if s["stage"] == "preview_plan")
        check("preview.{}.next_plan_is_observation_only".format(cid),
              next_stage["step_count"] > 0 and not next_stage["plan_mutates"],
              "steps={} mutates={}; a zero-step plan would make the empty "
              "bound vacuous".format(next_stage["step_count"],
                                     next_stage["plan_mutates"]))
        check("preview.{}.next_plan_selects_an_observer".format(cid),
              all(r["selected_provider"] == RCF.PROVIDER_SCENE_OBSERVER
                  for r in art["provider_selection"]["preview_plan"]),
              "an observation step selected a mutating provider")

        # --- the envelope: a plan that DOES mutate has a NON-EMPTY bound ------
        env_stage = next(s for s in rep["stages"]
                         if s["stage"] == "mutation_envelope")
        env = art["expected_changes"]["mutation_envelope"]
        check("preview.{}.envelope_plan_mutates".format(cid),
              env_stage["plan_mutates"] and env_stage["step_count"] > 0,
              "outcome={} steps={}".format(env_stage["outcome"],
                                           env_stage["step_count"]))
        check("preview.{}.envelope_expected_changes_nonempty".format(cid),
              env["total"] > 0 and env["expected_changed_packages"]
              and not env["mutates_nothing"],
              "a plan that mutates must say what it could reach; got {}".format(env))
        check("preview.{}.envelope_changes_are_sorted_and_unique".format(cid),
              env["expected_changed_packages"] == sorted(set(
                  env["expected_changed_packages"]))
              and env["expected_changed_actors"] == sorted(set(
                  env["expected_changed_actors"])),
              "the union must be deduplicated and sorted")
        check("preview.{}.envelope_is_labelled_hypothetical".format(cid),
              art["mutation_envelope"]["not_an_observation"] is True
              and art["mutation_envelope"]["basis"] ==
              "authored_maximal_obligation",
              "an authored worst case that is not labelled as one reads as a "
              "finding about the world")
        check("preview.{}.envelope_bounds_all_valid".format(cid),
              all(r["bound_is_valid"]
                  for r in art["mutation_bounds"]["mutation_envelope"]),
              "delta.validate_mutation_bound rejected a bound this preview "
              "published")

        # --- rollback is read off the provider, and is real -------------------
        rb = art["rollback_actions"]["mutation_envelope"]
        check("preview.{}.envelope_rollback_capable".format(cid),
              rb and all(r["rollback_capable"] for r in rb),
              "a mutating step whose provider cannot compensate is a change "
              "nobody can take back: {}".format(
                  [(r["step_id"], r["provider_rollback_mode"]) for r in rb]))
        check("preview.{}.envelope_rollback_names_actions".format(cid),
              all(r["compensating_actions"] for r in rb),
              "rollback_capable with no declared compensating action is a "
              "promise with no mechanism behind it")
        check("preview.{}.envelope_uses_the_real_sink".format(cid),
              all(r["provider_id"] == RCF.PROVIDER_EDITOR_SINK for r in rb),
              "the envelope must name the provider WorldForge actually has")

        check("preview.{}.declares_it_mutated_nothing".format(cid),
              rep["mutated_anything"] is False, "")

    # The two previews must differ, or one consumer's bundle is proving both.
    pa = previews["demoarena"]["artifacts"]["expected_changes"]["mutation_envelope"]
    pb = previews["demoexpanse"]["artifacts"]["expected_changes"]["mutation_envelope"]
    check("preview.envelopes_differ",
          set(pa["expected_changed_packages"]) !=
          set(pb["expected_changed_packages"]),
          "both consumers' envelopes reach the same packages {}; the bound is "
          "not being derived from the consumer at all".format(
              pa["expected_changed_packages"]))
    check("preview.declared_unknown_is_not_planned_around",
          any(e["constraint_class"] == "declared_unknown"
              for e in previews["demoexpanse"]["artifacts"][
                  "mutation_envelope"]["excluded_constraints"]),
          "demoexpanse's declared_unknown must be EXCLUDED from the envelope "
          "and reported; planning a world mutation to resolve it would have "
          "Core decide something the consumer reserved")
    check("preview.protected_semantics_is_not_planned_around",
          all(any(e["constraint_class"] == "protected_semantics"
                  for e in previews[c]["artifacts"]["mutation_envelope"][
                      "excluded_constraints"]) for c in CONSUMERS),
          "a protected-semantics remedy would mutate the content the consumer "
          "protected")

    # --- 4b. NEGATIVE CONTROLS for every preview claim above -------------------
    # (a) the observed-world validator must REJECT a fabricated measurement, or
    #     "nothing is backed" above only proves the model is empty.
    forged = RCF._unobserved_world()
    forged["world_identity"] = OW.measured(
        {"world_id": "w", "request_id": "r", "revision": 0},
        "operation_that_never_ran", "nobody", ("evidence#nonexistent",))
    codes = {c for (_n, ok, _d, c) in
             OW.validate_observed_world(forged, strict=True) if not ok and c}
    check("control.fabricated_measurement_is_rejected",
          "WF1218_CORE_OBSERVED_WORLD_UNBACKED" in codes,
          "a field claiming a measurement from an undeclared operation and a "
          "dangling evidence ref must not validate; codes={}".format(
              sorted(codes)))
    check("control.fabricated_measurement_would_be_seen_as_backed",
          OW.is_backed(forged["world_identity"]),
          "the forged field must LOOK backed locally, or the cross-record "
          "rails above are not what rejected it")

    # (b) the bound reader must produce a NON-EMPTY bound for a step that
    #     declares changes, or the empty preview bound proves only a dead reader.
    live = TD.bound_from_step({
        "step_id": "step_control",
        "expected_changed_packages": ["control://pkg_b", "control://pkg_a"],
        "expected_changed_actors": ["control://pkg_a/actor_1"]})
    check("control.bound_from_step_sees_declared_changes",
          len(live["allowed_packages"]) == 2 and len(live["allowed_actors"]) == 1
          and not live.get("declares_no_mutation"),
          "bound_from_step returned {!r} for a step that declares three "
          "targets".format(live))
    empty = TD.bound_from_step({"step_id": "step_control_empty",
                                "expected_changed_packages": [],
                                "expected_changed_actors": []})
    check("control.bound_from_step_signs_an_empty_bound",
          empty.get("declares_no_mutation") is True,
          "an explicitly empty bound must be SIGNED, so it cannot be confused "
          "with a step that forgot to declare one")

    # (c) the registry must refuse an unproven determinism claim, or the
    #     provider stage above is not validating anything.
    reg = PR.CapabilityRegistry()
    unproven = PB._example_provider_declaration(provider_id="control_unproven")
    del unproven["determinism_evidence"]          # still claims DET_SEEDED
    codes = {c for (_n, ok, _d, c) in reg.register(unproven, strict=True)
             if not ok and c}
    check("control.unproven_determinism_is_refused",
          "WF1233_CORE_PROVIDER_DETERMINISM_UNPROVEN" in codes
          and "control_unproven" not in reg,
          "codes={} registered={}".format(sorted(codes),
                                          "control_unproven" in reg))

    # (d) the shipped declarations must SURVIVE that same validator, or (c)
    #     passes because the validator rejects everything.
    reg2 = PR.CapabilityRegistry()
    for decl in (RCF._editor_sink_declaration(), RCF._scene_observer_declaration()):
        bad = [(n, c) for (n, ok, _d, c) in reg2.register(decl, strict=True)
               if not ok]
        check("control.declaration_valid.{}".format(decl["provider_id"]),
              not bad, "{}".format(bad[:4]))
    check("control.registry_covers_both_capabilities",
          not reg2.uncovered([PB.CAP_EDITOR_AUTHORING, PB.CAP_SCENE_OBSERVATION]),
          "uncovered={}".format(reg2.uncovered(
              [PB.CAP_EDITOR_AUTHORING, PB.CAP_SCENE_OBSERVATION])))

    # (e) the preview must not be able to claim a caller it does not have.
    over = ADP.validate_run_provenance(ADP._example_adapter(),
                                       ADP.ORIGINATION_CALLER)
    codes = {c for (_n, ok, _d, c) in over if not ok and c}
    check("control.preview_cannot_upgrade_to_caller_originated",
          "WF1288_CORE_CALLER_PROVENANCE_FABRICATED" in codes,
          "codes={}".format(sorted(codes)))

    # --- the boundary proof, run for real -------------------------------------
    with tempfile.TemporaryDirectory() as td:
        base_path = os.path.join(td, "base.json")
        baseline = CBP.capture()
        check("proof.baseline_is_not_vacuous", baseline["file_count"] > 0,
              "a baseline over zero files makes every verify vacuously pass")
        with open(base_path, "w", encoding="utf-8") as fh:
            json.dump(baseline, fh)

        # The PREVIEW path is exercised inside the boundary window too. It is
        # the code that reaches deepest into Core -- analysis, planning,
        # providers, transaction, acceptance -- so it is the path most able to
        # have changed something, and the one whose innocence is worth proving
        # rather than assuming.
        for cid in CONSUMERS:
            RCF.run_consumer(cid)
            RCF.run_preview(cid)

        after = CBP.capture()
        result = CBP.compare(baseline, after)
        check("proof.core_untouched_by_both_consumers", result["unchanged"],
              "modified={} added={} removed={}".format(
                  result["modified"], result["added"], result["removed"]))

        # negative control: the proof must NOTICE a change, or its silence
        # above means nothing at all.
        tampered = json.loads(json.dumps(baseline))
        tampered["files"]["tri.py"] = "sha256:" + "0" * 64
        tampered["core_digest"] = "sha256:" + "0" * 64
        neg = CBP.compare(tampered, after)
        check("proof.negative_control_detects_a_change",
              not neg["unchanged"] and "tri.py" in neg["modified"],
              "the proof failed to notice a tampered baseline: {}".format(neg))

    print("")
    if FAILURES:
        print("CONSUMER-PROOF GATE: RED ({} failure(s))".format(len(FAILURES)))
        for f in FAILURES:
            print("  - {}".format(f))
        return 1
    print("CONSUMER-PROOF GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
