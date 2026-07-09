// Copyright Epic Games, Inc. All Rights Reserved.

#include "WFRuntime.h"

#include "Components/SphereComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/SceneComponent.h"
#include "GameFramework/PlayerStart.h"
#include "GameFramework/PlayerController.h"
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

// ===========================================================================
// v1.7 NPCForge — AWFNPCPawn + AWFEncounterManager
// ===========================================================================

// ---------------------------------------------------------------------------
// AWFNPCPawn
// ---------------------------------------------------------------------------
AWFNPCPawn::AWFNPCPawn()
{
	PrimaryActorTick.bCanEverTick = true;
	// NPCs are AI sentries — never auto-possessed by the player.
	AutoPossessPlayer = EAutoReceiveInput::Disabled;

	if (UCharacterMovementComponent* M = GetCharacterMovement())
	{
		M->GravityScale = 1.f;                 // grounded: stands on real terrain
		M->DefaultLandMovementMode = MOVE_Walking;
		M->MaxWalkSpeed = 200.f;
	}
	if (UCapsuleComponent* C = GetCapsuleComponent())
	{
		// Collide with the world so it stands on terrain, but IGNORE the Pawn
		// channel so an NPC can NEVER block the player's mission path.
		C->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
		C->SetCollisionProfileName(TEXT("Pawn"));
		C->SetCollisionResponseToChannel(ECC_Pawn, ECR_Ignore);
	}
}

FString AWFNPCPawn::StateName() const
{
	switch (State)
	{
	case EWFNPCState::Idle:       return TEXT("idle");
	case EWFNPCState::Alerted:    return TEXT("alerted");
	case EWFNPCState::Pressuring: return TEXT("pressuring");
	default:                      return TEXT("resolved");
	}
}

void AWFNPCPawn::SetState(EWFNPCState NewState, const TCHAR* Why)
{
	if (State == NewState)
	{
		return;
	}
	const FString From = StateName();
	State = NewState;
	UE_LOG(LogWFRuntime, Display, TEXT("WF_NPC_STATE npc=%s %s->%s why=%s"),
		*InstanceId, *From, *StateName(), Why);
}

void AWFNPCPawn::BeginPlay()
{
	Super::BeginPlay();
	SpawnZ = GetActorLocation().Z;
	UE_LOG(LogWFRuntime, Display,
		TEXT("WF_NPC_INIT npc=%s role=%s at=%s perc=%.0f engage=%.0f pressR=%.0f pressV=%.1f"),
		*InstanceId, *ArchetypeRole, *GetActorLocation().ToCompactString(),
		PerceptionRadius, EngagementRadius, PressureRadius, PressureValue);
}

void AWFNPCPawn::Resolve()
{
	if (State != EWFNPCState::Resolved)
	{
		SetState(EWFNPCState::Resolved, TEXT("mission_complete_or_departed"));
	}
}

void AWFNPCPawn::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (State == EWFNPCState::Resolved)
	{
		return;
	}
	APawn* Player = UGameplayStatics::GetPlayerPawn(GetWorld(), 0);
	if (!Player)
	{
		return;
	}
	const float Dist = FVector::Dist(GetActorLocation(), Player->GetActorLocation());

	// Perception: detect the real, moving player within the perception radius.
	if (Dist <= PerceptionRadius)
	{
		if (!bDetectedPlayer)
		{
			bDetectedPlayer = true;
			UE_LOG(LogWFRuntime, Display, TEXT("WF_NPC_PERCEPT npc=%s detected dist=%.0f"),
				*InstanceId, Dist);
		}
		if (State == EWFNPCState::Idle)
		{
			SetState(EWFNPCState::Alerted, TEXT("player_perceived"));
		}
	}

	// Pressure: genuine per-tick pressure while the player is within range.
	if (Dist <= PressureRadius)
	{
		if (State != EWFNPCState::Pressuring)
		{
			SetState(EWFNPCState::Pressuring, TEXT("player_in_pressure_radius"));
		}
		const float Now = GetWorld()->GetTimeSeconds();
		if (Now - LastPressureTime >= PressureTickInterval)
		{
			LastPressureTime = Now;
			++PressureApplied;
			UE_LOG(LogWFRuntime, Display,
				TEXT("WF_NPC_PRESSURE npc=%s applied=%d value=%.1f dist=%.0f"),
				*InstanceId, PressureApplied, PressureValue, Dist);
		}
	}
	else if (State == EWFNPCState::Pressuring && Dist > DisengagementRadius)
	{
		// Player escaped the disengagement radius — pressure expires.
		UE_LOG(LogWFRuntime, Display, TEXT("WF_NPC_PRESSURE_EXPIRED npc=%s applied=%d"),
			*InstanceId, PressureApplied);
		SetState(EWFNPCState::Alerted, TEXT("player_left_pressure_radius"));
	}
}

// ---------------------------------------------------------------------------
// AWFEncounterManager
// ---------------------------------------------------------------------------
AWFEncounterManager::AWFEncounterManager()
{
	PrimaryActorTick.bCanEverTick = true;
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
}

static int32 WFEnvInt(const TCHAR* Name, int32 Def)
{
	const FString V = FPlatformMisc::GetEnvironmentVariable(Name);
	return V.IsEmpty() ? Def : FCString::Atoi(*V);
}
static float WFEnvFloat(const TCHAR* Name, float Def)
{
	const FString V = FPlatformMisc::GetEnvironmentVariable(Name);
	return V.IsEmpty() ? Def : FCString::Atof(*V);
}
static FString WFEnvStr(const TCHAR* Name, const FString& Def)
{
	const FString V = FPlatformMisc::GetEnvironmentVariable(Name);
	return V.IsEmpty() ? Def : V;
}

void AWFEncounterManager::BeginPlay()
{
	Super::BeginPlay();
	StartTime = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.f;

	// --- per-scenario spec from the environment (set by the batch driver) ---
	ScenarioId = WFEnvStr(TEXT("WF_NPC_SCENARIO_ID"), ScenarioId.IsEmpty() ? TEXT("unknown") : ScenarioId);
	Profile = WFEnvStr(TEXT("WF_NPC_PROFILE"), TEXT("light_pressure"));
	int32 Count = FMath::Max(1, WFEnvInt(TEXT("WF_NPC_COUNT"), DefaultNPCCount));
	const float PressV = WFEnvFloat(TEXT("WF_NPC_PRESSURE_VALUE"), Profile == TEXT("standard_pressure") ? 6.f : 4.f);
	const float PressR = WFEnvFloat(TEXT("WF_NPC_PRESSURE_RADIUS"), Profile == TEXT("standard_pressure") ? 800.f : 600.f);
	const float EngageR = WFEnvFloat(TEXT("WF_NPC_ENGAGE_RADIUS"), 800.f);

	UE_LOG(LogWFRuntime, Display,
		TEXT("WF_NPC_MGR scenario.started scenario=%s profile=%s requested_count=%d"),
		*ScenarioId, *Profile, Count);

	// --- locate the player's route: PlayerStart -> objective --------------
	Objective = nullptr;
	for (TActorIterator<AWFRuntimeObjective> It(GetWorld()); It; ++It) { Objective = *It; break; }
	FVector Start(0, 0, 300.f);
	for (TActorIterator<APlayerStart> It(GetWorld()); It; ++It) { Start = It->GetActorLocation(); break; }
	const FVector Goal = Objective ? Objective->GetActorLocation() : Start + FVector(900, 0, 0);
	const FVector Mid = (Start + Goal) * 0.5f;

	// --- spawn grounded NPC sentries near the route (never on it) ----------
	FActorSpawnParameters SP;
	SP.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	int32 Spawned = 0;
	for (int32 i = 0; i < Count; ++i)
	{
		// Deterministic lateral offsets: along the route, off to the side, so the
		// walking player passes within pressure range but the path stays clear.
		const float Along = (float)i * 150.f - (Count - 1) * 75.f;
		const float Side = 250.f + (float)(i % 3) * 90.f;
		const FVector Loc(Mid.X + Along, Mid.Y + Side, Start.Z + 50.f);
		AWFNPCPawn* N = GetWorld()->SpawnActor<AWFNPCPawn>(AWFNPCPawn::StaticClass(), Loc, FRotator::ZeroRotator, SP);
		if (!N)
		{
			continue;
		}
		N->InstanceId = FString::Printf(TEXT("%s_npc_%d"), *ScenarioId, i);
		N->ArchetypeRole = (i % 2 == 0) ? TEXT("static_guard") : TEXT("ranged_sentry");
		N->EngagementRadius = EngageR;
		N->DisengagementRadius = EngageR + 400.f;
		N->PerceptionRadius = EngageR + 100.f;
		N->PressureRadius = PressR;
		N->PressureValue = PressV;
		NPCs.Add(N);
		++Spawned;
		// Route binding: each NPC is bound to a grounded guard waypoint (its own
		// spawn location) — a grounded_manual_waypoint, never flight/teleport.
		UE_LOG(LogWFRuntime, Display, TEXT("WF_NPC_ROUTE_BOUND npc=%s mode=grounded_manual_waypoint node=%s"),
			*N->InstanceId, *Loc.ToCompactString());
	}
	UE_LOG(LogWFRuntime, Display, TEXT("WF_NPC_SPAWN count=%d requested=%d"), Spawned, Count);
	if (Spawned == 0)
	{
		FinalizeFailure(TEXT("no_npc_spawned"));
	}
}

int32 AWFEncounterManager::TotalPressure() const
{
	int32 T = 0;
	for (const AWFNPCPawn* N : NPCs)
	{
		if (N) { T += N->GetPressureApplied(); }
	}
	return T;
}

void AWFEncounterManager::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (bFinalized)
	{
		return;
	}

	// Encounter-level state transitions, logged once each.
	bool bAnyAlerted = false, bAnyPressuring = false;
	for (const AWFNPCPawn* N : NPCs)
	{
		if (!N) { continue; }
		if (N->DetectedPlayer()) { bAnyAlerted = true; }
		if (N->GetState() == EWFNPCState::Pressuring) { bAnyPressuring = true; }
	}
	if (bAnyAlerted && !bLoggedAlerted)
	{
		bLoggedAlerted = true;
		UE_LOG(LogWFRuntime, Display, TEXT("WF_ENC_STATE idle->alerted scenario=%s"), *ScenarioId);
	}
	if (bAnyPressuring && !bLoggedPressuring)
	{
		bLoggedPressuring = true;
		UE_LOG(LogWFRuntime, Display, TEXT("WF_ENC_STATE alerted->pressuring scenario=%s"), *ScenarioId);
	}

	// Completion: the mission objective is genuinely done AND real pressure fired.
	const bool bMissionDone = Objective && Objective->IsCompleted();
	if (bMissionDone && TotalPressure() >= 1)
	{
		FinalizeCompletion();
		return;
	}

	// Hard lifetime backstop so a process never hangs.
	if (GetWorld()->GetTimeSeconds() - StartTime > MaxLifetimeSeconds)
	{
		if (bMissionDone)
		{
			FinalizeFailure(TEXT("mission_done_but_no_pressure"));
		}
		else
		{
			FinalizeFailure(TEXT("timeout_no_mission_completion"));
		}
	}
}

void AWFEncounterManager::FinalizeCompletion()
{
	if (bFinalized) { return; }
	bFinalized = true;

	// Resolve every NPC and collect its persisted state.
	UWFNPCSaveGame* Save = Cast<UWFNPCSaveGame>(
		UGameplayStatics::CreateSaveGameObject(UWFNPCSaveGame::StaticClass()));
	int32 Total = 0;
	if (Save)
	{
		Save->ScenarioId = ScenarioId;
		for (AWFNPCPawn* N : NPCs)
		{
			if (!N) { continue; }
			N->Resolve();
			FWFNPCStateEntry E;
			E.InstanceId = N->InstanceId;
			E.ArchetypeRole = N->ArchetypeRole;
			E.FinalState = N->StateName();
			E.PressureApplied = N->GetPressureApplied();
			E.bDetectedPlayer = N->DetectedPlayer();
			Total += E.PressureApplied;
			Save->NPCs.Add(E);
		}
		Save->TotalPressureApplied = Total;
	}
	UE_LOG(LogWFRuntime, Display, TEXT("WF_ENC_STATE pressuring->resolved scenario=%s"), *ScenarioId);

	const FString Slot = TEXT("WFNPC_State");
	const bool bSaved = Save && UGameplayStatics::SaveGameToSlot(Save, Slot, 0);
	UE_LOG(LogWFRuntime, Display, TEXT("WF_NPC_SAVE saved=%d slot=%s npcs=%d pressure=%d"),
		bSaved ? 1 : 0, *Slot, Save ? Save->NPCs.Num() : 0, Total);

	// Reload-verify from disk in-process.
	int32 LoadedNPCs = 0, LoadedPressure = 0;
	bool bVerified = false;
	if (bSaved && UGameplayStatics::DoesSaveGameExist(Slot, 0))
	{
		if (UWFNPCSaveGame* L = Cast<UWFNPCSaveGame>(UGameplayStatics::LoadGameFromSlot(Slot, 0)))
		{
			LoadedNPCs = L->NPCs.Num();
			LoadedPressure = L->TotalPressureApplied;
			bVerified = (LoadedNPCs == (Save ? Save->NPCs.Num() : -1)) && LoadedNPCs > 0 && LoadedPressure >= 1;
		}
	}
	UE_LOG(LogWFRuntime, Display, TEXT("WF_NPC_VERIFY persisted_%s npcs=%d pressure=%d"),
		bVerified ? TEXT("true") : TEXT("false"), LoadedNPCs, LoadedPressure);

	if (bSaved && bVerified && Total >= 1)
	{
		UE_LOG(LogWFRuntime, Display,
			TEXT("WF_NPC_DONE scenario.completed scenario=%s npcs=%d pressure=%d"),
			*ScenarioId, LoadedNPCs, Total);
	}
	else
	{
		UE_LOG(LogWFRuntime, Warning,
			TEXT("WF_NPC_FAIL completion_chain_broken saved=%d verified=%d pressure=%d"),
			bSaved ? 1 : 0, bVerified ? 1 : 0, Total);
	}
	// The objective owns the process exit (it schedules a graceful exit on arrival);
	// we do not race it. If the objective is gone, request exit ourselves.
	if (!Objective)
	{
		FTimerHandle H;
		GetWorldTimerManager().SetTimer(H, []() { FPlatformMisc::RequestExit(false); }, 1.0f, false);
	}
}

void AWFEncounterManager::FinalizeFailure(const TCHAR* Why)
{
	if (bFinalized) { return; }
	bFinalized = true;
	UE_LOG(LogWFRuntime, Warning, TEXT("WF_NPC_FAIL %s scenario=%s npcs=%d pressure=%d"),
		Why, *ScenarioId, NPCs.Num(), TotalPressure());
	FTimerHandle H;
	GetWorldTimerManager().SetTimer(H, []() { FPlatformMisc::RequestExit(false); }, 1.0f, false);
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

// ---------------------------------------------------------------------------
// UWFRuntimeAutoSpawnSubsystem — runtime-spawn the actor set on clean maps
// ---------------------------------------------------------------------------
void UWFRuntimeAutoSpawnSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);

	// Only the headless NPC behavior batch sets WF_NPC_SCENARIO_ID (per scenario).
	// Editor, PIE, and normal play never do — so this stays completely inert there.
	const FString ScenarioId = FPlatformMisc::GetEnvironmentVariable(TEXT("WF_NPC_SCENARIO_ID"));
	if (ScenarioId.IsEmpty() || !InWorld.IsGameWorld())
	{
		return;
	}

	// Idempotent: a materialized (baked) map already carries the actor set — leave it
	// exactly as authored so baked/editor-preview maps keep working unchanged.
	for (TActorIterator<AWFEncounterManager> It(&InWorld); It; ++It)
	{
		UE_LOG(LogWFRuntime, Display,
			TEXT("WF_AUTOSPAWN skipped=already_materialized scenario=%s"), *ScenarioId);
		return;
	}

	// Mirror the editor prepare step: locate the PlayerStart, then spawn the objective
	// (+900 X, reach 250), the grounded player pawn (at the start), and the manager.
	FVector Start(0, 0, 300.f);
	for (TActorIterator<APlayerStart> It(&InWorld); It; ++It) { Start = It->GetActorLocation(); break; }

	FActorSpawnParameters SP;
	SP.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

	// Objective FIRST: the pawn and manager find it via TActorIterator in their own
	// BeginPlay, which runs synchronously as each actor is spawned into a live world.
	AWFRuntimeObjective* Obj = InWorld.SpawnActor<AWFRuntimeObjective>(
		AWFRuntimeObjective::StaticClass(), Start + FVector(900.f, 0.f, 0.f), FRotator::ZeroRotator, SP);
	if (Obj)
	{
		Obj->ScenarioId = ScenarioId;
		Obj->ReachRadius = 250.f;
	}

	// Grounded player pawn, explicitly possessed by Player 0 — AutoPossessPlayer is
	// unreliable for a pawn spawned after the world has already begun play.
	AWFGroundedRuntimePawn* Pawn = InWorld.SpawnActor<AWFGroundedRuntimePawn>(
		AWFGroundedRuntimePawn::StaticClass(), Start, FRotator::ZeroRotator, SP);
	if (Pawn)
	{
		if (APlayerController* PC = UGameplayStatics::GetPlayerController(&InWorld, 0))
		{
			PC->Possess(Pawn);
		}
	}

	// Encounter manager (reads the per-scenario NPC spec from the environment in its
	// own BeginPlay, then spawns the grounded sentries).
	AWFEncounterManager* Mgr = InWorld.SpawnActor<AWFEncounterManager>(
		AWFEncounterManager::StaticClass(), Start, FRotator::ZeroRotator, SP);
	if (Mgr)
	{
		Mgr->ScenarioId = ScenarioId;
	}

	UE_LOG(LogWFRuntime, Display,
		TEXT("WF_AUTOSPAWN spawned scenario=%s pawn=%d obj=%d mgr=%d start=%s"),
		*ScenarioId, Pawn ? 1 : 0, Obj ? 1 : 0, Mgr ? 1 : 0, *Start.ToCompactString());
}
