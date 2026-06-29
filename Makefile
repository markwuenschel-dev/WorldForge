# UE5 Procedural Pipeline Makefile

PYTHON := python
UE_PYTHON := python

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
        create-world-pack validate-world-pack \
        ue-doctor \
        create-terrain validate-terrain import-terrain \
        create-poi validate-poi \
        run-state-sim validate-runtime-state apply-state-scenario \
        register-generated-asset validate-generated-asset relocate-houdini-asset

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
	  $(if $(DEEP),--deep,)

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

validate-world-pack:
	$(PYTHON) tools/pipeline/validate_world_pack.py --pack procedural/world_packs/$(PACK).yaml \
	  $(if $(DEEP),--deep,)

# v0.5 — pre-flight
ue-doctor:
	$(PYTHON) tools/pipeline/ue_doctor.py

# v0.6 — TerrainForge Lite
# Generate deterministic terrain artifacts from a terrain recipe.
#   RECIPE  terrain recipe id (procedural/definitions/terrain/<RECIPE>.yaml)
#   NAME    output terrain name (e.g. Terrain_AshFlats_01)
create-terrain:
	$(PYTHON) tools/pipeline/create_terrain.py --recipe $(RECIPE) --name $(NAME)

# Validate generated terrain artifacts (pure Python; no UE required).
validate-terrain:
	$(PYTHON) tools/pipeline/validate_terrain.py --name $(NAME)

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
	$(PYTHON) tools/pipeline/validate_poi.py --name $(NAME)

# v0.8 — Runtime StateForge (make generated worlds react and remember)
# Authoring-side scenario simulation: mutate + aggregate state, expect the MPC
# effect + POI evidence, and prove a save/load round-trip. Pure Python; no UE.
#   NAME      target slice id / Region context_id
#   SCENARIO  scenario id (procedural/definitions/scenarios/<SCENARIO>.yaml)
run-state-sim:
	$(PYTHON) tools/pipeline/run_state_sim.py --name $(NAME) --scenario $(SCENARIO) --force

validate-runtime-state:
	$(PYTHON) tools/pipeline/validate_runtime_state.py --name $(NAME) \
	  $(if $(SCENARIO),--scenario $(SCENARIO),)

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
	$(PYTHON) tools/pipeline/validate_generated_asset.py --asset $(ASSET)

# UE-side: duplicate the baked Houdini asset out of /Game/HoudiniEngine/Bake into
# the WorldForge-owned tree and assert it is a StaticMesh (requires editor).
relocate-houdini-asset:
	$(UE_PYTHON) tools/unreal/relocate_houdini_asset.py \
	  --descriptor procedural/generated/generated_assets/$(ASSET)/descriptor.json --project-root .

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
