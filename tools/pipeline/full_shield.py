#!/usr/bin/env python3
"""full_shield.py — WorldForge v1.0x final integration gate (Agent 0).

Runs every registered v1.0x gate in order against a world pack and rolls the
results into ONE structured report plus a concise human summary. The parent
FAILS if any required child gate fails. This is the canonical
``make full-shield`` entrypoint:

    make full-shield PACK=desert_mvp_world JOBS=8 STRICT=1 DEEP=1 TORTURE=1 SEEDS=100

Design principles (brief §"No fake green"):
  * A gate whose validator SCRIPT DOES NOT EXIST is a blocking failure
    (status=missing) — never silently skipped.
  * A gate that exits non-zero is a blocking failure.
  * A gate that should have written a report but did not is a failure.
  * Torture-only / destructive gates run only under TORTURE=1.
  * The final report carries git SHA, pack, flags, seed set, timestamp and the
    per-gate status list; determinism consumers strip runtime-only meta.

The gate registry is data-driven so gates can be added/tuned in one place. Each
gate declares the exact argv (validators added by other v1.0x lanes all share
the contract CLI: ``--pack <id|yaml> [--strict] [--deep]``, exit 0/1, and write
a report under procedural/reports/...).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

from report_meta import build_meta, flag_from_env, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
WORLD_PACK_YAML = "procedural/world_packs/{pack}.yaml"

# Phases group gates for the human summary.
PHASES = [
    "spec", "generate", "environment", "sky-lighting-fog", "rendering",
    "poi", "entity", "scenario-package", "determinism-fuzz", "lifecycle",
    "regression", "final",
]


def _s(strict):
    return ["--strict"] if strict else []


def _d(deep):
    return ["--deep"] if deep else []


def gate(gid, label, phase, code, script, args_fn, report=None,
         torture_only=False, required=True):
    """Declare one gate. args_fn(ctx)->list[str] builds argv tail after the script."""
    return {
        "id": gid, "label": label, "phase": phase, "code": code,
        "script": script, "args_fn": args_fn, "report": report,
        "torture_only": torture_only, "required": required,
    }


def build_registry():
    """The ordered 33-gate v1.0x contract. Some gates are owned by lanes that
    land incrementally; until their script exists they register as blocking
    failures (status=missing)."""
    yaml_arg = lambda c: WORLD_PACK_YAML.format(pack=c["pack_id"])
    id_arg = lambda c: c["pack_id"]

    reports = "procedural/reports/world_packs/{pack}"

    def r(name):
        return lambda c: reports.format(pack=c["world_pack_id"]) + "/" + name

    G = []
    # 1 — static spec pre-flight
    G.append(gate("validate-world-pack-spec", "Validate world-pack spec", "spec",
                  FailureCode.CONTRACT_FAILURE, "validate_world_pack_spec.py",
                  lambda c: ["--pack", yaml_arg(c)] + _s(c["strict"])))
    # 2 — environment contract
    G.append(gate("validate-environment-contract", "Validate environment contract", "environment",
                  FailureCode.ENVIRONMENT_PROFILE_FAILURE, "validate_environment_contract.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=r("validate_environment_contract_report.json")))
    # 3 — build the pack (generation). Heavy; gated so a validation-only shield
    # can skip rebuild via BUILD=0.
    G.append(gate("create-world-pack", "Create world pack", "generate",
                  FailureCode.GENERATION_FAILURE, "create_world_pack.py",
                  lambda c: ["--pack", yaml_arg(c), "--jobs", str(c["jobs"])]
                            + (["--specs-only"] if c.get("biomeforge") else []),
                  required=True))
    # 4 — deep world-pack validation
    G.append(gate("validate-world-pack", "Validate world pack (deep)", "generate",
                  FailureCode.CONTRACT_FAILURE, "validate_world_pack.py",
                  lambda c: ["--pack", yaml_arg(c)] + _d(c["deep"]) + _s(c["strict"])))
    # 5 — report integrity (Agent 1)
    G.append(gate("validate-report-integrity", "Validate report integrity", "generate",
                  FailureCode.REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    # 6 — inspection metadata
    G.append(gate("validate-inspection", "Validate inspection metadata", "generate",
                  FailureCode.CONTRACT_FAILURE, "generate_inspection_metadata.py",
                  lambda c: ["--pack", yaml_arg(c), "--validate"] + _s(c["strict"])))
    # 7 — runtime scenario
    G.append(gate("run-world-state-scenario", "Run world-state scenario", "scenario-package",
                  FailureCode.SCENARIO_FAILURE, "run_world_state_scenario.py",
                  lambda c: ["--pack", yaml_arg(c), "--scenario", c["scenario"]] + _s(c["strict"])))
    # 8-11 — sky/lighting/fog/atmosphere (Agent 3)
    for name, code in (("sky", FailureCode.SKY_PROFILE_FAILURE),
                       ("lighting", FailureCode.LIGHTING_PROFILE_FAILURE),
                       ("fog", FailureCode.FOG_PROFILE_FAILURE),
                       ("atmosphere", FailureCode.ATMOSPHERE_PROFILE_FAILURE)):
        G.append(gate("validate-%s" % name, "Validate %s" % name, "sky-lighting-fog",
                      code, "validate_%s.py" % name,
                      lambda c, n=name: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r("validate_%s_report.json" % name)))
    # 12-15 — rendering/scalability/raytracing/budgets (Agent 6)
    for name, code in (("rendering-profiles", FailureCode.RENDERING_PROFILE_FAILURE),
                       ("scalability", FailureCode.SCALABILITY_FAILURE),
                       ("raytracing", FailureCode.RAYTRACING_FAILURE),
                       ("performance-budgets", FailureCode.BUDGET_FAILURE)):
        script = "validate_%s.py" % name.replace("-", "_")
        G.append(gate("validate-%s" % name, "Validate %s" % name, "rendering",
                      code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r(script.replace(".py", "_report.json"))))
    # 16-pre — generate level-design overlays (Agent 4) before validating them
    G.append(gate("generate-level-design", "Generate level-design overlays", "poi",
                  FailureCode.GENERATION_FAILURE, "generate_level_design.py",
                  lambda c: ["--pack", id_arg(c)]))
    # 16-19 — POI/level-design/reachability/poi-graph (Agent 4)
    for name, code in (("pois", FailureCode.POI_USABILITY_FAILURE),
                       ("level-design", FailureCode.LEVEL_DESIGN_FAILURE),
                       ("reachability", FailureCode.REACHABILITY_FAILURE),
                       ("poi-graph", FailureCode.POI_GRAPH_FAILURE)):
        script = "validate_%s.py" % name.replace("-", "_")
        G.append(gate("validate-%s" % name, "Validate %s" % name, "poi",
                      code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r(script.replace(".py", "_report.json"))))
    # 20-pre — generate entity-anchor overlays (Agent 5) before validating them
    G.append(gate("generate-entity-anchors", "Generate entity-anchor overlays", "entity",
                  FailureCode.GENERATION_FAILURE, "generate_entity_anchors.py",
                  lambda c: ["--pack", id_arg(c)]))
    # 20-22 — entity anchors/npc spawns/encounter readiness (Agent 5)
    for name, code in (("entity-anchors", FailureCode.ENTITY_ANCHOR_FAILURE),
                       ("npc-spawns", FailureCode.NPC_SPAWN_FAILURE),
                       ("encounter-readiness", FailureCode.ENCOUNTER_READINESS_FAILURE)):
        script = "validate_%s.py" % name.replace("-", "_")
        G.append(gate("validate-%s" % name, "Validate %s" % name, "entity",
                      code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r(script.replace(".py", "_report.json"))))
    # 23 — package check
    G.append(gate("package-check", "Package check", "scenario-package",
                  FailureCode.PACKAGE_FAILURE, "package_check.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    # 24 — determinism (Agent 7)
    G.append(gate("validate-determinism", "Validate determinism", "determinism-fuzz",
                  FailureCode.DETERMINISM_FAILURE, "validate_determinism.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    # 25 — seed matrix (Agent 7)
    G.append(gate("seed-matrix", "Seed matrix", "determinism-fuzz",
                  FailureCode.DETERMINISM_FAILURE, "seed_matrix.py",
                  lambda c: ["--pack", id_arg(c), "--seeds", str(c["seeds"])] + _s(c["strict"])))
    # 26 — fuzz (Agent 7)
    G.append(gate("fuzz-world-pack", "Fuzz world pack", "determinism-fuzz",
                  FailureCode.FUZZ_FAILURE, "fuzz_world_pack.py",
                  lambda c: ["--pack", id_arg(c), "--cases", str(c["cases"])] + _s(c["strict"])))
    # 27 — lifecycle torture (Agent 7) — TORTURE only
    G.append(gate("lifecycle-torture", "Lifecycle torture", "lifecycle",
                  FailureCode.LIFECYCLE_FAILURE, "lifecycle_torture.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  torture_only=True))
    # 28 — repair (existing)
    G.append(gate("repair-world-pack", "Repair world pack", "lifecycle",
                  FailureCode.LIFECYCLE_FAILURE, "repair_world_pack.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  torture_only=True))
    # 29-31 destroy/rebuild/revalidate are performed inside lifecycle-torture on
    # an owned scope (safe, provenance-guarded). Represented by gate 27 above +
    # revalidate below.
    # 31 — revalidate (Agent 0)
    G.append(gate("revalidate-world-pack", "Revalidate world pack", "lifecycle",
                  FailureCode.LIFECYCLE_FAILURE, "revalidate_world_pack.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  torture_only=True))
    # 32 — regression matrix (Agent 7)
    G.append(gate("validate-regression-matrix", "Validate regression matrix", "regression",
                  FailureCode.REGRESSION_FAILURE, "validate_regression_matrix.py",
                  lambda c: _s(c["strict"])))
    # 33 — final report integrity (Agent 1) — re-run after everything
    G.append(gate("final-report-integrity", "Final report integrity check", "final",
                  FailureCode.REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c), "--final"] + _s(c["strict"])))
    return G


def build_biomeforge_gates():
    """v1.1 BiomeForge gates. Appended to the registry ONLY for biome packs
    (a world pack that declares ``biome_families:`` / ``biomeforge: true``).
    desert_mvp_world does not declare biomes, so these never run for it and the
    v1.0x regression contract is untouched. Until each validator SCRIPT exists it
    registers as a blocking failure (status=missing) — no fake green.
    """
    id_arg = lambda c: c["pack_id"]
    reports = "procedural/reports/world_packs/{pack}"

    def r(name):
        return lambda c: reports.format(pack=c["world_pack_id"]) + "/" + name

    G = []
    biome_gates = [
        ("validate-biome-contract", "Validate biome contract",
         FailureCode.BIOME_CONTRACT_FAILURE, "validate_biome_contract.py"),
        ("validate-biome-matrix", "Validate biome matrix",
         FailureCode.BIOME_MATRIX_FAILURE, "validate_biome_matrix.py"),
        ("validate-biome-profile-bindings", "Validate biome profile bindings",
         FailureCode.BIOME_PROFILE_BINDING_FAILURE, "validate_biome_profile_bindings.py"),
        ("validate-biome-environment-compatibility", "Validate biome/environment compatibility",
         FailureCode.BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE,
         "validate_biome_environment_compatibility.py"),
        ("validate-biome-inspection", "Validate biome inspection",
         FailureCode.BIOME_CONTRACT_FAILURE, "validate_biome_inspection.py"),
        ("validate-terrain-forms", "Validate terrain forms",
         FailureCode.TERRAIN_FORM_FAILURE, "validate_terrain_forms.py"),
        ("validate-material-families", "Validate material families",
         FailureCode.MATERIAL_FAMILY_FAILURE, "validate_material_families.py"),
        ("validate-vegetation-profiles", "Validate vegetation profiles",
         FailureCode.VEGETATION_PROFILE_FAILURE, "validate_vegetation_profiles.py"),
        ("validate-placement-profiles", "Validate placement profiles",
         FailureCode.PLACEMENT_PROFILE_FAILURE, "validate_placement_profiles.py"),
        ("validate-biome-poi-compatibility", "Validate biome/POI compatibility",
         FailureCode.BIOME_POI_COMPATIBILITY_FAILURE, "validate_biome_poi_compatibility.py"),
        ("validate-biome-traversal", "Validate biome traversal",
         FailureCode.BIOME_TRAVERSAL_FAILURE, "validate_biome_traversal.py"),
        ("validate-biome-ecology-tags", "Validate biome ecology tags",
         FailureCode.BIOME_ECOLOGY_FAILURE, "validate_biome_ecology_tags.py"),
    ]
    for gid, label, code, script in biome_gates:
        G.append(gate(gid, label, "biome", code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r(script.replace(".py", "_report.json"))))
    # Biome fuzz matrix (Agent 7) — combinatorial biome/profile fuzzing.
    G.append(gate("fuzz-biome-matrix", "Fuzz biome matrix", "determinism-fuzz",
                  FailureCode.BIOME_FUZZ_FAILURE, "fuzz_biome_matrix.py",
                  lambda c: ["--pack", id_arg(c), "--cases", str(c["cases"])] + _s(c["strict"])))
    return G


def build_meshforge_gates():
    """v1.2 MeshForge Intake gates (brief §17, gates 47-61). Spliced into the
    registry ONLY when MESHES=1. Until each validator SCRIPT exists it registers
    as a blocking failure (status=missing) — no fake green. Every gate maps to the
    shared CLI contract (``--pack <id> [--strict]``, exit 0/1, writes a report)."""
    id_arg = lambda c: c["pack_id"]

    def rr(command, name):
        # mesh command reports live under procedural/reports/mesh/<command>/<name>
        return lambda c: "procedural/reports/mesh/{}/{}".format(command, name)

    G = []
    # 47 — generate/ingest the mesh asset matrix (Agent 2). Deterministic.
    G.append(gate("create-mesh-assets", "Create mesh assets", "mesh",
                  FailureCode.MESH_CONTRACT_FAILURE, "create_mesh_assets.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("create_mesh_assets", "create_mesh_assets_report.json")))
    # 48-57 — per-dimension mesh validators.
    mesh_gates = [
        ("validate-mesh-contract", "Validate mesh contract",
         FailureCode.MESH_CONTRACT_FAILURE, "validate_mesh_contract.py"),
        ("validate-mesh-catalog", "Validate mesh catalog",
         FailureCode.MESH_CATALOG_FAILURE, "validate_mesh_catalog.py"),
        ("validate-mesh-provenance", "Validate mesh provenance",
         FailureCode.MESH_PROVENANCE_FAILURE, "validate_mesh_provenance.py"),
        ("validate-mesh-final-paths", "Validate mesh final paths",
         FailureCode.MESH_FINAL_PATH_FAILURE, "validate_mesh_final_paths.py"),
        ("validate-mesh-material-bindings", "Validate mesh material bindings",
         FailureCode.MESH_MATERIAL_BINDING_FAILURE, "validate_mesh_material_bindings.py"),
        ("validate-mesh-collision-bounds", "Validate mesh collision/bounds",
         FailureCode.MESH_COLLISION_FAILURE, "validate_mesh_collision_bounds.py"),
        ("validate-mesh-pcg-eligibility", "Validate mesh PCG eligibility",
         FailureCode.MESH_PCG_ELIGIBILITY_FAILURE, "validate_mesh_pcg_eligibility.py"),
        ("validate-mesh-biome-compatibility", "Validate mesh biome compatibility",
         FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE, "validate_mesh_biome_compatibility.py"),
        ("validate-mesh-rendering-budgets", "Validate mesh rendering budgets",
         FailureCode.MESH_RENDERING_BUDGET_FAILURE, "validate_mesh_rendering_budgets.py"),
        ("validate-mesh-package", "Validate mesh package",
         FailureCode.MESH_PACKAGE_FAILURE, "validate_mesh_package.py"),
    ]
    for gid, label, code, script in mesh_gates:
        command = script.replace(".py", "")
        G.append(gate(gid, label, "mesh", code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr(command, command + "_report.json")))
    # 58 — negative mesh fixtures (Agent 7): known-bad definitions must be rejected.
    G.append(gate("mesh-negative-validators", "Mesh negative validators", "mesh",
                  FailureCode.MESH_NEGATIVE_FIXTURE_FAILURE, "test_negative_mesh.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    # 59-60 — mesh lifecycle torture (Agent 7): repair -> destroy -> rebuild ->
    # revalidate on a generated-owned scope. TORTURE only.
    G.append(gate("mesh-lifecycle-torture", "Mesh lifecycle torture", "mesh",
                  FailureCode.MESH_LIFECYCLE_FAILURE, "mesh_lifecycle_torture.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  torture_only=True))
    # 61 — final report integrity INCLUDING mesh reports (Agent 7 extends).
    G.append(gate("mesh-report-integrity", "Mesh report integrity", "mesh",
                  FailureCode.REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c), "--mesh"] + _s(c["strict"])))
    return G


def build_source_gates(houdini_mode, megascans_on):
    """v1.2 addendum — source-specific gates (Houdini §5 + Megascans §6, gates
    62-75). Houdini gates run when HOUDINI is set (live or metadata_only);
    Megascans gates run when MEGASCANS is set. Until a validator SCRIPT exists it
    registers as a blocking failure (status=missing) — no fake green."""
    id_arg = lambda c: c["pack_id"]
    lib_arg = lambda c: ["--lib", "megascans"]

    def rr(command):
        return lambda c: "procedural/reports/mesh/{}/{}_report.json".format(command, command)

    G = []
    if houdini_mode:
        houdini_gates = [
            ("validate-houdini-intake", "Validate Houdini intake",
             FailureCode.HOUDINI_SOURCE_FAILURE, "validate_houdini_intake.py"),
            ("validate-houdini-cook-reports", "Validate Houdini cook reports",
             FailureCode.HOUDINI_COOK_FAILURE, "validate_houdini_cook_reports.py"),
            ("validate-houdini-bake-reports", "Validate Houdini bake reports",
             FailureCode.HOUDINI_BAKE_FAILURE, "validate_houdini_bake_reports.py"),
            ("validate-houdini-generated-assets", "Validate Houdini generated assets",
             FailureCode.HOUDINI_OUTPUT_REGISTRY_FAILURE, "validate_houdini_generated_assets.py"),
        ]
        for gid, label, code, script in houdini_gates:
            command = script.replace(".py", "")
            G.append(gate(gid, label, "source-houdini", code, script,
                          lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                          report=rr(command)))
    if megascans_on:
        # 66 — scan the external library first (produces the external catalog).
        G.append(gate("scan-external-asset-library", "Scan external asset library",
                      "source-megascans", FailureCode.MEGASCANS_SCAN_FAILURE,
                      "scan_external_asset_library.py", lambda c: lib_arg(c) + _s(c["strict"]),
                      report=rr("scan_external_asset_library")))
        lib_gates = [
            ("validate-external-asset-catalog", "Validate external asset catalog",
             FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE, "validate_external_asset_catalog.py", True),
            ("validate-megascans-catalog", "Validate Megascans catalog",
             FailureCode.MEGASCANS_CATALOG_FAILURE, "validate_megascans_catalog.py", True),
            ("validate-external-asset-ownership", "Validate external asset ownership",
             FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE, "validate_external_asset_ownership.py", True),
        ]
        for gid, label, code, script, is_lib in lib_gates:
            command = script.replace(".py", "")
            args_fn = (lambda c: lib_arg(c) + _s(c["strict"])) if is_lib else \
                      (lambda c: ["--pack", id_arg(c)] + _s(c["strict"]))
            G.append(gate(gid, label, "source-megascans", code, script, args_fn, report=rr(command)))
        pack_gates = [
            ("validate-megascans-bindings", "Validate Megascans bindings",
             FailureCode.MEGASCANS_BINDING_FAILURE, "validate_megascans_bindings.py"),
            ("validate-megascans-pcg-eligibility", "Validate Megascans PCG eligibility",
             FailureCode.MEGASCANS_PCG_ELIGIBILITY_FAILURE, "validate_megascans_pcg_eligibility.py"),
            ("validate-megascans-biome-compatibility", "Validate Megascans biome compatibility",
             FailureCode.MEGASCANS_BIOME_COMPATIBILITY_FAILURE, "validate_megascans_biome_compatibility.py"),
            ("validate-third-party-package-policy", "Validate third-party package policy",
             FailureCode.THIRD_PARTY_ASSET_PACKAGE_POLICY_FAILURE, "validate_third_party_package_policy.py"),
        ]
        for gid, label, code, script in pack_gates:
            command = script.replace(".py", "")
            G.append(gate(gid, label, "source-megascans", code, script,
                          lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr(command)))
    # 74 — source ownership separation (runs whenever any source flag is on).
    if houdini_mode or megascans_on:
        G.append(gate("validate-source-ownership-separation", "Validate source ownership separation",
                      "source-separation", FailureCode.SOURCE_OWNERSHIP_SEPARATION_FAILURE,
                      "validate_source_ownership_separation.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr("validate_source_ownership_separation")))
        # source negative fixtures — known-bad houdini/megascans records must be rejected.
        G.append(gate("source-negative-validators", "Source negative validators",
                      "source-separation", FailureCode.MESH_NEGATIVE_FIXTURE_FAILURE,
                      "test_negative_sources.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
        # source lifecycle torture (Megascans destroy-protection + ownership) — TORTURE only.
        G.append(gate("source-lifecycle-torture", "Source lifecycle torture",
                      "source-separation", FailureCode.MESH_LIFECYCLE_FAILURE,
                      "source_lifecycle_torture.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      torture_only=True))
        # 75 — source-specific report integrity (extends validate_report_integrity).
        G.append(gate("source-report-integrity", "Source report integrity",
                      "source-separation", FailureCode.REPORT_INTEGRITY_FAILURE,
                      "validate_report_integrity.py",
                      lambda c: ["--pack", id_arg(c), "--sources"] + _s(c["strict"])))
    return G


def pack_declares_missionforge(pack):
    """True if a pack yaml declares MissionForge (``missionforge: true``)."""
    import yaml as _yaml
    from world_pack_maps import resolve_world_pack_path
    try:
        wp_path = resolve_world_pack_path(pack)
        if not wp_path.is_file():
            return False
        data = _yaml.safe_load(wp_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return bool(data.get("missionforge"))


def build_missionforge_gates(playtest_on):
    """v1.3 MissionForge + PlaytestForge gates. A missionforge pack (mission_loop_
    world) layers missions over a source pack, so this is a mission-FOCUSED gate
    set — not the 33 world-gen gates. Playtest gates only run under PLAYTEST=1.
    Until a validator SCRIPT exists it registers as blocking (status=missing)."""
    id_arg = lambda c: c["pack_id"]

    def rr(command):
        return lambda c: "procedural/reports/missions/{}/{}_report.json".format(command, command)

    G = []
    # generate the mission loops first.
    G.append(gate("create-mission-loops", "Create mission loops", "mission",
                  FailureCode.MISSION_CONTRACT_FAILURE, "create_mission_loops.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("create_mission_loops")))
    mission_gates = [
        ("validate-mission-contract", FailureCode.MISSION_CONTRACT_FAILURE, "validate_mission_contract.py"),
        ("validate-mission-graph", FailureCode.MISSION_GRAPH_FAILURE, "validate_mission_graph.py"),
        ("validate-mission-placement", FailureCode.MISSION_PLACEMENT_FAILURE, "validate_mission_placement.py"),
        ("validate-mission-biome-compatibility", FailureCode.MISSION_BIOME_COMPATIBILITY_FAILURE, "validate_mission_biome_compatibility.py"),
        ("validate-mission-routes", FailureCode.MISSION_ROUTE_FAILURE, "validate_mission_routes.py"),
        ("validate-mission-objectives", FailureCode.MISSION_OBJECTIVE_FAILURE, "validate_mission_objectives.py"),
        ("validate-mission-state", FailureCode.MISSION_STATE_FAILURE, "validate_mission_state.py"),
        ("validate-mission-save-load", FailureCode.MISSION_SAVE_LOAD_FAILURE, "validate_mission_save_load.py"),
        ("validate-mission-rewards", FailureCode.MISSION_REWARD_FAILURE, "validate_mission_rewards.py"),
        ("validate-mission-dependencies", FailureCode.MISSION_MESH_DEPENDENCY_FAILURE, "validate_mission_dependencies.py"),
        ("validate-mission-mesh-usage", FailureCode.MISSION_MESH_DEPENDENCY_FAILURE, "validate_mission_mesh_usage.py"),
        ("validate-mission-entity-anchors", FailureCode.MISSION_GRAPH_FAILURE, "validate_mission_entity_anchors.py"),
    ]
    for gid, code, script in mission_gates:
        command = script.replace(".py", "")
        G.append(gate(gid, gid.replace("-", " ").title(), "mission", code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr(command)))
    if playtest_on:
        G.append(gate("validate-playtest-contract", "Validate playtest contract", "playtest",
                      FailureCode.PLAYTEST_CONTRACT_FAILURE, "validate_playtest_contract.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr("validate_playtest_contract")))
        G.append(gate("run-playtest-forge", "Run PlaytestForge", "playtest",
                      FailureCode.PLAYTEST_COMPLETION_FAILURE, "run_playtest_forge.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr("run_playtest_forge")))
        G.append(gate("validate-playtest-reports", "Validate playtest reports", "playtest",
                      FailureCode.PLAYTEST_REPORT_FAILURE, "validate_playtest_reports.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr("validate_playtest_reports")))
    # mission negative + fuzz + torture + report integrity.
    G.append(gate("mission-negative-validators", "Mission negative validators", "mission",
                  FailureCode.MISSION_CONTRACT_FAILURE, "test_negative_mission.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    G.append(gate("fuzz-mission-matrix", "Fuzz mission matrix", "mission",
                  FailureCode.MISSION_CONTRACT_FAILURE, "fuzz_mission_matrix.py",
                  lambda c: ["--pack", id_arg(c), "--cases", str(c["cases"])] + _s(c["strict"])))
    G.append(gate("mission-lifecycle-torture", "Mission lifecycle torture", "mission",
                  FailureCode.MISSION_CONTRACT_FAILURE, "mission_lifecycle_torture.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), torture_only=True))
    G.append(gate("mission-report-integrity", "Mission report integrity", "mission",
                  FailureCode.REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c), "--missions"] + _s(c["strict"])))
    return G


def pack_declares_biomes(pack):
    """True if a world pack yaml declares BiomeForge (``biome_families:`` list or
    ``biomeforge: true``). Used to conditionally include the v1.1 gates."""
    import yaml as _yaml
    from world_pack_maps import resolve_world_pack_path
    wp_path = resolve_world_pack_path(pack)
    if not wp_path.is_file():
        return False
    try:
        data = _yaml.safe_load(wp_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return bool(data.get("biomeforge")) or bool(data.get("biome_families"))


def run_gate(g, ctx):
    """Run one gate; return a result row."""
    script_path = PIPELINE / g["script"]
    row = {"id": g["id"], "label": g["label"], "phase": g["phase"],
           "code": g["code"], "status": None, "rc": None, "detail": ""}

    if g["torture_only"] and not ctx["torture"]:
        row["status"] = "skipped_no_torture"
        row["detail"] = "torture-only gate; TORTURE not set"
        return row

    if not script_path.is_file():
        row["status"] = "missing"
        row["detail"] = "validator not implemented yet: tools/pipeline/%s" % g["script"]
        return row

    argv = [PY, str(script_path)] + g["args_fn"](ctx)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if ctx["strict"]:
        env["STRICT"] = "1"
    if ctx["deep"]:
        env["DEEP"] = "1"
    # v1.2 addendum — make source flags visible to gate subprocesses even when
    # they were passed as full_shield args rather than the environment.
    if ctx.get("houdini_mode"):
        env["HOUDINI"] = ctx["houdini_mode"]
    if ctx.get("megascans"):
        env["MEGASCANS"] = "1"
    try:
        proc = subprocess.run(argv, cwd=str(REPO_ROOT), env=env,
                              capture_output=True, text=True, timeout=ctx["timeout"])
    except subprocess.TimeoutExpired:
        row["status"] = "fail"
        row["detail"] = "timeout after %ss" % ctx["timeout"]
        return row
    row["rc"] = proc.returncode
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    row["detail"] = " | ".join(tail)[:400]

    # Cross-check the gate's report if it declares one.
    if g["report"]:
        rpt_path = REPO_ROOT / g["report"](ctx)
        if not rpt_path.is_file():
            row["status"] = "fail"
            row["detail"] = "gate exited %s but wrote no report: %s" % (proc.returncode, g["report"](ctx))
            return row
        try:
            rpt = json.loads(rpt_path.read_text(encoding="utf-8"))
            row["report_status"] = rpt.get("status")
            rc_meta = rpt.get("meta") or {}
            row["record_count"] = rc_meta.get("record_count", rpt.get("counts", {}).get("PASS"))
        except Exception as exc:
            row["status"] = "fail"
            row["detail"] = "report unparseable: %s" % exc
            return row

    row["status"] = "pass" if proc.returncode == 0 else "fail"
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.0x full-shield integration gate.")
    ap.add_argument("--pack", default="desert_mvp_world")
    ap.add_argument("--jobs", type=int, default=int(os.environ.get("JOBS", "1")))
    ap.add_argument("--seeds", type=int, default=int(os.environ.get("SEEDS", "5")))
    ap.add_argument("--cases", type=int, default=int(os.environ.get("CASES", "25")))
    ap.add_argument("--scenario", default="industrial_takeover")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--torture", action="store_true")
    ap.add_argument("--meshes", action="store_true",
                    help="Include v1.2 MeshForge Intake gates (also via MESHES=1).")
    ap.add_argument("--missions", action="store_true",
                    help="Include v1.3 MissionForge gates (also via MISSIONS=1).")
    ap.add_argument("--playtest", action="store_true",
                    help="Include v1.3 PlaytestForge gates (also via PLAYTEST=1).")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--no-build", action="store_true",
                    help="Skip the heavy create-world-pack rebuild gate (validation-only run).")
    ap.add_argument("--only", default=None, help="Run only gates whose id contains this substring")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    deep = args.deep or flag_from_env("DEEP")
    torture = args.torture or flag_from_env("TORTURE")

    missionforge = pack_declares_missionforge(args.pack)
    missions_on = args.missions or flag_from_env("MISSIONS") or missionforge
    playtest_on = args.playtest or flag_from_env("PLAYTEST")

    # Resolve world_pack_id from the pack yaml. A missionforge pack layers missions
    # over a source pack and owns no maps of its own, so enumerate_maps is bypassed.
    from world_pack_maps import enumerate_maps
    if missionforge:
        world_pack_id, maps = args.pack, []
    else:
        try:
            world_pack_id, maps = enumerate_maps(args.pack)
        except Exception as exc:
            sys.stderr.write("ERROR: cannot enumerate pack %s: %s\n" % (args.pack, exc))
            sys.exit(2)

    ctx = {"pack_id": args.pack, "world_pack_id": world_pack_id,
           "strict": strict, "deep": deep, "torture": torture,
           "jobs": args.jobs, "seeds": args.seeds, "cases": args.cases,
           "scenario": args.scenario, "timeout": args.timeout}

    print("=" * 70)
    print("WorldForge v1.0x FULL-SHIELD — pack=%s strict=%s deep=%s torture=%s seeds=%s" % (
        world_pack_id, strict, deep, torture, args.seeds))
    print("=" * 70)

    # v1.3 — a missionforge pack runs a mission-FOCUSED shield (missions +
    # playtest + optional mesh/megascans gates), NOT the 33 world-gen gates
    # (those belong to its source pack, exercised by the regression gate).
    if missionforge:
        import houdini_contract  # noqa: E402
        ctx["biomeforge"] = False
        ctx["meshes"] = args.meshes or flag_from_env("MESHES")
        ctx["houdini_mode"] = houdini_contract.houdini_mode_from_env()
        ctx["megascans"] = flag_from_env("MEGASCANS")
        registry = build_missionforge_gates(playtest_on)
        if ctx["meshes"]:
            registry = (build_meshforge_gates()
                        + build_source_gates(ctx["houdini_mode"], ctx["megascans"])
                        + registry)
        print("MissionForge pack — %d gate(s) active (playtest=%s, meshes=%s, megascans=%s)." % (
            len(registry), bool(playtest_on), bool(ctx["meshes"]), bool(ctx["megascans"])))
    else:
        registry = build_registry()

    # v1.1 — splice in BiomeForge gates for biome packs only. desert_mvp_world
    # does not declare biomes, so its 33-gate v1.0x contract is unchanged.
    # A missionforge pack lists biome_families for context but is NOT a biome
    # world pack, so it skips the biome/mesh splice blocks entirely.
    ctx["biomeforge"] = (not missionforge) and pack_declares_biomes(args.pack)
    if ctx["biomeforge"]:
        # Biome packs are not desert/industrial; use the biome-neutral runtime
        # scenario unless the operator explicitly overrode --scenario.
        if args.scenario == "industrial_takeover":
            ctx["scenario"] = "biome_site_activation"
        bf = build_biomeforge_gates()
        fuzz_gate = [g for g in bf if g["id"] == "fuzz-biome-matrix"]
        data_gates = [g for g in bf if g["id"] != "fuzz-biome-matrix"]
        ids = [g["id"] for g in registry]
        # biome data validators run after deep world-pack validation.
        anchor = ids.index("validate-world-pack") + 1 if "validate-world-pack" in ids else len(registry)
        registry[anchor:anchor] = data_gates
        ids = [g["id"] for g in registry]
        fanchor = ids.index("fuzz-world-pack") + 1 if "fuzz-world-pack" in ids else len(registry)
        registry[fanchor:fanchor] = fuzz_gate
        print("BiomeForge pack detected — %d v1.1 gate(s) active." % len(bf))

    # v1.2 — splice in MeshForge Intake gates when MESHES=1. They append after the
    # regression matrix and before the final report-integrity gate, so mesh
    # failures roll up by lane and the final integrity scan sees mesh reports.
    ctx["meshes"] = (not missionforge) and (args.meshes or flag_from_env("MESHES"))
    # v1.2 addendum — Houdini/Megascans source flags. HOUDINI may be '1'/'live'
    # or 'metadata_only'; MEGASCANS is a plain flag.
    import houdini_contract  # noqa: E402
    if not missionforge:
        ctx["houdini_mode"] = houdini_contract.houdini_mode_from_env()
        ctx["megascans"] = flag_from_env("MEGASCANS")
    if ctx["meshes"]:
        mf = build_meshforge_gates()
        # Addendum source gates depend on the mesh catalog, so append them to the
        # mesh block (still before final-report-integrity).
        mf += build_source_gates(ctx["houdini_mode"], ctx["megascans"])
        ids = [g["id"] for g in registry]
        anchor = ids.index("final-report-integrity") if "final-report-integrity" in ids else len(registry)
        registry[anchor:anchor] = mf
        print("MeshForge Intake enabled — %d v1.2 mesh gate(s) active." % len(mf))
        if ctx["houdini_mode"]:
            print("Houdini intake enabled — mode=%s" % ctx["houdini_mode"])
        if ctx["megascans"]:
            print("Megascans external library enabled.")

    if args.no_build or flag_from_env("NO_BUILD"):
        registry = [g for g in registry if g["id"] != "create-world-pack"]
    if args.only:
        registry = [g for g in registry if args.only in g["id"]]

    rows = []
    for i, g in enumerate(registry, 1):
        print("\n[%2d/%d] %s (%s)" % (i, len(registry), g["label"], g["id"]))
        row = run_gate(g, ctx)
        rows.append(row)
        mark = {"pass": "PASS", "fail": "FAIL", "missing": "MISSING",
                "skipped_no_torture": "SKIP"}.get(row["status"], row["status"].upper())
        print("       -> %s  %s" % (mark, row["detail"]))

    # Roll up.
    def is_blocking(row, g):
        if row["status"] in ("fail", "missing"):
            return True
        return False

    gate_by_id = {g["id"]: g for g in registry}
    blocking = [r for r in rows if is_blocking(r, gate_by_id[r["id"]])]
    n_pass = sum(1 for r in rows if r["status"] == "pass")
    n_fail = sum(1 for r in rows if r["status"] == "fail")
    n_missing = sum(1 for r in rows if r["status"] == "missing")
    n_skip = sum(1 for r in rows if r["status"] == "skipped_no_torture")
    passed = len(blocking) == 0

    # Failure taxonomy rollup.
    taxonomy = {}
    for r in blocking:
        taxonomy.setdefault(r["code"], []).append(r["id"])

    meta = build_meta(command="full-shield", pack=world_pack_id, strict=strict,
                      deep=deep, torture=torture, seeds=args.seeds,
                      status="ok" if passed else "fail",
                      failure_count=len(blocking), record_count=len(rows))

    report = {
        "world_pack_id": world_pack_id, "meta": meta,
        "passed": passed, "status": "ok" if passed else "fail",
        "totals": {"gates": len(rows), "pass": n_pass, "fail": n_fail,
                   "missing": n_missing, "skipped": n_skip},
        "blocking_gates": [r["id"] for r in blocking],
        "failure_taxonomy": taxonomy,
        "gates": rows,
        "map_count": len(maps),
    }
    report_dir = REPO_ROOT / "procedural" / "reports" / "world_packs" / world_pack_id
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / "full_shield_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print("FULL-SHIELD %s — %d/%d gates pass (%d fail, %d missing, %d skipped)" % (
        "PASS" if passed else "FAIL", n_pass, len(rows), n_fail, n_missing, n_skip))
    if blocking:
        print("Blocking gates:")
        for r in blocking:
            print("  [%s] %s (%s)" % (r["status"].upper(), r["id"], r["code"]))
    if taxonomy:
        print("Failure taxonomy:")
        for code, ids in sorted(taxonomy.items()):
            print("  %s: %s" % (code, ", ".join(ids)))
    print("Report: procedural/reports/world_packs/%s/full_shield_report.json" % world_pack_id)
    print("=" * 70)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
