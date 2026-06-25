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
        create-slice-spec prepare-slice create-slice-map validate-slice create-slice

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

create-slice-spec:
	$(PYTHON) tools/pipeline/create_slice_spec.py --biome $(BIOME) --variant $(VARIANT) --name $(NAME)

prepare-slice:
	$(PYTHON) tools/pipeline/prepare_slice.py --spec $(SPEC)

create-slice-map:
	$(PYTHON) tools/pipeline/run_slice_ue.py --script create_slice_map.py --spec $(SPEC)

validate-slice:
	$(PYTHON) tools/pipeline/run_slice_ue.py --script validate_slice.py --spec $(SPEC)

create-slice:
	$(MAKE) create-slice-spec BIOME=$(BIOME) VARIANT=$(VARIANT) NAME=$(NAME)
	$(MAKE) prepare-slice SPEC=$(SLICE_SPEC)
	$(MAKE) create-slice-map SPEC=$(SLICE_SPEC)
	$(MAKE) validate-slice SPEC=$(SLICE_SPEC)

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
