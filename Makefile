# UE5 Procedural Pipeline Makefile

PYTHON := python
UE_PYTHON := python

.PHONY: help validate-recipe render-substance generate-manifest placeholder-exports \
        import-textures create-master create-world-state-mpc wire-terrain-soot create-material create-data-asset \
        validate-assets diagnose pre-ue-audit validate-and-manifest preview build clean

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
