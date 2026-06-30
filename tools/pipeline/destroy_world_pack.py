#!/usr/bin/env python3
"""destroy_world_pack.py — WorldForge v0.9 world-pack lifecycle: destroy.

Destroys ONLY the registry-owned generated assets belonging to a world pack's
slices, then removes those slices from the registry. It is the world-pack-scoped
sibling of ``destroy_slice.py`` (one slice) and ``clean_orphans.py`` (unregistered
orphans).

Resolution: ``--pack <id>`` -> ``procedural/world_packs/<id>.yaml`` -> its slice
packs -> every slice ``name``. Only slices that are CURRENTLY in the registry are
destroyed (their registration is what marks them factory-owned). Slices named in
the pack but absent from the registry are reported, never touched (they may be
orphans — use ``clean-orphans``).

Per registered slice, the destroyable target set is exactly the generated
artifacts the factory emits:
  * ``owned_assets``           (e.g. Content/WorldForge/Maps/<name>.umap)
  * the generated slice spec   (procedural/slices/<biome>/generated/<name>.json)
  * the placement DataAsset    (procedural/generated/placement/<name>_da.json)
  * the per-slice report dir   (procedural/reports/slices/<biome>/<name>/)

``referenced_assets`` (shared materials / PCG graphs / shared DAs) are NEVER
targeted. Every target is additionally run through the shared
``clean_orphans.is_generated_owned_path`` gate; any target that is not positively
generated-owned is RETAINED and reported, never deleted.

Default is a DRY-RUN (lists what WOULD be removed, deletes nothing, leaves the
registry untouched). ``--confirm`` (or ``CONFIRM=1``) performs deletion and writes
the registry.

Usage:
    python tools/pipeline/destroy_world_pack.py --pack desert_poi_lite_seed
    python tools/pipeline/destroy_world_pack.py --pack desert_poi_lite_seed --confirm
"""

import argparse
import shutil
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
from registry import load_registry, remove_entry, save_registry  # noqa: E402
import clean_orphans  # noqa: E402  (shared ownership gate)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORLD_PACKS_DIR = REPO_ROOT / "procedural" / "world_packs"
REPORT_DIR_REL = "procedural/reports/world_packs"
REPORT_FILENAME = "destroy_world_pack_report.json"


def _posix(p):
    return str(p).replace("\\", "/")


def resolve_pack_path(pack):
    p = Path(pack)
    if not p.is_absolute():
        if p.suffix:
            p = REPO_ROOT / p
        else:
            p = WORLD_PACKS_DIR / (pack + ".yaml")
    return p


def world_pack_slice_names(pack_path):
    """Return (world_pack_id, [slice_name, ...], [missing_pack_path, ...])."""
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


def _slice_targets(name, entry):
    """Repo-relative POSIX target paths for one registered slice. (path, is_dir)."""
    biome = entry.get("biome", "desert")
    targets = []
    for a in entry.get("owned_assets", []) or []:
        targets.append((_posix(Path(a)), False))
    sp = entry.get("spec_path") or "procedural/slices/{}/generated/{}.json".format(biome, name)
    targets.append((_posix(Path(sp)), False))
    targets.append(("procedural/generated/placement/{}_da.json".format(name), False))
    targets.append(("procedural/reports/slices/{}/{}".format(biome, name), True))
    return targets


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Destroy a world pack's registry-owned generated assets (dry-run by default).")
    ap.add_argument("--pack", required=True, help="world pack id or path (e.g. desert_poi_lite_seed)")
    ap.add_argument("--confirm", action="store_true",
                    help="actually delete + update registry (without it: dry-run)")
    ap.add_argument("--strict", action="store_true", help="strict reporting mode")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    pack_path = resolve_pack_path(args.pack)
    if not pack_path.is_file():
        sys.stderr.write("ERROR: world pack not found: {}\n".format(pack_path))
        sys.exit(1)

    world_pack_id, slice_names, missing_packs = world_pack_slice_names(pack_path)
    registry = load_registry(REPO_ROOT)

    mode = "DELETE (--confirm)" if args.confirm else "DRY-RUN (pass --confirm to delete)"
    print("DESTROY WORLD PACK: {}  MODE: {}  strict={}".format(
        world_pack_id, mode, "on" if strict else "off"))
    print("  slices declared: {}".format(len(slice_names)))

    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    for mp in missing_packs:
        rep.check("slice_pack_resolves:{}".format(mp), False,
                  "referenced slice pack not found: {}".format(mp),
                  code=FailureCode.SPEC_INVALID)

    deleted, would_delete, retained, gone = [], [], [], []
    destroyed_slices, unregistered_slices = [], []

    for name in slice_names:
        entry = registry.get(name)
        if entry is None:
            unregistered_slices.append(name)
            print("  [SKIP] {} — not in registry (nothing owned to destroy)".format(name))
            rep.check("slice_owned:{}".format(name), True,
                      "not registered — no registry-owned assets to destroy "
                      "(run clean-orphans if stray artifacts remain)")
            continue

        print("  slice: {}".format(name))
        any_target_acted = False
        for rel, is_dir in _slice_targets(name, entry):
            full = REPO_ROOT / rel
            safe, reason = clean_orphans.is_safe_to_delete(rel, registry)
            cname = "target:{}".format(rel)

            # The slice's OWN owned_assets are registry-protected against the
            # generic orphan gate; that protection is expected here (we are
            # intentionally destroying this slice), so re-gate on pure path policy.
            if not safe and reason.startswith("tracked by a registry entry"):
                safe, reason = clean_orphans.is_generated_owned_path(rel)

            if not safe:
                retained.append((rel, reason))
                print("    [RETAINED] {} — {}".format(rel, reason))
                rep.check(cname, False,
                          "RETAINED (not generated-owned): {} — {}".format(rel, reason),
                          warn_only=True, code=FailureCode.OWNER_UNRESOLVABLE)
                continue

            if not full.exists():
                gone.append(rel)
                print("    [GONE]     {} — already absent".format(rel))
                continue

            any_target_acted = True
            if args.confirm:
                try:
                    if full.is_dir():
                        shutil.rmtree(str(full))
                    else:
                        full.unlink()
                    deleted.append(rel)
                    print("    [DELETED]  {}".format(rel))
                except OSError as exc:
                    print("    [ERROR]    {} — {}".format(rel, exc))
                    rep.check(cname, False, "failed to delete {}: {}".format(rel, exc),
                              code=FailureCode.REGISTRY_INCONSISTENT)
            else:
                would_delete.append(rel)
                print("    [WOULD-DELETE] {}".format(rel))

        destroyed_slices.append(name)
        if args.confirm:
            registry = remove_entry(registry, name)
        rep.check("slice_destroyed:{}".format(name), True,
                  "{} registry-owned generated assets {}".format(
                      name, "destroyed" if args.confirm else "would be destroyed"))
        _ = any_target_acted

    if args.confirm and destroyed_slices:
        save_registry(REPO_ROOT, registry)
        print("\nRegistry updated — {} slice(s) removed.".format(len(destroyed_slices)))

    rep.finalize()

    print("\nSUMMARY (world pack '{}')".format(world_pack_id))
    print("  registered slices destroyed: {}".format(len(destroyed_slices)))
    print("  unregistered slices skipped: {}".format(len(unregistered_slices)))
    if args.confirm:
        print("  files deleted:   {}".format(len(deleted)))
    else:
        print("  files to delete: {}".format(len(would_delete)))
    print("  retained (unsafe): {}".format(len(retained)))
    print("  already gone:    {}".format(len(gone)))

    rep.write(REPO_ROOT / REPORT_DIR_REL / world_pack_id, REPORT_FILENAME)
    rep.print_summary("destroy-world-pack")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
