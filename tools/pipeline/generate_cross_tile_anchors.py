#!/usr/bin/env python3
"""generate_cross_tile_anchors.py — v2.3 Wave 2 cross-tile anchor authoring (Agent 3).

Emits the per-region CrossTileAnchor records from streaming_spec.anchor_plan:
region entry/exit anchors, per-tile npc_spawn + save_checkpoint, mission_objective
anchors on hub/objective tiles, and reciprocal transition-anchor PAIRS at every tile
boundary. Deterministic; each anchor validated against its contract before writing.

Deliverables:  procedural/generated/anchors/*.json
Report:        procedural/reports/streaming/authoring/anchor_authoring_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_cross_tile_anchors.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
import streaming_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

ANCHORS_DIR = REPO_ROOT / "procedural" / "generated" / "anchors"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "authoring"


def generate(rep):
    ANCHORS_DIR.mkdir(parents=True, exist_ok=True)
    all_ids = set()
    plans = []
    for region in SPEC.REGIONS:
        plans.extend(SPEC.anchor_plan(region))
    for ap in plans:
        all_ids.add(ap["anchor_id"])

    n = 0
    for ap in plans:
        anchor = SC._example_cross_tile_anchor(**{k: ap[k] for k in (
            "anchor_id", "region_id", "tile_id", "anchor_type", "world_location",
            "linked_anchor_ids", "route_role", "mission_role", "npc_role",
            "save_load_key", "tile_role")})
        fails = [c for c in SC.validate_cross_tile_anchor(anchor, strict=True) if not c[1]]
        rep.check("anchor::{}::valid".format(ap["anchor_id"]), len(fails) == 0,
                  "anchor invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_ANCHOR_INVALID)
        # reciprocity: every linked anchor must exist and link back.
        for linked in ap["linked_anchor_ids"]:
            rep.check("anchor::{}::link_resolves::{}".format(ap["anchor_id"], linked),
                      linked in all_ids, "linked anchor {} does not resolve".format(linked),
                      code=F.STREAMING_ANCHOR_LINK_BROKEN)
            partner = next((p for p in plans if p["anchor_id"] == linked), None)
            rep.check("anchor::{}::reciprocal::{}".format(ap["anchor_id"], linked),
                      partner is not None and ap["anchor_id"] in partner["linked_anchor_ids"],
                      "linked anchor {} must link back".format(linked),
                      code=F.STREAMING_ANCHOR_LINK_BROKEN)
        (ANCHORS_DIR / (ap["anchor_id"] + ".json")).write_text(
            json.dumps(anchor, indent=2, sort_keys=True), encoding="utf-8")
        n += 1

    rep.check("anchors::nonempty", n >= 12, "expected >= 12 anchors (got {})".format(n),
              code=F.STREAMING_ANCHOR_INVALID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 cross-tile anchor generator.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-cross-tile-anchors", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.anchor_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "anchor_authoring_report.json")
    rep.print_summary("generate-cross-tile-anchors")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
