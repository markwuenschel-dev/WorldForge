#!/usr/bin/env python3
"""transition_hygiene.py — v2.5 transition artifact-hygiene gate (--hostile).

Proves the UE 5.8 evidence surface is free of path-hygiene drift that would make a report
non-portable or launder frozen 5.7 evidence:
  * NO absolute-path leak (drive-letter / POSIX-root) in any evidence PATH field where a
    project-relative path is required (map_path, report_path, evidence_entries, *_path[s]).
  * NO path drawn from the frozen procedural/reports/ue5_7 tree referenced by a 5.8 report.
  * NO stray writable UE transient (Saved / Intermediate / DerivedDataCache / Build tree, or
    a .sav / crash file) committed under the 5.8 report tree.

The single source-of-truth predicate is ``hygiene_findings_for_record(rec)`` (empty == clean),
dogfooded on synthetic clean/dirty records, then applied across the real committed reports.

Args: [reports_dir] (default procedural/reports/ue5_8) and --strict.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/transition_hygiene.py procedural/reports/ue5_8 --strict
Reports -> procedural/reports/ue5_8/hostile/transition_hygiene_report.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_report_integrity import path_strings  # noqa: E402  (shared extractor)
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "hostile"
DEFAULT_SCAN = "procedural/reports/ue5_8"

_ABS_PATH_RE = re.compile(r"^([A-Za-z]:[\\/]|[\\/])")
_UE5_7_FRAG = "procedural/reports/ue5_7"
# Forbidden UE-transient path SEGMENTS (matched as whole segments, not substrings, so a
# legitimately-named report like build_x_report.json does not trip "Build").
FORBIDDEN_DIRS = ("Saved", "Intermediate", "DerivedDataCache", "Build")
FORBIDDEN_SUFFIX = (".sav",)


def hygiene_findings_for_record(rec):
    """Return a list of (label, code) hygiene findings for a report/manifest dict; [] == clean."""
    f = []
    for s in path_strings(rec):
        norm = s.replace("\\", "/")
        if _ABS_PATH_RE.match(s.strip()):
            f.append(("absolute_path_leak:{}".format(s[:60]), C.TRANSITION_HYGIENE_FAILED))
        if _UE5_7_FRAG in norm:
            f.append(("ue5_7_path_referenced:{}".format(s[:60]), C.TRANSITION_HYGIENE_FAILED))
        seg = norm.split("/")
        if any(d in seg for d in FORBIDDEN_DIRS) or any(s.lower().endswith(x) for x in FORBIDDEN_SUFFIX):
            f.append(("transient_path_referenced:{}".format(s[:60]), C.TRANSITION_HYGIENE_FAILED))
    return f


def _is_transient_file(root, p):
    rel_parts = p.relative_to(root).parts
    if any(seg in FORBIDDEN_DIRS for seg in rel_parts):
        return True
    if p.suffix.lower() in FORBIDDEN_SUFFIX:
        return True
    return "crash" in p.name.lower()


def _clean_record():
    return {"maps": [{"map_path": "Content/Maps/encounter_loop_world.umap"}],
            "evidence_entries": ["procedural/reports/ue5_8/gloam/probe.json"],
            "report_paths": ["procedural/reports/ue5_8/x.json"]}


def _dirty_variants():
    return [
        ("absolute_leak_drive", lambda r: r["evidence_entries"].append("D:/Unreal/leak.json")),
        ("absolute_leak_root", lambda r: r["evidence_entries"].append("/var/tmp/leak.json")),
        ("ue5_7_ref", lambda r: r["report_paths"].append("procedural/reports/ue5_7/old.json")),
        ("saved_transient", lambda r: r["report_paths"].append("Saved/Autosaves/x.json")),
        ("sav_file", lambda r: r["evidence_entries"].append("procedural/reports/ue5_8/x.sav")),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition hygiene gate.")
    ap.add_argument("reports_dir", nargs="?", default=DEFAULT_SCAN)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "transition_hygiene", strict=strict)

    # 1. Dogfood the predicate.
    rep.check("dogfood::clean_passes", hygiene_findings_for_record(_clean_record()) == [],
              "clean record must pass: {}".format(hygiene_findings_for_record(_clean_record())),
              code=C.TRANSITION_HYGIENE_FAILED)
    for label, mut in _dirty_variants():
        bad = _clean_record()
        mut(bad)
        rep.check("dogfood::flags_{}".format(label), hygiene_findings_for_record(bad) != [],
                  "dirty record ({}) must be flagged".format(label), code=C.TRANSITION_HYGIENE_FAILED)

    # 2. Scan the real committed report tree.
    scan_root = (REPO_ROOT / args.reports_dir).resolve()
    scanned = 0
    if scan_root.is_dir():
        for p in sorted(scan_root.rglob("*")):
            if not p.is_file():
                continue
            if _is_transient_file(scan_root, p):
                rep.check("hygiene::no_transient::{}".format(p.name), False,
                          "forbidden UE transient committed under {}: {}".format(
                              args.reports_dir, p.relative_to(scan_root)),
                          code=C.TRANSITION_HYGIENE_FAILED)
            if p.suffix.lower() != ".json":
                continue
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            findings = hygiene_findings_for_record(obj)
            rep.check("hygiene::{}".format(rel), findings == [],
                      "hygiene problems: {}".format([(lbl, str(cd)) for lbl, cd in findings]),
                      code=C.TRANSITION_HYGIENE_FAILED)
            scanned += 1
    rep.check("hygiene::non_vacuous", scanned >= 1,
              "must scan >= 1 real report under {} (got {})".format(args.reports_dir, scanned),
              code=C.TRANSITION_HYGIENE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="transition-hygiene", pack=None, strict=strict, status=rep.status,
        record_count=scanned, records_total=scanned, report_type="wf.transition.hygiene.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "transition_hygiene_report.json")
    rep.print_summary("transition-hygiene")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
