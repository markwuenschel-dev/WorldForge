#!/usr/bin/env python3
"""clean_orphans.py — WorldForge v0.9 hardened orphan remover.

Removes generated-content orphans found by ``list_orphans.scan_orphans`` — slice
specs / placement DataAssets / slice maps / per-slice report dirs that exist on
disk but whose owning slice_id is not in ``worldforge_registry.json``.

Default is a DRY-RUN that lists exactly what WOULD be removed and deletes nothing.
``--confirm`` (or ``CONFIRM=1`` via the Makefile) is required to actually delete.

LOAD-BEARING SAFETY (``is_safe_to_delete`` — the single ownership gate reused by
``list_orphans`` and ``destroy_world_pack``): an artifact may be removed ONLY when
its path is positively resolved as *generated-owned*. It is NEVER removed when it
is:
  * a registry ``owned_assets`` / ``referenced_assets`` path (shared/owned elsewhere);
  * under a human/shared/internal tree — material masters (``Content/Materials``),
    PCG graph internals (``Content/Procedural``), Houdini source (``Content/Houdini*``,
    ``Content/HoudiniEngine``), shared catalog/preset definitions
    (``procedural/definitions``), human variant templates
    (``procedural/slices/<biome>/*.yaml``, i.e. NOT under ``generated/``), or tools.
If ownership cannot be positively resolved as generated-owned, the path is
reported and RETAINED — never deleted.

Usage:
    python tools/pipeline/clean_orphans.py             # dry-run (deletes nothing)
    python tools/pipeline/clean_orphans.py --confirm   # actually delete
"""

import argparse
import shutil
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from registry import load_registry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

REPORT_DIR_REL = "procedural/reports/orphans"
REPORT_FILENAME = "clean_orphans_report.json"

# Prefixes (repo-relative POSIX) a generated-owned, destroyable artifact may live
# under. ``procedural/slices/`` is gated further: only ``.../generated/...``.
ALLOWED_PREFIXES = (
    "Content/WorldForge/Maps/",
    "procedural/slices/",            # only under a generated/ subdir (enforced below)
    "procedural/reports/slices/",
    "procedural/generated/placement/",
)

# Prefixes that are NEVER safe to delete from — human-owned / shared / internal.
BLOCKED_PREFIXES = (
    "Content/Materials/",            # material masters
    "Content/Procedural/",           # PCG graph internals
    "Content/HoudiniEngine/",        # Houdini source / intermediate
    "Content/Houdini/",
    "Content/WorldForge/Placeholder/",
    "procedural/definitions/",       # shared catalogs / presets / recipes
    "procedural/substance/",
    "procedural/manifests/",
    "tools/",
    "Source/",
    "Config/",
)


def _posix(p):
    return str(p).replace("\\", "/")


def _registry_protected_paths(registry):
    protected = set()
    for entry in registry.values():
        for a in entry.get("owned_assets", []) or []:
            protected.add(_posix(Path(a)))
        for r in entry.get("referenced_assets", []) or []:
            protected.add(_posix(r))
    return protected


def is_generated_owned_path(rel_posix):
    """Pure path-policy gate. Return (ok, reason).

    True ONLY when ``rel_posix`` is under a generated-owned tree and not under any
    blocked human/shared/internal tree. No registry knowledge here.
    """
    rel = _posix(rel_posix)
    for bp in BLOCKED_PREFIXES:
        if rel.startswith(bp):
            return False, "under blocked tree {}".format(bp)
    for ap in ALLOWED_PREFIXES:
        if rel.startswith(ap):
            if ap == "procedural/slices/" and "/generated/" not in rel:
                return False, "procedural/slices path is a human template (not under generated/)"
            return True, "generated-owned ({})".format(ap)
    return False, "not under any generated-owned tree"


def is_safe_to_delete(rel_posix, registry):
    """Full ownership gate = registry guard + path policy. Return (ok, reason).

    Reused by list_orphans (to classify) and destroy_world_pack (to gate each
    target). A path tracked by ANY registry entry is protected even if it sits
    under a generated-owned tree.
    """
    rel = _posix(rel_posix)
    if rel in _registry_protected_paths(registry):
        return False, "tracked by a registry entry (owned/referenced) — not an orphan"
    return is_generated_owned_path(rel)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Remove WorldForge orphaned generated content (dry-run by default).")
    ap.add_argument("--confirm", action="store_true",
                    help="actually delete (without it: dry-run, deletes nothing)")
    ap.add_argument("--strict", action="store_true",
                    help="strict: orphan findings become blocking (exit 1)")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    import list_orphans  # sibling; provides the pure scan

    registry = load_registry(REPO_ROOT)
    orphans = list_orphans.scan_orphans(REPO_ROOT, registry)

    mode = "DELETE (--confirm)" if args.confirm else "DRY-RUN (pass --confirm to delete)"
    print("CLEAN ORPHANS — MODE: {}  strict={}".format(mode, "on" if strict else "off"))

    rep = ValidationReport("clean_orphans", "generated_content", strict=strict)

    if not orphans:
        print("  no orphaned generated content found — nothing to clean.")
        rep.check("no_orphaned_generated_content", True,
                  "every generated artifact resolves to a registry-owned slice")
        rep.finalize()
        rep.write(REPO_ROOT / REPORT_DIR_REL, REPORT_FILENAME)
        rep.print_summary("clean-orphans")
        return rep.exit_code

    deleted, would_delete, retained, gone = [], [], [], []

    for o in orphans:
        rel = o["path"]
        full = REPO_ROOT / rel
        safe, reason = is_safe_to_delete(rel, registry)
        name = "orphan:{}".format(rel)

        if not safe:
            retained.append((rel, reason))
            print("  [RETAINED] {} — {}".format(rel, reason))
            rep.check(name, False,
                      "RETAINED (ownership not generated-owned): {} — {}".format(rel, reason),
                      warn_only=True, code=FailureCode.OWNER_UNRESOLVABLE)
            continue

        if not full.exists():
            gone.append(rel)
            print("  [GONE]     {} — already absent".format(rel))
            rep.check(name, True, "already absent: {}".format(rel))
            continue

        if args.confirm:
            try:
                if full.is_dir():
                    shutil.rmtree(str(full))
                else:
                    full.unlink()
                deleted.append(rel)
                print("  [DELETED]  {}".format(rel))
                rep.check(name, False, "DELETED orphan {} ({})".format(rel, o["kind"]),
                          warn_only=True, code=FailureCode.REGISTRY_MISSING_ENTRY)
            except OSError as exc:
                print("  [ERROR]    {} — {}".format(rel, exc))
                rep.check(name, False, "failed to delete {}: {}".format(rel, exc),
                          code=FailureCode.REGISTRY_INCONSISTENT)
        else:
            would_delete.append(rel)
            print("  [WOULD-DELETE] {}  ({})".format(rel, o["kind"]))
            rep.check(name, False,
                      "orphaned {} (slice_id={}) — would delete with --confirm".format(
                          o["kind"], o["slice_id"]),
                      warn_only=True, code=FailureCode.REGISTRY_MISSING_ENTRY)

    rep.finalize()

    print("\nSUMMARY")
    if args.confirm:
        print("  deleted:       {}".format(len(deleted)))
    else:
        print("  would delete:  {}".format(len(would_delete)))
    print("  retained (unsafe): {}".format(len(retained)))
    print("  already gone:  {}".format(len(gone)))

    rep.write(REPO_ROOT / REPORT_DIR_REL, REPORT_FILENAME)
    rep.print_summary("clean-orphans")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
