#!/usr/bin/env python3
"""validate_mesh_rendering_budgets.py — WorldForge v1.2 mesh rendering-budget lane.

Validates that every generated mesh asset carries a complete, coherent rendering
budget (brief §14): a known budget class, a structurally-complete rendering_budget
block, declared nanite / LOD / shadow / raytracing policies drawn from the mesh
contract vocabularies, an explicit raytracing policy where the budget class demands
one, and a budget class that is cap-resolvable against the rendering-profile caps.

This is the budget gate for MeshForge Intake: it does NOT re-check the whole
contract (that is validate_mesh_contract.py) — it focuses on the render cost /
scalability dimension so a performance_safe rendering profile can never silently
inherit a raytraced_high mesh set.

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record), falling back to the definition YAML if a descriptor is absent.

Usage:
    python tools/pipeline/validate_mesh_rendering_budgets.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_rendering_budgets.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_rendering_budgets/validate_mesh_rendering_budgets_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_CODE = FailureCode.MESH_RENDERING_BUDGET_FAILURE

# A raytracing policy that is present, explicit, and NOT the passive default —
# an asset whose budget class requires ray tracing must declare one of these.
_EXPLICIT_RAYTRACING = tuple(
    p for p in MC.RAYTRACING_POLICIES if p != "raytracing_default"
)


def _load_record(asset_id, repo_root=REPO_ROOT):
    """Prefer the descriptor; fall back to the raw definition YAML."""
    desc = MC.mesh_descriptor_path(asset_id, repo_root)
    if desc.is_file():
        try:
            return json.loads(desc.read_text(encoding="utf-8")), None
        except Exception as exc:
            return None, "descriptor unparseable: {}".format(exc)
    data, err = MC.load_mesh_definition(MC.mesh_definition_path(asset_id, repo_root))
    return data, err


def check_asset(rep, asset_id, record, strict):
    """Run all rendering-budget checks for one asset, prefixing check names."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=_CODE)

    # -- budget class known -------------------------------------------------
    budget_class = record.get("budget_class")
    c("budget_class_valid", budget_class in MC.BUDGET_CLASSES,
      "budget_class={}".format(budget_class))

    # -- rendering_budget block present + structurally complete -------------
    rb = record.get("rendering_budget")
    if isinstance(rb, dict):
        missing = [k for k in MC.RENDERING_BUDGET_REQUIRED if k not in rb]
        c("rendering_budget_complete", not missing,
          "rendering_budget missing keys: {}".format(missing))
    else:
        rb = {}
        c("rendering_budget_present", False, "rendering_budget absent")

    # -- policy vocabularies (declared, not None, drawn from the contract) --
    nanite = record.get("nanite_policy")
    c("nanite_policy_valid",
      nanite is not None and nanite in MC.NANITE_POLICIES,
      "nanite_policy={}".format(nanite))

    lod = record.get("lod_policy")
    c("lod_policy_valid",
      lod is not None and lod in MC.LOD_POLICIES,
      "lod_policy={}".format(lod))

    shadow = record.get("shadow_policy")
    c("shadow_policy_declared",
      shadow not in (None, ""),
      "shadow_policy={}".format(shadow))

    raytracing = record.get("raytracing_policy")
    c("raytracing_policy_valid",
      raytracing is not None and raytracing in MC.RAYTRACING_POLICIES,
      "raytracing_policy={}".format(raytracing))

    # -- raytracing-required budgets need an explicit (non-default) policy ---
    if budget_class in MC.RAYTRACING_REQUIRED_BUDGETS:
        c("raytracing_explicit_for_budget",
          raytracing in _EXPLICIT_RAYTRACING,
          "budget_class={} requires an explicit raytracing policy (one of {}), "
          "got raytracing_policy={}".format(
              budget_class, list(_EXPLICIT_RAYTRACING), raytracing))

    # -- cap-resolvable sanity: budget class must resolve under the highest cap
    c("budget_within_high_fidelity_cap",
      MC.budget_within_cap(budget_class, "high_fidelity") is True,
      "budget_class={} is not a known, cap-resolvable class under "
      "high_fidelity".format(budget_class))

    # -- performance_safe consumability: an asset that declares itself
    #    performance_safe may be consumed by a performance_safe profile only if
    #    it is within that profile's cap (brief §14).
    if budget_class == "performance_safe":
        c("performance_safe_within_cap",
          MC.budget_within_cap(budget_class, "performance_safe") is True,
          "performance_safe asset not within performance_safe profile cap: "
          "budget_class={}".format(budget_class))


def validate(pack, strict, asset=None):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    asset_ids = [asset] if asset else [aid for aid, _ in
                                       sorted((catalog.get("assets") or {}).items())]
    if not asset_ids:
        rep.error("no mesh assets found — run 'make create-mesh-assets' first")
        return rep, 0

    n = 0
    for aid in asset_ids:
        record, err = _load_record(aid)
        if record is None:
            rep.check("{}::record_loads".format(aid), False, err or "no record",
                      code=_CODE)
            continue
        check_asset(rep, aid, record, strict)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 mesh rendering budgets.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Validate a single asset id")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict, asset=args.asset)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-rendering-budgets", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_rendering_budgets"
    rep.write(report_dir, "validate_mesh_rendering_budgets_report.json")
    rep.print_summary("validate-mesh-rendering-budgets")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
