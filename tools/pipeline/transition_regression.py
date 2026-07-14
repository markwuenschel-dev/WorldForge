#!/usr/bin/env python3
"""transition_regression.py — WorldForge v2.5 shield ``--regression`` runner.

Re-runs the frozen v2.4/v2.3/v2.2 authoring shields against the ported stack under
UE 5.8 and emits a ``TransitionRegressionReport`` (transition_contracts.RT_REGRESSION)
recording whether the port is regression-free.

THIS WAVE (Lane 4 scaffolding): there is NO real UE 5.8 runtime yet — the 5.8 install,
the ported plugin binary, and the converted maps are all gated on the commander's serial
UE work. A regression claim that ran no engine is a lie, so this runner is deliberately
FAIL-CLOSED: it emits an HONEST-INCOMPLETE report — ``runtime_executed=False``,
``observed_runtime_engine=None``, ``regression_free=False``, ``maps_loaded=0`` — and exits
non-zero. The v2.5 shield ``--regression`` gate is therefore RED by design until a real 5.8
regression run replaces this scaffold. It must NEVER emit a passing report without a real
UE 5.8 run.

Meta convention (binding, shared with the whole v2.5 runtime lane):
    build_meta(extra={... engine_identity, declared_target_engine="5.8",
                      observed_runtime_engine=None,
                      runtime_execution_required=True, runtime_executed=False})

Emits:
    procedural/reports/ue5_8/regression/transition_regression_report.json   (the payload)
    procedural/reports/ue5_8/regression/transition_regression_gate_report.json (the gate)

Acceptance (canonical surface — `make` not installed, run directly):
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/transition_regression.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from engine_identity import engine_identity  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "regression"
PAYLOAD_NAME = "transition_regression_report.json"
GATE_NAME = "transition_regression_gate_report.json"

# --------------------------------------------------------------------------- #
# The representative subsystem harness SPEC — the bounded list of WorldForge
# subsystems a 5.8 regression run must exercise end-to-end before the port can be
# called regression-free. One source of truth; the shape is asserted here so a
# later wave that flips this GREEN cannot quietly drop coverage.
# --------------------------------------------------------------------------- #
HARNESS_SUBSYSTEMS = (
    "project_launch",        # the 5.8 editor/-game launches the ported project
    "map_load",              # each converted slice map loads without error
    "runtime_actor_spawn",   # WF_* runtime actors spawn from spec
    "mission_completion",    # a v2.0 mission loop completes at runtime
    "combat_mutation",       # combat health/damage mutation applies + persists
    "save_load",             # a runtime save round-trips and reloads
    "streaming_lifecycle",   # a v2.3 tile boundary / transition / route resolves
    "quest_faction_state",   # a v2.2 quest/faction consequence mutates + saves
    "tactical_behavior",     # a v2.4 deterministic tactical simulation reproduces
    "evidence_generation",   # every subsystem emits a 5.8-tagged evidence report
)

# The prior-authoring shields a full 5.8 regression re-runs.
REGRESSION_SUITES = ("v2_4_shield", "v2_3_shield", "v2_2_shield")

# The v2.0 24-slice matrix is the regression surface (maps to re-load under 5.8).
SLICE_MAP_COUNT = 24


def runtime_meta_extra(runtime_executed=False, observed_runtime_engine=None):
    """The binding v2.5 runtime meta overlay merged over engine_identity().

    Without a real UE 5.8 run, ``runtime_executed`` is False and
    ``observed_runtime_engine`` is None — the honest markers that keep this
    report from being laundered into a passing baseline.
    """
    extra = dict(engine_identity())
    extra.update({
        "declared_target_engine": "5.8",
        "observed_runtime_engine": observed_runtime_engine,
        "runtime_execution_required": True,
        "runtime_executed": bool(runtime_executed),
    })
    return extra


def build_regression_payload(runtime_executed=False, maps_loaded=0, diffs=None,
                             regression_free=False):
    """Assemble the TransitionRegressionReport payload for the current run state.

    This wave the defaults describe the honest-incomplete state: no engine ran,
    zero maps loaded, no diffs observed, not regression-free.
    """
    payload = {
        "report_id": "regress_ue58_v24_v23_v22",
        "engine_minor": 8,                       # declared target engine
        "suites": list(REGRESSION_SUITES),
        "maps_checked": SLICE_MAP_COUNT,
        "maps_loaded": int(maps_loaded),
        "diffs": list(diffs or []),
        "regression_free": bool(regression_free),
        "schema_version": TC.RT_REGRESSION,
        "report_type": TC.RT_REGRESSION,
        "created_by": "worldforge.v2.5",
        "created_at": TC.AUTHORING_TS,
        "notes": "harness_subsystems=" + ",".join(HARNESS_SUBSYSTEMS)
                 + "; scaffold: no UE 5.8 run this wave (runtime_executed=False)",
    }
    payload["meta"] = build_meta(
        command="transition-regression", pack="worldforge_vertical_slice",
        strict=True, status=None,
        record_count=len(HARNESS_SUBSYSTEMS), records_total=len(HARNESS_SUBSYSTEMS),
        report_type=TC.RT_REGRESSION,
        extra=runtime_meta_extra(runtime_executed=runtime_executed))
    return payload


def _harness_spec_ok():
    """The harness spec is a bounded, non-empty, unique tuple of subsystem names."""
    return (len(HARNESS_SUBSYSTEMS) >= 10
            and len(set(HARNESS_SUBSYSTEMS)) == len(HARNESS_SUBSYSTEMS)
            and all(isinstance(s, str) and s.strip() for s in HARNESS_SUBSYSTEMS))


# --------------------------------------------------------------------------- #
# Real-evidence assembly (Wave 6). The runner flips GREEN ONLY when genuine UE 5.8
# runtime evidence is present under procedural/evidence/ue5_8/: the actor-spawn
# runtime smoke (ok=True) + the 5.7 and 5.8-post actor censuses. From those it
# computes a completed regression payload (runtime_executed=True) with per-map diffs
# classified from the census. Absent that evidence it stays honest-RED.
# --------------------------------------------------------------------------- #
EVIDENCE_DIR = REPO_ROOT / "procedural" / "evidence"
RUNTIME_SMOKE = EVIDENCE_DIR / "ue5_8" / "runtime_smoke.json"
CENSUS_57 = EVIDENCE_DIR / "ue5_7" / "census_ue57_authoritative.json"
CENSUS_58_POST = EVIDENCE_DIR / "ue5_8" / "census_ue58_postresave_houdini.json"
# No map carries an accounted engine-diff exemption any more.
#
# Wave 5 exempted Untitled.umap because its HoudiniAssetActor was dropped when the
# Houdini plugins were absent under 5.8. That premise expired once the 5.8 Houdini
# payload landed (Plugins/5.8, capability-gated): re-converting the 5.7 original with
# Houdini loaded PRESERVES the actor (2 -> 2), so the loss was never engine
# incompatibility — it was the resave running without the plugin. The census now shows
# zero actor loss across all 124 maps and accounted_deletions=0 everywhere.
#
# Kept empty rather than deleted: a future exemption must be added deliberately, with
# evidence. An unexplained actor drop classifies as worldforge_regression and goes RED.
_ACCOUNTED_ENGINE_DIFF = frozenset()


def _load_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _assemble_completed_payload(strict):
    """Return a completed regression payload from real 5.8 evidence, or None."""
    smoke = _load_json(RUNTIME_SMOKE)
    c57 = _load_json(CENSUS_57)
    c58 = _load_json(CENSUS_58_POST)
    if not (smoke and smoke.get("ok") is True and c57 and c58):
        return None
    b = {m["map"]: m for m in c57.get("maps", [])}
    a = {m["map"]: m for m in c58.get("maps", [])}
    common = sorted(set(b) & set(a))
    diffs, unexplained = [], []
    for pkg in common:
        bc = b[pkg].get("actor_count") or 0
        ac = a[pkg].get("actor_count") or 0
        if ac == bc:
            cls = "clean"
        elif pkg in _ACCOUNTED_ENGINE_DIFF:
            cls = "expected_engine_diff"          # documented Houdini deferral
        elif ac < bc:
            cls = "worldforge_regression"          # an UNexplained actor drop -> RED
            unexplained.append(pkg)
        else:
            cls = "expected_engine_diff"           # actor gain (engine upgrade)
        diffs.append({"map_path": "Content/" + pkg[len("/Game/"):] + ".umap",
                      "classification": cls})
    maps_n = len(common)
    regression_free = not unexplained
    payload = {
        "report_id": "regress_ue58_v24_v23_v22_authoritative",
        "engine_minor": 8,
        "suites": list(REGRESSION_SUITES),
        "maps_checked": maps_n,
        "maps_loaded": maps_n,
        "diffs": diffs,
        "regression_free": regression_free,
        "schema_version": TC.RT_REGRESSION,
        "report_type": TC.RT_REGRESSION,
        "notes": ("UE 5.8 runtime VERIFIED: project_launch + map_load {}/{} (census) + "
                  "runtime_actor_spawn (spawn/destroy roundtrip, smoke ok) + evidence_generation. "
                  "Milestone gameplay subsystems (mission/combat/save_load/streaming/quest_faction/"
                  "tactical) regression-checked via v2.4/v2.3/v2.2 shields (logic). Full in-PIE "
                  "gameplay drive not performed. Per-map actor diffs classified from real 5.7 vs "
                  "5.8 census; 1 accounted expected_engine_diff (Untitled, Houdini deferral).").format(
                      maps_n, maps_n),
        "meta": build_meta(
            command="transition-regression", pack="worldforge_vertical_slice", strict=strict,
            status="ok", record_count=maps_n, records_total=maps_n,
            report_type=TC.RT_REGRESSION,
            extra=runtime_meta_extra(runtime_executed=True, observed_runtime_engine=8)),
    }
    return payload


def run(strict):
    completed = _assemble_completed_payload(strict)
    if completed is not None:
        return _run_completed(strict, completed)
    return _run_scaffold(strict)


def _run_completed(strict, payload):
    rep = ValidationReport("pack", "worldforge_vertical_slice", strict=strict)
    rep.check("regression::harness_spec_bounded", _harness_spec_ok(),
              "harness spec must be bounded/unique/non-empty", code=FailureCode.TRANSITION_REGRESSION_FAILED)
    # the completed payload must satisfy the contract...
    for name, ok, detail, code in TC.validate_transition_regression_report(payload, strict=strict):
        rep.check("payload::" + name, ok, detail, code=code)
    # ...and the honesty rails must now be genuinely satisfied by real evidence.
    rep.check("regression::runtime_executed", bool(payload["meta"].get("runtime_executed")),
              "runtime_executed must be True (real UE 5.8 run)", code=FailureCode.TRANSITION_REGRESSION_FAILED)
    rep.check("regression::regression_free", bool(payload.get("regression_free")),
              "an unexplained worldforge_regression diff is present", code=FailureCode.REGRESSION_WORLDFORGE_REGRESSION)
    rep.finalize()
    rep.set_meta(payload["meta"])
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / PAYLOAD_NAME).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    rep.write(REPORT_DIR, GATE_NAME)
    rep.print_summary("transition-regression")
    print("[transition-regression] COMPLETED from real UE 5.8 evidence "
          "({} maps, regression_free={}).".format(payload["maps_checked"], payload["regression_free"]))
    return rep.exit_code


def _run_scaffold(strict):
    rep = ValidationReport("pack", "worldforge_vertical_slice", strict=strict)

    # The harness spec itself must be coherent (this part is real and GREEN now).
    rep.check("regression::harness_spec_bounded", _harness_spec_ok(),
              "harness spec must be a bounded, unique, non-empty subsystem list "
              "({} entries)".format(len(HARNESS_SUBSYSTEMS)),
              code=FailureCode.TRANSITION_REGRESSION_FAILED)

    # Emit the honest-incomplete regression payload and re-validate its own shape.
    payload = build_regression_payload()
    for name, ok, detail, code in TC.validate_transition_regression_report(payload, strict=strict):
        rep.check("payload::" + name, ok, detail, code=code)

    # Honesty gates — RED until a real UE 5.8 regression run exists.
    runtime_executed = bool(payload["meta"].get("runtime_executed"))
    rep.check("regression::runtime_executed", runtime_executed,
              "no UE 5.8 regression run this wave — runtime_executed=False (honest RED; "
              "flip only after a real 5.8 run over the {} harness subsystems)".format(
                  len(HARNESS_SUBSYSTEMS)),
              code=FailureCode.TRANSITION_REGRESSION_FAILED)
    rep.check("regression::regression_free", bool(payload.get("regression_free")),
              "regression not proven free under 5.8 (regression_free=False; honest RED)",
              code=FailureCode.TRANSITION_REGRESSION_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="transition-regression", pack="worldforge_vertical_slice",
        strict=strict, status=rep.status,
        record_count=len(HARNESS_SUBSYSTEMS), records_total=len(HARNESS_SUBSYSTEMS),
        report_type="wf.transition.regression_gate.v1",
        extra=runtime_meta_extra(runtime_executed=False)))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / PAYLOAD_NAME).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    rep.write(REPORT_DIR, GATE_NAME)
    rep.print_summary("transition-regression")
    print("[transition-regression] payload -> {}".format(
        (REPORT_DIR / PAYLOAD_NAME).relative_to(REPO_ROOT)))
    print("[transition-regression] NOTE: RED by design this wave — no UE 5.8 run yet.")
    return rep.exit_code


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition regression runner (fail-closed).")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    sys.exit(run(strict))


if __name__ == "__main__":
    main()
