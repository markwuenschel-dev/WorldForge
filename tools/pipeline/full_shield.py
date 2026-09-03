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
    # 32b — generative-source integrity. A declared generative source may not
    # be EMPTY (its digest would be the digest of nothing, recorded as
    # faithfully as a real one), and a generated output must name the tool
    # that produced it (a stopgap and a real render write identical files to
    # identical paths). Takes no --pack: it grades every material manifest.
    G.append(gate("validate-generative-sources", "Validate generative sources", "spec",
                  FailureCode.PROVENANCE_SOURCE_EMPTY, "validate_generative_sources.py",
                  lambda c: _s(c["strict"]),
                  report="procedural/reports/materials/validate_generative_sources/validate_generative_sources_report.json"))
    # 32c — PCG execution. Binding a graph is a wiring fact; this gate wants a
    # MEASURED generation result. 121 slices report pcg_graph_bound=true and
    # none report what the graph produced, so this is RED until the slice
    # builder's measurement has actually run in an editor.
    G.append(gate("validate-pcg-execution", "Validate PCG execution is measured", "generate",
                  FailureCode.PCG_EXECUTION_UNMEASURED, "validate_pcg_execution.py",
                  lambda c: _s(c["strict"]),
                  report="procedural/reports/slices/validate_pcg_execution/validate_pcg_execution_report.json"))
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
            # Asks the question the four above do not: WHO WROTE the report
            # being graded? The pipeline writes its own cook/bake/import
            # reports, so those gates and their subject share an author.
            # This one refuses self-authored cook evidence (WF239) and is
            # RED by design until a real Houdini process leaves evidence.
            ("validate-houdini-cook-evidence", "Validate Houdini cook evidence is independent",
             FailureCode.HOUDINI_COOK_EVIDENCE_SELF_AUTHORED,
             "validate_houdini_cook_evidence.py"),
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


def build_visualforge_gates(include_v1_5_kits=False):
    """v1.3.5 VisualFidelityForge gates. Spliced into a missionforge shield when
    VISUALS=1. Materializes the environment rig + surface/dressing/coverage and
    validates fidelity without breaking playability/budget/lifecycle. Until a
    validator SCRIPT exists it registers as blocking (status=missing).

    The v1.5 VisualEnvironmentForge biome-kit gates (which include a fail-closed
    inspection-screenshot gate needing a live UE capture) are added ONLY when
    include_v1_5_kits=True — i.e. on the v1.5 materialize shield — so a prior-pack
    shield run with plain VISUALS=1 (mission/biome) is not regressed by v1.5 work."""
    id_arg = lambda c: c["pack_id"]

    def rr(command):
        return lambda c: "procedural/reports/visual/{}/{}_report.json".format(command, command)

    G = []
    # generate/scan first: materialize rigs, scan Megascans visual assets, dress.
    G.append(gate("materialize-environment-rigs", "Materialize environment rigs", "visual",
                  FailureCode.ENVIRONMENT_RIG_FAILURE, "materialize_environment_rigs.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("materialize_environment_rigs")))
    G.append(gate("scan-megascans-visual-assets", "Scan Megascans visual assets", "visual",
                  FailureCode.VISUAL_ASSET_COVERAGE_FAILURE, "scan_megascans_visual_assets.py",
                  lambda c: ["--lib", "megascans"] + _s(c["strict"]),
                  report=rr("scan_megascans_visual_assets")))
    G.append(gate("create-visual-dressing", "Create visual dressing", "visual",
                  FailureCode.WORLD_DRESSING_FAILURE, "create_visual_dressing.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("create_visual_dressing")))
    visual_gates = [
        ("validate-visual-asset-coverage", FailureCode.VISUAL_ASSET_COVERAGE_FAILURE, "validate_visual_asset_coverage.py"),
        ("validate-surface-materialization", FailureCode.SURFACE_MATERIALIZATION_FAILURE, "validate_surface_materialization.py"),
        ("validate-world-dressing", FailureCode.WORLD_DRESSING_FAILURE, "validate_world_dressing.py"),
        ("validate-environment-rig", FailureCode.ENVIRONMENT_RIG_FAILURE, "validate_environment_rig.py"),
        ("validate-sky-materialization", FailureCode.SKY_MATERIALIZATION_FAILURE, "validate_sky_materialization.py"),
        ("validate-fog-materialization", FailureCode.FOG_MATERIALIZATION_FAILURE, "validate_fog_materialization.py"),
        ("validate-cloud-materialization", FailureCode.CLOUD_MATERIALIZATION_FAILURE, "validate_cloud_materialization.py"),
        ("validate-lighting-exposure", FailureCode.LIGHTING_EXPOSURE_FAILURE, "validate_lighting_exposure.py"),
        ("validate-post-process-profiles", FailureCode.POST_PROCESS_PROFILE_FAILURE, "validate_post_process_profiles.py"),
        ("validate-weather-vfx", FailureCode.WEATHER_VFX_FAILURE, "validate_weather_vfx.py"),
        ("validate-visual-readability", FailureCode.VISUAL_READABILITY_FAILURE, "validate_visual_readability.py"),
        ("validate-visual-budgets", FailureCode.VISUAL_BUDGET_FAILURE, "validate_visual_budgets.py"),
        ("validate-visual-package", FailureCode.VISUAL_PACKAGE_FAILURE, "validate_visual_package.py"),
    ]
    for gid, code, script in visual_gates:
        command = script.replace(".py", "")
        G.append(gate(gid, gid.replace("-", " ").title(), "visual", code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr(command)))
    # v1.5 VisualEnvironmentForge — biome visual kits composed from the v1.3.5
    # profile system, materialized live, with per-zone readability + density +
    # inspection-evidence gates. Registers blocking (missing) until each script
    # exists; the inspection gate is fail-closed until the live UE capture runs.
    # Gated on the v1.5 materialize lane so prior VISUALS-only shields are clean.
    if include_v1_5_kits:
        G.append(gate("create-visual-environment-kits", "Create visual environment kits", "visual",
                      FailureCode.VISUAL_KIT_CONTRACT_FAILURE, "create_visual_environment_kits.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr("create_visual_environment_kits")))
        v1_5_visual_gates = [
            ("validate-visual-kit-schema", FailureCode.VISUAL_KIT_SCHEMA_FAILURE, "validate_visual_kit.py"),
            ("validate-biome-visual-readability", FailureCode.VISUAL_ROUTE_READABILITY_FAILURE, "validate_biome_visual_readability.py"),
            ("validate-visual-density-budgets", FailureCode.VISUAL_DENSITY_BUDGET_FAILURE, "validate_visual_density_budgets.py"),
            ("visual-inspection-report", FailureCode.VISUAL_SCREENSHOT_REPORT_FAILURE, "validate_visual_inspection_report.py"),
        ]
        for gid, code, script in v1_5_visual_gates:
            command = script.replace(".py", "")
            G.append(gate(gid, gid.replace("-", " ").title(), "visual", code, script,
                          lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr(command)))
    G.append(gate("visual-negative-validators", "Visual negative validators", "visual",
                  FailureCode.VISUAL_READABILITY_FAILURE, "test_negative_visual.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    G.append(gate("visual-lifecycle-torture", "Visual lifecycle torture", "visual",
                  FailureCode.VISUAL_LIFECYCLE_FAILURE, "visual_lifecycle_torture.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), torture_only=True))
    G.append(gate("visual-report-integrity", "Visual report integrity", "visual",
                  FailureCode.REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c), "--visuals"] + _s(c["strict"])))
    return G


def build_assetforge_gates():
    """v1.5 AssetAcquisitionForge gates. Spliced when ASSETS=1. Gap analysis →
    procurement → source-adapter policy → quarantine → license/provenance/hash →
    catalog → package policy, plus acquisition negatives + report integrity.
    Until a validator SCRIPT exists it registers as blocking (status=missing) so
    the shield is honest about the unfinished lane."""
    id_arg = lambda c: c["pack_id"]

    def rr(command):
        return lambda c: "procedural/reports/assets/{}/{}_report.json".format(command, command)

    G = []
    # generate first: gap report -> procurement manifest.
    G.append(gate("asset-gap-report", "Asset gap report", "assets",
                  FailureCode.ASSET_NEED_ANALYSIS_FAILURE, "analyze_asset_gaps.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("analyze_asset_gaps")))
    G.append(gate("asset-procurement-manifest", "Asset procurement manifest", "assets",
                  FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE, "create_procurement_manifest.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("create_procurement_manifest")))
    # contract/schema validators (pack-independent, but keyed on --pack for reports).
    schema_gates = [
        ("validate-asset-need-schema", FailureCode.ASSET_NEED_SCHEMA_FAILURE, "validate_asset_need.py"),
        ("validate-asset-procurement-schema", FailureCode.ASSET_PROCUREMENT_MANIFEST_FAILURE, "validate_asset_procurement.py"),
        ("validate-asset-candidate-schema", FailureCode.ASSET_CANDIDATE_SCHEMA_FAILURE, "validate_asset_candidate.py"),
        ("validate-asset-approval-schema", FailureCode.ASSET_APPROVAL_STATE_FAILURE, "validate_asset_approval.py"),
        ("validate-asset-quarantine-schema", FailureCode.ASSET_QUARANTINE_SCHEMA_FAILURE, "validate_asset_quarantine_schema.py"),
        ("validate-asset-catalog-schema", FailureCode.ASSET_CATALOG_FAILURE, "validate_asset_catalog_schema.py"),
        ("validate-v1-5-taxonomy", FailureCode.V1_5_TAXONOMY_FAILURE, "validate_v1_5_taxonomy.py"),
    ]
    for gid, code, script in schema_gates:
        command = script.replace(".py", "")
        G.append(gate(gid, gid.replace("-", " ").title(), "assets", code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr(command)))
    # policy + intake validators.
    intake_gates = [
        ("validate-source-adapters", FailureCode.ASSET_SOURCE_ADAPTER_FAILURE, "validate_source_adapters.py"),
        ("asset-quarantine-validators", FailureCode.ASSET_QUARANTINE_FAILURE, "validate_asset_quarantine.py"),
        ("validate-asset-licenses", FailureCode.ASSET_LICENSE_MISSING, "validate_asset_licenses.py"),
        ("validate-asset-provenance", FailureCode.ASSET_PROVENANCE_MISSING, "validate_asset_provenance.py"),
        ("validate-asset-hashes", FailureCode.ASSET_HASH_MISMATCH, "validate_asset_hashes.py"),
        ("asset-catalog-validators", FailureCode.ASSET_CATALOG_FAILURE, "validate_asset_catalog.py"),
        ("validate-asset-package-policy", FailureCode.ASSET_PACKAGE_POLICY_FAILURE, "validate_asset_package_policy.py"),
    ]
    for gid, code, script in intake_gates:
        command = script.replace(".py", "")
        G.append(gate(gid, gid.replace("-", " ").title(), "assets", code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr(command)))
    # negatives + report integrity.
    G.append(gate("asset-acquisition-negative-validators", "Asset acquisition negatives", "assets",
                  FailureCode.ASSET_NEGATIVE_FIXTURE_FAILURE, "test_negative_assets.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    G.append(gate("asset-source-torture", "Asset source torture", "assets",
                  FailureCode.ASSET_QUARANTINE_BYPASS, "asset_source_torture.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), torture_only=True))
    G.append(gate("asset-report-integrity", "Asset report integrity", "assets",
                  FailureCode.V1_5_REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c), "--assets"] + _s(c["strict"])))
    return G


def build_realizationforge_gates():
    """v1.5 AssetRealizationForge gates. Spliced when MATERIALIZE=1. Generated-
    owned baseline cover meshes -> import approved third-party -> hybrid cube→real
    replacement -> validate materialization/dependencies/cover semantics. The
    headless resolvers here write plans/bindings + read the UE-driver reports; the
    live editor import/spawn runs via tools/unreal drivers. Until a SCRIPT exists a
    gate registers as blocking (status=missing)."""
    id_arg = lambda c: c["pack_id"]

    def rr(command):
        return lambda c: "procedural/reports/realization/{}/{}_report.json".format(command, command)

    G = []
    # generate: guaranteed generated-owned baseline cover per family (hybrid rule).
    G.append(gate("generate-owned-cover-meshes", "Generate owned cover meshes", "realization",
                  FailureCode.COVER_BASELINE_MISSING, "generate_owned_cover_meshes.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("generate_owned_cover_meshes")))
    G.append(gate("asset-materialize-ue", "Materialize approved assets in UE", "realization",
                  FailureCode.ASSET_UE_MATERIALIZATION_FAILURE, "materialize_assets.py",
                  lambda c: ["--pack", id_arg(c), "--approved-only"] + _s(c["strict"]),
                  report=rr("materialize_assets")))
    G.append(gate("visual-cover-replacement", "Replace cover proxies", "realization",
                  FailureCode.COVER_PROXY_REPLACEMENT_FAILURE, "replace_cover_proxies.py",
                  lambda c: ["--pack", id_arg(c), "--approved-only"] + _s(c["strict"]),
                  report=rr("replace_cover_proxies")))
    real_gates = [
        ("validate-cover-binding-schema", FailureCode.COVER_BINDING_SCHEMA_FAILURE, "validate_cover_binding.py"),
        ("validate-ue-materialization", FailureCode.ASSET_UE_MATERIALIZATION_FAILURE, "validate_ue_materialization.py"),
        ("validate-asset-dependencies", FailureCode.ASSET_DEPENDENCY_FAILURE, "validate_asset_dependencies.py"),
        ("validate-cover-real-meshes", FailureCode.COVER_PROXY_REPLACEMENT_FAILURE, "validate_cover_replacement.py"),
    ]
    for gid, code, script in real_gates:
        command = script.replace(".py", "")
        G.append(gate(gid, gid.replace("-", " ").title(), "realization", code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr(command)))
    G.append(gate("realization-report-integrity", "Realization report integrity", "realization",
                  FailureCode.V1_5_REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c), "--materialize"] + _s(c["strict"])))
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


def pack_declares_encounterforge(pack):
    """True if a pack yaml declares EncounterForge (``encounterforge: true``)."""
    import yaml as _yaml
    from world_pack_maps import resolve_world_pack_path
    try:
        wp_path = resolve_world_pack_path(pack)
        if not wp_path.is_file():
            return False
        data = _yaml.safe_load(wp_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return bool(data.get("encounterforge"))


def build_encounterforge_gates(playtest_beta_on, balance_on):
    """v1.4 EncounterForge + PlaytestForge Beta + BalanceForge Alpha gates.

    An encounterforge pack (encounter_loop_world) layers encounters over the 60
    missions of its source pack, so this is an encounter-FOCUSED gate set.
    Playtest-beta gates run under PLAYTEST=beta; balance gates under BALANCE=1.
    Until a validator SCRIPT exists it registers as blocking (status=missing)."""
    id_arg = lambda c: c["pack_id"]

    def rr(command):
        return lambda c: "procedural/reports/encounters/{}/{}_report.json".format(command, command)

    G = []
    G.append(gate("create-encounter-pack", "Create encounter pack", "encounter",
                  FailureCode.ENCOUNTER_CONTRACT_FAILURE, "create_encounter_pack.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("create_encounter_pack")))
    G.append(gate("create-encounters", "Create encounters", "encounter",
                  FailureCode.ENCOUNTER_CONTRACT_FAILURE, "create_encounters.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=rr("create_encounters")))
    encounter_gates = [
        ("validate-encounter-contract", FailureCode.ENCOUNTER_CONTRACT_FAILURE, "validate_encounter_contract.py"),
        ("validate-encounter-archetypes", FailureCode.ENCOUNTER_ARCHETYPE_FAILURE, "validate_encounter_archetypes.py"),
        ("validate-spawn-groups", FailureCode.ENCOUNTER_SPAWN_GROUP_FAILURE, "validate_spawn_groups.py"),
        ("validate-encounter-anchors", FailureCode.ENCOUNTER_ANCHOR_FAILURE, "validate_encounter_anchors.py"),
        ("validate-encounter-routes", FailureCode.ENCOUNTER_ROUTE_FAILURE, "validate_encounter_routes.py"),
        ("validate-encounter-pressure", FailureCode.ENCOUNTER_PRESSURE_FAILURE, "validate_encounter_pressure.py"),
        ("validate-encounter-pacing", FailureCode.ENCOUNTER_PACING_FAILURE, "validate_encounter_pacing.py"),
        ("validate-encounter-biome-compatibility", FailureCode.ENCOUNTER_BIOME_COMPATIBILITY_FAILURE, "validate_encounter_biome_compatibility.py"),
        ("validate-encounter-mission-compatibility", FailureCode.ENCOUNTER_MISSION_COMPATIBILITY_FAILURE, "validate_encounter_mission_compatibility.py"),
        ("validate-encounter-mesh-dependencies", FailureCode.ENCOUNTER_MESH_DEPENDENCY_FAILURE, "validate_encounter_mesh_dependencies.py"),
        ("validate-encounter-cover", FailureCode.ENCOUNTER_MESH_DEPENDENCY_FAILURE, "validate_encounter_cover.py"),
        ("validate-encounter-hazards", FailureCode.ENCOUNTER_BIOME_COMPATIBILITY_FAILURE, "validate_encounter_hazards.py"),
        ("validate-encounter-resources", FailureCode.ENCOUNTER_REWARD_FAILURE, "validate_encounter_resources.py"),
        ("validate-encounter-state", FailureCode.ENCOUNTER_STATE_FAILURE, "validate_encounter_state.py"),
        ("validate-encounter-save-load", FailureCode.ENCOUNTER_SAVE_LOAD_FAILURE, "validate_encounter_save_load.py"),
        ("validate-encounter-rewards", FailureCode.ENCOUNTER_REWARD_FAILURE, "validate_encounter_rewards.py"),
    ]
    for gid, code, script in encounter_gates:
        command = script.replace(".py", "")
        G.append(gate(gid, gid.replace("-", " ").title(), "encounter", code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), report=rr(command)))
    if playtest_beta_on:
        G.append(gate("validate-playtest-beta-contract", "Validate playtest beta contract",
                      "playtest_beta", FailureCode.PLAYTEST_BETA_CONTRACT_FAILURE,
                      "validate_playtest_beta_contract.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr("validate_playtest_beta_contract")))
        G.append(gate("run-playtest-forge-beta", "Run PlaytestForge Beta", "playtest_beta",
                      FailureCode.PLAYTEST_BETA_COMPLETION_FAILURE, "run_playtest_forge_beta.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr("run_playtest_forge_beta")))
        G.append(gate("validate-playtest-beta-reports", "Validate playtest beta reports",
                      "playtest_beta", FailureCode.PLAYTEST_BETA_REPORT_FAILURE,
                      "validate_playtest_beta_reports.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr("validate_playtest_beta_reports")))
    if balance_on:
        G.append(gate("validate-balance-contract", "Validate balance contract", "balance",
                      FailureCode.BALANCE_CONTRACT_FAILURE, "validate_balance_contract.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr("validate_balance_contract")))
        G.append(gate("run-balance-forge", "Run BalanceForge", "balance",
                      FailureCode.ENCOUNTER_BALANCE_FAILURE, "run_balance_forge.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr("run_balance_forge")))
        G.append(gate("validate-balance-reports", "Validate balance reports", "balance",
                      FailureCode.BALANCE_REPORT_FAILURE, "validate_balance_reports.py",
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=rr("validate_balance_reports")))
    # encounter negative + fuzz + torture + report integrity.
    G.append(gate("encounter-negative-validators", "Encounter negative validators", "encounter",
                  FailureCode.ENCOUNTER_CONTRACT_FAILURE, "test_negative_encounter.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    G.append(gate("fuzz-encounter-matrix", "Fuzz encounter matrix", "encounter",
                  FailureCode.ENCOUNTER_CONTRACT_FAILURE, "fuzz_encounter_matrix.py",
                  lambda c: ["--pack", id_arg(c), "--cases", str(c["cases"])] + _s(c["strict"])))
    G.append(gate("encounter-lifecycle-torture", "Encounter lifecycle torture", "encounter",
                  FailureCode.ENCOUNTER_LIFECYCLE_FAILURE, "encounter_lifecycle_torture.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]), torture_only=True))
    G.append(gate("encounter-report-integrity", "Encounter report integrity", "encounter",
                  FailureCode.REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c), "--encounters"] + _s(c["strict"])))
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
    ap.add_argument("--visuals", action="store_true",
                    help="Include v1.3.5 VisualFidelity gates (also via VISUALS=1).")
    ap.add_argument("--encounters", action="store_true",
                    help="Include v1.4 EncounterForge gates (also via ENCOUNTERS=1).")
    ap.add_argument("--playtest-beta", action="store_true",
                    help="Include v1.4 PlaytestForge Beta gates (also via PLAYTEST=beta).")
    ap.add_argument("--balance", action="store_true",
                    help="Include v1.4 BalanceForge Alpha gates (also via BALANCE=1).")
    ap.add_argument("--assets", action="store_true",
                    help="Include v1.5 AssetAcquisitionForge gates (also via ASSETS=1).")
    ap.add_argument("--materialize", action="store_true",
                    help="Include v1.5 AssetRealizationForge gates (also via MATERIALIZE=1).")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--no-build", action="store_true",
                    help="Skip the heavy create-world-pack rebuild gate (validation-only run).")
    ap.add_argument("--only", default=None, help="Run only gates whose id contains this substring")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    deep = args.deep or flag_from_env("DEEP")
    torture = args.torture or flag_from_env("TORTURE")

    missionforge = pack_declares_missionforge(args.pack)
    encounterforge = pack_declares_encounterforge(args.pack)
    missions_on = args.missions or flag_from_env("MISSIONS") or missionforge
    encounters_on = args.encounters or flag_from_env("ENCOUNTERS") or encounterforge
    # PLAYTEST=beta is a mode value, not a boolean flag (cf. HOUDINI=metadata_only).
    playtest_beta_on = args.playtest_beta or (
        os.environ.get("PLAYTEST", "").strip().lower() == "beta")
    # Beta layers on Alpha: PLAYTEST=beta keeps the v1.3 alpha playtest gates on.
    playtest_on = args.playtest or flag_from_env("PLAYTEST") or playtest_beta_on
    balance_on = args.balance or flag_from_env("BALANCE")
    # v1.5 lane flags. VISUAL is accepted as an alias for VISUALS (the v1.5 shield
    # target spells it VISUAL=1); assets/materialize are net-new.
    assets_on = args.assets or flag_from_env("ASSETS")
    materialize_on = args.materialize or flag_from_env("MATERIALIZE")

    # Resolve world_pack_id from the pack yaml. A missionforge/encounterforge pack
    # layers over a source pack and owns no maps of its own, so enumerate_maps is
    # bypassed.
    from world_pack_maps import enumerate_maps
    if missionforge or encounterforge:
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

    # v1.4 — an encounterforge pack runs an encounter-FOCUSED shield: encounter +
    # playtest-beta + balance gates layered over the mission gate block (MISSIONS=1
    # keeps the 60-mission substrate proven inside the same shield), plus optional
    # visual/mesh/megascans gates. The 33 world-gen gates belong to the source
    # packs, exercised by the regression gates.
    if encounterforge:
        import houdini_contract  # noqa: E402
        ctx["biomeforge"] = False
        ctx["meshes"] = args.meshes or flag_from_env("MESHES")
        ctx["houdini_mode"] = houdini_contract.houdini_mode_from_env()
        ctx["megascans"] = flag_from_env("MEGASCANS")
        ctx["visuals"] = args.visuals or flag_from_env("VISUALS") or flag_from_env("VISUAL")
        registry = build_encounterforge_gates(playtest_beta_on, balance_on)
        if missions_on:
            registry = build_missionforge_gates(playtest_on) + registry
        if ctx["visuals"]:
            registry = registry + build_visualforge_gates(include_v1_5_kits=materialize_on)
        # v1.5 — acquisition substrate before realization (realization consumes the
        # approved catalog), both after the encounter/mission/visual gates.
        if assets_on:
            registry = registry + build_assetforge_gates()
        if materialize_on:
            registry = registry + build_realizationforge_gates()
        if ctx["meshes"]:
            registry = (build_meshforge_gates()
                        + build_source_gates(ctx["houdini_mode"], ctx["megascans"])
                        + registry)
        print("EncounterForge pack — %d gate(s) active (missions=%s, playtest=%s, "
              "playtest_beta=%s, balance=%s, visuals=%s, assets=%s, materialize=%s, "
              "meshes=%s, megascans=%s)." % (
                  len(registry), bool(missions_on), bool(playtest_on),
                  bool(playtest_beta_on), bool(balance_on), bool(ctx["visuals"]),
                  bool(assets_on), bool(materialize_on),
                  bool(ctx["meshes"]), bool(ctx["megascans"])))
    # v1.3 — a missionforge pack runs a mission-FOCUSED shield (missions +
    # playtest + optional mesh/megascans gates), NOT the 33 world-gen gates
    # (those belong to its source pack, exercised by the regression gate).
    elif missionforge:
        import houdini_contract  # noqa: E402
        ctx["biomeforge"] = False
        ctx["meshes"] = args.meshes or flag_from_env("MESHES")
        ctx["houdini_mode"] = houdini_contract.houdini_mode_from_env()
        ctx["megascans"] = flag_from_env("MEGASCANS")
        ctx["visuals"] = args.visuals or flag_from_env("VISUALS") or flag_from_env("VISUAL")
        registry = build_missionforge_gates(playtest_on)
        if ctx["visuals"]:
            registry = registry + build_visualforge_gates(include_v1_5_kits=materialize_on)
        if assets_on:
            registry = registry + build_assetforge_gates()
        if materialize_on:
            registry = registry + build_realizationforge_gates()
        if ctx["meshes"]:
            registry = (build_meshforge_gates()
                        + build_source_gates(ctx["houdini_mode"], ctx["megascans"])
                        + registry)
        print("MissionForge pack — %d gate(s) active (playtest=%s, visuals=%s, assets=%s, materialize=%s, meshes=%s, megascans=%s)." % (
            len(registry), bool(playtest_on), bool(ctx["visuals"]), bool(assets_on),
            bool(materialize_on), bool(ctx["meshes"]), bool(ctx["megascans"])))
    else:
        registry = build_registry()

    # v1.1 — splice in BiomeForge gates for biome packs only. desert_mvp_world
    # does not declare biomes, so its 33-gate v1.0x contract is unchanged.
    # A missionforge pack lists biome_families for context but is NOT a biome
    # world pack, so it skips the biome/mesh splice blocks entirely.
    ctx["biomeforge"] = (not (missionforge or encounterforge)) and pack_declares_biomes(args.pack)
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
    ctx["meshes"] = (not (missionforge or encounterforge)) and (args.meshes or flag_from_env("MESHES"))
    # v1.2 addendum — Houdini/Megascans source flags. HOUDINI may be '1'/'live'
    # or 'metadata_only'; MEGASCANS is a plain flag.
    import houdini_contract  # noqa: E402
    if not (missionforge or encounterforge):
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
