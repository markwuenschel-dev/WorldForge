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
# v1.3.5 — export visual flag to full_shield gate subprocesses.
export VISUALS
# v1.4 — export encounter/balance flags to full_shield gate subprocesses.
# (PLAYTEST is already exported above; PLAYTEST=beta selects PlaytestForge Beta.)
export ENCOUNTERS
export BALANCE
# v1.5 — export asset-acquisition / realization flags to full_shield gate
# subprocesses and the UE-side + source validators. VISUAL is an alias for VISUALS.
export ASSETS
export MATERIALIZE
export VISUAL
export SOURCE

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
        inspect-mission-pack diagnose-mission-pack \
        materialize-environment-rigs scan-megascans-visual-assets create-visual-dressing \
        validate-visual-asset-coverage validate-surface-materialization validate-world-dressing \
        validate-environment-rig validate-sky-materialization validate-fog-materialization \
        validate-cloud-materialization validate-lighting-exposure validate-post-process-profiles \
        validate-weather-vfx validate-visual-readability validate-visual-budgets validate-visual-package \
        visual-negative-validators visual-lifecycle-torture inspect-visual-pack diagnose-visual-pack \
        create-encounter-pack create-encounters validate-encounter-contract validate-encounter-archetypes \
        validate-spawn-groups validate-encounter-anchors validate-encounter-routes \
        validate-encounter-pressure validate-encounter-pacing validate-encounter-biome-compatibility \
        validate-encounter-mission-compatibility validate-encounter-mesh-dependencies \
        validate-encounter-cover validate-encounter-hazards validate-encounter-resources \
        validate-encounter-state validate-encounter-save-load validate-encounter-rewards \
        validate-playtest-beta-contract run-playtest-forge-beta validate-playtest-beta-reports \
        validate-balance-contract run-balance-forge validate-balance-reports \
        encounter-negative-validators fuzz-encounter-matrix encounter-lifecycle-torture \
        inspect-encounter-pack inspect-encounter diagnose-encounter-pack

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
	  $(if $(MISSIONS),--missions,) $(if $(PLAYTEST),--playtest,) $(if $(VISUALS),--visuals,) \
	  $(if $(VISUAL),--visuals,) \
	  $(if $(ENCOUNTERS),--encounters,) $(if $(BALANCE),--balance,) \
	  $(if $(ASSETS),--assets,) $(if $(MATERIALIZE),--materialize,)

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

# ======================================================================
# v1.4 EncounterForge + PlaytestForge Beta + BalanceForge Alpha
# ----------------------------------------------------------------------
# Layers biome/mission-aware encounter pressure over the 60 mission loops:
# 120 encounter-enabled missions (2 profiles x 8 archetypes), proven by
# PlaytestForge Beta + classified by BalanceForge Alpha. Folds into
# `make full-shield PACK=encounter_loop_world MISSIONS=1 ENCOUNTERS=1
#  PLAYTEST=beta BALANCE=1 MESHES=1 MEGASCANS=1`.
# ======================================================================
ENCOUNTER_PACK ?= encounter_loop_world

create-encounter-pack:
	$(PYTHON) tools/pipeline/create_encounter_pack.py --pack $(PACK) $(if $(STRICT),--strict,)
create-encounters:
	$(PYTHON) tools/pipeline/create_encounters.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-contract:
	$(PYTHON) tools/pipeline/validate_encounter_contract.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-archetypes:
	$(PYTHON) tools/pipeline/validate_encounter_archetypes.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-spawn-groups:
	$(PYTHON) tools/pipeline/validate_spawn_groups.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-anchors:
	$(PYTHON) tools/pipeline/validate_encounter_anchors.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-routes:
	$(PYTHON) tools/pipeline/validate_encounter_routes.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-pressure:
	$(PYTHON) tools/pipeline/validate_encounter_pressure.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-pacing:
	$(PYTHON) tools/pipeline/validate_encounter_pacing.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-biome-compatibility:
	$(PYTHON) tools/pipeline/validate_encounter_biome_compatibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-mission-compatibility:
	$(PYTHON) tools/pipeline/validate_encounter_mission_compatibility.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-mesh-dependencies:
	$(PYTHON) tools/pipeline/validate_encounter_mesh_dependencies.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-cover:
	$(PYTHON) tools/pipeline/validate_encounter_cover.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-hazards:
	$(PYTHON) tools/pipeline/validate_encounter_hazards.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-resources:
	$(PYTHON) tools/pipeline/validate_encounter_resources.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-state:
	$(PYTHON) tools/pipeline/validate_encounter_state.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-save-load:
	$(PYTHON) tools/pipeline/validate_encounter_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-rewards:
	$(PYTHON) tools/pipeline/validate_encounter_rewards.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-playtest-beta-contract:
	$(PYTHON) tools/pipeline/validate_playtest_beta_contract.py --pack $(PACK) $(if $(STRICT),--strict,)
run-playtest-forge-beta:
	$(PYTHON) tools/pipeline/run_playtest_forge_beta.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-playtest-beta-reports:
	$(PYTHON) tools/pipeline/validate_playtest_beta_reports.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-balance-contract:
	$(PYTHON) tools/pipeline/validate_balance_contract.py --pack $(PACK) $(if $(STRICT),--strict,)
run-balance-forge:
	$(PYTHON) tools/pipeline/run_balance_forge.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-balance-reports:
	$(PYTHON) tools/pipeline/validate_balance_reports.py --pack $(PACK) $(if $(STRICT),--strict,)
encounter-negative-validators:
	$(PYTHON) tools/pipeline/test_negative_encounter.py --pack $(PACK) $(if $(STRICT),--strict,)
fuzz-encounter-matrix:
	$(PYTHON) tools/pipeline/fuzz_encounter_matrix.py --pack $(PACK) --cases $(CASES) $(if $(STRICT),--strict,)
encounter-lifecycle-torture:
	$(PYTHON) tools/pipeline/encounter_lifecycle_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
inspect-encounter-pack:
	$(PYTHON) tools/pipeline/inspect_encounter_pack.py --pack $(PACK)
inspect-encounter:
	$(PYTHON) tools/pipeline/inspect_encounter_pack.py --pack $(PACK) $(if $(ENCOUNTER),--encounter $(ENCOUNTER),)
diagnose-encounter-pack:
	$(PYTHON) tools/pipeline/inspect_encounter_pack.py --pack $(PACK) --diagnose $(if $(STRICT),--strict,)

# ======================================================================
# v1.3.5 VisualFidelityForge — visual realization over the mission substrate
# ----------------------------------------------------------------------
# Materializes UE-native environment rigs + Megascans surfaces + world dressing
# and validates fidelity without breaking playability/budget/lifecycle. Folds
# into `make full-shield PACK=mission_loop_world MISSIONS=1 PLAYTEST=1 VISUALS=1`.
# ======================================================================
materialize-environment-rigs:
	$(PYTHON) tools/pipeline/materialize_environment_rigs.py --pack $(PACK) $(if $(STRICT),--strict,)
scan-megascans-visual-assets:
	$(PYTHON) tools/pipeline/scan_megascans_visual_assets.py --lib $(if $(LIB),$(LIB),megascans) $(if $(STRICT),--strict,)
create-visual-dressing:
	$(PYTHON) tools/pipeline/create_visual_dressing.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-visual-asset-coverage:
	$(PYTHON) tools/pipeline/validate_visual_asset_coverage.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-surface-materialization:
	$(PYTHON) tools/pipeline/validate_surface_materialization.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-world-dressing:
	$(PYTHON) tools/pipeline/validate_world_dressing.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-environment-rig:
	$(PYTHON) tools/pipeline/validate_environment_rig.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-sky-materialization:
	$(PYTHON) tools/pipeline/validate_sky_materialization.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-fog-materialization:
	$(PYTHON) tools/pipeline/validate_fog_materialization.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-cloud-materialization:
	$(PYTHON) tools/pipeline/validate_cloud_materialization.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-lighting-exposure:
	$(PYTHON) tools/pipeline/validate_lighting_exposure.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-post-process-profiles:
	$(PYTHON) tools/pipeline/validate_post_process_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-weather-vfx:
	$(PYTHON) tools/pipeline/validate_weather_vfx.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-visual-readability:
	$(PYTHON) tools/pipeline/validate_visual_readability.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-visual-budgets:
	$(PYTHON) tools/pipeline/validate_visual_budgets.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-visual-package:
	$(PYTHON) tools/pipeline/validate_visual_package.py --pack $(PACK) $(if $(STRICT),--strict,)
visual-negative-validators:
	$(PYTHON) tools/pipeline/test_negative_visual.py --pack $(PACK) $(if $(STRICT),--strict,)
visual-lifecycle-torture:
	$(PYTHON) tools/pipeline/visual_lifecycle_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
inspect-visual-pack:
	$(PYTHON) tools/pipeline/inspect_visual_pack.py --pack $(PACK) $(if $(MAP),--map $(MAP),)
diagnose-visual-pack:
	$(PYTHON) tools/pipeline/inspect_visual_pack.py --pack $(PACK) --diagnose $(if $(STRICT),--strict,)

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

# ======================================================================
# v1.5 — AssetAcquisitionForge + AssetRealizationForge + VisualEnvironmentForge
# ----------------------------------------------------------------------
# Every target maps 1:1 to a tools/pipeline/<script>.py entrypoint (UE-side
# drivers live in tools/unreal/). SOURCE/PRIORITY parameterize acquisition.
# ======================================================================
SOURCE   ?= polyhaven
PRIORITY ?= P1

.PHONY: validate-asset-need-schema validate-asset-procurement-schema \
        validate-asset-candidate-schema validate-asset-approval-schema \
        validate-asset-quarantine-schema validate-asset-catalog-schema \
        validate-visual-kit-schema validate-cover-binding-schema validate-v1-5-taxonomy \
        asset-gap-report asset-procurement-manifest asset-shopping-list \
        asset-free-downloads asset-local-cache-scan asset-quarantine-validators \
        asset-catalog-validators validate-asset-package-policy validate-source-adapters \
        validate-asset-licenses validate-asset-provenance validate-asset-hashes \
        validate-asset-approval-flow asset-acquisition-negative-validators asset-source-torture \
        generate-owned-cover-meshes asset-materialize-ue validate-ue-materialization-reports \
        validate-asset-dependencies list-cover-proxies \
        visual-environment-kits visual-materialize visual-cover-replacement \
        validate-cover-real-meshes validate-biome-visual-readability \
        validate-visual-density-budgets visual-inspection-report \
        run-balance-forge-alpha validate-route-clearance-after-visuals \
        validate-encounter-anchor-preservation v1-5-fuzz v1-5-shield \
        validate-failure-codes

# --- v1.5 Agent 1: contract / schema gates ----------------------------
validate-asset-need-schema:
	$(PYTHON) tools/pipeline/validate_asset_need.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-procurement-schema:
	$(PYTHON) tools/pipeline/validate_asset_procurement.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-candidate-schema:
	$(PYTHON) tools/pipeline/validate_asset_candidate.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-approval-schema:
	$(PYTHON) tools/pipeline/validate_asset_approval.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-quarantine-schema:
	$(PYTHON) tools/pipeline/validate_asset_quarantine_schema.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-catalog-schema:
	$(PYTHON) tools/pipeline/validate_asset_catalog_schema.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-visual-kit-schema:
	$(PYTHON) tools/pipeline/validate_visual_kit.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-cover-binding-schema:
	$(PYTHON) tools/pipeline/validate_cover_binding.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-v1-5-taxonomy:
	$(PYTHON) tools/pipeline/validate_v1_5_taxonomy.py $(if $(STRICT),--strict,)
validate-failure-codes:
	$(PYTHON) tools/pipeline/validate_failure_codes.py $(if $(STRICT),--strict,)

# --- v1.5 Agent 2/3: acquisition + quarantine + catalog ---------------
asset-gap-report:
	$(PYTHON) tools/pipeline/analyze_asset_gaps.py --pack $(PACK) $(if $(STRICT),--strict,)
asset-procurement-manifest:
	$(PYTHON) tools/pipeline/create_procurement_manifest.py --pack $(PACK) $(if $(STRICT),--strict,)
asset-shopping-list:
	$(PYTHON) tools/pipeline/export_shopping_list.py --pack $(PACK) --source $(SOURCE) --priority $(PRIORITY) $(if $(STRICT),--strict,)
asset-free-downloads:
	$(PYTHON) tools/pipeline/acquire_free_assets.py --source $(SOURCE) --approved-free-only $(if $(STRICT),--strict,)
asset-local-cache-scan:
	$(PYTHON) tools/pipeline/scan_local_asset_cache.py --source $(SOURCE) $(if $(STRICT),--strict,)
validate-source-adapters:
	$(PYTHON) tools/pipeline/validate_source_adapters.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-approval-flow:
	$(PYTHON) tools/pipeline/validate_asset_approval_flow.py --pack $(PACK) $(if $(STRICT),--strict,)
asset-quarantine-validators:
	$(PYTHON) tools/pipeline/validate_asset_quarantine.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-licenses:
	$(PYTHON) tools/pipeline/validate_asset_licenses.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-provenance:
	$(PYTHON) tools/pipeline/validate_asset_provenance.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-hashes:
	$(PYTHON) tools/pipeline/validate_asset_hashes.py --pack $(PACK) $(if $(STRICT),--strict,)
asset-catalog-validators:
	$(PYTHON) tools/pipeline/validate_asset_catalog.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-package-policy:
	$(PYTHON) tools/pipeline/validate_asset_package_policy.py --pack $(PACK) $(if $(STRICT),--strict,)
asset-acquisition-negative-validators:
	$(PYTHON) tools/pipeline/test_negative_assets.py --pack $(PACK) $(if $(STRICT),--strict,)
asset-source-torture:
	$(PYTHON) tools/pipeline/asset_source_torture.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- v1.5 Agent 4: UE realization + cover replacement -----------------
generate-owned-cover-meshes:
	$(PYTHON) tools/pipeline/generate_owned_cover_meshes.py --pack $(PACK) $(if $(STRICT),--strict,)
asset-materialize-ue:
	$(PYTHON) tools/pipeline/materialize_assets.py --pack $(PACK) --approved-only $(if $(STRICT),--strict,)
validate-ue-materialization-reports:
	$(PYTHON) tools/pipeline/validate_ue_materialization.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-asset-dependencies:
	$(PYTHON) tools/pipeline/validate_asset_dependencies.py --pack $(PACK) $(if $(STRICT),--strict,)
list-cover-proxies:
	$(PYTHON) tools/pipeline/list_cover_proxies.py --pack $(PACK) $(if $(STRICT),--strict,)
visual-cover-replacement:
	$(PYTHON) tools/pipeline/replace_cover_proxies.py --pack $(PACK) --approved-only $(if $(STRICT),--strict,)
validate-cover-real-meshes:
	$(PYTHON) tools/pipeline/validate_cover_replacement.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- v1.5 Agent 5: visual environment kits ----------------------------
visual-environment-kits:
	$(PYTHON) tools/pipeline/create_visual_environment_kits.py --pack $(PACK) $(if $(STRICT),--strict,)
visual-materialize:
	$(PYTHON) tools/pipeline/materialize_visual_environment_kits.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-biome-visual-readability:
	$(PYTHON) tools/pipeline/validate_biome_visual_readability.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-visual-density-budgets:
	$(PYTHON) tools/pipeline/validate_visual_density_budgets.py --pack $(PACK) $(if $(STRICT),--strict,)
visual-inspection-report:
	$(PYTHON) tools/pipeline/validate_visual_inspection_report.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- v1.5 Agent 6: regression preservation ----------------------------
run-balance-forge-alpha:
	$(PYTHON) tools/pipeline/run_balance_forge.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-route-clearance-after-visuals:
	$(PYTHON) tools/pipeline/validate_route_clearance_after_visuals.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-encounter-anchor-preservation:
	$(PYTHON) tools/pipeline/validate_encounter_anchor_preservation.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- v1.5 Agent 7: fuzz ------------------------------------------------
v1-5-fuzz:
	$(PYTHON) tools/pipeline/v1_5_fuzz.py --cases $(CASES) $(if $(STRICT),--strict,)

# --- v1.5 full shield --------------------------------------------------
v1-5-shield:
	$(PYTHON) tools/pipeline/full_shield.py --pack $(PACK) --jobs $(JOBS) \
	  --seeds $(SEEDS) --cases $(CASES) \
	  $(if $(STRICT),--strict,) $(if $(DEEP),--deep,) $(if $(TORTURE),--torture,) \
	  --missions --encounters --playtest --balance \
	  $(if $(VISUAL)$(VISUALS),--visuals,) $(if $(ASSETS),--assets,) $(if $(MATERIALIZE),--materialize,)

# ======================================================================
# v1.6 LiveRuntimeForge Alpha + InteractionForge Alpha + PlaytestForge Gamma
# ----------------------------------------------------------------------
# First runtime-truth milestone: generate runtime scenarios from the v1.5-
# realized encounter_loop_world, materialize interaction actors, and drive a
# controlled UE pawn through real navmesh/collision to completion + save/load.
# The authoring substrate (contracts/generation/validation/coverage) is proven
# WITHOUT the editor; the live-run gates fail closed (RUNTIME_LIVE_RUN_PENDING,
# blocking under STRICT) until the NeoStack/UE bridge is connected — they never
# fake-green. See docs/guides + the v1.6 status doc.
# ======================================================================
RUNTIME_PACK ?= encounter_loop_world

# --- v1.6 taxonomy / contracts -----------------------------------------
validate-v1-6-taxonomy:
	$(PYTHON) tools/pipeline/validate_v1_6_taxonomy.py $(if $(STRICT),--strict,)

# --- v1.6 Agent 4: runtime scenario generation + validation ------------
runtime-scenarios:
	$(PYTHON) tools/pipeline/generate_runtime_scenarios.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-runtime-scenarios:
	$(PYTHON) tools/pipeline/validate_runtime_scenarios.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-runtime-scenario-schema:
	$(PYTHON) tools/pipeline/validate_runtime_scenarios.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-runtime-scenario-coverage:
	$(PYTHON) tools/pipeline/validate_runtime_scenario_coverage.py --pack $(PACK) $(if $(STRICT),--strict,)

.PHONY: validate-v1-6-taxonomy runtime-scenarios validate-runtime-scenarios \
	validate-runtime-scenario-schema validate-runtime-scenario-coverage

# --- v1.6 Agent 2: runtime pawn profile --------------------------------
runtime-pawn-profile:
	$(PYTHON) tools/pipeline/create_runtime_pawn_profile.py --profile $(if $(PROFILE),$(PROFILE),default) $(if $(STRICT),--strict,)
validate-runtime-pawn-profile:
	$(PYTHON) tools/pipeline/validate_runtime_pawn_profile.py --profile $(if $(PROFILE),$(PROFILE),default) $(if $(STRICT),--strict,)

.PHONY: runtime-pawn-profile validate-runtime-pawn-profile

# --- v1.6 Agent 3: InteractionForge Alpha ------------------------------
runtime-interaction-actors:
	$(PYTHON) tools/pipeline/materialize_runtime_interaction_actors.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-runtime-interactions:
	$(PYTHON) tools/pipeline/validate_runtime_interactions.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-runtime-interaction-verbs:
	$(PYTHON) tools/pipeline/validate_runtime_interaction_verbs.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-runtime-mission-completion-bridge:
	$(PYTHON) tools/pipeline/validate_runtime_mission_completion_bridge.py --pack $(PACK) $(if $(STRICT),--strict,)

.PHONY: runtime-interaction-actors validate-runtime-interactions \
	validate-runtime-interaction-verbs validate-runtime-mission-completion-bridge

# --- v1.6 Agent 4: route plans -----------------------------------------
runtime-route-plans:
	$(PYTHON) tools/pipeline/generate_runtime_route_plans.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-runtime-route-plans:
	$(PYTHON) tools/pipeline/validate_runtime_route_plans.py --pack $(PACK) $(if $(STRICT),--strict,)

.PHONY: runtime-route-plans validate-runtime-route-plans

# --- v1.6 Agent 5: PlaytestForge Gamma classification ------------------
run-playtest-forge-gamma:
	$(PYTHON) tools/pipeline/run_playtest_forge_gamma.py --pack $(PACK) --scenarios $(if $(SCENARIOS),$(SCENARIOS),all) $(if $(STRICT),--strict,)
validate-runtime-completion:
	$(PYTHON) tools/pipeline/validate_runtime_completion.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-playtest-gamma-no-fake-green:
	$(PYTHON) tools/pipeline/validate_playtest_gamma_no_fake_green.py --pack $(PACK) $(if $(STRICT),--strict,)
runtime-bridge-status:
	$(PYTHON) tools/pipeline/runtime_bridge.py

# --- v1.6 full shield --------------------------------------------------
v1-6-shield:
	$(PYTHON) tools/pipeline/v1_6_shield.py --pack $(PACK) $(if $(STRICT),--strict,) $(if $(REQUIRE_LIVE),--require-live,)

.PHONY: run-playtest-forge-gamma validate-runtime-completion \
	validate-playtest-gamma-no-fake-green runtime-bridge-status v1-6-shield

# --- v1.6 Agent 6/7: live-output validators + negatives ----------------
validate-runtime-telemetry:
	$(PYTHON) tools/pipeline/validate_runtime_telemetry.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-runtime-save-load:
	$(PYTHON) tools/pipeline/validate_runtime_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)
runtime-negative-validators:
	$(PYTHON) tools/pipeline/test_negative_runtime.py $(if $(STRICT),--strict,)

.PHONY: validate-runtime-telemetry validate-runtime-save-load runtime-negative-validators

# --- v1.6 Agent 7: fuzz + report integrity -----------------------------
v1-6-fuzz:
	$(PYTHON) tools/pipeline/v1_6_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)
runtime-report-integrity:
	$(PYTHON) tools/pipeline/runtime_report_integrity.py --pack $(PACK) $(if $(STRICT),--strict,)

.PHONY: v1-6-fuzz runtime-report-integrity

# --- v1.6x: headless full-matrix live runtime completion ---------------
# Drives all 120 scenarios to GENUINE completed_runtime with no editor, no
# NeoStack bridge and no navmesh. Each scenario is one fresh crash-isolated
# UnrealEditor-Cmd -game process running the C++ AWFRuntimeTestPawn/Objective:
# the pawn flies continuously (never teleports) to the real objective transform,
# mutates state, saves, reload-verifies, and requests a graceful exit. Requires
# the WorldForge module built (Build.bat WorldForgeEditor Win64 Development).
#   make v1-6x-prepare        # place C++ runtime actors on all 60 maps (1 boot)
#   make v1-6x-run            # drive pending scenarios (checkpoint/resume)
#   make v1-6x-gate STRICT=1  # exit 0 only if all 120 genuinely completed_runtime
#   make v1-6x-status
v1-6x-prepare:
	$(PYTHON) tools/pipeline/run_headless_runtime_batch.py --prepare $(if $(LIMIT),--limit $(LIMIT),)
v1-6x-run:
	$(PYTHON) tools/pipeline/run_headless_runtime_batch.py --run $(if $(LIMIT),--limit $(LIMIT),) $(if $(ONLY),--only $(ONLY),)
v1-6x-gate:
	$(PYTHON) tools/pipeline/run_headless_runtime_batch.py --gate $(if $(STRICT),--strict,)
v1-6x-status:
	$(PYTHON) tools/pipeline/run_headless_runtime_batch.py --status

.PHONY: v1-6x-prepare v1-6x-run v1-6x-gate v1-6x-status

# --- v1.6y GroundTraversalForge: grounded (walking, gravity, collision) runtime -
# Wave-0 empirical decision: UE runtime navmesh is unavailable headless
# (WF_GNAV path_exists=0), but the static-mesh terrain HAS collision, so a
# gravity+capsule Character lands and WALKS to the objective. Success mode =
# grounded_manual_waypoint (grounded straight-line following); flight and
# teleport can NEVER count as grounded success.
#   make ground-prepare / ground-run / ground-gate STRICT=1 / ground-status
ground-prepare:
	$(PYTHON) tools/pipeline/run_ground_runtime_batch.py --prepare $(if $(LIMIT),--limit $(LIMIT),)
ground-run:
	$(PYTHON) tools/pipeline/run_ground_runtime_batch.py --run $(if $(LIMIT),--limit $(LIMIT),) $(if $(ONLY),--only $(ONLY),)
run-grounded-runtime-sample:
	$(PYTHON) tools/pipeline/run_ground_runtime_batch.py --run --limit $(if $(SCENARIOS),$(SCENARIOS),12)
run-playtest-forge-delta:
	$(PYTHON) tools/pipeline/run_ground_runtime_batch.py --run $(if $(SCENARIOS),--limit $(SCENARIOS),)
ground-gate:
	$(PYTHON) tools/pipeline/run_ground_runtime_batch.py --gate $(if $(STRICT),--strict,)
ground-status:
	$(PYTHON) tools/pipeline/run_ground_runtime_batch.py --status
validate-ground-completion:
	$(PYTHON) tools/pipeline/validate_ground_completion.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-no-flight-ground-success:
	$(PYTHON) tools/pipeline/validate_no_flight_ground_success.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-no-teleport-ground-success:
	$(PYTHON) tools/pipeline/validate_no_flight_ground_success.py --pack $(PACK) $(if $(STRICT),--strict,)
ground-no-fake-green-selftest:
	$(PYTHON) tools/pipeline/validate_no_flight_ground_success.py --self-test
v1-6y-shield:
	$(PYTHON) tools/pipeline/v1_6y_shield.py --pack $(PACK) $(if $(STRICT),--strict,) $(if $(REQUIRE_LIVE),--require-live,)

.PHONY: ground-prepare ground-run run-grounded-runtime-sample run-playtest-forge-delta \
	ground-gate ground-status validate-ground-completion validate-no-flight-ground-success \
	validate-no-teleport-ground-success ground-no-fake-green-selftest v1-6y-shield

# --- v1.6z GroundTraversalForge Production Hardening -------------------
# Contract spine, deep walkability (real UE geometry), multi-node route graph,
# and the full hostile-validation suite that NPCForge will stand on.
validate-ground-traversal-schemas:
	$(PYTHON) tools/pipeline/validate_ground_traversal_schemas.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-v1-6z-taxonomy:
	$(PYTHON) tools/pipeline/validate_ground_traversal_schemas.py --pack $(PACK) $(if $(STRICT),--strict,)
analyze-ground-walkability:
	$(PYTHON) tools/pipeline/analyze_ground_walkability.py --pack $(PACK) $(if $(STRICT),--strict,) $(if $(LIMIT),--limit $(LIMIT),)
validate-ground-walkability:
	$(PYTHON) tools/pipeline/validate_ground_walkability.py --pack $(PACK) $(if $(STRICT),--strict,)
generate-ground-route-graph:
	$(PYTHON) tools/pipeline/generate_ground_route_graph.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-ground-route-graph:
	$(PYTHON) tools/pipeline/validate_ground_route_graph.py --pack $(PACK) $(if $(STRICT),--strict,)
generate-ground-route-plans:
	$(PYTHON) tools/pipeline/generate_ground_route_plans.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-ground-route-plans:
	$(PYTHON) tools/pipeline/validate_ground_route_plans.py --pack $(PACK) $(if $(STRICT),--strict,)
ground-traversal-negative-validators:
	$(PYTHON) tools/pipeline/ground_traversal_negatives.py $(if $(STRICT),--strict,)
ground-walkability-negative-validators:
	$(PYTHON) tools/pipeline/ground_traversal_negatives.py $(if $(STRICT),--strict,)
ground-navmesh-negative-validators:
	$(PYTHON) tools/pipeline/ground_traversal_negatives.py $(if $(STRICT),--strict,)
ground-route-graph-negative-validators:
	$(PYTHON) tools/pipeline/ground_traversal_negatives.py $(if $(STRICT),--strict,)
ground-traversal-torture:
	$(PYTHON) tools/pipeline/ground_traversal_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
ground-traversal-report-integrity:
	$(PYTHON) tools/pipeline/ground_traversal_report_integrity.py --pack $(PACK) $(if $(STRICT),--strict,)
ground-traversal-fuzz:
	$(PYTHON) tools/pipeline/ground_traversal_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)
v1-6z-shield:
	$(PYTHON) tools/pipeline/v1_6z_shield.py --pack $(PACK) $(if $(STRICT),--strict,) $(if $(REQUIRE_LIVE),--require-live,)

# v1.6x regression alias: the headless flight matrix is gated by the v1.6 shield
# under --require-live (which runs the 120/120 headless full-matrix gate).
v1-6x-shield:
	$(PYTHON) tools/pipeline/v1_6_shield.py --pack $(PACK) $(if $(STRICT),--strict,) $(if $(REQUIRE_LIVE),--require-live,)

.PHONY: validate-ground-traversal-schemas validate-v1-6z-taxonomy analyze-ground-walkability \
	validate-ground-walkability generate-ground-route-graph validate-ground-route-graph \
	generate-ground-route-plans validate-ground-route-plans ground-traversal-negative-validators \
	ground-walkability-negative-validators ground-navmesh-negative-validators \
	ground-route-graph-negative-validators ground-traversal-torture ground-traversal-report-integrity \
	ground-traversal-fuzz v1-6z-shield v1-6x-shield

# ======================================================================
# v1.7 NPCForge + EncounterBehaviorForge — behavior substrate (Agent 0)
# ----------------------------------------------------------------------
# Every target maps 1:1 to a python tools/pipeline/<script>.py entrypoint, on
# the v1.6z grounded traversal substrate. Gates are FAIL-CLOSED: a target whose
# script is not yet built errors (non-zero), turning v1-7-shield RED until it is
# implemented and green. No native UE navmesh claim; NPCs move over the validated
# grounded_worldforge_route substrate — never flight, never teleport.
#
#   make v1-7-shield PACK=encounter_loop_world JOBS=8 STRICT=1 DEEP=1 TORTURE=1 NPC=1 BEHAVIOR=1
# ======================================================================
NPC_PACK ?= encounter_loop_world

# --- Contracts + generation -------------------------------------------
npc-contracts:
	$(PYTHON) tools/pipeline/validate_npc_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
npc-archetypes:
	$(PYTHON) tools/pipeline/generate_npc_archetypes.py --pack $(PACK) $(if $(STRICT),--strict,)
npc-spawn-groups:
	$(PYTHON) tools/pipeline/generate_npc_spawn_groups.py --pack $(PACK) $(if $(STRICT),--strict,)
npc-behavior-profiles:
	$(PYTHON) tools/pipeline/generate_npc_behavior_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)
npc-behavior-scenarios:
	$(PYTHON) tools/pipeline/generate_npc_behavior_scenarios.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-behavior-scenarios:
	$(PYTHON) tools/pipeline/validate_npc_behavior_scenarios.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Materialization ---------------------------------------------------
npc-materialize:
	$(PYTHON) tools/pipeline/materialize_npc_actors.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-actors:
	$(PYTHON) tools/pipeline/validate_npc_actors.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-spawn-placement:
	$(PYTHON) tools/pipeline/validate_npc_spawn_placement.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-route-binding:
	$(PYTHON) tools/pipeline/validate_npc_route_binding.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Runtime behavior --------------------------------------------------
validate-npc-runtime-core:
	$(PYTHON) tools/pipeline/validate_npc_runtime_core.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-perception:
	$(PYTHON) tools/pipeline/validate_npc_perception.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-movement:
	$(PYTHON) tools/pipeline/validate_npc_movement.py --pack $(PACK) $(if $(STRICT),--strict,)
run-npc-behavior-sample:
	$(PYTHON) tools/pipeline/run_npc_behavior_batch.py --scenarios $(if $(SCENARIOS),$(SCENARIOS),12) $(if $(STRICT),--strict,)
run-encounter-behavior-forge-alpha:
	$(PYTHON) tools/pipeline/run_npc_behavior_batch.py --gate --scenarios $(if $(SCENARIOS),$(SCENARIOS),120) $(if $(STRICT),--strict,)
validate-npc-telemetry:
	$(PYTHON) tools/pipeline/validate_npc_telemetry.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-completion:
	$(PYTHON) tools/pipeline/validate_npc_completion.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-save-load:
	$(PYTHON) tools/pipeline/validate_npc_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Balance -----------------------------------------------------------
classify-npc-pressure:
	$(PYTHON) tools/pipeline/classify_npc_pressure.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-balance:
	$(PYTHON) tools/pipeline/validate_npc_balance.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Hostile validation ------------------------------------------------
npc-negative-validators:
	$(PYTHON) tools/pipeline/npc_behavior_negatives.py $(if $(STRICT),--strict,)
npc-behavior-torture:
	$(PYTHON) tools/pipeline/npc_behavior_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
npc-report-integrity:
	$(PYTHON) tools/pipeline/npc_report_integrity.py --pack $(PACK) $(if $(STRICT),--strict,)
npc-fuzz:
	$(PYTHON) tools/pipeline/npc_behavior_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)

# --- Shield ------------------------------------------------------------
v1-7-shield:
	$(PYTHON) tools/pipeline/v1_7_shield.py --pack $(PACK) $(if $(STRICT),--strict,) \
	  $(if $(DEEP),--deep,) $(if $(TORTURE),--torture,) $(if $(NPC),--npc,) \
	  $(if $(BEHAVIOR),--behavior,) $(if $(REQUIRE_LIVE),--require-live,) \
	  $(if $(SCENARIOS),--scenarios $(SCENARIOS),)

.PHONY: npc-contracts npc-archetypes npc-spawn-groups npc-behavior-profiles npc-behavior-scenarios \
	validate-npc-behavior-scenarios npc-materialize validate-npc-actors validate-npc-spawn-placement \
	validate-npc-route-binding validate-npc-runtime-core validate-npc-perception validate-npc-movement \
	run-npc-behavior-sample run-encounter-behavior-forge-alpha validate-npc-telemetry \
	validate-npc-completion validate-npc-save-load classify-npc-pressure validate-npc-balance \
	npc-negative-validators npc-behavior-torture npc-report-integrity npc-fuzz v1-7-shield

# ======================================================================
# v1.8 CombatForge Alpha — runtime combat pressure (Agent 0)
# ----------------------------------------------------------------------
# Turns v1.7 NPC behavior pressure into real runtime combat pressure: NPC
# pressure and hazards produce damage, player health mutates at runtime, mission
# completion must remain possible under baseline. Every target maps 1:1 to a
# python tools/pipeline/<script>.py entrypoint. Gates are FAIL-CLOSED: a target
# whose script is not yet built errors (non-zero), turning v1-8-shield RED until
# it is implemented and green. Hard non-goals: no weapons/abilities/boss/tactical
# AI/cover/navmesh — only that damage happens, health mutates, and baseline stays
# winnable, all provably (no fake combat success).
#
#   make v1-8-shield PACK=encounter_loop_world STRICT=1 REQUIRE_LIVE=1 COMBAT=1 BEHAVIOR=1 TORTURE=1
# ======================================================================
COMBAT_PACK ?= encounter_loop_world

# --- Contracts + profiles ---------------------------------------------
combat-contracts:
	$(PYTHON) tools/pipeline/validate_combat_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
combat-profiles:
	$(PYTHON) tools/pipeline/generate_combat_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-combat-profiles:
	$(PYTHON) tools/pipeline/validate_combat_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Runtime combat ----------------------------------------------------
validate-combat-runtime-core:
	$(PYTHON) tools/pipeline/validate_combat_runtime_core.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-npc-damage-bridge:
	$(PYTHON) tools/pipeline/validate_npc_damage_bridge.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-hazard-combat:
	$(PYTHON) tools/pipeline/validate_hazard_combat.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-player-health:
	$(PYTHON) tools/pipeline/validate_player_health.py --pack $(PACK) $(if $(STRICT),--strict,)
run-combat-forge-sample:
	$(PYTHON) tools/pipeline/run_combat_forge_alpha.py --scenarios $(if $(SCENARIOS),$(SCENARIOS),12) $(if $(STRICT),--strict,)
run-combat-forge-alpha:
	$(PYTHON) tools/pipeline/run_combat_forge_alpha.py --gate --scenarios $(if $(SCENARIOS),$(SCENARIOS),120) $(if $(STRICT),--strict,)
validate-combat-telemetry:
	$(PYTHON) tools/pipeline/validate_combat_telemetry.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-combat-completion:
	$(PYTHON) tools/pipeline/validate_combat_completion.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-combat-save-load:
	$(PYTHON) tools/pipeline/validate_combat_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Balance / survivability -------------------------------------------
classify-combat-balance:
	$(PYTHON) tools/pipeline/classify_combat_balance.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-combat-balance:
	$(PYTHON) tools/pipeline/validate_combat_balance.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Hostile validation ------------------------------------------------
combat-negative-validators:
	$(PYTHON) tools/pipeline/combat_negatives.py $(if $(STRICT),--strict,)
combat-torture:
	$(PYTHON) tools/pipeline/combat_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
combat-report-integrity:
	$(PYTHON) tools/pipeline/combat_report_integrity.py --pack $(PACK) $(if $(STRICT),--strict,)
combat-fuzz:
	$(PYTHON) tools/pipeline/combat_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)

# --- Shield ------------------------------------------------------------
v1-8-shield:
	$(PYTHON) tools/pipeline/v1_8_shield.py --pack $(PACK) $(if $(STRICT),--strict,) \
	  $(if $(COMBAT),--combat,) $(if $(BEHAVIOR),--behavior,) $(if $(TORTURE),--torture,) \
	  $(if $(REQUIRE_LIVE),--require-live,) $(if $(SCENARIOS),--scenarios $(SCENARIOS),)

.PHONY: combat-contracts combat-profiles validate-combat-profiles validate-combat-runtime-core \
	validate-npc-damage-bridge validate-hazard-combat validate-player-health run-combat-forge-sample \
	run-combat-forge-alpha validate-combat-telemetry validate-combat-completion validate-combat-save-load \
	classify-combat-balance validate-combat-balance combat-negative-validators combat-torture \
	combat-report-integrity combat-fuzz v1-8-shield

# ======================================================================
# v1.9 LoadoutForge + RewardForge + ProgressionForge Alpha (Agent 0)
# ----------------------------------------------------------------------
# Turns mission/combat completion into durable loadout, reward, inventory,
# unlock, and progression consequence. FAIL-CLOSED: a gate whose script is
# not yet built turns v1-9-shield RED until it exists (no fake green).
# NOTE: `make` is not installed in this environment; these targets document
# the canonical command surface — run the mapped `python tools/pipeline/*.py`
# directly. Wave 1 ships the contract spine + fail-closed shield; Waves 2/R/7
# fill the authoring, runtime, and hostile gates.
#
#   make v1-9-shield PACK=encounter_loop_world STRICT=1 REWARDS=1 PROGRESSION=1
# ======================================================================
REWARD_PACK ?= encounter_loop_world

# --- Contract spine ----------------------------------------------------
loadout-contracts:
	$(PYTHON) tools/pipeline/validate_loadout_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
reward-contracts:
	$(PYTHON) tools/pipeline/validate_reward_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
progression-contracts:
	$(PYTHON) tools/pipeline/validate_progression_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Reward-table / catalog authoring (Wave 2/3) -----------------------
reward-tables:
	$(PYTHON) tools/pipeline/generate_reward_tables.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-reward-tables:
	$(PYTHON) tools/pipeline/validate_reward_tables.py --pack $(PACK) $(if $(STRICT),--strict,)
classify-risk-reward:
	$(PYTHON) tools/pipeline/classify_risk_reward.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-risk-reward:
	$(PYTHON) tools/pipeline/validate_risk_reward.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Progression / inventory / unlock state + persistence (Wave 2/R) ---
progression-state:
	$(PYTHON) tools/pipeline/generate_progression_state.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-progression-state:
	$(PYTHON) tools/pipeline/validate_progression_state.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-unlock-state:
	$(PYTHON) tools/pipeline/validate_unlock_state.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-inventory-save-load:
	$(PYTHON) tools/pipeline/validate_inventory_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-progression-save-load:
	$(PYTHON) tools/pipeline/validate_progression_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-next-mission-state:
	$(PYTHON) tools/pipeline/validate_next_mission_state.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Runtime reward bridge (Wave R) ------------------------------------
run-reward-forge-alpha:
	$(PYTHON) tools/pipeline/run_reward_forge_alpha.py --gate --scenarios $(if $(SCENARIOS),$(SCENARIOS),120) $(if $(STRICT),--strict,)
validate-reward-bridge:
	$(PYTHON) tools/pipeline/validate_reward_bridge.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Hostile validation (Wave 7) ---------------------------------------
reward-negative-validators:
	$(PYTHON) tools/pipeline/reward_negatives.py $(if $(STRICT),--strict,)
reward-fuzz:
	$(PYTHON) tools/pipeline/reward_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)
reward-torture:
	$(PYTHON) tools/pipeline/reward_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
reward-report-integrity:
	$(PYTHON) tools/pipeline/reward_report_integrity.py --pack $(PACK) $(if $(STRICT),--strict,)
reward-hygiene:
	$(PYTHON) tools/pipeline/reward_hygiene.py $(if $(STRICT),--strict,)

# --- Shield ------------------------------------------------------------
v1-9-shield:
	$(PYTHON) tools/pipeline/v1_9_shield.py --pack $(PACK) $(if $(STRICT),--strict,) \
	  $(if $(REWARDS),--rewards,) $(if $(PROGRESSION),--progression,) $(if $(TORTURE),--torture,) \
	  $(if $(REQUIRE_LIVE),--require-live,) $(if $(SCENARIOS),--scenarios $(SCENARIOS),)

.PHONY: loadout-contracts reward-contracts progression-contracts reward-tables validate-reward-tables \
	classify-risk-reward validate-risk-reward progression-state validate-progression-state \
	validate-unlock-state validate-inventory-save-load validate-progression-save-load \
	validate-next-mission-state run-reward-forge-alpha validate-reward-bridge \
	reward-negative-validators reward-fuzz reward-torture reward-report-integrity reward-hygiene v1-9-shield

# ======================================================================
# v2.0 VerticalSliceForge — Vertical Slice (Agent 0)
# ----------------------------------------------------------------------
# Integrates the v1.5-v1.9 substrates into one generated playable slice.
# FAIL-CLOSED: a gate whose script is not yet built turns v2-0-shield RED
# until it exists (no fake green). NOTE: `make` is not installed in this
# environment; these targets document the canonical command surface — run
# the mapped `python tools/pipeline/*.py` directly (PYTHONUTF8=1 on Windows).
#   python tools/pipeline/v2_0_shield.py --pack encounter_loop_world \
#     --strict --slices --require-live --package --torture
# ======================================================================
SLICE_PACK ?= encounter_loop_world

# --- Contract spine (Wave 1, GREEN) ------------------------------------
vertical-slice-contracts:
	$(PYTHON) tools/pipeline/validate_vertical_slice_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-makefile-refs:
	$(PYTHON) tools/pipeline/validate_makefile_refs.py $(if $(STRICT),--strict,)

# --- Slice authoring (Wave 2) ------------------------------------------
generate-slice-scenarios:
	$(PYTHON) tools/pipeline/generate_slice_scenarios.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-slice-scenarios:
	$(PYTHON) tools/pipeline/validate_slice_scenarios.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-slice-environment:
	$(PYTHON) tools/pipeline/validate_slice_environment.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-slice-assets:
	$(PYTHON) tools/pipeline/validate_slice_assets.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Runtime slice matrix (Wave R) -------------------------------------
# The UE build is bundled into packaging (RunUAT BuildCookRun does build+cook+
# stage in one pass), so build-vertical-slice and package-slice share one script.
build-vertical-slice:
	$(PYTHON) tools/pipeline/package_slice.py --pack $(PACK) $(if $(STRICT),--strict,)
run-vertical-slice-runtime:
	$(PYTHON) tools/pipeline/run_slice_forge_alpha.py --run --pack $(PACK) $(if $(SCENARIOS),--scenarios $(SCENARIOS),--scenarios 24) $(if $(STRICT),--strict,)
validate-slice-traversal:
	$(PYTHON) tools/pipeline/validate_slice_traversal.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-slice-npc-combat:
	$(PYTHON) tools/pipeline/validate_slice_npc_combat.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-slice-rewards:
	$(PYTHON) tools/pipeline/validate_slice_rewards.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-slice-save-load:
	$(PYTHON) tools/pipeline/validate_slice_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)
build-slice-evidence-index:
	$(PYTHON) tools/pipeline/run_slice_forge_alpha.py --index $(if $(STRICT),--strict,)
validate-slice-evidence-index:
	$(PYTHON) tools/pipeline/validate_slice_evidence_index.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Package proof (Wave P) --------------------------------------------
package-slice:
	$(PYTHON) tools/pipeline/package_slice.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-slice-package:
	$(PYTHON) tools/pipeline/validate_slice_package.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Hostile validation (Agent 7) --------------------------------------
vertical-slice-negative-validators:
	$(PYTHON) tools/pipeline/slice_negatives.py $(if $(STRICT),--strict,)
vertical-slice-fuzz:
	$(PYTHON) tools/pipeline/slice_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)
vertical-slice-torture:
	$(PYTHON) tools/pipeline/slice_torture.py --pack $(PACK) $(if $(STRICT),--strict,)
vertical-slice-report-integrity:
	$(PYTHON) tools/pipeline/slice_report_integrity.py --pack $(PACK) $(if $(STRICT),--strict,)
vertical-slice-hygiene:
	$(PYTHON) tools/pipeline/slice_hygiene.py $(if $(STRICT),--strict,)

# --- Shield ------------------------------------------------------------
v2-0-shield:
	$(PYTHON) tools/pipeline/v2_0_shield.py --pack $(PACK) $(if $(STRICT),--strict,) \
	  $(if $(SLICES),--slices,) $(if $(REQUIRE_LIVE),--require-live,) \
	  $(if $(PACKAGE),--package,) $(if $(TORTURE),--torture,) \
	  $(if $(REGRESSIONS),--regressions,) $(if $(SCENARIOS),--scenarios $(SCENARIOS),)

.PHONY: vertical-slice-contracts validate-makefile-refs generate-slice-scenarios validate-slice-scenarios \
	validate-slice-environment validate-slice-assets build-vertical-slice \
	run-vertical-slice-runtime validate-slice-traversal validate-slice-npc-combat \
	validate-slice-rewards validate-slice-save-load build-slice-evidence-index validate-slice-evidence-index \
	package-slice validate-slice-package vertical-slice-negative-validators \
	vertical-slice-fuzz vertical-slice-torture vertical-slice-report-integrity \
	vertical-slice-hygiene v2-0-shield

# ======================================================================
# v2.1 OperatorForge — operator control plane (Agent 0)
# ----------------------------------------------------------------------
# Turns WorldForge's evidence sprawl into an operator-readable surface:
# report index + evidence graph, static pack/scenario/evidence/failure/
# asset/route dashboard, safe bounded command launcher, and run diffs.
# FAIL-CLOSED: a gate whose script is not yet built turns v2-1-shield RED
# until it exists (no fake green). NOTE: `make` is not installed in this
# environment; these targets document the canonical command surface — run
# the mapped `python tools/operator/*.py` (or tools/pipeline/*.py for the
# shield) directly (PYTHONUTF8=1 on Windows). Operator scripts live under
# tools/operator/ so they are additive to the tools/pipeline/ surface.
#   python tools/pipeline/v2_1_shield.py --strict --operator
# ======================================================================
OPERATOR_PACK ?= worldforge_vertical_slice

# --- Contract spine (Wave 1, GREEN) ------------------------------------
operator-contracts:
	$(PYTHON) tools/operator/validate_operator_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
operator-negative-fixtures:
	$(PYTHON) tools/operator/operator_negatives.py $(if $(STRICT),--strict,)

# --- Report index + evidence graph (Wave 2) ----------------------------
operator-index-reports:
	$(PYTHON) tools/operator/index_reports.py $(if $(STRICT),--strict,)
validate-operator-index:
	$(PYTHON) tools/operator/validate_operator_index.py $(if $(STRICT),--strict,)

# --- Static dashboard + per-view builders (Wave 3) ---------------------
operator-dashboard:
	$(PYTHON) tools/operator/build_dashboard.py $(if $(STRICT),--strict,)
operator-smoke:
	$(PYTHON) tools/operator/operator_smoke.py $(if $(STRICT),--strict,)
operator-evidence-view:
	$(PYTHON) tools/operator/validate_operator_evidence.py $(if $(STRICT),--strict,)
operator-failure-index:
	$(PYTHON) tools/operator/build_failure_index.py $(if $(STRICT),--strict,)
operator-asset-ownership:
	$(PYTHON) tools/operator/build_asset_ownership.py $(if $(STRICT),--strict,)
operator-route-view:
	$(PYTHON) tools/operator/build_route_view.py $(if $(STRICT),--strict,)

# --- Safe command launcher + diff (Wave 4) -----------------------------
operator-command-dry-run:
	$(PYTHON) tools/operator/operator_command.py --dry-run --command operator-index-reports $(if $(STRICT),--strict,)
operator-diff-runs:
	$(PYTHON) tools/operator/diff_operator_runs.py $(if $(STRICT),--strict,)
operator-command-negative-validators:
	$(PYTHON) tools/operator/operator_command_negatives.py $(if $(STRICT),--strict,)

# --- Hostile validation (Wave R) ---------------------------------------
operator-negative-validators:
	$(PYTHON) tools/operator/operator_negatives.py $(if $(STRICT),--strict,)
operator-fuzz:
	$(PYTHON) tools/operator/operator_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)
operator-torture:
	$(PYTHON) tools/operator/operator_torture.py $(if $(STRICT),--strict,)
operator-report-integrity:
	$(PYTHON) tools/operator/operator_report_integrity.py $(if $(STRICT),--strict,)
operator-hygiene:
	$(PYTHON) tools/operator/operator_hygiene.py $(if $(STRICT),--strict,)

# --- Shield ------------------------------------------------------------
v2-1-shield:
	$(PYTHON) tools/pipeline/v2_1_shield.py --pack $(PACK) $(if $(STRICT),--strict,) \
	  $(if $(OPERATOR),--operator,) $(if $(REGRESSIONS),--regressions,)

.PHONY: operator-contracts operator-negative-fixtures operator-index-reports \
	validate-operator-index operator-dashboard operator-smoke operator-evidence-view \
	operator-failure-index operator-asset-ownership operator-route-view \
	operator-command-dry-run operator-diff-runs operator-command-negative-validators \
	operator-negative-validators operator-fuzz operator-torture \
	operator-report-integrity operator-hygiene v2-1-shield

# ======================================================================
# v2.2 QuestForge + FactionStateForge — stateful quest/faction consequence
# ----------------------------------------------------------------------
# The first stateful narrative-consequence substrate for WorldForge: bounded
# quests (a validated state machine over v2.0 scenario actions), factions
# (persistent bounded state vectors), and consequence continuity (deltas +
# ledgers + next-mission state) over the 24-scenario vertical-slice matrix.
# NOT a story campaign / dialogue / lore system (handoff §4).
# FAIL-CLOSED: a gate whose script is not yet built turns v2-2-shield RED
# until it exists (no fake green). Targets are added per wave as their scripts
# land (validate_makefile_refs asserts every tools/pipeline ref resolves).
# NOTE: `make` is not installed in this environment; these targets document the
# canonical command surface — run the mapped `python tools/pipeline/*.py` (or
# tools/operator/*.py) directly (PYTHONUTF8=1 on Windows). e.g.
#   python tools/pipeline/v2_2_shield.py --strict --quests --factions
# ======================================================================
QUEST_FACTION_PACK ?= worldforge_vertical_slice

# --- Contract spine (Wave 1, GREEN) ------------------------------------
quest-contracts:
	$(PYTHON) tools/pipeline/validate_quest_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
faction-contracts:
	$(PYTHON) tools/pipeline/validate_faction_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
quest-faction-contracts:
	$(PYTHON) tools/pipeline/validate_quest_faction_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
quest-faction-negative-fixtures:
	$(PYTHON) tools/pipeline/quest_faction_negatives.py $(if $(STRICT),--strict,)

# --- Authoring generators (Wave 2) -------------------------------------
generate-quests:
	$(PYTHON) tools/pipeline/generate_quests.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-generated-quests:
	$(PYTHON) tools/pipeline/validate_generated_quests.py --pack $(PACK) $(if $(STRICT),--strict,)
generate-factions:
	$(PYTHON) tools/pipeline/generate_factions.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-generated-factions:
	$(PYTHON) tools/pipeline/validate_generated_factions.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Runtime quest/faction proof (Wave 3) ------------------------------
run-quest-faction-smoke:
	$(PYTHON) tools/pipeline/run_quest_faction_alpha.py --smoke $(if $(STRICT),--strict,)
run-quest-faction-runtime:
	$(PYTHON) tools/pipeline/run_quest_faction_alpha.py --gate --scenarios $(if $(SCENARIOS),$(SCENARIOS),24) $(if $(STRICT),--strict,)
validate-quest-faction-runtime:
	$(PYTHON) tools/pipeline/validate_quest_faction_runtime.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-quest-faction-save-load:
	$(PYTHON) tools/pipeline/validate_quest_faction_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- OperatorForge quest/faction views (Wave 4) ------------------------
operator-quest-faction-index:
	$(PYTHON) tools/operator/build_quest_faction_index.py $(if $(STRICT),--strict,)
operator-quest-faction-dashboard:
	$(PYTHON) tools/operator/build_quest_faction_dashboard.py $(if $(STRICT),--strict,)
operator-quest-faction-smoke:
	$(PYTHON) tools/operator/quest_faction_operator_smoke.py $(if $(STRICT),--strict,)

# --- Hostile validation (Wave R) ---------------------------------------
quest-faction-negative-validators:
	$(PYTHON) tools/pipeline/quest_faction_negative_validators.py $(if $(STRICT),--strict,)
quest-faction-fuzz:
	$(PYTHON) tools/pipeline/quest_faction_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)
quest-faction-torture:
	$(PYTHON) tools/pipeline/quest_faction_torture.py $(if $(STRICT),--strict,)
quest-faction-report-integrity:
	$(PYTHON) tools/pipeline/quest_faction_report_integrity.py $(if $(STRICT),--strict,)
quest-faction-hygiene:
	$(PYTHON) tools/pipeline/quest_faction_hygiene.py $(if $(STRICT),--strict,)

# --- Shield ------------------------------------------------------------
v2-2-shield:
	$(PYTHON) tools/pipeline/v2_2_shield.py --pack $(PACK) $(if $(STRICT),--strict,) \
	  $(if $(QUESTS),--quests,) $(if $(FACTIONS),--factions,) \
	  $(if $(SCENARIOS),--scenarios $(SCENARIOS),) $(if $(REGRESSIONS),--regressions,)

.PHONY: quest-contracts faction-contracts quest-faction-contracts \
	quest-faction-negative-fixtures generate-quests validate-generated-quests \
	generate-factions validate-generated-factions run-quest-faction-smoke \
	run-quest-faction-runtime validate-quest-faction-runtime \
	validate-quest-faction-save-load operator-quest-faction-index \
	operator-quest-faction-dashboard operator-quest-faction-smoke \
	quest-faction-negative-validators quest-faction-fuzz quest-faction-torture \
	quest-faction-report-integrity quest-faction-hygiene v2-2-shield

# ======================================================================
# v2.3 StreamingForge / WorldScaleForge — cross-tile generated regions
# ----------------------------------------------------------------------
# The first cross-tile generated-region substrate: bounded regions composed
# of streamable tiles connected by stable cross-tile anchors + routes, with
# runtime tile lifecycle, cross-tile save/load continuity, and declared
# streaming/package budgets — over the v2.0 slice + v2.2 quest/faction stack.
# NOT a full open world / multiplayer / final World Partition (handoff §4).
# FAIL-CLOSED: a gate whose script is not yet built turns v2-3-shield RED
# until it exists. Targets added per wave as their scripts land
# (validate_makefile_refs asserts every tools/pipeline ref resolves).
# NOTE: `make` is not installed here; these targets document the canonical
# surface — run the mapped `python tools/pipeline|operator/*.py` directly
# (PYTHONUTF8=1 on Windows). e.g.
#   python tools/pipeline/v2_3_shield.py --strict --streaming --worldscale
# ======================================================================
STREAMING_PACK ?= worldforge_vertical_slice

# --- Contract spine (Wave 1, GREEN) ------------------------------------
streaming-contracts:
	$(PYTHON) tools/pipeline/validate_streaming_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
streaming-negative-fixtures:
	$(PYTHON) tools/pipeline/streaming_negatives.py $(if $(STRICT),--strict,)

# --- Authoring generators (Wave 2) -------------------------------------
generate-streaming-regions:
	$(PYTHON) tools/pipeline/generate_streaming_regions.py --pack $(PACK) $(if $(STRICT),--strict,)
generate-cross-tile-anchors:
	$(PYTHON) tools/pipeline/generate_cross_tile_anchors.py --pack $(PACK) $(if $(STRICT),--strict,)
generate-cross-tile-routes:
	$(PYTHON) tools/pipeline/generate_cross_tile_routes.py --pack $(PACK) $(if $(STRICT),--strict,)
generate-streamed-bindings:
	$(PYTHON) tools/pipeline/generate_streamed_bindings.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-streaming-authoring:
	$(PYTHON) tools/pipeline/validate_streaming_authoring.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Runtime + lifecycle (Wave 3) --------------------------------------
run-streaming-smoke:
	$(PYTHON) tools/pipeline/run_streaming_forge_alpha.py --smoke $(if $(STRICT),--strict,)
run-streaming-runtime:
	$(PYTHON) tools/pipeline/run_streaming_forge_alpha.py --gate --scenarios $(if $(SCENARIOS),$(SCENARIOS),24) $(if $(STRICT),--strict,)
validate-streaming-runtime:
	$(PYTHON) tools/pipeline/validate_streaming_runtime.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Cross-tile save/load + budgets (Wave 4) ---------------------------
validate-streaming-save-load:
	$(PYTHON) tools/pipeline/validate_streaming_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-streaming-budgets:
	$(PYTHON) tools/pipeline/validate_streaming_budgets.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- OperatorForge region/tile views (Wave 5) --------------------------
operator-streaming-index:
	$(PYTHON) tools/operator/build_streaming_index.py $(if $(STRICT),--strict,)
operator-streaming-dashboard:
	$(PYTHON) tools/operator/build_streaming_dashboard.py $(if $(STRICT),--strict,)
operator-streaming-smoke:
	$(PYTHON) tools/operator/streaming_operator_smoke.py $(if $(STRICT),--strict,)

# --- Hostile validation (Wave R) ---------------------------------------
streaming-negative-validators:
	$(PYTHON) tools/pipeline/streaming_negative_validators.py $(if $(STRICT),--strict,)
streaming-fuzz:
	$(PYTHON) tools/pipeline/streaming_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)
streaming-torture:
	$(PYTHON) tools/pipeline/streaming_torture.py $(if $(STRICT),--strict,)
streaming-report-integrity:
	$(PYTHON) tools/pipeline/streaming_report_integrity.py $(if $(STRICT),--strict,)
streaming-hygiene:
	$(PYTHON) tools/pipeline/streaming_hygiene.py $(if $(STRICT),--strict,)

# --- Shield ------------------------------------------------------------
v2-3-shield:
	$(PYTHON) tools/pipeline/v2_3_shield.py --pack $(PACK) $(if $(STRICT),--strict,) \
	  $(if $(STREAMING),--streaming,) $(if $(WORLDSCALE),--worldscale,) \
	  $(if $(SCENARIOS),--scenarios $(SCENARIOS),) $(if $(REGRESSIONS),--regressions,)

.PHONY: streaming-contracts streaming-negative-fixtures generate-streaming-regions \
	generate-cross-tile-anchors generate-cross-tile-routes generate-streamed-bindings \
	validate-streaming-authoring run-streaming-smoke run-streaming-runtime \
	validate-streaming-runtime validate-streaming-save-load validate-streaming-budgets \
	operator-streaming-index operator-streaming-dashboard operator-streaming-smoke \
	streaming-negative-validators streaming-fuzz streaming-torture \
	streaming-report-integrity streaming-hygiene v2-3-shield

# ======================================================================
# v2.4 AdvancedAIForge / TacticalBehaviorForge — bounded tactical behavior
# ----------------------------------------------------------------------
# The first bounded tactical-behavior substrate: generated NPCs making
# BOUNDED, INSPECTABLE tactical decisions over terrain, routes, cover,
# objectives, mission/quest/faction context, and streaming tile scope —
# over the v2.3 streaming regions + v2.2 quest/faction stack. Every tactical
# decision records its inputs, options, constraints, selected action,
# execution result, and state mutation, and validates against contracts.
# NOT AAA combat AI, a GOAP planner, a behavior-tree editor, EQS, RL, or an
# LLM-driven NPC (handoff §4).
# FAIL-CLOSED: a gate whose script is not yet built turns v2-4-shield RED
# until it exists. Targets are added per wave as their scripts land
# (validate_makefile_refs asserts every tools/pipeline ref resolves).
# NOTE: `make` is not installed here; these targets document the canonical
# surface — run the mapped `python tools/pipeline|operator/*.py` directly
# (PYTHONUTF8=1 on Windows). e.g.
#   python tools/pipeline/v2_4_shield.py --strict --tactical --advanced-ai
# ======================================================================
TACTICAL_PACK ?= worldforge_vertical_slice

# --- Contract spine (Wave 1, GREEN) ------------------------------------
tactical-contracts:
	$(PYTHON) tools/pipeline/validate_tactical_contracts.py --pack $(PACK) $(if $(STRICT),--strict,)
tactical-negative-fixtures:
	$(PYTHON) tools/pipeline/tactical_negatives.py $(if $(STRICT),--strict,)

# --- Profile/role/affordance authoring (Wave 2) ------------------------
generate-tactical-profiles:
	$(PYTHON) tools/pipeline/generate_tactical_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-tactical-profiles:
	$(PYTHON) tools/pipeline/validate_tactical_profiles.py --pack $(PACK) $(if $(STRICT),--strict,)
generate-tactical-affordances:
	$(PYTHON) tools/pipeline/generate_tactical_affordances.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-tactical-affordances:
	$(PYTHON) tools/pipeline/validate_tactical_affordances.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- NPC/group bindings (Wave 3) ---------------------------------------
generate-tactical-bindings:
	$(PYTHON) tools/pipeline/generate_tactical_bindings.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-tactical-bindings:
	$(PYTHON) tools/pipeline/validate_tactical_bindings.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Runtime + decision proof (Wave 4) ---------------------------------
run-tactical-smoke:
	$(PYTHON) tools/pipeline/run_tactical_behavior_alpha.py --smoke $(if $(STRICT),--strict,)
run-tactical-runtime:
	$(PYTHON) tools/pipeline/run_tactical_behavior_alpha.py --gate --scenarios $(if $(SCENARIOS),$(SCENARIOS),24) $(if $(STRICT),--strict,)
validate-tactical-runtime:
	$(PYTHON) tools/pipeline/validate_tactical_runtime.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- Save/load + budgets (Wave 5) --------------------------------------
validate-tactical-save-load:
	$(PYTHON) tools/pipeline/validate_tactical_save_load.py --pack $(PACK) $(if $(STRICT),--strict,)
validate-tactical-budgets:
	$(PYTHON) tools/pipeline/validate_tactical_budgets.py --pack $(PACK) $(if $(STRICT),--strict,)

# --- OperatorForge tactical views (Wave 6) -----------------------------
operator-tactical-index:
	$(PYTHON) tools/operator/build_tactical_index.py $(if $(STRICT),--strict,)
operator-tactical-dashboard:
	$(PYTHON) tools/operator/build_tactical_dashboard.py $(if $(STRICT),--strict,)
operator-tactical-smoke:
	$(PYTHON) tools/operator/tactical_operator_smoke.py $(if $(STRICT),--strict,)

# --- Hostile validation (Wave R) ---------------------------------------
tactical-negative-validators:
	$(PYTHON) tools/pipeline/tactical_negative_validators.py $(if $(STRICT),--strict,)
tactical-fuzz:
	$(PYTHON) tools/pipeline/tactical_fuzz.py --cases $(if $(CASES),$(CASES),300) --seed $(if $(SEED),$(SEED),1337) $(if $(STRICT),--strict,)
tactical-torture:
	$(PYTHON) tools/pipeline/tactical_torture.py $(if $(STRICT),--strict,)
tactical-report-integrity:
	$(PYTHON) tools/pipeline/tactical_report_integrity.py $(if $(STRICT),--strict,)
tactical-hygiene:
	$(PYTHON) tools/pipeline/tactical_hygiene.py $(if $(STRICT),--strict,)

# --- Shield ------------------------------------------------------------
v2-4-shield:
	$(PYTHON) tools/pipeline/v2_4_shield.py --pack $(PACK) $(if $(STRICT),--strict,) \
	  $(if $(TACTICAL),--tactical,) $(if $(ADVANCED_AI),--advanced-ai,) \
	  $(if $(SCENARIOS),--scenarios $(SCENARIOS),) $(if $(REGRESSIONS),--regressions,)

.PHONY: tactical-contracts tactical-negative-fixtures generate-tactical-profiles \
	validate-tactical-profiles generate-tactical-affordances validate-tactical-affordances \
	generate-tactical-bindings validate-tactical-bindings run-tactical-smoke \
	run-tactical-runtime validate-tactical-runtime validate-tactical-save-load \
	validate-tactical-budgets operator-tactical-index operator-tactical-dashboard \
	operator-tactical-smoke tactical-negative-validators tactical-fuzz tactical-torture \
	tactical-report-integrity tactical-hygiene v2-4-shield
