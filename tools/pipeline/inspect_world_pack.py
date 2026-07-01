#!/usr/bin/env python3
"""inspect_world_pack.py — WorldForge v1.0x operator inspection tool.

Read-only. Shows what a generated world pack (or a single map) actually IS, by
joining the per-map spec, its environment/visual/sky/lighting/fog/rendering
profile bindings, its POI and entity-anchor overlays, and its validation
reports into one view. This is an operator utility to cut debugging time — NOT
docs and NOT a validator (it never fails a gate; it reports).

    python tools/pipeline/inspect_world_pack.py --pack desert_mvp_world
    python tools/pipeline/inspect_world_pack.py --pack desert_mvp_world --map Desert_AshFlats_IndustrialYard_Heavy_01
    python tools/pipeline/inspect_world_pack.py --pack desert_mvp_world --json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from world_pack_maps import enumerate_maps, report_dir_for  # noqa: E402

try:
    import profiles  # noqa: E402
    HAVE_PROFILES = True
except Exception:
    HAVE_PROFILES = False


def _load(path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _overlay(kind, slice_id):
    return _load(REPO_ROOT / "procedural" / "generated" / kind / (slice_id + ".json"))


def _env_view(world_pack_id, slice_id):
    if not HAVE_PROFILES:
        return {"environment_profile": "n/a (profiles.py unavailable)"}
    try:
        env_name, source = profiles.environment_for(world_pack_id, slice_id)
        resolved = profiles.resolve_environment(env_name)
        children = resolved.get("children", {})

        def cn(kind):
            c = children.get(kind) or {}
            return c.get("name") or c.get("id") or (resolved["environment"].get(kind))
        return {
            "environment_profile": env_name,
            "environment_source": source,
            "environment_class": resolved["environment"].get("class"),
            "visual_style": cn("visual_style"),
            "sky": cn("sky"),
            "lighting": cn("lighting"),
            "fog": cn("fog"),
            "rendering": cn("rendering"),
            "scalability": cn("scalability"),
            "ray_tracing": cn("ray_tracing"),
        }
    except Exception as exc:
        return {"environment_profile": "ERROR: %s" % exc}


def _map_view(world_pack_id, m):
    spec = m.spec
    sid = m.slice_id
    ld = _overlay("level_design", sid) or {}
    ea = _overlay("entity_anchors", sid) or {}
    pois = ld.get("pois") or ld.get("poi_nodes") or []
    poi_classes = sorted({p.get("class") for p in pois if isinstance(p, dict) and p.get("class")})
    anchors = ea.get("anchors") or []
    view = {
        "map_id": sid,
        "terrain_form": (spec.get("terrain_forge") or {}).get("recipe_id"),
        "placement_profile": spec.get("placement_preset_id"),
        "material_variant": spec.get("variant"),
        "scenario": (m.get("row") or {}).get("scenarios"),
        "poi_count": len(pois),
        "poi_classes": poi_classes,
        "entity_anchor_count": len(anchors),
        "state": (spec.get("state") or {}).get("key"),
    }
    view.update(_env_view(world_pack_id, sid))
    return view


def _validation_status(world_pack_id):
    """Summarise each *_report.json status in the pack report dir."""
    rdir = report_dir_for(world_pack_id)
    out = {}
    for rpt in sorted(rdir.glob("*_report.json")):
        data = _load(rpt) or {}
        out[rpt.stem.replace("_report", "")] = data.get("status", "?")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inspect a WorldForge world pack or map.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--map", default=None, help="Inspect a single map id")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = ap.parse_args(argv)

    world_pack_id, maps = enumerate_maps(args.pack)
    if args.map:
        maps = [m for m in maps if m.slice_id == args.map]
        if not maps:
            sys.stderr.write("map not found in pack: %s\n" % args.map)
            sys.exit(1)

    views = [_map_view(world_pack_id, m) for m in maps if m.spec_exists]
    val = _validation_status(world_pack_id)

    if args.json:
        json.dump({"world_pack_id": world_pack_id, "maps": views,
                   "validation_status": val}, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    print("=" * 72)
    print("WorldForge pack: %s  (%d maps)" % (world_pack_id, len(views)))
    print("=" * 72)
    if args.map and views:
        v = views[0]
        for k in ("map_id", "terrain_form", "placement_profile", "material_variant",
                  "environment_profile", "environment_class", "visual_style", "sky",
                  "lighting", "fog", "rendering", "scalability", "ray_tracing",
                  "state", "scenario", "poi_count", "poi_classes", "entity_anchor_count"):
            print("  %-22s %s" % (k, v.get(k)))
    else:
        for v in views:
            print("  %-42s env=%-28s POIs=%-2s anchors=%s" % (
                v["map_id"], v.get("environment_profile"), v["poi_count"], v["entity_anchor_count"]))
        # profile distribution
        from collections import Counter
        envc = Counter(v.get("environment_profile") for v in views)
        print("\n  Environment profile distribution:")
        for name, n in envc.most_common():
            print("    %-30s %d" % (name, n))
    print("\n  Validation report status:")
    for name, status in val.items():
        print("    %-34s %s" % (name, status))


if __name__ == "__main__":
    main()
