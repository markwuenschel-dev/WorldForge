#!/usr/bin/env python3
"""inspect_houdini_intake.py — WorldForge v1.2 addendum operator utility.

Read-only. Shows what the Houdini-generated slice of the mesh catalog actually
IS. Houdini is a GENERATED backend (addendum §1/§5): the baked/imported
StaticMesh WorldForge produces is generated_owned, but the source HDA must NOT
be assumed generated-owned — it is project_owned or third_party_owned. A
houdini_generated asset is a normal MeshForge mesh asset that additionally
carries a ``houdini_intake`` block plus cook/bake/import reports. With
--diagnose it classifies every problem into the addendum's HOUDINI_* failure
buckets so an operator sees which lane is red without opening every descriptor.
It mirrors the console + JSON-report habit of inspect_mesh_catalog.py; it is NOT
a generator and NOT part of any create/validate contract. It joins:

    procedural/generated/worldforge_mesh_catalog.json          — the catalog
    procedural/generated/mesh_assets/<id>/descriptor.json      — houdini_intake
    procedural/reports/mesh_assets/<id>/{cook,bake,import}_report.json

Three modes (addendum §12):
    inspect-houdini-intake   default: human summary + JSON report, exit 0
    inspect-houdini-asset    --asset <id>: full houdini dossier, exit 0
                             (2 if unknown / not houdini)
    diagnose-houdini-intake  --diagnose: classify problems into HOUDINI_*
                             buckets, exit 0 if clean, 1 if any

    PYTHONUTF8=1 python tools/pipeline/inspect_houdini_intake.py --pack biome_expansion_world
    PYTHONUTF8=1 python tools/pipeline/inspect_houdini_intake.py --pack biome_expansion_world --asset mesh_rock_houdini_desert_boulder
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/inspect_houdini_intake.py --pack biome_expansion_world --diagnose --strict
"""

import argparse
import json
import os
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC  # noqa: E402
import houdini_contract as HC  # noqa: E402
from mesh_catalog import load_mesh_catalog, catalog_content_hash  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, strict_from_env, hash_obj  # noqa: E402

REPORT_KEYS = ("cook_report", "bake_report", "import_report")


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------
def _load_json(path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_descriptor(asset_id):
    return _load_json(MC.mesh_descriptor_path(asset_id, REPO_ROOT))


def _resolve_report(ref):
    """A cook/bake/import report entry is either an inline dict or a path string
    pointing at the report JSON. Resolve to the report dict, or None if absent."""
    if isinstance(ref, dict):
        return ref
    if isinstance(ref, str) and ref:
        p = Path(ref) if os.path.isabs(ref) else (REPO_ROOT / ref)
        return _load_json(p)
    return None


def _report_status(intake, key):
    """Return (present, ok) for one report key of a houdini_intake block."""
    report = _resolve_report(intake.get(key))
    if report is None:
        return False, False
    return True, HC.report_ok(report)


# ---------------------------------------------------------------------------
# inspect-houdini-intake
# ---------------------------------------------------------------------------
def _summary_data(pack, catalog):
    hda_ids = set()
    hda_ownership = Counter()
    report_present = {k: 0 for k in REPORT_KEYS}
    report_ok = {k: 0 for k in REPORT_KEYS}
    final_path = Counter()
    registry = Counter()
    provenance = Counter()
    package = Counter()
    validation = Counter()

    asset_ids = []
    for aid, entry in HC.iter_houdini_assets(catalog):
        asset_ids.append(aid)
        descriptor = _load_descriptor(aid) or {}
        intake = HC.houdini_intake_block(descriptor) or HC.houdini_intake_block(entry)

        hid = intake.get("hda_id")
        if hid:
            hda_ids.add(hid)
        hda_ownership[intake.get("hda_ownership_class") or "(unset)"] += 1

        for k in REPORT_KEYS:
            present, ok = _report_status(intake, k)
            report_present[k] += int(present)
            report_ok[k] += int(ok)

        fp = descriptor.get("final_asset_path") or entry.get("final_asset_path")
        if MC.is_forbidden_final_path(fp):
            final_path["forbidden"] += 1
        elif MC.is_allowed_final_path(fp):
            final_path["allowed"] += 1
        else:
            final_path["not_owned"] += 1

        registry["present" if (descriptor.get("registry_id") or entry.get("registry_id"))
                 else "missing"] += 1
        provenance["present" if (descriptor.get("provenance_id") or entry.get("provenance_id"))
                   else "missing"] += 1
        package[entry.get("package_status") or "(unset)"] += 1
        validation[entry.get("validation_status") or "(unset)"] += 1

    return {
        "pack": pack,
        "generated_output_count": len(asset_ids),
        "asset_ids": asset_ids,
        "distinct_hda_count": len(hda_ids),
        "hda_ids": sorted(hda_ids),
        "by_hda_ownership_class": OrderedDict(sorted(hda_ownership.items())),
        "cook_report": {"present": report_present["cook_report"], "ok": report_ok["cook_report"]},
        "bake_report": {"present": report_present["bake_report"], "ok": report_ok["bake_report"]},
        "import_report": {"present": report_present["import_report"], "ok": report_ok["import_report"]},
        "final_path_status": OrderedDict(sorted(final_path.items())),
        "registry_status": OrderedDict(sorted(registry.items())),
        "provenance_status": OrderedDict(sorted(provenance.items())),
        "package_status": OrderedDict(sorted(package.items())),
        "validation_status": OrderedDict(sorted(validation.items())),
    }


def _print_counter(title, mapping, indent="    "):
    print("  %s" % title)
    if not mapping:
        print("%s(none)" % indent)
        return
    for key, n in mapping.items():
        print("%s%-30s %d" % (indent, key, n))


def cmd_inspect_intake(pack, catalog, strict):
    data = _summary_data(pack, catalog)
    n = data["generated_output_count"]

    print("=" * 72)
    print("INSPECT-HOUDINI-INTAKE  pack=%s  (%d houdini asset(s))" % (pack, n))
    print("=" * 72)
    print("  distinct HDA count  %d" % data["distinct_hda_count"])
    if data["hda_ids"]:
        print("    %s" % ", ".join(data["hda_ids"]))
    print("  generated output count  %d" % n)
    _print_counter("HDA ownership classes:", data["by_hda_ownership_class"])
    print("  Report status (present / ok, out of %d):" % n)
    for k in REPORT_KEYS:
        print("    %-16s present=%d  ok=%d" % (k, data[k]["present"], data[k]["ok"]))
    _print_counter("Final path status:", data["final_path_status"])
    _print_counter("Registry status:", data["registry_status"])
    _print_counter("Provenance status:", data["provenance_status"])
    _print_counter("Package status:", data["package_status"])
    _print_counter("Validation status:", data["validation_status"])

    meta = build_meta(
        command="inspect-houdini-intake", pack=pack, strict=strict,
        status="ok", record_count=n,
        input_spec_hash=catalog_content_hash(catalog),
        output_manifest_hash=hash_obj(data),
        extra={"summary": data},
    )
    report = {"pack": pack, "summary": data, "meta": meta}
    _write_report("inspect_houdini_intake", "inspect_houdini_intake_report.json", report)
    return 0


# ---------------------------------------------------------------------------
# inspect-houdini-asset
# ---------------------------------------------------------------------------
def cmd_inspect_asset(pack, catalog, asset_id, strict):
    entry = (catalog.get("assets") or {}).get(asset_id)
    descriptor = _load_descriptor(asset_id)
    if entry is None and descriptor is None:
        sys.stderr.write("asset not found in catalog or on disk: %s\n" % asset_id)
        return 2
    if not HC.is_houdini_asset(entry) and not HC.is_houdini_asset(descriptor):
        sys.stderr.write("asset is not houdini_generated: %s\n" % asset_id)
        return 2

    d = descriptor or {}
    intake = HC.houdini_intake_block(d) or HC.houdini_intake_block(entry)

    print("=" * 72)
    print("INSPECT-HOUDINI-ASSET  %s  (pack=%s)" % (asset_id, pack))
    print("=" * 72)
    if descriptor is None:
        print("  WARNING: descriptor.json missing on disk — catalog record only")

    ce = entry or {}
    print("  %-24s %s" % ("final_asset_path", d.get("final_asset_path") or ce.get("final_asset_path")))
    print("  %-24s %s" % ("generated_owned", d.get("generated_owned")))
    print("  %-24s %s" % ("registry_id", d.get("registry_id") or ce.get("registry_id")))
    print("  %-24s %s" % ("provenance_id", d.get("provenance_id") or ce.get("provenance_id")))
    print("  %-24s %s" % ("package_status", ce.get("package_status")))
    print("  %-24s %s" % ("validation_status", ce.get("validation_status")))
    print("  houdini_intake:")
    for k in HC.HOUDINI_INTAKE_REQUIRED:
        if k in REPORT_KEYS:
            continue
        v = intake.get(k)
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        print("    %-22s %s" % (k, v))
    print("  reports (present / ok):")
    report_status = {}
    for k in REPORT_KEYS:
        present, ok = _report_status(intake, k)
        report_status[k] = {"present": present, "ok": ok, "ref": intake.get(k)}
        print("    %-16s present=%s  ok=%s  ref=%s" % (k, present, ok, intake.get(k)))

    dossier = {"asset_id": asset_id, "houdini_intake": intake,
               "report_status": report_status,
               "final_asset_path": d.get("final_asset_path") or ce.get("final_asset_path"),
               "catalog_entry": entry}
    meta = build_meta(
        command="inspect-houdini-asset", pack=pack, strict=strict,
        status="ok", record_count=1,
        input_spec_hash=hash_obj(intake),
        extra={"asset_id": asset_id},
    )
    report = {"pack": pack, "asset": dossier, "meta": meta}
    _write_report("inspect_houdini_intake",
                  "inspect_houdini_asset_%s_report.json" % asset_id, report)
    return 0


# ---------------------------------------------------------------------------
# diagnose-houdini-intake
# ---------------------------------------------------------------------------
DIAGNOSE_BUCKETS = (
    ("intake", FailureCode.HOUDINI_SOURCE_FAILURE),
    ("hda-ownership", FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE),
    ("cook", FailureCode.HOUDINI_COOK_FAILURE),
    ("bake", FailureCode.HOUDINI_BAKE_FAILURE),
    ("import", FailureCode.HOUDINI_IMPORT_FAILURE),
    ("final-path", FailureCode.MESH_FINAL_PATH_FAILURE),
    ("registry", FailureCode.HOUDINI_OUTPUT_REGISTRY_FAILURE),
    ("provenance", FailureCode.HOUDINI_OUTPUT_PROVENANCE_FAILURE),
    # Who WROTE the report. Presence and status say nothing about authorship,
    # and this dossier previously reported total_problems=0 over reports the
    # pipeline had written itself. Same classifier as the gate -- imported, not
    # reimplemented, so the dossier and the gate can never disagree.
    ("evidence", FailureCode.HOUDINI_COOK_EVIDENCE_SELF_AUTHORED),
)

_REPORT_BUCKET = {"cook_report": "cook", "bake_report": "bake", "import_report": "import"}

# ONE authorship classifier, shared with validate_houdini_cook_evidence.py. A
# second copy here is exactly how a dossier comes to disagree with its gate.
from validate_houdini_cook_evidence import classify as _cook_evidence_state


def _classify_houdini(asset_id, entry):
    """Re-check one houdini_generated asset. Return list of (bucket, detail).

    A valid houdini asset (intake present, non-generated HDA ownership, ok
    cook/bake/import reports, owned final path, registry + provenance) returns []."""
    problems = []
    descriptor = _load_descriptor(asset_id)
    d = descriptor or {}
    intake = HC.houdini_intake_block(d) or HC.houdini_intake_block(entry)

    # intake block must exist.
    if not intake:
        problems.append(("intake", "missing houdini_intake block"))
        return problems  # nothing else is trustworthy without the intake block

    # HDA ownership: NEVER generated-owned; must be project_/third_party_owned.
    own = intake.get("hda_ownership_class")
    if own == "generated_owned":
        problems.append(("hda-ownership", "hda_ownership_class is generated_owned (wrong: HDA source is not generated)"))
    elif own not in HC.HDA_OWNERSHIP_CLASSES:
        problems.append(("hda-ownership", "invalid hda_ownership_class: %r" % own))

    # cook / bake / import reports must be present and status-ok.
    for key in REPORT_KEYS:
        bucket = _REPORT_BUCKET[key]
        report = _resolve_report(intake.get(key))
        if report is None:
            problems.append((bucket, "missing %s" % key))
        elif HC.report_failed(report):
            problems.append((bucket, "%s status is failed" % key))
        elif not HC.report_ok(report):
            problems.append((bucket, "%s status not ok: %r" % (key, report.get("status"))))
        if report is not None:
            state, detail = _cook_evidence_state(report)
            if state != "resolved":
                problems.append(("evidence", "%s is %s: %s" % (key, state, detail)))

    # final path must be owned and not a Houdini Temp/Bake leak.
    fp = d.get("final_asset_path") or entry.get("final_asset_path")
    if MC.is_forbidden_final_path(fp):
        problems.append(("final-path", "forbidden final path (Temp/Bake): %r" % fp))
    elif not MC.is_allowed_final_path(fp):
        problems.append(("final-path", "final path not under an owned root: %r" % fp))

    # registry + provenance for the generated output.
    if not (d.get("registry_id") or entry.get("registry_id")):
        problems.append(("registry", "missing registry_id"))
    if not (d.get("provenance_id") or entry.get("provenance_id")):
        problems.append(("provenance", "missing provenance_id"))

    return problems


def cmd_diagnose(pack, catalog, strict):
    houdini = list(HC.iter_houdini_assets(catalog))
    found = {label: [] for label, _ in DIAGNOSE_BUCKETS}

    for aid, entry in houdini:
        for bucket, detail in _classify_houdini(aid, entry):
            found[bucket].append((aid, detail))

    total_problems = sum(len(v) for v in found.values())

    print("=" * 72)
    print("DIAGNOSE-HOUDINI-INTAKE  pack=%s  (%d houdini asset(s), %d problem(s))" % (
        pack, len(houdini), total_problems))
    print("=" * 72)
    for label, code in DIAGNOSE_BUCKETS:
        items = found[label]
        if not items:
            print("  [%-14s] (%s)  none" % (label, code))
            continue
        print("  [%-14s] (%s)  %d" % (label, code, len(items)))
        for aid, detail in items:
            print("      %-38s %s" % (aid, detail))

    if total_problems == 0:
        print("\n  No problems found. GREEN.")

    status = "ok" if total_problems == 0 else "fail"
    buckets_report = {
        label: {"code": code, "count": len(found[label]),
                "assets": [aid for aid, _ in found[label]],
                "details": ["%s: %s" % (aid, det) for aid, det in found[label]]}
        for label, code in DIAGNOSE_BUCKETS
    }
    meta = build_meta(
        command="diagnose-houdini-intake", pack=pack, strict=strict,
        status=status, failure_count=total_problems, record_count=len(houdini),
        input_spec_hash=catalog_content_hash(catalog),
        extra={"total_problems": total_problems, "buckets": buckets_report},
    )
    report = {"pack": pack, "total_problems": total_problems,
              "buckets": buckets_report, "meta": meta}
    _write_report("diagnose_houdini_intake", "diagnose_houdini_intake_report.json", report)

    return 0 if total_problems == 0 else 1


# ---------------------------------------------------------------------------
# report writer
# ---------------------------------------------------------------------------
def _write_report(command_dir, filename, report):
    out_dir = REPO_ROOT / MC.MESH_REPORTS_REL / command_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    with path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    try:
        shown = path.relative_to(Path.cwd())
    except ValueError:
        shown = path
    print("\n[report] -> %s" % shown)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inspect / diagnose the WorldForge Houdini-generated mesh intake.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Inspect a single houdini asset by id")
    ap.add_argument("--diagnose", action="store_true",
                    help="Classify houdini-intake problems into HOUDINI_* failure buckets")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    catalog = load_mesh_catalog(REPO_ROOT)

    if args.asset:
        return cmd_inspect_asset(args.pack, catalog, args.asset, strict)
    if args.diagnose:
        return cmd_diagnose(args.pack, catalog, strict)
    return cmd_inspect_intake(args.pack, catalog, strict)


if __name__ == "__main__":
    sys.exit(main())
