#!/usr/bin/env python3
"""generate_owned_cover_meshes.py — WorldForge v1.5 Wave-3 owned-cover baseline factory.

HYBRID PRODUCTION RULE (locked, non-negotiable): every cover family present in a
pack MUST have a ``generated_owned`` baseline cover mesh — the GUARANTEED coverage
that a third-party catalog mesh only ever *replaces* (never removes). This tool
emits, for every cover family the pack needs (derived from encounter data x
``encounter_contract.BIOME_COVER_FAMILIES``) x every realized-cover height class,
a baseline cover-mesh SPEC (descriptor JSON) under
``asset_paths.OWNED_COVER_DIR/<sm_id>.json``. A UE driver builds the real
StaticMesh from this spec later; this layer only writes the honest plan.

Fail-closed: if any family/height the pack needs lacks a baseline spec, the run
fails with COVER_BASELINE_MISSING (the hybrid rule cannot be silently violated).

Determinism: no wall-clock / random in this module — provenance is stamped by the
shared ``provenance.build_provenance`` helper the contract mandates.

Usage:
    python tools/pipeline/generate_owned_cover_meshes.py --pack encounter_loop_world [--strict]
Report: wf.realization.owned_cover_report.v1
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import encounter_contract as EC
import mesh_contract as MC
import provenance as PROV
import realized_cover_contract as RC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "generate_owned_cover_meshes"
REPORT_TYPE = "wf.realization.owned_cover_report.v1"
GENERATOR_VERSION = "1.5.0"

OWNED_COVER_ROOT = "/Game/WorldForge/Generated/Meshes/OwnedCover/"

# Baseline bounds sized to the realized-cover height class (cm). Footprint grows
# modestly with height so the three classes are visibly distinct blockers.
HEIGHT_BOUNDS = {
    "low": {"x_cm": 180.0, "y_cm": 140.0, "z_cm": 90.0},
    "half_height": {"x_cm": 200.0, "y_cm": 160.0, "z_cm": 180.0},
    "full_height": {"x_cm": 220.0, "y_cm": 180.0, "z_cm": 280.0},
}


def load_pack_encounters(pack):
    """Return the encounter dicts belonging to ``pack`` (sorted by id)."""
    base = REPO_ROOT / "procedural" / "generated" / "encounters"
    out = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        p = d / "encounter.json"
        if not p.is_file():
            continue
        try:
            enc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — corrupt encounter is a caller concern
            continue
        if enc.get("pack_id") == pack:
            out.append(enc)
    return out


def sm_id_for(family, height_class):
    return "SM_Owned_{}_{}".format(family, height_class)


def pack_cover_needs(encounters):
    """Compute the (family, height_class) pairs the pack actually needs.

    families come from encounter biomes x BIOME_COVER_FAMILIES; heights from the
    height classes that actually appear on the pack's cover anchors. Also returns
    the family->biomes map so each baseline can declare biome_compatibility.
    """
    needs = set()
    families = set()
    heights = set()
    family_biomes = {}
    for enc in encounters:
        biome = enc.get("biome_family")
        fams = EC.BIOME_COVER_FAMILIES.get(biome, ())
        for f in fams:
            families.add(f)
            family_biomes.setdefault(f, set()).add(biome)
        for cov in enc.get("cover_anchors") or []:
            hc = cov.get("height_class")
            if hc in RC.HEIGHT_CLASSES:
                heights.add(hc)
    for f in families:
        for h in heights:
            needs.add((f, h))
    return needs, sorted(families), sorted(heights), family_biomes


def build_baseline_spec(family, height_class, biomes, prov):
    bounds = dict(HEIGHT_BOUNDS[height_class])
    sm_id = sm_id_for(family, height_class)
    return {
        "sm_id": sm_id,
        "family": family,
        "height_class": height_class,
        "final_asset_path": OWNED_COVER_ROOT + sm_id,
        "ownership_class": MC.OWNERSHIP_GENERATED,
        "generated_owned": True,
        "third_party_owned": False,
        "human_owned": False,
        "project_owned": False,
        "collision_profile": RC.REQUIRED_COLLISION_PROFILE,
        "bounds": bounds,
        "pivot_policy": "base_center",
        "scale_policy": "uniform",
        "biome_compatibility": sorted(biomes),
        "budget_class": "performance_safe",
        "generator": COMMAND,
        "generator_version": GENERATOR_VERSION,
        "recipe_id": "recipe_owned_cover_{}_{}".format(family, height_class),
        "live_built": False,  # UE driver flips True once the StaticMesh is built
        "materialization_status": "not_materialized",
        "schema_version": RC.SCHEMA_VERSION,
        "provenance": prov,
    }


def generate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    encounters = load_pack_encounters(pack)
    rep.check("pack_has_encounters", bool(encounters),
              "no encounters in pack '{}'".format(pack),
              code=FailureCode.COVER_BASELINE_MISSING)
    if not encounters:
        return rep, 0, []

    needs, families, heights, family_biomes = pack_cover_needs(encounters)
    rep.check("pack_declares_cover_families", bool(families),
              "no cover families derivable from pack biomes",
              code=FailureCode.COVER_BASELINE_MISSING)
    rep.check("pack_declares_height_classes", bool(heights),
              "no realized-cover height classes on pack cover anchors",
              code=FailureCode.COVER_BASELINE_MISSING)

    prov = PROV.build_provenance(
        REPO_ROOT,
        [Path(EC.__file__), Path(MC.__file__), Path(RC.__file__)],
        COMMAND, GENERATOR_VERSION)
    # Determinism: keep only the deterministic provenance (git sha + input content
    # hashes); drop the wall-clock stamp so specs are byte-stable across re-runs.
    prov.pop("generated_at_utc", None)

    # Emit the FULL family x height matrix (guaranteed coverage): even a height a
    # given family has not yet been placed at gets a baseline, so no anchor can
    # ever land without one.
    written = []
    for family in families:
        biomes = family_biomes.get(family, set())
        for height in RC.HEIGHT_CLASSES:
            spec = build_baseline_spec(family, height, biomes, prov)
            out = asset_paths.ensure(
                asset_paths.OWNED_COVER_DIR / (spec["sm_id"] + ".json"))
            out.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            written.append(spec["sm_id"])

    written_ids = set(written)

    # Fail-closed hybrid guarantee: every (family, height) the pack NEEDS must now
    # have a baseline spec on disk.
    for family, height in sorted(needs):
        want = sm_id_for(family, height)
        rep.check("baseline_present[{}:{}]".format(family, height),
                  want in written_ids,
                  "cover family '{}' at height '{}' has no generated_owned "
                  "baseline (hybrid rule violated)".format(family, height),
                  code=FailureCode.COVER_BASELINE_MISSING)

    return rep, len(written), sorted(written_ids)


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 owned-cover baseline factory.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep, n_written, written = generate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=n_written, records_total=n_written,
        records_passed=n_written if rep.passed else 0,
        records_failed=0 if rep.passed else n_written,
        extra={"baseline_specs": written,
               "owned_cover_dir": asset_paths.OWNED_COVER_DIR.relative_to(REPO_ROOT).as_posix()}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write("[{}] {} baseline spec(s) written\n".format(COMMAND, n_written))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
