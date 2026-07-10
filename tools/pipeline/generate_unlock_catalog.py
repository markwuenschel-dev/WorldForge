#!/usr/bin/env python3
"""generate_unlock_catalog.py — WorldForge v1.9 unlock-definition catalog gen.

Materializes the deterministic unlock-DEFINITION catalog from the reward_forge
spine as a SINGLE document at ``procedural/generated/rewards/unlock_catalog.json``.
Unlock definitions are distinct from runtime UnlockState — they are the vocabulary
a high-risk reward table draws its ``unlock_id`` from. The doc is only written once
every definition passes: ids unique and non-empty, ``unlock_type`` in
``RX.UNLOCK_TYPES``, and ``affects_generation`` an explicit boolean (never implied).

Report -> ``procedural/reports/rewards/catalog/generate_unlock_catalog_report.json``.

Acceptance: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_unlock_catalog.py --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
import reward_forge as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

UNLOCK_CATALOG_REL = "procedural/generated/rewards/unlock_catalog.json"
REPORT_REL = "procedural/reports/rewards/catalog"
C = FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    catalog = F.build_unlock_catalog()
    unlocks = catalog.get("unlocks") if isinstance(catalog, dict) else None

    rep.check("unlock-catalog::is_list", isinstance(unlocks, list) and len(unlocks) > 0,
              "catalog must carry a non-empty unlocks list (got {})".format(
                  type(unlocks).__name__ if unlocks is not None else None),
              code=C.UNLOCK_STATE_INVALID)

    ids = []
    if isinstance(unlocks, list):
        for i, u in enumerate(unlocks):
            uid = u.get("unlock_id") if isinstance(u, dict) else None
            utype = u.get("unlock_type") if isinstance(u, dict) else None
            ag = u.get("affects_generation") if isinstance(u, dict) else None
            rep.check("unlock-catalog::{}_id_nonempty".format(i),
                      isinstance(uid, str) and len(uid) > 0,
                      "unlock_id must be a non-empty string", code=C.UNLOCK_STATE_INVALID)
            rep.check("unlock-catalog::{}_type_known".format(uid or i),
                      utype in RX.UNLOCK_TYPES,
                      "unlock_type {!r} not in {}".format(utype, RX.UNLOCK_TYPES),
                      code=C.UNLOCK_STATE_INVALID)
            rep.check("unlock-catalog::{}_affects_generation_bool".format(uid or i),
                      isinstance(ag, bool),
                      "affects_generation must be an explicit boolean", code=C.UNLOCK_STATE_INVALID)
            ids.append(uid)
        rep.check("unlock-catalog::ids_unique", len(ids) == len(set(ids)),
                  "unlock_id must be unique across the catalog", code=C.UNLOCK_STATE_INVALID)

    if rep.passed:
        out = REPO_ROOT / UNLOCK_CATALOG_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rep.finalize()
    rep.set_meta(build_meta(command="generate-unlock-catalog", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(ids),
                            report_type="wf.reward.unlock_catalog.v1",
                            records_total=len(ids)))
    rep.write(REPO_ROOT / REPORT_REL, "generate_unlock_catalog_report.json")
    rep.print_summary("generate-unlock-catalog")
    print("[generate-unlock-catalog] {} unlock definition(s) -> {}".format(
        len(ids) if rep.passed else 0, UNLOCK_CATALOG_REL))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
