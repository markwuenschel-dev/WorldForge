#!/usr/bin/env python3
"""materialize_environment_rigs.py — WorldForge v1.3.5 environment rig materializer (Agent 3).

Resolves the UE-native environment rig for every mission map: reads each map's
bound environment profile (v1.0x/v1.1 data) and resolves it into a CONCRETE
actor/component spec (SkyAtmosphere / DirectionalLight / SkyLight /
ExponentialHeightFog / VolumetricCloud / PostProcessVolume / weather VFX) with
every parameter bound. Writes the rig spec + a materialization report per map and
the visual catalog. This is the anti-"JSON-only" step (brief §5): a profile that
is only a name does not resolve into a rig and fails.

Live in-editor actor spawning is deferred (no UE on this runner); the resolved
spec + report are exactly what tools/unreal/materialize_environment_rig.py
consumes when an editor is available. That is a follow-up, not a gate blocker.

Usage:
    python tools/pipeline/materialize_environment_rigs.py --pack mission_loop_world [--strict]
Writes: procedural/generated/visual/environment_rigs/<slice_id>.json + visual catalog + report.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_catalog import catalog_content_hash, load_visual_catalog, save_visual_catalog, upsert_map
from mission_catalog import load_mission_catalog
import mission_contract as MC
from report_meta import build_meta, hash_obj, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GENERATOR = "materialize_environment_rigs"
GENERATOR_VERSION = "1.3.5"
SOURCE_PACK = "biome_expansion_world"


def _map_biome_pairs(repo_root):
    """Return [(slice_id, biome), ...] for the mission maps (one rig per mission map)."""
    catalog = load_mission_catalog(repo_root)
    out = []
    seen = set()
    for mid, e in sorted((catalog.get("missions") or {}).items()):
        sid = e.get("source_map")
        if sid and sid not in seen:
            seen.add(sid)
            out.append((sid, e.get("biome_family")))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Materialize v1.3.5 environment rigs.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    pairs = _map_biome_pairs(REPO_ROOT)
    if not pairs:
        rep.error("no mission maps — run 'make create-mission-loops' first")

    catalog = load_visual_catalog(REPO_ROOT)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    written, biomes = [], set()
    rig_dir = REPO_ROOT / VC.ENV_RIGS_REL
    rig_dir.mkdir(parents=True, exist_ok=True)

    for slice_id, biome in pairs:
        rig, err = VC.resolve_rig(SOURCE_PACK, slice_id, biome=biome)
        if rig is None:
            rep.check("{}::rig_resolves".format(slice_id), False, err,
                      code=FailureCode.ENVIRONMENT_RIG_FAILURE)
            continue
        ok, detail = VC.rig_is_fully_resolved(rig)
        rep.check("{}::rig_fully_resolved".format(slice_id), ok, detail,
                  code=FailureCode.ENVIRONMENT_RIG_FAILURE)
        rig["provenance"] = {"generator": GENERATOR, "generator_version": GENERATOR_VERSION,
                             "generated_at_utc": now}
        # Materialization report the UE driver will consume (live spawn deferred).
        rig["materialization_report"] = {
            "spec_resolved": ok,
            "live_spawned": False,   # no UE editor on this runner (deferred)
            "ue_driver": "tools/unreal/materialize_environment_rig.py",
            "actor_set": [c["ue_class"] for c in rig["components"] if c["enabled"]],
        }
        out = rig_dir / "{}.json".format(slice_id)
        out.write_text(json.dumps(rig, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        entry = {
            "slice_id": slice_id, "biome": biome,
            "environment_profile": rig["environment_profile"],
            "profile_class": rig["profile_class"],
            "rig_path": out.relative_to(REPO_ROOT).as_posix(),
            "rig_resolved": ok,
            "component_count": len([c for c in rig["components"] if c["enabled"]]),
            "surface_status": "pending", "dressing_status": "pending",
            "readability_status": "pending", "budget_status": "pending",
            "ownership_class": VC.OWNERSHIP_GENERATED,
        }
        catalog = upsert_map(catalog, entry)
        written.append(slice_id)
        biomes.add(biome)

    save_visual_catalog(REPO_ROOT, catalog)
    rep.check("rigs_materialized", len(written) > 0, "materialized {} rigs".format(len(written)),
              code=FailureCode.ENVIRONMENT_RIG_FAILURE)
    rep.check("all_biomes_covered", len(biomes) >= 5, "biomes: {}".format(sorted(biomes)),
              code=FailureCode.ENVIRONMENT_RIG_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="materialize-environment-rigs", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(written),
                            output_manifest_hash=catalog_content_hash(catalog),
                            extra={"biomes": sorted(biomes), "live_spawned": False,
                                   "note": "spec-resolved; live UE spawn deferred (no editor)"}))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "materialize_environment_rigs",
              "materialize_environment_rigs_report.json")
    rep.print_summary("materialize-environment-rigs")
    print("[materialize-environment-rigs] {} rigs, {} biomes (spec-resolved; live spawn deferred)".format(
        len(written), len(biomes)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
