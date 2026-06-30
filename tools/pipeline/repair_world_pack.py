#!/usr/bin/env python3
"""repair_world_pack.py — WorldForge v0.9 world-pack lifecycle: repair.

Re-derives / repairs the generated artifacts and registry consistency for every
slice in a world pack, leaning on the existing per-slice repair where a UE step is
involved. World-pack-scoped sibling of ``run_ue_repair.py`` (one slice via UE) and
``repair-slice``.

Resolution: ``--pack <id>`` -> ``procedural/world_packs/<id>.yaml`` -> its slice
packs -> every slice ``name``.

For each slice it diagnoses, and (only with ``--apply``) repairs, the artifacts
the factory can re-derive deterministically without a human/editor step:
  * registry entry present + internally consistent      (REGISTRY_MISSING_ENTRY / _INCONSISTENT)
  * generated slice spec present + parseable            (SPEC_INVALID)
  * placement DataAsset present                         (ARTIFACT_MISSING — re-derivable)
  * UE slice map materialized (owned .umap on disk)     (D7-GATED — needs editor)

Repair actions:
  * default               : report-only diagnosis (mutates nothing).
  * ``--apply``           : re-derive any MISSING placement DataAsset via
                            ``generate_placement_da.py`` (pure Python, no UE).
  * ``--apply --ue``      : additionally run ``run_ue_repair.py`` per registered
                            slice (D7 — needs an editor; otherwise stays gated).

A D7-gated UE map gap never blocks; it clears once a human/editor materializes the
map (``make repair-slice NAME=<slice>``). Exit 0 unless a blocking failure
(missing registry/spec) is found, or ``STRICT=1`` escalates a soft gap.

Usage:
    python tools/pipeline/repair_world_pack.py --pack desert_poi_lite_seed
    python tools/pipeline/repair_world_pack.py --pack desert_poi_lite_seed --apply
    python tools/pipeline/repair_world_pack.py --pack desert_poi_lite_seed --apply --ue
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from registry import load_registry, compute_input_hash  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
WORLD_PACKS_DIR = REPO_ROOT / "procedural" / "world_packs"
GEN_DA_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "generate_placement_da.py"
RUN_UE_REPAIR = REPO_ROOT / "tools" / "pipeline" / "run_ue_repair.py"
REPORT_DIR_REL = "procedural/reports/world_packs"
REPORT_FILENAME = "repair_world_pack_report.json"


def resolve_pack_path(pack):
    p = Path(pack)
    if not p.is_absolute():
        if p.suffix:
            p = REPO_ROOT / p
        else:
            p = WORLD_PACKS_DIR / (pack + ".yaml")
    return p


def world_pack_slice_names(pack_path):
    with pack_path.open("r", encoding="utf-8") as fh:
        wp = yaml.safe_load(fh) or {}
    world_pack_id = wp.get("world_pack_id", pack_path.stem)
    names, missing = [], []
    for entry in wp.get("packs", []) or []:
        rel = entry.get("pack_path", "")
        sp = REPO_ROOT / rel if rel else None
        if not sp or not sp.is_file():
            missing.append(rel or "<unspecified>")
            continue
        with sp.open("r", encoding="utf-8") as fh:
            spack = yaml.safe_load(fh) or {}
        for sl in spack.get("slices", []) or []:
            nm = sl.get("name")
            if nm:
                names.append(nm)
    return world_pack_id, names, missing


def _run(argv):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return subprocess.run([str(a) for a in argv], cwd=str(REPO_ROOT), env=env).returncode


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Repair a world pack's generated artifacts + registry consistency.")
    ap.add_argument("--pack", required=True, help="world pack id or path (e.g. desert_poi_lite_seed)")
    ap.add_argument("--apply", action="store_true",
                    help="re-derive missing pure-Python artifacts (placement DAs)")
    ap.add_argument("--ue", action="store_true",
                    help="with --apply, also run per-slice UE repair (needs editor)")
    ap.add_argument("--strict", action="store_true", help="strict reporting mode")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    pack_path = resolve_pack_path(args.pack)
    if not pack_path.is_file():
        sys.stderr.write("ERROR: world pack not found: {}\n".format(pack_path))
        sys.exit(1)

    world_pack_id, slice_names, missing_packs = world_pack_slice_names(pack_path)
    registry = load_registry(REPO_ROOT)

    print("REPAIR WORLD PACK: {}  mode: {}  strict={}".format(
        world_pack_id, "APPLY" if args.apply else "DIAGNOSE", "on" if strict else "off"))
    print("  slices declared: {}".format(len(slice_names)))

    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    for mp in missing_packs:
        rep.check("slice_pack_resolves:{}".format(mp), False,
                  "referenced slice pack not found: {}".format(mp),
                  code=FailureCode.SPEC_INVALID)

    repaired = []

    for name in slice_names:
        entry = registry.get(name)

        # 1. registry presence
        if entry is None:
            rep.check("{}:registered".format(name), False,
                      "slice declared by world pack but missing from registry "
                      "— run create-world-pack PACK={}".format(world_pack_id),
                      code=FailureCode.REGISTRY_MISSING_ENTRY)
            print("  [MISSING] {} — not in registry".format(name))
            continue
        rep.check("{}:registered".format(name), True, "present in registry")

        biome = entry.get("biome", "desert")

        # 2. generated spec present + parseable
        spec_rel = entry.get("spec_path") or \
            "procedural/slices/{}/generated/{}.json".format(biome, name)
        spec_path = REPO_ROOT / spec_rel
        spec = None
        if spec_path.is_file():
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                rep.check("{}:spec_parseable".format(name), False,
                          "spec unparseable: {}".format(exc),
                          code=FailureCode.SPEC_INVALID)
        rep.check("{}:spec_present".format(name), spec is not None,
                  "generated spec missing/unparseable: {}".format(spec_rel),
                  code=FailureCode.SPEC_INVALID)

        # 3. registry internal consistency
        rep.check("{}:registry_consistent".format(name),
                  bool(entry.get("map_path")) and bool(entry.get("owned_assets")),
                  "registry entry missing map_path/owned_assets",
                  warn_only=True, code=FailureCode.REGISTRY_INCONSISTENT)
        if spec is not None and entry.get("input_hash"):
            cur = compute_input_hash(spec)
            rep.check("{}:input_hash_fresh".format(name),
                      cur == entry.get("input_hash"),
                      "registry input_hash is stale vs current spec "
                      "— rebuild slice to re-stamp",
                      warn_only=True, code=FailureCode.REGISTRY_INCONSISTENT)

        # 4. placement DA present (re-derivable without UE)
        da_path = REPO_ROOT / "procedural" / "generated" / "placement" / (name + "_da.json")
        if da_path.is_file():
            rep.check("{}:placement_da".format(name), True, "placement DA present")
        elif args.apply and spec is not None:
            rc = _run([sys.executable, GEN_DA_SCRIPT, "--spec", str(spec_path)])
            ok = rc == 0 and da_path.is_file()
            rep.check("{}:placement_da".format(name), ok,
                      "re-derived placement DA via generate_placement_da" if ok
                      else "failed to re-derive placement DA (rc={})".format(rc),
                      code=FailureCode.ARTIFACT_MISSING)
            if ok:
                repaired.append("{} placement DA".format(name))
                print("  [REPAIRED] {} placement DA".format(name))
        else:
            rep.check("{}:placement_da".format(name), False,
                      "placement DA missing: {} — re-run with --apply to re-derive".format(
                          da_path.relative_to(REPO_ROOT).as_posix()),
                      code=FailureCode.ARTIFACT_MISSING)

        # 5. UE slice map materialization (D7-gated)
        owned_umaps = [a for a in entry.get("owned_assets", []) or [] if str(a).endswith(".umap")]
        map_on_disk = all((REPO_ROOT / a).is_file() for a in owned_umaps) if owned_umaps else False
        rep.gated("{}:ue_map_materialized".format(name), map_on_disk,
                  "slice map not materialized on disk — run "
                  "`make repair-slice NAME={}` (editor)".format(name),
                  code=FailureCode.UE_MATERIALIZATION_PENDING)
        if args.apply and args.ue and not map_on_disk:
            rc = _run([sys.executable, RUN_UE_REPAIR, "--name", name])
            print("  [UE-REPAIR] {} rc={}".format(name, rc))
            if rc == 0:
                repaired.append("{} UE map".format(name))

    rep.finalize()

    print("\nSUMMARY (world pack '{}')".format(world_pack_id))
    print("  slices checked: {}".format(len(slice_names)))
    print("  repaired:       {}".format(len(repaired)))
    for r in repaired:
        print("    - {}".format(r))

    rep.write(REPO_ROOT / REPORT_DIR_REL / world_pack_id, REPORT_FILENAME)
    rep.print_summary("repair-world-pack")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
