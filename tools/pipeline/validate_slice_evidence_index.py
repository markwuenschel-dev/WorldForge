#!/usr/bin/env python3
"""validate_slice_evidence_index.py — v2.0 Agent-3/7 evidence-index gate.

Proves the SliceEvidenceIndex covers all 24 scenarios: it validates the index file
against the schema and cross-checks scenario_count_seen == expected == 24 with no
missing/stale entries. The index is the single artifact an operator inspects to
answer "is every scenario proven?". Fail-closed RED until Wave R writes it.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_evidence_index.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/integrity/validate_slice_evidence_index_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
import slice_evidence as SE
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / SX.SLICE_INTEGRITY_REPORTS_REL
SLICE_ID = "worldforge_vertical_slice"


def _dogfood(rep):
    ids = ["vs_scn_{:02d}".format(i) for i in range(24)]  # 24 DISTINCT ids
    good = SX._example_slice_evidence_index(
        scenario_count_expected=24, scenario_count_seen=24,
        runtime_reports=list(ids), traversal_reports=list(ids),
        npc_reports=list(ids), combat_reports=list(ids),
        reward_reports=list(ids), save_load_reports=list(ids))
    gfails = [c for c in SX.validate_slice_evidence_index(good, strict=True) if not c[1]]
    rep.check("dogfood::good_index_passes", len(gfails) == 0,
              "reference index rejected: {}".format([c[0] for c in gfails][:4]),
              code=F.SLICE_REPORT_INTEGRITY_FAILED)
    for label, over in (
            ("partial", {"scenario_count_seen": 23, "runtime_reports": list(ids[:23])}),
            ("stale", {"stale_evidence": ["vs_x"]}),
            ("missing", {"missing_evidence": ["vs_x"]}),
            # coverage by DUPLICATE ids is not coverage (the C1 fake-green class):
            ("duplicate_ids", {"runtime_reports": ["s"] * 24, "traversal_reports": ["s"] * 24,
                               "npc_reports": ["s"] * 24, "combat_reports": ["s"] * 24,
                               "reward_reports": ["s"] * 24, "save_load_reports": ["s"] * 24})):
        bad = dict(good)
        bad.update(over)
        bfails = [c for c in SX.validate_slice_evidence_index(bad, strict=True) if not c[1]]
        rep.check("dogfood::rejects_{}".format(label), len(bfails) > 0,
                  "'{}' index must be rejected".format(label), code=F.SLICE_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice evidence-index gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    idx_path = SE.INTEGRITY_DIR / "slice_evidence_index_{}.json".format(SLICE_ID)
    rep.check("index_present", idx_path.is_file(),
              "evidence index missing — run Wave R to produce it ({})".format(idx_path.name),
              code=F.SLICE_EVIDENCE_INDEX_INVALID)
    if idx_path.is_file():
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        for name, ok, detail, code in SX.validate_slice_evidence_index(idx, strict=True):
            rep.check("index::{}".format(name), ok, detail, code=code)
        rep.check("index::covers_24",
                  idx.get("scenario_count_seen") == SE.EXPECTED_SCENARIOS
                  and idx.get("scenario_count_expected") == SE.EXPECTED_SCENARIOS,
                  "evidence index must cover all 24 scenarios", code=F.SLICE_PARTIAL_MATRIX)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-evidence-index", pack=args.pack, strict=strict,
                            status=rep.status, record_count=1,
                            report_type="wf.slice.evidence_index_gate.v1"))
    rep.write(REPORT_DIR, "validate_slice_evidence_index_report.json")
    rep.print_summary("validate-slice-evidence-index")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
