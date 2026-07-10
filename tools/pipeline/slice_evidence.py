#!/usr/bin/env python3
"""slice_evidence.py — v2.0 shared slice runtime-evidence access helpers.

The runtime/package/integrity gates all read the same slice evidence trees and
must agree on: what counts as evidence, how many scenarios are expected, and how
a report maps back to a manifest scenario. Centralizing that here keeps the ~10
gates DRY and prevents them from drifting on the fail-closed threshold.

Evidence layout (produced by Wave R / Wave P; absent until the UE runs):
    procedural/reports/slice/runtime/slice_runtime_<ssid>.json   SliceRuntimeReport
    procedural/reports/slice/save_load/slice_save_load_<ssid>.json
    procedural/reports/slice/package/slice_package_<slice_id>.json
    procedural/reports/slice/integrity/slice_evidence_index_<slice_id>.json

Until the UE runtime runs, the runtime tree is empty, so every gate that requires
the full matrix fail-closes RED — the honest state, never fake-green.
"""

import json
from pathlib import Path

import slice_contracts as SX

REPO_ROOT = Path(__file__).resolve().parents[2]
# single source of truth (slice_contracts) — no bare literal here.
EXPECTED_SCENARIOS = SX.EXPECTED_SCENARIOS

RUNTIME_DIR = REPO_ROOT / SX.SLICE_RUNTIME_REPORTS_REL
SAVE_LOAD_DIR = REPO_ROOT / SX.SLICE_SAVE_LOAD_REPORTS_REL
PACKAGE_DIR = REPO_ROOT / SX.SLICE_PACKAGE_REPORTS_REL
INTEGRITY_DIR = REPO_ROOT / SX.SLICE_INTEGRITY_REPORTS_REL


def manifest_scenario_ids():
    """The authoritative set of expected slice_scenario_ids (from the manifest)."""
    mpath = REPO_ROOT / SX.SLICE_MANIFEST_REL
    if not mpath.is_file():
        return []
    m = json.loads(mpath.read_text(encoding="utf-8"))
    return list(m.get("scenarios", []))


def load_reports(directory, prefix):
    """Return [(path, dict) ...] for prefix*.json in directory (parse-safe)."""
    d = Path(directory)
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob(prefix + "*.json")):
        if p.name.startswith("validate_") or p.name.endswith("_report.json"):
            continue  # skip sibling validator-output reports
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001
            out.append((p, None))
    return out


def runtime_reports():
    return load_reports(RUNTIME_DIR, "slice_runtime_")


def telemetry_path_exists(rel_path):
    """A telemetry_path string resolves to a real file under the repo."""
    if not isinstance(rel_path, str) or not rel_path:
        return False
    return (REPO_ROOT / rel_path).is_file()


def facet_gate(rep, facet_fn, need, missing_code, partial_code):
    """Shared runtime-facet scan: apply facet_fn(doc)->(ok, detail) to every
    SliceRuntimeReport, require `need` to pass, fail-closed on an empty tree.

    facet_fn receives a parsed report dict and returns (ok, detail). Returns the
    count of scenarios that passed the facet.
    """
    reports = runtime_reports()
    passed = 0
    seen = []
    for path, doc in reports:
        stem = path.stem
        if doc is None:
            rep.check("facet::{}::parses".format(stem), False,
                      "unparseable runtime report", code=missing_code)
            continue
        ssid = doc.get("slice_scenario_id", stem)
        seen.append(ssid)
        ok, detail = facet_fn(doc)
        rep.check("facet::{}".format(ssid), ok, detail, code=missing_code)
        if ok:
            passed += 1
    rep.check("facet::matrix_complete", passed >= need,
              "{}/{} scenarios satisfy this facet (needs {}) — run Wave R (UE) "
              "to produce runtime evidence".format(passed, len(reports), need),
              code=partial_code)
    rep.check("facet::no_duplicates", len(seen) == len(set(seen)),
              "duplicate scenario runtime reports", code=partial_code)
    return passed
