// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "MaterialRecipeDataAsset.generated.h"

class UMaterialInstanceConstant;
class UTexture2D;

/**
 * UMaterialRecipeDataAsset - provenance + linkage record for one generated material.
 *
 * This is NOT a runtime-queried registry. Its single job is to answer
 * "which recipe / params / commit / manifest produced this Material Instance and
 * these textures?" for tooling, validation, audit, and future world-state work.
 *
 * It is a plain UDataAsset with hard object references (see forge_design_decisions
 * D3). Promote to UPrimaryDataAsset only when a runtime system must discover,
 * enumerate, async-load, or bundle recipes by id/type/tag.
 *
 * Every field is authored by tooling (create_data_asset.py) and copied verbatim
 * from the manifest's provenance block; nothing here is hand-edited.
 */
UCLASS(BlueprintType)
class WORLDFORGECORE_API UMaterialRecipeDataAsset : public UDataAsset
{
	GENERATED_BODY()

public:
	// --- Identity ------------------------------------------------------------

	/** Stable recipe identifier (e.g. "terrain_rock_desert_01"). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Identity")
	FName RecipeId;

	/** Recipe/manifest schema version the asset was generated against. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Identity")
	FString SchemaVersion;

	// --- Provenance (copied verbatim from the manifest) ----------------------

	/** Repo-relative path to the source recipe YAML. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString SourceRecipePath;

	/** Repo-relative path to the manifest that produced this asset. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString ManifestPath;

	/** Name of the generator that stamped provenance (e.g. "worldforge-generate-manifest"). */
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

	/** SHA-256 of the source recipe at generation time; lets validation detect stale provenance. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Provenance")
	FString SourceRecipeHash;

	// --- Linkage (hard references to the produced assets) --------------------

	/** The generated Material Instance this recipe produced. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Linkage")
	TObjectPtr<UMaterialInstanceConstant> MaterialInstance;

	/** Generated textures, keyed by material parameter name (e.g. "BaseColorTexture"). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Linkage")
	TMap<FName, TObjectPtr<UTexture2D>> TextureOutputs;

	/** Scalar parameter values applied to the Material Instance. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WorldForge|Linkage")
	TMap<FName, float> Parameters;
};
