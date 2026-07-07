#!/usr/bin/env python3
"""v1_5_fuzz.py — WorldForge v1.5 Wave-4 deterministic contract fuzz harness.

Attacks the seven v1.5 record schemas by mutating a known-valid base record in
structured ways that MUST be rejected, then asserts the contract's
``validate_record`` rejects every invalid mutation and accepts the untouched base.

The seven contracts fuzzed (each exposes ``validate_record`` + ``_example_record``
+ ``REQUIRED_FIELDS``):
    asset_need, asset_candidate, asset_approval, quarantine,
    asset_catalog, visual_kit, realized_cover

Structured mutation families (each hand-picked to hit a rule the contract really
enforces, so a green run means the guard fired, not that the mutation was inert):
    * drop a required field                (rejected in both modes)
    * out-of-enum value                    (priority/status/biome/height/... )
    * wrong-typed field                    (list->str, dict->str, int->str)
    * negative count / invalid numeric     (required_count < 0)
    * illegal state combination            (paid w/o manual, third-party redistrib,
                                            eula w/o manual, missing source ref,
                                            hash missing, path outside quarantine,
                                            protected-lifecycle violation, ...)
    * add an unknown field                 (rejected under strict)

DETERMINISM: a single ``random.Random(seed)`` (fixed default seed, overridable via
--seed) drives which contract + mutation each case index uses. No datetime.now(),
no unseeded randomness — identical output for a given (--cases, --seed).

Report: wf.v1_5.fuzz.v1 (cases_run / rejected / accepted / crashes).
Exit 0 iff every invalid mutation was rejected, every base was accepted, and no
validator crashed.

Usage:
    python tools/pipeline/v1_5_fuzz.py --cases 300 [--seed 1505] [--strict]
Writes:
    procedural/reports/realization/v1_5_fuzz/v1_5_fuzz_report.json
"""

import argparse
import copy
import sys
from pathlib import Path
from random import Random

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import asset_paths
import asset_need_contract
import asset_candidate_contract
import asset_approval_contract
import quarantine_contract
import asset_catalog_contract
import visual_kit_contract
import realized_cover_contract
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

COMMAND = "v1_5_fuzz"
REPORT_TYPE = "wf.v1_5.fuzz.v1"
CODE = FailureCode.V1_5_FUZZ_FAILURE
DEFAULT_SEED = 1505
UNKNOWN_FIELD = "__wf_v1_5_fuzz_unknown_field__"


# -- mutation primitives ------------------------------------------------------
def _set(field, value):
    def f(r):
        r[field] = value
    return f


def _drop(field):
    def f(r):
        r.pop(field, None)
    return f


def _set_many(pairs):
    def f(r):
        for k, v in pairs:
            r[k] = v
    return f


def _add_unknown(r):
    r[UNKNOWN_FIELD] = "unexpected"


# -- per-contract targeted mutations (label, mutate_fn, requires_strict) -------
# Every entry is verified (by reading each contract's validate_record) to trip at
# least one failing check; the harness itself re-proves that at runtime.
_TARGETED = {
    "asset_need": [
        ("enum:priority", _set("priority", "__bad__"), False),
        ("enum:asset_type", _set("asset_type", "__bad__"), False),
        ("enum:minimum_quality_tier", _set("minimum_quality_tier", "__bad__"), False),
        ("negative:required_count", _set("required_count", -1), False),
        ("wrongtype:required_count_str", _set("required_count", "5"), False),
        ("wrongtype:required_count_bool", _set("required_count", True), False),
        ("wrongtype:biome_tags", _set("biome_tags", "not_a_list"), False),
        ("wrongtype:usage_tags", _set("usage_tags", 7), False),
        ("state:license_families_overlap",
         _set("disallowed_license_families", ["cc0", "fab_standard"]), False),
    ],
    "asset_candidate": [
        ("enum:candidate_status", _set("candidate_status", "__bad__"), False),
        ("enum:price_class", _set("price_class", "__bad__"), False),
        ("state:paid_without_manual", _set("price_class", "paid"), False),
        ("state:eula_without_manual", _set("eula_required", True), False),
        ("state:no_source_reference",
         _set_many([("source_url", ""), ("source_path", "")]), False),
    ],
    "asset_approval": [
        ("enum:approval_type", _set("approval_type", "__bad__"), False),
        ("state:manual_action_incomplete", _set("manual_action_completed", False), False),
        ("state:eula_marker_unset", _set("eula_accepted_by_user", False), False),
        ("state:purchase_marker_unset", _set("purchase_completed_by_user", False), False),
        ("state:third_party_standalone_redistribution",
         _set("standalone_redistribution_allowed", True), False),
    ],
    "quarantine": [
        ("state:hashes_empty", _set("hashes", {}), False),
        ("state:hashes_no_content_sha256", _set("hashes", {"md5": "abc"}), False),
        ("wrongtype:hashes", _set("hashes", "deadbeef"), False),
        ("state:path_outside_quarantine",
         _set("local_quarantine_path", "/Game/WorldForge/Final/rock"), False),
        ("state:path_empty", _set("local_quarantine_path", ""), False),
    ],
    "asset_catalog": [
        ("state:third_party_not_external_licensed",
         _set("external_licensed", False), False),
        ("state:protected_lifecycle_repair_allowed",
         _set("lifecycle_policy", {"repair_allowed": True, "destroy_allowed": True}), False),
        ("state:protected_lifecycle_destroy_allowed",
         _set("lifecycle_policy", {"repair_allowed": False, "destroy_allowed": True}), False),
    ],
    "visual_kit": [
        ("enum:biome", _set("biome", "__bad__"), False),
        ("wrongtype:sky_profile_int", _set("sky_profile", 123), False),
        ("empty:fog_profile", _set("fog_profile", ""), False),
        ("wrongtype:density_budget", _set("density_budget", "not_a_dict"), False),
        ("wrongtype:performance_budget", _set("performance_budget", 5), False),
    ],
    "realized_cover": [
        ("enum:ownership_class", _set("ownership_class", "__bad__"), False),
        ("enum:height_class", _set("height_class", "__bad__"), False),
        ("state:collision_not_block_all", _set("collision_profile", "NoCollision"), False),
        ("state:route_result_empty", _set("route_clearance_result", {}), False),
        ("state:los_result_passed_not_bool",
         _set("line_of_sight_result", {"passed": "yes"}), False),
        ("state:route_result_no_passed_key",
         _set("route_clearance_result", {"min_clearance_cm": 620.0}), False),
    ],
}

# The seven contracts, in fixed order (module carries validate_record / _example /
# REQUIRED_FIELDS).
CONTRACTS = (
    ("asset_need", asset_need_contract),
    ("asset_candidate", asset_candidate_contract),
    ("asset_approval", asset_approval_contract),
    ("quarantine", quarantine_contract),
    ("asset_catalog", asset_catalog_contract),
    ("visual_kit", visual_kit_contract),
    ("realized_cover", realized_cover_contract),
)


def build_pool(name, module):
    """Full mutation pool for one contract: drop-each-required + targeted + unknown."""
    pool = []
    for field in module.REQUIRED_FIELDS:
        pool.append(("drop:{}".format(field), _drop(field), False))
    pool.extend(_TARGETED.get(name, []))
    pool.append(("unknown_field_strict", _add_unknown, True))
    return pool


def _accepted(module, record, strict):
    """True iff every check the contract emits passes (record accepted)."""
    results = module.validate_record(record, strict=strict)
    return all(c[1] for c in results), results


def run(cases, seed, strict):
    rep = ValidationReport("fuzz", "v1_5_schemas", strict=strict)
    rng = Random(seed)

    pools = {name: build_pool(name, module) for name, module in CONTRACTS}

    # 1. Every untouched base record must be ACCEPTED.
    base_accepted = 0
    for name, module in CONTRACTS:
        base = module._example_record()
        try:
            ok, results = _accepted(module, base, strict)
        except Exception as exc:  # noqa: BLE001
            rep.check("base_validation_crash::{}".format(name), False,
                      "validate_record crashed on base record: {!r}".format(exc), code=CODE)
            continue
        failing = [c[0] for c in results if not c[1]]
        rep.check("base_accepted::{}".format(name), ok,
                  "untouched base record rejected: {}".format(failing), code=CODE)
        if ok:
            base_accepted += 1

    # 2. Distribute cases across the seven contracts (even split, remainder first).
    per = cases // len(CONTRACTS)
    extra = cases % len(CONTRACTS)
    counts = {}
    for i, (name, _m) in enumerate(CONTRACTS):
        counts[name] = per + (1 if i < extra else 0)

    cases_run = 0
    rejected = 0
    wrongly_accepted = 0
    crashes = 0
    for name, module in CONTRACTS:
        base = module._example_record()
        pool = pools[name]
        for _ in range(counts[name]):
            label, fn, needs_strict = pool[rng.randrange(len(pool))]
            sflag = True if needs_strict else strict
            rec = copy.deepcopy(base)
            fn(rec)
            cases_run += 1
            try:
                ok, _results = _accepted(module, rec, sflag)
            except Exception as exc:  # noqa: BLE001
                crashes += 1
                rep.check("fuzz_crash::{}::{}::{}".format(name, label, cases_run), False,
                          "validate_record crashed on mutation: {!r}".format(exc), code=CODE)
                continue
            if ok:
                wrongly_accepted += 1
                rep.check("fuzz_wrongly_accepted::{}::{}::{}".format(name, label, cases_run),
                          False,
                          "invalid mutation '{}' on {} was ACCEPTED (strict={})".format(
                              label, name, sflag), code=CODE)
            else:
                rejected += 1

    # 3. Summary invariants (concise green report; detail lives above on failure).
    rep.check("all_base_records_accepted", base_accepted == len(CONTRACTS),
              "{}/{} base records accepted".format(base_accepted, len(CONTRACTS)), code=CODE)
    rep.check("no_invalid_mutation_accepted", wrongly_accepted == 0,
              "{} invalid mutation(s) were wrongly accepted".format(wrongly_accepted), code=CODE)
    rep.check("no_validator_crash", crashes == 0,
              "{} validator crash(es) during fuzzing".format(crashes), code=CODE)
    rep.check("every_case_ran", cases_run == cases,
              "ran {} of {} requested cases".format(cases_run, cases), code=CODE)

    stats = {"cases_run": cases_run, "rejected": rejected,
             "accepted": wrongly_accepted, "crashes": crashes,
             "base_accepted": base_accepted}
    return rep, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 deterministic contract fuzz.")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, stats = run(args.cases, args.seed, strict)
    rep.finalize()
    rep.set_meta(build_meta(
        command=COMMAND.replace("_", "-"), strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=stats["cases_run"], records_total=stats["cases_run"],
        records_passed=stats["rejected"] + stats["base_accepted"] if rep.passed else 0,
        records_failed=stats["accepted"] + stats["crashes"],
        extra={"cases_run": stats["cases_run"],
               "rejected": stats["rejected"],
               "accepted": stats["accepted"],
               "crashes": stats["crashes"],
               "base_records_accepted": stats["base_accepted"],
               "seed": args.seed,
               "contracts_fuzzed": [n for n, _ in CONTRACTS]}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write(
        "[{}] cases_run={cases_run} rejected={rejected} accepted={accepted} "
        "crashes={crashes} base_accepted={base_accepted}/{n} seed={seed}\n".format(
            COMMAND, n=len(CONTRACTS), seed=args.seed, **stats))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
