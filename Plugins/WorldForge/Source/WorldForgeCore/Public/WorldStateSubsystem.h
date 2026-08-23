// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "WorldForgeStateTypes.h"
#include "WorldStateSubsystem.generated.h"

class UMaterialParameterCollection;
class UWorldStateSubsystem;
class FWorldForgeStateWriteLease;

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
 * contract and a curated render mirror. Accumulation, influence falloff,
 * aggregation, persistence, and emitters layer on top later and all resolve into
 * the native write contract - they are NOT part of this spine.
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
	 * Native-only generic write. Unreserved addresses accept this write; a reserved
	 * address can be written only by its matching native lease.
	 */
	bool SetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Value);

	/**
	 * Reserves one exact address and returns its opaque native write lease. An
	 * already-reserved address returns an invalid lease.
	 */
	FWorldForgeStateWriteLease ReserveStateAddress(EWorldForgeStateScope Scope, FName ContextId, FName Key);

	/**
	 * Writes a reserved address only when Lease was issued by this subsystem for
	 * that exact address and remains active.
	 */
	bool SetStateValueWithLease(
		const FWorldForgeStateWriteLease& Lease,
		EWorldForgeStateScope Scope,
		FName ContextId,
		FName Key,
		float Value);

	/** Releases the exact reservation represented by Lease and invalidates it. */
	bool ReleaseStateAddress(FWorldForgeStateWriteLease& Lease);

private:
	friend class FWorldForgeStateWriteLease;

	/** In-memory store. Spine only: no persistence (D11). */
	TMap<FWorldForgeStateAddress, float> StateStore;

	/** Active native write reservations, keyed by their exact state address. */
	TMap<FWorldForgeStateAddress, FGuid> StateWriteReservations;

	/** Cached MPC_WorldState render mirror (loaded lazily, may be null in non-content builds). */
	UPROPERTY(Transient)
	TObjectPtr<UMaterialParameterCollection> CachedStateCollection;

	/** Curated render-facing state keys -> MPC scalar parameter names. */
	static const TMap<FName, FName>& GetCuratedMpcParams();

	/** Push a curated value into the MPC mirror (no-op for non-curated keys / missing MPC). */
	void PushToMpc(FName Key, float Value);

	/** Resolve (and cache) the MPC_WorldState asset. */
	UMaterialParameterCollection* GetStateCollection();

	/** Validates that Lease is the active reservation for Address in this world. */
	bool IsMatchingLease(const FWorldForgeStateWriteLease& Lease, const FWorldForgeStateAddress& Address) const;

	/** Allows the opaque lease to expose active validity without exposing its token. */
	bool IsLeaseActive(const FWorldForgeStateWriteLease& Lease) const;

	/** Stores a validated write and mirrors a curated render-facing key. */
	void WriteStateValue(const FWorldForgeStateAddress& Address, float Value);
};

/**
 * Opaque, move-only native capability for one reserved world-state address.
 *
 * The subsystem remains the authority: this type exposes no address or token and
 * checks its active reservation with the issuing subsystem on every use.
 */
class WORLDFORGECORE_API FWorldForgeStateWriteLease final
{
public:
	FWorldForgeStateWriteLease() = default;
	FWorldForgeStateWriteLease(const FWorldForgeStateWriteLease&) = delete;
	FWorldForgeStateWriteLease& operator=(const FWorldForgeStateWriteLease&) = delete;
	FWorldForgeStateWriteLease(FWorldForgeStateWriteLease&& Other) noexcept;
	FWorldForgeStateWriteLease& operator=(FWorldForgeStateWriteLease&&) = delete;
	~FWorldForgeStateWriteLease();

	/** Returns true only while the issuing subsystem still owns this reservation. */
	bool IsValid() const;

private:
	friend class UWorldStateSubsystem;

	FWorldForgeStateWriteLease(
		UWorldStateSubsystem* InOwningSubsystem,
		const FWorldForgeStateAddress& InAddress,
		const FGuid& InLeaseId);

	void Invalidate();

	TWeakObjectPtr<UWorldStateSubsystem> OwningSubsystem;
	FWorldForgeStateAddress Address;
	FGuid LeaseId;
};
