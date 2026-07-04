#!/usr/bin/env python3
"""validate_visual_package.py — WorldForge v1.3.5 visual-package lane (Pillar 7 package).

The dressing plan for each map references real visual assets: a ground surface, a
cliff surface, and a set of dressing placements. This validator proves the
package is closed and ownership-clean:

  * Every referenced asset EXISTS — generated meshes in the mesh catalog,
    Megascans in the external asset catalog. A dressing that references a missing
    asset fails (VISUAL_PACKAGE_FAILURE "package omits referenced visual asset").
  * Every Megascans-referenced asset is third_party_owned and follows the
    incorporated-package policy — never emitted standalone, never rewritten to
    generated_owned (a megascans reference recorded as generated_owned, or a
    catalog entry whose package_usage is not incorporated_project_content, fails).
  * Every generated dressing record is generated_owned.
  * Aggregate: the union of referenced third-party assets all carry
    package_usage=incorporated_project_content in the external catalog.

Ownership models never merge (v1.2 addendum): the generated mesh catalog stays
generated_owned; the Megascans catalog stays third_party_owned + incorporated.

Usage:
    python tools/pipeline/validate_visual_package.py --pack mission_loop_world
    STRICT=1 python tools/pipeline/validate_visual_package.py --pack mission_loop_world --strict

Writes: procedural/reports/visual/validate_visual_package/validate_visual_package_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_catalog import load_visual_catalog
from mesh_catalog import load_mesh_catalog
from external_asset_contract import (
    load_external_catalog, PACKAGE_USAGE_INCORPORATED)
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_CODE = FailureCode.VISUAL_PACKAGE_FAILURE


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _is_external_ref(ref):
    """A dressing record that names a third-party (Megascans) source asset."""
    ref = ref or {}
    if ref.get("external_asset_id"):
        return True
    if ref.get("source") in ("external", "external_catalog"):
        return True
    if ref.get("ownership_class") == VC.OWNERSHIP_THIRD_PARTY:
        return True
    return str(ref.get("asset_id") or "").startswith("megascans")


def _external_id(ref):
    return ref.get("external_asset_id") or ref.get("asset_id")


def _iter_refs(dressing):
    """Yield (slot_label, ref_dict) for every asset the dressing plan references."""
    for key in ("ground_surface", "cliff_surface"):
        r = dressing.get(key)
        if isinstance(r, dict) and r.get("asset_id"):
            yield key, r
    for i, r in enumerate(dressing.get("dressing_assets") or []):
        if isinstance(r, dict) and r.get("asset_id"):
            yield "dressing_{}".format(i), r


def check_map(rep, sid, dressing, mesh_assets, ext_assets):
    """Check one map's dressing plan. Returns the set of referenced third-party
    external_asset_ids so the caller can assert the aggregate package policy."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=_CODE)

    referenced_external = set()

    for label, ref in _iter_refs(dressing):
        aid = ref.get("asset_id")
        if _is_external_ref(ref):
            ext_id = _external_id(ref)
            entry = ext_assets.get(ext_id)
            # exists in the external catalog
            c("{}_external_exists".format(label), entry is not None,
              "package omits referenced visual asset: megascans '{}' absent from "
              "external catalog".format(ext_id))
            # never rewritten to generated_owned in the dressing record
            c("{}_not_rewritten_generated".format(label),
              ref.get("ownership_class") == VC.OWNERSHIP_THIRD_PARTY,
              "megascans ref '{}' recorded ownership_class={} (must stay {})".format(
                  ext_id, ref.get("ownership_class"), VC.OWNERSHIP_THIRD_PARTY))
            if entry is not None:
                referenced_external.add(ext_id)
                # catalog entry is third_party_owned + incorporated (never standalone)
                c("{}_catalog_third_party".format(label),
                  entry.get("ownership_class") == VC.OWNERSHIP_THIRD_PARTY,
                  "external catalog entry '{}' ownership_class={}".format(
                      ext_id, entry.get("ownership_class")))
                policy = entry.get("package_policy") or {}
                c("{}_incorporated_not_standalone".format(label),
                  policy.get("package_usage") == PACKAGE_USAGE_INCORPORATED
                  and not policy.get("standalone_redistribution_allowed", False),
                  "megascans '{}' package policy is not incorporated/non-standalone: "
                  "package_usage={} standalone_redistribution_allowed={}".format(
                      ext_id, policy.get("package_usage"),
                      policy.get("standalone_redistribution_allowed")))
        else:
            # generated mesh reference
            c("{}_generated_exists".format(label), aid in mesh_assets,
              "package omits referenced visual asset: generated mesh '{}' absent "
              "from mesh catalog".format(aid))
            c("{}_generated_owned".format(label),
              ref.get("ownership_class") == VC.OWNERSHIP_GENERATED,
              "generated dressing record '{}' ownership_class={} (must be {})".format(
                  aid, ref.get("ownership_class"), VC.OWNERSHIP_GENERATED))

    return referenced_external


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_visual_catalog(REPO_ROOT)
    maps = catalog.get("maps") or {}
    if not maps:
        rep.error("no visual maps found — run the v1.3.5 visual materialization first")
        return rep, 0

    mesh_assets = (load_mesh_catalog(REPO_ROOT).get("assets") or {})
    ext_assets = (load_external_catalog(REPO_ROOT).get("assets") or {})

    all_external = set()
    n = 0
    for sid in sorted(maps):
        entry = maps.get(sid) or {}
        dress_rel = entry.get("dressing_path") or "{}/{}.json".format(VC.DRESSING_REL, sid)
        dressing, derr = _read_json(REPO_ROOT / dress_rel)
        if dressing is None:
            rep.check("{}::dressing_loads".format(sid), False, derr or dress_rel, code=_CODE)
            continue
        all_external |= check_map(rep, sid, dressing, mesh_assets, ext_assets)
        n += 1

    # -- aggregate: every referenced third-party asset is incorporated project content
    non_incorporated = sorted(
        aid for aid in all_external
        if (ext_assets.get(aid, {}).get("package_policy") or {}).get("package_usage")
        != PACKAGE_USAGE_INCORPORATED)
    rep.check("aggregate::third_party_all_incorporated", not non_incorporated,
              "referenced third-party assets not package_usage={}: {}".format(
                  PACKAGE_USAGE_INCORPORATED, non_incorporated), code=_CODE)
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.3.5 visual package closure/ownership.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-visual-package", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_visual_package"
    rep.write(report_dir, "validate_visual_package_report.json")
    rep.print_summary("validate-visual-package")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
