#!/usr/bin/env python3
"""npc_gen_common.py — WorldForge v1.7 NPCForge generator scaffolding.

Shared write + validate + report helper so every generator behaves identically:
each generated record is validated against its own contract at generation time
(a generator that emits a record its own validator would reject is a bug), written
to its generated root, and summarized in a v1.5-shaped report. Fails the whole run
if any record is invalid — no partial/zero-record success.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402


def write_records(records, out_rel, id_key):
    """Write each record as <id>.json under out_rel; return list of paths."""
    out_dir = REPO_ROOT / out_rel
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for rec in records:
        rid = rec[id_key]
        p = out_dir / "{}.json".format(rid)
        p.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(p)
    return paths


def run_generator(command, pack, records, validate_fn, out_rel, id_key, report_rel,
                  report_name, report_type, code, strict=None, extra_checks=None):
    """Validate every record, write them, and emit a report. sys.exit(exit_code)."""
    strict = strict_from_env() if strict is None else strict
    rep = ValidationReport("pack", pack, strict=strict)

    rep.check("{}::nonzero".format(command), len(records) > 0,
              "generator produced {} records (no zero-record success)".format(len(records)),
              code=code)
    invalid = 0
    for rec in records:
        fails = [c for c in validate_fn(rec, strict=True) if not c[1]]
        if fails:
            invalid += 1
            rep.check("{}::{}_valid".format(command, rec.get(id_key, "?")), False,
                      "invalid record {}: {}".format(rec.get(id_key), [c[0] for c in fails][:4]),
                      code=code)
    rep.check("{}::all_valid".format(command), invalid == 0,
              "{}/{} records invalid".format(invalid, len(records)), code=code)

    if extra_checks:
        for name, ok, detail, c in extra_checks:
            rep.check(name, ok, detail, code=c)

    if rep.passed:
        write_records(records, out_rel, id_key)

    rep.finalize()
    rep.set_meta(build_meta(command=command, pack=pack, strict=strict, status=rep.status,
                            record_count=len(records), report_type=report_type,
                            records_total=len(records), records_failed=invalid))
    rep.write(REPO_ROOT / report_rel, report_name)
    rep.print_summary(command)
    print("[{}] {} record(s) generated -> {}".format(command, len(records) if rep.passed else 0, out_rel))
    sys.exit(rep.exit_code)
