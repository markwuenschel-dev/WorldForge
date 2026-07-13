#!/usr/bin/env python3
"""build_transition_baseline.py — v2.5 one-time UE 5.8 baseline BUILDER (gated).

Builds the ``TransitionBaseline`` evidence index (transition_contracts.RT_BASELINE):
the frozen snapshot of the 5.8-tagged reports that certify the port. Building a baseline
is a one-way, high-trust act — a baseline laundered from 5.7 evidence or built before the
port actually passed would poison every downstream trust claim. So this builder is
DOUBLE-GATED and refuses by default:

  GATE 1 (authorization): the file
      procedural/reports/ue5_8/baseline/AUTHORIZED
  must exist. The commander creates it in Wave 8 after the serial UE 5.8 work lands. This
  tool NEVER creates it.

  GATE 2 (completed regression): a COMPLETED regression report must be present —
      procedural/reports/ue5_8/regression/transition_regression_report.json
  with meta.runtime_executed == True AND regression_free == True AND passing the
  TransitionRegressionReport contract. This wave the regression is honest-incomplete
  (runtime_executed=False), so even a present AUTHORIZED file would not suffice.

Either gate unmet -> print "baseline not authorized" (with the specific reason) and exit
non-zero WITHOUT writing anything. When both gates pass, it scans the ue5_8 evidence tree
for 5.8-tagged reports, assembles the baseline index, validates it against the contract,
and only then writes procedural/reports/ue5_8/baseline/baseline_index.json.

Usage:
    PYTHONUTF8=1 python tools/pipeline/build_transition_baseline.py [--force-scan-empty-ok]
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from report_meta import build_meta  # noqa: E402

UE58_REPORTS = REPO_ROOT / "procedural" / "reports" / "ue5_8"
BASELINE_DIR = UE58_REPORTS / "baseline"
AUTHORIZED_PATH = BASELINE_DIR / "AUTHORIZED"
REGRESSION_PATH = UE58_REPORTS / "regression" / "transition_regression_report.json"
BASELINE_INDEX_PATH = BASELINE_DIR / "baseline_index.json"


def _refuse(reason):
    print("baseline not authorized")
    print("  reason: {}".format(reason))
    print("  Wave-8 prerequisites to authorize a baseline build:")
    print("    1. {} must exist (commander creates it after 5.8 UE work).".format(
        AUTHORIZED_PATH.relative_to(REPO_ROOT)))
    print("    2. {} must be a COMPLETED regression:".format(
        REGRESSION_PATH.relative_to(REPO_ROOT)))
    print("       meta.runtime_executed == True AND regression_free == True AND "
          "contract-valid.")
    return 2


def _completed_regression_reason():
    """Return None if a completed regression is present, else the blocking reason."""
    if not REGRESSION_PATH.is_file():
        return "no regression report at {}".format(REGRESSION_PATH.relative_to(REPO_ROOT))
    try:
        payload = json.loads(REGRESSION_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return "regression report unparseable: {}".format(exc)
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not (isinstance(meta, dict) and meta.get("runtime_executed") is True):
        return "regression report has runtime_executed != True (no real UE 5.8 run)"
    if payload.get("regression_free") is not True:
        return "regression report regression_free != True"
    fails = [c for c in TC.validate_transition_regression_report(payload, strict=True) if not c[1]]
    if fails:
        return "regression report fails its contract: {}".format([c[0] for c in fails][:4])
    return None


def _scan_baseline_entries():
    """Scan the ue5_8 tree for 5.8-tagged reports and build baseline entries.

    Only reports whose meta.engine_minor == 8 (the engine that RAN them) are
    eligible; the baseline dir itself is excluded so it never indexes itself.
    """
    entries = []
    for path in sorted(UE58_REPORTS.rglob("*.json")):
        if BASELINE_DIR in path.parents or path == BASELINE_INDEX_PATH:
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = obj.get("meta") if isinstance(obj, dict) else None
        if not isinstance(meta, dict) or meta.get("engine_minor") != 8:
            continue
        entries.append({
            "report_path": path.relative_to(REPO_ROOT).as_posix(),
            "engine_minor": 8,
            "report_type": meta.get("report_type") or obj.get("schema_version"),
        })
    return entries


def build(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 one-time UE 5.8 baseline builder (gated).")
    ap.add_argument("--force-scan-empty-ok", action="store_true",
                    help="permit writing a baseline even if the scan finds no entries")
    args, _ = ap.parse_known_args(argv)

    # GATE 1 — authorization file.
    if not AUTHORIZED_PATH.is_file():
        return _refuse("authorization file absent: {}".format(
            AUTHORIZED_PATH.relative_to(REPO_ROOT)))

    # GATE 2 — completed regression.
    reason = _completed_regression_reason()
    if reason is not None:
        return _refuse(reason)

    # Both gates passed — assemble, validate, then write the baseline index.
    entries = _scan_baseline_entries()
    if not entries and not args.force_scan_empty_ok:
        print("baseline not authorized")
        print("  reason: scan found no 5.8-tagged (meta.engine_minor==8) reports to index")
        return 2

    index = {
        "index_id": "baseline_ue58_v2_5",
        "engine_minor": 8,
        "entry_count": len(entries),
        "entries": entries,
        "schema_version": TC.RT_BASELINE,
        "report_type": TC.RT_BASELINE,
        "created_by": "worldforge.v2.5",
        "created_at": TC.AUTHORING_TS,
        "meta": build_meta(command="build-transition-baseline",
                           pack="worldforge_vertical_slice", strict=True, status="ok",
                           record_count=len(entries), records_total=len(entries),
                           report_type=TC.RT_BASELINE,
                           extra={"engine_minor": 8, "declared_target_engine": "5.8",
                                  "observed_runtime_engine": "5.8",
                                  "runtime_execution_required": True,
                                  "runtime_executed": True}),
    }
    fails = [c for c in TC.validate_transition_baseline(index, strict=True) if not c[1]]
    if fails:
        print("baseline build refused: assembled index fails its own contract: {}".format(
            [c[0] for c in fails][:6]))
        return 1

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    with BASELINE_INDEX_PATH.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("baseline written -> {} ({} entries)".format(
        BASELINE_INDEX_PATH.relative_to(REPO_ROOT), len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(build())
