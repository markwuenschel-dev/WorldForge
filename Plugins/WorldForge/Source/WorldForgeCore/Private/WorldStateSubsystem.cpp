// Copyright Epic Games, Inc. All Rights Reserved.

#include "WorldStateSubsystem.h"

#include "HAL/IConsoleManager.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Materials/MaterialParameterCollection.h"

DEFINE_LOG_CATEGORY_STATIC(LogWorldForgeState, Log, All);

namespace
{
	// The curated MPC render mirror lives next to the master material so the master
	// can sample it without creating a plugin -> /Game content dependency.
	const TCHAR* GStateCollectionPath = TEXT("/CoreTerrainMaterials/State/MPC_WorldState.MPC_WorldState");

	bool ParseScope(const FString& In, EWorldForgeStateScope& Out)
	{
		if (In.Equals(TEXT("Global"), ESearchCase::IgnoreCase)) { Out = EWorldForgeStateScope::Global; return true; }
		if (In.Equals(TEXT("Region"), ESearchCase::IgnoreCase)) { Out = EWorldForgeStateScope::Region; return true; }
		if (In.Equals(TEXT("Local"), ESearchCase::IgnoreCase)) { Out = EWorldForgeStateScope::Local; return true; }
		if (In.Equals(TEXT("Settlement"), ESearchCase::IgnoreCase)) { Out = EWorldForgeStateScope::Settlement; return true; }
		return false;
	}
}

void UWorldStateSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);

	SetStateCommand = IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("WorldForge.SetState"),
		TEXT("Set a world-state value. Usage: WorldForge.SetState <Global|Region|Local|Settlement> <ContextId> <Key> <Value>"),
		FConsoleCommandWithArgsDelegate::CreateUObject(this, &UWorldStateSubsystem::HandleSetStateCommand),
		ECVF_Default);
}

void UWorldStateSubsystem::Deinitialize()
{
	if (SetStateCommand)
	{
		IConsoleManager::Get().UnregisterConsoleObject(SetStateCommand);
		SetStateCommand = nullptr;
	}

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

void UWorldStateSubsystem::SetStateValue(EWorldForgeStateScope Scope, FName ContextId, FName Key, float Value)
{
	StateStore.Add(FWorldForgeStateAddress(Scope, ContextId, Key), Value);

	// Mirror render-facing values into the MPC. Gameplay-scale state stays in the
	// store only (D10): the MPC is a render-only projection.
	if (GetCuratedMpcParams().Contains(Key))
	{
		PushToMpc(Key, Value);
	}
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

void UWorldStateSubsystem::HandleSetStateCommand(const TArray<FString>& Args)
{
	if (Args.Num() != 4)
	{
		UE_LOG(LogWorldForgeState, Warning,
			TEXT("Usage: WorldForge.SetState <Global|Region|Local|Settlement> <ContextId> <Key> <Value>"));
		return;
	}

	EWorldForgeStateScope Scope;
	if (!ParseScope(Args[0], Scope))
	{
		UE_LOG(LogWorldForgeState, Warning, TEXT("Unknown scope '%s'."), *Args[0]);
		return;
	}

	const FName ContextId = (Args[1].Equals(TEXT("None"), ESearchCase::IgnoreCase)) ? NAME_None : FName(*Args[1]);
	const FName Key = FName(*Args[2]);
	const float Value = FCString::Atof(*Args[3]);

	SetStateValue(Scope, ContextId, Key, Value);

	UE_LOG(LogWorldForgeState, Log, TEXT("SetState %s/%s/%s = %f"),
		*Args[0], *ContextId.ToString(), *Key.ToString(), Value);
}
