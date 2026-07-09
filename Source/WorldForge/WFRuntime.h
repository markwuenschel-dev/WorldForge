// Copyright Epic Games, Inc. All Rights Reserved.
//
// WorldForge v1.6x — headless runtime-completion classes.
//
// These are the "WF_RuntimeTestPawn" runtime classes the v1.6 plan always
// required. They exist so a scenario can be COMPLETED in a fresh, crash-isolated
// standalone process with no editor, no NeoStack bridge, and — critically — no
// runtime navmesh (standalone `-game` does not build one). The pawn reaches the
// real objective transform by continuous per-tick movement (never a teleport);
// the objective saves + reload-verifies + requests a clean exit so each scenario
// is one short deterministic process the batch orchestrator can drive 120x.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "GameFramework/Actor.h"
#include "GameFramework/SaveGame.h"
#include "WFRuntime.generated.h"

class USphereComponent;

/** Persisted proof object. Save/load of this across a process restart is the
 *  save-load verification the runtime-truth rules demand. */
UCLASS()
class UWFRuntimeSaveGame : public USaveGame
{
	GENERATED_BODY()
public:
	UPROPERTY() bool bMissionComplete = false;
	UPROPERTY() FString ScenarioId;
	UPROPERTY() FString MapId;
};

/** The objective actor. BeginPlay logs WF_BEGIN; when the pawn reaches it the
 *  objective mutates state, saves, reload-verifies, logs mission.completed and
 *  requests a graceful exit. Marker strings are the batch orchestrator's contract. */
UCLASS()
class AWFRuntimeObjective : public AActor
{
	GENERATED_BODY()
public:
	AWFRuntimeObjective();

	/** Radius (uu) within which the pawn is considered to have reached the objective. */
	UPROPERTY(EditAnywhere, Category = "WorldForge") float ReachRadius = 200.f;

	/** Save slot the completion is persisted to. */
	UPROPERTY(EditAnywhere, Category = "WorldForge") FString SaveSlot = TEXT("WFRuntime_Complete");

	UPROPERTY(EditAnywhere, Category = "WorldForge") FString ScenarioId;

	bool IsCompleted() const { return bCompleted; }

	/** Idempotently complete: mutate state, save, verify, log, schedule exit. */
	void CompleteObjective();

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY() USphereComponent* Trigger = nullptr;
	bool bCompleted = false;

	void ScheduleExit();
};

/** v1.6y traversal mode the grounded pawn should attempt. */
UENUM()
enum class EWFGroundMode : uint8
{
	GroundedStraight,  // grounded walking, straight-line AddMovementInput (WorldForce route substrate)
	NavMesh            // AI SimpleMoveToLocation over UE navmesh
};

/** v1.6y grounded pawn. Walks (gravity ON, capsule collision ON, MOVE_Walking)
 *  toward the objective and records genuine grounded evidence — is-on-ground
 *  samples, movement mode, a navmesh path probe, and fall-through detection — so
 *  v1.6y can classify grounded traversal truthfully and NEVER count flight. This
 *  is the Wave-0 viability probe and the grounded runtime driver seed. */
UCLASS()
class AWFGroundedRuntimePawn : public ACharacter
{
	GENERATED_BODY()
public:
	AWFGroundedRuntimePawn();

	UPROPERTY(EditAnywhere, Category = "WorldForge") EWFGroundMode Mode = EWFGroundMode::GroundedStraight;
	UPROPERTY(EditAnywhere, Category = "WorldForge") float MaxWalkSpeedProp = 600.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge") float MaxSlopeDegrees = 44.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge") float MaxStepHeight = 45.f;
	/** If the pawn falls below (spawn Z - this) it is judged to have fallen through
	 *  the world — a truthful failure, never a success. */
	UPROPERTY(EditAnywhere, Category = "WorldForge") float FallThroughDropZ = 2000.f;

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	UPROPERTY() AWFRuntimeObjective* Target = nullptr;
	float StartTime = 0.f;
	float SpawnZ = 0.f;
	float LastSampleTime = -1.f;
	int32 GroundedSamples = 0;
	int32 AirborneSamples = 0;
	bool bLoggedArrival = false;
	bool bNavMoveIssued = false;
	bool bDead = false;

	AWFRuntimeObjective* FindObjective();
	void ProbeNavmesh(const FVector& Goal);
	void ProbeWalkability(const FVector& Goal);  // game-world grid geometry probe
	void RequestGracefulExit(const TCHAR* Why);
};

// ===========================================================================
// v1.7 NPCForge — runtime NPC behavior layer
//
// These classes add genuine, headless NPC behavior ON TOP of the proven v1.6y
// grounded completion. The player pawn (AWFGroundedRuntimePawn) still walks to
// the objective (mission completion preserved); an AWFEncounterManager spawns
// real grounded AWFNPCPawn sentries near the player's path that genuinely
// perceive the moving player, apply real per-tick pressure while in range, run a
// per-NPC state machine, and persist their state across a save+reload — all
// emitting WF_NPC_* / WF_ENC_* markers the batch orchestrator parses. NPCs never
// block the mission path (they ignore the Pawn channel) and never fly or
// teleport, so the honesty invariants the v1.7 contracts enforce hold at runtime.
// ===========================================================================

/** Per-NPC runtime state machine. */
UENUM()
enum class EWFNPCState : uint8
{
	Idle,        // spawned, unaware of the player
	Alerted,     // player detected within perception radius
	Pressuring,  // player within pressure radius — applying pressure ticks
	Resolved     // player left / mission complete — pressure ended
};

/** One NPC's persisted state — the save/load unit. */
USTRUCT()
struct FWFNPCStateEntry
{
	GENERATED_BODY()
	UPROPERTY() FString InstanceId;
	UPROPERTY() FString ArchetypeRole;
	UPROPERTY() FString FinalState;
	UPROPERTY() int32 PressureApplied = 0;
	UPROPERTY() bool bDetectedPlayer = false;
};

/** Persisted NPC roster. Save+reload of this across the completion is the NPC
 *  save/load verification the v1.7 rules demand (distinct slot from the mission
 *  completion save so both are proven independently). */
UCLASS()
class UWFNPCSaveGame : public USaveGame
{
	GENERATED_BODY()
public:
	UPROPERTY() FString ScenarioId;
	UPROPERTY() int32 TotalPressureApplied = 0;
	UPROPERTY() TArray<FWFNPCStateEntry> NPCs;
};

/** A grounded NPC sentry. Gravity + capsule collision ON so it stands on the real
 *  terrain, but it IGNORES the Pawn channel so it can never block the player's
 *  mission path. Each tick it measures its distance to the real player pawn,
 *  detects within its perception radius, and applies genuine per-tick pressure
 *  while the player is within its pressure radius, driving an Idle→Alerted→
 *  Pressuring→Resolved state machine. No flight, no teleport. */
UCLASS()
class AWFNPCPawn : public ACharacter
{
	GENERATED_BODY()
public:
	AWFNPCPawn();

	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") FString InstanceId;
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") FString ArchetypeRole = TEXT("static_guard");
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") float PerceptionRadius = 900.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") float EngagementRadius = 800.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") float DisengagementRadius = 1200.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") float PressureRadius = 600.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") float PressureValue = 4.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") float PressureTickInterval = 0.5f;

	EWFNPCState GetState() const { return State; }
	int32 GetPressureApplied() const { return PressureApplied; }
	bool DetectedPlayer() const { return bDetectedPlayer; }
	FString StateName() const;

	/** Called by the manager when the mission completes / player departs. */
	void Resolve();

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	EWFNPCState State = EWFNPCState::Idle;
	int32 PressureApplied = 0;
	bool bDetectedPlayer = false;
	float LastPressureTime = -1000.f;
	float SpawnZ = 0.f;

	void SetState(EWFNPCState NewState, const TCHAR* Why);
};

/** Placed once per map at prepare time. At BeginPlay it reads the per-scenario
 *  spec from the environment (count/profile/pressure params/scenario id), spawns
 *  that many grounded AWFNPCPawn near the player's route, binds each to a grounded
 *  waypoint, and logs spawn/init/route-bound markers. It ticks the encounter-level
 *  state machine, and — the moment the mission objective is genuinely completed and
 *  at least one real pressure event has fired — persists the NPC roster, reloads +
 *  verifies it, and logs the completion markers. It never fakes: with zero NPCs or
 *  zero pressure it logs a failure instead of a completion. */
UCLASS()
class AWFEncounterManager : public AActor
{
	GENERATED_BODY()
public:
	AWFEncounterManager();

	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") FString ScenarioId;
	/** Fallback NPC count if the environment does not specify one. */
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") int32 DefaultNPCCount = 3;
	/** Hard lifetime cap (s) — if the mission never completes the process still exits. */
	UPROPERTY(EditAnywhere, Category = "WorldForge|NPC") float MaxLifetimeSeconds = 150.f;

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	UPROPERTY() TArray<AWFNPCPawn*> NPCs;
	UPROPERTY() AWFRuntimeObjective* Objective = nullptr;
	float StartTime = 0.f;
	bool bFinalized = false;
	bool bLoggedAlerted = false;
	bool bLoggedPressuring = false;
	FString Profile = TEXT("light_pressure");

	int32 TotalPressure() const;
	void FinalizeCompletion();
	void FinalizeFailure(const TCHAR* Why);
};

/** The controlled pawn. Flies (gravity-free, nav-free) straight toward the single
 *  AWFRuntimeObjective by continuous AddMovementInput every tick — genuine motion
 *  through the world, not a teleport — and triggers completion on arrival. Flight
 *  is the deliberate, disclosed substitute for navmesh walking, which standalone
 *  `-game` cannot provide; it makes completion terrain- and nav-independent so the
 *  full 120-scenario matrix can complete headlessly and deterministically. */
UCLASS()
class AWFRuntimeTestPawn : public ACharacter
{
	GENERATED_BODY()
public:
	AWFRuntimeTestPawn();

	/** Cruise speed (uu/s) of the continuous traversal. */
	UPROPERTY(EditAnywhere, Category = "WorldForge") float CruiseSpeed = 1200.f;

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	UPROPERTY() AWFRuntimeObjective* Target = nullptr;
	float TravelStartTime = 0.f;
	bool bLoggedArrival = false;

	AWFRuntimeObjective* FindObjective();
};
