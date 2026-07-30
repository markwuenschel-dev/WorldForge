#!/usr/bin/env python3
"""verify_flat_plane_fixture.py — replay a Houdini fixture WITHOUT Houdini.

This is the consumer path. A support-grid test does not need Houdini installed:
Houdini's only job was to produce ``raw_observations``, and those are frozen in
the manifest. This script proves three things with plain CPython:

  1. ``content_hash`` still matches the document (the manifest is intact).
  2. ``generator.authority_module_sha256`` still matches the live
     ``tools/pipeline/support_grid_canonical.py`` (the expected block was
     derived by the SAME authority the consumer is about to test against).
  3. Re-deriving the expected block from ``raw_observations`` through
     ``support_grid_canonical.derive_grid`` reproduces it EXACTLY.

Check 2 is the important one. This fixture's resolved classes are a function of
whether ``tau_n`` is declared, so a manifest generated against a different
authority version is not merely stale — it encodes a different contract. It is
reported as STALE, not as a failure of the geometry.

**TEST INPUT ONLY.** A pass here says the fixture is self-consistent. It is not
acceptance evidence for anything and must not be wired into a shield or gate.

Run:
    python procedural/fixtures/houdini/verify_flat_plane_fixture.py
    python procedural/fixtures/houdini/verify_flat_plane_fixture.py --json

Exit codes: 0 = consistent · 1 = inconsistent · 2 = stale vs live authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTHORITY = REPO_ROOT / "tools" / "pipeline" / "support_grid_canonical.py"
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import support_grid_canonical as SG  # noqa: E402

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "flat_plane_v1.json"

EXIT_OK = 0
EXIT_INCONSISTENT = 1
EXIT_STALE = 2


def canonical_json(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def check_content_hash(doc):
    declared = doc["content_hash"]["value"]
    probe = json.loads(json.dumps(doc))
    probe["content_hash"]["value"] = ""
    actual = hashlib.sha256(canonical_json(probe).encode("utf-8")).hexdigest()
    return declared == actual, declared, actual


def check_authority(doc):
    declared = doc["generator"]["authority_module_sha256"]
    actual = hashlib.sha256(AUTHORITY.read_bytes()).hexdigest()
    return declared == actual, declared, actual


def _tuple_or_none(v):
    return None if v is None else tuple(float(c) for c in v)


def rebuild_cells(doc):
    """Reconstruct canonical RawCell objects from the frozen raw observations."""
    cells = []
    for rec in doc["raw_observations"]:
        g = rec["ground"]
        ground = SG.RawTrace(
            trace_start=_tuple_or_none(g["trace_start"]),
            trace_end=_tuple_or_none(g["trace_end"]),
            hit=g["hit"],
            impact_point=_tuple_or_none(g.get("impact_point")),
            normal=_tuple_or_none(g.get("normal")),
            actor_path=g.get("actor_path"),
            component_path=g.get("component_path"),
            failure=g.get("failure"),
        )
        h = rec.get("head")
        head = None
        if h is not None:
            head = SG.RawTrace(
                trace_start=_tuple_or_none(h["trace_start"]),
                trace_end=_tuple_or_none(h["trace_end"]),
                hit=h["hit"],
                impact_point=_tuple_or_none(h.get("impact_point")),
                normal=_tuple_or_none(h.get("normal")),
                failure=h.get("failure"),
            )
        cells.append(SG.RawCell(i=rec["i"], j=rec["j"], ground=ground, head=head))
    return cells


def check_rederivation(doc):
    """Re-derive expectations from raw observations; return list of mismatches."""
    req = doc["survey_request"]
    result = SG.derive_grid(
        rebuild_cells(doc),
        (req["anchor_xyz_cm"][0], req["anchor_xyz_cm"][1]),
        req["radius_cm"], req["step_cm"],
        sample_region_shape=req["sample_region_shape"])

    exp = doc["expected"]
    bad = []

    def cmp(name, expected, actual):
        if expected != actual:
            bad.append("{}: manifest={!r} rederived={!r}".format(
                name, expected, actual))

    cmp("k", exp["k"], result.k)
    cmp("nominal_sample_count", exp["nominal_sample_count"], result.nominal_count)
    cmp("tau_n_evaluated", exp["tau_n_evaluated"], result.tau_n_evaluated)
    cmp("class_counts", exp["class_counts"], result.counts())

    got_cells = [{"i": c.i, "j": c.j, "supported": c.supported,
                  "pass1_class": c.pass1_class, "edge": c.edge,
                  "edge_terms": list(c.edge_terms),
                  "resolved_class": c.resolved_class, "reason": c.reason}
                 for c in result.cells]
    cmp("support_classes", exp["support_classes"], got_cells)

    cmp("edge_cells", [list(x) for x in exp["edge_cells"]],
        [[c.i, c.j] for c in result.cells if c.edge is True])
    cmp("indeterminate_edge_cells", [list(x) for x in exp["indeterminate_edge_cells"]],
        [list(x) for x in result.indeterminate_indices()])
    cmp("unsupported_regions", [list(x) for x in exp["unsupported_regions"]],
        [[c.i, c.j] for c in result.cells if c.supported is False])
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fixture", nargs="?", default=str(DEFAULT_FIXTURE))
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    doc = json.loads(Path(args.fixture).read_text(encoding="utf-8"))

    hash_ok, hash_declared, hash_actual = check_content_hash(doc)
    auth_ok, auth_declared, auth_actual = check_authority(doc)
    mismatches = check_rederivation(doc)

    if not hash_ok or mismatches:
        status, code = "INCONSISTENT", EXIT_INCONSISTENT
    elif not auth_ok:
        status, code = "STALE_VS_LIVE_AUTHORITY", EXIT_STALE
    else:
        status, code = "CONSISTENT", EXIT_OK

    report = {
        "fixture": str(Path(args.fixture)),
        "fixture_id": doc.get("fixture_id"),
        "fixture_version": doc.get("fixture_version"),
        "role": doc.get("role"),
        "status": status,
        "content_hash_ok": hash_ok,
        "content_hash_declared": hash_declared,
        "content_hash_actual": hash_actual,
        "authority_hash_ok": auth_ok,
        "authority_hash_declared": auth_declared,
        "authority_hash_live": auth_actual,
        "rederivation_mismatches": mismatches,
        "tau_n_deg_in_manifest": doc["tolerances"]["tau_n_deg"],
        "tau_n_deg_live": SG.CONTRACT_TOLERANCES.tau_n_deg,
        "class_counts": doc["expected"]["class_counts"],
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("fixture        {}".format(report["fixture_id"]))
        print("status         {}".format(status))
        print("content hash   {}".format("OK" if hash_ok else
                                         "MISMATCH {} != {}".format(
                                             hash_declared, hash_actual)))
        print("authority hash {}".format(
            "OK" if auth_ok else
            "STALE  manifest={}  live={}".format(auth_declared[:16],
                                                 auth_actual[:16])))
        print("tau_n_deg      manifest={!r}  live={!r}".format(
            report["tau_n_deg_in_manifest"], report["tau_n_deg_live"]))
        print("re-derivation  {}".format(
            "EXACT MATCH" if not mismatches else
            "{} MISMATCH(ES)".format(len(mismatches))))
        for m in mismatches:
            print("   - {}".format(m))
        print("class counts   {}".format(report["class_counts"]))
        if status == "STALE_VS_LIVE_AUTHORITY":
            print("\nThe geometry is fine; the expected block was derived by a "
                  "different version of support_grid_canonical.py.\n"
                  "Regenerate with hython — do NOT reconcile by hand.")
    return code


if __name__ == "__main__":
    sys.exit(main())
