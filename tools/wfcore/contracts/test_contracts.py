#!/usr/bin/env python3
"""wfcore.contracts.test_contracts -- negatives-first suite for the five contracts.

    cd tools && PYTHONUTF8=1 python -m wfcore.contracts.test_contracts

WHY THIS SUITE IS SHAPED AROUND KNOWN-BADS
------------------------------------------
A validator that only ever sees its own canonical example proves one thing: that
the example matches the validator. Both were written in the same hour by the same
author, so the agreement is not evidence. What must be proved is that each RAIL
FIRES -- that the specific malformed record the rail exists to catch is actually
caught, and caught with the failure code the rail claims. So every validator here
gets its canonical example asserted valid (in strict mode, which is the stricter
claim) and then at least three distinct known-bads asserted to fail with a named
check and an expected code.

The known-bads are all spawned from the canonical example via ``**over``, which
means each one differs from a VALID record in exactly one stated way. That is
what makes a failure attributable: if the record fails, it fails because of the
thing that was changed.

Exit code is non-zero on any failure, so this module works as a gate and not only
as a developer convenience.
"""

import sys
from typing import Any, Dict, List, Optional

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from . import ContractAuthorityError, Check
from . import acceptance_criteria as AC
from . import asset_catalog as CAT
from . import consumer_profile as CP
from . import revision_policy as RP
from . import world_request as WR

_PASSED: List[str] = []
_FAILED: List[str] = []


def _failures(checks: List[Check]) -> List[Check]:
    return [c for c in checks if not c[1]]


def _record(ok: bool, label: str, detail: str = "") -> None:
    if ok:
        _PASSED.append(label)
        print("  [PASS] {}".format(label))
    else:
        _FAILED.append(label)
        print("  [FAIL] {}{}".format(label, "  -- " + detail if detail else ""))


def expect_valid(label: str, checks: List[Check]) -> None:
    bad = _failures(checks)
    _record(not bad, label,
            "expected a clean record, got {} failing check(s): {}".format(
                len(bad), "; ".join("{} ({})".format(c[0], c[3]) for c in bad[:4])))


def expect_failure(label: str, checks: List[Check], check_name: str,
                   code: str) -> None:
    """Assert that a SPECIFIC named check failed with a SPECIFIC code.

    Asserting only "something failed" would pass when an unrelated rail fired --
    which is how a suite keeps reporting green after the rail it was written for
    stopped working.
    """
    hits = [c for c in _failures(checks) if check_name in c[0]]
    if not hits:
        _record(False, label,
                "expected check containing {!r} to FAIL; failing checks were {}"
                .format(check_name,
                        [c[0] for c in _failures(checks)][:6] or "(none)"))
        return
    codes = {c[3] for c in hits}
    ok = code in codes
    _record(ok, label,
            "check {!r} failed with code(s) {} but expected {}".format(
                check_name, sorted(codes), code))


def expect_raises(label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except ContractAuthorityError:
        _record(True, label)
        return
    except Exception as exc:  # wrong exception is still a failure
        _record(False, label, "raised {} instead of ContractAuthorityError".format(
            type(exc).__name__))
        return
    _record(False, label, "did not raise ContractAuthorityError")


def expect_equal(label: str, actual: Any, expected: Any) -> None:
    _record(actual == expected, label,
            "got {!r}, expected {!r}".format(actual, expected))


def _drop(d: Dict[str, Any], key: str) -> Dict[str, Any]:
    out = dict(d)
    out.pop(key, None)
    return out


def _with(d: Dict[str, Any], **over: Any) -> Dict[str, Any]:
    out = dict(d)
    out.update(over)
    return out


# --------------------------------------------------------------------------- #
# 1. consumer_profile
# --------------------------------------------------------------------------- #
def test_consumer_profile() -> None:
    print("\nconsumer_profile")
    expect_valid("cp canonical example is valid (strict)",
                 CP.validate_consumer_profile(CP._example_consumer_profile(),
                                              strict=True))

    expect_failure(
        "cp rejects a game_type outside the closed vocabulary",
        CP.validate_consumer_profile(
            CP._example_consumer_profile(game_type="mmo_shooter")),
        "game_type_in_vocabulary", C.CORE_CONSUMER_PROFILE_INVALID)

    expect_failure(
        "cp rejects an unsupported contract_version",
        CP.validate_consumer_profile(
            CP._example_consumer_profile(contract_version="wf.core.contract.v99")),
        "contract_version_supported", C.CORE_CONTRACT_VERSION_UNSUPPORTED)

    metrics = CP._example_consumer_profile()["player_metrics"]
    expect_failure(
        "cp rejects a fabricated zero where a measure belongs",
        CP.validate_consumer_profile(
            CP._example_consumer_profile(
                player_metrics=_with(metrics, max_step_height_cm=0))),
        "player_metrics.max_step_height_cm_measure",
        C.CORE_CONSUMER_PROFILE_INVALID)

    expect_failure(
        "cp rejects a capsule whose diameter exceeds its height",
        CP.validate_consumer_profile(
            CP._example_consumer_profile(
                player_metrics=_with(metrics, capsule_radius_cm=120.0))),
        "capsule_is_a_capsule", C.CORE_CONSUMER_PROFILE_INVALID)

    expect_failure(
        "cp rejects an unknown metric with no resolution owner",
        CP.validate_consumer_profile(
            CP._example_consumer_profile(
                player_metrics=_with(metrics, max_jump_height_cm=tri.UNKNOWN))),
        "unknown_metric_names_resolution_owner",
        C.CORE_CONSUMER_PROFILE_INVALID)

    expect_valid(
        "cp ACCEPTS an unknown metric when an owner is named (honest unknown)",
        CP.validate_consumer_profile(
            CP._example_consumer_profile(
                player_metrics=_with(metrics, max_jump_height_cm=tri.UNKNOWN),
                unknown_resolution_owner="consumer-side design owner")))

    expect_failure(
        "cp rejects a standing constraint with an unknown class",
        CP.validate_consumer_profile(
            CP._example_consumer_profile(standing_constraints=[{
                "constraint_id": "sc_bad",
                "constraint_class": "nice_to_have",
                "subject": "composition.mood",
                "detail": "a class that is not in the taxonomy",
            }])),
        "standing[0].constraint_class_known", C.CORE_CONSTRAINT_UNKNOWN_CLASS)

    expect_failure(
        "cp rejects a missing engine identity field",
        CP.validate_consumer_profile(
            CP._example_consumer_profile(
                engine_identity={"engine_version": "0.0.0"})),
        "engine_identity.has_project_identifier",
        C.CORE_CONSUMER_PROFILE_INVALID)

    # fail-closed factory: Core must never invent the caller's identity.
    expect_raises("cp build fails closed with no caller-owned fields",
                  CP.build_consumer_profile)
    expect_raises("cp build fails closed without declared_capabilities",
                  CP.build_consumer_profile,
                  consumer_id="x", engine_identity={})

    profile = CP._example_consumer_profile()
    expect_equal("cp capability verdict: declared -> SATISFIED",
                 CP.declared_capability_verdict(profile, "terrain.heightfield"),
                 tri.SATISFIED)
    expect_equal("cp capability verdict: undeclared -> VIOLATED (closed list)",
                 CP.declared_capability_verdict(profile, "weather.simulation"),
                 tri.VIOLATED)
    expect_equal("cp capability verdict: no list at all -> UNKNOWN",
                 CP.declared_capability_verdict(_drop(profile,
                                                      "declared_capabilities"),
                                                "terrain.heightfield"),
                 tri.UNKNOWN)


# --------------------------------------------------------------------------- #
# 2. asset_catalog
# --------------------------------------------------------------------------- #
def test_asset_catalog() -> None:
    print("\nasset_catalog")
    expect_valid("cat canonical example is valid (strict)",
                 CAT.validate_asset_catalog(CAT._example_asset_catalog(),
                                            strict=True))

    expect_failure(
        "cat rejects a catalog that declares itself open",
        CAT.validate_asset_catalog(CAT._example_asset_catalog(closed_world=False)),
        "catalog_is_closed_world", C.CORE_ASSET_CATALOG_INVALID)

    expect_failure(
        "cat rejects an empty closed catalog",
        CAT.validate_asset_catalog(
            CAT._example_asset_catalog(entries=[], style_families=[])),
        "entries_non_empty", C.CORE_ASSET_CATALOG_INVALID)

    expect_failure(
        "cat rejects a style family naming an asset not in the catalog",
        CAT.validate_asset_catalog(CAT._example_asset_catalog(style_families=[{
            "style_id": "style_family_a",
            "member_asset_ids": ["asset_placeholder_surface_01",
                                 "asset_placeholder_absent_01"],
        }])),
        "style_family_members_resolve", C.CORE_ASSET_CATALOG_INVALID)

    expect_failure(
        "cat rejects a style family that gathers a DENIED asset",
        CAT.validate_asset_catalog(CAT._example_asset_catalog(style_families=[{
            "style_id": "style_family_a",
            "member_asset_ids": ["asset_placeholder_surface_01",
                                 "asset_placeholder_effect_01"],
        }])),
        "style_family_excludes_denied", C.CORE_ASSET_CATALOG_INVALID)

    expect_failure(
        "cat rejects a denial with no reason",
        CAT.validate_asset_catalog(CAT._example_asset_catalog(entries=[
            CAT._example_asset_entry(),
            CAT._example_asset_entry(asset_id="asset_placeholder_effect_01",
                                     authorization=CAT.DENIED),
        ], style_families=[])),
        "denial_states_reason", C.CORE_ASSET_CATALOG_INVALID)

    expect_failure(
        "cat rejects a conditional approval with no conditions",
        CAT.validate_asset_catalog(CAT._example_asset_catalog(entries=[
            CAT._example_asset_entry(
                authorization=CAT.APPROVED_WITH_CONDITIONS),
        ], style_families=[])),
        "conditional_approval_states_conditions", C.CORE_ASSET_CATALOG_INVALID)

    expect_failure(
        "cat rejects duplicate asset ids",
        CAT.validate_asset_catalog(CAT._example_asset_catalog(entries=[
            CAT._example_asset_entry(),
            CAT._example_asset_entry(asset_role="static_geometry"),
        ], style_families=[])),
        "asset_ids_unique", C.CORE_ASSET_CATALOG_INVALID)

    expect_failure(
        "cat rejects a variant pointing outside the catalog",
        CAT.validate_asset_catalog(CAT._example_asset_catalog(entries=[
            CAT._example_asset_entry(),
            CAT._example_asset_entry(asset_id="asset_placeholder_surface_02",
                                     variant_of="asset_placeholder_absent_01"),
        ], style_families=[])),
        "variant_targets_resolve", C.CORE_ASSET_CATALOG_INVALID)

    expect_raises("cat build fails closed with no caller-owned fields",
                  CAT.build_asset_catalog)
    expect_raises("cat build fails closed without entries",
                  CAT.build_asset_catalog,
                  catalog_id="c", consumer_id="x")

    catalog = CAT._example_asset_catalog()
    expect_equal("cat authorization: approved -> SATISFIED",
                 CAT.authorization_of(catalog, "asset_placeholder_surface_01"),
                 tri.SATISFIED)
    expect_equal("cat authorization: denied -> VIOLATED",
                 CAT.authorization_of(catalog, "asset_placeholder_effect_01"),
                 tri.VIOLATED)
    expect_equal("cat authorization: unreviewed -> UNKNOWN (never satisfied)",
                 CAT.authorization_of(catalog, "asset_placeholder_foliage_01"),
                 tri.UNKNOWN)
    expect_equal("cat authorization: absent from a CLOSED catalog -> VIOLATED",
                 CAT.authorization_of(catalog, "asset_placeholder_absent_01"),
                 tri.VIOLATED)
    conditional = CAT._example_asset_catalog(entries=[
        CAT._example_asset_entry(authorization=CAT.APPROVED_WITH_CONDITIONS,
                                 conditions=["only in interior spaces"])],
        style_families=[])
    expect_equal("cat authorization: approved_with_conditions -> UNKNOWN",
                 CAT.authorization_of(conditional,
                                      "asset_placeholder_surface_01"),
                 tri.UNKNOWN)


# --------------------------------------------------------------------------- #
# 3. world_request
# --------------------------------------------------------------------------- #
def test_world_request() -> None:
    print("\nworld_request")
    expect_valid("wr canonical example is valid (strict)",
                 WR.validate_world_request(WR._example_world_request(),
                                           strict=True))

    expect_failure(
        "wr rejects a revision that does not name what it revises",
        WR.validate_world_request(
            WR._example_world_request(request_kind=WR.REVISION,
                                      revision_policy_id="policy_placeholder")),
        "revision_names_target", C.CORE_WORLD_REQUEST_INVALID)

    expect_failure(
        "wr rejects a revision with no policy bound",
        WR.validate_world_request(
            WR._example_world_request(request_kind=WR.REVISION,
                                      revision_target="subject_placeholder")),
        "revision_names_policy", C.CORE_WORLD_REQUEST_INVALID)

    expect_failure(
        "wr rejects a new_world that carries a revision target",
        WR.validate_world_request(
            WR._example_world_request(revision_target="subject_placeholder")),
        "new_world_carries_no_revision_target", C.CORE_WORLD_REQUEST_INVALID)

    landmarks = WR._example_world_request()["semantic_landmarks"]
    expect_failure(
        "wr rejects a request with no entry landmark",
        WR.validate_world_request(WR._example_world_request(
            semantic_landmarks=[lm for lm in landmarks
                                if lm["role"] != "entry"])),
        "request_declares_an_entry_landmark", C.CORE_WORLD_REQUEST_INVALID)

    example = WR._example_world_request()
    expect_failure(
        "wr rejects a required affordance no load-bearing constraint names",
        WR.validate_world_request(WR._example_world_request(
            constraints=[c for c in example["constraints"]
                         if c["constraint_id"] != "afford_traversal_spine"])),
        "required_affordance_is_load_bearing", C.CORE_WORLD_REQUEST_INVALID)

    expect_failure(
        "wr delegates to the constraint taxonomy: no load-bearing member",
        WR.validate_world_request(WR._example_world_request(
            constraints=[c for c in example["constraints"]
                         if c["constraint_class"] == K.SOFT_PREFERENCE],
            gameplay_affordances=[
                _with(a, required=False)
                for a in example["gameplay_affordances"]])),
        "constraints.constraint_set_has_load_bearing_member",
        C.CORE_NO_LOAD_BEARING_CONSTRAINT)

    expect_failure(
        "wr rejects an unknown population density with no resolution owner",
        WR.validate_world_request(WR._example_world_request(
            population={"density_class": tri.UNKNOWN,
                        "population_roles": []})),
        "population.unknown_names_resolution_owner",
        C.CORE_WORLD_REQUEST_INVALID)

    expect_valid(
        "wr ACCEPTS an unknown population density when an owner is named",
        WR.validate_world_request(WR._example_world_request(
            population={"density_class": tri.UNKNOWN,
                        "population_roles": [],
                        "resolution_owner": "consumer-side design owner"})))

    expect_failure(
        "wr rejects density 'none' contradicting declared population roles",
        WR.validate_world_request(WR._example_world_request(
            population={"density_class": "none",
                        "population_roles": ["population_role_a"]})),
        "population.density_matches_roles", C.CORE_WORLD_REQUEST_INVALID)

    expect_failure(
        "wr rejects a fabricated zero extent",
        WR.validate_world_request(WR._example_world_request(
            environment={"extent_m2": 0, "relief_class": "rolling",
                         "lighting_condition": "overcast"})),
        "environment.extent_m2_measure", C.CORE_WORLD_REQUEST_INVALID)

    expect_raises("wr build fails closed with no caller-owned fields",
                  WR.build_world_request)
    expect_raises("wr build fails closed without a subject",
                  WR.build_world_request,
                  request_id="r", consumer_id="x", catalog_id="c",
                  constraints=[])


# --------------------------------------------------------------------------- #
# 4. revision_policy
# --------------------------------------------------------------------------- #
def test_revision_policy() -> None:
    print("\nrevision_policy")
    expect_valid("rp canonical example is valid (strict)",
                 RP.validate_revision_policy(RP._example_revision_policy(),
                                             strict=True))

    expect_failure(
        "rp rejects a mutation kind that is both permitted and prohibited",
        RP.validate_revision_policy(RP._example_revision_policy(
            prohibited_mutations=["add_geometry"])),
        "permit_prohibit_disjoint", C.CORE_REVISION_POLICY_INVALID)

    expect_failure(
        "rp rejects a protected semantic wearing a non-protecting class",
        RP.validate_revision_policy(RP._example_revision_policy(
            protected_semantics=[{
                "constraint_id": "ps_wrong_class",
                "constraint_class": K.SOFT_PREFERENCE,
                "subject": "landmark.identity",
                "detail": "reads as protection, cannot block anything",
                "weight": 0.9,
            }])),
        "protected_semantics_carry_protected_class",
        C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION)

    expect_failure(
        "rp rejects an unrecognised mutation kind in permitted_mutations",
        RP.validate_revision_policy(RP._example_revision_policy(
            permitted_mutations=["add_geometry", "rewrite_everything"])),
        "permitted_mutations_in_vocabulary", C.CORE_MUTATION_NOT_PERMITTED)

    expect_failure(
        "rp rejects a demanded rollback with no granularity to roll back to",
        RP.validate_revision_policy(RP._example_revision_policy(rollback={
            "rollback_required": True,
            "rollback_granularity": "none",
            "max_revision_attempts": 3,
        })),
        "required_rollback_has_granularity", C.CORE_REVISION_POLICY_INVALID)

    expect_failure(
        "rp rejects zero revision attempts",
        RP.validate_revision_policy(RP._example_revision_policy(rollback={
            "rollback_required": True,
            "rollback_granularity": "per_transaction",
            "max_revision_attempts": 0,
        })),
        "max_revision_attempts_int_min_1", C.CORE_REVISION_POLICY_INVALID)

    expect_failure(
        "rp rejects protecting nothing without saying so",
        RP.validate_revision_policy(RP._example_revision_policy(
            protected_content=[], protected_semantics=[])),
        "protection_is_stated", C.CORE_REVISION_POLICY_INVALID)

    expect_valid(
        "rp ACCEPTS protecting nothing when it is acknowledged explicitly",
        RP.validate_revision_policy(RP._example_revision_policy(
            protected_content=[], protected_semantics=[],
            unprotected_acknowledged=True)))

    expect_failure(
        "rp rejects an empty permitted set (a policy that authorises nothing)",
        RP.validate_revision_policy(RP._example_revision_policy(
            permitted_mutations=[])),
        "permitted_mutations_str_list", C.CORE_REVISION_POLICY_INVALID)

    expect_raises("rp build fails closed with no caller-owned fields",
                  RP.build_revision_policy)
    expect_raises("rp build fails closed without protected_content",
                  RP.build_revision_policy,
                  policy_id="p", consumer_id="x",
                  permitted_mutations=["add_geometry"])

    policy = RP._example_revision_policy()
    expect_equal("rp mutation verdict: permitted -> SATISFIED",
                 RP.mutation_verdict(policy, "add_geometry"), tri.SATISFIED)
    expect_equal("rp mutation verdict: prohibited -> VIOLATED",
                 RP.mutation_verdict(policy, "remove_geometry"), tri.VIOLATED)
    expect_equal("rp mutation verdict: unlisted -> VIOLATED (allow-list)",
                 RP.mutation_verdict(policy, "adjust_audio"), tri.VIOLATED)
    expect_equal("rp mutation verdict: nothing stated at all -> UNKNOWN",
                 RP.mutation_verdict({}, "add_geometry"), tri.UNKNOWN)


# --------------------------------------------------------------------------- #
# 5. acceptance_criteria
# --------------------------------------------------------------------------- #
def test_acceptance_criteria() -> None:
    print("\nacceptance_criteria")
    example = AC._example_acceptance_criteria()
    expect_valid("acc canonical example is valid (strict)",
                 AC.validate_acceptance_criteria(example, strict=True))

    expect_failure(
        "acc rejects a load-bearing constraint nothing will ever evaluate",
        AC.validate_acceptance_criteria(AC._example_acceptance_criteria(
            evaluation_requirements=[r for r in example["evaluation_requirements"]
                                     if r["constraint_id"] != "c_generation_budget"])),
        "every_load_bearing_constraint_is_evaluable",
        C.CORE_CONSTRAINT_NOT_EVALUATED)

    expect_failure(
        "acc rejects must_block_ids naming a soft preference",
        AC.validate_acceptance_criteria(AC._example_acceptance_criteria(
            must_block_ids=["afford_traversal_spine", "c_silhouette_variety"])),
        "must_block_ids_are_load_bearing",
        C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION)

    expect_failure(
        "acc rejects must_block_ids naming a constraint not in the set",
        AC.validate_acceptance_criteria(AC._example_acceptance_criteria(
            must_block_ids=["c_absent"])),
        "must_block_ids_resolve", C.CORE_ACCEPTANCE_CRITERIA_INVALID)

    expect_failure(
        "acc rejects an evaluation requirement for a constraint not in the set",
        AC.validate_acceptance_criteria(AC._example_acceptance_criteria(
            evaluation_requirements=example["evaluation_requirements"] + [
                {"constraint_id": "c_absent",
                 "evidence_kind": "static_analysis"}])),
        "evaluation_requirements_resolve", C.CORE_ACCEPTANCE_CRITERIA_INVALID)

    expect_failure(
        "acc rejects any unknown_handling that is not blocking",
        AC.validate_acceptance_criteria(AC._example_acceptance_criteria(
            unknown_handling="treat_as_satisfied")),
        "unknown_handling_in_vocabulary", C.CORE_ACCEPTANCE_CRITERIA_INVALID)

    expect_failure(
        "acc rejects an unknown evidence kind",
        AC.validate_acceptance_criteria(AC._example_acceptance_criteria(
            evaluation_requirements=[{"constraint_id": "afford_traversal_spine",
                                      "evidence_kind": "vibes"},
                                     {"constraint_id": "c_generation_budget",
                                      "evidence_kind": "external_measurement"}])),
        "evidence_kind_in_vocabulary", C.CORE_ACCEPTANCE_CRITERIA_INVALID)

    expect_raises("acc build fails closed with no caller-owned fields",
                  AC.build_acceptance_criteria)
    expect_raises("acc build fails closed without constraints",
                  AC.build_acceptance_criteria,
                  criteria_id="c", consumer_id="x", request_id="r")

    # --- the fold itself ------------------------------------------------------
    all_good = {
        "afford_traversal_spine": tri.SATISFIED,
        "c_generation_budget": tri.SATISFIED,
        "c_silhouette_variety": tri.VIOLATED,   # soft: structurally cannot block
    }
    verdict, blockers = AC.acceptance_verdict(example, all_good)
    expect_equal("acc verdict: load-bearing all satisfied -> SATISFIED",
                 verdict, tri.SATISFIED)
    expect_equal("acc verdict: a VIOLATED soft preference blocks nothing",
                 blockers, [])

    verdict, blockers = AC.acceptance_verdict(
        example, {"afford_traversal_spine": tri.SATISFIED})
    expect_equal("acc verdict: an unevaluated load-bearing constraint -> UNKNOWN",
                 verdict, tri.UNKNOWN)
    expect_equal("acc verdict: the unknown is reported as unmeasured, not failed",
                 [b["blocking_reason"] for b in blockers],
                 ["not_evaluated_no_observation_supports_a_verdict"])

    verdict, blockers = AC.acceptance_verdict(
        example, _with(all_good, afford_traversal_spine=tri.VIOLATED))
    expect_equal("acc verdict: a violated hard invariant -> VIOLATED",
                 verdict, tri.VIOLATED)
    expect_equal("acc verdict: the violation is reported as observed",
                 [b["blocking_reason"] for b in blockers],
                 ["violated_by_observation"])

    expect_equal("acc verdict: UNKNOWN never accepts",
                 tri.accepts(tri.UNKNOWN), False)


def main(argv: Optional[List[str]] = None) -> int:
    print("wfcore.contracts -- consumer contract suite "
          "(canonical example + known-bads per validator)")
    test_consumer_profile()
    test_asset_catalog()
    test_world_request()
    test_revision_policy()
    test_acceptance_criteria()

    total = len(_PASSED) + len(_FAILED)
    print("\n" + "-" * 68)
    print("  {} assertion(s): {} passed, {} failed".format(
        total, len(_PASSED), len(_FAILED)))
    if _FAILED:
        print("  FAILED:")
        for label in _FAILED:
            print("    - {}".format(label))
    print("  SUITE {}".format("GREEN" if not _FAILED else "RED"))
    return 0 if not _FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
