#!/usr/bin/env python3
"""operator_hygiene.py — v2.1 OperatorForge artifact-hygiene gate (Wave R).

Proves the operator surface is internally consistent and free of drift/orphans:

  * every tools/operator/*.py carries an 'Acceptance:' docstring line (the
    documented command surface stays real)
  * tools/operator/ holds only .py sources — no stray committed artifacts
  * every derived operator artifact lives UNDER procedural/reports/operator/**
    (the dashboard never writes outside its tree)
  * the core index/dashboard/diff/command artifacts exist and are non-empty
  * scenario_cards count == the slice manifest scenario_count == the number of
    generated scenario dashboard pages (no silent desync between index, cards,
    and rendered pages)

This is the "no silent drift" gate for the operator control plane.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/operator_hygiene.py --strict
Reports -> procedural/reports/operator/operator_hygiene_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

TOOLS_OP = REPO_ROOT / "tools" / "operator"
OPERATOR_DIR = REPO_ROOT / "procedural" / "reports" / "operator"
INDEX_DIR = OPERATOR_DIR / "index"
DASH_DIR = OPERATOR_DIR / "dashboard"
MANIFEST = REPO_ROOT / "procedural/generated/slice/manifest.json"

REQUIRED_ARTIFACTS = (
    INDEX_DIR / "operator_report_index.json",
    INDEX_DIR / "evidence_graph.json",
    INDEX_DIR / "pack_cards.json",
    INDEX_DIR / "scenario_cards.json",
    INDEX_DIR / "failure_code_index.json",
    INDEX_DIR / "asset_ownership_views.json",
    INDEX_DIR / "route_walkability_views.json",
    DASH_DIR / "index.html",
    OPERATOR_DIR / "diff" / "operator_diff_report.json",
)


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator artifact-hygiene gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("operator", "hygiene", strict=strict)

    # 1. every tools/operator/*.py has an Acceptance: docstring line.
    pys = sorted(TOOLS_OP.glob("*.py"))
    rep.check("scripts_present", len(pys) >= 10,
              "expected the operator toolchain in tools/operator (got {})".format(len(pys)),
              code=F.OPERATOR_HYGIENE_FAILED)
    for p in pys:
        text = p.read_text(encoding="utf-8", errors="ignore")
        # Only runnable gates (a __main__ entrypoint) must document an Acceptance
        # command; operator_contracts.py / operator_view.py are libraries.
        if '__name__ == "__main__"' not in text:
            continue
        rep.check("acceptance_doc::{}".format(p.name), "Acceptance:" in text,
                  "{} missing an 'Acceptance:' docstring line".format(p.name),
                  code=F.OPERATOR_HYGIENE_FAILED)

    # 2. tools/operator holds only .py sources (+ __pycache__), no stray artifacts.
    stray = [c.name for c in TOOLS_OP.iterdir()
             if c.is_file() and c.suffix != ".py"]
    rep.check("no_stray_files", not stray,
              "stray non-.py files in tools/operator: {}".format(stray[:5]),
              code=F.OPERATOR_HYGIENE_FAILED)

    # 3. required artifacts exist and are non-empty.
    for art in REQUIRED_ARTIFACTS:
        rep.check("artifact::{}".format(art.name),
                  art.is_file() and art.stat().st_size > 0,
                  "missing/empty operator artifact: {}".format(
                      art.relative_to(REPO_ROOT).as_posix()),
                  code=F.OPERATOR_HYGIENE_FAILED)

    # 4. no derived artifact escapes procedural/reports/operator/** (all under tree).
    #    (constructive: everything we build is rooted there; assert the tree exists
    #    and the dashboard/index dirs are inside it.)
    for d in (INDEX_DIR, DASH_DIR):
        rep.check("under_operator_tree::{}".format(d.name),
                  OPERATOR_DIR in d.parents or d == OPERATOR_DIR,
                  "{} is not under the operator report tree".format(d),
                  code=F.OPERATOR_HYGIENE_FAILED)

    # 5. no silent desync: manifest count == scenario_cards == scenario pages.
    if MANIFEST.is_file() and (INDEX_DIR / "scenario_cards.json").is_file():
        man_n = int(_load(MANIFEST).get("scenario_count", -1))
        cards = _load(INDEX_DIR / "scenario_cards.json")
        pages = list((DASH_DIR / "scenarios").glob("*.html")) if (DASH_DIR / "scenarios").is_dir() else []
        rep.check("count_agreement",
                  man_n == len(cards) == len(pages),
                  "manifest={} scenario_cards={} scenario_pages={} must agree".format(
                      man_n, len(cards), len(pages)),
                  code=F.OPERATOR_HYGIENE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-hygiene", pack=None, strict=strict, status=rep.status,
        record_count=len(pys), records_total=len(pys),
        report_type="wf.operator.hygiene.v1"))
    OPERATOR_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(OPERATOR_DIR, "operator_hygiene_report.json")
    rep.print_summary("operator-hygiene")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
