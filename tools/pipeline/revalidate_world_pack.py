#!/usr/bin/env python3
"""revalidate_world_pack.py — WorldForge v1.0x post-lifecycle re-validation (Agent 0).

After a destroy -> rebuild (or repair) lifecycle, prove the pack has genuinely
returned to green by re-running the core validation gates and requiring ALL of
them to pass. This is the "revalidate" step of the lifecycle contract and a
child gate of full-shield (torture path).

It is a thin, honest aggregator: it shells the canonical validator entrypoints
(same CLI contract as everywhere) and fails if any required gate is missing or
non-zero. A missing validator is a blocking failure, never a silent skip.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta  # noqa: E402
from world_pack_maps import enumerate_maps, report_dir_for  # noqa: E402

PY = sys.executable

# Core gates that MUST be green again after a lifecycle. Each: (id, script, args, code).
# args use {yaml} for the world pack yaml path or {id} for the pack id.
CORE_GATES = [
    ("validate-world-pack-spec", "validate_world_pack_spec.py", "{yaml}", FailureCode.CONTRACT_FAILURE),
    ("validate-world-pack", "validate_world_pack.py", "{yaml}", FailureCode.CONTRACT_FAILURE),
    ("validate-environment-contract", "validate_environment_contract.py", "{id}", FailureCode.ENVIRONMENT_PROFILE_FAILURE),
    ("validate-pois", "validate_pois.py", "{id}", FailureCode.POI_USABILITY_FAILURE),
    ("validate-entity-anchors", "validate_entity_anchors.py", "{id}", FailureCode.ENTITY_ANCHOR_FAILURE),
    ("validate-report-integrity", "validate_report_integrity.py", "{id}", FailureCode.REPORT_INTEGRITY_FAILURE),
]


def _run(script, pack_arg, strict, deep):
    path = PIPELINE / script
    if not path.is_file():
        return None, "validator missing: %s" % script
    argv = [PY, str(path), "--pack", pack_arg]
    if strict:
        argv.append("--strict")
    if deep and script == "validate_world_pack.py":
        argv.append("--deep")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if strict:
        env["STRICT"] = "1"
    proc = subprocess.run(argv, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-2:])[:300]
    return proc.returncode, tail


def main(argv=None):
    ap = argparse.ArgumentParser(description="Re-validate a world pack returned to green after lifecycle.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--deep", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    world_pack_id, maps = enumerate_maps(args.pack)
    yaml_arg = "procedural/world_packs/%s.yaml" % args.pack

    # Overlays are generated-owned artifacts a destroy step may have removed;
    # regenerate them (best-effort) so the overlay-consuming validators have
    # their inputs. Missing generators are simply skipped here — the validators
    # will then FAIL loudly on absent overlays, which is the honest outcome.
    for gen in ("generate_level_design.py", "generate_entity_anchors.py"):
        if (PIPELINE / gen).is_file():
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            subprocess.run([PY, str(PIPELINE / gen), "--pack", args.pack],
                           cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)

    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    for gid, script, argtmpl, code in CORE_GATES:
        pack_arg = yaml_arg if argtmpl == "{yaml}" else args.pack
        rc, detail = _run(script, pack_arg, strict, args.deep)
        if rc is None:
            rep.check(gid, False, detail, code=FailureCode.VALIDATOR_SKIPPED)
        else:
            rep.check(gid, rc == 0, detail or ("exit %s" % rc), code=code)

    rep.set_meta(build_meta(command="revalidate-world-pack", pack=world_pack_id,
                            strict=strict, status=None, record_count=len(CORE_GATES)))
    rep.finalize()
    rep.write(report_dir_for(world_pack_id), "revalidate_world_pack_report.json")
    rep.print_summary("revalidate-world-pack")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
