#!/usr/bin/env python3
r"""package_check.py — WorldForge v0.9 world-pack package/ship readiness gate.

ONE read-only command that takes a world pack and asserts it is package/ship-ready:

  * every slice is registered + provenance-stamped     (REGISTRY_MISSING_ENTRY / PROVENANCE_MISSING)
  * the pack's FINAL dependency set never reaches into a forbidden Houdini
    Temp/Bake path                                       (PACKAGE_FORBIDDEN_DEPENDENCY)
  * every registry-owned REPO-SIDE artifact exists       (PACKAGE_MISSING_OWNED_ASSET)
  * generated-owned references resolve to a registry     (PACKAGE_UNRESOLVED_REFERENCE)
  * no human-owned template is flagged generated-owned   (HUMAN_TEMPLATE_MARKED_GENERATED)
  * a budget profile resolves for the pack and EVERY package budget category is
    within cap                                           (BUDGET_EXCEEDED / BUDGET_PROFILE_MISSING)

It is the packaging companion to ``audit-generated-content`` (repo-wide ownership)
and ``worldforge-doctor`` (environment health): the audit asserts NOTHING in the
whole tree has slipped its ownership guarantees; package-check asks the narrower,
ship-time question — "is THIS world pack safe to cook/package?" — and resolves a
per-pack budget profile to enforce performance caps the audit does not.

UE materialization: the tooling drives the editor to materialize ``Content/**``
(owned ``.umap`` on disk, importable ``/Game`` dependencies). A check that depends
on a UE-side artifact PASSes when the artifact is present and FAILs when it is
absent (run the editor to produce it). Repo-checkable guarantees FAIL directly.

NON-MUTATING: never writes into ``Content/**`` or any registry. The only thing it
writes is its own report under ``procedural/reports/package_check/<pack>/``.

Usage:
    python tools/pipeline/package_check.py --pack desert_poi_lite_seed
    python tools/pipeline/package_check.py --pack desert_production_seed --strict
    python tools/pipeline/package_check.py --pack <name|path/to/world_pack.yaml>

Strict is also honored via STRICT=1 (v0.9 contract). Strict only ever ADDS blocking:
soft gaps (e.g. a placement DataAsset with no provenance) become blocking; hard
ownership/path/budget violations FAIL in both modes.

Exit 0 when the pack is package-ready (status ok|warn), 1 when a blocking check FAILs.
"""

import argparse
import json
import struct
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

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


def _ue_asset_on_disk(repo_root, ref):
    """True if a /Game or Content UE asset reference is materialized on disk."""
    if ref.startswith("Content/"):
        return (repo_root / ref).is_file()
    if ref.startswith("/Game/"):
        rest = ref[len("/Game/"):]
    elif ref.endswith((".umap", ".uasset")):
        return (repo_root / ref).is_file()
    else:
        rest = ref
    return ((repo_root / ("Content/" + rest + ".uasset")).is_file()
            or (repo_root / ("Content/" + rest + ".umap")).is_file())


REPORT_DIR_REL = "procedural/reports/package_check"
REPORT_FILENAME = "package_check_report.json"

# Owned trees (mirror audit_generated_content.py ownership policy).
OWNED_UE_PREFIX = "/Game/WorldForge/"
OWNED_CONTENT_PREFIX = "Content/WorldForge/"

# Check categories, in report/summary order.
CATEGORIES = (
    "resolution",
    "registry",
    "provenance",
    "paths",
    "owned_assets",
    "references",
    "ownership_integrity",
    "budget",
)

# Package budget categories, in report order: (key, cap_field, unit).
BUDGET_CATEGORIES = (
    ("map_count", "max_map_count", "maps"),
    ("terrain_dimension", "max_terrain_dimension", "px"),
    ("height_range_cm", "max_height_range_cm", "cm"),
    ("mask_dimension", "max_mask_dimension", "px"),
    ("placement_instance_count", "max_placement_instances", "instances"),
    ("static_mesh_actor_count", "max_static_mesh_actors", "actors"),
    ("poi_marker_count", "max_poi_markers", "markers"),
    ("poi_bounds_area_cm2", "max_poi_bounds_area_cm2", "cm^2"),
    ("scenario_count", "max_scenario_count", "scenarios"),
    ("generated_file_count", "max_generated_file_count", "files"),
    ("package_size_mb", "max_package_size_mb", "MB"),
    ("forbidden_path_references", "max_forbidden_path_references", "refs"),
)


# ---------------------------------------------------------------------------
# small IO helpers
# ---------------------------------------------------------------------------

def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _load_yaml_mod():
    try:
        import yaml  # noqa: F401
        return yaml
    except Exception:
        return None


def _slug(path):
    """Short, unique-ish, filename-safe tail of an asset path for check naming."""
    tail = str(path).rstrip("/").replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in tail) or "ref"


def _png_dimensions(path):
    """Return (w, h) from a PNG IHDR header, or None if unreadable.

    Dependency-free: the IHDR width/height are big-endian uint32 at bytes 16-24.
    """
    try:
        head = Path(path).read_bytes()[:24]
        if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h = struct.unpack(">II", head[16:24])
        return int(w), int(h)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# PackChecker — thin wrapper over ValidationReport that namespaces checks per
# category (so one pack report stays readable) and tracks category membership
# for the per-category roll-up. Mirrors audit_generated_content.Auditor.
# ---------------------------------------------------------------------------

class PackChecker:
    def __init__(self, rep, repo_root):
        self.rep = rep
        self.repo_root = repo_root
        self.category_of = {}
        self.items = {c: set() for c in CATEGORIES}

    def _full(self, category, item, name):
        return "{}:{}:{}".format(category, item, name) if item else "{}:{}".format(category, name)

    def seen(self, category, item):
        if item:
            self.items.setdefault(category, set()).add(item)

    def chk(self, category, item, name, ok, detail="", code=None,
            warn_only=False, allow_in_strict=False):
        full = self._full(category, item, name)
        self.category_of[full] = category
        self.seen(category, item)
        return self.rep.check(full, ok, detail, warn_only=warn_only, code=code,
                              allow_in_strict=allow_in_strict)

    def warn(self, category, item, name, ok, detail="", code=None):
        return self.chk(category, item, name, ok, detail, code=code, warn_only=True)

    def ue_check(self, category, item, name, ok, detail="", code=None):
        """A UE-artifact presence check: present -> PASS, absent -> FAIL."""
        full = self._full(category, item, name)
        self.category_of[full] = category
        self.seen(category, item)
        return self.rep.ue_check(full, ok, detail, code=code)

    def skip(self, category, item, name, detail=""):
        full = self._full(category, item, name)
        self.category_of[full] = category
        self.seen(category, item)
        return self.rep.skip(full, detail)

    def _rel(self, path):
        try:
            return Path(path).resolve().relative_to(self.repo_root).as_posix()
        except Exception:  # noqa: BLE001
            return str(path).replace("\\", "/")


# ---------------------------------------------------------------------------
# Pack resolution — world pack -> slice packs -> slices, plus the terrain / POI /
# scenario surfaces those slices pull in.
# ---------------------------------------------------------------------------

class ResolvedPack:
    def __init__(self):
        self.world_pack_id = None
        self.biome = "desert"
        self.slice_pack_paths = []      # (pack_id, Path|None, rel)
        self.slice_entries = []         # raw slice dicts from the slice packs
        self.slice_ids = []             # ordered slice names
        self.terrain_recipes = set()    # recipe_ids referenced by slices
        self.poi_recipes = set()        # poi recipe_ids referenced by slices
        self.parse_errors = []          # (label, detail)


def resolve_world_pack(repo_root, pack_arg, yaml_mod):
    """Resolve a --pack arg (world pack id OR path) into a ResolvedPack."""
    rp = ResolvedPack()
    # locate the world pack yaml
    cand = Path(pack_arg)
    if not cand.is_absolute():
        if cand.suffix in (".yaml", ".yml") and (repo_root / cand).is_file():
            cand = repo_root / cand
        else:
            cand = repo_root / "procedural" / "world_packs" / "{}.yaml".format(cand.name)
    if not cand.is_file():
        rp.parse_errors.append(("world_pack", "world pack not found: {}".format(pack_arg)))
        return rp
    if yaml_mod is None:
        rp.parse_errors.append(("world_pack", "pyyaml missing — cannot parse world pack"))
        return rp

    try:
        wp = yaml_mod.safe_load(cand.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        rp.parse_errors.append(("world_pack", "unparseable world pack: {}".format(exc)))
        return rp

    rp.world_pack_id = wp.get("world_pack_id", cand.stem)
    rp.biome = (wp.get("global_defaults", {}) or {}).get("biome", "desert")

    for entry in wp.get("packs", []) or []:
        pack_id = entry.get("pack_id", "<unknown>")
        pack_rel = entry.get("pack_path", "")
        sp_path = (repo_root / pack_rel) if pack_rel else None
        rp.slice_pack_paths.append((pack_id, sp_path if (sp_path and sp_path.is_file()) else None, pack_rel))
        if not sp_path or not sp_path.is_file():
            rp.parse_errors.append((pack_id, "slice pack file not found: {}".format(pack_rel)))
            continue
        try:
            sp = yaml_mod.safe_load(sp_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            rp.parse_errors.append((pack_id, "unparseable slice pack: {}".format(exc)))
            continue
        for s in sp.get("slices", []) or []:
            rp.slice_entries.append(s)
            name = s.get("name")
            if name:
                rp.slice_ids.append(name)
            if s.get("terrain"):
                rp.terrain_recipes.add(s["terrain"])
            if s.get("poi"):
                rp.poi_recipes.add(s["poi"])
    return rp


# ---------------------------------------------------------------------------
# Budget profile resolution
# ---------------------------------------------------------------------------

def resolve_budget_profiles(repo_root, biome, yaml_mod):
    """Return (package_profile, placement_profile, detail).

    package_profile : biome-matching budget that carries a ``package_budgets`` block
    placement_profile : biome-matching plain budget (placement instance ceiling)
    """
    bdir = repo_root / "procedural" / "definitions" / "budgets"
    if not bdir.is_dir() or yaml_mod is None:
        return None, None, "no budget definitions dir / pyyaml missing"
    package = None
    placement = None
    pkg_name = None
    plc_name = None
    for bp in sorted(bdir.glob("*.yaml")):
        try:
            data = yaml_mod.safe_load(bp.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        if data.get("biome") != biome:
            continue
        if isinstance(data.get("package_budgets"), dict):
            # prefer the conventional <biome>_package.yaml if several qualify
            if package is None or bp.stem == "{}_package".format(biome):
                package, pkg_name = data, bp.stem
        else:
            # a plain placement/instance budget; prefer <biome>_default
            if placement is None or bp.stem == "{}_default".format(biome):
                placement, plc_name = data, bp.stem
    detail = "package={} placement={}".format(pkg_name or "<none>", plc_name or "<none>")
    return package, placement, detail


# ---------------------------------------------------------------------------
# Per-category checks
# ---------------------------------------------------------------------------

def check_resolution(c, rp):
    """Pack structure resolves: world pack parsed, slice packs present, slices found."""
    for label, detail in rp.parse_errors:
        c.chk("resolution", label, "parse", False, detail,
              code=FailureCode.SPEC_INVALID)
    for pack_id, path, rel in rp.slice_pack_paths:
        c.chk("resolution", pack_id, "slice_pack_present", path is not None,
              "slice pack not found: {}".format(rel),
              code=FailureCode.RECIPE_MISSING)
    c.chk("resolution", "", "has_slices", bool(rp.slice_ids),
          "world pack resolved no slices",
          code=FailureCode.SPEC_INVALID)


def check_slices(c, rp, slice_registry, spec_dir):
    """Every slice in the pack must be registered + provenance-stamped, and its
    final/owned/referenced paths must obey ownership + path policy."""
    for sid in rp.slice_ids:
        entry = slice_registry.get(sid)
        # -- registry --
        c.chk("registry", sid, "registered", entry is not None,
              "slice not in worldforge_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

        # -- provenance (on the slice spec) --
        spec = None
        spec_path = spec_dir / "{}.json".format(sid)
        if not spec_path.is_file() and entry is not None and entry.get("spec_path"):
            alt = c.repo_root / entry["spec_path"]
            spec_path = alt if alt.is_file() else spec_path
        if spec_path.is_file():
            spec, _ = _load_json(spec_path)
        c.chk("provenance", sid, "spec_present", spec is not None,
              "slice spec missing/unparseable: {}".format(c._rel(spec_path)),
              code=FailureCode.SPEC_INVALID)
        if spec is not None:
            c.chk("provenance", sid, "provenance_stamped",
                  bool(spec.get("provenance")),
                  "slice spec has no provenance block",
                  code=FailureCode.PROVENANCE_MISSING)

        if entry is None:
            continue

        # -- forbidden-path scan over the slice's FINAL dependency set --
        final_deps = []
        final_deps.append(("map", entry.get("map_path", "")))
        for oa in entry.get("owned_assets", []) or []:
            final_deps.append(("owned_asset", oa))
        for ra in entry.get("referenced_assets", []) or []:
            final_deps.append(("referenced_asset", ra))
        for label, dep in final_deps:
            if not dep:
                continue
            c.chk("paths", sid, "{}_not_temp_bake[{}]".format(label, _slug(dep)),
                  not is_forbidden_path(dep),
                  "{} is a forbidden Houdini Temp/Bake path: {}".format(label, dep),
                  code=FailureCode.PACKAGE_FORBIDDEN_DEPENDENCY)

        # -- owned-asset presence: repo-side hard, UE Content materialized by the editor --
        for oa in entry.get("owned_assets", []) or []:
            if oa.startswith("/Game/") or oa.startswith("Content/") or oa.endswith((".umap", ".uasset")):
                # UE Content is materialized on disk by driving the editor; check it.
                c.ue_check("owned_assets", sid, "owned_ue_materialized[{}]".format(_slug(oa)),
                        _ue_asset_on_disk(c.repo_root, oa),
                        "owned UE asset not materialized on disk (run the editor build): {}".format(oa),
                        code=FailureCode.UE_ARTIFACT_MISSING)
            else:
                c.chk("owned_assets", sid, "owned_repo_present[{}]".format(_slug(oa)),
                      (c.repo_root / oa).is_file(),
                      "registry-owned repo artifact missing on disk: {}".format(oa),
                      code=FailureCode.PACKAGE_MISSING_OWNED_ASSET)

        # -- reference resolution --
        for ra in entry.get("referenced_assets", []) or []:
            if not ra or is_forbidden_path(ra):
                continue  # forbidden handled above
            if ra.startswith(OWNED_UE_PREFIX):
                # a generated-owned reference MUST resolve to a registry-owned path
                resolved = _generated_ref_resolves(ra, slice_registry,
                                                    load_generated_asset_registry(c.repo_root))
                c.chk("references", sid, "generated_ref_resolves[{}]".format(_slug(ra)), resolved,
                      "generated-owned reference resolves to no registry entry: {}".format(ra),
                      code=FailureCode.PACKAGE_UNRESOLVED_REFERENCE)
            else:
                # human-owned /Game dependency: check it is materialized on disk.
                on_disk = _ue_asset_on_disk(c.repo_root, ra)
                c.ue_check("references", sid, "human_ref_importable[{}]".format(_slug(ra)), on_disk,
                        "human-owned dependency not present on disk in this checkout: {}".format(ra),
                        code=FailureCode.UE_ARTIFACT_MISSING)

        # -- ownership integrity: owned/destroyable set must not include a
        #    human-owned referenced dependency --
        referenced = set(entry.get("referenced_assets", []) or [])
        for oa in entry.get("owned_assets", []) or []:
            c.chk("ownership_integrity", sid, "owned_not_referenced_dep[{}]".format(_slug(oa)),
                  oa not in referenced,
                  "owned/destroyable list includes a human-owned referenced dependency: {}".format(oa),
                  code=FailureCode.HUMAN_TEMPLATE_MARKED_GENERATED)


def _generated_ref_resolves(ref, slice_registry, gen_registry):
    ref = ref.rstrip("/")
    for e in slice_registry.values():
        if (e.get("map_path", "") or "").rstrip("/") == ref:
            return True
        for oa in e.get("owned_assets", []) or []:
            if oa.rstrip("/") == ref:
                return True
    for e in gen_registry.values():
        if (e.get("unreal_path", "") or "").rstrip("/") == ref:
            return True
    return False


def check_descriptor_surface(c, rp, registry, recipes, base_dir, registry_owner,
                             match_field, category_label):
    """Generic: each recipe referenced by the pack must resolve to a registered,
    provenance-stamped descriptor whose repo-side outputs exist.

    Returns the list of resolved descriptors (for budget computation)."""
    resolved = []
    # build recipe_id -> registry entry index
    by_recipe = {}
    for name, entry in registry.items():
        by_recipe.setdefault(entry.get(match_field), []).append((name, entry))

    for recipe in sorted(recipes):
        matches = by_recipe.get(recipe, [])
        c.chk("registry", recipe, "{}_registered".format(category_label), bool(matches),
              "no {} registry entry for recipe '{}'".format(category_label, recipe),
              code=FailureCode.REGISTRY_MISSING_ENTRY)
        for name, entry in matches:
            desc_path = base_dir / name / "descriptor.json"
            descriptor = None
            if desc_path.is_file():
                descriptor, _ = _load_json(desc_path)
            c.chk("provenance", name, "descriptor_present", descriptor is not None,
                  "descriptor.json missing/unparseable: {}".format(c._rel(desc_path)),
                  code=FailureCode.DESCRIPTOR_MISSING)
            if descriptor is None:
                continue
            c.chk("provenance", name, "provenance_stamped",
                  bool(descriptor.get("provenance")),
                  "descriptor has no provenance block",
                  code=FailureCode.PROVENANCE_MISSING)
            # human-template integrity
            is_template = bool(descriptor.get("is_template")) or descriptor.get("human_owned") is True
            if is_template:
                c.chk("ownership_integrity", name, "template_not_generated_owned",
                      descriptor.get("generated_owned") is not True,
                      "human-owned template flagged generated_owned",
                      code=FailureCode.HUMAN_TEMPLATE_MARKED_GENERATED)
            # repo-side owned outputs must exist
            outputs = descriptor.get("outputs", {}) or {}
            for okey, opath in sorted(outputs.items()):
                if isinstance(opath, str):
                    c.chk("owned_assets", name, "output_{}_present".format(okey),
                          (c.repo_root / opath).is_file(),
                          "declared output missing on disk: {}".format(opath),
                          code=FailureCode.PACKAGE_MISSING_OWNED_ASSET)
            # also explicit owned_outputs list on the registry entry
            for opath in entry.get("owned_outputs", []) or []:
                c.chk("owned_assets", name, "owned_output_present[{}]".format(_slug(opath)),
                      (c.repo_root / opath).is_file(),
                      "registry owned_output missing on disk: {}".format(opath),
                      code=FailureCode.PACKAGE_MISSING_OWNED_ASSET)
            resolved.append((name, descriptor, entry))
    return resolved


def check_scenarios(c, rp, scenario_registry, base_dir):
    """Runtime scenarios bound to the pack's slices must be registered + present."""
    slice_set = set(rp.slice_ids)
    runs = [(rid, e) for rid, e in scenario_registry.items()
            if e.get("target") in slice_set or e.get("context_id") in slice_set]
    for run_id, entry in runs:
        res_path = base_dir / run_id / "result.json"
        result = None
        if res_path.is_file():
            result, _ = _load_json(res_path)
        c.chk("owned_assets", run_id, "scenario_result_present", result is not None,
              "scenario result.json missing/unparseable: {}".format(c._rel(res_path)),
              code=FailureCode.PACKAGE_MISSING_OWNED_ASSET)
        if result is None:
            continue
        c.chk("provenance", run_id, "scenario_provenance_stamped",
              bool(result.get("provenance")),
              "scenario result has no provenance block",
              code=FailureCode.PROVENANCE_MISSING)
        for okey, opath in sorted((result.get("outputs", {}) or {}).items()):
            if isinstance(opath, str):
                c.chk("owned_assets", run_id, "scenario_output_{}_present".format(okey),
                      (c.repo_root / opath).is_file(),
                      "scenario output missing on disk: {}".format(opath),
                      code=FailureCode.PACKAGE_MISSING_OWNED_ASSET)
    return runs


def check_placement(c, rp, base_dir):
    """Placement DataAssets owned by the pack's slices. Provenance is currently a
    KNOWN soft gap (lightweight descriptor) — surfaced as a WARN that blocks under
    --strict, never a silent pass. Mirrors audit_generated_content treatment."""
    slice_set = set(rp.slice_ids)
    das = []
    if base_dir.is_dir():
        for dp in sorted(base_dir.glob("*_da.json")):
            da, err = _load_json(dp)
            if da is None:
                continue
            if da.get("slice_id") in slice_set:
                das.append((dp, da))
    for dp, da in das:
        da_id = da.get("da_id", dp.stem)
        # the placement DA's UE map binding must never be a forbidden path
        mp = da.get("map_path", "")
        if mp:
            c.chk("paths", da_id, "map_not_temp_bake", not is_forbidden_path(mp),
                  "placement DA map_path is a forbidden Houdini Temp/Bake path: {}".format(mp),
                  code=FailureCode.PACKAGE_FORBIDDEN_DEPENDENCY)
        c.warn("provenance", da_id, "placement_provenance_stamped",
               bool(da.get("provenance")),
               "placement DataAsset has no provenance block (lightweight descriptor)",
               code=FailureCode.PROVENANCE_MISSING)
    return das


# ---------------------------------------------------------------------------
# Budget computation + enforcement
# ---------------------------------------------------------------------------

def compute_observations(c, rp, terrains, pois, scenarios, das, placement_profile):
    """Return {category: (observed, applicable, detail)} for every budget category."""
    obs = {}

    # map count
    obs["map_count"] = (len(rp.slice_ids), True, "{} slice map(s)".format(len(rp.slice_ids)))

    # terrain dimension + height range + mask dimension
    if terrains:
        max_dim = 0
        max_span = 0.0
        max_mask = 0
        dim_src = span_src = mask_src = ""
        for name, desc, entry in terrains:
            dims = desc.get("dimensions") or []
            if dims:
                d = max(int(x) for x in dims)
                if d > max_dim:
                    max_dim, dim_src = d, name
            hr = desc.get("height_range_cm") or []
            if len(hr) == 2:
                span = float(hr[1]) - float(hr[0])
                if span > max_span:
                    max_span, span_src = span, name
            outputs = desc.get("outputs", {}) or {}
            for okey, opath in outputs.items():
                if "mask" in okey and isinstance(opath, str):
                    wh = _png_dimensions(c.repo_root / opath)
                    if wh:
                        m = max(wh)
                        if m > max_mask:
                            max_mask, mask_src = m, "{}:{}".format(name, okey)
        obs["terrain_dimension"] = (max_dim, True, "max {}px ({})".format(max_dim, dim_src))
        obs["height_range_cm"] = (int(max_span), True, "max span {}cm ({})".format(int(max_span), span_src))
        if max_mask:
            obs["mask_dimension"] = (max_mask, True, "max {}px ({})".format(max_mask, mask_src))
        else:
            obs["mask_dimension"] = (max_dim, True, "mask dims = terrain dims {}px".format(max_dim))
    else:
        for k in ("terrain_dimension", "height_range_cm", "mask_dimension"):
            obs[k] = (0, False, "pack references no forge terrain")

    # placement instance ceiling (declared placement budget)
    if das:
        ceiling = None
        src = "<none>"
        if isinstance(placement_profile, dict):
            ceiling = (placement_profile.get("limits", {}) or {}).get("max_total_instances")
            src = placement_profile.get("budget_id", "placement budget")
        if ceiling is None:
            obs["placement_instance_count"] = (0, False,
                                               "no placement budget resolved for declared ceiling")
        else:
            obs["placement_instance_count"] = (int(ceiling), True,
                                               "declared per-slice ceiling {} ({})".format(int(ceiling), src))
    else:
        obs["placement_instance_count"] = (0, False, "pack has no placement DataAssets")

    # POI-derived: static mesh actors / markers / bounds area
    if pois:
        max_actors = 0
        max_markers = 0
        max_area = 0
        a_src = m_src = ar_src = ""
        for name, desc, entry in pois:
            budgets = desc.get("budgets", {}) or {}
            sm = budgets.get("max_static_mesh_actors")
            if isinstance(sm, (int, float)) and sm > max_actors:
                max_actors, a_src = int(sm), name
            nm = len(desc.get("markers", []) or [])
            if nm > max_markers:
                max_markers, m_src = nm, name
            area = (desc.get("bounds", {}) or {}).get("area_cm2")
            if isinstance(area, (int, float)) and area > max_area:
                max_area, ar_src = int(area), name
        obs["static_mesh_actor_count"] = (max_actors, True, "max declared {} actors ({})".format(max_actors, a_src))
        obs["poi_marker_count"] = (max_markers, True, "max {} markers ({})".format(max_markers, m_src))
        obs["poi_bounds_area_cm2"] = (max_area, True, "max {} cm^2 ({})".format(max_area, ar_src))
    else:
        for k in ("static_mesh_actor_count", "poi_marker_count", "poi_bounds_area_cm2"):
            obs[k] = (0, False, "pack references no POIs")

    # scenario count
    obs["scenario_count"] = (len(scenarios), True, "{} runtime scenario(s)".format(len(scenarios)))

    # generated file count + package size estimate (repo-side owned files)
    files = _collect_generated_files(c, rp, terrains, pois, scenarios, das)
    total_bytes = 0
    for f in files:
        try:
            total_bytes += (c.repo_root / f).stat().st_size
        except OSError:
            pass
    size_mb = round(total_bytes / (1024.0 * 1024.0), 3)
    obs["generated_file_count"] = (len(files), True, "{} repo-side generated owned file(s)".format(len(files)))
    obs["package_size_mb"] = (size_mb, True, "~{} MB of generated owned files".format(size_mb))

    # forbidden path references (count over the pack's final dependency set)
    forbidden = _count_forbidden_refs(c, rp)
    obs["forbidden_path_references"] = (forbidden, True,
                                        "{} forbidden Temp/Bake reference(s) in final deps".format(forbidden))
    return obs


def _collect_generated_files(c, rp, terrains, pois, scenarios, das):
    files = set()
    spec_dir = c.repo_root / "procedural" / "slices" / "desert" / "generated"
    for sid in rp.slice_ids:
        sp = spec_dir / "{}.json".format(sid)
        if sp.is_file():
            files.add(c._rel(sp))
    for name, desc, entry in terrains:
        for opath in (entry.get("owned_outputs", []) or []):
            if (c.repo_root / opath).is_file():
                files.add(opath)
        dp = c.repo_root / "procedural" / "generated" / "terrain" / name / "descriptor.json"
        if dp.is_file():
            files.add(c._rel(dp))
    for name, desc, entry in pois:
        dp = c.repo_root / "procedural" / "generated" / "poi" / name / "descriptor.json"
        if dp.is_file():
            files.add(c._rel(dp))
    for run_id, entry in scenarios:
        base = c.repo_root / "procedural" / "generated" / "scenarios" / run_id
        for f in ("result.json", "state_save.json"):
            if (base / f).is_file():
                files.add(c._rel(base / f))
    for dp, da in das:
        files.add(c._rel(dp))
    return sorted(files)


def _count_forbidden_refs(c, rp):
    slice_registry = load_registry(c.repo_root)
    n = 0
    for sid in rp.slice_ids:
        entry = slice_registry.get(sid)
        if not entry:
            continue
        deps = [entry.get("map_path", "")]
        deps += list(entry.get("owned_assets", []) or [])
        deps += list(entry.get("referenced_assets", []) or [])
        for d in deps:
            if d and is_forbidden_path(d):
                n += 1
    return n


def check_budget(c, rp, obs, package_profile, profile_detail):
    """Resolve a budget profile and enforce every package budget category."""
    if not isinstance(package_profile, dict) or not isinstance(package_profile.get("package_budgets"), dict):
        c.warn("budget", "", "profile_resolved", False,
               "no package budget profile resolved for biome '{}' ({})".format(rp.biome, profile_detail),
               code=FailureCode.BUDGET_PROFILE_MISSING)
        return []
    c.chk("budget", "", "profile_resolved", True,
          "resolved package profile: {} ({})".format(package_profile.get("budget_id"), profile_detail))
    caps = package_profile["package_budgets"]

    rows = []
    for key, cap_field, unit in BUDGET_CATEGORIES:
        observed, applicable, detail = obs.get(key, (0, False, "not computed"))
        cap = caps.get(cap_field)
        if not applicable:
            c.skip("budget", "", key, detail)
            rows.append((key, observed, cap, unit, SKIP_NOT_APPLICABLE, detail))
            continue
        if cap is None:
            c.warn("budget", "", "{}_cap".format(key), False,
                   "no cap '{}' defined in package profile".format(cap_field),
                   code=FailureCode.BUDGET_PROFILE_MISSING)
            rows.append((key, observed, None, unit, WARN, "no cap defined"))
            continue
        within = observed <= cap
        c.chk("budget", "", key, within,
              "{} = {} {} (cap {}); {}".format(key, observed, unit, cap, detail),
              code=FailureCode.BUDGET_EXCEEDED)
        rows.append((key, observed, cap, unit, PASS if within else FAIL, detail))
    return rows


# ---------------------------------------------------------------------------
# Console rendering
# ---------------------------------------------------------------------------

_TAG = {
    PASS: "[OK   ]",
    WARN: "[WARN ]",
    WARN_ONLY: "[WARN ]",
    FAIL: "[FAIL ]",
    SKIP_NOT_APPLICABLE: "[SKIP ]",
}


def _category_counts(c):
    counts = {cat: {PASS: 0, WARN: 0, WARN_ONLY: 0, FAIL: 0,
                    SKIP_NOT_APPLICABLE: 0} for cat in CATEGORIES}
    for name, chk in c.rep.checks.items():
        cat = c.category_of.get(name)
        if cat is None:
            continue
        counts[cat][chk.get("verdict", PASS)] += 1
    return counts


def _category_verdict(cc):
    if cc[FAIL]:
        return "FAIL"
    if cc[WARN]:
        return "WARN"
    if cc[WARN_ONLY]:
        return "WARN"
    return "PASS"


def print_report(c, rp, budget_rows, strict, quiet):
    print("WORLDFORGE PACKAGE-CHECK — world pack '{}' (biome={}, strict={})".format(
        rp.world_pack_id, rp.biome, "on" if strict else "off"))
    print("  slices={}  slice_packs={}  terrains={}  pois={}".format(
        len(rp.slice_ids), len(rp.slice_pack_paths),
        len(rp.terrain_recipes), len(rp.poi_recipes)))

    cc = _category_counts(c)
    for cat in CATEGORIES:
        cnt = cc[cat]
        if not quiet:
            shown = [(n, ch) for n, ch in c.rep.checks.items()
                     if c.category_of.get(n) == cat and ch.get("verdict") != PASS]
            if shown:
                print("")
                print("  == {} ==".format(cat))
                for name, ch in shown:
                    tag = _TAG.get(ch.get("verdict"), "[????]")
                    block = " (blocks)" if ch.get("blocking") else ""
                    print("    {} {}{} — {}".format(tag, name, block, ch.get("detail", "")))
        print("  [{}] {:<20} PASS={} WARN={} FAIL={} SKIP={}".format(
            _category_verdict(cnt), cat,
            cnt[PASS], cnt[WARN] + cnt[WARN_ONLY], cnt[FAIL],
            cnt[SKIP_NOT_APPLICABLE]))

    if budget_rows:
        print("")
        print("  == budget categories ==")
        print("    {:<26} {:>14} {:>14}  {}".format("category", "observed", "cap", "verdict"))
        for key, observed, cap, unit, verdict, detail in budget_rows:
            cap_s = "n/a" if cap is None else "{} {}".format(cap, unit)
            obs_s = "{} {}".format(observed, unit)
            print("    {:<26} {:>14} {:>14}  {}".format(key, obs_s, cap_s, verdict))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge world-pack package/ship readiness gate (read-only).")
    ap.add_argument("--pack", required=True,
                    help="world pack id (e.g. desert_poi_lite_seed) or path to a world pack YAML")
    ap.add_argument("--strict", action="store_true",
                    help="strict mode: soft WARNs (e.g. missing placement provenance) become blocking")
    ap.add_argument("--repo-root", default=None,
                    help="override repo root (testing): resolves packs, registries and budgets from here")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-check listing (per-category + budget roll-up only)")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else DEFAULT_REPO_ROOT
    yaml_mod = _load_yaml_mod()

    rp = resolve_world_pack(repo_root, args.pack, yaml_mod)
    rep = ValidationReport("world_pack", rp.world_pack_id or args.pack, strict=strict)
    c = PackChecker(rep, repo_root)

    # Hard input failure: world pack itself could not be located/parsed.
    if rp.world_pack_id is None:
        for label, detail in rp.parse_errors:
            c.chk("resolution", label, "parse", False, detail, code=FailureCode.SPEC_INVALID)
        rep.error("world pack could not be resolved: {}".format(args.pack))
        rep.finalize()
        print_report(c, rp, [], strict, args.quiet)
        report_dir = repo_root / REPORT_DIR_REL / (rp.world_pack_id or Path(args.pack).stem)
        rep.write(report_dir, REPORT_FILENAME)
        rep.print_summary("package-check")
        sys.exit(rep.exit_code)

    # registries
    slice_registry = load_registry(repo_root)
    terrain_registry = load_terrain_registry(repo_root)
    poi_registry = load_poi_registry(repo_root)
    scenario_registry = load_scenario_registry(repo_root)

    spec_dir = repo_root / "procedural" / "slices" / "desert" / "generated"
    terrain_base = repo_root / "procedural" / "generated" / "terrain"
    poi_base = repo_root / "procedural" / "generated" / "poi"
    scenario_base = repo_root / "procedural" / "generated" / "scenarios"
    placement_base = repo_root / "procedural" / "generated" / "placement"

    # resolve budget profiles up-front (placement ceiling feeds a budget category)
    package_profile, placement_profile, profile_detail = resolve_budget_profiles(
        repo_root, rp.biome, yaml_mod)

    # ---- structural + ownership checks ----
    check_resolution(c, rp)
    check_slices(c, rp, slice_registry, spec_dir)
    terrains = check_descriptor_surface(
        c, rp, terrain_registry, rp.terrain_recipes, terrain_base,
        "worldforge_terrain_registry", "recipe_id", "terrain")
    pois = check_descriptor_surface(
        c, rp, poi_registry, rp.poi_recipes, poi_base,
        "worldforge_poi_registry", "recipe_id", "poi")
    scenarios = check_scenarios(c, rp, scenario_registry, scenario_base)
    das = check_placement(c, rp, placement_base)

    # ---- per-POI internal budget consistency (actual <= declared) ----
    for name, desc, entry in pois:
        budgets = desc.get("budgets", {}) or {}
        nm = len(desc.get("markers", []) or [])
        cap_m = budgets.get("max_marker_count")
        if isinstance(cap_m, (int, float)):
            c.chk("budget", name, "markers_within_declared", nm <= cap_m,
                  "POI {} has {} markers (declared cap {})".format(name, nm, cap_m),
                  code=FailureCode.BUDGET_EXCEEDED)
        area = (desc.get("bounds", {}) or {}).get("area_cm2")
        cap_a = budgets.get("max_bounds_area_cm2")
        if isinstance(area, (int, float)) and isinstance(cap_a, (int, float)):
            c.chk("budget", name, "bounds_within_declared", area <= cap_a,
                  "POI {} bounds {} cm^2 (declared cap {})".format(name, area, cap_a),
                  code=FailureCode.BUDGET_EXCEEDED)

    # ---- budget enforcement ----
    obs = compute_observations(c, rp, terrains, pois, scenarios, das, placement_profile)
    budget_rows = check_budget(c, rp, obs, package_profile, profile_detail)

    rep.finalize()
    print_report(c, rp, budget_rows, strict, args.quiet)

    counts = rep.to_dict()["counts"]
    print("")
    print("COUNTS: " + ", ".join("{}={}".format(k, v) for k, v in counts.items() if v))

    report_dir = repo_root / REPORT_DIR_REL / rp.world_pack_id
    rep.write(report_dir, REPORT_FILENAME)
    rep.print_summary("package-check")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
