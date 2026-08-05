#!/usr/bin/env python3
"""wfcore.planning.test_planning -- the negative suite for the planning lane.

Run:  cd tools && PYTHONUTF8=1 python -m wfcore.planning.test_planning

WHY THE NEGATIVES ARE THE POINT
-------------------------------
A validator that accepts its own canonical example proves almost nothing -- the
example was written to pass. What proves a rail exists is a record that SHOULD be
rejected being rejected FOR THE RIGHT CODE. Rejection for the wrong reason is not
coverage: it means the rail under test may not exist, and something else happened
to fire.

Five behaviours are load-bearing enough to be tested end to end:

  * a dependency cycle is CAUGHT, and the members are named
  * the topological order is identical across input orders AND across processes
    with different hash seeds -- determinism is not "it looked stable once"
  * an UNKNOWN constraint produces an OBSERVATION step, never a mutation, and the
    control proves the same finding marked VIOLATED does produce a mutation
  * a step with side effects and an empty mutation bound is rejected
  * a plan that addresses nothing while mutating is rejected, and the control
    proves an observation-only plan with the same empty ``addresses`` is accepted

The harness itself is negative-controlled: if ``expect_rejected_for`` reported a
code the validator never emits, every negative below would be vacuous.

Exits non-zero on any failure.
"""

import json
import os
import subprocess
import sys

from .. import constraints as K
from .. import tri
from ..contracts import revision_policy as RP
from ..failure import FailureCode as C
from ..providers import base as B
from ..providers import registry as R
from . import plan as P
from . import synth as SY

FAILURES = []
PASSED = [0]


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #
def check(name, condition, detail=""):
    if condition:
        PASSED[0] += 1
    else:
        FAILURES.append("{}: {}".format(name, detail or "assertion failed"))


def all_ok(checks):
    return all(ok for (_n, ok, _d, _c) in checks)


def failing(checks):
    return [(n, d, c) for (n, ok, d, c) in checks if not ok]


def codes_of(checks):
    return {c for (_n, ok, _d, c) in checks if not ok and c}


def expect_valid(label, checks):
    check(label, all_ok(checks),
          "canonical example must pass; failures: {}".format(
              [(n, c) for (n, _d, c) in failing(checks)][:6]))


def expect_rejected_for(label, checks, code):
    got = codes_of(checks)
    check(label, code in got,
          "expected rejection code {} but got {}".format(code, sorted(got) or "NO FAILURE"))


# --------------------------------------------------------------------------- #
# fixtures (domain-neutral: engine/tooling vocabulary only, never a game's)
# --------------------------------------------------------------------------- #
AUTHORING_PROVIDER = B._example_provider_declaration(
    provider_id="editor_authoring_bridge",
    capabilities=[B.CAP_EDITOR_AUTHORING],
    requirements=[],
    outputs=["authored_asset_set", "operation_manifest"],
    evidence=["operation_manifest", "raw_observation_log"],
    cost_profile={"wall_seconds": 30.0},
)

OBSERVATION_PROVIDER = B._example_provider_declaration(
    provider_id="scene_observation_bridge",
    capabilities=[B.CAP_SCENE_OBSERVATION],
    requirements=[],
    side_effects=[B._example_side_effect(
        effect_id="eff_observation_log",
        effect_kind=B.EFFECT_EVIDENCE_ONLY,
        scope="evidence.observation_log",
        reversible=True,
        detail="emits a measurement record and changes nothing in the world")],
    determinism=B.DET_ENV_DEPENDENT,
    rollback=B.ROLLBACK_NONE,
    outputs=["observation_set", "operation_manifest"],
    evidence=["raw_observation_log", "operation_manifest"],
    cost_profile={"wall_seconds": 5.0},
)
del OBSERVATION_PROVIDER["determinism_evidence"]

# A mutating provider that cannot undo anything -- used to prove the rollback rail.
UNDOABLE_NOTHING = B._example_provider_declaration(
    provider_id="one_way_authoring_bridge",
    capabilities=[B.CAP_TERRAIN_SHAPING],
    requirements=[],
    determinism=B.DET_ENV_DEPENDENT,
    rollback=B.ROLLBACK_NONE,
    side_effects=[B._example_side_effect(reversible=False)],
    outputs=["authored_asset_set", "operation_manifest"],
    evidence=["operation_manifest"],
)
del UNDOABLE_NOTHING["determinism_evidence"]

POLICY = RP._example_revision_policy(consumer_id="consumer_placeholder")


def registry_with(*declarations):
    reg = R.CapabilityRegistry()
    for d in declarations:
        checks = reg.register(d)
        if not all_ok(checks):
            FAILURES.append("fixture {} failed registration: {}".format(
                d.get("provider_id"), [(n, c) for (n, _d, c) in failing(checks)][:6]))
    return reg


def full_registry():
    return registry_with(AUTHORING_PROVIDER, OBSERVATION_PROVIDER, UNDOABLE_NOTHING)


# --------------------------------------------------------------------------- #
# 0. the harness must be able to fail
# --------------------------------------------------------------------------- #
def test_harness_negative_control():
    good = P.validate_plan(P._example_plan(), strict=True)
    check("harness.canonical_plan_emits_no_codes", not codes_of(good),
          "canonical plan produced codes {}; failures {}".format(
              sorted(codes_of(good)), [(n, c) for (n, _d, c) in failing(good)][:6]))

    broken = P.validate_plan(P._example_plan(steps=[]))
    got = codes_of(broken)
    check("harness.detects_a_real_rejection", C.CORE_PLAN_INVALID in got,
          "expected WF1236 for an empty plan, got {}".format(sorted(got)))
    check("harness.does_not_report_a_code_nobody_emitted",
          C.CORE_DELTA_OUT_OF_BOUNDS not in got,
          "codes_of() reported a code the plan validator never emits: {}".format(
              sorted(got)))
    check("harness.expect_rejected_for_can_discriminate",
          C.CORE_PLAN_DEPENDENCY_CYCLE not in got,
          "an empty plan must not report a dependency cycle; got {}".format(sorted(got)))


# --------------------------------------------------------------------------- #
# 1. validate_plan_step
# --------------------------------------------------------------------------- #
def test_plan_step_validator():
    expect_valid("step.canonical_valid",
                 P.validate_plan_step(P._example_plan_step(), strict=True))
    expect_valid("step.canonical_observation_valid",
                 P.validate_plan_step(P._example_observation_step(), strict=True))
    expect_valid("step.canonical_valid_against_its_provider_and_policy",
                 P.validate_plan_step(P._example_plan_step(), strict=True,
                                      declaration=AUTHORING_PROVIDER, policy=POLICY))

    # REQUIRED: side effects with an empty mutation bound.
    expect_rejected_for(
        "step.bad.mutation_with_empty_bound",
        P.validate_plan_step(P._example_plan_step(expected_changed_packages=[],
                                                  expected_changed_actors=[])),
        C.CORE_PLAN_STEP_INVALID)
    # ... and the control: the SAME empty bound is fine when nothing is mutated.
    expect_valid("step.control.empty_bound_is_legal_for_an_observation",
                 P.validate_plan_step(P._example_observation_step(), strict=True))

    expect_rejected_for(
        "step.bad.provider_named_without_a_selection",
        P.validate_plan_step(P._example_plan_step(selection=None)),
        C.CORE_PLAN_STEP_INVALID)

    expect_rejected_for(
        "step.bad.selection_names_a_different_provider",
        P.validate_plan_step(P._example_plan_step(
            selection=P._example_selection(selected_provider="some_other_bridge"))),
        C.CORE_PLAN_STEP_INVALID)

    expect_rejected_for(
        "step.bad.no_side_effects_declared",
        P.validate_plan_step(P._example_plan_step(allowed_side_effects=[])),
        C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED)

    expect_rejected_for(
        "step.bad.side_effect_outside_provider_declaration",
        P.validate_plan_step(P._example_plan_step(
            allowed_side_effects=["mutates_persistent_asset", "consumes_network"]),
            declaration=AUTHORING_PROVIDER),
        C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED)

    expect_rejected_for(
        "step.bad.evidence_the_provider_cannot_emit",
        P.validate_plan_step(P._example_plan_step(
            evidence_requirements=["a_proof_this_provider_never_emits"]),
            declaration=AUTHORING_PROVIDER),
        C.CORE_PLAN_STEP_INVALID)

    expect_rejected_for(
        "step.bad.requires_no_evidence_at_all",
        P.validate_plan_step(P._example_plan_step(evidence_requirements=[])),
        C.CORE_PLAN_STEP_INVALID)

    expect_rejected_for(
        "step.bad.no_postcondition",
        P.validate_plan_step(P._example_plan_step(postconditions=[])),
        C.CORE_PLAN_STEP_INVALID)

    expect_rejected_for(
        "step.bad.capability_outside_vocabulary",
        P.validate_plan_step(P._example_plan_step(capability="make_it_look_nice")),
        C.CORE_PROVIDER_CAPABILITY_UNKNOWN)

    expect_rejected_for(
        "step.bad.observation_step_claims_a_bound",
        P.validate_plan_step(P._example_observation_step(
            expected_changed_packages=["content_root/placeholder_package_a"])),
        C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED)

    expect_rejected_for(
        "step.bad.mutation_declares_no_mutation_kind",
        P.validate_plan_step(P._example_plan_step(mutation_kinds=[])),
        C.CORE_MUTATION_NOT_PERMITTED)

    expect_rejected_for(
        "step.bad.mutation_kind_not_permitted_by_policy",
        P.validate_plan_step(P._example_plan_step(mutation_kinds=["remove_geometry"]),
                             policy=POLICY),
        C.CORE_MUTATION_NOT_PERMITTED)

    expect_rejected_for(
        "step.bad.bound_touches_protected_content",
        P.validate_plan_step(P._example_plan_step(
            expected_changed_packages=["protected_content_id_a"]), policy=POLICY),
        C.CORE_PROTECTED_CONTENT_TOUCHED)

    expect_rejected_for(
        "step.bad.bound_touches_inside_protected_content",
        P.validate_plan_step(P._example_plan_step(
            expected_changed_actors=["protected_content_id_a.placeholder_entity_7"],
            expected_changed_packages=[]), policy=POLICY),
        C.CORE_PROTECTED_CONTENT_TOUCHED)

    expect_rejected_for(
        "step.bad.rollback_required_but_provider_cannot",
        P.validate_plan_step(P._example_plan_step(
            rollback=P._example_step_rollback(provider_rollback="none"))),
        C.CORE_PLAN_NO_ROLLBACK)

    expect_rejected_for(
        "step.bad.rollback_claim_contradicts_the_declaration",
        P.validate_plan_step(P._example_plan_step(
            rollback=P._example_step_rollback(provider_rollback="compensating")),
            declaration=AUTHORING_PROVIDER),
        C.CORE_PLAN_NO_ROLLBACK)

    expect_rejected_for(
        "step.bad.depends_on_itself",
        P.validate_plan_step(P._example_plan_step(
            depends_on=["step_revise_c_placeholder_invariant"])),
        C.CORE_PLAN_DEPENDENCY_CYCLE)


# --------------------------------------------------------------------------- #
# 2. fallback policy
# --------------------------------------------------------------------------- #
def test_fallback_validator():
    expect_valid("fallback.canonical_valid",
                 P.validate_fallback_policy(P._example_fallback_policy(), strict=True))

    expect_rejected_for(
        "fallback.bad.unknown_policy",
        P.validate_fallback_policy({"on_failure": "hope_for_the_best"}),
        C.CORE_PLAN_FALLBACK_INVALID)

    expect_rejected_for(
        "fallback.bad.reselect_without_attempt_ceiling",
        P.validate_fallback_policy({"on_failure": P.FALLBACK_RESELECT_PROVIDER}),
        C.CORE_PLAN_FALLBACK_INVALID)

    expect_valid("fallback.reselect_with_ceiling_is_valid",
                 P.validate_fallback_policy({"on_failure": P.FALLBACK_RESELECT_PROVIDER,
                                             "max_attempts": 2}, strict=True))

    expect_rejected_for(
        "fallback.bad.not_an_object",
        P.validate_fallback_policy("abort"),
        C.CORE_PLAN_FALLBACK_INVALID)

    # plan-level coherence: skipping a step other steps depend on
    observe = P._example_observation_step(
        fallback_policy={"on_failure": P.FALLBACK_SKIP_STEP})
    revise = P._example_plan_step(depends_on=[observe["step_id"]])
    expect_rejected_for(
        "fallback.bad.skip_a_step_others_depend_on",
        P.validate_plan(P._example_plan(steps=[observe, revise])),
        C.CORE_PLAN_FALLBACK_INVALID)

    expect_rejected_for(
        "fallback.bad.skip_a_mutating_step",
        P.validate_plan(P._example_plan(steps=[P._example_plan_step(
            fallback_policy={"on_failure": P.FALLBACK_SKIP_STEP})])),
        C.CORE_PLAN_FALLBACK_INVALID)


# --------------------------------------------------------------------------- #
# 3. validate_plan
# --------------------------------------------------------------------------- #
def test_plan_validator():
    expect_valid("plan.canonical_valid", P.validate_plan(P._example_plan(), strict=True))
    expect_valid("plan.canonical_valid_against_registry_and_policy",
                 P.validate_plan(P._example_plan(), strict=True,
                                 registry=full_registry(), policy=POLICY))

    expect_rejected_for("plan.bad.no_steps",
                        P.validate_plan(P._example_plan(steps=[])),
                        C.CORE_PLAN_INVALID)

    # REQUIRED: a plan that addresses nothing while mutating.
    expect_rejected_for(
        "plan.bad.addresses_nothing",
        P.validate_plan(P._example_plan(addresses=[])),
        C.CORE_PLAN_ADDRESSES_NOTHING)
    # ... control: the SAME empty addresses is legal for an observation-only plan,
    # so the rail is firing on mutation-without-purpose, not on emptiness.
    expect_valid("plan.control.observation_only_plan_may_address_nothing",
                 P.validate_plan(P._example_plan(
                     steps=[P._example_observation_step()], addresses=[]), strict=True))

    expect_rejected_for(
        "plan.bad.schema_version_wrong",
        P.validate_plan(P._example_plan(schema_version="wf.core.plan.v0")),
        C.CORE_PLAN_INVALID)

    expect_rejected_for(
        "plan.bad.dangling_dependency",
        P.validate_plan(P._example_plan(steps=[
            P._example_plan_step(depends_on=["step_that_does_not_exist"])])),
        C.CORE_PLAN_INVALID)

    expect_rejected_for(
        "plan.bad.duplicate_step_ids",
        P.validate_plan(P._example_plan(steps=[P._example_plan_step(),
                                               P._example_plan_step()])),
        C.CORE_PLAN_INVALID)

    expect_rejected_for(
        "plan.bad.required_rollback_with_an_unrollbackable_step",
        P.validate_plan(P._example_plan(steps=[P._example_plan_step(
            selected_provider="one_way_authoring_bridge",
            capability="terrain_shaping",
            selection=P._example_selection(
                capability="terrain_shaping",
                selected_provider="one_way_authoring_bridge"),
            mutation_kinds=["adjust_terrain_height"],
            rollback=P._example_step_rollback(rollback_required=False,
                                              rollback_granularity="none",
                                              provider_rollback="none"))])),
        C.CORE_PLAN_NO_ROLLBACK)

    expect_rejected_for(
        "plan.bad.provider_not_registered",
        P.validate_plan(P._example_plan(steps=[P._example_plan_step(
            selected_provider="ghost_bridge",
            selection=P._example_selection(selected_provider="ghost_bridge"))]),
            registry=full_registry()),
        C.CORE_NO_PROVIDER_FOR_CAPABILITY)

    # analysis-aware: addressing something that is NOT violated is the exact
    # inversion this lane exists to prevent.
    analysis = SY._example_analysis()
    expect_rejected_for(
        "plan.bad.addresses_an_unknown_constraint",
        P.validate_plan(P._example_plan(addresses=["c_placeholder_unknown"]),
                        analysis=analysis),
        C.CORE_PLAN_ADDRESSES_NOTHING)
    expect_rejected_for(
        "plan.bad.addresses_a_constraint_the_analysis_never_saw",
        P.validate_plan(P._example_plan(addresses=["c_never_evaluated"]),
                        analysis=analysis),
        C.CORE_PLAN_ADDRESSES_NOTHING)
    expect_valid("plan.control.addresses_a_violated_constraint",
                 P.validate_plan(P._example_plan(), strict=True, analysis=analysis))


# --------------------------------------------------------------------------- #
# 4. REQUIRED: dependency cycles are caught and named
# --------------------------------------------------------------------------- #
def test_dependency_cycle_is_caught():
    a = P._example_plan_step(step_id="step_a", depends_on=["step_b"])
    b = P._example_plan_step(step_id="step_b", depends_on=["step_a"])
    cyclic = P._example_plan(steps=[a, b])

    order, cycle = P.topological_order(cyclic)
    check("cycle.no_order_exists", order == [], "order={}".format(order))
    check("cycle.members_are_named", cycle == ["step_a", "step_b"],
          "cycle={}".format(cycle))
    expect_rejected_for("cycle.plan_is_rejected", P.validate_plan(cyclic),
                        C.CORE_PLAN_DEPENDENCY_CYCLE)

    # a longer cycle, and an acyclic step that must NOT be swept up in it
    c1 = P._example_plan_step(step_id="step_c1", depends_on=["step_c3"])
    c2 = P._example_plan_step(step_id="step_c2", depends_on=["step_c1"])
    c3 = P._example_plan_step(step_id="step_c3", depends_on=["step_c2"])
    free = P._example_observation_step(step_id="step_free")
    order, cycle = P.topological_order(P._example_plan(steps=[c1, c2, c3, free]))
    check("cycle.three_step_cycle_is_detected",
          cycle == ["step_c1", "step_c2", "step_c3"], "cycle={}".format(cycle))
    check("cycle.acyclic_step_still_ordered", order == ["step_free"],
          "order={}".format(order))

    # control: the same steps without the back-edge order cleanly
    c1_ok = P._example_plan_step(step_id="step_c1", depends_on=[])
    order, cycle = P.topological_order(P._example_plan(steps=[c1_ok, c2, c3, free]))
    check("cycle.control_acyclic_has_full_order",
          cycle == [] and order == ["step_c1", "step_free", "step_c2", "step_c3"],
          "order={} cycle={}".format(order, cycle))


# --------------------------------------------------------------------------- #
# 5. REQUIRED: the topological order is deterministic
# --------------------------------------------------------------------------- #
_DETERMINISM_SNIPPET = """
import json
from wfcore.planning import plan as P

steps = []
for i in range(12):
    s = P._example_observation_step(step_id="step_obs_{:02d}".format(i))
    s["depends_on"] = ["step_obs_{:02d}".format(j) for j in range(i % 4)]
    steps.append(s)
steps.reverse()
order, cycle = P.topological_order(P._example_plan(steps=steps, addresses=[]))
print(json.dumps([order, cycle]))
"""


def _wide_plan(rotation=0):
    steps = []
    for i in range(12):
        s = P._example_observation_step(step_id="step_obs_{:02d}".format(i))
        s["depends_on"] = ["step_obs_{:02d}".format(j) for j in range(i % 4)]
        steps.append(s)
    rotation = rotation % len(steps)
    steps = steps[rotation:] + steps[:rotation]
    return P._example_plan(steps=steps, addresses=[])


def test_topological_order_is_deterministic():
    baseline, cycle = P.topological_order(_wide_plan(0))
    check("determinism.baseline_is_acyclic", cycle == [], "cycle={}".format(cycle))
    check("determinism.every_step_is_ordered", len(baseline) == 12,
          "order={}".format(baseline))

    for rotation in range(1, 12):
        order, _ = P.topological_order(_wide_plan(rotation))
        check("determinism.authored_order_is_not_observable[{}]".format(rotation),
              order == baseline,
              "rotation {} gave {} but baseline is {}".format(rotation, order, baseline))

    reverse_order, _ = P.topological_order(
        P._example_plan(steps=list(reversed(_wide_plan(0)["steps"])), addresses=[]))
    check("determinism.reversed_input_gives_the_same_order", reverse_order == baseline,
          "reversed={} baseline={}".format(reverse_order, baseline))

    for _ in range(5):
        again, _ = P.topological_order(_wide_plan(0))
        check("determinism.repeated_calls_agree", again == baseline,
              "again={} baseline={}".format(again, baseline))

    # dependencies really are respected, or "deterministic" would be worthless
    positions = {sid: idx for idx, sid in enumerate(baseline)}
    ok = all(positions["step_obs_{:02d}".format(j)] < positions["step_obs_{:02d}".format(i)]
             for i in range(12) for j in range(i % 4))
    check("determinism.order_respects_every_dependency", ok,
          "order={}".format(baseline))

    # ACROSS PROCESSES: string hashing is randomised per process, so a set or dict
    # iteration leaking into the order would show up here and nowhere else.
    tools_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    outputs = []
    for seed in ("0", "1", "12345"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONUTF8"] = "1"
        proc = subprocess.run([sys.executable, "-c", _DETERMINISM_SNIPPET],
                              cwd=tools_dir, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        if proc.returncode != 0:
            check("determinism.subprocess_ran[seed={}]".format(seed), False,
                  "exit {}: {}".format(proc.returncode,
                                       proc.stderr.decode("utf-8", "replace")[-400:]))
            return
        outputs.append(proc.stdout.decode("utf-8").strip())
    check("determinism.identical_across_hash_seeds", len(set(outputs)) == 1,
          "hash seeds produced different orders: {}".format(outputs))
    check("determinism.subprocess_agrees_with_in_process",
          json.loads(outputs[0])[0] == baseline,
          "subprocess={} in-process={}".format(json.loads(outputs[0])[0], baseline))


# --------------------------------------------------------------------------- #
# 6. predicate gates -- violated is coded, unknown blocks WITHOUT a code
# --------------------------------------------------------------------------- #
def test_predicate_gates():
    step = P._example_plan_step()
    key = "engine.authoring_session_open"

    gate = P.gate_step_preconditions(step, {key: True})
    check("gate.satisfied_precondition_passes",
          gate["evaluation"] == tri.SATISFIED and not gate["failure_codes"],
          "gate={}".format(gate))

    gate = P.gate_step_preconditions(step, {key: False})
    check("gate.violated_precondition_carries_wf1239",
          gate["evaluation"] == tri.VIOLATED
          and C.CORE_PLAN_PRECONDITION_UNMET in gate["failure_codes"],
          "gate={}".format(gate))

    gate = P.gate_step_preconditions(step, {})
    check("gate.unmeasured_precondition_blocks", gate["evaluation"] == tri.UNKNOWN,
          "gate={}".format(gate))
    check("gate.unmeasured_precondition_is_not_reported_as_unmet",
          not gate["failure_codes"]
          and all(r["failure_code"] is None for r in gate["reasons"]),
          "an unmeasured precondition reported as UNMET states a defect nobody "
          "observed; gate={}".format(gate))
    check("gate.unmeasured_reason_names_the_predicate",
          any(r["predicate_id"] == "pred_authoring_session_open"
              for r in gate["reasons"]), "gate={}".format(gate))

    post = P.gate_step_postconditions(step, {"placeholder.measurable_holds": False})
    check("gate.violated_postcondition_carries_wf1240",
          C.CORE_PLAN_POSTCONDITION_UNMET in post["failure_codes"],
          "post={}".format(post))

    check("gate.empty_predicate_list_is_vacuously_satisfied",
          P.gate_step_preconditions(P._example_observation_step(), {})["evaluation"]
          == tri.SATISFIED)


# --------------------------------------------------------------------------- #
# 7. the analysis boundary is validated, not assumed
# --------------------------------------------------------------------------- #
def test_analysis_expectation_validator():
    expect_valid("analysis.canonical_valid",
                 SY.validate_analysis_expectation(SY._example_analysis(), strict=True))

    expect_rejected_for(
        "analysis.bad.evaluation_is_not_a_tri_value",
        SY.validate_analysis_expectation(SY._example_analysis(
            findings=[SY._example_finding(evaluation=False)])),
        C.CORE_PLAN_INVALID)

    expect_rejected_for(
        "analysis.bad.violated_finding_names_no_remedy_capability",
        SY.validate_analysis_expectation(SY._example_analysis(
            findings=[SY._example_finding(remedy_capability=None)])),
        C.CORE_PROVIDER_CAPABILITY_UNKNOWN)

    expect_rejected_for(
        "analysis.bad.violated_finding_names_no_mutation_bound",
        SY.validate_analysis_expectation(SY._example_analysis(
            findings=[SY._example_finding(expected_changed_packages=[],
                                          expected_changed_actors=[])])),
        C.CORE_PLAN_STEP_INVALID)

    expect_rejected_for(
        "analysis.bad.violated_finding_names_no_mutation_kind",
        SY.validate_analysis_expectation(SY._example_analysis(
            findings=[SY._example_finding(mutation_kinds=[])])),
        C.CORE_MUTATION_NOT_PERMITTED)

    expect_rejected_for(
        "analysis.bad.duplicate_constraint_ids",
        SY.validate_analysis_expectation(SY._example_analysis(
            findings=[SY._example_finding(), SY._example_finding()])),
        C.CORE_PLAN_INVALID)

    expect_rejected_for(
        "analysis.bad.observations_missing",
        SY.validate_analysis_expectation(SY._example_analysis(observations=None)),
        C.CORE_PLAN_INVALID)


# --------------------------------------------------------------------------- #
# 8. REQUIRED: an UNKNOWN produces an OBSERVATION step, never a mutation
# --------------------------------------------------------------------------- #
def test_unknown_constraint_becomes_an_observation_step():
    reg = full_registry()
    analysis = SY._example_analysis(findings=[SY._example_unknown_finding()])
    result = SY.synthesize_plan(analysis, reg, POLICY)

    check("unknown.synthesis_planned", result["outcome"] == SY.OUTCOME_PLANNED,
          "outcome={} unresolved={}".format(result["outcome"], result["unresolved"]))
    plan = result["plan"]
    check("unknown.exactly_one_step", plan and len(plan["steps"]) == 1,
          "steps={}".format(plan and [s["step_id"] for s in plan["steps"]]))
    step = plan["steps"][0]

    check("unknown.step_is_an_observation_step",
          step["step_id"] == "step_observe_c_placeholder_unknown",
          "step_id={}".format(step["step_id"]))
    check("unknown.step_mutates_nothing", not P.step_mutates(step),
          "allowed_side_effects={}".format(step["allowed_side_effects"]))
    check("unknown.step_declares_evidence_only",
          step["allowed_side_effects"] == [B.EFFECT_EVIDENCE_ONLY],
          "allowed_side_effects={}".format(step["allowed_side_effects"]))
    check("unknown.step_bound_is_empty", P.step_mutation_bound(step) == (),
          "bound={}".format(P.step_mutation_bound(step)))
    check("unknown.step_declares_no_mutation_kind", "mutation_kinds" not in step,
          "step={}".format(step))
    check("unknown.step_ran_an_observation_capability",
          step["capability"] == B.CAP_SCENE_OBSERVATION,
          "capability={}".format(step["capability"]))
    check("unknown.plan_addresses_nothing", plan["addresses"] == [],
          "addresses={}; measuring is not resolving".format(plan["addresses"]))
    check("unknown.plan_records_what_it_observes",
          plan["observes"] == ["c_placeholder_unknown"],
          "observes={}".format(plan["observes"]))
    expect_valid("unknown.plan_validates",
                 P.validate_plan(plan, strict=True, registry=reg, policy=POLICY,
                                 analysis=analysis))

    # NEGATIVE CONTROL: the same subject marked VIOLATED must produce a MUTATION
    # step. Without this, the test above would pass on a synthesiser that only
    # ever emits observation steps.
    violated = SY._example_finding(constraint_id="c_placeholder_unknown",
                                   subject="placeholder.unmeasured")
    control = SY.synthesize_plan(
        SY._example_analysis(findings=[violated]), reg, POLICY)
    check("unknown.control_synthesis_planned",
          control["outcome"] == SY.OUTCOME_PLANNED,
          "outcome={} unresolved={}".format(control["outcome"], control["unresolved"]))
    control_step = control["plan"]["steps"][0]
    check("unknown.control_violated_produces_a_mutation_step",
          P.step_mutates(control_step)
          and control_step["step_id"] == "step_revise_c_placeholder_unknown",
          "step={}".format(control_step["step_id"]))
    check("unknown.control_violated_step_has_a_bound",
          P.step_mutation_bound(control_step) != (),
          "bound={}".format(P.step_mutation_bound(control_step)))
    check("unknown.control_plan_addresses_it",
          control["plan"]["addresses"] == ["c_placeholder_unknown"],
          "addresses={}".format(control["plan"]["addresses"]))

    # and a SATISFIED finding produces no step at all
    satisfied = SY.synthesize_plan(SY._example_analysis(findings=[
        SY._example_finding(evaluation=tri.SATISFIED)]), reg, POLICY)
    check("unknown.satisfied_finding_produces_nothing",
          satisfied["outcome"] == SY.OUTCOME_NOTHING_TO_PLAN
          and satisfied["plan"] is None,
          "outcome={}".format(satisfied["outcome"]))


# --------------------------------------------------------------------------- #
# 9. synthesis end to end
# --------------------------------------------------------------------------- #
def test_synthesis_end_to_end():
    reg = full_registry()
    analysis = SY._example_analysis()
    result = SY.synthesize_plan(analysis, reg, POLICY)

    check("synth.outcome_is_planned", result["outcome"] == SY.OUTCOME_PLANNED,
          "outcome={} unresolved={}".format(result["outcome"], result["unresolved"]))
    plan = result["plan"]
    expect_valid("synth.plan_validates_against_everything",
                 P.validate_plan(plan, strict=True, registry=reg, policy=POLICY,
                                 analysis=analysis))
    check("synth.addresses_only_the_violated_constraint",
          plan["addresses"] == ["c_placeholder_invariant"],
          "addresses={}".format(plan["addresses"]))
    check("synth.observes_only_the_unknown_constraint",
          plan["observes"] == ["c_placeholder_unknown"],
          "observes={}".format(plan["observes"]))

    # provider choice went through selection and the evidence is carried
    for step in plan["steps"]:
        check("synth.step_carries_its_selection[{}]".format(step["step_id"]),
              isinstance(step.get("selection"), dict)
              and step["selection"]["selected_provider"] == step["selected_provider"]
              and step["selection"]["outcome"] == "selected",
              "selection={}".format(step.get("selection")))
    check("synth.selection_recorded_the_pool_it_chose_from",
          all(s["selection"].get("registry_snapshot") for s in plan["steps"]),
          "a selection with no registry snapshot cannot be re-checked")

    # subject-shared dependency: the revision waits for nothing here (different
    # subjects), so wire one that DOES share a subject and check the edge appears.
    shared = SY._example_analysis(findings=[
        SY._example_unknown_finding(subject="placeholder.measurable"),
        SY._example_finding()])
    wired = SY.synthesize_plan(shared, reg, POLICY)
    by_id = {s["step_id"]: s for s in wired["plan"]["steps"]}
    check("synth.revision_waits_for_the_measurement_of_its_own_subject",
          by_id["step_revise_c_placeholder_invariant"]["depends_on"]
          == ["step_observe_c_placeholder_unknown"],
          "depends_on={}".format(
              by_id["step_revise_c_placeholder_invariant"]["depends_on"]))
    order, cycle = P.topological_order(wired["plan"])
    check("synth.wired_plan_orders_measurement_first",
          cycle == [] and order[0] == "step_observe_c_placeholder_unknown",
          "order={} cycle={}".format(order, cycle))

    # synthesis does not depend on the order the analysis emitted its findings
    reordered = SY.synthesize_plan(
        SY._example_analysis(findings=list(reversed(analysis["findings"]))),
        full_registry(), POLICY)
    check("synth.finding_order_is_not_observable",
          json.dumps(reordered["plan"], sort_keys=True, default=str)
          == json.dumps(plan, sort_keys=True, default=str),
          "reordered findings produced a different plan")

    check("synth.explains_itself",
          any("step_revise_c_placeholder_invariant" in line
              for line in SY.explain_synthesis(result)),
          "lines={}".format(SY.explain_synthesis(result)))


# --------------------------------------------------------------------------- #
# 10. synthesis fails closed rather than emitting a partial plan
# --------------------------------------------------------------------------- #
def test_synthesis_fails_closed():
    reg = registry_with(OBSERVATION_PROVIDER)   # nothing can author anything

    unplannable = SY.synthesize_plan(
        SY._example_analysis(findings=[SY._example_finding()]), reg, POLICY)
    check("closed.no_provider_means_no_plan",
          unplannable["outcome"] == SY.OUTCOME_UNPLANNABLE
          and unplannable["plan"] is None,
          "outcome={} plan={}".format(unplannable["outcome"], unplannable["plan"]))
    check("closed.names_the_missing_capability",
          C.CORE_NO_PROVIDER_FOR_CAPABILITY in unplannable["failure_codes"],
          "codes={}".format(unplannable["failure_codes"]))

    # a plannable finding alongside an unplannable one must NOT yield a partial plan
    mixed = SY.synthesize_plan(SY._example_analysis(findings=[
        SY._example_unknown_finding(), SY._example_finding()]), reg, POLICY)
    check("closed.partial_plan_is_refused",
          mixed["outcome"] == SY.OUTCOME_UNPLANNABLE and mixed["plan"] is None,
          "outcome={} plan steps={}".format(
              mixed["outcome"],
              mixed["plan"] and [s["step_id"] for s in mixed["plan"]["steps"]]))

    # a mutation the consumer never permitted cannot be planned
    forbidden = SY.synthesize_plan(SY._example_analysis(findings=[
        SY._example_finding(mutation_kinds=["remove_geometry"])]),
        full_registry(), POLICY)
    check("closed.unpermitted_mutation_is_not_planned",
          forbidden["outcome"] == SY.OUTCOME_UNPLANNABLE
          and C.CORE_MUTATION_NOT_PERMITTED in forbidden["failure_codes"],
          "outcome={} codes={}".format(forbidden["outcome"], forbidden["failure_codes"]))

    # protected content is not planned around silently either
    protected = SY.synthesize_plan(SY._example_analysis(findings=[
        SY._example_finding(expected_changed_packages=["protected_content_id_a"],
                            expected_changed_actors=[])]),
        full_registry(), POLICY)
    check("closed.protected_content_is_not_planned",
          protected["outcome"] == SY.OUTCOME_UNPLANNABLE
          and C.CORE_PROTECTED_CONTENT_TOUCHED in protected["failure_codes"],
          "outcome={} codes={}".format(protected["outcome"], protected["failure_codes"]))

    # an observation whose only candidate MUTATES is ineligible -- measuring must
    # not change the thing being measured
    mutating_only = registry_with(AUTHORING_PROVIDER)
    no_observer = SY.synthesize_plan(SY._example_analysis(findings=[
        SY._example_unknown_finding(measure_capability=B.CAP_EDITOR_AUTHORING)]),
        mutating_only, POLICY)
    check("closed.a_mutating_provider_cannot_serve_an_observation",
          no_observer["outcome"] == SY.OUTCOME_UNPLANNABLE,
          "outcome={} plan={}".format(no_observer["outcome"], no_observer["plan"]))

    # a malformed analysis is reported at the boundary, not planned around
    malformed = SY.synthesize_plan({"analysis_id": "analysis_placeholder"},
                                   full_registry(), POLICY)
    check("closed.malformed_analysis_is_refused",
          malformed["outcome"] == SY.OUTCOME_UNPLANNABLE
          and C.CORE_PLAN_INVALID in malformed["failure_codes"],
          "outcome={} codes={}".format(malformed["outcome"], malformed["failure_codes"]))

    # a provider whose requirement was never measured is UNKNOWN, so unselectable
    needs_measurement = B._example_provider_declaration(
        provider_id="gated_authoring_bridge",
        capabilities=[B.CAP_EDITOR_AUTHORING],
        outputs=["authored_asset_set", "operation_manifest"],
        evidence=["operation_manifest"])
    gated = SY.synthesize_plan(SY._example_analysis(findings=[SY._example_finding()]),
                               registry_with(needs_measurement), POLICY)
    check("closed.unmeasured_provider_requirement_blocks_planning",
          gated["outcome"] == SY.OUTCOME_UNPLANNABLE,
          "outcome={} plan={}".format(gated["outcome"], gated["plan"]))


# --------------------------------------------------------------------------- #
# 11. non-load-bearing findings never author a change
# --------------------------------------------------------------------------- #
def test_non_load_bearing_findings_author_nothing():
    reg = full_registry()
    for klass in K.SCORING_CLASSES:
        finding = SY._example_finding(constraint_id="c_placeholder_preference",
                                      constraint_class=klass)
        if klass == K.OPTIMIZATION_TARGET:
            finding["detail"] = "a direction to optimise along, with no pass/fail"
        check("scoring.{}_produces_no_step".format(klass),
              SY.finding_step_kind(finding) is None,
              "kind={}".format(SY.finding_step_kind(finding)))
        result = SY.synthesize_plan(SY._example_analysis(findings=[finding]),
                                    reg, POLICY)
        check("scoring.{}_yields_nothing_to_plan".format(klass),
              result["outcome"] == SY.OUTCOME_NOTHING_TO_PLAN,
              "outcome={}".format(result["outcome"]))

    check("scoring.declared_unknown_is_load_bearing_and_measured",
          SY.finding_step_kind(SY._example_unknown_finding(
              constraint_class=K.DECLARED_UNKNOWN)) == SY.STEP_KIND_OBSERVATION)


# --------------------------------------------------------------------------- #
def main():
    tests = [
        test_harness_negative_control,
        test_plan_step_validator,
        test_fallback_validator,
        test_plan_validator,
        test_dependency_cycle_is_caught,
        test_topological_order_is_deterministic,
        test_predicate_gates,
        test_analysis_expectation_validator,
        test_unknown_constraint_becomes_an_observation_step,
        test_synthesis_end_to_end,
        test_synthesis_fails_closed,
        test_non_load_bearing_findings_author_nothing,
    ]
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a skip
            FAILURES.append("{} raised {}: {}".format(fn.__name__, type(exc).__name__, exc))
        print("  ran {}".format(fn.__name__))

    print("")
    print("wfcore.planning: {} assertion(s) passed, {} failed".format(
        PASSED[0], len(FAILURES)))
    for f in FAILURES:
        print("  FAIL {}".format(f))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
