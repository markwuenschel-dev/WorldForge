#!/usr/bin/env python3
"""validate_inventory_root_coverage.py — v2.5.1 gate: inventory roots cannot drift.

WHY THIS EXISTS
---------------
Commit e1b65e3c ("widen conversion inventory to plugin-owned content") widened
``build_conversion_manifest.CONTENT_ROOTS`` from 2 roots to 3 — adding
``Plugins/CoreTerrainMaterials/Content`` — but never regenerated the manifest. The
committed ``pre_conversion_manifest.json`` still records 2 roots at
``meta.git_sha=fa922a37``, and NO gate compared the two. The commit's stated purpose was
never reflected in its evidence.

That is not a cosmetic bookkeeping miss. It is exactly why two CoreTerrainMaterials
packages were resaved by a UE 5.8 editor with no inventory entry to classify them
against: the widened root existed in code and nowhere in the data.

This gate makes root drift fail closed. It asserts:

  1. the canonical manifest records the SAME roots the inventory script declares;
  2. every declared root is actually represented (or is explicitly, knowingly empty);
  3. the canonical manifest is the real artifact, not a stub.

A gate that only ever passes proves nothing, so the negative is proven too: drop a root
from the manifest and this goes RED (WF1015).

NOTE ON pre_conversion_manifest.json: it is NOT regenerated to fix the drift, and must
not be. It is the 5.7 *before* baseline; regenerating it from a 5.8 working tree would
record 5.8 bytes as the 5.7 "before" state — laundering the very thing it exists to
witness. canonical_conversion_manifest.json supersedes it: it sources its 5.7 side from
the frozen tag, so it cannot be contaminated by tree state.

Runtime-free gate.
Report -> procedural/reports/ue5_8/audit/validate_inventory_root_coverage_report.json
Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_inventory_root_coverage.py --strict
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from build_conversion_manifest import CONTENT_ROOTS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_identity import transition_identity  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "audit"
CANONICAL = REPO_ROOT / "procedural/manifests/ue5_8_conversion/canonical_conversion_manifest.json"

def _root_is_genuinely_package_free(root):
    """True when a root really holds no UE packages, on disk AND at the 5.7 tag.

    Deliberately NOT a hard-coded exemption list. `Plugins/WorldForge/Content` legitimately
    contributes zero packages — it holds only a .gitkeep placeholder — so failing on
    "0 packages" would be wrong there. But exempting it BY NAME would also exempt it on
    the day a bug empties it, which is the failure this gate exists to catch. Verifying
    against the filesystem and the frozen tag keeps "empty" a fact rather than a promise.
    """
    live = REPO_ROOT / root
    if live.is_dir():
        for p in live.rglob("*"):
            if p.is_file() and p.suffix in (".uasset", ".umap"):
                return False
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only",
                         "worldforge-v2.4-ue5.7-final", "--", root],
                        cwd=str(REPO_ROOT), capture_output=True, text=True)
    if ls.returncode == 0:
        for f in ls.stdout.splitlines():
            if f.endswith((".uasset", ".umap")):
                return False
    return True


def run(rep, manifest_path=CANONICAL):
    if not Path(manifest_path).is_file():
        rep.check("roots::manifest_present", False,
                  "canonical manifest missing at {}".format(manifest_path),
                  code=C.CONVERSION_MANIFEST_INCOMPLETE)
        return
    rep.check("roots::manifest_present", True, "", code=C.CONVERSION_MANIFEST_INCOMPLETE)

    try:
        m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except ValueError as e:
        rep.check("roots::manifest_parses", False, "unparseable: {}".format(e),
                  code=C.CONVERSION_MANIFEST_INCOMPLETE)
        return
    rep.check("roots::manifest_parses", True, "", code=C.CONVERSION_MANIFEST_INCOMPLETE)

    declared = list(CONTENT_ROOTS)
    recorded = m.get("content_roots")

    rep.check("roots::recorded_present", isinstance(recorded, list) and bool(recorded),
              "manifest records no content_roots — drift is undetectable",
              code=C.CONVERSION_MANIFEST_INCOMPLETE)
    if not isinstance(recorded, list):
        return

    missing = [r for r in declared if r not in recorded]
    extra = [r for r in recorded if r not in declared]
    rep.check("roots::no_drift_vs_script", not missing and not extra,
              "script declares {} but manifest records {} (missing={}, extra={})".format(
                  declared, recorded, missing, extra),
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    per_root = m.get("packages_per_root") or {}
    for root in declared:
        n = per_root.get(root)
        if isinstance(n, int) and n == 0 and _root_is_genuinely_package_free(root):
            # Verified empty: no .uasset/.umap on disk or at the 5.7 tag. Record it as an
            # observed fact so the zero is auditable rather than silently tolerated.
            rep.check("roots::root_verified_package_free::{}".format(root), True,
                      "root holds no UE packages on disk or at the 5.7 tag",
                      code=C.CONVERSION_MANIFEST_INCOMPLETE)
            continue
        rep.check("roots::root_represented::{}".format(root),
                  isinstance(n, int) and n > 0,
                  "declared root {!r} contributes {} packages — a root in code but not in "
                  "data is how CoreTerrainMaterials went unclassified".format(root, n),
                  code=C.CONVERSION_MANIFEST_INCOMPLETE)

    pkgs = m.get("packages") or []
    rep.check("roots::manifest_not_stub", len(pkgs) > 0,
              "canonical manifest has no packages — stub cannot satisfy this gate",
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    # Every package must live under a declared root; a package from nowhere means the
    # keyspace and the roots disagree.
    orphans = [p.get("repo_path") for p in pkgs
               if not any((p.get("repo_path") or "").startswith(r + "/") for r in declared)]
    rep.check("roots::no_orphan_packages", not orphans,
              "packages outside every declared root: {}".format(orphans[:5]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5.1 inventory-root-coverage gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--manifest", default=str(CANONICAL))
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("gate", "inventory_root_coverage", strict=strict)
    run(rep, args.manifest)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-inventory-root-coverage", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.root_coverage_validate.v1",
        extra=transition_identity("5.8", runtime_required=False,
                                  runtime_executed=False,
                                  observed_runtime_engine=None)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_inventory_root_coverage_report.json")
    rep.print_summary("inventory-root-coverage")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
