#!/usr/bin/env python3
"""validate_capability_manifest.py — v2.5 shield ``--capability`` gate (Lane 2).

DOGFOODS the ``CapabilityManifest`` contract (transition_contracts) AND authors +
validates a REAL declared 5.8 capability manifest:

  * engine-module / subsystem / build-tool capabilities are verified by PRESENCE
    ON DISK under ``D:/UE_5.8`` (e.g. Engine/Plugins/PCG, the Engine WorldPartition
    sources, the UnrealBuildTool binary) — available=True only when the path is
    really there;
  * the WorldForge plugin is DECLARED (availability pending Lane 1's load
    handshake). Lane 2 does NOT claim it proven-available: it is entered as
    required=False / available=False with an explicit availability_state note, so
    the manifest stays honestly GREEN without laundering an unproven capability
    into an "available" one. Lane 1 owns the load proof.

The contract's own honesty rules still bite: any REQUIRED engine capability whose
disk path is missing would flip available=False and fail the manifest (WF1011) —
that is the point.

Runtime-free gate. Report -> procedural/reports/ue5_8/validate_capability_manifest_report.json
Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_capability_manifest.py --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_identity import transition_identity  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8"

# The active UE 5.8 install root (see engine_identity.KNOWN_ENGINE_ROOTS["5.8"]).
UE58_ROOT = Path("D:/UE_5.8")

# On-disk anchors that prove an engine capability is really present in 5.8.
_DISK_ANCHORS = {
    "PCGFramework": "Engine/Plugins/PCG",
    "WorldPartition": "Engine/Source/Runtime/Engine/Private/WorldPartition",
    "UnrealBuildTool": "Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.exe",
}


def _present(rel):
    return (UE58_ROOT / rel).exists()


def build_real_manifest():
    """Author the REAL declared 5.8 capability manifest with disk-verified entries."""
    caps = [
        {"capability_id": "PCGFramework", "kind": "engine_module",
         "required": True, "available": _present(_DISK_ANCHORS["PCGFramework"]),
         "required_version": None,
         "actual_version": "5.8.0" if _present(_DISK_ANCHORS["PCGFramework"]) else None,
         "verified_on_disk": _DISK_ANCHORS["PCGFramework"]},
        {"capability_id": "WorldPartition", "kind": "editor_subsystem",
         "required": True, "available": _present(_DISK_ANCHORS["WorldPartition"]),
         "required_version": None,
         "actual_version": "5.8.0" if _present(_DISK_ANCHORS["WorldPartition"]) else None,
         "verified_on_disk": _DISK_ANCHORS["WorldPartition"]},
        {"capability_id": "UnrealBuildTool", "kind": "build_tool",
         "required": True, "available": _present(_DISK_ANCHORS["UnrealBuildTool"]),
         "required_version": None,
         "actual_version": "5.8.0" if _present(_DISK_ANCHORS["UnrealBuildTool"]) else None,
         "verified_on_disk": _DISK_ANCHORS["UnrealBuildTool"]},
        # WorldForge plugin: DECLARED only. Lane 1 owns the proven-available proof.
        {"capability_id": "WorldForgeRuntime", "kind": "plugin_module",
         "required": False, "available": False,
         "required_version": "2.5.0", "actual_version": None,
         "availability_state": "declared_pending_lane1",
         "note": "pending Lane 1 load handshake; NOT proven available by Lane 2"},
    ]
    return {
        "manifest_id": "capman_ue58_transition_lane2",
        "engine_minor": 8,
        "capabilities": caps,
        "created_by": "worldforge.v2.5.lane2",
        "created_at": TC.AUTHORING_TS,
        "schema_version": TC.RT_CAPABILITY_MANIFEST,
        "report_type": TC.RT_CAPABILITY_MANIFEST,
        "notes": "engine caps disk-verified under D:/UE_5.8; WorldForge plugin declared-only",
    }


def run(rep):
    # 1. Dogfood the CapabilityManifest contract on its fixtures.
    validate, good, bad = TC.CONTRACTS["CapabilityManifest"]
    gfails = [c for c in validate(good(), strict=True) if not c[1]]
    rep.check("dogfood::CapabilityManifest::valid_example_passes", len(gfails) == 0,
              "valid example rejected: {}".format([c[0] for c in gfails][:4]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    bfails = [c for c in validate(bad(), strict=True) if not c[1]]
    bcodes = {c[3] for c in bfails}
    owning = TC.KNOWN_BAD_OWNING_CODE["CapabilityManifest"]
    rep.check("dogfood::CapabilityManifest::known_bad_rejected", len(bfails) > 0,
              "known-bad must be rejected", code=C.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("dogfood::CapabilityManifest::rejected_for_owning_code", owning in bcodes,
              "known-bad must be rejected for {} (got {})".format(
                  owning, sorted(str(c) for c in bcodes)[:4]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    # 2. The UE 5.8 install is actually present.
    rep.check("capability::ue58_install_present", UE58_ROOT.is_dir(),
              "UE 5.8 install root missing at {}".format(UE58_ROOT),
              code=C.CAPABILITY_UNAVAILABLE)

    # 3. Author + disk-verify the REAL manifest.
    manifest = build_real_manifest()
    for cap in manifest["capabilities"]:
        anchor = cap.get("verified_on_disk")
        if anchor is not None:
            rep.check("capability::disk_present::{}".format(cap["capability_id"]),
                      cap["available"] is True,
                      "engine capability {} not found on disk at {}".format(
                          cap["capability_id"], anchor),
                      code=C.CAPABILITY_UNAVAILABLE)
    # honesty breadcrumb: the WorldForge plugin is declared-only, not claimed available.
    wf = next(c for c in manifest["capabilities"] if c["capability_id"] == "WorldForgeRuntime")
    rep.check("capability::worldforge_plugin_declared_only",
              wf["available"] is False and wf["required"] is False,
              "WorldForge plugin must be declared-only (pending Lane 1), not claimed available",
              code=C.TRANSITION_HYGIENE_FAILED)

    # 4. The real manifest satisfies the contract (GREEN).
    mfails = [c for c in validate(manifest, strict=True) if not c[1]]
    rep.check("capability::real_manifest_valid", len(mfails) == 0,
              "real 5.8 capability manifest rejected: {}".format(
                  [(c[0], c[2]) for c in mfails][:6]),
              code=C.CAPABILITY_UNAVAILABLE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 capability-manifest gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("gate", "capability_manifest", strict=strict)
    run(rep)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-capability-manifest", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.capability_manifest_gate.v1",
        extra=transition_identity("5.8", runtime_required=False,
                                  runtime_executed=False, observed_runtime_engine=None)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_capability_manifest_report.json")
    rep.print_summary("capability-manifest")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
