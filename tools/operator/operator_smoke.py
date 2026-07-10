#!/usr/bin/env python3
"""operator_smoke.py — v2.1 OperatorForge dashboard smoke + broken-link gate (Wave 3).

Proves the static dashboard actually exists, is non-empty, and does not carry a
single broken link — a dashboard that links to a report that isn't there is the
operator-facing form of fake-green.

Checks (FAIL-CLOSED — absent dashboard is RED):
  * the index page + pack page + one page per v2.0 scenario are present & non-empty
  * every page carries the expected structural markers (<title>, wrap, foot)
  * EVERY relative href/link across all pages resolves to a real file on disk
    (WF735 OPERATOR_LINK_BROKEN) — links into the evidence tree are checked too
  * the dashboard is not stale vs the index: every page's embedded git_sha matches
    the current operator_report_index.json git_sha (WF734 OPERATOR_DASHBOARD_STALE)

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/operator_smoke.py --strict
Reports -> procedural/reports/operator/dashboard/operator_smoke_report.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

DASH = REPO_ROOT / "procedural" / "reports" / "operator" / "dashboard"
INDEX_FILE = REPO_ROOT / "procedural" / "reports" / "operator" / "index" / "operator_report_index.json"
MANIFEST = REPO_ROOT / "procedural/generated/slice/manifest.json"

_HREF_RE = re.compile(r'href="([^"]+)"')
_SHA_RE = re.compile(r"git_sha <code>([0-9a-f]+)</code>")


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator dashboard smoke gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("operator", "dashboard_smoke", strict=strict)

    index_html = DASH / "index.html"
    rep.check("dashboard_present", index_html.is_file(),
              "dashboard/index.html missing — run operator-dashboard first",
              code=F.OPERATOR_DASHBOARD_MISSING)
    if not index_html.is_file():
        rep.finalize()
        rep.set_meta(build_meta("operator-smoke", pack=None, strict=strict,
                                status=rep.status, record_count=0, records_total=0,
                                report_type="wf.operator.smoke.v1"))
        DASH.mkdir(parents=True, exist_ok=True)
        rep.write(DASH, "operator_smoke_report.json")
        rep.print_summary("operator-smoke")
        sys.exit(rep.exit_code)

    cur_sha = (_load(INDEX_FILE).get("git_sha", "") if INDEX_FILE.is_file() else "")[:12]
    manifest = _load(MANIFEST) if MANIFEST.is_file() else {"scenarios": []}

    pages = sorted(DASH.rglob("*.html"))
    rep.check("pages_present", len(pages) >= 2 + len(manifest.get("scenarios", [])),
              "expected index + pack + {} scenario pages (got {})".format(
                  len(manifest.get("scenarios", [])), len(pages)),
              code=F.OPERATOR_DASHBOARD_MISSING)

    # one page per scenario must exist
    for ssid in manifest.get("scenarios", []):
        p = DASH / "scenarios" / "{}.html".format(ssid)
        rep.check("scenario_page::{}".format(ssid), p.is_file(),
                  "missing scenario page: {}".format(ssid),
                  code=F.OPERATOR_DASHBOARD_MISSING)

    broken = 0
    stale = 0
    for page in pages:
        text = page.read_text(encoding="utf-8")
        rep.check("nonempty::{}".format(page.name), len(text) > 200,
                  "page too small: {}".format(page.name), code=F.OPERATOR_DASHBOARD_MISSING)
        rep.check("markers::{}".format(page.name),
                  "<title>" in text and 'class="wrap"' in text and 'class="foot"' in text,
                  "page missing structural markers: {}".format(page.name),
                  code=F.OPERATOR_DASHBOARD_MISSING)
        # staleness: embedded sha must match the current index sha.
        m = _SHA_RE.search(text)
        if cur_sha and m and m.group(1) != cur_sha:
            stale += 1
        # broken links: every relative href must resolve.
        for href in _HREF_RE.findall(text):
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target = (page.parent / href).resolve()
            if not target.exists():
                broken += 1
                rep.check("link::{}::{}".format(page.name, href.split("/")[-1]), False,
                          "broken link in {}: {}".format(page.name, href),
                          code=F.OPERATOR_LINK_BROKEN)

    rep.check("no_broken_links", broken == 0,
              "{} broken link(s) across dashboard".format(broken),
              code=F.OPERATOR_LINK_BROKEN)
    rep.check("dashboard_not_stale", stale == 0,
              "{} page(s) with a git_sha != current index sha ({})".format(stale, cur_sha),
              code=F.OPERATOR_DASHBOARD_STALE)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-smoke", pack=None, strict=strict, status=rep.status,
        record_count=len(pages), records_total=len(pages),
        report_type="wf.operator.smoke.v1"))
    rep.write(DASH, "operator_smoke_report.json")
    rep.print_summary("operator-smoke")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
