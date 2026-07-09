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
#include "Subsystems/WorldSubsystem.h"
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

/** v1.8 CombatForge — persisted player combat state (the combat save/load unit).
 *  Distinct slot (WFCombat_State) from the mission (WFRuntime_Complete) and NPC
 *  (WFNPC_State) saves, so combat persistence is proven INDEPENDENTLY of mission
 *  and NPC save/load. */
UCLASS()
class UWFCombatSaveGame : public USaveGame
{
	GENERATED_BODY()
public:
	UPROPERTY() FString ScenarioId;
	UPROPERTY() FString PlayerInstanceId;
	UPROPERTY() float MaxHealth = 0.f;
	UPROPERTY() float CurrentHealth = 0.f;
	UPROPERTY() float DamageTakenTotal = 0.f;
	UPROPERTY() int32 DamageEventsCount = 0;
	UPROPERTY() bool bIsAlive = true;
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

	// --- v1.8 combat: player health (inert unless WF_COMBAT_ENABLED=1) ---------
	/** Apply real combat damage from a source: mutates CurrentHealth (clamped >=0),
	 *  records the event, emits WF_COMBAT_DAMAGE + WF_COMBAT_HEALTH_CHANGED, and
	 *  returns the post-damage health. No-op (returns current health unchanged) when
	 *  combat is disabled or the pawn is already dead. `Amount` logged is the amount
	 *  actually applied, so health_after == health_before - amount exactly. */
	float ApplyCombatDamage(float Amount, const FString& SourceType, const FString& SourceId, const FString& DamageType);
	bool IsCombatEnabled() const { return bCombatEnabled; }
	float GetMaxHealth() const { return MaxHealth; }
	float GetCurrentHealth() const { return CurrentHealth; }
	float GetMinHealth() const { return MinHealth; }
	float GetDamageTakenTotal() const { return DamageTakenTotal; }
	int32 GetDamageEventsCount() const { return DamageEventsCount; }
	bool IsAlive() const { return CurrentHealth > 0.f; }
	FString GetPlayerInstanceId() const { return PlayerInstanceId; }

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

	// v1.8 combat health state (set from the environment when combat is enabled).
	bool bCombatEnabled = false;
	float MaxHealth = 0.f;
	float CurrentHealth = 0.f;
	float MinHealth = 0.f;
	float DamageTakenTotal = 0.f;
	int32 DamageEventsCount = 0;
	FString PlayerInstanceId;

	AWFRuntimeObjective* FindObjective();
	void ProbeNavmesh(const FVector& Goal);
	void ProbeWalkability(const FVector& Goal);  // game-world grid geometry probe
	void RequestGracefulExit(const TCHAR* Why);
	void InitCombatFromEnv();  // v1.8: reads WF_COMBAT_* env, inits health, logs init
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

	// v1.8 combat: when enabled by the manager, each pressure tick also applies real
	// damage to the player pawn (the NPC pressure-to-damage bridge).
	void EnableDamage(float PerTick) { bDealsDamage = true; DamagePerTick = PerTick; }
	int32 GetDamageDealt() const { return DamageDealt; }

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	EWFNPCState State = EWFNPCState::Idle;
	int32 PressureApplied = 0;
	bool bDetectedPlayer = false;
	float LastPressureTime = -1000.f;
	float SpawnZ = 0.f;

	// v1.8 combat bridge
	bool bDealsDamage = false;
	float DamagePerTick = 0.f;
	int32 DamageDealt = 0;

	void SetState(EWFNPCState NewState, const TCHAR* Why);
};

/** v1.8 CombatForge — a grounded damage-over-time hazard zone. While the player
 *  pawn is within its radius it applies real per-tick damage via the pawn's
 *  ApplyCombatDamage, emitting WF_COMBAT_DAMAGE source=hazard. Query-only overlap so
 *  it never blocks the mission path. Spawned by the manager only for combat
 *  scenarios whose source includes hazard. */
UCLASS()
class AWFHazardVolume : public AActor
{
	GENERATED_BODY()
public:
	AWFHazardVolume();

	UPROPERTY(EditAnywhere, Category = "WorldForge|Combat") FString HazardId = TEXT("hazard_0");
	UPROPERTY(EditAnywhere, Category = "WorldForge|Combat") float Radius = 500.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge|Combat") float DamagePerTick = 5.f;
	UPROPERTY(EditAnywhere, Category = "WorldForge|Combat") float TickInterval = 0.5f;

	int32 GetDamageDealt() const { return DamageDealt; }

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	UPROPERTY() USphereComponent* Zone = nullptr;
	float LastTick = -1000.f;
	int32 DamageDealt = 0;
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

	// v1.8 combat layer (active only when WF_COMBAT_ENABLED=1; otherwise a pure v1.7
	// behavior run — this is what keeps the v1.7 + v1.6z regressions green).
	bool bCombatEnabled = false;
	bool bCombatFinalized = false;
	FString CombatSource = TEXT("npc_pressure");
	float PlayerMaxHealth = 100.f;
	UPROPERTY() TArray<AWFHazardVolume*> Hazards;

	int32 TotalPressure() const;
	int32 TotalDamageEvents() const;                 // v1.8: player pawn's damage-event count
	AWFGroundedRuntimePawn* FindPlayerPawn() const;  // v1.8
	void SetupCombat(const FVector& Start, const FVector& Goal);  // v1.8: enable NPC damage + spawn hazards
	void FinalizeCombat(bool bMissionDone);          // v1.8: combat save/verify + WF_COMBAT_DONE
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

/** Headless runtime auto-spawn for the NPC behavior batch.
 *
 *  v1.7 originally required each map to be MATERIALIZED (the runtime actor set baked
 *  into the .umap by the editor prepare step) before the batch could drive it. That
 *  made the committed 120/120 evidence depend on uncommitted map edits — it did not
 *  reproduce from a clean checkout. This subsystem removes that dependency: when the
 *  batch drives a map in standalone `-game` (signalled by the WF_NPC_SCENARIO_ID
 *  environment variable the driver sets per scenario), it spawns the SAME actor set
 *  the editor prepare step would have baked — the grounded player pawn, the mission
 *  objective, and the encounter manager — at world begin-play. Runtime spawn is now
 *  the canonical v1.7 materialization mode; baked editor placement is optional
 *  (editor-preview / v1.7x).
 *
 *  It is deliberately inert everywhere else: it does nothing unless WF_NPC_SCENARIO_ID
 *  is set AND the world is a game world, and it is idempotent — if the map was already
 *  materialized (an AWFEncounterManager already exists) it skips, so baked maps,
 *  the editor, and normal play are entirely unaffected. */
UCLASS()
class UWFRuntimeAutoSpawnSubsystem : public UWorldSubsystem
{
	GENERATED_BODY()
public:
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
};
