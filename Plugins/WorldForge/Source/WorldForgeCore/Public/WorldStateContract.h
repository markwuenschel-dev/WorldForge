// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "WorldStateContract.generated.h"

/**
 * A single adaptive world-state contract entry.
 *
 * Contracts are the stable interface between WorldForge tooling output and
 * whatever game consumes it. They must stay game-agnostic: describe *capabilities*
 * and *parameters* (e.g. "biome.temperature"), never specific lore, factions,
 * or quests. This keeps generated data forward-compatible and agent-safe.
 */
USTRUCT(BlueprintType)
struct WORLDFORGECORE_API FWorldForgeStateContract
{
	GENERATED_BODY()

	/** Stable identifier for this contract (e.g. "biome.temperature"). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WorldForge")
	FName Key;

	/** Schema version, so generated data can evolve without breaking consumers. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WorldForge")
	int32 Version = 1;

	/** Human- and agent-readable description of what this contract guarantees. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WorldForge")
	FString Description;
};
