#!/usr/bin/env python3
"""v1_5_schema_gate.py — shared runner for v1.5 record-schema validators.

Every v1.5 schema validator (asset need / procurement / candidate / approval /
quarantine / catalog / visual kit / cover binding) does the same thing: discover
the generated records of its type, run each through its contract's pure
``validate_record(record, strict) -> [(check, ok, detail, code)]`` helper, and
emit a canonical ValidationReport with a v1.5 meta block written to the exact path
full_shield's gate cross-check expects.

This is a thin shared helper, NOT a framework — it exists so the schema gates are
byte-identical in shape and so a single fix (report path, zero-record policy)
lands everywhere. Fail-closed: a schema gate with zero generated records FAILS
(records_present check) rather than passing vacuously — "no records yet" is
"not done", which is the honest Wave-1/pre-generation state.
"""

import json
from pathlib import Path

from report_meta import build_meta
from validation_report import ValidationReport, strict_from_env

REPO_ROOT = Path(__file__).resolve().parents[2]


def _report_paths(command, report_root):
    rel = "procedural/reports/{}/{}".format(report_root, command)
    return REPO_ROOT / rel, "{}_report.json".format(command)


def discover_records(record_dirs, glob="*.json"):
    """Yield (source_name, dict) for every JSON record under the given dirs.

    Returns (records, parse_errors) where parse_errors is a list of
    (name, detail) for files that failed to parse — the caller records those as
    blocking checks so a corrupt record can never be silently skipped.
    """
    records, parse_errors = [], []
    for d in record_dirs:
        base = REPO_ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.glob(glob)):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                parse_errors.append((p.name, str(exc)))
                continue
            # A file may hold one record or a list of records.
            if isinstance(data, list):
                for i, rec in enumerate(data):
                    records.append(("{}[{}]".format(p.name, i), rec))
            elif isinstance(data, dict) and isinstance(data.get("records"), list):
                for i, rec in enumerate(data["records"]):
                    records.append(("{}#records[{}]".format(p.name, i), rec))
            else:
                records.append((p.name, data))
    return records, parse_errors


def run_schema_gate(command, entity_key, report_type, contract_validate,
                    record_dirs, zero_code, pack=None, report_root="assets",
                    glob="*.json"):
    """Run a record-schema gate. Returns a process exit code (0 pass / 1 fail)."""
    strict = strict_from_env()
    rep = ValidationReport(entity_key, pack or "all", strict=strict)

    records, parse_errors = discover_records(record_dirs, glob=glob)
    for name, detail in parse_errors:
        rep.check("parse::{}".format(name), False,
                  "unparseable record: {}".format(detail), code=zero_code)

    # Fail-closed: zero records is not a vacuous pass.
    rep.check("records_present", bool(records),
              "no records under {}".format(record_dirs), code=zero_code)

    n_pass = 0
    for name, rec in records:
        rec_ok = True
        for cname, ok, detail, code in contract_validate(rec, strict=strict):
            rep.check("{}::{}".format(name, cname), ok, detail, code=code)
            rec_ok = rec_ok and ok
        n_pass += 1 if rec_ok else 0

    report_dir, filename = _report_paths(command, report_root)
    rep.set_meta(build_meta(
        command.replace("_", "-"), pack=pack, strict=strict,
        report_type=report_type, record_count=len(records),
        records_total=len(records), records_passed=n_pass,
        records_failed=len(records) - n_pass))
    rep.finalize()
    rep.write(report_dir, filename)
    rep.print_summary(command.replace("_", "-"))
    return rep.exit_code
