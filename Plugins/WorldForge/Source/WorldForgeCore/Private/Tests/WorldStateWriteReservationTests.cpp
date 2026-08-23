// Copyright Epic Games, Inc. All Rights Reserved.

#include "Misc/AutomationTest.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "WorldStateSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FWorldForgeStateWriteReservationTest,
	"WorldForge.Core.WorldState.WriteReservations",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FWorldForgeStateWriteReservationTest::RunTest(const FString& /*Parameters*/)
{
	UWorld* PrimaryWorld = UWorld::CreateWorld(EWorldType::Game, false, TEXT("WorldForgeStateLeasePrimary"));
	UWorld* SecondaryWorld = UWorld::CreateWorld(EWorldType::Game, false, TEXT("WorldForgeStateLeaseSecondary"));
	if (!TestNotNull(TEXT("primary game world is available"), PrimaryWorld)
		|| !TestNotNull(TEXT("secondary game world is available"), SecondaryWorld))
	{
		if (PrimaryWorld)
		{
			PrimaryWorld->DestroyWorld(false);
		}
		if (SecondaryWorld)
		{
			SecondaryWorld->DestroyWorld(false);
		}
		return false;
	}

	UWorldStateSubsystem* State = PrimaryWorld->GetSubsystem<UWorldStateSubsystem>();
	UWorldStateSubsystem* SecondaryState = SecondaryWorld->GetSubsystem<UWorldStateSubsystem>();
	if (!TestNotNull(TEXT("primary state subsystem is initialized"), State)
		|| !TestNotNull(TEXT("secondary state subsystem is initialized"), SecondaryState))
	{
		PrimaryWorld->DestroyWorld(false);
		SecondaryWorld->DestroyWorld(false);
		return false;
	}

	const EWorldForgeStateScope Scope = EWorldForgeStateScope::Region;
	const FName AddressAContext(TEXT("test-context-alpha"));
	const FName AddressAKey(TEXT("test-key-alpha"));
	const FName AddressBContext(TEXT("test-context-beta"));
	const FName AddressBKey(TEXT("test-key-beta"));

	TestNull(TEXT("two initialized worlds do not register a process-global state console route"),
		IConsoleManager::Get().FindConsoleObject(TEXT("WorldForge.SetState")));

	TestTrue(TEXT("unreserved address accepts a generic native write"),
		State->SetStateValue(Scope, AddressAContext, AddressAKey, 0.25f));
	TestEqual(TEXT("unreserved write remains readable"),
		State->GetStateValue(Scope, AddressAContext, AddressAKey), 0.25f);

	FWorldForgeStateWriteLease LeaseA = State->ReserveStateAddress(Scope, AddressAContext, AddressAKey);
	TestTrue(TEXT("first reservation returns an opaque native lease"), LeaseA.IsValid());
	FWorldForgeStateWriteLease ActiveLeaseA(MoveTemp(LeaseA));
	TestFalse(TEXT("moved-from lease loses write authority"), LeaseA.IsValid());
	TestTrue(TEXT("moved lease retains write authority"), ActiveLeaseA.IsValid());
	TestFalse(TEXT("duplicate reservation is rejected"),
		State->ReserveStateAddress(Scope, AddressAContext, AddressAKey).IsValid());
	TestFalse(TEXT("generic write cannot mutate a reserved address"),
		State->SetStateValue(Scope, AddressAContext, AddressAKey, 0.50f));
	TestEqual(TEXT("rejected generic write preserves the reserved value"),
		State->GetStateValue(Scope, AddressAContext, AddressAKey), 0.25f);

	FWorldForgeStateWriteLease ForgedLease;
	TestFalse(TEXT("default or forged lease cannot write a reserved address"),
		State->SetStateValueWithLease(ForgedLease, Scope, AddressAContext, AddressAKey, 0.50f));

	FWorldForgeStateWriteLease LeaseB = State->ReserveStateAddress(Scope, AddressBContext, AddressBKey);
	TestTrue(TEXT("second address reserves independently"), LeaseB.IsValid());
	TestFalse(TEXT("lease for a different address cannot write the first address"),
		State->SetStateValueWithLease(LeaseB, Scope, AddressAContext, AddressAKey, 0.50f));
	{
		const FName ScopedContext(TEXT("test-context-scope"));
		const FName ScopedKey(TEXT("test-key-scope"));
		FWorldForgeStateWriteLease ScopedLease = State->ReserveStateAddress(Scope, ScopedContext, ScopedKey);
		TestTrue(TEXT("scoped lease is active before destruction"), ScopedLease.IsValid());
	}
	TestTrue(TEXT("lease destruction releases its reservation"),
		State->SetStateValue(Scope, FName(TEXT("test-context-scope")), FName(TEXT("test-key-scope")), 0.10f));

	FWorldForgeStateWriteLease SecondaryLease = SecondaryState->ReserveStateAddress(Scope, AddressAContext, AddressAKey);
	TestTrue(TEXT("second world can issue an independent native lease"), SecondaryLease.IsValid());
	TestFalse(TEXT("lease issued by another world cannot write this world's address"),
		State->SetStateValueWithLease(SecondaryLease, Scope, AddressAContext, AddressAKey, 0.50f));
	TestTrue(TEXT("matching lease writes its reserved address"),
		State->SetStateValueWithLease(ActiveLeaseA, Scope, AddressAContext, AddressAKey, 0.50f));
	TestEqual(TEXT("matching lease write is readable"),
		State->GetStateValue(Scope, AddressAContext, AddressAKey), 0.50f);

	TestTrue(TEXT("matching lease releases its address"), State->ReleaseStateAddress(ActiveLeaseA));
	TestFalse(TEXT("released lease cannot write again"),
		State->SetStateValueWithLease(ActiveLeaseA, Scope, AddressAContext, AddressAKey, 0.75f));
	TestTrue(TEXT("released address accepts a generic native write again"),
		State->SetStateValue(Scope, AddressAContext, AddressAKey, 0.75f));

	TestNull(TEXT("generic setter is not reflected for Blueprint callers"),
		UWorldStateSubsystem::StaticClass()->FindFunctionByName(TEXT("SetStateValue")));
	TestNull(TEXT("reservation acquisition is not reflected for Blueprint callers"),
		UWorldStateSubsystem::StaticClass()->FindFunctionByName(TEXT("ReserveStateAddress")));
	TestNull(TEXT("lease writes are not reflected for Blueprint callers"),
		UWorldStateSubsystem::StaticClass()->FindFunctionByName(TEXT("SetStateValueWithLease")));
	TestNull(TEXT("reservation release is not reflected for Blueprint callers"),
		UWorldStateSubsystem::StaticClass()->FindFunctionByName(TEXT("ReleaseStateAddress")));

	SecondaryWorld->DestroyWorld(false);
	SecondaryWorld = nullptr;
	TestFalse(TEXT("world deinitialization invalidates outstanding leases"), SecondaryLease.IsValid());

	PrimaryWorld->DestroyWorld(false);

	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
