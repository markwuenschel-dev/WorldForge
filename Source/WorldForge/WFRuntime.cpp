// Copyright Epic Games, Inc. All Rights Reserved.

#include "WFRuntime.h"

#include "Components/SphereComponent.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Kismet/GameplayStatics.h"
#include "TimerManager.h"
#include "EngineUtils.h"
#include "HAL/PlatformMisc.h"
#include "NavigationSystem.h"
#include "NavigationPath.h"
#include "Blueprint/AIBlueprintHelperLibrary.h"

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

// ---------------------------------------------------------------------------
// AWFGroundedRuntimePawn — v1.6y grounded traversal viability + driver seed
// ---------------------------------------------------------------------------
AWFGroundedRuntimePawn::AWFGroundedRuntimePawn()
{
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessPlayer = EAutoReceiveInput::Player0;

	if (UCharacterMovementComponent* M = GetCharacterMovement())
	{
		M->GravityScale = 1.f;                       // grounded: gravity ON
		M->DefaultLandMovementMode = MOVE_Walking;
		M->MaxWalkSpeed = MaxWalkSpeedProp;
		M->MaxStepHeight = MaxStepHeight;
		M->SetWalkableFloorAngle(MaxSlopeDegrees);
	}
	// Capsule collides with the world so the pawn actually stands on terrain.
	if (UCapsuleComponent* C = GetCapsuleComponent())
	{
		C->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
		C->SetCollisionProfileName(TEXT("Pawn"));
	}
}

AWFRuntimeObjective* AWFGroundedRuntimePawn::FindObjective()
{
	for (TActorIterator<AWFRuntimeObjective> It(GetWorld()); It; ++It)
	{
		return *It;
	}
	return nullptr;
}

void AWFGroundedRuntimePawn::ProbeNavmesh(const FVector& Goal)
{
	// Honest navmesh classification: is there a nav system, and does a real
	// (non-partial) path from the pawn to the objective exist at runtime?
	UNavigationSystemV1* Nav = UNavigationSystemV1::GetCurrent(GetWorld());
	if (!Nav)
	{
		UE_LOG(LogWFRuntime, Display, TEXT("WF_GNAV navmesh_present=0 path_exists=0 reason=no_nav_system"));
		return;
	}
	UNavigationPath* Path = Nav->FindPathToLocationSynchronously(GetWorld(), GetActorLocation(), Goal, this);
	const bool bValid = Path && Path->IsValid();
	const bool bPartial = Path && Path->IsPartial();
	const bool bPathExists = bValid && !bPartial;
	const float Len = bValid ? Path->GetPathLength() : 0.f;
	const int32 Pts = bValid ? Path->PathPoints.Num() : 0;
	UE_LOG(LogWFRuntime, Display,
		TEXT("WF_GNAV navmesh_present=1 path_exists=%d partial=%d length=%.1f points=%d"),
		bPathExists ? 1 : 0, bPartial ? 1 : 0, Len, Pts);
}

void AWFGroundedRuntimePawn::RequestGracefulExit(const TCHAR* Why)
{
	UE_LOG(LogWFRuntime, Display, TEXT("WF_GEXIT %s"), Why);
	FTimerHandle H;
	GetWorldTimerManager().SetTimer(H, []() { FPlatformMisc::RequestExit(false); }, 1.0f, false);
}

void AWFGroundedRuntimePawn::BeginPlay()
{
	Super::BeginPlay();
	if (UCharacterMovementComponent* M = GetCharacterMovement())
	{
		M->SetMovementMode(MOVE_Walking);
		M->MaxWalkSpeed = MaxWalkSpeedProp;
	}
	StartTime = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.f;
	SpawnZ = GetActorLocation().Z;
	AWFRuntimeObjective* Obj = FindObjective();
	const FVector Goal = Obj ? Obj->GetActorLocation() : GetActorLocation();
	UE_LOG(LogWFRuntime, Display,
		TEXT("WF_GBEGIN grounded_pawn controller=%s mode=%s spawnZ=%.0f gravity=%.1f"),
		GetController() ? TEXT("yes") : TEXT("none"),
		Mode == EWFGroundMode::NavMesh ? TEXT("navmesh") : TEXT("grounded_straight"),
		SpawnZ, GetCharacterMovement() ? GetCharacterMovement()->GravityScale : -1.f);
	ProbeNavmesh(Goal);
	ProbeWalkability(Goal);
}

void AWFGroundedRuntimePawn::ProbeWalkability(const FVector& Goal)
{
	// Deep walkability from the REAL game-world collision the pawn falls onto:
	// a grid of downward complex traces -> slope (from impact normal), step
	// discontinuities between neighbours, and head clearance; plus spawn /
	// objective / corridor walkability. Emitted as one WF_WALK line the
	// analyzer parses into a WalkabilityReport.
	UWorld* W = GetWorld();
	if (!W) { return; }
	const FVector Ctr = GetActorLocation();
	const float Extent = 1500.f, Step = 250.f, MaxSlope = 44.f, MaxStepH = 45.f;
	const int32 N = (int32)(Extent / Step);
	FCollisionQueryParams Q;
	Q.bTraceComplex = true;
	Q.AddIgnoredActor(this);

	auto TraceDown = [&](float X, float Y, float& OutZ, float& OutSlopeDeg) -> bool
	{
		FHitResult H;
		const FVector S(X, Y, Ctr.Z + 1000.f), E(X, Y, Ctr.Z - 3000.f);
		if (!W->LineTraceSingleByChannel(H, S, E, ECC_Visibility, Q)) { return false; }
		OutZ = H.ImpactPoint.Z;
		OutSlopeDeg = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(H.ImpactNormal.Z, -1.f, 1.f)));
		return true;
	};
	auto HeadClear = [&](float X, float Y, float GZ) -> bool
	{
		FHitResult H;
		const FVector S(X, Y, GZ + MaxStepH + 5.f), E(X, Y, GZ + 176.f);
		return W->LineTraceSingleByChannel(H, S, E, ECC_Visibility, Q);  // blocked = clearance fail
	};

	int32 Checked = 0, Walk = 0, Blocked = 0, Unknown = 0, SlopeF = 0, StepF = 0, ClearF = 0;
	TMap<int64, float> GridZ;
	for (int32 ix = -N; ix <= N; ++ix)
	{
		for (int32 iy = -N; iy <= N; ++iy)
		{
			++Checked;
			float Z = 0.f, Sl = 0.f;
			if (!TraceDown(Ctr.X + ix * Step, Ctr.Y + iy * Step, Z, Sl)) { ++Unknown; continue; }
			GridZ.Add((int64)ix * 100000 + iy, Z);
			if (Sl > MaxSlope) { ++Blocked; ++SlopeF; continue; }
			++Walk;
			if (HeadClear(Ctr.X + ix * Step, Ctr.Y + iy * Step, Z)) { ++ClearF; }
		}
	}
	for (const TPair<int64, float>& It : GridZ)
	{
		const int64 K = It.Key;
		for (int64 D : {(int64)100000, (int64)1})
		{
			const float* Nb = GridZ.Find(K + D);
			if (Nb && FMath::Abs(It.Value - *Nb) > MaxStepH * 2.f) { ++StepF; }
		}
	}
	auto WalkAt = [&](float X, float Y) -> bool
	{
		float Z = 0.f, Sl = 0.f;
		return TraceDown(X, Y, Z, Sl) && Sl <= MaxSlope;
	};
	const bool SpawnW = WalkAt(Ctr.X, Ctr.Y);
	const bool ObjW = WalkAt(Goal.X, Goal.Y);
	const bool Corridor = WalkAt(FMath::Lerp(Ctr.X, Goal.X, 0.25f), Ctr.Y)
		&& WalkAt(FMath::Lerp(Ctr.X, Goal.X, 0.5f), Ctr.Y)
		&& WalkAt(FMath::Lerp(Ctr.X, Goal.X, 0.75f), Ctr.Y);

	UE_LOG(LogWFRuntime, Display,
		TEXT("WF_WALK checked=%d walkable=%d blocked=%d unknown=%d slopeF=%d stepF=%d clearF=%d ")
		TEXT("spawnW=%d objW=%d corridorW=%d"),
		Checked, Walk, Blocked, Unknown, SlopeF, StepF, ClearF,
		SpawnW ? 1 : 0, ObjW ? 1 : 0, Corridor ? 1 : 0);
}

void AWFGroundedRuntimePawn::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (bDead)
	{
		return;
	}
	if (!Target)
	{
		Target = FindObjective();
		if (!Target)
		{
			return;
		}
		UE_LOG(LogWFRuntime, Display, TEXT("WF_GROUTE route.started toward=%s"),
			*Target->GetActorLocation().ToCompactString());
	}
	if (Target->IsCompleted())
	{
		return;
	}

	const FVector Self = GetActorLocation();
	const FVector Goal = Target->GetActorLocation();

	if (Self.Z < SpawnZ - FallThroughDropZ)
	{
		UE_LOG(LogWFRuntime, Warning,
			TEXT("WF_GFALL fell_through_world z=%.0f spawnZ=%.0f grounded_samples=%d airborne=%d"),
			Self.Z, SpawnZ, GroundedSamples, AirborneSamples);
		bDead = true;
		RequestGracefulExit(TEXT("fell_through_world"));
		return;
	}

	UCharacterMovementComponent* M = GetCharacterMovement();
	const bool bOnGround = M && M->IsMovingOnGround();
	const float Now = GetWorld()->GetTimeSeconds();
	if (Now - LastSampleTime >= 0.5f)
	{
		LastSampleTime = Now;
		(bOnGround ? GroundedSamples : AirborneSamples)++;
		UE_LOG(LogWFRuntime, Display, TEXT("WF_GROUND grounded=%d z=%.0f mode=%d speed=%.0f"),
			bOnGround ? 1 : 0, Self.Z, M ? (int32)M->MovementMode.GetValue() : -1,
			M ? M->Velocity.Size() : 0.f);
	}

	const FVector2D SelfXY(Self.X, Self.Y);
	const FVector2D GoalXY(Goal.X, Goal.Y);
	const float DistXY = FVector2D::Distance(SelfXY, GoalXY);

	if (DistXY <= Target->ReachRadius)
	{
		if (!bLoggedArrival)
		{
			bLoggedArrival = true;
			UE_LOG(LogWFRuntime, Display,
				TEXT("WF_GARRIVE grounded=%d distXY=%.1f secs=%.2f grounded_samples=%d airborne=%d"),
				bOnGround ? 1 : 0, DistXY, Now - StartTime, GroundedSamples, AirborneSamples);
		}
		if (bOnGround)
		{
			Target->CompleteObjective();  // grounded success
		}
		else if (Now - StartTime > 3.f)
		{
			UE_LOG(LogWFRuntime, Warning, TEXT("WF_GFAIL arrived_airborne not_grounded_at_objective"));
			bDead = true;
			RequestGracefulExit(TEXT("arrived_airborne"));
		}
		return;
	}

	if (Mode == EWFGroundMode::NavMesh)
	{
		if (!bNavMoveIssued && GetController())
		{
			bNavMoveIssued = true;
			UAIBlueprintHelperLibrary::SimpleMoveToLocation(GetController(), Goal);
			UE_LOG(LogWFRuntime, Display, TEXT("WF_GNAVMOVE SimpleMoveToLocation issued"));
		}
	}
	else
	{
		// Grounded straight-line: horizontal input; CharacterMovement handles
		// floor following, step-up and slope walking.
		const FVector Dir = (FVector(GoalXY.X, GoalXY.Y, Self.Z) - Self).GetSafeNormal();
		AddMovementInput(Dir, 1.0f);
	}
}
