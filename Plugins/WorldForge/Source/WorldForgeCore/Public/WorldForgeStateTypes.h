// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "WorldForgeStateTypes.generated.h"

/**
 * Scope of a world-state value. Together with a ContextId and Key it forms the
 * address every forge binds to (see forge_design_decisions D10).
 *
 * ContextId by scope:
 *   Global     -> NAME_None
 *   Region     -> RegionId
 *   Local      -> InfluenceFieldId
 *   Settlement -> SettlementId
 */
UENUM(BlueprintType)
enum class EWorldForgeStateScope : uint8
{
	Global     UMETA(DisplayName = "Global"),
	Region     UMETA(DisplayName = "Region"),
	Local      UMETA(DisplayName = "Local"),
	Settlement UMETA(DisplayName = "Settlement"),
};

/**
 * Fully-qualified address of a single float-valued world-state entry:
 * Scope + ContextId + Key. Used as the in-memory store key in
 * UWorldStateSubsystem. Plain (non-reflected) struct - it is an internal map key,
 * not a Blueprint type.
 */
struct FWorldForgeStateAddress
{
	EWorldForgeStateScope Scope = EWorldForgeStateScope::Global;
	FName ContextId = NAME_None;
	FName Key = NAME_None;

	FWorldForgeStateAddress() = default;

	FWorldForgeStateAddress(EWorldForgeStateScope InScope, FName InContextId, FName InKey)
		: Scope(InScope), ContextId(InContextId), Key(InKey)
	{
	}

	bool operator==(const FWorldForgeStateAddress& Other) const
	{
		return Scope == Other.Scope && ContextId == Other.ContextId && Key == Other.Key;
	}
};

FORCEINLINE uint32 GetTypeHash(const FWorldForgeStateAddress& Address)
{
	return HashCombine(
		HashCombine(GetTypeHash(static_cast<uint8>(Address.Scope)), GetTypeHash(Address.ContextId)),
		GetTypeHash(Address.Key));
}
