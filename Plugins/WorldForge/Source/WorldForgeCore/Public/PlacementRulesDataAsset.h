// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "WorldForgeStateTypes.h"
#include "PlacementRulesDataAsset.generated.h"

/**
 * FPlacementSpeciesRule - one scatter species the PCG graph reads.
 *
 * The PCG graph (human-owned template) reads BaseDensity / scale / mesh from here
 * AND pulls the live world-state value at (StateScope, region cell, StateKey) via
 * UWorldStateSubsystem::GetStateValue, then modulates density by lerping between
 * DensityAtStateZero and DensityAtStateOne (forge_design_decisions D13).
 *
 * The RESPONSE (the two endpoints) is baked here; the STATE VALUE is read live.
 * Never bake the resolved state value into the Data Asset - that kills runtime
 * reactivity (D13).
 */
USTRUCT(BlueprintType)
struct FPlacementSpeciesRule
{
	GENERATED_BODY()

	/** Stable species identifier (e.g. "dead_scrub"). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	FName SpeciesId;

	/**
	 * Mesh scattered for this species, as a soft path. The PCG graph resolves/loads
	 * it; the plugin never hard-loads content. FSoftObjectPath (not TSoftObjectPtr)
	 * so tooling can author a path to content that lives in the consuming game
	 * project and doesn't exist here. AllowedClasses keeps the editor picker typed.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement",
		meta = (AllowedClasses = "/Script/Engine.StaticMesh"))
	FSoftObjectPath Mesh;

	/** Base scatter density (target instances per 100 m^2) before state modulation. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	float BaseDensity = 0.f;

	/** Minimum uniform instance scale. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	float ScaleMin = 1.f;

	/** Maximum uniform instance scale. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	float ScaleMax = 1.f;

	/** Scope of the world-state value that modulates this species' density. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	EWorldForgeStateScope StateScope = EWorldForgeStateScope::Region;

	/** World-state key that modulates this species (e.g. "restoration_level"). NAME_None = unmodulated. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	FName StateKey;

	/** Density multiplier when the state value is 0.0. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	float DensityAtStateZero = 1.f;

	/** Density multiplier when the state value is 1.0. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	float DensityAtStateOne = 1.f;
};

/**
 * UPlacementRulesDataAsset - the state-aware rules record one FoliageSpawnRules
 * definition produces. The second state-aware consumer after the material MPC
 * tracer (forge_design_decisions D13).
 *
 * Two jobs, mirroring MaterialRecipeDataAsset's provenance shape but ADDING a
 * runtime-read payload:
 *   1. Provenance + linkage: "which definition / commit / manifest produced this?"
 *   2. Runtime rules: the PCG graph reads Species[] from here and pulls live state
 *      per cell to modulate density (it never reads the YAML).
 *
 * Plain UDataAsset with the same upgrade trigger as MaterialRecipeDataAsset (D3):
 * promote to UPrimaryDataAsset only when a runtime system must discover/enumerate/
 * async-load rulesets by id/tag. Provenance fields are authored by tooling
 * (create_placement_data_asset.py) and copied verbatim from the manifest.
 */
UCLASS(BlueprintType)
class WORLDFORGECORE_API UPlacementRulesDataAsset : public UDataAsset
{
	GENERATED_BODY()

public:
	// --- Identity ------------------------------------------------------------

	/** Stable definition identifier (e.g. "reclaimed_desert_foliage"). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Identity")
	FName RulesId;

	/** Definition/manifest schema version the asset was generated against. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Identity")
	FString SchemaVersion;

	/** Biome this ruleset belongs to (e.g. "reclaimed_desert"). Free-form linkage. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Identity")
	FName Biome;

	// --- Runtime rules (read by the PCG graph) -------------------------------

	/** Path to the human-owned PCG graph template this ruleset feeds (recorded, not loaded here). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	FSoftObjectPath PcgGraphTemplate;

	/** The scatter species the PCG graph reads. State is pulled live per cell; never baked. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Placement")
	TArray<FPlacementSpeciesRule> Species;

	// --- Provenance (copied verbatim from the manifest) ----------------------

	/** Repo-relative path to the source FoliageSpawnRules YAML. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString SourceRecipePath;

	/** Repo-relative path to the manifest that produced this asset. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString ManifestPath;

	/** Name of the generator that stamped provenance. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString GeneratorName;

	/** Generator version, so regenerated provenance is traceable. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString GeneratorVersion;

	/** ISO-8601 UTC timestamp of manifest generation (stored as text, copied verbatim). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString GeneratedAtUtc;

	/** Git commit the inputs were generated from. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString SourceCommit;

	/** True if the source inputs were dirty (uncommitted) at generation time. Recorded, never hidden. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	bool bSourceTreeDirty = false;

	/** SHA-256 of the source definition at generation time; lets validation detect stale provenance. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString SourceRecipeHash;
};
