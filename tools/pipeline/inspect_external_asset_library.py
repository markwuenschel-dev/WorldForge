#!/usr/bin/env python3
"""inspect_external_asset_library.py — WorldForge v1.2 addendum operator utility.

Read-only. Shows what the THIRD-PARTY external asset catalog (Megascans/Fab)
actually IS — kept deliberately separate from the generated mesh catalog so the
ownership models never merge (addendum §6/§7) — and, with --diagnose, classifies
every problem into the addendum's MEGASCANS_* / EXTERNAL_* failure buckets so an
operator sees which lane is red without opening 51 external records. It mirrors
the console + JSON-report habit of inspect_mesh_catalog.py; it is NOT a generator
and NOT part of any create/validate contract. It joins:

    procedural/generated/worldforge_external_asset_catalog.json — the ledger
    the external_asset_contract taxonomy (required fields / package policy)
    asset_config.library_root — the machine-local (gitignored) library root

Three modes (addendum §12):
    inspect-external-asset-library   default: human summary + JSON report, exit 0
    inspect-external-asset           --asset <id>: full record dossier, exit 0
                                     (2 if unknown)
    diagnose-external-asset-library  --diagnose: classify problems into
                                     MEGASCANS_*/EXTERNAL_* buckets, exit 0 if
                                     clean, 1 if any (usable as a gate)

    PYTHONUTF8=1 python tools/pipeline/inspect_external_asset_library.py --lib megascans
    PYTHONUTF8=1 python tools/pipeline/inspect_external_asset_library.py --lib megascans --asset megascans_arid_debris_48ea3af3
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/inspect_external_asset_library.py --lib megascans --diagnose --strict
"""

import argparse
import json
import os
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import external_asset_contract as EAC  # noqa: E402
import asset_config as AC  # noqa: E402
import mesh_contract as MC  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, strict_from_env, hash_obj  # noqa: E402


# ---------------------------------------------------------------------------
# Ordering taxonomies (so the summary reads the same across runs)
# ---------------------------------------------------------------------------
ASSET_TYPE_ORDER = ("surface", "rock", "debris", "vegetation", "decal")
BIOME_ORDER = ("desert", "volcanic_ashlands", "temperate_forest",
               "alpine_snow", "wetland_mire", "alien_crystal_badlands")


def _ordered(counter, taxonomy):
    out = OrderedDict()
    for key in taxonomy:
        out[key] = counter.get(key, 0)
    for key in sorted(counter):
        if key not in out:
            out[key] = counter[key]
    return out


def _is_abs_leak(path):
    """True if a committed source_path leaked an absolute machine path.

    External source_path should be a stable, machine-independent alias-relative
    key (e.g. "Arid_Debris-48ea3af3"), never a drive-rooted or UNC absolute path
    that pins the record to one machine's library cache.
    """
    if not path or not isinstance(path, str):
        return False
    return os.path.isabs(path) or path.startswith(("\\\\", "//"))


# ---------------------------------------------------------------------------
# inspect-external-asset-library
# ---------------------------------------------------------------------------
def _summary_data(lib, catalog):
    assets = catalog.get("assets") or {}

    categories = Counter()
    types = Counter()
    licenses = Counter()
    ownership = Counter()
    pcg = Counter()
    biome = Counter()
    package_usage = Counter()

    missing_metadata = 0
    invalid_ownership = 0
    destroy_protected = 0

    for aid, e in assets.items():
        categories[e.get("asset_category") or "(unset)"] += 1
        types[e.get("asset_type") or "(unset)"] += 1
        licenses[e.get("license_family") or "(unset)"] += 1
        ownership[e.get("ownership_class") or "(unset)"] += 1
        pcg[e.get("pcg_eligibility") or "(unset)"] += 1
        package_usage[(e.get("package_policy") or {}).get("package_usage") or "(unset)"] += 1
        for b in (e.get("biome_compatibility") or []):
            biome[b] += 1

        if [f for f in EAC.EXTERNAL_REQUIRED_FIELDS if f not in e]:
            missing_metadata += 1
        if e.get("ownership_class") != "third_party_owned" or not e.get("third_party_owned"):
            invalid_ownership += 1
        if e.get("repair_destroy_protected"):
            destroy_protected += 1

    return {
        "library_id": lib,
        "library_root_alias": AC.library_root_alias(lib),
        "total_assets": len(assets),
        "by_asset_category": OrderedDict(sorted(categories.items())),
        "by_asset_type": _ordered(types, ASSET_TYPE_ORDER),
        "by_license_family": _ordered(licenses, EAC.LICENSE_FAMILIES),
        "by_ownership_class": OrderedDict(sorted(ownership.items())),
        "by_pcg_eligibility": OrderedDict(sorted(pcg.items())),
        "biome_compatibility": _ordered(biome, BIOME_ORDER),
        "by_package_usage": OrderedDict(sorted(package_usage.items())),
        "missing_metadata_count": missing_metadata,
        "invalid_ownership_count": invalid_ownership,
        "destroy_protected_count": destroy_protected,
    }


def _print_counter(title, mapping, indent="    "):
    print("  %s" % title)
    if not mapping:
        print("%s(none)" % indent)
        return
    for key, n in mapping.items():
        print("%s%-34s %d" % (indent, key, n))


def cmd_inspect_library(lib, catalog, strict):
    data = _summary_data(lib, catalog)

    print("=" * 72)
    print("INSPECT-EXTERNAL-ASSET-LIBRARY  lib=%s  (%d asset(s))" % (
        lib, data["total_assets"]))
    print("=" * 72)
    print("  library_id          %s" % data["library_id"])
    print("  library_root_alias  %s" % data["library_root_alias"])
    _print_counter("Assets per asset_category:", data["by_asset_category"])
    _print_counter("Assets per asset_type:", data["by_asset_type"])
    _print_counter("Assets per license_family:", data["by_license_family"])
    _print_counter("Assets per ownership_class:", data["by_ownership_class"])
    _print_counter("Assets per pcg_eligibility:", data["by_pcg_eligibility"])
    _print_counter("Assets compatible per biome:", data["biome_compatibility"])
    _print_counter("Assets per package_usage:", data["by_package_usage"])
    print("  Integrity:")
    print("    missing-metadata records                 %d" % data["missing_metadata_count"])
    print("    invalid-ownership (not third_party)      %d" % data["invalid_ownership_count"])
    print("    destroy-protected records                %d" % data["destroy_protected_count"])

    meta = build_meta(
        command="inspect-external-asset-library", pack=lib, strict=strict,
        status="ok", record_count=data["total_assets"],
        input_spec_hash=EAC.external_catalog_content_hash(catalog),
        output_manifest_hash=hash_obj(data),
        extra={"summary": data},
    )
    report = {"lib": lib, "summary": data, "meta": meta}
    _write_report("inspect_external_asset_library",
                  "inspect_external_asset_library_report.json", report)
    return 0


# ---------------------------------------------------------------------------
# inspect-external-asset
# ---------------------------------------------------------------------------
def cmd_inspect_asset(lib, catalog, asset_id, strict):
    entry = (catalog.get("assets") or {}).get(asset_id)
    if entry is None:
        sys.stderr.write("external asset not found in catalog: %s\n" % asset_id)
        return 2

    print("=" * 72)
    print("INSPECT-EXTERNAL-ASSET  %s  (lib=%s)" % (asset_id, lib))
    print("=" * 72)
    for k in sorted(entry.keys()):
        v = entry[k]
        if isinstance(v, (dict, list)):
            print("  %-26s %s" % (k, json.dumps(v, ensure_ascii=False)))
        else:
            print("  %-26s %s" % (k, v))

    meta = build_meta(
        command="inspect-external-asset", pack=lib, strict=strict,
        status="ok", record_count=1,
        input_spec_hash=hash_obj(entry),
        extra={"external_asset_id": asset_id},
    )
    report = {"lib": lib, "external_asset_id": asset_id, "record": entry, "meta": meta}
    _write_report("inspect_external_asset_library",
                  "inspect_external_asset_%s_report.json" % asset_id, report)
    return 0


# ---------------------------------------------------------------------------
# diagnose-external-asset-library
# ---------------------------------------------------------------------------
# Ordered buckets: (label, FailureCode). Every external-asset problem lands in a
# bucket; a valid third-party record produces none.
DIAGNOSE_BUCKETS = (
    ("library-root", FailureCode.MEGASCANS_LIBRARY_FAILURE),
    ("ownership", FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE),
    ("license", FailureCode.EXTERNAL_LICENSE_METADATA_FAILURE),
    ("destroy-protection", FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK),
    ("catalog-provenance", FailureCode.MEGASCANS_CATALOG_FAILURE),
    ("package-policy", FailureCode.THIRD_PARTY_ASSET_PACKAGE_POLICY_FAILURE),
    ("metadata", FailureCode.MEGASCANS_SCAN_FAILURE),
    ("source-path-leak", FailureCode.SOURCE_OWNERSHIP_SEPARATION_FAILURE),
)


def _classify_external(entry):
    """Re-check one external-asset record. Return list of (bucket, detail).

    A valid third_party_owned, licensed, destroy-protected record returns []."""
    problems = []

    # ownership: must be third_party_owned; never generated-owned.
    if entry.get("ownership_class") != "third_party_owned":
        problems.append(("ownership", "ownership_class is %r, not third_party_owned"
                         % entry.get("ownership_class")))
    if not entry.get("third_party_owned"):
        problems.append(("ownership", "third_party_owned is not true"))
    if entry.get("generated_owned"):
        problems.append(("ownership", "generated_owned is true for an external asset"))

    # license metadata.
    lic = entry.get("license_family")
    if not lic:
        problems.append(("license", "missing license_family"))
    elif lic not in EAC.LICENSE_FAMILIES:
        problems.append(("license", "unknown license_family: %r" % lic))
    if not entry.get("external_licensed"):
        problems.append(("license", "external_licensed is not true"))

    # destroy protection: a source cache file must never be destroyable.
    if not entry.get("repair_destroy_protected"):
        problems.append(("destroy-protection", "not repair_destroy_protected"))
    if entry.get("raw_asset_destroy_allowed"):
        problems.append(("destroy-protection", "raw_asset_destroy_allowed is true"))

    # catalog + provenance record references.
    if not entry.get("catalog_record"):
        problems.append(("catalog-provenance", "missing catalog_record"))
    if not entry.get("provenance_record"):
        problems.append(("catalog-provenance", "missing provenance_record"))

    # package policy: incorporated-only, no standalone/raw redistribution.
    pp = entry.get("package_policy") or {}
    if pp.get("package_usage") != EAC.PACKAGE_USAGE_INCORPORATED:
        problems.append(("package-policy", "package_usage is %r, not %r"
                         % (pp.get("package_usage"), EAC.PACKAGE_USAGE_INCORPORATED)))
    if pp.get("standalone_redistribution_allowed"):
        problems.append(("package-policy", "standalone_redistribution_allowed is true"))
    if pp.get("raw_asset_export_allowed"):
        problems.append(("package-policy", "raw_asset_export_allowed is true"))

    # metadata completeness.
    missing = [f for f in EAC.EXTERNAL_REQUIRED_FIELDS if f not in entry]
    if missing:
        problems.append(("metadata", "missing required field(s): %s" % ", ".join(missing)))

    # source-path leak.
    if _is_abs_leak(entry.get("source_path")):
        problems.append(("source-path-leak",
                         "absolute source_path leaked: %r" % entry.get("source_path")))

    return problems


def cmd_diagnose(lib, catalog, strict):
    assets = catalog.get("assets") or {}
    found = {label: [] for label, _ in DIAGNOSE_BUCKETS}

    # Library-level: the configured library root must resolve on this machine.
    if AC.library_root(lib) is None:
        found["library-root"].append(
            (lib, "library root not configured or missing on this machine "
                  "(asset_config.library_root returned None)"))

    for aid in sorted(assets):
        for bucket, detail in _classify_external(assets[aid]):
            found[bucket].append((aid, detail))

    total_problems = sum(len(v) for v in found.values())

    print("=" * 72)
    print("DIAGNOSE-EXTERNAL-ASSET-LIBRARY  lib=%s  (%d asset(s), %d problem(s))" % (
        lib, len(assets), total_problems))
    print("=" * 72)
    for label, code in DIAGNOSE_BUCKETS:
        items = found[label]
        if not items:
            print("  [%-18s] (%s)  none" % (label, code))
            continue
        print("  [%-18s] (%s)  %d" % (label, code, len(items)))
        for aid, detail in items:
            print("      %-42s %s" % (aid, detail))

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
        command="diagnose-external-asset-library", pack=lib, strict=strict,
        status=status, failure_count=total_problems, record_count=len(assets),
        input_spec_hash=EAC.external_catalog_content_hash(catalog),
        extra={"total_problems": total_problems, "buckets": buckets_report},
    )
    report = {"lib": lib, "total_problems": total_problems,
              "buckets": buckets_report, "meta": meta}
    _write_report("diagnose_external_asset_library",
                  "diagnose_external_asset_library_report.json", report)

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
        description="Inspect / diagnose the WorldForge external (Megascans) asset library.")
    ap.add_argument("--lib", default="megascans")
    ap.add_argument("--asset", default=None, help="Inspect a single external asset by id")
    ap.add_argument("--diagnose", action="store_true",
                    help="Classify problems into MEGASCANS_*/EXTERNAL_* failure buckets")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    catalog = EAC.load_external_catalog(REPO_ROOT)

    if args.asset:
        return cmd_inspect_asset(args.lib, catalog, args.asset, strict)
    if args.diagnose:
        return cmd_diagnose(args.lib, catalog, strict)
    return cmd_inspect_library(args.lib, catalog, strict)


if __name__ == "__main__":
    sys.exit(main())
