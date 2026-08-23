// Copyright Epic Games, Inc. All Rights Reserved.

#include "WorldStateSubsystem.h"

#include "Kismet/KismetMaterialLibrary.h"
#include "Materials/MaterialParameterCollection.h"

DEFINE_LOG_CATEGORY_STATIC(LogWorldForgeState, Log, All);

namespace
{
	// The curated MPC render mirror lives next to the master material so the master
	// can sample it without creating a plugin -> /Game content dependency.
	const TCHAR* GStateCollectionPath = TEXT("/CoreTerrainMaterials/State/MPC_WorldState.MPC_WorldState");
}

void UWorldStateSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
}

void UWorldStateSubsystem::Deinitialize()
{
	StateWriteReservations.Reset();
	StateStore.Reset();
	CachedStateCollection = nullptr;

	Super::Deinitialize();
}

float UWorldStateSubsystem::GetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Default) const
{
	if (const float* Found = StateStore.Find(FWorldForgeStateAddress(Scope, ContextId, Key)))
	{
		return *Found;
	}
	return Default;
}

bool UWorldStateSubsystem::SetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Value)
{
	const FWorldForgeStateAddress Address(Scope, ContextId, Key);
	if (StateWriteReservations.Contains(Address))
	{
		return false;
	}

	WriteStateValue(Address, Value);
	return true;
}

FWorldForgeStateWriteLease UWorldStateSubsystem::ReserveStateAddress(
	EWorldForgeStateScope Scope,
	FName ContextId,
	FName Key)
{
	const FWorldForgeStateAddress Address(Scope, ContextId, Key);
	if (StateWriteReservations.Contains(Address))
	{
		return FWorldForgeStateWriteLease();
	}

	const FGuid LeaseId = FGuid::NewGuid();
	StateWriteReservations.Add(Address, LeaseId);
	return FWorldForgeStateWriteLease(this, Address, LeaseId);
}

bool UWorldStateSubsystem::SetStateValueWithLease(
	const FWorldForgeStateWriteLease& Lease,
	EWorldForgeStateScope Scope,
	FName ContextId,
	FName Key,
	float Value)
{
	const FWorldForgeStateAddress Address(Scope, ContextId, Key);
	if (!IsMatchingLease(Lease, Address))
	{
		return false;
	}

	WriteStateValue(Address, Value);
	return true;
}

bool UWorldStateSubsystem::ReleaseStateAddress(FWorldForgeStateWriteLease& Lease)
{
	if (!IsLeaseActive(Lease))
	{
		return false;
	}

	StateWriteReservations.Remove(Lease.Address);
	Lease.Invalidate();
	return true;
}

bool UWorldStateSubsystem::IsMatchingLease(
	const FWorldForgeStateWriteLease& Lease,
	const FWorldForgeStateAddress& Address) const
{
	if (Lease.OwningSubsystem.Get() != this || !(Lease.Address == Address) || !Lease.LeaseId.IsValid())
	{
		return false;
	}

	const FGuid* ActiveLeaseId = StateWriteReservations.Find(Address);
	return ActiveLeaseId && *ActiveLeaseId == Lease.LeaseId;
}

bool UWorldStateSubsystem::IsLeaseActive(const FWorldForgeStateWriteLease& Lease) const
{
	return IsMatchingLease(Lease, Lease.Address);
}

void UWorldStateSubsystem::WriteStateValue(const FWorldForgeStateAddress& Address, float Value)
{
	StateStore.Add(Address, Value);

	// Mirror render-facing values into the MPC. Gameplay-scale state stays in the
	// store only (D10): the MPC is a render-only projection.
	if (GetCuratedMpcParams().Contains(Address.Key))
	{
		PushToMpc(Address.Key, Value);
	}
}

FWorldForgeStateWriteLease::FWorldForgeStateWriteLease(
	UWorldStateSubsystem* InOwningSubsystem,
	const FWorldForgeStateAddress& InAddress,
	const FGuid& InLeaseId)
	: OwningSubsystem(InOwningSubsystem)
	, Address(InAddress)
	, LeaseId(InLeaseId)
{
}

FWorldForgeStateWriteLease::FWorldForgeStateWriteLease(FWorldForgeStateWriteLease&& Other) noexcept
	: OwningSubsystem(Other.OwningSubsystem)
	, Address(Other.Address)
	, LeaseId(Other.LeaseId)
{
	Other.Invalidate();
}

FWorldForgeStateWriteLease::~FWorldForgeStateWriteLease()
{
	if (UWorldStateSubsystem* StateSubsystem = OwningSubsystem.Get())
	{
		StateSubsystem->ReleaseStateAddress(*this);
	}
}

bool FWorldForgeStateWriteLease::IsValid() const
{
	const UWorldStateSubsystem* StateSubsystem = OwningSubsystem.Get();
	return StateSubsystem && StateSubsystem->IsLeaseActive(*this);
}

void FWorldForgeStateWriteLease::Invalidate()
{
	OwningSubsystem.Reset();
	Address = FWorldForgeStateAddress();
	LeaseId = FGuid();
}

const TMap<FName, FName>& UWorldStateSubsystem::GetCuratedMpcParams()
{
	// state Key -> MPC scalar parameter name. Keep in sync with MPC_WorldState
	// (created by tools/unreal/create_world_state_mpc.py) and the master material's
	// MPC samplers. FactionTint is a vector param, out of scope for the scalar spine.
	static const TMap<FName, FName> CuratedParams = {
		{ FName("industrial_pressure"), FName("IndustrialPressure") },
		{ FName("corruption_level"),    FName("CorruptionLevel") },
		{ FName("restoration_level"),   FName("RestorationLevel") },
		{ FName("wetness"),             FName("Wetness") },
		{ FName("ashfall"),             FName("Ashfall") },
	};
	return CuratedParams;
}

UMaterialParameterCollection* UWorldStateSubsystem::GetStateCollection()
{
	if (!CachedStateCollection)
	{
		CachedStateCollection = LoadObject<UMaterialParameterCollection>(nullptr, GStateCollectionPath);
		if (!CachedStateCollection)
		{
			UE_LOG(LogWorldForgeState, Warning,
				TEXT("MPC_WorldState not found at %s - render mirror disabled. Run create_world_state_mpc.py."),
				GStateCollectionPath);
		}
	}
	return CachedStateCollection;
}

void UWorldStateSubsystem::PushToMpc(FName Key, float Value)
{
	const FName* ParamName = GetCuratedMpcParams().Find(Key);
	if (!ParamName)
	{
		return;
	}

	UMaterialParameterCollection* Collection = GetStateCollection();
	if (!Collection)
	{
		return;
	}

	UKismetMaterialLibrary::SetScalarParameterValue(this, Collection, *ParamName, Value);
	UE_LOG(LogWorldForgeState, Verbose, TEXT("MPC mirror: %s = %f"), *ParamName->ToString(), Value);
}
