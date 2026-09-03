#!/usr/bin/env python3
"""test_build_manifest -- prove the manifest refuses to describe damage tidily.

A manifest's whole job is to be believed later, by someone who was not there.
So the assertions here are almost entirely negative: what it must REFUSE to
say. A validator that only confirms well-formed input is a schema check wearing
an evidence check's name.

The three that carry the weight:

  * a generated artifact standing on a caller-declared protected path is
    rejected outright -- that is not a labelling slip to be corrected in the
    document, it means the build authored over content it was told not to touch
  * a match claimed with nothing observed is rejected -- agreement asserted
    against an absence is the exact shape of a fabricated verification
  * an unstamped manifest is rejected -- without created_at and git_sha it
    certifies content of unknown age forever
"""

import copy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import build_manifest as BM     # noqa: E402

_FAILS = []
_N = [0]


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))


def _plan(n=2):
    return {
        "schema_version": "wf.core.route_placement_plan.v1",
        "provider_id": "route_placement_planner",
        "anchor_ids": ["a.start", "a.end"],
        "placements": [
            {"index": i + 1, "location_cm": [float(i * 100), 0.0, 0.0],
             "rotation_pyr": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}
            for i in range(n)],
    }


def _paths(n=2):
    return ["/Game/Maps/M:mk_{:03d}".format(i + 1) for i in range(n)]


def _observed(paths, plan):
    return {tp: {"actor_class": "StaticMeshActor",
                 "location": list(pl["location_cm"]),
                 "rotation": list(pl["rotation_pyr"]),
                 "scale": list(pl["scale"])}
            for tp, pl in zip(paths, plan["placements"])}


def _good():
    plan, paths = _plan(), _paths()
    return BM.build_manifest(
        request_id="op_t", plan=plan, target_paths=paths,
        observed_payloads=_observed(paths, plan),
        protected_identities=["/Game/Maps/M:HumanThing"],
        created_at="2026-01-01T00:00:00+00:00")


def _failed(man):
    return {c[0] for c in BM.validate_build_manifest(man, strict=True)
            if not c[1]}


# --------------------------------------------------------------------------- #
def test_wellformed_passes():
    man = _good()
    bad = _failed(man)
    check("wellformed_manifest_validates", not bad, bad)
    check("counts_are_derived_not_asserted",
          man["counts"] == {"generated": 2, "observed": 2,
                            "intent_matches_observed": 2}, man["counts"])
    check("every_artifact_hashed",
          all(a["intent_hash"].startswith("sha256:") for a in man["artifacts"]))
    check("git_sha_recorded", bool(man.get("git_sha")))


def test_hashes_are_content_addressed():
    a, b = _good(), _good()
    check("same_inputs_same_hashes",
          [x["intent_hash"] for x in a["artifacts"]]
          == [x["intent_hash"] for x in b["artifacts"]])
    plan, paths = _plan(), _paths()
    plan["placements"][0]["location_cm"] = [999.0, 0.0, 0.0]
    moved = BM.build_manifest("op_t", plan, _observed(paths, plan), [],
                              "2026-01-01T00:00:00+00:00", target_paths=paths)
    check("moved_placement_changes_its_hash",
          moved["artifacts"][0]["intent_hash"] != a["artifacts"][0]["intent_hash"])
    check("untouched_placement_keeps_its_hash",
          moved["artifacts"][1]["intent_hash"] == a["artifacts"][1]["intent_hash"])
    check("canonical_hash_is_key_order_stable",
          BM.canonical_hash({"a": 1, "b": 2}) == BM.canonical_hash({"b": 2, "a": 1}))


def test_refuses_to_claim_game_owned_content():
    man = _good()
    # The artifact now stands on a path the caller declared game-owned.
    man["declared_game_owned"] = [man["artifacts"][0]["target_path"]]
    names = _failed(man)
    check("generated_on_protected_path_is_rejected",
          any("does_not_claim_game_owned_content" in n for n in names), names)


def test_refuses_a_match_with_nothing_observed():
    man = _good()
    man["artifacts"][0]["observed_hash"] = None
    man["artifacts"][0]["intent_matches_observed"] = True
    names = _failed(man)
    check("match_without_observation_is_rejected",
          any("no_match_claimed_without_observation" in n for n in names), names)

    honest = _good()
    honest["artifacts"][0]["observed_hash"] = None
    honest["artifacts"][0]["intent_matches_observed"] = None
    check("unobserved_but_honest_is_accepted",
          not any("no_match_claimed_without_observation" in n
                  for n in _failed(honest)))


def test_refuses_unstamped():
    for field in ("created_at", "git_sha"):
        man = _good()
        man[field] = None
        names = _failed(man)
        check("unstamped_{}_is_rejected".format(field),
              any("is_stamped" in n for n in names), names)


def test_refuses_duplicate_identity():
    man = _good()
    man["artifacts"][1]["target_path"] = man["artifacts"][0]["target_path"]
    names = _failed(man)
    check("two_artifacts_one_path_is_rejected",
          any("target_path_unique" in n for n in names), names)


def test_refuses_unknown_ownership_and_bad_shape():
    man = _good()
    man["artifacts"][0]["ownership"] = "probably_ours"
    check("unknown_ownership_is_rejected",
          any("ownership_known" in n for n in _failed(man)))

    man2 = _good()
    man2["artifacts"][0]["intent_hash"] = "md5:abc"
    check("non_sha256_hash_is_rejected",
          any("intent_hash_wellformed" in n for n in _failed(man2)))

    man3 = _good()
    man3["schema_version"] = "wf.core.build_manifest.v0"
    check("wrong_schema_version_is_rejected",
          any("schema_version" in n for n in _failed(man3)))

    check("non_object_is_rejected", bool(_failed("not a manifest")))

    man4 = _good()
    del man4["artifacts"][0]["validation"]
    check("missing_required_artifact_field_is_rejected",
          any("has_validation" in n for n in _failed(man4)))


def test_divergence_is_reported_per_artifact():
    plan, paths = _plan(), _paths()
    obs = _observed(paths, plan)
    obs[paths[0]]["location"] = [12345.0, 0.0, 0.0]     # world drifted
    man = BM.build_manifest("op_t", plan, obs, [], "2026-01-01T00:00:00+00:00",
                            target_paths=paths)
    check("divergent_artifact_is_flagged",
          man["artifacts"][0]["intent_matches_observed"] is False)
    check("agreeing_artifact_is_not_flagged",
          man["artifacts"][1]["intent_matches_observed"] is True)
    check("counts_do_not_average_away_the_divergence",
          man["counts"]["intent_matches_observed"] == 1, man["counts"])
    check("a_divergent_manifest_is_still_structurally_valid",
          not _failed(man), _failed(man))


def main():
    for fn in (test_wellformed_passes, test_hashes_are_content_addressed,
               test_refuses_to_claim_game_owned_content,
               test_refuses_a_match_with_nothing_observed,
               test_refuses_unstamped, test_refuses_duplicate_identity,
               test_refuses_unknown_ownership_and_bad_shape,
               test_divergence_is_reported_per_artifact):
        fn()
    if _FAILS:
        print("test_build_manifest: {} passed, {} FAILED".format(
            _N[0], len(_FAILS)))
        for f in _FAILS:
            print("  - {}".format(f))
        return 1
    print("test_build_manifest: {} assertion(s) passed, 0 failed".format(_N[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
