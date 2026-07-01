#!/usr/bin/env python3
"""world_pack_maps.py — WorldForge v1.0x shared world-pack map enumeration.

Every v1.0x validator (environment, sky/lighting/fog, POI, entity anchors,
rendering, determinism, ...) must iterate the SAME set of maps in the SAME way,
or the gates disagree about what "every map" means and fake-green sneaks in
through enumeration drift. This module is the single source of truth for
"what maps does world pack X contain, and where is each map's generated spec".

Resolution chain:
    world pack yaml  (procedural/world_packs/<pack>.yaml)
      -> packs[].pack_path                 (procedural/slice_packs/<sp>.yaml)
        -> slices[].name                   (slice id)
          -> generated spec                (procedural/slices/<biome>/generated/<name>.json)

Returns a list of MapRecord dicts; missing specs are surfaced (not silently
dropped) so validators can fail on a coverage shortfall instead of validating a
smaller set than the pack declares.
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    raise

import json

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _abs(rel):
    p = Path(rel)
    return p if p.is_absolute() else REPO_ROOT / p


def resolve_world_pack_path(pack):
    """Accept a pack id, a bare filename, or a path; return the yaml Path."""
    p = Path(pack)
    candidates = []
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(REPO_ROOT / pack)
        candidates.append(REPO_ROOT / "procedural" / "world_packs" / pack)
        if not pack.endswith(".yaml"):
            candidates.append(REPO_ROOT / "procedural" / "world_packs" / (pack + ".yaml"))
    for c in candidates:
        if c.is_file():
            return c
    return candidates[-1]  # non-existent; caller reports the miss


def generated_spec_path(biome, slice_name):
    """Canonical generated-spec path for a slice."""
    return REPO_ROOT / "procedural" / "slices" / biome / "generated" / (slice_name + ".json")


class MapRecord(dict):
    """A single map in a world pack. Behaves as a dict; convenience accessors below."""

    @property
    def slice_id(self):
        return self.get("slice_id")

    @property
    def spec(self):
        return self.get("spec") or {}

    @property
    def spec_exists(self):
        return bool(self.get("spec_exists"))

    @property
    def spec_path(self):
        return self.get("spec_path")


def enumerate_maps(pack):
    """Return (world_pack_id, [MapRecord, ...]).

    Each MapRecord carries: slice_id, biome, variant, seed, pack_id, row (the
    slice-pack row dict), spec_path, spec_exists, spec (loaded json or {}),
    spec_error (parse error string or None).
    """
    wp_path = resolve_world_pack_path(pack)
    if not wp_path.is_file():
        raise FileNotFoundError("world pack not found: {}".format(wp_path))

    wp = _load_yaml(wp_path)
    world_pack_id = wp.get("world_pack_id", wp_path.stem)
    global_defaults = wp.get("global_defaults", {}) or {}

    records = []
    for pack_entry in wp.get("packs", []):
        pack_id = pack_entry.get("pack_id", "<unknown>")
        pack_rel = pack_entry.get("pack_path", "")
        sp_path = _abs(pack_rel) if pack_rel else None
        if not sp_path or not sp_path.is_file():
            # Surface a placeholder record so callers can fail on the gap.
            records.append(MapRecord({
                "slice_id": None, "pack_id": pack_id, "biome": None,
                "variant": None, "seed": None, "row": {},
                "spec_path": str(sp_path) if sp_path else pack_rel,
                "spec_exists": False, "spec": {},
                "spec_error": "slice pack file not found: {}".format(pack_rel),
            }))
            continue

        sp = _load_yaml(sp_path)
        biome = sp.get("biome") or global_defaults.get("biome") or "desert"
        for row in sp.get("slices", []):
            name = row.get("name")
            spec_path = generated_spec_path(biome, name) if name else None
            spec, spec_exists, spec_error = {}, False, None
            if spec_path and spec_path.is_file():
                try:
                    spec = json.loads(spec_path.read_text(encoding="utf-8"))
                    spec_exists = True
                except Exception as exc:
                    spec_error = "spec unparseable: {}".format(exc)
            elif spec_path:
                spec_error = "generated spec missing: {}".format(
                    spec_path.relative_to(REPO_ROOT) if spec_path else name)
            records.append(MapRecord({
                "slice_id": name,
                "pack_id": pack_id,
                "biome": biome,
                "variant": row.get("variant"),
                "seed": row.get("seed"),
                "row": row,
                "spec_path": str(spec_path) if spec_path else None,
                "spec_exists": spec_exists,
                "spec": spec,
                "spec_error": spec_error,
            }))
    return world_pack_id, records


def report_dir_for(world_pack_id):
    """Canonical v1.0x report directory for a world pack."""
    d = REPO_ROOT / "procedural" / "reports" / "world_packs" / world_pack_id
    d.mkdir(parents=True, exist_ok=True)
    return d


if __name__ == "__main__":
    pack = sys.argv[1] if len(sys.argv) > 1 else "desert_mvp_world"
    wid, maps = enumerate_maps(pack)
    present = sum(1 for m in maps if m.spec_exists)
    print("world_pack={} maps={} specs_present={}".format(wid, len(maps), present))
    for m in maps:
        if not m.spec_exists:
            print("  MISSING: {} ({})".format(m.slice_id, m.get("spec_error")))
