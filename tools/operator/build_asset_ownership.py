#!/usr/bin/env python3
"""build_asset_ownership.py — v2.1 OperatorForge asset-ownership inspector (Wave 3).

Exposes asset ownership / provenance / package + repair-destroy policy from the
REAL WorldForge asset catalogs, keeping the four ownership classes DISTINCT
(handoff §7.6): WorldForge-generated meshes (worldforge_mesh_catalog.json →
generated_owned) never collapse into Megascans third-party source
(worldforge_external_asset_catalog.json → third_party_owned).

The repair/destroy policy is derived from ownership, and the honesty invariant is
enforced by the AssetOwnershipView contract itself: a third_party/human-owned asset
may NEVER be marked 'regenerate' (destroyable). A row that violates its schema
turns this builder RED — a collapsed ownership class cannot be published.

Deliverables:
  index/asset_ownership_views.json       (list[AssetOwnershipView])
  dashboard/assets/index.html            (ownership inspector, grouped by class)

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_asset_ownership.py --strict
Reports -> procedural/reports/operator/index/build_asset_ownership_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
import operator_view as V
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
MESH_CATALOG = REPO_ROOT / "procedural/generated/worldforge_mesh_catalog.json"
MESH_CATALOG_REL = "procedural/generated/worldforge_mesh_catalog.json"
EXT_CATALOG = REPO_ROOT / "procedural/generated/worldforge_external_asset_catalog.json"
EXT_CATALOG_REL = "procedural/generated/worldforge_external_asset_catalog.json"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _generated_rows(cat):
    rows = []
    for aid, a in sorted(cat.get("assets", {}).items()):
        rows.append(OX._example_asset_ownership_view(
            asset_id=aid,
            asset_path=a.get("final_asset_path", "procedural/generated/mesh/{}".format(aid)),
            ownership_class="generated_owned",
            source=a.get("source_type", "internal_recipe"),
            license_class="worldforge_generated",
            used_by_maps=[],
            used_by_scenarios=[],
            repair_destroy_policy="regenerate",   # generated is safe to rebuild
            package_policy="include",
            provenance_report_path=MESH_CATALOG_REL,
            status="ok",
            failure_codes=[],
        ))
    return rows


def _external_rows(cat):
    rows = []
    lib = cat.get("library_id", "external")
    assets = cat.get("assets", [])
    items = list(assets.values()) if isinstance(assets, dict) else list(assets)
    for a in sorted(items, key=lambda x: x.get("external_asset_id", x.get("asset_name", ""))):
        oc = a.get("ownership_class", "third_party_owned")
        rows.append(OX._example_asset_ownership_view(
            asset_id=a.get("external_asset_id", a.get("asset_name", "unknown")),
            asset_path=a.get("source_path", "external://{}".format(lib)),
            ownership_class=oc if oc in OX.OWNERSHIP_CLASSES else "third_party_owned",
            source=a.get("source_type", "{}_library".format(lib)),
            license_class=a.get("license_family", "external_licensed"),
            used_by_maps=[],
            used_by_scenarios=[],
            repair_destroy_policy="protected",    # third-party source is never destroyed
            package_policy="external_reference",
            provenance_report_path=EXT_CATALOG_REL,
            status="ok",
            failure_codes=[],
        ))
    return rows


def _render(rows, sha):
    by_class = {}
    for r in rows:
        by_class.setdefault(r["ownership_class"], []).append(r)
    body = ""
    for cls in OX.OWNERSHIP_CLASSES:
        items = by_class.get(cls, [])
        if not items:
            continue
        body += '<h2>{} ({})</h2><div class="scroll"><table>'.format(V.esc(cls), len(items))
        body += "<tr><th>asset</th><th>source</th><th>license</th><th>repair/destroy</th>"\
                "<th>package</th></tr>"
        for r in items:
            body += "<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                V.esc(r["asset_id"]), V.esc(r["source"]), V.esc(r["license_class"]),
                V.badge("pass" if r["repair_destroy_policy"] == "protected" else "blocked")
                if cls in OX.PROTECTED_OWNERSHIP_CLASSES else V.esc(r["repair_destroy_policy"]),
                V.esc(r["package_policy"]))
        body += "</table></div>"
    return V.page("Asset ownership inspector", body,
                  subtitle="{} assets · 4 ownership classes kept distinct".format(len(rows)),
                  git_sha=sha, back=("../index.html", "dashboard"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator asset-ownership inspector.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("operator", "asset_ownership", strict=strict)

    rows = []
    if MESH_CATALOG.is_file():
        rows += _generated_rows(_load(MESH_CATALOG))
    if EXT_CATALOG.is_file():
        rows += _external_rows(_load(EXT_CATALOG))

    rep.check("asset_views_nonempty", len(rows) > 0,
              "no asset catalogs found to index", code=F.OPERATOR_ASSET_OWNERSHIP_INVALID)
    # distinctness: both a generated_owned and a third_party_owned class must exist,
    # proving the classes did not collapse.
    classes = {r["ownership_class"] for r in rows}
    rep.check("classes_distinct",
              "generated_owned" in classes and "third_party_owned" in classes,
              "expected both generated_owned and third_party_owned classes (got {})".format(
                  sorted(classes)),
              code=F.OPERATOR_ASSET_OWNERSHIP_INVALID)
    for r in rows:
        fails = [c for c in OX.validate_asset_ownership_view(r, strict=strict) if not c[1]]
        rep.check("asset::{}::schema".format(r["asset_id"]), len(fails) == 0,
                  "asset view schema failures: {}".format([c[0] for c in fails][:3]),
                  code=F.OPERATOR_ASSET_OWNERSHIP_INVALID)

    if rep.passed:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        (INDEX_DIR / "asset_ownership_views.json").write_text(
            json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
        sha = ""
        idx = INDEX_DIR / "operator_report_index.json"
        if idx.is_file():
            sha = json.loads(idx.read_text(encoding="utf-8")).get("git_sha", "")
        V.write_page("assets/index.html", _render(rows, sha))

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-asset-ownership", pack=None, strict=strict, status=rep.status,
        record_count=len(rows), records_total=len(rows),
        report_type="wf.operator.asset_ownership.v1"))
    rep.write(INDEX_DIR, "build_asset_ownership_report.json")
    rep.print_summary("operator-asset-ownership")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
