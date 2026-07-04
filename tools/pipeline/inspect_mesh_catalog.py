#!/usr/bin/env python3
"""inspect_mesh_catalog.py — WorldForge v1.2 MeshForge Intake operator utility.

Read-only. Shows what the generated mesh catalog (or a single mesh asset)
actually IS, and — with --diagnose — classifies every problem into the brief's
MeshForge failure buckets so an operator sees which lane is red without opening
24 descriptor files. Mirrors the console/JSON-report habit of the existing
inspect_world_pack.py and diagnose_world_pack.py operator tools; it is NOT a
generator and NOT part of the create/validate contract. It joins three things:

    procedural/generated/worldforge_mesh_catalog.json   — the catalog ledger
    procedural/generated/mesh_assets/<id>/descriptor.json — per-asset records
    the mesh_contract taxonomy (families/sources/paths/pcg/budgets)

Three modes (brief §21):
    inspect-mesh-catalog   default: human summary + JSON report, exit 0
    inspect-mesh-asset     --asset <id>: full per-asset dossier, exit 0 (2 if unknown)
    diagnose-mesh-catalog  --diagnose: classify problems into MESH_* buckets,
                           exit 0 if clean, 1 if any problem (usable as a gate)

    PYTHONUTF8=1 python tools/pipeline/inspect_mesh_catalog.py --pack biome_expansion_world
    PYTHONUTF8=1 python tools/pipeline/inspect_mesh_catalog.py --pack biome_expansion_world --asset mesh_rock_desert_eroded_rock
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/inspect_mesh_catalog.py --pack biome_expansion_world --diagnose --strict
"""

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC  # noqa: E402
from mesh_catalog import load_mesh_catalog, catalog_content_hash  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, strict_from_env, hash_obj  # noqa: E402


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


def _descriptor_ids_on_disk():
    """Every asset_id that has a descriptor.json materialized on disk."""
    root = REPO_ROOT / MC.MESH_GENERATED_REL
    ids = set()
    if not root.is_dir():
        return ids
    for sub in sorted(root.iterdir()):
        if sub.is_dir() and (sub / "descriptor.json").is_file():
            ids.add(sub.name)
    return ids


def _load_descriptor(asset_id):
    return _load_json(MC.mesh_descriptor_path(asset_id, REPO_ROOT))


def _bounds_max_extent(bounds):
    """Largest axis extent in cm, or 0.0 if bounds are absent/zero/garbage."""
    if not isinstance(bounds, dict):
        return 0.0
    vals = []
    for k in MC.BOUNDS_REQUIRED:
        try:
            vals.append(float(bounds.get(k) or 0.0))
        except (TypeError, ValueError):
            vals.append(0.0)
    return max(vals) if vals else 0.0


# ---------------------------------------------------------------------------
# inspect-mesh-catalog
# ---------------------------------------------------------------------------
def _summary_data(catalog):
    assets = catalog.get("assets") or {}
    disk_ids = _descriptor_ids_on_disk()

    families = Counter()
    sources = Counter()
    pcg = Counter()
    budgets = Counter()
    biome = Counter()
    package_status = Counter()
    validation_status = Counter()
    lifecycle_status = Counter()

    for aid, entry in assets.items():
        families[entry.get("mesh_family") or "(unset)"] += 1
        sources[entry.get("source_type") or "(unset)"] += 1
        pcg[entry.get("pcg_eligibility") or "(unset)"] += 1
        budgets[entry.get("budget_class") or "(unset)"] += 1
        package_status[entry.get("package_status") or "(unset)"] += 1
        validation_status[entry.get("validation_status") or "(unset)"] += 1
        lifecycle_status[entry.get("lifecycle_status") or "(unset)"] += 1
        for b in (entry.get("biome_compatibility") or []):
            biome[b] += 1

    catalog_ids = set(assets.keys())
    orphans = sorted(disk_ids - catalog_ids)
    missing_deps = sorted(
        aid for aid in catalog_ids
        if not MC.mesh_descriptor_path(aid, REPO_ROOT).is_file()
    )

    # Order family/source/pcg/budget/biome by the contract taxonomy so the
    # summary reads the same across runs; append any stragglers alphabetically.
    def _ordered(counter, taxonomy):
        out = OrderedDict()
        for key in taxonomy:
            out[key] = counter.get(key, 0)
        for key in sorted(counter):
            if key not in out:
                out[key] = counter[key]
        return out

    return {
        "total_assets": len(assets),
        "by_mesh_family": _ordered(families, MC.MESH_FAMILIES),
        "by_source_type": _ordered(sources, MC.SOURCE_TYPES),
        "by_pcg_eligibility": _ordered(pcg, MC.PCG_ELIGIBILITY_VALUES),
        "by_budget_class": _ordered(budgets, MC.BUDGET_CLASSES),
        "biome_compatibility": _ordered(biome, MC.BIOME_FAMILIES),
        "by_package_status": OrderedDict(sorted(package_status.items())),
        "by_validation_status": OrderedDict(sorted(validation_status.items())),
        "by_lifecycle_status": OrderedDict(sorted(lifecycle_status.items())),
        "orphan_count": len(orphans),
        "orphans": orphans,
        "missing_dependency_count": len(missing_deps),
        "missing_dependencies": missing_deps,
    }


def _print_counter(title, mapping, indent="    "):
    print("  %s" % title)
    if not mapping:
        print("%s(none)" % indent)
        return
    for key, n in mapping.items():
        print("%s%-30s %d" % (indent, key, n))


def cmd_inspect_catalog(pack, catalog, strict):
    data = _summary_data(catalog)

    print("=" * 72)
    print("INSPECT-MESH-CATALOG  pack=%s  (%d asset(s))" % (pack, data["total_assets"]))
    print("=" * 72)
    _print_counter("Assets per mesh_family:", data["by_mesh_family"])
    _print_counter("Assets per source_type:", data["by_source_type"])
    _print_counter("Assets per pcg_eligibility:", data["by_pcg_eligibility"])
    _print_counter("Assets per budget_class:", data["by_budget_class"])
    _print_counter("Assets compatible per biome:", data["biome_compatibility"])
    _print_counter("Package status:", data["by_package_status"])
    _print_counter("Validation status:", data["by_validation_status"])
    _print_counter("Lifecycle status:", data["by_lifecycle_status"])
    print("  Integrity:")
    print("    orphan descriptors (no catalog record)   %d" % data["orphan_count"])
    if data["orphans"]:
        print("      %s" % ", ".join(data["orphans"]))
    print("    missing dependencies (record, no file)   %d" % data["missing_dependency_count"])
    if data["missing_dependencies"]:
        print("      %s" % ", ".join(data["missing_dependencies"]))

    meta = build_meta(
        command="inspect-mesh-catalog", pack=pack, strict=strict,
        status="ok", record_count=data["total_assets"],
        input_spec_hash=catalog_content_hash(catalog),
        output_manifest_hash=hash_obj(data),
        extra={"summary": data},
    )
    report = {"pack": pack, "summary": data, "meta": meta}
    _write_report("inspect_mesh_catalog", "inspect_mesh_catalog_report.json", report)
    return 0


# ---------------------------------------------------------------------------
# inspect-mesh-asset
# ---------------------------------------------------------------------------
DOSSIER_FIELDS = (
    "asset_id", "display_name", "mesh_family", "source_type", "source_recipe",
    "source_hash", "final_asset_path", "registry_id", "provenance_id",
    "collision_profile", "pivot_policy", "scale_policy", "lod_policy",
    "nanite_policy", "pcg_eligibility", "budget_class",
)


def cmd_inspect_asset(pack, catalog, asset_id, strict):
    descriptor = _load_descriptor(asset_id)
    entry = (catalog.get("assets") or {}).get(asset_id)
    if descriptor is None and entry is None:
        sys.stderr.write("asset not found in catalog or on disk: %s\n" % asset_id)
        return 2

    d = descriptor or {}
    print("=" * 72)
    print("INSPECT-MESH-ASSET  %s  (pack=%s)" % (asset_id, pack))
    print("=" * 72)
    if descriptor is None:
        print("  WARNING: descriptor.json missing on disk — showing catalog record only")
        d = entry or {}

    for k in DOSSIER_FIELDS:
        print("  %-22s %s" % (k, d.get(k)))

    # material_bindings: slot -> path
    print("  %-22s" % "material_bindings")
    bindings = d.get("material_bindings") or []
    if not bindings:
        print("      (none)")
    for b in bindings:
        if isinstance(b, dict):
            print("      %-16s -> %s" % (b.get("slot_name"), b.get("material_asset_path")))
        else:
            print("      %s" % b)

    # bounds
    bounds = d.get("bounds") or {}
    print("  %-22s x=%s y=%s z=%s (max_extent=%.1f cm)" % (
        "bounds", bounds.get("x_cm"), bounds.get("y_cm"), bounds.get("z_cm"),
        _bounds_max_extent(bounds)))

    # biome / poi compatibility
    print("  %-22s %s" % ("biome_compatibility", d.get("biome_compatibility")))
    print("  %-22s %s" % ("poi_compatibility", d.get("poi_compatibility")))

    # package / validation / lifecycle status come off the catalog entry
    ce = entry or {}
    print("  %-22s %s" % ("package_status", ce.get("package_status")))
    print("  %-22s %s" % ("validation_status", ce.get("validation_status")))
    print("  %-22s %s" % ("lifecycle_status", ce.get("lifecycle_status")))

    dossier = {"asset_id": asset_id, "descriptor": d, "catalog_entry": entry}
    meta = build_meta(
        command="inspect-mesh-asset", pack=pack, strict=strict,
        status="ok", record_count=1,
        input_spec_hash=hash_obj(d),
        extra={"asset_id": asset_id},
    )
    report = {"pack": pack, "asset": dossier, "meta": meta}
    _write_report("inspect_mesh_catalog",
                  "inspect_mesh_asset_%s_report.json" % asset_id, report)
    return 0


# ---------------------------------------------------------------------------
# diagnose-mesh-catalog
# ---------------------------------------------------------------------------
# Ordered buckets: (label, FailureCode). Every asset problem lands in exactly
# one bucket via _classify_asset below; catalog-membership problems (orphans /
# missing deps) land in the catalog bucket.
DIAGNOSE_BUCKETS = (
    ("contract", FailureCode.MESH_CONTRACT_FAILURE),
    ("catalog", FailureCode.MESH_CATALOG_FAILURE),
    ("source", FailureCode.MESH_SOURCE_FAILURE),
    ("path", FailureCode.MESH_FINAL_PATH_FAILURE),
    ("ownership", FailureCode.MESH_OWNERSHIP_FAILURE),
    ("provenance", FailureCode.MESH_PROVENANCE_FAILURE),
    ("material-binding", FailureCode.MESH_MATERIAL_BINDING_FAILURE),
    ("collision-bounds", FailureCode.MESH_BOUNDS_FAILURE),
    ("pcg", FailureCode.MESH_PCG_ELIGIBILITY_FAILURE),
    ("biome", FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE),
    ("rendering-budget", FailureCode.MESH_RENDERING_BUDGET_FAILURE),
    ("package", FailureCode.MESH_PACKAGE_FAILURE),
    ("lifecycle", FailureCode.MESH_LIFECYCLE_FAILURE),
    ("report-integrity", FailureCode.REPORT_INTEGRITY_FAILURE),
)


def _classify_asset(asset_id, entry):
    """Cheaply re-check one catalog asset. Return list of (bucket, detail).

    The descriptor is the source of truth for the deep fields; the catalog entry
    carries lifecycle/package status. A valid asset returns [].
    """
    problems = []
    descriptor = _load_descriptor(asset_id)

    # contract: descriptor must exist, parse, and carry required contract fields.
    if descriptor is None:
        problems.append(("contract", "descriptor.json missing or unparseable"))
        return problems  # nothing else is trustworthy without a descriptor
    missing = MC.missing_required_fields(descriptor)
    if missing:
        problems.append(("contract", "missing required field(s): %s" % ", ".join(missing)))

    # source: known source_type + recipe + hash present.
    stype = descriptor.get("source_type")
    if stype not in MC.SOURCE_TYPES:
        problems.append(("source", "unknown source_type: %r" % stype))
    if not descriptor.get("source_recipe"):
        problems.append(("source", "missing source_recipe"))
    if not descriptor.get("source_hash"):
        problems.append(("source", "missing source_hash"))

    # path: final asset path must be owned and not a Temp/Bake/plugin leak.
    final_path = descriptor.get("final_asset_path")
    if MC.is_forbidden_final_path(final_path):
        problems.append(("path", "forbidden final path: %r" % final_path))
    elif not MC.is_allowed_final_path(final_path):
        problems.append(("path", "final path not under an owned root: %r" % final_path))

    # ownership: generated-owned, registry id present, not human-owned.
    if not descriptor.get("registry_id"):
        problems.append(("ownership", "missing registry_id"))
    if not descriptor.get("generated_owned", False):
        problems.append(("ownership", "generated_owned is not true"))
    if descriptor.get("human_owned", False):
        problems.append(("ownership", "human_owned is true for a generated mesh"))

    # provenance.
    if not descriptor.get("provenance_id"):
        problems.append(("provenance", "missing provenance_id"))

    # material bindings.
    bindings = descriptor.get("material_bindings")
    if not bindings:
        problems.append(("material-binding", "no material_bindings declared"))

    # collision + bounds.
    collision = descriptor.get("collision_profile")
    family = descriptor.get("mesh_family")
    allowed_collision = MC.FAMILY_ALLOWED_COLLISION.get(family)
    if not collision:
        problems.append(("collision-bounds", "missing collision_profile"))
    elif allowed_collision is not None and collision not in allowed_collision:
        problems.append(("collision-bounds",
                         "collision %r not allowed for family %r" % (collision, family)))
    if _bounds_max_extent(descriptor.get("bounds")) <= 0.0:
        problems.append(("collision-bounds", "zero / missing bounds"))

    # pcg eligibility.
    pcg = descriptor.get("pcg_eligibility")
    if pcg not in MC.PCG_ELIGIBILITY_VALUES:
        problems.append(("pcg", "invalid pcg_eligibility: %r" % pcg))

    # biome compatibility.
    biomes = descriptor.get("biome_compatibility") or []
    if not biomes:
        problems.append(("biome", "empty biome_compatibility"))
    else:
        bad = [b for b in biomes if b not in MC.BIOME_FAMILIES]
        if bad:
            problems.append(("biome", "unknown biome(s): %s" % ", ".join(map(str, bad))))

    # rendering budget.
    budget = descriptor.get("budget_class")
    if budget not in MC.BUDGET_CLASSES:
        problems.append(("rendering-budget", "invalid budget_class: %r" % budget))

    # package + lifecycle status live on the catalog entry.
    ce = entry or {}
    if not ce.get("package_status"):
        problems.append(("package", "missing package_status in catalog entry"))
    if not ce.get("lifecycle_status"):
        problems.append(("lifecycle", "missing lifecycle_status in catalog entry"))

    return problems


def cmd_diagnose(pack, catalog, strict):
    assets = catalog.get("assets") or {}
    catalog_ids = set(assets.keys())
    disk_ids = _descriptor_ids_on_disk()

    # bucket -> list of (asset_id, detail)
    found = {label: [] for label, _ in DIAGNOSE_BUCKETS}

    # Per-asset re-checks.
    for aid in sorted(catalog_ids):
        for bucket, detail in _classify_asset(aid, assets[aid]):
            found[bucket].append((aid, detail))

    # Catalog-membership problems.
    for aid in sorted(disk_ids - catalog_ids):
        found["catalog"].append((aid, "orphan: descriptor on disk with no catalog record"))
    for aid in sorted(catalog_ids):
        if not MC.mesh_descriptor_path(aid, REPO_ROOT).is_file():
            found["catalog"].append((aid, "missing dependency: catalog record has no descriptor.json"))

    total_problems = sum(len(v) for v in found.values())

    print("=" * 72)
    print("DIAGNOSE-MESH-CATALOG  pack=%s  (%d asset(s), %d problem(s))" % (
        pack, len(catalog_ids), total_problems))
    print("=" * 72)
    for label, code in DIAGNOSE_BUCKETS:
        items = found[label]
        if not items:
            print("  [%-16s] (%s)  none" % (label, code))
            continue
        print("  [%-16s] (%s)  %d" % (label, code, len(items)))
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
        command="diagnose-mesh-catalog", pack=pack, strict=strict,
        status=status, failure_count=total_problems,
        record_count=len(catalog_ids),
        input_spec_hash=catalog_content_hash(catalog),
        extra={"total_problems": total_problems, "buckets": buckets_report},
    )
    report = {"pack": pack, "total_problems": total_problems,
              "buckets": buckets_report, "meta": meta}
    _write_report("diagnose_mesh_catalog", "diagnose_mesh_catalog_report.json", report)

    return 0 if total_problems == 0 else 1


# ---------------------------------------------------------------------------
# report writer + diff
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
        description="Inspect / diagnose the WorldForge generated mesh catalog.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Inspect a single mesh asset by id")
    ap.add_argument("--diagnose", action="store_true",
                    help="Classify catalog problems into MeshForge failure buckets")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--diff", action="store_true",
                    help="(nice-to-have) diff against a baseline report")
    ap.add_argument("--baseline", default=None)
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    catalog = load_mesh_catalog(REPO_ROOT)

    if args.diff:
        # diff is an explicitly-optional nice-to-have; keep it honest and cheap.
        print("diff not supported")
        return 0

    if args.asset:
        return cmd_inspect_asset(args.pack, catalog, args.asset, strict)
    if args.diagnose:
        return cmd_diagnose(args.pack, catalog, strict)
    return cmd_inspect_catalog(args.pack, catalog, strict)


if __name__ == "__main__":
    sys.exit(main())
