# UE5 Procedural Pipeline Makefile

PYTHON := python
UE_PYTHON := python

# v0.9 — export STRICT so it reaches subprocesses (incl. UE-side validators that
# resolve it via strict_from_env(); there is no reliable argv in -ExecutePythonScript).
export STRICT
# v1.2 addendum — export the source flags so full_shield's gate subprocesses and
# the source validators resolve them from the environment.
export HOUDINI
export MEGASCANS
export MESHES
# v1.3 — export mission/playtest flags to full_shield gate subprocesses.
export MISSIONS
export PLAYTEST

.PHONY: help validate-recipe render-substance generate-manifest placeholder-exports \
        import-textures create-master create-world-state-mpc wire-terrain-soot create-material create-data-asset \
        validate-assets diagnose pre-ue-audit validate-and-manifest preview build clean \
        validate-placement generate-placement-manifest create-placement-data-asset \
        validate-placement-assets placement-build biome-slice \
        prepare-material render-desert-variants \
        prepare-biome-slice render-biome-slice render-desert-pack \
        create-slice-spec prepare-slice create-slice-map validate-slice create-slice \
        create-slice-pack validate-slice-pack destroy-slice rebuild-slice \
        validate-asset-catalog validate-placement-preset validate-state-preset validate-budget \
        generate-placement-da update-slice-placement \
        repair-slice list-orphans clean-orphans \
        compare-slice-determinism \
        create-world-pack validate-world-pack validate-world-pack-spec \
        run-world-state-scenario inspect-world-pack validate-inspection \
        ue-doctor \
        create-terrain validate-terrain import-terrain \
        create-poi validate-poi \
        run-state-sim validate-runtime-state apply-state-scenario \
        register-generated-asset validate-generated-asset relocate-houdini-asset \
        worldforge-doctor audit-generated-content package-check \
        repair-world-pack destroy-world-pack \
        full-shield revalidate-world-pack validate-report-integrity test-negative-validators \
        validate-environment-contract \
        validate-sky validate-lighting validate-fog validate-atmosphere \
        generate-level-design validate-pois validate-level-design validate-reachability validate-poi-graph \
        generate-entity-anchors validate-entity-anchors validate-npc-spawns validate-encounter-readiness \
        validate-rendering-profiles validate-scalability validate-raytracing validate-performance-budgets \
        corrupt-world-pack lifecycle-torture seed-matrix fuzz-world-pack validate-determinism validate-regression-matrix \
        inspect-pack inspect-map diagnose-world-pack diff-world-pack \
        validate-biome-contract validate-biome-matrix validate-biome-profile-bindings \
        validate-biome-environment-compatibility validate-biome-inspection \
        validate-terrain-forms validate-material-families validate-vegetation-profiles validate-placement-profiles \
        validate-biome-poi-compatibility validate-biome-traversal validate-biome-ecology-tags \
        fuzz-biome-matrix \
        create-mesh-assets validate-mesh-contract validate-mesh-catalog validate-mesh-provenance \
        validate-mesh-final-paths validate-mesh-material-bindings validate-mesh-collision-bounds \
        validate-mesh-pcg-eligibility validate-mesh-biome-compatibility validate-mesh-rendering-budgets \
        validate-mesh-package mesh-negative-validators mesh-lifecycle-torture \
        inspect-mesh-catalog inspect-mesh-asset diagnose-mesh-catalog diff-mesh-catalog \
        validate-houdini-intake validate-houdini-cook-reports validate-houdini-bake-reports \
        validate-houdini-generated-assets inspect-houdini-intake diagnose-houdini-intake \
        scan-external-asset-library validate-external-asset-catalog validate-megascans-catalog \
        validate-megascans-bindings validate-megascans-pcg-eligibility validate-megascans-biome-compatibility \
        validate-external-asset-ownership validate-third-party-package-policy validate-source-ownership-separation \
        inspect-external-asset-library inspect-external-asset diagnose-external-asset-library \
        create-mission-loops validate-mission-contract validate-mission-graph validate-mission-placement \
        validate-mission-biome-compatibility validate-mission-routes validate-mission-objectives \
        validate-mission-state validate-mission-save-load validate-mission-rewards \
        validate-mission-dependencies validate-mission-mesh-usage validate-mission-entity-anchors \
        validate-playtest-contract run-playtest-forge validate-playtest-reports \
        mission-negative-validators fuzz-mission-matrix mission-lifecycle-torture \
        inspect-mission-pack diagnose-mission-pack

help:
	@echo "UE5 Procedural Pipeline - Available targets:"
	@echo ""
	@echo "Non-UE authoring steps:"
	@echo "  make validate-recipe RECIPE=terrain_rock_desert_01"
	@echo "  make render-substance RECIPE=terrain_rock_desert_01"
	@echo "  make generate-manifest RECIPE=terrain_rock_desert_01"
	@echo "  make placeholder-exports RECIPE=terrain_rock_desert_01  # solid PNGs for testing w/o Substance"
	@echo "  make pre-ue-audit"
	@echo "  make validate-and-manifest RECIPE=terrain_rock_desert_01"
	@echo ""
	@echo "UE-side steps (run inside UE Python):"
	@echo "  make import-textures RECIPE=terrain_rock_desert_01"
	@echo "  make create-master RECIPE=terrain_rock_desert_01    # one-time per master"
	@echo "  make create-world-state-mpc                         # one-time: MPC_WorldState render mirror"
	@echo "  make wire-terrain-soot                              # one-time: M_Terrain_Master soot reaction (Tier-2)"
	@echo "  make create-material RECIPE=terrain_rock_desert_01"
	@echo "  make create-data-asset RECIPE=terrain_rock_desert_01  # provenance + linkage record"
	@echo "  make validate-assets RECIPE=terrain_rock_desert_01"
	@echo "  make diagnose RECIPE=terrain_rock_desert_01"
	@echo ""
	@echo ""
	@echo "PlacementForge (FoliageSpawnRules -> PCG-read PlacementRulesDataAsset):"
	@echo "  make validate-placement DEF=reclaimed_desert_foliage"
	@echo "  make generate-placement-manifest DEF=reclaimed_desert_foliage"
	@echo "  make create-placement-data-asset DEF=reclaimed_desert_foliage  # UE-side"
	@echo "  make validate-placement-assets DEF=reclaimed_desert_foliage    # UE-side"
	@echo "  make placement-build DEF=reclaimed_desert_foliage              # authoring-side"
	@echo ""
	@echo "Biome slice (THE one-command before/after proof; configs in procedural/slices/):"
	@echo "  make biome-slice BIOME=desert VARIANT=industrialized      # 0.00 -> 0.75 (reference)"
	@echo "  make biome-slice BIOME=desert VARIANT=light_industrial    # 0.00 -> 0.35"
	@echo "  make biome-slice BIOME=desert VARIANT=ruined_industrial   # 0.00 -> 1.00"
	@echo "  make biome-slice BIOME=desert VARIANT=industrialized RENDER=0  # authoring + spec only"
	@echo ""
	@echo "Batch orchestration (no per-variant hand-typing):"
	@echo "  make prepare-biome-slice BIOME=desert VARIANT=sandy  # authoring prep only (validate+manifest each recipe)"
	@echo "  make render-biome-slice BIOME=desert VARIANT=sandy   # prepare-biome-slice THEN biome-slice (render)"
	@echo "  make render-desert-pack                              # render EVERY desert variant back to back + pack score"
	@echo ""
	@echo "Convenience batches:"
	@echo "  make prepare-material RECIPE=terrain_sand_desert_01   # UE-side: import+MI+DA+validate (needs UE python)"
	@echo "  make render-desert-variants                          # render desert_sandy + desert_ash (assets must exist)"
	@echo ""
	@echo "Slice factory (create a NEW named, state-aware UE slice from a preset):"
	@echo "  make create-slice BIOME=desert VARIANT=ash NAME=Desert_Outpost_01   # spec->prepare->map->validate"
	@echo "  make create-slice-spec BIOME=desert VARIANT=ash NAME=Desert_Outpost_01  # just emit the generated spec"
	@echo "  make prepare-slice SPEC=procedural/slices/desert/generated/Desert_Outpost_01.json"
	@echo "  make create-slice-map SPEC=...   # headless UE: build + save the map"
	@echo "  make validate-slice SPEC=...     # headless UE: assert the slice is wired"
	@echo "  make create-slice-pack PACK=desert_foundation JOBS=4  # batch create all slices in a pack"
	@echo "  make validate-slice-pack PACK=desert_foundation        # aggregate validate reports for pack"
	@echo "  make destroy-slice NAME=Desert_Ash_Outpost_01          # delete owned generated assets"
	@echo "  make rebuild-slice BIOME=desert VARIANT=ash NAME=Desert_Ash_Outpost_01  # destroy + create"
	@echo ""
	@echo "TerrainForge Lite (v0.6 — deterministic terrain from data):"
	@echo "  make create-terrain RECIPE=ash_flats NAME=Terrain_AshFlats_01"
	@echo "  make validate-terrain NAME=Terrain_AshFlats_01"
	@echo "  make import-terrain NAME=Terrain_AshFlats_01    # UE-side import (requires editor)"
	@echo "  make create-slice BIOME=desert TERRAIN=ash_flats VARIANT=ash PLACEMENT=dead_scrub STATE=industrialized NAME=Desert_AshFlats_Industrialized_01"
	@echo ""
	@echo "Runtime StateForge (v0.8 — make generated worlds react and remember):"
	@echo "  make run-state-sim NAME=Desert_Ash_IndustrialYard_01 SCENARIO=activate_industrial_forge"
	@echo "  make validate-runtime-state NAME=Desert_Ash_IndustrialYard_01"
	@echo "  make apply-state-scenario NAME=Desert_Ash_IndustrialYard_01 SCENARIO=activate_industrial_forge  # UE-side"
	@echo ""
	@echo "Houdini generated-asset intake (v0.8 sidecar — one owned StaticMesh, NOT MeshForge):"
	@echo "  make register-generated-asset ASSET=rock_generator_desert_01"
	@echo "  make validate-generated-asset ASSET=rock_generator_desert_01"
	@echo "  make relocate-houdini-asset ASSET=rock_generator_desert_01   # UE-side: bake -> WorldForge-owned"
	@echo ""
	@echo "Production Hardening (v0.9 — health, audit, packaging, lifecycle; STRICT=1 escalates WARN->blocking):"
	@echo "  make worldforge-doctor                                  # local factory health (read-only)"
	@echo "  make audit-generated-content                            # repo-wide ownership/provenance/path audit (read-only)"
	@echo "  make package-check PACK=desert_production_seed          # world-pack ship-readiness gate (read-only)"
	@echo "  make repair-world-pack PACK=desert_poi_lite_seed        # diagnose; APPLY=1 re-derives, APPLY=1 UE=1 runs editor repair"
	@echo "  make destroy-world-pack PACK=desert_poi_lite_seed       # dry-run; CONFIRM=1 deletes registry-owned generated assets"
	@echo ""
	@echo "Other:"
	@echo "  make preview     # Always fails until preview generation exists"
	@echo "  make build RECIPE=...   # Authoring-side steps only"

# Non-UE targets
validate-recipe:
	$(PYTHON) tools/substance/validate_recipe.py --recipe $(RECIPE)

render-substance:
	$(PYTHON) tools/substance/render_with_sbsrender.py --recipe $(RECIPE)

generate-manifest:
	$(PYTHON) tools/pipeline/generate_manifest.py --recipe $(RECIPE)

placeholder-exports:
	$(PYTHON) tools/substance/make_placeholder_exports.py --recipe $(RECIPE)

pre-ue-audit:
	@echo "=== Pre-UE Audit ==="
	python -m py_compile $$(find tools -name "*.py")
	grep -R "import yaml" tools/unreal/ || echo "✓ No import yaml in UE scripts"
	grep -R "yaml.safe_load" tools/unreal/ || echo "✓ No yaml.safe_load in UE scripts"

validate-and-manifest: validate-recipe generate-manifest
	@echo "✓ Recipe validated and manifest generated"

# UE-side targets
import-textures:
	$(UE_PYTHON) tools/unreal/import_textures.py --manifest procedural/manifests/materials/$(RECIPE).json --project-root .

create-master:
	$(UE_PYTHON) tools/unreal/create_master_material.py --manifest procedural/manifests/materials/$(RECIPE).json --project-root .

create-world-state-mpc:
	$(UE_PYTHON) tools/unreal/create_world_state_mpc.py --project-root .

wire-terrain-soot:
	$(UE_PYTHON) tools/unreal/wire_terrain_soot.py --project-root .

create-material:
	$(UE_PYTHON) tools/unreal/create_material_instances.py --manifest procedural/manifests/materials/$(RECIPE).json --project-root .

create-data-asset:
	$(UE_PYTHON) tools/unreal/create_data_asset.py --manifest procedural/manifests/materials/$(RECIPE).json --project-root .

validate-assets:
	$(UE_PYTHON) tools/unreal/validate_assets.py --manifest procedural/manifests/materials/$(RECIPE).json --project-root .

diagnose:
	@echo "Run inside UE5 Python Console:"
	@echo "import diagnose_material_lane"
	@echo "diagnose_material_lane.run_diagnostics('$(RECIPE)')"

# PlacementForge targets (FoliageSpawnRules -> PlacementRulesDataAsset, D13)
validate-placement:
	$(PYTHON) tools/pipeline/validate_placement.py --definition $(DEF)

generate-placement-manifest:
	$(PYTHON) tools/pipeline/generate_placement_manifest.py --definition $(DEF)

create-placement-data-asset:
	$(UE_PYTHON) tools/unreal/create_placement_data_asset.py --manifest procedural/manifests/placement/$(DEF).json --project-root .

validate-placement-assets:
	$(UE_PYTHON) tools/unreal/validate_placement_assets.py --manifest procedural/manifests/placement/$(DEF).json --project-root .

placement-build:
	@echo "Authoring-side placement build for $(DEF)..."
	$(MAKE) validate-placement DEF=$(DEF)
	$(MAKE) generate-placement-manifest DEF=$(DEF)
	@echo ""
	@echo "Next steps (run inside UE Python):"
	@echo "  make create-placement-data-asset DEF=$(DEF)"
	@echo "  make validate-placement-assets DEF=$(DEF)"

# One-command biome slice: authoring chain -> headless render -> acceptance score.
# RENDER=0 stops before the headless UE launch (authoring + JSON spec only).
biome-slice:
	$(PYTHON) tools/pipeline/biome_slice.py --biome $(BIOME) --variant $(VARIANT) $(if $(filter 0,$(RENDER)),--no-render,)

# Authoring-side prep for one variant: validate + manifest every recipe in the
# slice. No headless UE launch (UE-side import/create steps are out of scope).
prepare-biome-slice:
	$(PYTHON) tools/pipeline/prepare_biome_slice.py --biome $(BIOME) --variant $(VARIANT)

# Prepare (authoring) THEN render: the full single-variant chain in one command.
render-biome-slice:
	$(MAKE) prepare-biome-slice BIOME=$(BIOME) VARIANT=$(VARIANT)
	$(MAKE) biome-slice BIOME=$(BIOME) VARIANT=$(VARIANT)

# Generic UE-side material prep: one recipe -> textures + MI + DataAsset + validate.
# UE-side steps `import unreal`, so UE_PYTHON must point at the editor's Python
# (or run these from inside the editor). biome-slice is the headless render path.
prepare-material:
	$(MAKE) import-textures RECIPE=$(RECIPE)
	$(MAKE) create-material RECIPE=$(RECIPE)
	$(MAKE) create-data-asset RECIPE=$(RECIPE)
	$(MAKE) validate-assets RECIPE=$(RECIPE)

# Dumb batch: render both new desert presets back to back. The terrain MIs /
# DataAssets must already exist (see prepare-material). Leaves the golden
# desert_industrialized baseline untouched.
render-desert-variants:
	$(MAKE) biome-slice BIOME=desert VARIANT=sandy
	$(MAKE) biome-slice BIOME=desert VARIANT=ash

# One-command pack render: render EVERY desert variant back to back (continues
# past a failing variant), then run pack_score.py if another agent has created
# it. render_pack.py exits non-zero if any variant failed; the guarded scorer
# line tolerates pack_score.py's absence.
render-desert-pack:
	$(PYTHON) tools/pipeline/render_pack.py --biome desert
	@[ -f tools/pipeline/pack_score.py ] && $(PYTHON) tools/pipeline/pack_score.py || echo "[render-desert-pack] pack_score.py not present yet; skipping rich score."

# Slice factory: create a NEW named, state-aware UE slice from a biome/variant preset.
# create-slice chains: emit generated spec -> prepare assets -> build+save UE map -> validate.
SLICE_SPEC = procedural/slices/$(BIOME)/generated/$(NAME).json

# Optional composition args for create-slice / create-slice-pack
PLACEMENT    ?=
STATE_PRESET ?=
DEEP         ?=
CONFIRM      ?=
CATALOG      ?= desert_asset_catalog
PRESET       ?= industrial_debris
STATE        ?= industrialized
BUDGET       ?= procedural/definitions/budgets/desert_default.yaml
TERRAIN      ?=
POI_TYPE     ?=
POI          ?=
SCENARIO     ?= activate_industrial_forge
ASSET        ?= rock_generator_desert_01

create-slice-spec:
	$(PYTHON) tools/pipeline/create_slice_spec.py --biome $(BIOME) --variant $(VARIANT) --name $(NAME) \
	  $(if $(PLACEMENT),--placement $(PLACEMENT),) \
	  $(if $(STATE_PRESET),--state-preset $(STATE_PRESET),) \
	  $(if $(TERRAIN),--terrain $(TERRAIN),) \
	  $(if $(POI),--poi $(POI),)

prepare-slice:
	$(PYTHON) tools/pipeline/prepare_slice.py --spec $(SPEC)

create-slice-map:
	$(PYTHON) tools/pipeline/run_slice_ue.py --script create_slice_map.py --spec $(SPEC)

validate-slice:
	$(PYTHON) tools/pipeline/run_slice_ue.py --script validate_slice.py --spec $(SPEC) \
	  $(if $(DEEP),--deep,)

create-slice:
	$(MAKE) create-slice-spec BIOME=$(BIOME) VARIANT=$(VARIANT) NAME=$(NAME) \
	  PLACEMENT=$(PLACEMENT) STATE_PRESET=$(STATE_PRESET) TERRAIN=$(TERRAIN) POI=$(POI)
	$(MAKE) prepare-slice SPEC=$(SLICE_SPEC)
	$(MAKE) create-slice-map SPEC=$(SLICE_SPEC)
	$(PYTHON) tools/pipeline/generate_placement_da.py --spec $(SLICE_SPEC)
	$(MAKE) validate-slice SPEC=$(SLICE_SPEC)

PACK     ?= desert_foundation
JOBS     ?= 1

create-slice-pack:
	$(PYTHON) tools/pipeline/create_slice_pack.py --pack procedural/slice_packs/$(PACK).yaml --jobs $(JOBS)

validate-slice-pack:
	$(PYTHON) tools/pipeline/validate_slice_pack.py --pack procedural/slice_packs/$(PACK).yaml \
	  $(if $(DEEP),--deep,) $(if $(STRICT),--strict,)

destroy-slice:
	$(PYTHON) tools/pipeline/destroy_slice.py --name $(NAME)

rebuild-slice:
	$(MAKE) destroy-slice NAME=$(NAME)
	$(MAKE) create-slice BIOME=$(BIOME) VARIANT=$(VARIANT) NAME=$(NAME) \
	  PLACEMENT=$(PLACEMENT) STATE_PRESET=$(STATE_PRESET)

# v0.5 — definition validators
validate-asset-catalog:
	$(PYTHON) tools/pipeline/validate_asset_catalog.py --catalog procedural/definitions/assets/$(CATALOG).yaml

validate-placement-preset:
	$(PYTHON) tools/pipeline/validate_placement_preset.py --preset procedural/definitions/placement/$(BIOME)/$(PRESET).yaml

validate-state-preset:
	$(PYTHON) tools/pipeline/validate_state_preset.py --preset procedural/definitions/state/$(BIOME)/$(STATE).yaml

validate-budget:
	$(PYTHON) tools/pipeline/validate_budget.py --budget $(BUDGET)

# v0.5 — per-slice placement DA
generate-placement-da:
	$(PYTHON) tools/pipeline/generate_placement_da.py --spec $(SPEC)

update-slice-placement:
	$(PYTHON) tools/pipeline/run_ue_update_placement.py --spec $(SPEC)

# v0.5 — repair / orphan lifecycle
repair-slice:
	$(PYTHON) tools/pipeline/run_ue_repair.py --name $(NAME)

list-orphans:
	$(PYTHON) tools/pipeline/list_orphans.py

clean-orphans:
	$(PYTHON) tools/pipeline/clean_orphans.py $(if $(CONFIRM),--confirm,)

# v0.5 — determinism
compare-slice-determinism:
	$(PYTHON) tools/pipeline/compare_slice_determinism.py --name $(NAME)

# v0.5 — world packs
create-world-pack:
	$(PYTHON) tools/pipeline/create_world_pack.py --pack procedural/world_packs/$(PACK).yaml --jobs $(JOBS)

# v1.0 — static world-pack SPEC pre-flight (no UE, no generation). Resolves every
# referenced surface + reports MVP coverage. STRICT=1 makes coverage shortfalls block.
validate-world-pack-spec:
	$(PYTHON) tools/pipeline/validate_world_pack_spec.py --pack procedural/world_packs/$(PACK).yaml \
	  $(if $(STRICT),--strict,)

# v1.0 — run a Runtime StateForge scenario across a world pack's compatible maps.
# SCENARIO selects the scenario id; STRICT=1 threads strict into per-map validation;
# FORCE=1 reruns sims; LIMIT caps the number of maps. No UE is launched.
run-world-state-scenario:
	$(PYTHON) tools/pipeline/run_world_state_scenario.py --pack procedural/world_packs/$(PACK).yaml \
	  --scenario $(SCENARIO) $(if $(STRICT),--strict,) $(if $(FORCE),--force,) \
	  $(if $(LIMIT),--limit $(LIMIT),)

# v1.0 — playable-inspection metadata for every map in a world pack (no UE).
inspect-world-pack:
	$(PYTHON) tools/pipeline/generate_inspection_metadata.py --pack procedural/world_packs/$(PACK).yaml

# v1.0 — assert complete inspection metadata exists for every generated map.
validate-inspection:
	$(PYTHON) tools/pipeline/generate_inspection_metadata.py --pack procedural/world_packs/$(PACK).yaml \
	  --validate $(if $(STRICT),--strict,)

validate-world-pack:
	$(PYTHON) tools/pipeline/validate_world_pack.py --pack procedural/world_packs/$(PACK).yaml \
	  $(if $(DEEP),--deep,) $(if $(STRICT),--strict,)

# v0.5 — pre-flight
ue-doctor:
	$(PYTHON) tools/pipeline/ue_doctor.py

# v0.9 — local factory health check (read-only). STRICT=1 escalates soft warnings.
worldforge-doctor:
	$(PYTHON) tools/pipeline/worldforge_doctor.py $(if $(STRICT),--strict,)

# v0.9 — repo-wide generated-content ownership/provenance/path audit (read-only).
# STRICT=1 escalates soft warnings (e.g. missing provenance) to blocking.
audit-generated-content:
	$(PYTHON) tools/pipeline/audit_generated_content.py $(if $(STRICT),--strict,)

# v0.9 — world-pack package/ship readiness gate (read-only). STRICT=1 escalates warnings.
package-check:
	$(PYTHON) tools/pipeline/package_check.py --pack $(PACK) $(if $(STRICT),--strict,)

# v0.9 — world-pack lifecycle. destroy requires CONFIRM=1; repair APPLY=1 (UE=1 for map gaps).
repair-world-pack:
	$(PYTHON) tools/pipeline/repair_world_pack.py --pack $(PACK) \
	  $(if $(APPLY),--apply,) $(if $(UE),--ue,) $(if $(STRICT),--strict,)

destroy-world-pack:
	$(PYTHON) tools/pipeline/destroy_world_pack.py --pack $(PACK) \
	  $(if $(CONFIRM),--confirm,) $(if $(STRICT),--strict,)

# v0.6 — TerrainForge Lite
# Generate deterministic terrain artifacts from a terrain recipe.
#   RECIPE  terrain recipe id (procedural/definitions/terrain/<RECIPE>.yaml)
#   NAME    output terrain name (e.g. Terrain_AshFlats_01)
create-terrain:
	$(PYTHON) tools/pipeline/create_terrain.py --recipe $(RECIPE) --name $(NAME)

# Validate generated terrain artifacts (pure Python; no UE required).
validate-terrain:
	$(PYTHON) tools/pipeline/validate_terrain.py --name $(NAME) $(if $(STRICT),--strict,)

# Run UE-side terrain import (Stage C); requires editor.
import-terrain:
	$(PYTHON) tools/pipeline/run_terrain_ue.py --script import_terrain_heightmap.py --name $(NAME)

# v0.7 — POIForge Lite
# Generate a POI descriptor from a recipe.
#   POI_TYPE  poi type / recipe id (procedural/definitions/poi/<POI_TYPE>.yaml)
#   NAME      output poi name (e.g. POI_IndustrialYard_01)
create-poi:
	$(PYTHON) tools/pipeline/create_poi.py --type $(POI_TYPE) --name $(NAME)

# Validate generated POI artifacts (pure Python; no UE required).
validate-poi:
	$(PYTHON) tools/pipeline/validate_poi.py --name $(NAME) $(if $(STRICT),--strict,)

# v0.8 — Runtime StateForge (make generated worlds react and remember)
# Authoring-side scenario simulation: mutate + aggregate state, expect the MPC
# effect + POI evidence, and prove a save/load round-trip. Pure Python; no UE.
#   NAME      target slice id / Region context_id
#   SCENARIO  scenario id (procedural/definitions/scenarios/<SCENARIO>.yaml)
run-state-sim:
	$(PYTHON) tools/pipeline/run_state_sim.py --name $(NAME) --scenario $(SCENARIO) --force

validate-runtime-state:
	$(PYTHON) tools/pipeline/validate_runtime_state.py --name $(NAME) \
	  $(if $(SCENARIO),--scenario $(SCENARIO),) $(if $(STRICT),--strict,)

# UE-side bridge: apply the scenario in-editor and read the MPC back (requires
# the scenario's slice map open in the editor).
apply-state-scenario:
	$(UE_PYTHON) tools/unreal/run_state_scenario.py \
	  --result procedural/generated/scenarios/$(NAME)__$(SCENARIO)/result.json --project-root .

# v0.8 — Houdini generated-asset intake sidecar (ONE owned StaticMesh; NOT MeshForge)
# Authoring-side registration + validation. Pure Python; no UE.
#   ASSET   asset id (procedural/definitions/generated_assets/<ASSET>.yaml)
register-generated-asset:
	$(PYTHON) tools/pipeline/register_generated_asset.py --asset $(ASSET)

validate-generated-asset:
	$(PYTHON) tools/pipeline/validate_generated_asset.py --asset $(ASSET) $(if $(STRICT),--strict,)

# UE-side: duplicate the baked Houdini asset out of /Game/HoudiniEngine/Bake into
# the WorldForge-owned tree and assert it is a StaticMesh (requires editor).
relocate-houdini-asset:
	$(UE_PYTHON) tools/unreal/relocate_houdini_asset.py \
	  --descriptor procedural/generated/generated_assets/$(ASSET)/descriptor.json --project-root .

# ======================================================================
# v1.0x hardening — hostile validation platform (Agent 0 aggregation)
# ----------------------------------------------------------------------
# `make` may be absent in some environments; every target below maps 1:1 to a
# `python tools/pipeline/<script>.py` entrypoint so the Python calls are the
# equivalent interface. STRICT/DEEP/TORTURE/SEEDS thread through as flags.
# ======================================================================
SEEDS   ?= 5
CASES   ?= 25

# --- Agent 0: integration + full-shield -------------------------------
full-shield:
	$(PYTHON) tools/pipeline/full_shield.py --pack $(PACK) --jobs $(JOBS) \
	  --seeds $(SEEDS) --cases $(CASES) \
	  $(if $(STRICT),--strict,) $(if $(DEEP),--deep,) $(if $(TORTURE),--torture,) $(if $(MESHES),--meshes,) \
	  $(if $(MISSIONS),--missions,) $(if $(PLAYTEST),--playtest,)

revalidate-world-pack:
	$(PYTHON) tools/pipeline/revalidate_world_pack.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Agent 1: no-fake-green / report integrity ------------------------
validate-report-integrity:
	$(PYTHON) tools/pipeline/validate_report_integrity.py --pack $(PACK) $(if $(STRICT),--strict,)

test-negative-validators:
	$(PYTHON) tools/pipeline/test_negative_validators.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Agent 2: environment contracts / visual profiles -----------------
validate-environment-contract:
	$(PYTHON) tools/pipeline/validate_environment_contract.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Agent 3: sky / lighting / fog / atmosphere -----------------------
validate-sky:
	$(PYTHON) tools/pipeline/validate_sky.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-lighting:
	$(PYTHON) tools/pipeline/validate_lighting.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-fog:
	$(PYTHON) tools/pipeline/validate_fog.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-atmosphere:
	$(PYTHON) tools/pipeline/validate_atmosphere.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Agent 4: POI / level design / reachability -----------------------
generate-level-design:
	$(PYTHON) tools/pipeline/generate_level_design.py --pack $(PACK)
validate-pois:
	$(PYTHON) tools/pipeline/validate_pois.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-level-design:
	$(PYTHON) tools/pipeline/validate_level_design.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-reachability:
	$(PYTHON) tools/pipeline/validate_reachability.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-poi-graph:
	$(PYTHON) tools/pipeline/validate_poi_graph.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Agent 5: entity anchors / encounter substrate --------------------
generate-entity-anchors:
	$(PYTHON) tools/pipeline/generate_entity_anchors.py --pack $(PACK)
validate-entity-anchors:
	$(PYTHON) tools/pipeline/validate_entity_anchors.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-spawns:
	$(PYTHON) tools/pipeline/validate_npc_spawns.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-readiness:
	$(PYTHON) tools/pipeline/validate_encounter_readiness.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Agent 6: rendering / scalability / raytracing / budgets ----------
validate-rendering-profiles:
	$(PYTHON) tools/pipeline/validate_rendering_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-scalability:
	$(PYTHON) tools/pipeline/validate_scalability.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-raytracing:
	$(PYTHON) tools/pipeline/validate_raytracing.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-performance-budgets:
	$(PYTHON) tools/pipeline/validate_performance_budgets.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Agent 7: lifecycle torture / fuzz / determinism / regression -----
corrupt-world-pack:
	$(PYTHON) tools/pipeline/corrupt_world_pack.py --pack $(PACK) --mode $(MODE)
lifecycle-torture:
	$(PYTHON) tools/pipeline/lifecycle_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
seed-matrix:
	$(PYTHON) tools/pipeline/seed_matrix.py --pack $(PACK) --seeds $(SEEDS) $(if $(STRICT),--strict,)
fuzz-world-pack:
	$(PYTHON) tools/pipeline/fuzz_world_pack.py --pack $(PACK) --cases $(CASES) $(if $(STRICT),--strict,)
validate-determinism:
	$(PYTHON) tools/pipeline/validate_determinism.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-regression-matrix:
	$(PYTHON) tools/pipeline/validate_regression_matrix.py $(if $(STRICT),--strict,)

# --- Optional operator tools ------------------------------------------
# NOTE: `inspect-world-pack` already exists above (inspection-metadata generator
# feeding validate-inspection); the v1.0x operator pack-overview is `inspect-pack`.
inspect-pack:
	$(PYTHON) tools/pipeline/inspect_world_pack.py --pack $(PACK)
inspect-map:
	$(PYTHON) tools/pipeline/inspect_world_pack.py --pack $(PACK) --map $(MAP)
diagnose-world-pack:
	$(PYTHON) tools/pipeline/diagnose_world_pack.py --pack $(PACK) $(if $(STRICT),--strict,)

# ======================================================================
# v1.1 BiomeForge — multi-environment expansion (Agent 0 aggregation)
# ----------------------------------------------------------------------
# Every target maps 1:1 to a python tools/pipeline/<script>.py entrypoint. The
# biome gates are folded into `make full-shield` automatically for any world
# pack that declares `biomeforge: true` (e.g. biome_expansion_world); they never
# run for desert_mvp_world, preserving the v1.0x regression contract.
#
#   make full-shield PACK=biome_expansion_world JOBS=8 STRICT=1 DEEP=1 TORTURE=1 SEEDS=200
# ======================================================================
BIOME_PACK ?= biome_expansion_world

validate-biome-contract:
	$(PYTHON) tools/pipeline/validate_biome_contract.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-biome-matrix:
	$(PYTHON) tools/pipeline/validate_biome_matrix.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-biome-profile-bindings:
	$(PYTHON) tools/pipeline/validate_biome_profile_bindings.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-biome-environment-compatibility:
	$(PYTHON) tools/pipeline/validate_biome_environment_compatibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-biome-inspection:
	$(PYTHON) tools/pipeline/validate_biome_inspection.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-terrain-forms:
	$(PYTHON) tools/pipeline/validate_terrain_forms.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-material-families:
	$(PYTHON) tools/pipeline/validate_material_families.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-vegetation-profiles:
	$(PYTHON) tools/pipeline/validate_vegetation_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-placement-profiles:
	$(PYTHON) tools/pipeline/validate_placement_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-biome-poi-compatibility:
	$(PYTHON) tools/pipeline/validate_biome_poi_compatibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-biome-traversal:
	$(PYTHON) tools/pipeline/validate_biome_traversal.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-biome-ecology-tags:
	$(PYTHON) tools/pipeline/validate_biome_ecology_tags.py --pack $(PACK) $(if $(STRICT),--strict,)
fuzz-biome-matrix:
	$(PYTHON) tools/pipeline/fuzz_biome_matrix.py --pack $(PACK) --cases $(CASES) $(if $(STRICT),--strict,)
diff-world-pack:
	$(PYTHON) tools/pipeline/diff_world_pack.py --pack $(PACK) --baseline $(BASELINE) $(if $(STRICT),--strict,)

# ======================================================================
# v1.2 MeshForge Intake — generated mesh asset catalog (Agent 0 aggregation)
# ----------------------------------------------------------------------
# Every target maps 1:1 to a python tools/pipeline/<script>.py entrypoint. The
# mesh gates fold into `make full-shield ... MESHES=1` (any pack). The intake
# layer is source-agnostic: internal_recipe / ue_generated / imported_generated_stub.
#
#   make full-shield PACK=biome_expansion_world JOBS=8 STRICT=1 DEEP=1 TORTURE=1 SEEDS=200 BIOMES=all PROFILES=all MESHES=1
# ======================================================================
MESH_PACK ?= biome_expansion_world

create-mesh-assets:
	$(PYTHON) tools/pipeline/create_mesh_assets.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-contract:
	$(PYTHON) tools/pipeline/validate_mesh_contract.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-catalog:
	$(PYTHON) tools/pipeline/validate_mesh_catalog.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-provenance:
	$(PYTHON) tools/pipeline/validate_mesh_provenance.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-final-paths:
	$(PYTHON) tools/pipeline/validate_mesh_final_paths.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-material-bindings:
	$(PYTHON) tools/pipeline/validate_mesh_material_bindings.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-collision-bounds:
	$(PYTHON) tools/pipeline/validate_mesh_collision_bounds.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-pcg-eligibility:
	$(PYTHON) tools/pipeline/validate_mesh_pcg_eligibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-biome-compatibility:
	$(PYTHON) tools/pipeline/validate_mesh_biome_compatibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-rendering-budgets:
	$(PYTHON) tools/pipeline/validate_mesh_rendering_budgets.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mesh-package:
	$(PYTHON) tools/pipeline/validate_mesh_package.py --pack $(PACK) $(if $(STRICT),--strict,)
mesh-negative-validators:
	$(PYTHON) tools/pipeline/test_negative_mesh.py --pack $(PACK) $(if $(STRICT),--strict,)
mesh-lifecycle-torture:
	$(PYTHON) tools/pipeline/mesh_lifecycle_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
inspect-mesh-catalog:
	$(PYTHON) tools/pipeline/inspect_mesh_catalog.py --pack $(PACK) $(if $(ASSET),--asset $(ASSET),)
inspect-mesh-asset:
	$(PYTHON) tools/pipeline/inspect_mesh_catalog.py --pack $(PACK) --asset $(ASSET)
diagnose-mesh-catalog:
	$(PYTHON) tools/pipeline/inspect_mesh_catalog.py --pack $(PACK) --diagnose $(if $(STRICT),--strict,)
diff-mesh-catalog:
	$(PYTHON) tools/pipeline/inspect_mesh_catalog.py --pack $(PACK) --diff --baseline $(BASELINE)

# ======================================================================
# v1.2 addendum — Houdini intake + Megascans external library
# ----------------------------------------------------------------------
# Houdini is a GENERATED backend (outputs generated_owned; HDA project/third-
# party owned). Megascans is a THIRD-PARTY external library (third_party_owned,
# licensed, repair/destroy-protected). Never collapse the two ownership models.
#   make full-shield PACK=biome_expansion_world ... MESHES=1 HOUDINI=1 MEGASCANS=1
#   make full-shield PACK=biome_expansion_world ... MESHES=1 HOUDINI=metadata_only MEGASCANS=1
# ======================================================================
LIB ?= megascans

# --- Houdini intake ---------------------------------------------------
validate-houdini-intake:
	$(PYTHON) tools/pipeline/validate_houdini_intake.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-houdini-cook-reports:
	$(PYTHON) tools/pipeline/validate_houdini_cook_reports.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-houdini-bake-reports:
	$(PYTHON) tools/pipeline/validate_houdini_bake_reports.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-houdini-generated-assets:
	$(PYTHON) tools/pipeline/validate_houdini_generated_assets.py --pack $(PACK) $(if $(STRICT),--strict,)
inspect-houdini-intake:
	$(PYTHON) tools/pipeline/inspect_houdini_intake.py --pack $(PACK)
diagnose-houdini-intake:
	$(PYTHON) tools/pipeline/inspect_houdini_intake.py --pack $(PACK) --diagnose $(if $(STRICT),--strict,)

# --- Megascans / external library -------------------------------------
scan-external-asset-library:
	$(PYTHON) tools/pipeline/scan_external_asset_library.py --lib $(LIB) $(if $(STRICT),--strict,)
validate-external-asset-catalog:
	$(PYTHON) tools/pipeline/validate_external_asset_catalog.py --lib $(LIB) $(if $(STRICT),--strict,)
validate-megascans-catalog:
	$(PYTHON) tools/pipeline/validate_megascans_catalog.py --lib $(LIB) $(if $(STRICT),--strict,)
validate-megascans-bindings:
	$(PYTHON) tools/pipeline/validate_megascans_bindings.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-megascans-pcg-eligibility:
	$(PYTHON) tools/pipeline/validate_megascans_pcg_eligibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-megascans-biome-compatibility:
	$(PYTHON) tools/pipeline/validate_megascans_biome_compatibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-external-asset-ownership:
	$(PYTHON) tools/pipeline/validate_external_asset_ownership.py --lib $(LIB) $(if $(STRICT),--strict,)
validate-third-party-package-policy:
	$(PYTHON) tools/pipeline/validate_third_party_package_policy.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-source-ownership-separation:
	$(PYTHON) tools/pipeline/validate_source_ownership_separation.py --pack $(PACK) $(if $(STRICT),--strict,)
inspect-external-asset-library:
	$(PYTHON) tools/pipeline/inspect_external_asset_library.py --lib $(LIB) $(if $(ASSET),--asset $(ASSET),)
inspect-external-asset:
	$(PYTHON) tools/pipeline/inspect_external_asset_library.py --lib $(LIB) --asset $(ASSET)
diagnose-external-asset-library:
	$(PYTHON) tools/pipeline/inspect_external_asset_library.py --lib $(LIB) --diagnose $(if $(STRICT),--strict,)

# ======================================================================
# v1.3 MissionForge + PlaytestForge Alpha
# ----------------------------------------------------------------------
# Missions are biome-aware playable purpose layered over biome_expansion_world's
# maps. Every target maps 1:1 to a python entrypoint. Mission + playtest gates
# fold into `make full-shield PACK=mission_loop_world MISSIONS=1 PLAYTEST=1`.
# ======================================================================
MISSION_PACK ?= mission_loop_world

create-mission-loops:
	$(PYTHON) tools/pipeline/create_mission_loops.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-contract:
	$(PYTHON) tools/pipeline/validate_mission_contract.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-graph:
	$(PYTHON) tools/pipeline/validate_mission_graph.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-placement:
	$(PYTHON) tools/pipeline/validate_mission_placement.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-biome-compatibility:
	$(PYTHON) tools/pipeline/validate_mission_biome_compatibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-routes:
	$(PYTHON) tools/pipeline/validate_mission_routes.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-objectives:
	$(PYTHON) tools/pipeline/validate_mission_objectives.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-state:
	$(PYTHON) tools/pipeline/validate_mission_state.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-save-load:
	$(PYTHON) tools/pipeline/validate_mission_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-rewards:
	$(PYTHON) tools/pipeline/validate_mission_rewards.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-dependencies:
	$(PYTHON) tools/pipeline/validate_mission_dependencies.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-mesh-usage:
	$(PYTHON) tools/pipeline/validate_mission_mesh_usage.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-mission-entity-anchors:
	$(PYTHON) tools/pipeline/validate_mission_entity_anchors.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-playtest-contract:
	$(PYTHON) tools/pipeline/validate_playtest_contract.py --pack $(PACK) $(if $(STRICT),--strict,)
run-playtest-forge:
	$(PYTHON) tools/pipeline/run_playtest_forge.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-playtest-reports:
	$(PYTHON) tools/pipeline/validate_playtest_reports.py --pack $(PACK) $(if $(STRICT),--strict,)
mission-negative-validators:
	$(PYTHON) tools/pipeline/test_negative_mission.py --pack $(PACK) $(if $(STRICT),--strict,)
fuzz-mission-matrix:
	$(PYTHON) tools/pipeline/fuzz_mission_matrix.py --pack $(PACK) --cases $(CASES) $(if $(STRICT),--strict,)
mission-lifecycle-torture:
	$(PYTHON) tools/pipeline/mission_lifecycle_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
inspect-mission-pack:
	$(PYTHON) tools/pipeline/inspect_mission_pack.py --pack $(PACK) $(if $(MISSION),--mission $(MISSION),)
diagnose-mission-pack:
	$(PYTHON) tools/pipeline/inspect_mission_pack.py --pack $(PACK) --diagnose $(if $(STRICT),--strict,)

preview:
	@echo "Preview generation is not implemented yet."
	@exit 1

build:
	@echo "Authoring-side build steps for $(RECIPE)..."
	$(MAKE) validate-recipe RECIPE=$(RECIPE)
	$(MAKE) render-substance RECIPE=$(RECIPE)
	$(MAKE) generate-manifest RECIPE=$(RECIPE)
	@echo ""
	@echo "Next steps (run inside UE Python):"
	@echo "  make import-textures RECIPE=$(RECIPE)"
	@echo "  make create-material RECIPE=$(RECIPE)"
	@echo "  make create-data-asset RECIPE=$(RECIPE)"
	@echo "  make validate-assets RECIPE=$(RECIPE)"

clean:
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
