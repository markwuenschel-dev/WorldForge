#!/usr/bin/env python3
"""wfcore.providers.test_providers -- the negative suite for the provider lane.

Run:  cd tools && PYTHONUTF8=1 python -m wfcore.providers.test_providers

WHY THE NEGATIVES ARE THE POINT
-------------------------------
A validator that accepts its own canonical example proves almost nothing -- the
example was written to pass. What proves a rail exists is a record that SHOULD be
rejected being rejected FOR THE RIGHT CODE. Rejection for the wrong reason is not
coverage: it means the rail under test may not exist at all, and something else
happened to fire.

Three behaviours are load-bearing enough to be tested end to end rather than
through a validator:

  * two equally-ranked providers must produce WF1229, NOT a pick
  * a hard invariant must eliminate the HIGHEST-SCORING provider (proved by
    running the same request with and without the invariant, so the test cannot
    pass by the provider simply scoring badly)
  * an unevaluable requirement must leave a provider unselected AND unaccused

Exits non-zero on any failure.
"""

import sys

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from . import base as B
from . import registry as R
from . import selection as S

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
def decl(provider_id, **over):
    d = B._example_provider_declaration(provider_id=provider_id)
    d.update(over)
    return d


FAST_NONDETERMINISTIC = decl(
    "fast_nondeterministic_bridge",
    capabilities=[B.CAP_MATERIAL_AUTHORING],
    requirements=[],
    determinism=B.DET_NONDETERMINISTIC,
    rollback=B.ROLLBACK_NONE,
    side_effects=[B._example_side_effect(reversible=False)],
    cost_profile={"wall_seconds": 5.0},
)
del FAST_NONDETERMINISTIC["determinism_evidence"]

SLOW_SEEDED = decl(
    "slow_seeded_bridge",
    capabilities=[B.CAP_MATERIAL_AUTHORING],
    requirements=[],
    determinism=B.DET_SEEDED,
    rollback=B.ROLLBACK_TRANSACTIONAL,
    cost_profile={"wall_seconds": 60.0},
)

TWIN_A = decl("twin_bridge_a", capabilities=[B.CAP_MATERIAL_AUTHORING],
              requirements=[], cost_profile={"wall_seconds": 10.0})
TWIN_B = decl("twin_bridge_b", capabilities=[B.CAP_MATERIAL_AUTHORING],
              requirements=[], cost_profile={"wall_seconds": 10.0})

UNMEASURED = decl(
    "external_tool_bridge",
    capabilities=[B.CAP_MATERIAL_AUTHORING],
    requirements=[B._example_requirement(
        requirement_id="req_external_tool_reachable",
        requirement_kind=B.REQ_EXTERNAL_TOOL,
        subject="tooling.external_synthesis_host",
        detail="the external synthesis host must be installed and reachable",
        observation_key="tooling.external_synthesis_host_reachable")],
)


def registry_with(*declarations):
    reg = R.CapabilityRegistry()
    for d in declarations:
        checks = reg.register(d)
        if not all_ok(checks):
            FAILURES.append("fixture {} failed registration: {}".format(
                d.get("provider_id"), [(n, c) for (n, _d, c) in failing(checks)][:6]))
    return reg


def request(**over):
    r = {
        "request_id": "req_fixture",
        "capability": B.CAP_MATERIAL_AUTHORING,
        "required_outputs": ["authored_asset_set"],
        "constraints": [],
        "observations": {},
        "schema_version": S.RT_SELECTION_REQUEST,
    }
    r.update(over)
    return r


def constraint(cid, klass, subject, **over):
    c = K._example_constraint(constraint_id=cid, constraint_class=klass,
                              subject=subject, detail="fixture constraint")
    c.update(over)
    return c


# --------------------------------------------------------------------------- #
# 1. validate_provider_declaration
# --------------------------------------------------------------------------- #
def test_provider_declaration():
    expect_valid("declaration.canonical_valid",
                 B.validate_provider_declaration(B._example_provider_declaration(),
                                                 strict=True))

    expect_rejected_for(
        "declaration.bad.no_side_effects_declared",
        B.validate_provider_declaration(B._example_provider_declaration(side_effects=[])),
        C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED)

    expect_rejected_for(
        "declaration.bad.no_limitations_declared",
        B.validate_provider_declaration(B._example_provider_declaration(limitations=[])),
        C.CORE_PROVIDER_DECLARATION_INVALID)

    unproven = B._example_provider_declaration()
    del unproven["determinism_evidence"]
    expect_rejected_for("declaration.bad.determinism_claimed_without_proof",
                        B.validate_provider_declaration(unproven),
                        C.CORE_PROVIDER_DETERMINISM_UNPROVEN)

    expect_rejected_for(
        "declaration.bad.transactional_rollback_over_irreversible_effect",
        B.validate_provider_declaration(B._example_provider_declaration(
            rollback=B.ROLLBACK_TRANSACTIONAL,
            side_effects=[B._example_side_effect(reversible=False)])),
        C.CORE_PROVIDER_ROLLBACK_UNSUPPORTED)

    expect_rejected_for(
        "declaration.bad.reversible_effect_with_no_rollback_mechanism",
        B.validate_provider_declaration(B._example_provider_declaration(
            rollback=B.ROLLBACK_NONE,
            side_effects=[B._example_side_effect(reversible=True)])),
        C.CORE_PROVIDER_ROLLBACK_UNSUPPORTED)

    expect_rejected_for(
        "declaration.bad.capability_outside_vocabulary",
        B.validate_provider_declaration(B._example_provider_declaration(
            capabilities=["make_it_look_nice"])),
        C.CORE_PROVIDER_CAPABILITY_UNKNOWN)

    expect_rejected_for(
        "declaration.bad.unsigned_universality_claim",
        B.validate_provider_declaration(B._example_provider_declaration(
            limitations=[B._example_limitation(limitation_kind=B.LIM_NONE_KNOWN,
                                               detail="no known limitation")])),
        C.CORE_PROVIDER_DECLARATION_INVALID)

    expect_rejected_for(
        "declaration.bad.side_effect_reversibility_omitted",
        B.validate_provider_declaration(B._example_provider_declaration(
            side_effects=[{"effect_id": "eff_x", "effect_kind": B.EFFECT_FILESYSTEM,
                           "scope": "workspace.scratch"}])),
        C.CORE_PROVIDER_ROLLBACK_UNSUPPORTED)


# --------------------------------------------------------------------------- #
# 2. requirement evaluation (tri)
# --------------------------------------------------------------------------- #
def test_requirement_evaluation():
    req = B._example_requirement()
    check("requirement.absent_observation_is_unknown",
          B.evaluate_requirement(req, {}) == tri.UNKNOWN)
    check("requirement.false_observation_is_violated",
          B.evaluate_requirement(req, {"engine.authoring_session_open": False}) == tri.VIOLATED)
    check("requirement.true_observation_is_satisfied",
          B.evaluate_requirement(req, {"engine.authoring_session_open": True}) == tri.SATISFIED)
    check("requirement.uninterpretable_observation_is_unknown",
          B.evaluate_requirement(req, {"engine.authoring_session_open": "maybe"}) == tri.UNKNOWN)

    value, trace = B.evaluate_requirements(UNMEASURED, {})
    check("requirement.fold_is_unknown_when_unmeasured", value == tri.UNKNOWN)
    check("requirement.trace_names_the_unmeasured_requirement",
          any(t["requirement_id"] == "req_external_tool_reachable"
              and t["evaluation"] == tri.UNKNOWN for t in trace),
          "trace={}".format(trace))
    value, _ = B.evaluate_requirements(SLOW_SEEDED, {})
    check("requirement.no_requirements_folds_satisfied", value == tri.SATISFIED)


# --------------------------------------------------------------------------- #
# 3. registry
# --------------------------------------------------------------------------- #
def test_registry():
    reg = R.CapabilityRegistry()
    expect_valid("registry.register_valid", reg.register(B._example_provider_declaration()))
    check("registry.valid_declaration_is_stored", "editor_authoring_bridge" in reg)

    dupe = reg.register(B._example_provider_declaration())
    expect_rejected_for("registry.duplicate_provider_id_rejected", dupe,
                        C.CORE_PROVIDER_DECLARATION_INVALID)
    check("registry.duplicate_did_not_grow_the_registry", len(reg) == 1)

    bad = reg.register(B._example_provider_declaration(provider_id="broken_bridge",
                                                       limitations=[]))
    check("registry.invalid_declaration_is_not_stored",
          "broken_bridge" not in reg and not all_ok(bad))

    expect_rejected_for("registry.unknown_capability_word",
                        reg.check_capability("make_it_look_nice"),
                        C.CORE_PROVIDER_CAPABILITY_UNKNOWN)
    expect_rejected_for("registry.capability_with_no_provider",
                        reg.check_capability(B.CAP_GEOMETRY_SYNTHESIS),
                        C.CORE_NO_PROVIDER_FOR_CAPABILITY)

    reg2 = registry_with(TWIN_A, TWIN_B, SLOW_SEEDED)
    check("registry.lookup_is_sorted_not_insertion_ordered",
          [d["provider_id"] for d in reg2.providers_for(B.CAP_MATERIAL_AUTHORING)]
          == ["slow_seeded_bridge", "twin_bridge_a", "twin_bridge_b"])
    check("registry.collision_is_reported",
          reg2.collisions().get(B.CAP_MATERIAL_AUTHORING)
          == ("slow_seeded_bridge", "twin_bridge_a", "twin_bridge_b"),
          "collisions={}".format(reg2.collisions()))
    check("registry.uncovered_capability_listed",
          reg2.uncovered([B.CAP_MATERIAL_AUTHORING, B.CAP_GEOMETRY_SYNTHESIS])
          == (B.CAP_GEOMETRY_SYNTHESIS,))
    expect_valid("registry.live_snapshot_validates",
                 R.validate_registry_snapshot(reg2.snapshot(), strict=True))


# --------------------------------------------------------------------------- #
# 4. validate_registry_snapshot
# --------------------------------------------------------------------------- #
def test_registry_snapshot_validator():
    expect_valid("snapshot.canonical_valid",
                 R.validate_registry_snapshot(R._example_registry_snapshot(), strict=True))

    expect_rejected_for(
        "snapshot.bad.collision_under_reported",
        R.validate_registry_snapshot(R._example_registry_snapshot(collisions={})),
        C.CORE_PROVIDER_SELECTION_AMBIGUOUS)

    expect_rejected_for(
        "snapshot.bad.capability_outside_vocabulary",
        R.validate_registry_snapshot(R._example_registry_snapshot(
            capability_index={"make_it_look_nice": ["editor_authoring_bridge"]},
            collisions={})),
        C.CORE_PROVIDER_CAPABILITY_UNKNOWN)

    expect_rejected_for(
        "snapshot.bad.index_entry_names_no_provider",
        R.validate_registry_snapshot(R._example_registry_snapshot(
            capability_index={"editor_authoring": []}, collisions={})),
        C.CORE_NO_PROVIDER_FOR_CAPABILITY)

    expect_rejected_for(
        "snapshot.bad.index_references_unregistered_provider",
        R.validate_registry_snapshot(R._example_registry_snapshot(
            capability_index={"editor_authoring": ["ghost_bridge"]}, collisions={})),
        C.CORE_PROVIDER_DECLARATION_INVALID)


# --------------------------------------------------------------------------- #
# 5. validate_selection_request
# --------------------------------------------------------------------------- #
def test_selection_request_validator():
    expect_valid("request.canonical_valid",
                 S.validate_selection_request(S._example_selection_request(), strict=True))

    expect_rejected_for(
        "request.bad.names_a_provider_directly",
        S.validate_selection_request(S._example_selection_request(
            provider_id="editor_authoring_bridge")),
        C.CORE_PROVIDER_DECLARATION_INVALID)

    expect_rejected_for(
        "request.bad.capability_outside_vocabulary",
        S.validate_selection_request(S._example_selection_request(
            capability="make_it_look_nice")),
        C.CORE_PROVIDER_CAPABILITY_UNKNOWN)

    expect_rejected_for(
        "request.bad.states_no_required_result",
        S.validate_selection_request(S._example_selection_request(required_outputs=[])),
        C.CORE_PROVIDER_DECLARATION_INVALID)

    expect_rejected_for(
        "request.bad.tiebreak_by_provider_name",
        S.validate_selection_request(S._example_selection_request(
            tiebreak_criteria=["editor_authoring_bridge"])),
        C.CORE_PROVIDER_DECLARATION_INVALID)


# --------------------------------------------------------------------------- #
# 6. validate_selection_result
# --------------------------------------------------------------------------- #
def test_selection_result_validator():
    expect_valid("result.canonical_valid",
                 S.validate_selection_result(S._example_selection_result(), strict=True))

    expect_rejected_for(
        "result.bad.winner_merely_tied_with_no_tiebreak",
        S.validate_selection_result(S._example_selection_result(
            ranking=[{"provider_id": "twin_bridge_a", "score": 1.0},
                     {"provider_id": "twin_bridge_b", "score": 1.0}])),
        C.CORE_PROVIDER_SELECTION_AMBIGUOUS)

    expect_rejected_for(
        "result.bad.ambiguous_without_its_code",
        S.validate_selection_result(S._example_selection_result(
            outcome=S.OUTCOME_AMBIGUOUS, selected_provider=None,
            ambiguous_between=["twin_bridge_a"], failure_codes=[])),
        C.CORE_PROVIDER_SELECTION_AMBIGUOUS)

    expect_rejected_for(
        "result.bad.unexplained_rejection",
        S.validate_selection_result(S._example_selection_result(
            considered=[{"provider_id": "runtime_authoring_bridge",
                         "status": S.STATUS_REJECTED, "eligibility": tri.VIOLATED,
                         "score": None, "reasons": []}])),
        C.CORE_PROVIDER_DECLARATION_INVALID)

    expect_rejected_for(
        "result.bad.unknown_reported_as_requirement_failure",
        S.validate_selection_result(S._example_selection_result(
            considered=[{"provider_id": "external_tool_bridge",
                         "status": S.STATUS_UNKNOWN, "eligibility": tri.UNKNOWN,
                         "score": None,
                         "reasons": [{"stage": S.STAGE_REQUIREMENTS,
                                      "subject": "tooling.external_synthesis_host",
                                      "evaluation": tri.UNKNOWN,
                                      "detail": "never measured",
                                      "failure_code": C.CORE_PROVIDER_REQUIREMENT_UNMET}]}])),
        C.CORE_PROVIDER_REQUIREMENT_UNMET)

    expect_rejected_for(
        "result.bad.selected_a_provider_with_unknown_eligibility",
        S.validate_selection_result(S._example_selection_result(
            selected_provider="external_tool_bridge",
            considered=[{"provider_id": "external_tool_bridge",
                         "status": S.STATUS_SELECTED, "eligibility": tri.UNKNOWN,
                         "score": 1.0, "reasons": []}])),
        C.CORE_NO_PROVIDER_FOR_CAPABILITY)

    expect_rejected_for(
        "result.bad.unselected_outcome_carries_no_reason",
        S.validate_selection_result(S._example_selection_result(
            outcome=S.OUTCOME_NO_ELIGIBLE_CANDIDATE, selected_provider=None,
            failure_codes=[])),
        C.CORE_PROVIDER_DECLARATION_INVALID)


# --------------------------------------------------------------------------- #
# 7. REQUIRED: a tie is WF1229, never an arbitrary pick
# --------------------------------------------------------------------------- #
def test_tie_is_ambiguous_not_arbitrary():
    reg = registry_with(TWIN_A, TWIN_B)
    req = request(constraints=[
        constraint("c_prefer_transactional", K.SOFT_PREFERENCE,
                   S.FACET_ROLLBACK_TRANSACTIONAL, weight=1.0)])
    result = S.select_provider(reg, req)

    check("tie.outcome_is_ambiguous", result["outcome"] == S.OUTCOME_AMBIGUOUS,
          "outcome={} selected={}".format(result["outcome"], result["selected_provider"]))
    check("tie.nothing_was_picked", result["selected_provider"] is None,
          "selected={}".format(result["selected_provider"]))
    check("tie.both_are_named", result["ambiguous_between"] == ["twin_bridge_a", "twin_bridge_b"],
          "ambiguous_between={}".format(result["ambiguous_between"]))
    check("tie.carries_the_ambiguity_code",
          C.CORE_PROVIDER_SELECTION_AMBIGUOUS in result["failure_codes"],
          "codes={}".format(result["failure_codes"]))
    check("tie.scores_really_were_equal",
          len({r["score"] for r in result["ranking"]}) == 1,
          "ranking={}".format(result["ranking"]))
    expect_valid("tie.result_validates", S.validate_selection_result(result, strict=True))

    # ... and a DECLARED tiebreak criterion resolves it without naming a provider.
    twin_b_transactional = dict(TWIN_B)
    twin_b_transactional["rollback"] = B.ROLLBACK_COMPENSATING
    reg2 = registry_with(TWIN_A, twin_b_transactional)
    req2 = request(constraints=[
        constraint("c_prefer_seeded", K.SOFT_PREFERENCE, S.FACET_DETERMINISM_SEEDED,
                   weight=1.0)],
        tiebreak_criteria=[S.FACET_ROLLBACK_TRANSACTIONAL])
    result2 = S.select_provider(reg2, req2)
    check("tie.declared_criterion_resolves_it",
          result2["outcome"] == S.OUTCOME_SELECTED
          and result2["selected_provider"] == "twin_bridge_a",
          "outcome={} selected={} applied={}".format(
              result2["outcome"], result2["selected_provider"], result2["tiebreak_applied"]))
    check("tie.tiebreak_is_recorded",
          result2["tiebreak_applied"] == [S.FACET_ROLLBACK_TRANSACTIONAL],
          "applied={}".format(result2["tiebreak_applied"]))
    expect_valid("tie.resolved_result_validates",
                 S.validate_selection_result(result2, strict=True))


# --------------------------------------------------------------------------- #
# 8. REQUIRED: a hard invariant filters out the HIGHEST-SCORING provider
# --------------------------------------------------------------------------- #
def test_hard_invariant_beats_score():
    reg = registry_with(FAST_NONDETERMINISTIC, SLOW_SEEDED)
    cheapest = constraint("c_minimise_wall_seconds", K.OPTIMIZATION_TARGET,
                          S.FACET_PREFIX_COST + "wall_seconds",
                          direction=K.MINIMIZE, weight=10.0)
    seeded = constraint("c_must_be_seeded", K.HARD_INVARIANT,
                        S.FACET_DETERMINISM_SEEDED)

    # control: with ONLY the optimisation target, the nondeterministic provider WINS.
    control = S.select_provider(reg, request(constraints=[cheapest]))
    check("hard_filter.control_highest_score_would_win",
          control["outcome"] == S.OUTCOME_SELECTED
          and control["selected_provider"] == "fast_nondeterministic_bridge",
          "control outcome={} selected={} ranking={}".format(
              control["outcome"], control["selected_provider"], control["ranking"]))

    # the real test: adding the hard invariant eliminates the top scorer.
    result = S.select_provider(reg, request(constraints=[cheapest, seeded]))
    check("hard_filter.top_scorer_is_eliminated",
          result["selected_provider"] == "slow_seeded_bridge",
          "outcome={} selected={} ranking={}".format(
              result["outcome"], result["selected_provider"], result["ranking"]))
    entries = {e["provider_id"]: e for e in result["considered"]}
    check("hard_filter.eliminated_provider_is_rejected_not_outranked",
          entries["fast_nondeterministic_bridge"]["status"] == S.STATUS_REJECTED
          and entries["fast_nondeterministic_bridge"]["eligibility"] == tri.VIOLATED,
          "entry={}".format(entries["fast_nondeterministic_bridge"]))
    check("hard_filter.rejection_names_the_invariant",
          any(r["subject"] == S.FACET_DETERMINISM_SEEDED
              and r["stage"] == S.STAGE_FILTER
              for r in entries["fast_nondeterministic_bridge"]["reasons"]),
          "reasons={}".format(entries["fast_nondeterministic_bridge"]["reasons"]))
    check("hard_filter.filtered_provider_gets_no_score",
          entries["fast_nondeterministic_bridge"]["score"] is None,
          "a filtered provider must not be ranked at all")
    expect_valid("hard_filter.result_validates",
                 S.validate_selection_result(result, strict=True))

    # a BUDGET (also load-bearing) filters rather than scores.
    budget = constraint("c_wall_seconds_budget", K.BUDGET,
                        S.FACET_PREFIX_COST + "wall_seconds", limit=10.0, unit="s")
    budgeted = S.select_provider(reg, request(constraints=[budget]))
    check("hard_filter.budget_eliminates_over_limit_provider",
          budgeted["selected_provider"] == "fast_nondeterministic_bridge",
          "outcome={} selected={}".format(budgeted["outcome"], budgeted["selected_provider"]))

    # a budget metric the provider does not declare is UNKNOWN, never "within budget".
    unmeasured_budget = constraint("c_unmeasured_budget", K.BUDGET,
                                   S.FACET_PREFIX_COST + "peak_memory_bytes",
                                   limit=1.0, unit="B")
    blocked = S.select_provider(reg, request(constraints=[unmeasured_budget]))
    check("hard_filter.unmeasured_budget_blocks_rather_than_passes",
          blocked["outcome"] == S.OUTCOME_NO_ELIGIBLE_CANDIDATE,
          "outcome={} selected={}".format(blocked["outcome"], blocked["selected_provider"]))


# --------------------------------------------------------------------------- #
# 9. REQUIRED: unknown requirement-eligibility does not select
# --------------------------------------------------------------------------- #
def test_unknown_eligibility_does_not_select():
    reg = registry_with(UNMEASURED)
    result = S.select_provider(reg, request())          # observations = {}

    check("unknown.nothing_was_selected", result["selected_provider"] is None,
          "selected={}".format(result["selected_provider"]))
    check("unknown.outcome_is_no_eligible_candidate",
          result["outcome"] == S.OUTCOME_NO_ELIGIBLE_CANDIDATE,
          "outcome={}".format(result["outcome"]))
    entry = result["considered"][0]
    check("unknown.status_is_unknown_not_rejected",
          entry["status"] == S.STATUS_UNKNOWN and entry["eligibility"] == tri.UNKNOWN,
          "entry={}".format(entry))
    check("unknown.is_not_reported_as_a_requirement_failure",
          all(r["failure_code"] != C.CORE_PROVIDER_REQUIREMENT_UNMET
              for r in entry["reasons"]),
          "reasons={}".format(entry["reasons"]))
    check("unknown.result_does_not_claim_a_requirement_was_unmet",
          C.CORE_PROVIDER_REQUIREMENT_UNMET not in result["failure_codes"],
          "codes={}".format(result["failure_codes"]))
    check("unknown.reason_names_the_unmeasured_requirement",
          any("req_external_tool_reachable" in (r["detail"] or "")
              for r in entry["reasons"]),
          "reasons={}".format(entry["reasons"]))
    expect_valid("unknown.result_validates",
                 S.validate_selection_result(result, strict=True))

    # the SAME provider, once the observation exists, is selectable...
    measured = S.select_provider(
        reg, request(observations={"tooling.external_synthesis_host_reachable": True}))
    check("unknown.becomes_selectable_once_measured",
          measured["selected_provider"] == "external_tool_bridge",
          "outcome={} selected={}".format(measured["outcome"], measured["selected_provider"]))

    # ...and a MEASURED failure is a rejection with the requirement code -- the
    # distinction unknown/violated is preserved end to end.
    violated = S.select_provider(
        reg, request(observations={"tooling.external_synthesis_host_reachable": False}))
    check("unknown.measured_failure_is_a_real_rejection",
          violated["considered"][0]["status"] == S.STATUS_REJECTED
          and C.CORE_PROVIDER_REQUIREMENT_UNMET in violated["failure_codes"],
          "entry={} codes={}".format(violated["considered"][0], violated["failure_codes"]))


# --------------------------------------------------------------------------- #
# 10. selection is explainable and reproducible
# --------------------------------------------------------------------------- #
def test_selection_is_explainable():
    reg = registry_with(FAST_NONDETERMINISTIC, SLOW_SEEDED, UNMEASURED)
    req = request(constraints=[
        constraint("c_must_be_seeded", K.HARD_INVARIANT, S.FACET_DETERMINISM_SEEDED)])
    result = S.select_provider(reg, req)

    check("explain.every_registered_provider_is_accounted_for",
          {e["provider_id"] for e in result["considered"]}
          == {"fast_nondeterministic_bridge", "slow_seeded_bridge", "external_tool_bridge"},
          "considered={}".format([e["provider_id"] for e in result["considered"]]))
    check("explain.every_non_winner_carries_a_reason",
          all(e["reasons"] for e in result["considered"]
              if e["provider_id"] != result["selected_provider"]),
          "considered={}".format(result["considered"]))
    check("explain.records_the_pool_it_chose_from",
          result["registry_snapshot"]["providers"] == list(reg.provider_ids()))
    check("explain.renders_human_readable_lines",
          any("slow_seeded_bridge" in line for line in S.explain(result)))

    # reproducibility: the same inputs in a different REGISTRATION order must
    # produce an identical decision, or the build depends on how the process booted.
    reg_reordered = registry_with(UNMEASURED, SLOW_SEEDED, FAST_NONDETERMINISTIC)
    again = S.select_provider(reg_reordered, req)
    check("explain.registration_order_is_not_observable",
          again["selected_provider"] == result["selected_provider"]
          and again["ranking"] == result["ranking"]
          and [e["provider_id"] for e in again["considered"]]
          == [e["provider_id"] for e in result["considered"]],
          "reordered={} original={}".format(again["ranking"], result["ranking"]))


# --------------------------------------------------------------------------- #
# 11. a preference can never block; an unknown facet fails closed
# --------------------------------------------------------------------------- #
def test_preferences_cannot_block_and_unknown_facets_fail_closed():
    reg = registry_with(FAST_NONDETERMINISTIC)
    unsatisfiable_preference = constraint(
        "c_prefer_seeded", K.SOFT_PREFERENCE, S.FACET_DETERMINISM_SEEDED, weight=5.0)
    result = S.select_provider(reg, request(constraints=[unsatisfiable_preference]))
    check("scoring.unmet_preference_does_not_block",
          result["outcome"] == S.OUTCOME_SELECTED
          and result["selected_provider"] == "fast_nondeterministic_bridge",
          "outcome={} codes={}".format(result["outcome"], result["failure_codes"]))
    check("scoring.unmet_preference_scores_zero",
          result["ranking"][0]["score"] == 0.0, "ranking={}".format(result["ranking"]))

    unrecognised = constraint("c_unrecognised_facet", K.HARD_INVARIANT,
                              "provider.does_something_nice")
    blocked = S.select_provider(reg, request(constraints=[unrecognised]))
    check("filter.unrecognised_provider_facet_fails_closed",
          blocked["outcome"] == S.OUTCOME_NO_ELIGIBLE_CANDIDATE
          and blocked["considered"][0]["status"] == S.STATUS_UNKNOWN,
          "outcome={} entry={}".format(blocked["outcome"], blocked["considered"][0]))

    world_constraint = constraint("c_world_reachability", K.HARD_INVARIANT,
                                  "navigation.reachability")
    unaffected = S.select_provider(reg, request(constraints=[world_constraint]))
    check("filter.world_constraint_does_not_filter_providers",
          unaffected["outcome"] == S.OUTCOME_SELECTED,
          "a constraint outside the provider namespace must not block selection; "
          "outcome={}".format(unaffected["outcome"]))

    prohibited = constraint("c_no_persistent_mutation", K.PROHIBITED_OUTCOME,
                            S.FACET_PREFIX_SIDE_EFFECT + B.EFFECT_PERSISTENT_ASSET)
    prohibited_result = S.select_provider(reg, request(constraints=[prohibited]))
    check("filter.prohibited_side_effect_eliminates_provider",
          prohibited_result["outcome"] == S.OUTCOME_NO_ELIGIBLE_CANDIDATE
          and prohibited_result["considered"][0]["status"] == S.STATUS_REJECTED,
          "outcome={}".format(prohibited_result["outcome"]))

    protected = constraint("c_protected_scopes", K.PROTECTED_SEMANTICS,
                           S.FACET_SIDE_EFFECT_SCOPE,
                           protected_ids=["content.authored_assets"])
    protected_result = S.select_provider(reg, request(constraints=[protected]))
    check("filter.protected_scope_eliminates_provider",
          protected_result["outcome"] == S.OUTCOME_NO_ELIGIBLE_CANDIDATE,
          "outcome={}".format(protected_result["outcome"]))


# --------------------------------------------------------------------------- #
# 12. no candidate at all
# --------------------------------------------------------------------------- #
def test_no_candidate():
    reg = registry_with(SLOW_SEEDED)
    result = S.select_provider(reg, request(capability=B.CAP_GEOMETRY_SYNTHESIS))
    check("no_candidate.outcome", result["outcome"] == S.OUTCOME_NO_CANDIDATE)
    check("no_candidate.code",
          C.CORE_NO_PROVIDER_FOR_CAPABILITY in result["failure_codes"],
          "codes={}".format(result["failure_codes"]))
    expect_valid("no_candidate.result_validates",
                 S.validate_selection_result(result, strict=True))

    missing_output = S.select_provider(
        reg, request(required_outputs=["a_kind_this_provider_does_not_produce"]))
    check("no_candidate.required_output_not_produced",
          missing_output["outcome"] == S.OUTCOME_NO_CANDIDATE,
          "outcome={}".format(missing_output["outcome"]))


# --------------------------------------------------------------------------- #
def main():
    tests = [
        test_provider_declaration,
        test_requirement_evaluation,
        test_registry,
        test_registry_snapshot_validator,
        test_selection_request_validator,
        test_selection_result_validator,
        test_tie_is_ambiguous_not_arbitrary,
        test_hard_invariant_beats_score,
        test_unknown_eligibility_does_not_select,
        test_selection_is_explainable,
        test_preferences_cannot_block_and_unknown_facets_fail_closed,
        test_no_candidate,
    ]
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a skip
            FAILURES.append("{} raised {}: {}".format(fn.__name__, type(exc).__name__, exc))
        print("  ran {}".format(fn.__name__))

    print("")
    print("wfcore.providers: {} assertion(s) passed, {} failed".format(
        PASSED[0], len(FAILURES)))
    for f in FAILURES:
        print("  FAIL {}".format(f))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
