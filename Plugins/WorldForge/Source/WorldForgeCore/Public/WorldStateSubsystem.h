// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "WorldForgeStateTypes.h"
#include "WorldStateSubsystem.generated.h"

class UMaterialParameterCollection;
struct IConsoleCommand;

/**
 * UWorldStateSubsystem - the thin StateForge spine (forge_design_decisions D9-D11).
 *
 * Source of truth for adaptive world state. Two roles:
 *  1. CPU pull-query API (GetStateValue) - the canonical interface every forge and
 *     gameplay system binds to. They ALWAYS pull from here; they never read the MPC.
 *  2. A curated render mirror: SetStateValue pushes render-facing keys into
 *     MPC_WorldState so materials can react. Materials read ONLY the MPC mirror.
 *
 * This is intentionally minimal: an in-memory float store plus the read/write
 * contract and one tracer reaction (industrial_pressure -> soot). Accumulation,
 * influence falloff, aggregation, persistence, and emitters layer on top later and
 * all resolve into SetStateValue (D11) - they are NOT part of this spine.
 */
UCLASS()
class WORLDFORGECORE_API UWorldStateSubsystem : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/**
	 * Canonical pull-query. Returns the float value at Scope+ContextId+Key, or
	 * Default if unset. This is the source of truth all CPU consumers bind to.
	 */
	UFUNCTION(BlueprintCallable, BlueprintPure, Category = "WorldForge|State")
	float GetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Default = 0.f) const;

	/**
	 * Authoritative setter. Writes the value into the in-memory store and, if Key is
	 * a curated render-facing value, mirrors it into MPC_WorldState. Higher-level
	 * influence/accumulation systems resolve into this primitive.
	 */
	UFUNCTION(BlueprintCallable, Category = "WorldForge|State")
	void SetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Value);

private:
	/** In-memory store. Spine only: no persistence (D11). */
	TMap<FWorldForgeStateAddress, float> StateStore;

	/** Cached MPC_WorldState render mirror (loaded lazily, may be null in non-content builds). */
	UPROPERTY(Transient)
	TObjectPtr<UMaterialParameterCollection> CachedStateCollection;

	/** Curated render-facing state keys -> MPC scalar parameter names. */
	static const TMap<FName, FName>& GetCuratedMpcParams();

	/** Push a curated value into the MPC mirror (no-op for non-curated keys / missing MPC). */
	void PushToMpc(FName Key, float Value);

	/** Resolve (and cache) the MPC_WorldState asset. */
	UMaterialParameterCollection* GetStateCollection();

	/** Console-driven tracer: `WorldForge.SetState <Scope> <ContextId> <Key> <Value>`. */
	IConsoleCommand* SetStateCommand = nullptr;
	void HandleSetStateCommand(const TArray<FString>& Args);
};
