#!/usr/bin/env python3
"""validate_engine_identity.py — v2.5 shield ``--engine-identity`` gate (Lane 2).

Two jobs, one gate:

  1. DOGFOOD the ``EngineIdentity`` contract from transition_contracts.CONTRACTS —
     its canonical-valid example passes with zero failures and its known-bad is
     rejected for the owning code (ENGINE_VERSION_MISMATCH). The REAL identity
     block engine_identity() emits in THIS worktree is also run through the
     contract so the schema is dogfooded on live data, not just fixtures.

  2. Enforce the commander meta-identity honesty convention on a report's meta
     block (declared_target_engine / observed_runtime_engine /
     runtime_execution_required / runtime_executed + worktree fingerprint). The
     gate REJECTS, each for a clear owning code:
        * a 5.8-declared report carrying a 5.7 OBSERVED runtime  -> WF1031
        * a runtime_execution_required report with observed=None -> WF1013
        * a runtime-FREE report claiming runtime_executed=True   -> WF1037
        * an absolute-path leak in an identity fingerprint field -> WF1029
        * a report whose worktree_identifier is the wrong worktree -> WF1034

  A runtime-FREE report that host-resolves to engine_minor=7 (the uproject
  fallback) is explicitly NOT contamination and must PASS — that separation is
  the whole point of the convention.

Runtime-free gate: meta carries runtime_execution_required=False,
runtime_executed=False, observed_runtime_engine=None.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_engine_identity.py --strict
Report -> procedural/reports/ue5_8/validate_engine_identity_report.json
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from engine_identity import IDENTITY_KEYS, engine_identity  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_identity import (  # noqa: E402
    CONVENTION_KEYS, declared_minor, transition_identity, worktree_identifier)
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8"

_ABS_PATH_RE = re.compile(r"^([A-Za-z]:[\\/]|[\\/])")
# Identity fingerprint fields that must never carry an absolute path.
_FINGERPRINT_FIELDS = ("worktree_identifier", "repository_identifier",
                       "project_path_identity")


def _no_abs(value):
    return isinstance(value, str) and not _ABS_PATH_RE.match(value.strip())


def validate_convention(meta, expected_worktree):
    """Return (name, ok, detail, code) tuples enforcing the honesty convention.

    ``expected_worktree`` is this worktree's fingerprint; a report whose
    worktree_identifier differs came from the wrong worktree.
    """
    ch = []
    # -- shape: the four convention keys present + well-typed --------------- #
    dt = meta.get("declared_target_engine")
    ch.append(("conv::declared_target_present",
               isinstance(dt, str) and bool(dt.strip()),
               "declared_target_engine must be a non-empty string (got {!r})".format(dt),
               C.EVIDENCE_ENGINE_MISMATCH))
    req = meta.get("runtime_execution_required")
    exe = meta.get("runtime_executed")
    obs = meta.get("observed_runtime_engine")
    ch.append(("conv::required_is_bool", isinstance(req, bool),
               "runtime_execution_required must be a bool (got {!r})".format(req),
               C.TRANSITION_HYGIENE_FAILED))
    ch.append(("conv::executed_is_bool", isinstance(exe, bool),
               "runtime_executed must be a bool (got {!r})".format(exe),
               C.TRANSITION_HYGIENE_FAILED))
    ch.append(("conv::observed_int_or_none",
               obs is None or (isinstance(obs, int) and not isinstance(obs, bool)),
               "observed_runtime_engine must be an int minor or None (got {!r})".format(obs),
               C.EVIDENCE_ENGINE_MISMATCH))
    want = declared_minor(dt if isinstance(dt, str) else "")
    # -- honesty: runtime-required implies an observed, matching engine ----- #
    if req is True:
        ch.append(("conv::required_implies_observed", obs is not None,
                   "runtime_execution_required=True but observed_runtime_engine is None",
                   C.ENGINE_VERSION_MISMATCH))
        ch.append(("conv::observed_matches_declared",
                   obs is None or want is None or obs == want,
                   "observed_runtime_engine {!r} != declared minor {!r} (contamination)".format(obs, want),
                   C.EVIDENCE_ENGINE_MISMATCH))
    else:
        # honesty: a runtime-FREE report may not claim it executed a UE runtime.
        ch.append(("conv::free_implies_not_executed", exe is not True,
                   "runtime-free report (required=False) claims runtime_executed=True",
                   C.TRANSITION_HYGIENE_FAILED))
    # -- hygiene: no absolute-path leak in the identity fingerprint fields -- #
    for f in _FINGERPRINT_FIELDS:
        v = meta.get(f)
        ch.append(("conv::no_abs_leak::{}".format(f),
                   v is None or _no_abs(v),
                   "identity field {} leaks an absolute path: {!r}".format(f, v),
                   C.BRIDGE_ABSOLUTE_PATH_LEAK))
    # -- integrity: the report must come from THIS worktree ----------------- #
    wt = meta.get("worktree_identifier")
    ch.append(("conv::worktree_matches_this_tree", wt == expected_worktree,
               "report worktree_identifier {!r} != this worktree {!r}".format(wt, expected_worktree),
               C.TRANSITION_REPORT_INTEGRITY_FAILED))
    return ch


# Inline convention fixtures. good() passes; each bad must be rejected for its
# stated owning code. Built by mutating a valid meta so a single wrong field is
# the sole cause of rejection.
def _good_meta():
    return transition_identity("5.8", runtime_required=False,
                               runtime_executed=False, observed_runtime_engine=None)


_CONVENTION_KNOWN_BAD = {
    # 5.8 declared, but a real runtime run OBSERVED 5.7 -> WF1031.
    "declared_5_8_observed_5_7": (
        lambda: transition_identity("5.8", runtime_required=True,
                                    runtime_executed=True, observed_runtime_engine=7),
        C.EVIDENCE_ENGINE_MISMATCH),
    # runtime required but nothing was observed -> WF1013.
    "required_but_observed_none": (
        lambda: transition_identity("5.8", runtime_required=True,
                                    runtime_executed=True, observed_runtime_engine=None),
        C.ENGINE_VERSION_MISMATCH),
    # runtime-free report pretending it executed a UE runtime -> WF1037.
    "free_but_pretends_executed": (
        lambda: {**_good_meta(), "runtime_executed": True},
        C.TRANSITION_HYGIENE_FAILED),
    # absolute-path leak in the worktree fingerprint -> WF1029.
    "abs_path_leak_in_identity": (
        lambda: {**_good_meta(), "worktree_identifier": "D:/Unreal Projects/WorldForge-UE58"},
        C.BRIDGE_ABSOLUTE_PATH_LEAK),
    # report fingerprinted to a different worktree -> WF1034.
    "wrong_worktree": (
        lambda: {**_good_meta(), "worktree_identifier": "deadbeefcafe:SomeOtherTree"},
        C.TRANSITION_REPORT_INTEGRITY_FAILED),
}


def _real_identity_block():
    """The live engine_identity() block, shaped as the EngineIdentity contract."""
    block = {k: engine_identity().get(k) for k in IDENTITY_KEYS}
    block["schema_version"] = TC.RT_ENGINE_IDENTITY
    block["report_type"] = TC.RT_ENGINE_IDENTITY
    return block


def run(rep):
    this_wt = worktree_identifier()

    # 1. Dogfood the EngineIdentity contract (fixtures).
    validate, good, bad = TC.CONTRACTS["EngineIdentity"]
    gfails = [c for c in validate(good(), strict=True) if not c[1]]
    rep.check("dogfood::EngineIdentity::valid_example_passes", len(gfails) == 0,
              "valid example rejected: {}".format([c[0] for c in gfails][:4]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    bfails = [c for c in validate(bad(), strict=True) if not c[1]]
    bcodes = {c[3] for c in bfails}
    owning = TC.KNOWN_BAD_OWNING_CODE["EngineIdentity"]
    rep.check("dogfood::EngineIdentity::known_bad_rejected", len(bfails) > 0,
              "EngineIdentity known-bad must be rejected",
              code=C.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("dogfood::EngineIdentity::rejected_for_owning_code", owning in bcodes,
              "EngineIdentity known-bad must be rejected for {} (got {})".format(
                  owning, sorted(str(c) for c in bcodes)[:4]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    # 2. Dogfood the contract on the REAL live identity block.
    rfails = [c for c in validate(_real_identity_block(), strict=True) if not c[1]]
    rep.check("dogfood::EngineIdentity::live_block_passes", len(rfails) == 0,
              "live engine_identity block rejected by contract: {}".format(
                  [(c[0], c[2]) for c in rfails][:4]),
              code=C.ENGINE_VERSION_MISMATCH)

    # 3. Convention holds on a real, honest, runtime-free meta.
    cfails = [c for c in validate_convention(_good_meta(), this_wt) if not c[1]]
    rep.check("convention::real_runtime_free_meta_passes", len(cfails) == 0,
              "honest runtime-free meta rejected: {}".format(
                  [(c[0], c[2]) for c in cfails][:4]),
              code=C.TRANSITION_HYGIENE_FAILED)

    # 4. Every known-bad meta is rejected FOR its owning code.
    for name, (factory, owning_code) in _CONVENTION_KNOWN_BAD.items():
        fails = [c for c in validate_convention(factory(), this_wt) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("negative::{}::rejected".format(name), len(fails) > 0,
                  "known-bad convention meta must be rejected",
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)
        rep.check("negative::{}::rejected_for_owning_code".format(name),
                  owning_code in codes,
                  "must be rejected for {} (got {})".format(
                      owning_code, sorted(str(c) for c in codes)[:4]),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 engine-identity honesty gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("gate", "engine_identity", strict=strict)
    run(rep)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-engine-identity", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.engine_identity_gate.v1",
        extra=transition_identity("5.8", runtime_required=False,
                                  runtime_executed=False, observed_runtime_engine=None)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_engine_identity_report.json")
    rep.print_summary("engine-identity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
