// Copyright Epic Games, Inc. All Rights Reserved.

#include "WFRuntime.h"

#include "Components/SphereComponent.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Kismet/GameplayStatics.h"
#include "TimerManager.h"
#include "EngineUtils.h"
#include "HAL/PlatformMisc.h"

DEFINE_LOG_CATEGORY_STATIC(LogWFRuntime, Display, All);

// ---------------------------------------------------------------------------
// AWFRuntimeObjective
// ---------------------------------------------------------------------------
AWFRuntimeObjective::AWFRuntimeObjective()
{
	PrimaryActorTick.bCanEverTick = false;
	Trigger = CreateDefaultSubobject<USphereComponent>(TEXT("Trigger"));
	Trigger->InitSphereRadius(ReachRadius);
	Trigger->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
	Trigger->SetCollisionResponseToAllChannels(ECR_Overlap);
	RootComponent = Trigger;
}

void AWFRuntimeObjective::BeginPlay()
{
	Super::BeginPlay();
	// Frame-0 proof the objective exists and its BeginPlay ran in this process.
	UE_LOG(LogWFRuntime, Display, TEXT("WF_BEGIN objective_beginplay scenario=%s at=%s"),
		*ScenarioId, *GetActorLocation().ToCompactString());
}

void AWFRuntimeObjective::CompleteObjective()
{
	if (bCompleted)
	{
		return;
	}
	bCompleted = true;
	UE_LOG(LogWFRuntime, Display, TEXT("WF_STATE objective.disabled=1 scenario=%s"), *ScenarioId);

	// Mutate + persist mission state.
	UWFRuntimeSaveGame* Save = Cast<UWFRuntimeSaveGame>(
		UGameplayStatics::CreateSaveGameObject(UWFRuntimeSaveGame::StaticClass()));
	bool bSaved = false;
	if (Save)
	{
		Save->bMissionComplete = true;
		Save->ScenarioId = ScenarioId;
		bSaved = UGameplayStatics::SaveGameToSlot(Save, SaveSlot, 0);
	}
	UE_LOG(LogWFRuntime, Display, TEXT("WF_SAVE saved=%d slot=%s"), bSaved ? 1 : 0, *SaveSlot);

	// Reload-verify from disk in this same process (SaveGameToSlot is synchronous).
	bool bExists = UGameplayStatics::DoesSaveGameExist(SaveSlot, 0);
	bool bVerified = false;
	if (bExists)
	{
		if (UWFRuntimeSaveGame* Loaded = Cast<UWFRuntimeSaveGame>(
				UGameplayStatics::LoadGameFromSlot(SaveSlot, 0)))
		{
			bVerified = Loaded->bMissionComplete;
		}
	}
	UE_LOG(LogWFRuntime, Display, TEXT("WF_VERIFY persisted_%s reloaded_complete=%d"),
		bVerified ? TEXT("true") : TEXT("false"), bVerified ? 1 : 0);

	// Only claim completion when the whole chain genuinely happened.
	if (bSaved && bVerified)
	{
		UE_LOG(LogWFRuntime, Display, TEXT("WF_DONE mission.completed scenario=%s"), *ScenarioId);
	}
	else
	{
		UE_LOG(LogWFRuntime, Warning, TEXT("WF_FAIL completion_chain_broken saved=%d verified=%d"),
			bSaved ? 1 : 0, bVerified ? 1 : 0);
	}

	ScheduleExit();
}

void AWFRuntimeObjective::ScheduleExit()
{
	// Give the log a moment to flush, then request a clean exit so this scenario's
	// process ends on its own — the orchestrator treats a clean exit + markers as
	// the completion signal.
	FTimerHandle Handle;
	GetWorldTimerManager().SetTimer(Handle, []()
	{
		UE_LOG(LogWFRuntime, Display, TEXT("WF_EXIT requesting_graceful_exit"));
		FPlatformMisc::RequestExit(false);
	}, 1.0f, false);
}

// ---------------------------------------------------------------------------
// AWFRuntimeTestPawn
// ---------------------------------------------------------------------------
AWFRuntimeTestPawn::AWFRuntimeTestPawn()
{
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessPlayer = EAutoReceiveInput::Player0;

	// Gravity-free flight: continuous straight-line motion to the objective that
	// does not depend on navmesh (absent in -game) or terrain collision.
	if (UCharacterMovementComponent* Move = GetCharacterMovement())
	{
		Move->GravityScale = 0.f;
		Move->MaxFlySpeed = CruiseSpeed;
		Move->MaxAcceleration = 8192.f;
		Move->BrakingDecelerationFlying = 4096.f;
		Move->DefaultLandMovementMode = MOVE_Flying;
	}
	GetCapsuleComponent()->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
	GetCapsuleComponent()->SetCollisionResponseToAllChannels(ECR_Overlap);
}

void AWFRuntimeTestPawn::BeginPlay()
{
	Super::BeginPlay();
	if (UCharacterMovementComponent* Move = GetCharacterMovement())
	{
		Move->SetMovementMode(MOVE_Flying);
		Move->MaxFlySpeed = CruiseSpeed;
	}
	TravelStartTime = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.f;
	UE_LOG(LogWFRuntime, Display, TEXT("WF_PAWN spawned_possessed controller=%s"),
		GetController() ? TEXT("yes") : TEXT("none"));
}

AWFRuntimeObjective* AWFRuntimeTestPawn::FindObjective()
{
	for (TActorIterator<AWFRuntimeObjective> It(GetWorld()); It; ++It)
	{
		return *It;
	}
	return nullptr;
}

void AWFRuntimeTestPawn::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!Target)
	{
		Target = FindObjective();
		if (!Target)
		{
			return;
		}
		UE_LOG(LogWFRuntime, Display, TEXT("WF_ROUTE route.started toward=%s"),
			*Target->GetActorLocation().ToCompactString());
	}
	if (Target->IsCompleted())
	{
		return;
	}

	const FVector Self = GetActorLocation();
	const FVector Goal = Target->GetActorLocation();
	const FVector Delta = Goal - Self;
	const float Dist = Delta.Size();

	if (Dist <= Target->ReachRadius)
	{
		if (!bLoggedArrival)
		{
			bLoggedArrival = true;
			const float Elapsed = GetWorld()->GetTimeSeconds() - TravelStartTime;
			UE_LOG(LogWFRuntime, Display, TEXT("WF_ROUTE route.completed dist_to_goal=%.1f secs=%.2f"),
				Dist, Elapsed);
		}
		Target->CompleteObjective();
		return;
	}

	// Continuous motion toward the objective (consumed by CharacterMovement).
	AddMovementInput(Delta.GetSafeNormal(), 1.0f);
}
