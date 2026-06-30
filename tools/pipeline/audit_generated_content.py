#!/usr/bin/env python3
r"""audit_generated_content.py — WorldForge v0.9 repo-wide ownership/provenance/path audit.

ONE read-only command that sweeps EVERY surface of generated content in the repo
and asserts the v0.9 ownership contract on each item:

  * a registry entry exists for the artifact            (REGISTRY_MISSING_ENTRY)
  * provenance is stamped                               (PROVENANCE_MISSING)
  * ``generated_owned`` is explicit where applicable    (GENERATED_FLAG_MISSING)
  * the final path is under an allowed owned tree        (PATH_NOT_OWNED)
  * a temp/bake path is never a final registered path    (FORBIDDEN_PATH / TEMP_PATH_AS_FINAL)
  * human-owned templates/deps are not destroyable       (DESTROYABLE_HUMAN_OWNED)
    nor flagged generated-owned                          (HUMAN_TEMPLATE_MARKED_GENERATED)
  * the owning forge/registry is resolvable              (OWNER_UNRESOLVABLE)

Surfaces covered (discovered from ``procedural/generated/**`` + each registry):
generated slices/maps, terrain artifacts + descriptors, placement DataAssets,
POI descriptors, runtime-scenario outputs, generated Houdini assets, asset
catalogs, all registries, and the provenance blocks on every descriptor.

It is the audit companion to ``worldforge-doctor`` (environment health) and the
per-artifact validators (``validate-terrain`` / ``validate-generated-asset`` /
``validate-runtime-state``): the validators check ONE artifact deeply; this audit
checks that NOTHING across the whole tree has slipped its ownership/provenance/path
guarantees, including registry/disk orphans the single-artifact validators never see.

NON-MUTATING: it never writes into project ``Content/**`` or any registry. The
only thing it writes is its own report under ``procedural/reports/audit/``.

Usage:
    python tools/pipeline/audit_generated_content.py            # audit
    python tools/pipeline/audit_generated_content.py --strict   # soft WARNs block
    python tools/pipeline/audit_generated_content.py --quiet    # roll-up only

Strict is also honored via STRICT=1 (v0.9 contract). Strict only ever ADDS
blocking: a missing-provenance soft gap becomes blocking; a hard ownership/path
violation FAILs in both modes.

Exit 0 when clean (status ok|warn), 1 when a blocking check FAILs.
"""

import argparse
import json
import sys
from pathlib import Path

# This file lives in tools/pipeline/. Make sibling contract + registry modules
# importable regardless of the caller's working directory.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from validation_report import (  # noqa: E402  (sibling contract module)
    ValidationReport,
    strict_from_env,
    PASS,
    WARN,
    WARN_ONLY,
    FAIL,
    GATED_HUMAN_EDITOR,
    SKIP_NOT_APPLICABLE,
)
from failure_codes import FailureCode  # noqa: E402

# Existing registry / provenance modules — REUSED, never reimplemented.
from registry import load_registry  # noqa: E402
from terrain_registry import load_terrain_registry  # noqa: E402
from poi_registry import load_poi_registry  # noqa: E402
from scenario_registry import load_scenario_registry  # noqa: E402
from generated_asset_registry import (  # noqa: E402
    load_generated_asset_registry,
    is_forbidden_path,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

REPORT_DIR_REL = "procedural/reports/audit"
REPORT_FILENAME = "audit_generated_content_report.json"

# Allowed "owned" trees a FINAL registered path may live under.
OWNED_UE_PREFIX = "/Game/WorldForge/"        # UE content paths the factory owns
OWNED_CONTENT_PREFIX = "Content/WorldForge/"  # on-disk .umap/.uasset the factory owns
OWNED_REPO_PREFIX = "procedural/generated/"   # repo-side generated artifacts/descriptors

# Surfaces, in report order.
SURFACES = (
    "registries",
    "generated_assets",
    "terrain",
    "poi",
    "slices",
    "placement",
    "scenarios",
    "catalogs",
)


# ---------------------------------------------------------------------------
# Auditor — thin wrapper over ValidationReport that namespaces checks per
# surface (so one repo-wide report stays readable) and tracks surface membership
# for the per-surface roll-up.
# ---------------------------------------------------------------------------

class Auditor:
    def __init__(self, rep):
        self.rep = rep
        self.surface_of = {}   # full check name -> surface
        self.items = {s: set() for s in SURFACES}  # surface -> item ids seen

    def _full(self, surface, item, name):
        return "{}:{}:{}".format(surface, item, name) if item else "{}:{}".format(surface, name)

    def seen(self, surface, item):
        self.items.setdefault(surface, set()).add(item)

    def chk(self, surface, item, name, ok, detail="", code=None,
            warn_only=False, allow_in_strict=False):
        full = self._full(surface, item, name)
        self.surface_of[full] = surface
        return self.rep.check(full, ok, detail, warn_only=warn_only, code=code,
                              allow_in_strict=allow_in_strict)

    def warn(self, surface, item, name, ok, detail="", code=None):
        return self.chk(surface, item, name, ok, detail, code=code, warn_only=True)

    def skip(self, surface, item, name, detail=""):
        full = self._full(surface, item, name)
        self.surface_of[full] = surface
        return self.rep.skip(full, detail)

    # -- shared path-ownership audit ------------------------------------------
    def audit_final_path(self, surface, item, label, path):
        """A FINAL registered path must live in an owned tree and never be a
        forbidden Houdini Temp/Bake path."""
        path = (path or "").strip()
        if not path:
            self.chk(surface, item, label + "_path_present", False,
                     "{} is empty/missing".format(label),
                     code=FailureCode.PATH_NOT_OWNED)
            return
        if path.startswith("/Game/"):
            # Forbidden temp/bake as a FINAL path is the load-bearing intake guard.
            self.chk(surface, item, label + "_not_temp_bake",
                     not is_forbidden_path(path),
                     "{} is a forbidden Houdini Temp/Bake path: {}".format(label, path),
                     code=FailureCode.FORBIDDEN_PATH)
            self.chk(surface, item, label + "_owned",
                     path.startswith(OWNED_UE_PREFIX),
                     "{} must be under {} — got {}".format(label, OWNED_UE_PREFIX, path),
                     code=FailureCode.PATH_NOT_OWNED)
        elif path.startswith("Content/") or path.endswith((".umap", ".uasset")):
            self.chk(surface, item, label + "_owned",
                     path.startswith(OWNED_CONTENT_PREFIX),
                     "{} must be under {} — got {}".format(label, OWNED_CONTENT_PREFIX, path),
                     code=FailureCode.PATH_NOT_OWNED)
        else:
            self.chk(surface, item, label + "_owned",
                     path.startswith(OWNED_REPO_PREFIX),
                     "{} must be under {} — got {}".format(label, OWNED_REPO_PREFIX, path),
                     code=FailureCode.PATH_NOT_OWNED)

    def audit_provenance(self, surface, item, descriptor, soft=False):
        """Provenance must be stamped (and, if present, reasonably complete)."""
        prov = descriptor.get("provenance") if isinstance(descriptor, dict) else None
        present = isinstance(prov, dict) and bool(prov)
        self.chk(surface, item, "provenance_present", present,
                 "no provenance block on descriptor — regenerate to stamp it",
                 code=FailureCode.PROVENANCE_MISSING, warn_only=soft)
        if present:
            # generator identity + a commit + an inputs map is the minimum honest
            # provenance shape (provenance.build_provenance / create_slice_spec).
            has_gen = bool(prov.get("generator_name") or prov.get("generator"))
            has_stamp = bool(prov.get("generated_at_utc"))
            complete = has_gen and has_stamp
            self.warn(surface, item, "provenance_complete", complete,
                      "provenance missing generator/timestamp fields: {}".format(
                          sorted(prov.keys())),
                      code=FailureCode.PROVENANCE_INCOMPLETE)

    def audit_owner(self, surface, item, descriptor, expected_registry):
        """The owning registry/forge must be resolvable from the descriptor."""
        owner = descriptor.get("registry_owner") if isinstance(descriptor, dict) else None
        if owner is None:
            # Older descriptors predate registry_owner; resolve via the fact that
            # a registry entry was found (caller asserts that separately). Treat a
            # missing stamp as a soft owner-resolution gap, not a hard fail.
            self.warn(surface, item, "owner_resolvable", False,
                      "descriptor has no registry_owner stamp; owner inferred from "
                      "{} membership".format(expected_registry),
                      code=FailureCode.OWNER_UNRESOLVABLE)
        else:
            self.chk(surface, item, "owner_resolvable", owner == expected_registry,
                     "registry_owner={} (expected {})".format(owner, expected_registry),
                     code=FailureCode.OWNER_UNRESOLVABLE)

    def audit_human_template_integrity(self, surface, item, descriptor):
        """A descriptor that REPRESENTS a human-owned template must not be flagged
        generated-owned or destroyable. Fires only when the item declares itself a
        template; otherwise genuinely not applicable."""
        if not isinstance(descriptor, dict):
            return
        is_template = bool(descriptor.get("is_template")) or \
            descriptor.get("human_owned") is True
        if not is_template:
            self.skip(surface, item, "human_template_integrity",
                      "item is not a human-owned template")
            return
        self.chk(surface, item, "template_not_generated_owned",
                 descriptor.get("generated_owned") is not True,
                 "a human-owned template must not be marked generated_owned",
                 code=FailureCode.HUMAN_TEMPLATE_MARKED_GENERATED)
        self.chk(surface, item, "template_not_destroyable",
                 descriptor.get("destroyable") is not True,
                 "a human-owned template must not be marked destroyable",
                 code=FailureCode.DESTROYABLE_HUMAN_OWNED)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _rel(path):
    # POSIX-normalize repo-relative paths so ownership-prefix checks match the
    # forward-slash convention every registry/descriptor stores (see provenance.py).
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def _load_yaml():
    try:
        import yaml  # noqa: F401
        return yaml
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-surface audits
# ---------------------------------------------------------------------------

def audit_registries(a):
    """Every registry root must be present and parseable."""
    gen = REPO_ROOT / "procedural" / "generated"
    roots = sorted(gen.glob("worldforge_*registry*.json")) if gen.is_dir() else []
    if not roots:
        a.warn("registries", "", "any_registry_present", False,
               "no worldforge_*registry*.json under procedural/generated — "
               "nothing has been built/tracked",
               code=FailureCode.REGISTRY_MISSING_ENTRY)
        return
    for p in roots:
        item = p.stem
        a.seen("registries", item)
        data, err = _load_json(p)
        a.chk("registries", item, "parseable", err is None,
              "unparseable registry root: {}".format(err),
              code=FailureCode.REGISTRY_INCONSISTENT)
        if err is None:
            n = len(data) if isinstance(data, dict) else 0
            a.chk("registries", item, "is_object", isinstance(data, dict),
                  "registry root must be a JSON object of entries (got {})".format(type(data).__name__),
                  code=FailureCode.REGISTRY_INCONSISTENT)
            a.skip("registries", item, "entry_count", "{} entry(ies)".format(n))


def audit_generated_assets(a):
    """Houdini-baked / generated owned assets (the intake ledger)."""
    surface = "generated_assets"
    registry = load_generated_asset_registry(REPO_ROOT)
    gen_dir = REPO_ROOT / "procedural" / "generated" / "generated_assets"
    disk_ids = set()
    if gen_dir.is_dir():
        for desc in sorted(gen_dir.glob("*/descriptor.json")):
            disk_ids.add(desc.parent.name)

    all_ids = sorted(set(registry.keys()) | disk_ids)
    if not all_ids:
        a.skip(surface, "", "present", "no generated assets discovered")
        return

    for asset_id in all_ids:
        a.seen(surface, asset_id)
        in_reg = asset_id in registry
        a.chk(surface, asset_id, "registry_entry", in_reg,
              "not in worldforge_generated_asset_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

        desc_path = gen_dir / asset_id / "descriptor.json"
        descriptor, err = (None, "missing")
        if desc_path.is_file():
            descriptor, err = _load_json(desc_path)
        a.chk(surface, asset_id, "descriptor_present", descriptor is not None,
              "descriptor.json missing/unparseable at {}: {}".format(_rel(desc_path), err),
              code=FailureCode.DESCRIPTOR_MISSING)
        if descriptor is None:
            continue

        # registry entry must point at this descriptor on disk
        if in_reg:
            reg_desc = registry[asset_id].get("descriptor_path", "")
            a.chk(surface, asset_id, "registry_descriptor_resolves",
                  bool(reg_desc) and (REPO_ROOT / reg_desc).is_file(),
                  "registry descriptor_path does not resolve: {}".format(reg_desc),
                  code=FailureCode.REGISTRY_INCONSISTENT)

        unreal_path = descriptor.get("unreal_path", "")
        a.audit_final_path(surface, asset_id, "unreal", unreal_path)
        a.audit_provenance(surface, asset_id, descriptor)
        a.audit_owner(surface, asset_id, descriptor, "worldforge_generated_asset_registry")
        a.audit_human_template_integrity(surface, asset_id, descriptor)

        # generated_owned must be EXPLICIT True (this surface carries the flag).
        a.chk(surface, asset_id, "generated_owned_explicit",
              descriptor.get("generated_owned") is True,
              "generated_owned={} (must be explicit true)".format(descriptor.get("generated_owned")),
              code=FailureCode.GENERATED_FLAG_MISSING)

        # temporary must not be a final registered asset
        a.chk(surface, asset_id, "not_temporary",
              descriptor.get("temporary") is not True,
              "temporary={} but asset is registered as final".format(descriptor.get("temporary")),
              code=FailureCode.TEMP_PATH_AS_FINAL)

        # source_bake_path is allowed ONLY as provenance, never as the final path
        bake = descriptor.get("source_bake_path")
        if bake:
            a.chk(surface, asset_id, "bake_path_not_final",
                  bake != unreal_path and not is_forbidden_path(unreal_path),
                  "final unreal_path coincides with a Houdini bake/temp path: {}".format(unreal_path),
                  code=FailureCode.TEMP_PATH_AS_FINAL)

    # registry entries whose on-disk descriptor is gone (orphans)
    for asset_id in sorted(set(registry.keys()) - disk_ids):
        a.chk(surface, asset_id, "descriptor_on_disk", False,
              "registry entry has no descriptor under {}".format(_rel(gen_dir / asset_id)),
              code=FailureCode.REGISTRY_INCONSISTENT)


def audit_terrain(a):
    surface = "terrain"
    registry = load_terrain_registry(REPO_ROOT)
    base = REPO_ROOT / "procedural" / "generated" / "terrain"
    disk_ids = set()
    if base.is_dir():
        for desc in sorted(base.glob("*/descriptor.json")):
            disk_ids.add(desc.parent.name)
    all_ids = sorted(set(registry.keys()) | disk_ids)
    if not all_ids:
        a.skip(surface, "", "present", "no terrain artifacts discovered")
        return

    for name in all_ids:
        a.seen(surface, name)
        a.chk(surface, name, "registry_entry", name in registry,
              "not in worldforge_terrain_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

        desc_path = base / name / "descriptor.json"
        descriptor, err = (None, "missing")
        if desc_path.is_file():
            descriptor, err = _load_json(desc_path)
        a.chk(surface, name, "descriptor_present", descriptor is not None,
              "descriptor.json missing/unparseable: {}".format(err),
              code=FailureCode.DESCRIPTOR_MISSING)
        if descriptor is None:
            continue

        a.audit_final_path(surface, name, "descriptor", _rel(desc_path))
        a.audit_provenance(surface, name, descriptor)
        a.audit_owner(surface, name, descriptor, "worldforge_terrain_registry")
        a.audit_human_template_integrity(surface, name, descriptor)

        # owned output masks/heightmaps must be under the owned repo tree + exist
        outputs = descriptor.get("outputs", {}) or {}
        for okey, opath in sorted(outputs.items()):
            a.audit_final_path(surface, name, "output_" + okey, opath)
            a.chk(surface, name, "output_{}_exists".format(okey),
                  (REPO_ROOT / opath).is_file(),
                  "declared output missing on disk: {}".format(opath),
                  code=FailureCode.ARTIFACT_MISSING)


def audit_poi(a):
    surface = "poi"
    registry = load_poi_registry(REPO_ROOT)
    base = REPO_ROOT / "procedural" / "generated" / "poi"
    disk_ids = set()
    if base.is_dir():
        for desc in sorted(base.glob("*/descriptor.json")):
            disk_ids.add(desc.parent.name)
    all_ids = sorted(set(registry.keys()) | disk_ids)
    if not all_ids:
        a.skip(surface, "", "present", "no POI descriptors discovered")
        return

    for name in all_ids:
        a.seen(surface, name)
        a.chk(surface, name, "registry_entry", name in registry,
              "not in worldforge_poi_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

        desc_path = base / name / "descriptor.json"
        descriptor, err = (None, "missing")
        if desc_path.is_file():
            descriptor, err = _load_json(desc_path)
        a.chk(surface, name, "descriptor_present", descriptor is not None,
              "descriptor.json missing/unparseable: {}".format(err),
              code=FailureCode.DESCRIPTOR_MISSING)
        if descriptor is None:
            continue

        a.audit_final_path(surface, name, "descriptor", _rel(desc_path))
        a.audit_provenance(surface, name, descriptor)
        a.audit_owner(surface, name, descriptor, "worldforge_poi_registry")
        a.audit_human_template_integrity(surface, name, descriptor)


def audit_slices(a):
    surface = "slices"
    registry = load_registry(REPO_ROOT)
    spec_dir = REPO_ROOT / "procedural" / "slices" / "desert" / "generated"
    disk_specs = {}
    if spec_dir.is_dir():
        for sp in sorted(spec_dir.glob("*.json")):
            disk_specs[sp.stem] = sp

    all_ids = sorted(set(registry.keys()) | set(disk_specs.keys()))
    if not all_ids:
        a.skip(surface, "", "present", "no slices discovered")
        return

    for sid in all_ids:
        a.seen(surface, sid)
        entry = registry.get(sid)
        a.chk(surface, sid, "registry_entry", entry is not None,
              "slice spec on disk but not in worldforge_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

        # spec file (carries the slice's provenance) must exist + be parseable
        spec_path = disk_specs.get(sid)
        if spec_path is None and entry is not None:
            sp = entry.get("spec_path")
            if sp and (REPO_ROOT / sp).is_file():
                spec_path = REPO_ROOT / sp
        spec = None
        if spec_path is not None:
            spec, _ = _load_json(spec_path)
        a.chk(surface, sid, "spec_present", spec is not None,
              "slice spec missing/unparseable",
              code=FailureCode.SPEC_INVALID)
        if spec is not None:
            a.audit_provenance(surface, sid, spec)

        if entry is None:
            continue

        # owner resolvable: a slice belongs to a pack
        a.chk(surface, sid, "owner_resolvable", bool(entry.get("pack_id")),
              "registry entry has no pack_id (owning pack unresolved)",
              code=FailureCode.OWNER_UNRESOLVABLE)

        # final UE map path must be owned
        a.audit_final_path(surface, sid, "map", entry.get("map_path", ""))

        # owned (destroyable) assets must all live in the owned tree...
        owned = entry.get("owned_assets", []) or []
        referenced = set(entry.get("referenced_assets", []) or [])
        a.chk(surface, sid, "has_owned_assets", bool(owned),
              "registry entry lists no owned_assets",
              code=FailureCode.REGISTRY_INCONSISTENT, warn_only=True)
        for oa in owned:
            a.audit_final_path(surface, sid, "owned_asset", oa)
            # ...and must never include a human-owned referenced dependency:
            # owned_assets are the destroyable set; referenced_assets are not.
            a.chk(surface, sid, "owned_not_a_referenced_dep",
                  oa not in referenced,
                  "owned/destroyable list includes a human-owned referenced "
                  "dependency: {}".format(oa),
                  code=FailureCode.DESTROYABLE_HUMAN_OWNED)


def audit_placement(a):
    surface = "placement"
    slice_registry = load_registry(REPO_ROOT)
    base = REPO_ROOT / "procedural" / "generated" / "placement"
    das = sorted(base.glob("*_da.json")) if base.is_dir() else []
    if not das:
        a.skip(surface, "", "present", "no placement DataAssets discovered")
        return

    for dp in das:
        da, err = _load_json(dp)
        item = dp.stem
        a.seen(surface, item)
        a.chk(surface, item, "parseable", da is not None,
              "placement DA unparseable: {}".format(err),
              code=FailureCode.DESCRIPTOR_UNPARSEABLE)
        if da is None:
            continue

        da_id = da.get("da_id", item)
        # placement DAs are owned BY their slice — that slice must be registered
        slice_id = da.get("slice_id", "")
        a.chk(surface, da_id, "owning_slice_registered",
              bool(slice_id) and slice_id in slice_registry,
              "placement DA references slice '{}' that is not registered".format(slice_id),
              code=FailureCode.OWNER_UNRESOLVABLE)
        # the on-disk DA must live under the owned repo tree
        a.audit_final_path(surface, da_id, "descriptor", _rel(dp))
        # its UE map binding must be owned
        a.audit_final_path(surface, da_id, "map", da.get("map_path", ""))
        # placement DAs currently carry no provenance block — surface as a soft
        # gap (blocks under --strict), not a hard fail, since it is a known
        # lightweight-descriptor shape rather than corruption.
        a.warn(surface, da_id, "provenance_present", bool(da.get("provenance")),
               "placement DataAsset has no provenance block (lightweight descriptor)",
               code=FailureCode.PROVENANCE_MISSING)


def audit_scenarios(a):
    surface = "scenarios"
    registry = load_scenario_registry(REPO_ROOT)
    base = REPO_ROOT / "procedural" / "generated" / "scenarios"
    disk_ids = set()
    if base.is_dir():
        for res in sorted(base.glob("*/result.json")):
            disk_ids.add(res.parent.name)
    all_ids = sorted(set(registry.keys()) | disk_ids)
    if not all_ids:
        a.skip(surface, "", "present", "no runtime scenarios discovered")
        return

    for run_id in all_ids:
        a.seen(surface, run_id)
        a.chk(surface, run_id, "registry_entry", run_id in registry,
              "not in worldforge_scenario_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

        res_path = base / run_id / "result.json"
        result, err = (None, "missing")
        if res_path.is_file():
            result, err = _load_json(res_path)
        a.chk(surface, run_id, "result_present", result is not None,
              "result.json missing/unparseable: {}".format(err),
              code=FailureCode.DESCRIPTOR_MISSING)
        if result is None:
            continue

        a.audit_final_path(surface, run_id, "result", _rel(res_path))
        a.audit_provenance(surface, run_id, result)
        a.audit_owner(surface, run_id, result, "worldforge_scenario_registry")

        outputs = result.get("outputs", {}) or {}
        for okey, opath in sorted(outputs.items()):
            a.audit_final_path(surface, run_id, "output_" + okey, opath)
            a.chk(surface, run_id, "output_{}_exists".format(okey),
                  (REPO_ROOT / opath).is_file(),
                  "declared output missing on disk: {}".format(opath),
                  code=FailureCode.ARTIFACT_MISSING)


def audit_catalogs(a, yaml_mod):
    """Asset catalogs are human-owned, but every PCG-eligible GENERATED asset that
    claims catalog membership must actually be listed (else PCG can't see it)."""
    surface = "catalogs"
    cat_dir = REPO_ROOT / "procedural" / "definitions" / "assets"
    catalogs = sorted(cat_dir.glob("*.yaml")) if cat_dir.is_dir() else []
    if not catalogs:
        a.skip(surface, "", "present", "no asset catalogs found")
        return
    if yaml_mod is None:
        a.skip(surface, "", "parse", "pyyaml missing — cannot read catalogs")
        return

    loaded = {}
    for cp in catalogs:
        item = cp.stem
        a.seen(surface, item)
        try:
            loaded[item] = yaml_mod.safe_load(cp.read_text(encoding="utf-8")) or {}
            a.chk(surface, item, "parseable", True, str(_rel(cp)))
        except Exception as exc:  # noqa: BLE001
            a.chk(surface, item, "parseable", False,
                  "catalog unparseable: {}".format(exc),
                  code=FailureCode.SPEC_INVALID)

    # membership cross-check for generated assets that opt into a catalog
    registry = load_generated_asset_registry(REPO_ROOT)
    gen_dir = REPO_ROOT / "procedural" / "generated" / "generated_assets"
    for asset_id in sorted(registry.keys()):
        desc_path = gen_dir / asset_id / "descriptor.json"
        descriptor, _ = _load_json(desc_path) if desc_path.is_file() else (None, None)
        if not isinstance(descriptor, dict):
            continue
        if descriptor.get("pcg_allowed") is not True:
            continue
        cat_id = descriptor.get("asset_catalog")
        category = descriptor.get("placement_category")
        unreal_path = descriptor.get("unreal_path", "")
        if not (cat_id and category):
            continue
        catalog = loaded.get(cat_id)
        listed = False
        if isinstance(catalog, dict):
            assets = (((catalog.get("categories", {}) or {}).get(category, {}) or {})
                      .get("assets", []) or [])
            listed = unreal_path in assets
        a.chk(surface, asset_id, "catalog_membership", listed,
              "PCG-eligible asset {} not listed in {}.{}".format(
                  unreal_path, cat_id, category),
              code=FailureCode.CATALOG_MEMBERSHIP_MISSING)


# ---------------------------------------------------------------------------
# Console rendering
# ---------------------------------------------------------------------------

_TAG = {
    PASS: "[OK   ]",
    WARN: "[WARN ]",
    WARN_ONLY: "[WARN ]",
    FAIL: "[FAIL ]",
    GATED_HUMAN_EDITOR: "[GATED]",
    SKIP_NOT_APPLICABLE: "[SKIP ]",
}


def _surface_counts(a):
    counts = {s: {PASS: 0, WARN: 0, WARN_ONLY: 0, FAIL: 0,
                  GATED_HUMAN_EDITOR: 0, SKIP_NOT_APPLICABLE: 0} for s in SURFACES}
    for name, c in a.rep.checks.items():
        surface = a.surface_of.get(name)
        if surface is None:
            continue
        counts[surface][c.get("verdict", PASS)] += 1
    return counts


def _surface_verdict(c):
    if c[FAIL]:
        return "FAIL"
    if c[WARN]:
        return "WARN"
    if c[WARN_ONLY] or c[GATED_HUMAN_EDITOR]:
        return "WARN"
    return "PASS"


def print_report(a, strict, quiet):
    print("WORLDFORGE AUDIT — generated content ownership/provenance/path "
          "(strict={})".format("on" if strict else "off"))
    sc = _surface_counts(a)
    for surface in SURFACES:
        c = sc[surface]
        n_items = len(a.items.get(surface, ()))
        if not quiet:
            print("")
            print("  == {} ({} item(s)) ==".format(surface, n_items))
            for name, chk in a.rep.checks.items():
                if a.surface_of.get(name) != surface:
                    continue
                verdict = chk.get("verdict", PASS)
                if verdict == PASS and quiet:
                    continue
                tag = _TAG.get(verdict, "[????]")
                block = " (blocks)" if chk.get("blocking") else ""
                print("    {} {}{} — {}".format(tag, name, block, chk.get("detail", "")))
        # per-surface roll-up line
        print("  [{}] {:<16} PASS={} WARN={} FAIL={} GATED={} SKIP={}".format(
            _surface_verdict(c), surface,
            c[PASS], c[WARN] + c[WARN_ONLY], c[FAIL],
            c[GATED_HUMAN_EDITOR], c[SKIP_NOT_APPLICABLE]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge repo-wide generated-content ownership/provenance/path audit (read-only).")
    ap.add_argument("--strict", action="store_true",
                    help="strict mode: soft WARNs (e.g. missing provenance) become blocking")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-check listing (per-surface + roll-up only)")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    report_dir = REPO_ROOT / REPORT_DIR_REL
    yaml_mod = _load_yaml()

    rep = ValidationReport("audit", "generated_content", strict=strict)
    a = Auditor(rep)

    audit_registries(a)
    audit_generated_assets(a)
    audit_terrain(a)
    audit_poi(a)
    audit_slices(a)
    audit_placement(a)
    audit_scenarios(a)
    audit_catalogs(a, yaml_mod)

    rep.finalize()

    print_report(a, strict, args.quiet)

    total_items = sum(len(v) for v in a.items.values())
    counts = rep.to_dict()["counts"]
    print("")
    print("AUDITED {} item(s) across {} surface(s)".format(total_items, len(SURFACES)))
    print("COUNTS: " + ", ".join("{}={}".format(k, v) for k, v in counts.items() if v))

    rep.write(report_dir, REPORT_FILENAME)
    rep.print_summary("audit-generated-content")

    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
